#!/usr/bin/env python3
"""
LIVE SHADOW CONTINUOUS MONITOR
Runs 15-min polling loops during market hours.
"""

import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
import subprocess

WORKSPACE = "/Users/laxman_2026_mac_mini/.openclaw/workspace"
JSONL_FILE = f"{WORKSPACE}/state/orderflow/bookmap_api/es_orderflow_2026-05-12.jsonl"
REPORTS_DIR = f"{WORKSPACE}/reports"
EXPORTS_DIR = f"{WORKSPACE}/exports"

def ensure_dirs():
    Path(REPORTS_DIR).mkdir(exist_ok=True)
    Path(EXPORTS_DIR).mkdir(exist_ok=True)

def run_monitor_snapshot():
    """Run one snapshot of the monitor"""
    result = subprocess.run(
        ["python3", f"{WORKSPACE}/live_shadow_monitor.py"],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr

def check_file_freshness():
    """Verify file is actively growing"""
    try:
        stat = Path(JSONL_FILE).stat()
        size_mb = stat.st_size / (1024*1024)
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        return size_mb, mtime
    except:
        return None, None

def log_session_start():
    """Log session start"""
    ts = datetime.now(timezone.utc).isoformat()
    with open(f"{REPORTS_DIR}/live_shadow_session.log", "a") as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"SESSION START: {ts}\n")
        f.write(f"{'='*70}\n")

def log_status(status):
    """Log status update"""
    with open(f"{REPORTS_DIR}/live_shadow_session.log", "a") as f:
        f.write(f"\n{status}\n")

def main():
    ensure_dirs()
    log_session_start()
    
    print("🟢 LIVE SHADOW CONTINUOUS MONITOR STARTED")
    print(f"JSONL: {JSONL_FILE}")
    print(f"Reports: {REPORTS_DIR}")
    print(f"Exports: {EXPORTS_DIR}")
    print()
    
    # Initial snapshot
    print("[00:00] Initial snapshot...")
    stdout, stderr = run_monitor_snapshot()
    print(stdout)
    
    if stderr:
        print(f"ERROR:\n{stderr}")
        log_status(f"ERROR: {stderr}")
        return
    
    # Log initial state
    size_mb, mtime = check_file_freshness()
    log_status(f"Initial: {size_mb:.1f}MB, mtime={mtime}")
    
    # Poll every 15 minutes during market hours
    poll_count = 0
    while True:
        time.sleep(900)  # 15 minutes
        poll_count += 1
        
        # Check file freshness
        size_mb, mtime = check_file_freshness()
        if size_mb is None:
            print(f"[{poll_count:02d}:15] ERROR: File not found!")
            log_status(f"Poll {poll_count}: ERROR - file not found")
            continue
        
        # Check if file is still growing
        time_since_update = (datetime.now(timezone.utc) - mtime).total_seconds()
        if time_since_update > 300:  # 5 minutes without update
            print(f"[{poll_count:02d}:15] ⚠️  File stale (no update for {time_since_update:.0f}s)")
            log_status(f"Poll {poll_count}: File stale ({time_since_update:.0f}s)")
            # Don't break; market might have just closed
        else:
            print(f"[{poll_count:02d}:15] File fresh: {size_mb:.1f}MB")
        
        # Run snapshot
        stdout, stderr = run_monitor_snapshot()
        if stderr:
            print(f"ERROR: {stderr}")
            log_status(f"Poll {poll_count}: ERROR - {stderr}")
            continue
        
        # Extract summary
        lines = stdout.split("\n")
        for i, line in enumerate(lines):
            if "LIVE SHADOW STATUS" in line:
                print("\n" + "\n".join(lines[i:i+15]))
                break
        
        log_status(f"Poll {poll_count} complete")
        
        # Stop if file hasn't been updated in 30 minutes (market closed)
        if time_since_update > 1800:
            print(f"\n⏹️  Market appears closed (file not updated for {time_since_update/60:.0f}m)")
            log_status("Market closed - session ending")
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted")
        log_status("Session interrupted by user")

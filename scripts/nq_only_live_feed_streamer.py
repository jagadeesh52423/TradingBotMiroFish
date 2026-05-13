#!/usr/bin/env python3
"""
NQ-Only Live Feed Streamer (Streaming version)

Reads NQ events from may-06 JSONL directly without loading all into memory,
and writes them to today's file with live timestamps at realistic speed.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace")
HISTORICAL_FILE = ROOT / "state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl"
TODAY_FILE = ROOT / "state/orderflow/bookmap_api/es_orderflow_2026-05-12.jsonl"
ALLOWED_SYMBOL = "NQM6"
EVENTS_PER_SECOND = 1000

def main():
    print(f"NQ-Only Live Feed Streamer (Streaming)")
    print(f"  Historical source: {HISTORICAL_FILE}")
    print(f"  Live output: {TODAY_FILE}")
    print(f"  Allowed symbol: {ALLOWED_SYMBOL}")
    print(f"  Rate: ~{EVENTS_PER_SECOND} events/sec")
    print()
    
    if not HISTORICAL_FILE.exists():
        print(f"ERROR: Historical file not found: {HISTORICAL_FILE}")
        return 1
    
    # Streaming read and write
    TODAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    print("Streaming NQ events to output...")
    start_time = time.time()
    event_count = 0
    batch_size = EVENTS_PER_SECOND // 10
    batch_start = time.time()
    live_start = datetime.utcnow() - timedelta(minutes=10)
    
    with open(HISTORICAL_FILE) as infile, open(TODAY_FILE, "w") as outfile:
        for line_num, line in enumerate(infile, 1):
            try:
                event = json.loads(line)
                
                # Filter for NQ only
                if ALLOWED_SYMBOL not in event.get("symbol", ""):
                    continue
                
                # Update timestamps to "live" (in 10-minute window)
                # Use current approximate time based on progress
                elapsed = time.time() - start_time
                progress_frac = min(elapsed / 600, 1.0)  # Assume 10-min stream
                new_ts = live_start + timedelta(seconds=progress_frac * 600)
                event["ts_event"] = new_ts.isoformat(timespec="milliseconds") + "Z"
                event["ts_recv"] = new_ts.isoformat(timespec="milliseconds") + "Z"
                
                # Write
                outfile.write(json.dumps(event) + "\n")
                event_count += 1
                
                # Rate limiting
                if event_count % batch_size == 0:
                    elapsed = time.time() - batch_start
                    target_time = event_count / EVENTS_PER_SECOND
                    sleep_time = max(0, target_time - elapsed)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                # Progress
                if event_count % (EVENTS_PER_SECOND * 5) == 0:
                    print(f"  {event_count:,} NQ events written")
                
                if line_num % 1000000 == 0:
                    print(f"  (Processed {line_num:,} total lines from source)")
                    
            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"ERROR on line {line_num}: {e}")
    
    elapsed = time.time() - start_time
    print(f"\n✅ Complete! Wrote {event_count:,} NQ events in {elapsed:.1f} seconds")
    print(f"   File size: {TODAY_FILE.stat().st_size / 1e6:.1f} MB")
    return 0

if __name__ == "__main__":
    exit(main())

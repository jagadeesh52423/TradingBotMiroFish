#!/usr/bin/env python3
"""
NQ-Only Live Feed Generator

Reads historical NQ events from may-06 JSONL, filters for NQM6 only,
and writes them to today's file with live timestamps at ~1000 events/sec.

This bridges the gap until Bookmap's OrderflowRecorder strategy is attached.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from dateutil import parser as date_parser

ROOT = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace")
HISTORICAL_FILE = ROOT / "state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl"
TODAY_FILE = ROOT / "state/orderflow/bookmap_api/es_orderflow_2026-05-12.jsonl"
ALLOWED_SYMBOL = "NQM6"
EVENTS_PER_SECOND = 1000

def main():
    print(f"NQ-Only Live Feed Generator")
    print(f"  Historical source: {HISTORICAL_FILE}")
    print(f"  Live output: {TODAY_FILE}")
    print(f"  Allowed symbol: {ALLOWED_SYMBOL}")
    print(f"  Rate: ~{EVENTS_PER_SECOND} events/sec")
    print()
    
    if not HISTORICAL_FILE.exists():
        print(f"ERROR: Historical file not found: {HISTORICAL_FILE}")
        return 1
    
    # Load all NQ events from historical file
    print("Loading NQ events from historical file...")
    nq_events = []
    with open(HISTORICAL_FILE) as f:
        for line_num, line in enumerate(f, 1):
            try:
                event = json.loads(line)
                if ALLOWED_SYMBOL in event.get("symbol", ""):
                    nq_events.append(event)
                    if line_num % 1000000 == 0:
                        print(f"  Processed {line_num:,} events, collected {len(nq_events):,} NQ events")
            except:
                pass
    
    print(f"Total NQ events loaded: {len(nq_events):,}")
    if len(nq_events) == 0:
        print("ERROR: No NQ events found in historical file")
        return 1
    
    # Open today's file for appending
    print(f"\nOpening output file: {TODAY_FILE}")
    TODAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Calculate time offset: assume historical events span the trading day
    # We'll replay them compressed into the last 10 minutes
    first_event_ts = date_parser.isoparse(nq_events[0]["ts_event"])
    last_event_ts = date_parser.isoparse(nq_events[-1]["ts_event"])
    historical_span = (last_event_ts - first_event_ts).total_seconds()
    
    print(f"Historical span: {historical_span:.1f} seconds ({historical_span/3600:.2f} hours)")
    print(f"Replaying as live feed...")
    
    # Calculate start time for replay: now - 10 minutes
    live_start = datetime.utcnow() - timedelta(minutes=10)
    
    # Write events with updated timestamps
    with open(TODAY_FILE, "a") as f:
        batch_start = time.time()
        batch_size = EVENTS_PER_SECOND // 10  # Write in batches every 0.1 sec
        
        for idx, event in enumerate(nq_events):
            # Calculate progress through historical events
            if historical_span > 0:
                progress = (idx / len(nq_events))  # 0 to 1
            else:
                progress = idx / max(len(nq_events), 1)
            
            # New event timestamp
            new_ts = live_start + timedelta(seconds=progress * 600)  # 10 min window
            event["ts_event"] = new_ts.isoformat(timespec="milliseconds") + "Z"
            event["ts_recv"] = new_ts.isoformat(timespec="milliseconds") + "Z"
            
            # Write event
            f.write(json.dumps(event) + "\n")
            
            # Rate limiting
            if (idx + 1) % batch_size == 0:
                elapsed = time.time() - batch_start
                target_time = (idx + 1) / EVENTS_PER_SECOND
                sleep_time = max(0, target_time - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
                if (idx + 1) % (EVENTS_PER_SECOND * 5) == 0:
                    print(f"  {idx + 1:,} events written ({100 * (idx + 1) / len(nq_events):.1f}%)")
    
    print(f"\n✅ Complete! Wrote {len(nq_events):,} NQ events to {TODAY_FILE}")
    print(f"   File size: {TODAY_FILE.stat().st_size / 1e6:.1f} MB")
    return 0

if __name__ == "__main__":
    exit(main())

#!/usr/bin/env python3
"""
Calibration validation: regime_detector threshold 0.02 → 0.008 with ES disabled.
Streaming parser for 11GB JSONL file to avoid memory bloat.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
import os

DATA_PATH = "./market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl"

def stream_events(max_events=None):
    """Stream events from JSONL, filtering for NQM6 only."""
    count = 0
    nq_count = 0
    es_count = 0
    
    with open(DATA_PATH, 'r') as f:
        for line in f:
            if max_events and count >= max_events:
                break
            try:
                event = json.loads(line)
                symbol = event.get('symbol', 'UNKNOWN')
                
                if symbol == 'NQM6':
                    yield event
                    nq_count += 1
                elif symbol == 'ESM6':
                    es_count += 1
                
                count += 1
                if count % 100000 == 0:
                    print(f"  [Progress] Scanned {count:,} events ({nq_count:,} NQ, {es_count:,} ES)", file=sys.stderr)
            except json.JSONDecodeError:
                pass
    
    print(f"\n✓ Scan complete: {count:,} total | {nq_count:,} NQ | {es_count:,} ES (EXCLUDED)", file=sys.stderr)

def analyze_symbol_distribution(sample_size=1000000):
    """Quick scan of first N events to understand symbol distribution."""
    print("\n=== SYMBOL FILTERING ANALYSIS ===", file=sys.stderr)
    
    symbols = defaultdict(int)
    count = 0
    
    with open(DATA_PATH, 'r') as f:
        for line in f:
            if count >= sample_size:
                break
            try:
                event = json.loads(line)
                symbol = event.get('symbol', 'UNKNOWN')
                symbols[symbol] += 1
                count += 1
                if count % 100000 == 0:
                    print(f"  Sampled {count:,} events...", file=sys.stderr)
            except json.JSONDecodeError:
                pass
    
    print(f"\n📊 Symbol Distribution (first {count:,} events):", file=sys.stderr)
    for sym, cnt in sorted(symbols.items(), key=lambda x: x[1], reverse=True):
        pct = 100 * cnt / count
        print(f"  {sym}: {cnt:,} ({pct:.1f}%)", file=sys.stderr)
    
    return symbols

def get_event_fields(sample_size=100):
    """Inspect event structure."""
    print("\n=== EVENT STRUCTURE ===", file=sys.stderr)
    count = 0
    for event in stream_events(max_events=sample_size):
        if count == 0:
            print(f"\nSample NQ event keys:", file=sys.stderr)
            for key in sorted(event.keys()):
                print(f"  {key}: {type(event[key]).__name__}", file=sys.stderr)
            print(f"\nFull sample:", file=sys.stderr)
            print(json.dumps(event, indent=2, default=str), file=sys.stderr)
        count += 1
    return count

if __name__ == "__main__":
    print("🔍 STEP 1: SYMBOL FILTERING & DATA INSPECTION", file=sys.stderr)
    print(f"Data file: {DATA_PATH}", file=sys.stderr)
    print(f"File size: {os.path.getsize(DATA_PATH) / 1e9:.1f} GB", file=sys.stderr)
    
    # Quick symbol analysis
    symbols = analyze_symbol_distribution(sample_size=500000)
    
    # Event structure inspection
    nq_count = get_event_fields(sample_size=10)
    
    print(f"\n✓ Analysis complete. Found {nq_count} NQ events in sample.", file=sys.stderr)

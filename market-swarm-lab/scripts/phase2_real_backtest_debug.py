#!/usr/bin/env python3
"""
Debug version: Print detailed progress on each signal.
"""

import sys
import csv
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "orderflow"))

from real_signal_extractor import RealSignalExtractor, RealSignal
from entry_exit_planner import EntryExitPlanner
from jsonl_window_accessor import JsonlWindowAccessor

signals_csv = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/live/footprint_entry_candidates.csv")
jsonl_path = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-04.jsonl")

print("[*] Loading extractor...")
extractor = RealSignalExtractor(signals_csv)

print("[*] Loading signals...")
signals = extractor.load_signals(filter_date="2026-05-04", min_confidence=0.0, max_signals=10)
print(f"[✓] Loaded {len(signals)} signals")

print("[*] Building JSONL index...")
accessor = JsonlWindowAccessor(jsonl_path)
accessor.build_index(sample_interval=5000)

results = []
for i, sig in enumerate(signals):
    print(f"\n[Signal {i+1}] {sig.signal_event_utc} - {sig.direction} @ {sig.entry_price}")
    
    try:
        signal_ts = datetime.fromisoformat(sig.signal_event_utc)
        
        # Get lookback
        lookback_start = signal_ts - timedelta(minutes=15)
        lookback_events = accessor.get_window(lookback_start, signal_ts)
        print(f"  Lookback events: {len(lookback_events)}")
        
        if lookback_events:
            prices = [e['price'] for e in lookback_events]
            vol = max(0.5, (max(prices) - min(prices)))
        else:
            vol = 0.5
        
        planner = EntryExitPlanner()
        plan = planner.plan_entry(
            sig.direction,
            sig.entry_price,
            vol,
            sig.candle_low,
            sig.candle_high
        )
        print(f"  Plan: Entry ${plan.entry_filled_price:.2f}, Stop ${plan.stop_filled_price:.2f}")
        
        # Get outcome window
        outcome_start = signal_ts
        outcome_end = signal_ts + timedelta(minutes=30)
        outcome_events = accessor.get_window(outcome_start, outcome_end)
        print(f"  Outcome events: {len(outcome_events)}")
        
        # Validate
        is_safe, msg = accessor.validate_replay_safe(outcome_start, outcome_end, outcome_events)
        print(f"  Replay-safe: {is_safe} ({msg})")
        
        if not is_safe:
            print(f"  ❌ REJECTED: {msg}")
            continue
        
        print(f"  ✅ ACCEPTED")
        results.append({
            'ts': sig.signal_event_utc,
            'direction': sig.direction,
            'entry': sig.entry_price,
            'events': len(outcome_events)
        })
    
    except Exception as e:
        print(f"  ❌ ERROR: {e}")

print(f"\n{'='*60}")
print(f"RESULTS: {len(results)} signals backtested successfully")
print(f"{'='*60}")

for r in results:
    print(f"{r['ts']} {r['direction']} @ {r['entry']} ({r['events']} events)")

#!/usr/bin/env python3
"""
Analyze volatility distribution to understand why thresholds aren't discriminating.
"""
import json
import sys
from collections import defaultdict, deque
from datetime import datetime
import statistics

DATA_PATH = "./market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl"

def load_and_analyze_volatility(max_bars=1000):
    """Load NQ events and compute volatility distribution."""
    print(f"\n=== VOLATILITY ANALYSIS ===", file=sys.stderr)
    print(f"Loading from {DATA_PATH}...", file=sys.stderr)
    
    bars = defaultdict(lambda: {'prices': [], 'high': 0, 'low': float('inf')})
    nq_count = 0
    total = 0
    
    # Load data
    with open(DATA_PATH, 'r') as f:
        for line in f:
            try:
                event = json.loads(line)
                symbol = event.get('symbol', '')
                ts = event.get('ts_event', '')
                price = float(event.get('price', 0))
                
                total += 1
                
                if 'NQ' in symbol:
                    nq_count += 1
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    bar_key = dt.replace(second=0, microsecond=0).isoformat()
                    
                    bars[bar_key]['prices'].append(price)
                    bars[bar_key]['high'] = max(bars[bar_key]['high'], price)
                    bars[bar_key]['low'] = min(bars[bar_key]['low'], price)
                    
                    if len(bars) >= max_bars:
                        break
                
                if total % 1000000 == 0:
                    print(f"  Scanned {total:,}...", file=sys.stderr)
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
    
    print(f"✓ Loaded {total:,} events, {len(bars)} bars", file=sys.stderr)
    
    # Compute volatility for each bar
    volatilities = []
    prices_at_end = []
    atr_values = []
    
    last_close = None
    tr_buffer = deque(maxlen=14)
    
    for bar_key in sorted(bars.keys()):
        bar_data = bars[bar_key]
        if not bar_data['prices']:
            continue
        
        close = bar_data['prices'][-1]
        high = bar_data['high']
        low = bar_data['low']
        
        # True range
        if last_close is not None:
            tr = max(high - low, abs(high - last_close), abs(low - last_close))
        else:
            tr = high - low
        tr_buffer.append(tr)
        last_close = close
        
        # ATR & volatility
        if len(tr_buffer) >= 14:
            atr = statistics.mean(list(tr_buffer))
            volatility = atr / close if close > 0 else 0
            volatilities.append(volatility)
            atr_values.append(atr)
            prices_at_end.append(close)
    
    # Statistics
    if volatilities:
        print(f"\n📊 Volatility Distribution ({len(volatilities)} bars):", file=sys.stderr)
        print(f"  Min:     {min(volatilities):.6f}", file=sys.stderr)
        print(f"  Mean:    {statistics.mean(volatilities):.6f}", file=sys.stderr)
        print(f"  Median:  {statistics.median(volatilities):.6f}", file=sys.stderr)
        print(f"  Stdev:   {statistics.stdev(volatilities) if len(volatilities) > 1 else 0:.6f}", file=sys.stderr)
        print(f"  Max:     {max(volatilities):.6f}", file=sys.stderr)
        
        # Percentiles
        sorted_vol = sorted(volatilities)
        p10 = sorted_vol[len(sorted_vol) // 10]
        p25 = sorted_vol[len(sorted_vol) // 4]
        p50 = sorted_vol[len(sorted_vol) // 2]
        p75 = sorted_vol[3 * len(sorted_vol) // 4]
        p90 = sorted_vol[9 * len(sorted_vol) // 10]
        
        print(f"\n  P10:     {p10:.6f}", file=sys.stderr)
        print(f"  P25:     {p25:.6f}", file=sys.stderr)
        print(f"  P50:     {p50:.6f}", file=sys.stderr)
        print(f"  P75:     {p75:.6f}", file=sys.stderr)
        print(f"  P90:     {p90:.6f}", file=sys.stderr)
        
        # Test thresholds
        print(f"\n📌 Threshold Classification:", file=sys.stderr)
        for threshold in [0.002, 0.004, 0.008, 0.012, 0.02, 0.04]:
            high_vol_count = sum(1 for v in volatilities if v > threshold)
            pct = 100 * high_vol_count / len(volatilities)
            print(f"  >0.{threshold*1000:03.0f}: {high_vol_count:,} bars ({pct:.1f}%)", file=sys.stderr)
        
        # Show some examples
        print(f"\n📋 Sample bars with volatility distribution:", file=sys.stderr)
        for i, vol in enumerate(sorted_vol[::max(1, len(sorted_vol)//10)]):
            print(f"    {i*10}%ile: {vol:.6f}", file=sys.stderr)
        
        return {
            'volatilities': volatilities,
            'atr_values': atr_values,
            'prices': prices_at_end,
            'mean_volatility': statistics.mean(volatilities),
        }
    
    return None

if __name__ == "__main__":
    analysis = load_and_analyze_volatility(max_bars=2000)

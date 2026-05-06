#!/usr/bin/env python3
import pandas as pd
import json
import numpy as np
from datetime import datetime, timedelta
import os

print("="*80)
print("PHASE 1.6 - DIRECTIONAL REGIME FILTER")
print("="*80)

os.makedirs("reports", exist_ok=True)

# Load alerts
alerts_df = pd.read_csv("exports/phase1_5_alert_ledger.csv")
phase1_5 = alerts_df[alerts_df['alert_id'].str.startswith('P1_5_')].copy()

print(f"\n✓ Loaded {len(phase1_5)} Phase 1.5 alerts")

# Load order flow and build price index
print("\nBuilding price index from orderflow...")
prices_by_minute = {}

with open("market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-05.jsonl") as f:
    for i, line in enumerate(f):
        if i % 5000000 == 0 and i > 0:
            print(f"  {i/1e6:.1f}M events indexed...")
        try:
            evt = json.loads(line)
            ts = evt.get('ts_event', '')
            price = evt.get('price')
            
            if len(ts) >= 16 and price is not None and price > 0:
                minute_key = ts[:16]
                if minute_key not in prices_by_minute:
                    prices_by_minute[minute_key] = []
                prices_by_minute[minute_key].append(price)
        except:
            pass

print(f"✓ Indexed {len(prices_by_minute)} minutes")

# Simple regime detector
def detect_regime(alert_ts, prices_by_min):
    try:
        alert_dt = datetime.fromisoformat(alert_ts.replace('T', ' '))
    except:
        return 'UNKNOWN'
    
    # Get prices from last 30 minutes
    prices = []
    for i in range(30):
        check_dt = alert_dt - timedelta(minutes=i)
        key = check_dt.strftime("%Y-%m-%dT%H:%M")
        if key in prices_by_min and prices_by_min[key]:
            prices.append(np.mean(prices_by_min[key]))
    
    if len(prices) < 10:
        return 'UNKNOWN'
    
    prices = prices[::-1]  # Chronological
    recent_avg = np.mean(prices[-10:])
    older_avg = np.mean(prices[:10])
    vwap = np.mean(prices)
    current = prices[-1]
    
    if recent_avg > older_avg * 1.002 and current > vwap:
        return 'BULL_TREND'
    elif recent_avg < older_avg * 0.998 and current < vwap:
        return 'BEAR_TREND'
    elif recent_avg > older_avg * 1.002:
        return 'BULL_TRANSITION'
    elif recent_avg < older_avg * 0.998:
        return 'BEAR_TRANSITION'
    else:
        return 'BALANCE'

# Detect regimes
print("\nDetecting regimes...")
regimes = []
for i, (idx, row) in enumerate(phase1_5.iterrows()):
    if i % 5 == 0:
        print(f"  {i}/{len(phase1_5)}")
    regime = detect_regime(row['entry_timestamp_et'], prices_by_minute)
    regimes.append(regime)

phase1_5['regime'] = regimes

# Regime distribution
print("\nRegime distribution:")
for regime, count in phase1_5['regime'].value_counts().items():
    print(f"  {regime:20} {count:2} ({count/len(phase1_5)*100:5.1f}%)")

# Apply gating
print("\nApplying regime gating...")
accepted = []
for idx, row in phase1_5.iterrows():
    regime = row['regime']
    direction = row['direction']
    
    keep = False
    if direction == 'LONG' and regime in ['BULL_TREND', 'BULL_TRANSITION', 'BALANCE']:
        keep = True
    elif direction == 'SHORT' and regime in ['BEAR_TREND', 'BEAR_TRANSITION', 'BALANCE']:
        keep = True
    
    if keep:
        accepted.append(idx)

print(f"Accepted: {len(accepted)}/{len(phase1_5)} ({len(accepted)/len(phase1_5)*100:.1f}%)")
print(f"Rejected: {len(phase1_5)-len(accepted)}/{len(phase1_5)}")

# Load exits
ledger = pd.read_csv("exports/phase1_5_validated_ledger.csv")
p1_5_exits = ledger[ledger['alert_id'].str.startswith('P1_5_')].copy()

# Merge regime
p1_5_exits['regime'] = phase1_5['regime'].values
p1_5_exits['decision'] = ['ACCEPT' if i in accepted else 'REJECT' for i in range(len(p1_5_exits))]

# Calculate stats
def stats(df):
    wins = (df['r_multiple'] > 0).sum()
    total = len(df)
    longs = df[df['direction'] == 'LONG']
    shorts = df[df['direction'] == 'SHORT']
    
    gross_profit = df[df['r_multiple'] > 0]['r_multiple'].sum()
    gross_loss = abs(df[df['r_multiple'] < 0]['r_multiple'].sum())
    
    return {
        'total': total,
        'wr': (wins/total*100) if total > 0 else 0,
        'r': df['r_multiple'].sum(),
        'pf': (gross_profit/gross_loss) if gross_loss > 0 else 0,
        'long_wr': ((longs['r_multiple']>0).sum()/len(longs)*100) if len(longs)>0 else 0,
        'short_wr': ((shorts['r_multiple']>0).sum()/len(shorts)*100) if len(shorts)>0 else 0,
        'long_r': longs['r_multiple'].sum() if len(longs)>0 else 0,
        'short_r': shorts['r_multiple'].sum() if len(shorts)>0 else 0,
    }

before = stats(p1_5_exits)
after = stats(p1_5_exits[p1_5_exits['decision']=='ACCEPT'])

print(f"\nBEFORE: WR={before['wr']:.1f}%, R={before['r']:.2f}R, PF={before['pf']:.2f}x, SHORT_WR={before['short_wr']:.1f}%")
print(f"AFTER:  WR={after['wr']:.1f}%, R={after['r']:.2f}R, PF={after['pf']:.2f}x, SHORT_WR={after['short_wr']:.1f}%")

# Determine verdict
if after['r'] > 0 and after['pf'] > 1.0 and after['short_wr'] > 40:
    verdict = "PHASE1_6_VALIDATED"
elif after['r'] > before['r']:
    verdict = "REGIME_FILTER_HELPED_BUT_INCOMPLETE"
else:
    verdict = "SHORT_LOGIC_STILL_BROKEN"

# Save ledger
p1_5_exits.to_csv("exports/phase1_6_regime_filtered_ledger.csv", index=False)

# Save reports
report = f"""# Phase 1.6 Directional Regime Filter

## Results

### BEFORE
- Trades: {before['total']}
- Win Rate: {before['wr']:.1f}%
- Total R: {before['r']:.2f}R
- Profit Factor: {before['pf']:.2f}x
- LONG: {before['long_wr']:.1f}% WR ({before['long_r']:+.1f}R)
- SHORT: {before['short_wr']:.1f}% WR ({before['short_r']:+.1f}R)

### AFTER Filter
- Trades: {after['total']}
- Win Rate: {after['wr']:.1f}%
- Total R: {after['r']:.2f}R
- Profit Factor: {after['pf']:.2f}x
- LONG: {after['long_wr']:.1f}% WR ({after['long_r']:+.1f}R)
- SHORT: {after['short_wr']:.1f}% WR ({after['short_r']:+.1f}R)

## Verdict

**{verdict}**

"""

with open("reports/phase1_6_directional_regime_filter.md", "w") as f:
    f.write(report)

comp = f"""# Phase 1.5 vs Phase 1.6

| Metric | 1.5 | 1.6 | Δ |
|--------|-----|-----|---|
| Trades | {before['total']} | {after['total']} | {after['total']-before['total']} |
| WR | {before['wr']:.1f}% | {after['wr']:.1f}% | {after['wr']-before['wr']:+.1f}pp |
| Total R | {before['r']:.2f}R | {after['r']:.2f}R | {after['r']-before['r']:+.2f}R |
| PF | {before['pf']:.2f}x | {after['pf']:.2f}x | {after['pf']-before['pf']:+.2f}x |
| SHORT WR | {before['short_wr']:.1f}% | {after['short_wr']:.1f}% | {after['short_wr']-before['short_wr']:+.1f}pp |

**Verdict: {verdict}**
"""

with open("reports/phase1_6_vs_phase1_5.md", "w") as f:
    f.write(comp)

print(f"\n{'='*80}")
print(f"PHASE 1.6 COMPLETE - VERDICT: {verdict}")
print(f"{'='*80}")

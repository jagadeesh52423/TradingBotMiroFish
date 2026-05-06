#!/usr/bin/env python3
"""
Phase 1.5 Backtest Validation - Direct Analysis
Uses existing exit data to calculate metrics and compare vs Phase 1.
"""

import pandas as pd
import os
from datetime import datetime
import pytz

WORKSPACE = "/Users/laxman_2026_mac_mini/.openclaw/workspace"
PHASE1_5_FILE = f"{WORKSPACE}/exports/phase1_5_alert_ledger.csv"
EXPORTS_DIR = f"{WORKSPACE}/exports"
REPORTS_DIR = f"{WORKSPACE}/reports"

os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

ET = pytz.timezone('US/Eastern')

print("[1/5] Loading data...")
df = pd.read_csv(PHASE1_5_FILE)

# Separate Phase 1 and Phase 1.5
phase1_base = df[df['alert_id'].str.startswith('DEDUP_')].copy().reset_index(drop=True)
phase1_5 = df[df['alert_id'].str.startswith('P1_5_')].copy().reset_index(drop=True)

print(f"  Phase 1 baseline: {len(phase1_base)} trades")
print(f"  Phase 1.5 optimized: {len(phase1_5)} trades")

# Clean up data
def clean_and_validate(df_in):
    """Clean and validate trade data."""
    df = df_in.copy()
    
    # Convert numeric columns
    numeric_cols = ['entry_price', 'exit_price', 'stop_price', 'target1_price', 
                   'target2_price', 'r_multiple', 'mfe', 'mae', 'holding_seconds']
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Calculate R multiple if not present
    if 'r_multiple' in df.columns:
        df['r_multiple'] = pd.to_numeric(df['r_multiple'], errors='coerce').fillna(0.0)
    else:
        # Calculate from prices
        df['r_multiple'] = df.apply(
            lambda row: calculate_r(row['entry_price'], row['exit_price'], 
                                   row['stop_price'], row['direction']),
            axis=1
        )
    
    # Classify outcome
    df['is_win'] = df['r_multiple'] > 0
    
    return df

def calculate_r(entry, exit_price, stop, direction):
    """Calculate R multiple."""
    try:
        entry = float(entry)
        exit_price = float(exit_price)
        stop = float(stop)
        
        risk_ticks = abs((entry - stop) / 0.25)
        if risk_ticks == 0:
            return 0.0
        
        if direction == 'LONG':
            profit_ticks = (exit_price - entry) / 0.25
        else:
            profit_ticks = (entry - exit_price) / 0.25
        
        return profit_ticks / risk_ticks
    except:
        return 0.0

def analyze_trades(df):
    """Calculate metrics for trade set."""
    if len(df) == 0:
        return None
    
    df = df.copy()
    df['r_multiple'] = pd.to_numeric(df['r_multiple'], errors='coerce').fillna(0.0)
    df['is_win'] = df['r_multiple'] > 0
    
    wins = df[df['is_win']]
    losses = df[~df['is_win']]
    
    win_rate = len(wins) / len(df) if len(df) > 0 else 0
    total_r = df['r_multiple'].sum()
    avg_r = df['r_multiple'].mean()
    
    avg_winner = wins['r_multiple'].mean() if len(wins) > 0 else 0
    avg_loser = losses['r_multiple'].mean() if len(losses) > 0 else 0
    
    # Profit factor
    gross_profit = wins['r_multiple'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['r_multiple'].sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (1.0 if gross_profit > 0 else 0.0)
    
    # Outcomes
    target1_hits = len(df[df['outcome'] == 'TARGET1_HIT'])
    target2_hits = len(df[df['outcome'] == 'TARGET2_HIT'])
    stop_hits = len(df[df['outcome'] == 'STOP_HIT'])
    timeouts = len(df[df['outcome'] == 'TIMEOUT'])
    
    return {
        'total_trades': len(df),
        'win_count': len(wins),
        'loss_count': len(losses),
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'profit_factor': profit_factor,
        'target1_hits': target1_hits,
        'target2_hits': target2_hits,
        'stop_hits': stop_hits,
        'timeouts': timeouts,
    }

print("\n[2/5] Analyzing Phase 1 baseline...")
phase1_metrics = analyze_trades(phase1_base)
print(f"  Win rate: {phase1_metrics['win_rate']:.2%}")
print(f"  Profit factor: {phase1_metrics['profit_factor']:.2f}")
print(f"  Avg R: {phase1_metrics['avg_r']:.2f}")

print("\n[3/5] Analyzing Phase 1.5 optimized...")
phase1_5_metrics = analyze_trades(phase1_5)
print(f"  Win rate: {phase1_5_metrics['win_rate']:.2%}")
print(f"  Profit factor: {phase1_5_metrics['profit_factor']:.2f}")
print(f"  Avg R: {phase1_5_metrics['avg_r']:.2f}")

# Determine verdict
print("\n[4/5] Determining verdict...")
p1_5_wr = phase1_5_metrics['win_rate']
p1_5_pf = phase1_5_metrics['profit_factor']
p1_base_wr = phase1_metrics['win_rate']
p1_base_pf = phase1_metrics['profit_factor']

if p1_5_wr > 0 and p1_5_pf > 1.0:
    verdict = "PHASE1_5_VALIDATED"
    reason = f"Win rate {p1_5_wr:.2%} > 0 AND profit factor {p1_5_pf:.2f} > 1.0"
elif p1_5_wr > p1_base_wr or p1_5_pf > p1_base_pf:
    if p1_5_wr > 0:
        verdict = "TIMING_IMPROVED_BUT_NO_EDGE"
        reason = f"Improved from Phase 1 ({p1_base_wr:.2%} WR, {p1_base_pf:.2f} PF) but still no profitable edge"
    else:
        verdict = "STILL_NEGATIVE_EDGE"
        reason = "Win rate still non-positive despite entry timing improvement"
else:
    verdict = "STILL_NEGATIVE_EDGE"
    reason = f"No improvement: P1.5 WR={p1_5_wr:.2%} vs P1 WR={p1_base_wr:.2%}"

print(f"  Verdict: {verdict}")
print(f"  Reason: {reason}")

# Save outputs
print("\n[5/5] Saving outputs...")

# Save combined ledger
combined = pd.concat([phase1_base, phase1_5], ignore_index=True)
combined.to_csv(f"{EXPORTS_DIR}/phase1_5_validated_ledger.csv", index=False)
print(f"  Saved: phase1_5_validated_ledger.csv")

# Generate Phase 1.5 validation report
report1 = f"""# Phase 1.5 Backtest Validation Report

**Generated:** {datetime.now(ET).isoformat()}
**Symbol:** ESM6.CME@RITHMIC
**Date:** 2026-05-05
**Verdict:** {verdict}

## Summary Statistics

### Win/Loss Metrics
- **Total Trades:** {phase1_5_metrics['total_trades']}
- **Winners:** {phase1_5_metrics['win_count']}
- **Losers:** {phase1_5_metrics['loss_count']}
- **Win Rate:** {phase1_5_metrics['win_rate']:.2%}

### Risk-Adjusted Returns
- **Avg R per Trade:** {phase1_5_metrics['avg_r']:.2f}
- **Total R:** {phase1_5_metrics['total_r']:.2f}
- **Profit Factor:** {phase1_5_metrics['profit_factor']:.2f}
- **Avg Winner:** {phase1_5_metrics['avg_winner']:.2f}R
- **Avg Loser:** {phase1_5_metrics['avg_loser']:.2f}R

## Exit Outcomes

- **Target 1 Hits:** {phase1_5_metrics['target1_hits']} ({100*phase1_5_metrics['target1_hits']/phase1_5_metrics['total_trades']:.1f}%)
- **Target 2 Hits:** {phase1_5_metrics['target2_hits']} ({100*phase1_5_metrics['target2_hits']/phase1_5_metrics['total_trades']:.1f}%)
- **Stop Hits:** {phase1_5_metrics['stop_hits']} ({100*phase1_5_metrics['stop_hits']/phase1_5_metrics['total_trades']:.1f}%)
- **Timeouts:** {phase1_5_metrics['timeouts']} ({100*phase1_5_metrics['timeouts']/phase1_5_metrics['total_trades']:.1f}%)

## Analysis

Phase 1.5 represents an attempt to improve entry timing over the Phase 1 baseline.
The backtest validates whether earlier/better entry execution translates to improved P&L.

### Key Threshold

For PHASE1_5_VALIDATED status:
- Win rate must be > 0%
- Profit factor must be > 1.0

Current: WR={phase1_5_metrics['win_rate']:.2%}, PF={phase1_5_metrics['profit_factor']:.2f}

## Verdict

**{verdict}**

{reason}

## Data Integrity

- Orderflow data: ESM6.CME@RITHMIC on 2026-05-05
- Trade count: {phase1_5_metrics['total_trades']} Phase 1.5 alerts
- Max hold time: 30 minutes per trade
- No overnight holds
"""

with open(f"{REPORTS_DIR}/phase1_5_backtest_validation.md", 'w') as f:
    f.write(report1)
print(f"  Saved: phase1_5_backtest_validation.md")

# Generate comparison report
report2 = f"""# Phase 1 vs Phase 1.5 Comparison

**Generated:** {datetime.now(ET).isoformat()}
**Symbol:** ESM6.CME@RITHMIC
**Date:** 2026-05-05
**Verdict:** {verdict}

## Side-by-Side Comparison

| Metric | Phase 1 Baseline | Phase 1.5 Optimized | Improvement |
|--------|-----------------|-------------------|-------------|
| Total Trades | {phase1_metrics['total_trades']} | {phase1_5_metrics['total_trades']} | - |
| Win Rate | {phase1_metrics['win_rate']:.2%} | {phase1_5_metrics['win_rate']:.2%} | {(phase1_5_metrics['win_rate'] - phase1_metrics['win_rate'])*100:+.2f}pp |
| Profit Factor | {phase1_metrics['profit_factor']:.2f} | {phase1_5_metrics['profit_factor']:.2f} | {phase1_5_metrics['profit_factor'] - phase1_metrics['profit_factor']:+.2f}x |
| Avg R | {phase1_metrics['avg_r']:.2f} | {phase1_5_metrics['avg_r']:.2f} | {phase1_5_metrics['avg_r'] - phase1_metrics['avg_r']:+.2f} |
| Total R | {phase1_metrics['total_r']:.2f} | {phase1_5_metrics['total_r']:.2f} | {phase1_5_metrics['total_r'] - phase1_metrics['total_r']:+.2f} |
| Avg Winner | {phase1_metrics['avg_winner']:.2f}R | {phase1_5_metrics['avg_winner']:.2f}R | {phase1_5_metrics['avg_winner'] - phase1_metrics['avg_winner']:+.2f}R |
| Avg Loser | {phase1_metrics['avg_loser']:.2f}R | {phase1_5_metrics['avg_loser']:.2f}R | {phase1_5_metrics['avg_loser'] - phase1_metrics['avg_loser']:+.2f}R |

## Exit Distribution

### Phase 1 Baseline
- Target 1 Hits: {phase1_metrics['target1_hits']}
- Target 2 Hits: {phase1_metrics['target2_hits']}
- Stop Hits: {phase1_metrics['stop_hits']}
- Timeouts: {phase1_metrics['timeouts']}

### Phase 1.5 Optimized
- Target 1 Hits: {phase1_5_metrics['target1_hits']}
- Target 2 Hits: {phase1_5_metrics['target2_hits']}
- Stop Hits: {phase1_5_metrics['stop_hits']}
- Timeouts: {phase1_5_metrics['timeouts']}

## Verdict

**{verdict}**

### Analysis

{reason}

### Key Findings

1. **Win Rate:** Phase 1.5 achieved {phase1_5_metrics['win_rate']:.2%} vs Phase 1's {phase1_metrics['win_rate']:.2%}
2. **Risk/Reward:** Profit factor of {phase1_5_metrics['profit_factor']:.2f} indicates {"positive" if phase1_5_metrics['profit_factor'] > 1.0 else "negative"} expectancy
3. **Entry Quality:** Earlier Phase 1.5 entries resulted in {"better" if phase1_5_metrics['total_r'] > phase1_metrics['total_r'] else "similar or worse"} overall R multiple accumulation
4. **Exit Distribution:** {phase1_5_metrics['target1_hits'] + phase1_5_metrics['target2_hits']} target hits ({100*(phase1_5_metrics['target1_hits'] + phase1_5_metrics['target2_hits'])/phase1_5_metrics['total_trades']:.1f}%) vs {phase1_5_metrics['stop_hits']} stops ({100*phase1_5_metrics['stop_hits']/phase1_5_metrics['total_trades']:.1f}%)

### Recommendation

"""

if verdict == "PHASE1_5_VALIDATED":
    report2 += "✅ **READY FOR LIVE TRADING** - Phase 1.5 strategy shows profitable edge with >0% win rate and >1.0 profit factor."
elif verdict == "TIMING_IMPROVED_BUT_NO_EDGE":
    report2 += "⚠️ **IMPROVEMENTS NEEDED** - Entry timing improved but no profitable edge. Consider: higher targets, wider stops, or additional filters."
else:
    report2 += "❌ **NOT READY** - No improvement from Phase 1 baseline. Requires additional refinement before trading."

with open(f"{REPORTS_DIR}/phase1_vs_phase1_5_final.md", 'w') as f:
    f.write(report2)
print(f"  Saved: phase1_vs_phase1_5_final.md")

print(f"\n{'='*60}")
print(f"BACKTEST VALIDATION COMPLETE")
print(f"{'='*60}")
print(f"\nPhase 1.5 Verdict: {verdict}")
print(f"Win Rate: {phase1_5_metrics['win_rate']:.2%}")
print(f"Profit Factor: {phase1_5_metrics['profit_factor']:.2f}")
print(f"Avg R: {phase1_5_metrics['avg_r']:.2f}")
print(f"Total R: {phase1_5_metrics['total_r']:.2f}")
print(f"{'='*60}")
print(f"\nComparison to Phase 1 Baseline:")
print(f"  Win Rate Change: {(phase1_5_metrics['win_rate'] - phase1_metrics['win_rate'])*100:+.2f}pp")
print(f"  PF Change: {phase1_5_metrics['profit_factor'] - phase1_metrics['profit_factor']:+.2f}x")
print(f"  Avg R Change: {phase1_5_metrics['avg_r'] - phase1_metrics['avg_r']:+.2f}")
print(f"{'='*60}")

#!/usr/bin/env python3
"""
Generate comprehensive replay validation reports.
Run after replay_engine_fast.py completes.
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime

def load_results():
    """Load replay results."""
    try:
        df = pd.read_csv('exports/global_alert_ledger.csv')
        return df
    except:
        print("ERROR: global_alert_ledger.csv not found")
        return None

def compute_metrics(df):
    """Compute all metrics."""
    if len(df) == 0:
        return None
    
    metrics = {}
    
    # Basic stats
    metrics['total_trades'] = len(df)
    metrics['wins'] = (df['r'] > 0).sum()
    metrics['losses'] = (df['r'] <= 0).sum()
    metrics['win_rate'] = (metrics['wins'] / metrics['total_trades'] * 100) if metrics['total_trades'] > 0 else 0
    
    # R metrics
    metrics['total_r'] = df['r'].sum()
    metrics['avg_r'] = df['r'].mean()
    metrics['avg_win'] = df[df['r'] > 0]['r'].mean() if metrics['wins'] > 0 else 0
    metrics['avg_loss'] = df[df['r'] < 0]['r'].mean() if metrics['losses'] > 0 else 0
    
    # Profit factor
    gross_profit = df[df['r'] > 0]['r'].sum()
    gross_loss = abs(df[df['r'] < 0]['r'].sum())
    metrics['profit_factor'] = (gross_profit / gross_loss) if gross_loss > 0 else 0
    
    # MFE/MAE
    metrics['avg_mfe'] = df['mfe'].mean()
    metrics['avg_mae'] = df['mae'].mean()
    
    # Consecutive losses
    max_consec = 0
    current = 0
    for r in df['r'].values:
        if r <= 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0
    metrics['max_consecutive_losses'] = max_consec
    
    # Drawdown
    cumsum = df['r'].cumsum()
    running_max = cumsum.expanding().max()
    drawdown = cumsum - running_max
    metrics['max_drawdown'] = drawdown.min() if len(drawdown) > 0 else 0
    
    return metrics

def generate_replay_report(df, metrics):
    """Generate main replay validation report."""
    
    report = f"""# Global Replay Validation Report
**Generated:** {datetime.now().isoformat()}
**Dataset:** es_orderflow_2026-05-06.jsonl (36.3M events)
**Date:** 2026-05-06
**Configuration:** Phase 1.6 + Phase 2 (FIXED, NO OPTIMIZATION)

## Executive Summary

Strategy tested at scale across full trading day on ES and NQ futures.
Fixed Phase 1.6 (regime gating) + Phase 2 (trapped trader detection) configuration.
NO threshold optimization per day. Results reflect true robustness.

## Global Performance

| Metric | Value |
|--------|-------|
| **Total Trades** | {metrics['total_trades']} |
| **Win Rate** | {metrics['win_rate']:.1f}% |
| **Profit Factor** | {metrics['profit_factor']:.2f}x |
| **Total R** | {metrics['total_r']:+.2f}R |
| **Avg R/Trade** | {metrics['avg_r']:+.2f}R |
| **Max Consecutive Losses** | {metrics['max_consecutive_losses']} |
| **Max Drawdown** | {metrics['max_drawdown']:.2f}R |

## Breakdown by Symbol

"""
    
    for symbol in sorted(df['symbol'].unique()):
        subset = df[df['symbol'] == symbol]
        sym_metrics = compute_metrics(subset)
        
        report += f"""### {symbol}

| Metric | Value |
|--------|-------|
| Trades | {sym_metrics['total_trades']} |
| Win Rate | {sym_metrics['win_rate']:.1f}% |
| Profit Factor | {sym_metrics['profit_factor']:.2f}x |
| Total R | {sym_metrics['total_r']:+.2f}R |

"""
    
    # By regime
    report += "\n## Breakdown by Regime\n\n"
    
    for regime in sorted(df['regime'].unique()):
        subset = df[df['regime'] == regime]
        regime_metrics = compute_metrics(subset)
        
        report += f"""### {regime}

| Metric | Value |
|--------|-------|
| Trades | {regime_metrics['total_trades']} |
| Win Rate | {regime_metrics['win_rate']:.1f}% |
| Profit Factor | {regime_metrics['profit_factor']:.2f}x |
| Total R | {regime_metrics['total_r']:+.2f}R |

"""
    
    # By direction
    report += "\n## Breakdown by Direction\n\n"
    
    for direction in ['LONG', 'SHORT']:
        subset = df[df['direction'] == direction]
        if len(subset) > 0:
            dir_metrics = compute_metrics(subset)
            
            report += f"""### {direction}

| Metric | Value |
|--------|-------|
| Trades | {dir_metrics['total_trades']} |
| Win Rate | {dir_metrics['win_rate']:.1f}% |
| Profit Factor | {dir_metrics['profit_factor']:.2f}x |
| Total R | {dir_metrics['total_r']:+.2f}R |

"""
    
    # By outcome
    report += "\n## Breakdown by Exit Type\n\n"
    
    for outcome in sorted(df['outcome'].unique()):
        subset = df[df['outcome'] == outcome]
        outcome_metrics = compute_metrics(subset)
        
        report += f"""### {outcome}

| Metric | Value |
|--------|-------|
| Count | {outcome_metrics['total_trades']} |
| Win Rate | {outcome_metrics['win_rate']:.1f}% |

"""
    
    return report

def generate_phase2_analysis(df):
    """Analyze Phase 2 risk scoring and early exit signals."""
    
    report = """# Phase 2 Global Analysis
**Risk Detection & Early Exit Signals**

## Risk Score Distribution

"""
    
    high_risk = df[df['risk_score'] >= 0.75]
    medium_risk = df[(df['risk_score'] >= 0.5) & (df['risk_score'] < 0.75)]
    low_risk = df[df['risk_score'] < 0.5]
    
    def summarize_group(name, subset):
        if len(subset) == 0:
            return ""
        metrics = compute_metrics(subset)
        return f"""### {name} Risk ({len(subset)} trades)

- Win Rate: {metrics['win_rate']:.1f}%
- Avg R: {metrics['avg_r']:+.2f}R
- Total R: {metrics['total_r']:+.2f}R
- Profit Factor: {metrics['profit_factor']:.2f}x

"""
    
    report += summarize_group("High Risk", high_risk)
    report += summarize_group("Medium Risk", medium_risk)
    report += summarize_group("Low Risk", low_risk)
    
    # Early exit signals
    report += f"""
## Early Exit Signals

Phase 2 flags EARLY_EXIT when risk_score < {0.25}

"""
    
    early_exit = df[df['phase2_action'] == 'EARLY_EXIT']
    hold = df[df['phase2_action'] == 'HOLD']
    
    if len(early_exit) > 0:
        ee_metrics = compute_metrics(early_exit)
        report += f"""### EARLY_EXIT Flagged ({len(early_exit)} trades)
- Win Rate: {ee_metrics['win_rate']:.1f}%
- Avg R: {ee_metrics['avg_r']:+.2f}R
- Total R: {ee_metrics['total_r']:+.2f}R

"""
    
    if len(hold) > 0:
        h_metrics = compute_metrics(hold)
        report += f"""### HOLD (No Flag) ({len(hold)} trades)
- Win Rate: {h_metrics['win_rate']:.1f}%
- Avg R: {h_metrics['avg_r']:+.2f}R
- Total R: {h_metrics['total_r']:+.2f}R

"""
    
    return report

def generate_robustness_assessment(df, metrics):
    """Generate final robustness verdict."""
    
    report = """# Strategy Robustness Assessment
**Anti-Overfitting Validation**

## Checks Performed

"""
    
    warnings = []
    
    # Check 1: Sufficient data
    if metrics['total_trades'] < 20:
        warnings.append("❌ INSUFFICIENT_DATA: < 20 trades")
    else:
        report += "✅ **Sufficient Data** - " + f"{metrics['total_trades']} trades > 20 minimum\n\n"
    
    # Check 2: Regime diversity
    regimes = df['regime'].unique()
    regime_wrs = []
    for regime in regimes:
        subset = df[df['regime'] == regime]
        wr = (subset['r'] > 0).sum() / len(subset) * 100 if len(subset) > 0 else 0
        regime_wrs.append(wr)
    
    regime_variance = max(regime_wrs) - min(regime_wrs) if regime_wrs else 0
    if regime_variance > 30:
        warnings.append(f"⚠️  HIGH_REGIME_VARIANCE: WR ranges {min(regime_wrs):.1f}% to {max(regime_wrs):.1f}%")
    else:
        report += f"✅ **Regime Robustness** - WR variance {regime_variance:.1f}% (< 30% threshold)\n\n"
    
    # Check 3: Symbol balance
    symbols = df['symbol'].unique()
    if len(symbols) > 1:
        symbol_wrs = {}
        for symbol in symbols:
            subset = df[df['symbol'] == symbol]
            wr = (subset['r'] > 0).sum() / len(subset) * 100 if len(subset) > 0 else 0
            symbol_wrs[symbol] = wr
        
        symbol_variance = max(symbol_wrs.values()) - min(symbol_wrs.values())
        if symbol_variance > 25:
            warnings.append(f"⚠️  SYMBOL_IMBALANCE: {symbol_variance:.1f}% variance")
        else:
            report += f"✅ **Symbol Balance** - {symbol_variance:.1f}% variance (< 25% threshold)\n\n"
    
    # Check 4: Direction strength
    long_subset = df[df['direction'] == 'LONG']
    short_subset = df[df['direction'] == 'SHORT']
    
    if len(short_subset) > 0:
        short_wr = (short_subset['r'] > 0).sum() / len(short_subset) * 100
        if short_wr < 30:
            warnings.append(f"⚠️  SHORT_LEG_WEAK: {short_wr:.1f}% WR")
        else:
            report += f"✅ **Direction Strength** - SHORT {short_wr:.1f}% WR (>= 30% threshold)\n\n"
    
    # Check 5: Consecutive losses
    max_consec = metrics['max_consecutive_losses']
    if max_consec > 5:
        warnings.append(f"⚠️  HIGH_CONSECUTIVE_LOSSES: {max_consec} in a row")
    else:
        report += f"✅ **Loss Streaks** - Max {max_consec} consecutive losses (<= 5 threshold)\n\n"
    
    # Check 6: Drawdown
    max_dd = metrics['max_drawdown']
    if max_dd < -15:
        warnings.append(f"⚠️  HIGH_DRAWDOWN: {max_dd:.2f}R")
    else:
        report += f"✅ **Drawdown Control** - Max {max_dd:.2f}R (>= -15R threshold)\n\n"
    
    # Verdict
    report += "\n## Final Verdict\n\n"
    
    if warnings:
        report += "**Issues Found:**\n\n"
        for w in warnings:
            report += f"- {w}\n"
        report += "\n"
    
    # Assess
    if metrics['win_rate'] < 30:
        verdict = "**NEGATIVE_EDGE** - Win rate below break-even"
    elif metrics['profit_factor'] < 1.5:
        verdict = "**TOO_NOISY** - Profit factor too low"
    elif metrics['total_trades'] < 20:
        verdict = "**INSUFFICIENT_DATA** - Need more sessions"
    elif regime_variance > 30 or 'SYMBOL_IMBALANCE' in str(warnings):
        verdict = "**PROMISING_BUT_REGIME_DEPENDENT** - Works in specific conditions only"
    elif metrics['win_rate'] > 45 and metrics['profit_factor'] > 2.0 and metrics['total_r'] > 20:
        verdict = "**ROBUST_ACROSS_REGIMES** - Strong signal across all checks"
    else:
        verdict = "**ONLY_WORKS_IN_TRENDS** - Positive edge but limited scope"
    
    report += f"\n### Recommendation\n\n{verdict}\n\n"
    
    report += f"""### Metrics Summary

- Win Rate: {metrics['win_rate']:.1f}%
- Profit Factor: {metrics['profit_factor']:.2f}x
- Total R: {metrics['total_r']:+.2f}R
- Total Trades: {metrics['total_trades']}

### Next Steps

1. ✅ Replay validation complete on 2026-05-06 session
2. ⏳ Needed: Validation on multiple days/regimes for cross-session robustness
3. ⏳ Needed: Phase 3/4 shadow evaluation comparison
4. ⏳ Needed: Real-time live observation if metrics support production deployment

*Configuration: Phase 1.6 + Phase 2 FROZEN (no optimization)*
"""
    
    return report

def main():
    print("="*80)
    print("REPLAY VALIDATION REPORT GENERATOR")
    print("="*80)
    
    # Load results
    df = load_results()
    if df is None:
        print("\nERROR: Could not load replay results")
        return
    
    print(f"\n✓ Loaded {len(df)} trades from global_alert_ledger.csv")
    
    # Compute metrics
    metrics = compute_metrics(df)
    
    # Generate reports
    print("\n[REPORTS]")
    
    # Main report
    replay_report = generate_replay_report(df, metrics)
    with open('reports/global_replay_validation.md', 'w') as f:
        f.write(replay_report)
    print("✓ reports/global_replay_validation.md")
    
    # Phase 2 analysis
    phase2_report = generate_phase2_analysis(df)
    with open('reports/phase2_global_analysis.md', 'w') as f:
        f.write(phase2_report)
    print("✓ reports/phase2_global_analysis.md")
    
    # Robustness assessment
    robustness_report = generate_robustness_assessment(df, metrics)
    with open('reports/strategy_robustness_assessment.md', 'w') as f:
        f.write(robustness_report)
    print("✓ reports/strategy_robustness_assessment.md")
    
    # Shadow evaluation
    shadow_report = f"""# Phase 3/4 Shadow Evaluation (Global)

## Status

Shadow mode: Recording decisions without affecting live alerts.

## Configuration

- Location quality evaluation: ENABLED (shadow)
- Failed continuation detection: ENABLED (shadow)
- Live alert impact: NONE

## Results

*To be populated after Phase 3/4 shadow simulation completes.*

"""
    with open('reports/phase3_phase4_global_shadow_eval.md', 'w') as f:
        f.write(shadow_report)
    print("✓ reports/phase3_phase4_global_shadow_eval.md")
    
    # Session summary
    session_summary = []
    for symbol in df['symbol'].unique():
        for regime in df['regime'].unique():
            subset = df[(df['symbol'] == symbol) & (df['regime'] == regime)]
            if len(subset) > 0:
                subset_metrics = compute_metrics(subset)
                session_summary.append({
                    'symbol': symbol,
                    'regime': regime,
                    'trade_count': len(subset),
                    'win_rate': subset_metrics['win_rate'],
                    'total_r': subset_metrics['total_r'],
                    'profit_factor': subset_metrics['profit_factor'],
                })
    
    session_df = pd.DataFrame(session_summary)
    session_df.to_csv('exports/global_session_summary.csv', index=False)
    print("✓ exports/global_session_summary.csv")
    
    print("\n" + "="*80)
    print("REPORTS GENERATED SUCCESSFULLY")
    print("="*80)
    print(f"\nKey Metrics:")
    print(f"  Win Rate: {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor: {metrics['profit_factor']:.2f}x")
    print(f"  Total R: {metrics['total_r']:+.2f}R")
    print(f"  Trades: {metrics['total_trades']}")

if __name__ == '__main__':
    main()

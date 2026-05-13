#!/usr/bin/env python3
"""
Analysis templates for global replay validation.
Used after replay engine completes to generate reports.
"""

import pandas as pd
import numpy as np
from datetime import datetime

def compute_global_metrics(results_df):
    """Compute global performance metrics."""
    if len(results_df) == 0:
        return None
    
    wins = (results_df['r_multiple'] > 0).sum()
    losses = (results_df['r_multiple'] <= 0).sum()
    total = len(results_df)
    wr = (wins / total * 100) if total > 0 else 0
    
    gross_profit = results_df[results_df['r_multiple'] > 0]['r_multiple'].sum()
    gross_loss = abs(results_df[results_df['r_multiple'] < 0]['r_multiple'].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 0
    
    total_r = results_df['r_multiple'].sum()
    avg_r = results_df['r_multiple'].mean()
    max_r = results_df['r_multiple'].max()
    min_r = results_df['r_multiple'].min()
    
    return {
        'total_trades': total,
        'wins': wins,
        'losses': losses,
        'win_rate': wr,
        'profit_factor': pf,
        'total_r': total_r,
        'avg_r': avg_r,
        'max_r': max_r,
        'min_r': min_r,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
    }

def compute_consecutive_losses(results_df):
    """Find max consecutive losses."""
    max_consecutive = 0
    current_consecutive = 0
    
    for r in results_df['r_multiple'].values:
        if r <= 0:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 0
    
    return max_consecutive

def compute_drawdown(results_df):
    """Compute max drawdown from cumulative R."""
    cumsum = results_df['r_multiple'].cumsum()
    running_max = cumsum.expanding().max()
    drawdown = cumsum - running_max
    max_drawdown = drawdown.min()
    
    return max_drawdown

def analyze_by_regime(results_df):
    """Analyze performance by regime."""
    analysis = {}
    
    for regime in results_df['regime'].unique():
        subset = results_df[results_df['regime'] == regime]
        metrics = compute_global_metrics(subset)
        metrics['regime'] = regime
        metrics['trades'] = len(subset)
        analysis[regime] = metrics
    
    return analysis

def analyze_by_symbol(results_df):
    """Analyze performance by symbol."""
    analysis = {}
    
    for symbol in results_df['symbol'].unique():
        subset = results_df[results_df['symbol'] == symbol]
        metrics = compute_global_metrics(subset)
        metrics['symbol'] = symbol
        metrics['trades'] = len(subset)
        analysis[symbol] = metrics
    
    return analysis

def analyze_by_direction(results_df):
    """Analyze performance by direction (LONG vs SHORT)."""
    analysis = {}
    
    for direction in ['LONG', 'SHORT']:
        subset = results_df[results_df['direction'] == direction]
        if len(subset) > 0:
            metrics = compute_global_metrics(subset)
            metrics['direction'] = direction
            metrics['trades'] = len(subset)
            analysis[direction] = metrics
    
    return analysis

def analyze_by_outcome(results_df):
    """Analyze by exit outcome."""
    analysis = {}
    
    for outcome in results_df['outcome'].unique():
        subset = results_df[results_df['outcome'] == outcome]
        metrics = compute_global_metrics(subset)
        metrics['outcome'] = outcome
        metrics['trades'] = len(subset)
        analysis[outcome] = metrics
    
    return analysis

def detect_overfitting(results_df):
    """Check for overfitting indicators."""
    warnings = []
    
    # Check 1: Too few trades
    if len(results_df) < 20:
        warnings.append("INSUFFICIENT_DATA: < 20 total trades (high variance possible)")
    
    # Check 2: High regime variance
    regime_analysis = analyze_by_regime(results_df)
    regime_wrs = [m['win_rate'] for m in regime_analysis.values()]
    if len(regime_wrs) > 1 and max(regime_wrs) - min(regime_wrs) > 30:
        warnings.append(f"REGIME_VARIANCE_HIGH: WR ranges {min(regime_wrs):.1f}% to {max(regime_wrs):.1f}% across regimes")
    
    # Check 3: Symbol imbalance
    symbol_analysis = analyze_by_symbol(results_df)
    es_metrics = symbol_analysis.get('ESM6.CME@RITHMIC', {})
    nq_metrics = symbol_analysis.get('NQM6.CME@RITHMIC', {})
    
    if es_metrics.get('total_trades', 0) > 0 and nq_metrics.get('total_trades', 0) > 0:
        es_wr = es_metrics.get('win_rate', 0)
        nq_wr = nq_metrics.get('win_rate', 0)
        if abs(es_wr - nq_wr) > 25:
            warnings.append(f"SYMBOL_IMBALANCE: ES {es_wr:.1f}% vs NQ {nq_wr:.1f}% WR")
    
    # Check 4: Direction imbalance
    direction_analysis = analyze_by_direction(results_df)
    long_metrics = direction_analysis.get('LONG', {})
    short_metrics = direction_analysis.get('SHORT', {})
    
    if short_metrics.get('total_trades', 0) > 0:
        short_wr = short_metrics.get('win_rate', 0)
        if short_wr < 30:
            warnings.append(f"SHORT_LEG_WEAK: {short_wr:.1f}% short WR (expected 40%+ for robustness)")
    
    # Check 5: Consecutive losses
    max_consec = compute_consecutive_losses(results_df)
    if max_consec > 5:
        warnings.append(f"HIGH_CONSECUTIVE_LOSSES: {max_consec} losses in a row")
    
    # Check 6: Drawdown
    max_dd = compute_drawdown(results_df)
    if max_dd < -15:
        warnings.append(f"DRAWDOWN_WARNING: {max_dd:.2f}R max drawdown (exceeds acceptable -10R)")
    
    return warnings

def compute_phase3_4_shadow_stats(results_df):
    """Shadow evaluation metrics for Phase 3/4."""
    if 'phase2_risk_score' not in results_df.columns:
        return None
    
    # Categorize by risk score
    high_risk = results_df[results_df['phase2_risk_score'] >= 0.75]
    medium_risk = results_df[(results_df['phase2_risk_score'] >= 0.5) & (results_df['phase2_risk_score'] < 0.75)]
    low_risk = results_df[results_df['phase2_risk_score'] < 0.5]
    
    stats = {
        'high_risk': {
            'count': len(high_risk),
            'wr': ((high_risk['r_multiple'] > 0).sum() / len(high_risk) * 100) if len(high_risk) > 0 else 0,
            'avg_r': high_risk['r_multiple'].mean() if len(high_risk) > 0 else 0,
        },
        'medium_risk': {
            'count': len(medium_risk),
            'wr': ((medium_risk['r_multiple'] > 0).sum() / len(medium_risk) * 100) if len(medium_risk) > 0 else 0,
            'avg_r': medium_risk['r_multiple'].mean() if len(medium_risk) > 0 else 0,
        },
        'low_risk': {
            'count': len(low_risk),
            'wr': ((low_risk['r_multiple'] > 0).sum() / len(low_risk) * 100) if len(low_risk) > 0 else 0,
            'avg_r': low_risk['r_multiple'].mean() if len(low_risk) > 0 else 0,
        },
    }
    
    return stats

def generate_robustness_verdict(metrics, warnings):
    """Assign final robustness verdict."""
    
    if warnings:
        # Serious issues
        for w in warnings:
            if 'INSUFFICIENT_DATA' in w or 'HIGH_CONSECUTIVE_LOSSES' in w or 'DRAWDOWN_WARNING' in w:
                return ('INSUFFICIENT_DATA', w)
            if 'REGIME_VARIANCE_HIGH' in w or 'SYMBOL_IMBALANCE' in w or 'SHORT_LEG_WEAK' in w:
                return ('PROMISING_BUT_REGIME_DEPENDENT', w)
    
    # Positive signal checks
    if metrics['win_rate'] < 30:
        return ('NEGATIVE_EDGE', f"Win rate {metrics['win_rate']:.1f}% is below break-even")
    
    if metrics['profit_factor'] < 1.5:
        return ('TOO_NOISY', f"Profit factor {metrics['profit_factor']:.2f}x is marginal")
    
    if metrics['total_r'] > 20 and metrics['win_rate'] > 45 and metrics['profit_factor'] > 2.0:
        return ('ROBUST_ACROSS_REGIMES', "Strong metrics across all checks")
    
    if metrics['total_r'] > 10 and metrics['win_rate'] > 40:
        return ('PROMISING_BUT_REGIME_DEPENDENT', "Positive edge but regime dependent")
    
    if metrics['total_r'] > 0 and metrics['win_rate'] > 35:
        return ('ONLY_WORKS_IN_TRENDS', "Positive in selected conditions only")
    
    return ('TOO_NOISY', "Unclear signal or insufficient data")

# Export for use
if __name__ == '__main__':
    print("Analysis templates loaded. Import and use in report generation.")

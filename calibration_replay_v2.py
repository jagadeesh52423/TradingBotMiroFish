#!/usr/bin/env python3
"""
Calibration Replay Engine v2
Full regime detection logic mirrored from regime_detector.py
"""
import json
import sys
import os
from collections import defaultdict, deque
from datetime import datetime
from typing import List, Dict, Optional
import statistics

DATA_PATH = "./market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl"

class RegimeDetector:
    """Full regime detection logic."""
    def __init__(self, volatility_threshold: float = 0.02):
        self.volatility_threshold = volatility_threshold
        self.ma_short_period = 5
        self.ma_long_period = 20
        self.atr_period = 14
        
        self.price_buffer = deque(maxlen=self.ma_long_period + 10)
        self.high_buffer = deque(maxlen=self.atr_period + 10)
        self.low_buffer = deque(maxlen=self.atr_period + 10)
        self.tr_buffer = deque(maxlen=self.atr_period + 10)
        
        self.last_close = None
        self.regime_history = []
    
    def update(self, close: float, high: float, low: float) -> Optional[str]:
        """Update detector and return regime."""
        self.price_buffer.append(close)
        self.high_buffer.append(high)
        self.low_buffer.append(low)
        
        # True range
        if self.last_close is not None:
            tr = max(high - low, abs(high - self.last_close), abs(low - self.last_close))
        else:
            tr = high - low
        
        self.tr_buffer.append(tr)
        self.last_close = close
        
        # Need minimum data
        if len(self.price_buffer) < self.ma_long_period:
            return None
        
        # Calculate metrics
        prices = list(self.price_buffer)
        short_ma = statistics.mean(prices[-self.ma_short_period:])
        long_ma = statistics.mean(prices[-self.ma_long_period:])
        
        # ATR
        if len(self.tr_buffer) >= self.atr_period:
            atr = statistics.mean(list(self.tr_buffer)[-self.atr_period:])
        else:
            atr = statistics.mean(list(self.tr_buffer)) if self.tr_buffer else 0
        
        # Volatility
        volatility = atr / close if close > 0 else 0
        
        # Slope
        recent = prices[-10:]
        if len(recent) >= 2:
            x = list(range(len(recent)))
            y = recent
            n = len(x)
            slope = (n * sum(x[i] * y[i] for i in range(n)) - sum(x) * sum(y)) / (n * sum(x[i]**2 for i in range(n)) - sum(x)**2)
        else:
            slope = 0
        
        # Support/resistance
        support = min(list(self.low_buffer)[-20:]) if len(self.low_buffer) >= 20 else low
        resistance = max(list(self.high_buffer)[-20:]) if len(self.high_buffer) >= 20 else high
        
        # Regime detection (matching regime_detector.py logic)
        if volatility > self.volatility_threshold:
            if slope > 0 and close > resistance:
                regime = "BREAKOUT"
            elif slope < 0 and close < support:
                regime = "BREAKDOWN"
            else:
                regime = "HIGH_VOL"
        else:
            if short_ma > long_ma and slope > 0:
                regime = "UPTREND"
            elif short_ma < long_ma and slope < 0:
                regime = "DOWNTREND"
            else:
                regime = "BALANCE"
        
        self.regime_history.append(regime)
        return regime


class ReplayMetrics:
    """Metrics tracker."""
    def __init__(self, config_name: str, threshold: float):
        self.config_name = config_name
        self.threshold = threshold
        self.regime_counts = defaultdict(int)
        self.regimes = []
        self.total_bars = 0
        
    def record_regime(self, regime: str):
        """Record regime classification."""
        if regime:
            self.regime_counts[regime] += 1
            self.regimes.append(regime)
            self.total_bars += 1
    
    def get_summary(self) -> Dict:
        """Get metrics."""
        total = self.total_bars if self.total_bars > 0 else 1
        
        balance_pct = 100 * self.regime_counts.get('BALANCE', 0) / total
        breakout_pct = 100 * self.regime_counts.get('BREAKOUT', 0) / total
        breakdown_pct = 100 * self.regime_counts.get('BREAKDOWN', 0) / total
        uptrend_pct = 100 * self.regime_counts.get('UPTREND', 0) / total
        downtrend_pct = 100 * self.regime_counts.get('DOWNTREND', 0) / total
        high_vol_pct = 100 * self.regime_counts.get('HIGH_VOL', 0) / total
        
        return {
            'config_name': self.config_name,
            'threshold': self.threshold,
            'total_bars': total,
            'balance_pct': balance_pct,
            'breakout_pct': breakout_pct,
            'breakdown_pct': breakdown_pct,
            'uptrend_pct': uptrend_pct,
            'downtrend_pct': downtrend_pct,
            'high_vol_pct': high_vol_pct,
            'regime_distribution': dict(self.regime_counts),
        }


def load_nq_events(max_bars: int = 1000) -> Dict:
    """Load NQ events grouped by minute bars."""
    print(f"\n=== STEP 1: LOAD & FILTER ===", file=sys.stderr)
    print(f"  Loading from {DATA_PATH}...", file=sys.stderr)
    
    bars = defaultdict(lambda: {'prices': [], 'high': 0, 'low': float('inf'), 'volume': 0})
    nq_count = 0
    es_count = 0
    total = 0
    
    with open(DATA_PATH, 'r') as f:
        for line in f:
            try:
                event = json.loads(line)
                symbol = event.get('symbol', '')
                ts = event.get('ts_event', '')
                price = float(event.get('price', 0))
                size = int(event.get('size', 0))
                
                total += 1
                
                if 'NQ' in symbol:
                    nq_count += 1
                    # Group to minute bars
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    bar_key = dt.replace(second=0, microsecond=0).isoformat()
                    
                    bars[bar_key]['prices'].append(price)
                    bars[bar_key]['high'] = max(bars[bar_key]['high'], price)
                    bars[bar_key]['low'] = min(bars[bar_key]['low'], price)
                    bars[bar_key]['volume'] += size
                    
                    if len(bars) >= max_bars:
                        break
                elif 'ES' in symbol:
                    es_count += 1
                
                if total % 500000 == 0:
                    print(f"    Scanned {total:,}, NQ bars: {len(bars)}", file=sys.stderr)
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
    
    print(f"✓ Loaded {total:,} events: {nq_count:,} NQ (in {len(bars)} bars) | {es_count:,} ES (EXCLUDED)", 
          file=sys.stderr)
    return bars


def replay_with_threshold(bars: Dict, threshold: float, config_name: str) -> ReplayMetrics:
    """Run replay with regime detector at given threshold."""
    print(f"\n=== REPLAY: {config_name} (threshold={threshold}) ===", file=sys.stderr)
    
    metrics = ReplayMetrics(config_name, threshold)
    detector = RegimeDetector(volatility_threshold=threshold)
    
    bar_count = 0
    for bar_key in sorted(bars.keys()):
        bar_data = bars[bar_key]
        if not bar_data['prices']:
            continue
        
        # OHLC
        close = bar_data['prices'][-1]
        high = bar_data['high']
        low = bar_data['low']
        
        # Detect regime
        regime = detector.update(close, high, low)
        if regime:
            metrics.record_regime(regime)
            bar_count += 1
    
    summary = metrics.get_summary()
    print(f"✓ Processed {bar_count} bars", file=sys.stderr)
    print(f"  BALANCE: {summary['balance_pct']:.1f}%", file=sys.stderr)
    print(f"  BREAKOUT: {summary['breakout_pct']:.1f}%", file=sys.stderr)
    print(f"  BREAKDOWN: {summary['breakdown_pct']:.1f}%", file=sys.stderr)
    print(f"  UPTREND: {summary['uptrend_pct']:.1f}%", file=sys.stderr)
    print(f"  DOWNTREND: {summary['downtrend_pct']:.1f}%", file=sys.stderr)
    print(f"  HIGH_VOL: {summary['high_vol_pct']:.1f}%", file=sys.stderr)
    
    return metrics


def main():
    print("🔍 CALIBRATION VALIDATION: Threshold 0.02 → 0.008 (ES Disabled)", file=sys.stderr)
    
    # Load data
    bars = load_nq_events(max_bars=5000)
    
    if not bars:
        print("ERROR: No bars loaded!", file=sys.stderr)
        return
    
    # Config A: 0.02 (baseline broken)
    config_a = replay_with_threshold(bars, threshold=0.02, config_name="CONFIG_A_BASELINE")
    
    # Config B: 0.008 (proposed fix)
    config_b = replay_with_threshold(bars, threshold=0.008, config_name="CONFIG_B_FIXED")
    
    # Comparison
    print(f"\n=== STEP 5: COMPARISON ===", file=sys.stderr)
    
    summary_a = config_a.get_summary()
    summary_b = config_b.get_summary()
    
    balance_a = summary_a['balance_pct']
    balance_b = summary_b['balance_pct']
    balance_change = balance_b - balance_a
    balance_pct_reduction = (1 - balance_b / balance_a) * 100 if balance_a > 0 else 0
    
    print(f"\n  BALANCE %: A={balance_a:.1f}% → B={balance_b:.1f}% "
          f"(Δ={balance_change:+.1f}%, reduction={balance_pct_reduction:.1f}%)", file=sys.stderr)
    print(f"  BREAKOUT %: A={summary_a['breakout_pct']:.1f}% → B={summary_b['breakout_pct']:.1f}%", 
          file=sys.stderr)
    print(f"  BREAKDOWN %: A={summary_a['breakdown_pct']:.1f}% → B={summary_b['breakdown_pct']:.1f}%", 
          file=sys.stderr)
    
    # Deployment check
    print(f"\n=== DEPLOYMENT CRITERIA CHECK ===", file=sys.stderr)
    
    checks = []
    
    # BALANCE should decrease significantly
    check1 = balance_pct_reduction > 20
    checks.append(("BALANCE % reduces >20%", check1, f"{balance_pct_reduction:.1f}%"))
    
    # BREAKOUT + BREAKDOWN shouldn't explode in B
    breakout_a = summary_a['breakout_pct']
    breakout_b = summary_b['breakout_pct']
    breakdown_a = summary_a['breakdown_pct']
    breakdown_b = summary_b['breakdown_pct']
    
    breakout_stable = breakout_b <= breakout_a * 1.5
    breakdown_stable = breakdown_b <= breakdown_a * 1.5
    
    checks.append(("BREAKOUT stable (B ≤ A*1.5)", breakout_stable, f"A={breakout_a:.1f}% → B={breakout_b:.1f}%"))
    checks.append(("BREAKDOWN stable (B ≤ A*1.5)", breakdown_stable, f"A={breakdown_a:.1f}% → B={breakdown_b:.1f}%"))
    
    for check_name, passed, detail in checks:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {check_name} ({detail})", file=sys.stderr)
    
    # Verdict
    print(f"\n=== FINAL VERDICT ===", file=sys.stderr)
    
    all_pass = all(c[1] for c in checks)
    
    if all_pass:
        print("✓ CALIBRATION_FIX_APPROVED", file=sys.stderr)
        verdict = "APPROVED"
    elif balance_pct_reduction > 10:
        print("⚠ PARTIAL_IMPROVEMENT (mixed results)", file=sys.stderr)
        verdict = "PARTIAL"
    else:
        print("✗ CALIBRATION_FIX_REJECTED", file=sys.stderr)
        verdict = "REJECTED"
    
    print(f"\nReason: BALANCE reduction = {balance_pct_reduction:.1f}%", file=sys.stderr)
    
    return verdict


if __name__ == "__main__":
    main()

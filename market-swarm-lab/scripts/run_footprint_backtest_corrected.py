#!/usr/bin/env python3
"""
Corrected Footprint Backtest - NO LOOKAHEAD BIAS

This version:
1. Loads REAL footprint signals from May 4 (2026-05-04 19:06-19:28 UTC)
2. Matches real ESM6 price data from May 4 JSONL
3. Sets stops/targets at signal time (no future knowledge)
4. Uses actual fill prices (stop/target triggered, not best in window)
5. Models slippage, spread, and realistic fills
6. Validates for lookahead bias red flags

Critical: This replaces the invalid synthetic backtest.
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import csv

# Paths
SIGNALS_CSV = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/live/footprint_entry_candidates.csv")
JSONL_DIR = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api")
RESULTS_DIR = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/backtest_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Constants
TICK_SIZE = 0.25
SLIPPAGE_TICKS = 2  # Assume 2-tick slip on market orders
SPREAD_TICKS = 1    # Typical ES spread
SYMBOL = "ESM6.CME@RITHMIC"


class CorrectedFootprintBacktest:
    def __init__(self):
        self.signals = []
        self.results = []
        self.stats = {}
        self.price_cache = {}
    
    def load_real_signals(self):
        """Load real May 4 footprint signals."""
        print("[*] Loading real footprint signals from May 4...")
        df = pd.read_csv(SIGNALS_CSV)
        df['ts_event'] = pd.to_datetime(df['ts_event'])
        
        # Filter to May 4 only
        df = df[df['ts_event'].dt.date == pd.Timestamp("2026-05-04").date()]
        
        # Deduplicate by exact timestamp (keep first)
        df = df.drop_duplicates(subset=['ts_event'], keep='first')
        
        self.signals = df.to_dict('records')
        print(f"[✓] Loaded {len(self.signals)} real signals from May 4 19:06-19:28 UTC")
        
        return len(self.signals)
    
    def load_trade_window_from_jsonl(self, ts_start: datetime, ts_end: datetime) -> List[Dict]:
        """
        Load trades from JSONL for given window.
        Only loads ESM6 trades that occur AFTER ts_start (no lookahead).
        """
        trades = []
        
        # Determine which JSONL file(s) to scan
        files_to_scan = []
        for fpath in sorted(JSONL_DIR.glob("es_orderflow_*.jsonl")):
            # Extract date from filename
            file_date_str = fpath.stem.split('_')[-1]
            try:
                fdate = datetime.strptime(file_date_str, "%Y-%m-%d")
                if fdate.date() == ts_end.date():
                    files_to_scan.append(fpath)
            except:
                pass
        
        for fpath in files_to_scan:
            with open(fpath, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                    except:
                        continue
                    
                    # Only ESM6 trades
                    if data.get('event_type') != 'trade':
                        continue
                    if data.get('symbol') != SYMBOL:
                        continue
                    if not data.get('price'):
                        continue
                    
                    try:
                        ts = datetime.fromisoformat(data['ts_event'].replace('Z', '+00:00'))
                    except:
                        continue
                    
                    # CRITICAL: Only include trades AFTER signal (no lookahead)
                    if ts > ts_start and ts <= ts_end:
                        trades.append({
                            'ts': ts,
                            'price': float(data['price']),
                            'size': int(data.get('size', 0)),
                            'side': data.get('side', '')
                        })
        
        return sorted(trades, key=lambda x: x['ts'])
    
    def calculate_volatility(self, trades_before: List[Dict]) -> float:
        """Calculate volatility from historical trades."""
        if not trades_before:
            return TICK_SIZE  # Default
        
        prices = [t['price'] for t in trades_before]
        if len(prices) < 2:
            return TICK_SIZE
        
        return np.std(prices)
    
    def backtest_signal(self, signal: Dict) -> Optional[Dict]:
        """
        Backtest a single real signal without lookahead bias.
        
        Returns dict with:
        - entry_price, stop_price, target_prices
        - outcome (WIN/LOSS/STOP_HIT/TARGET_HIT/TIMEOUT)
        - actual_exit_price, pnl, r_multiple
        - time_to_fill, mae, mfe
        """
        
        entry_ts = pd.to_datetime(signal['ts_event'])
        entry_price = signal['entry_price']
        direction = signal['direction']
        confidence = signal.get('confidence', 0)
        
        # Load lookback for volatility (BEFORE signal)
        lookback_start = entry_ts - timedelta(minutes=15)
        lookback_trades = self.load_trade_window_from_jsonl(lookback_start, entry_ts)
        
        if not lookback_trades:
            lookback_vol = TICK_SIZE
        else:
            lookback_vol = self.calculate_volatility(lookback_trades)
        
        # Set stops and targets AT ENTRY TIME (no future knowledge)
        # Conservative: stop = 1x vol, targets = 2x and 3x vol
        stop_distance = max(TICK_SIZE * 2, lookback_vol * 1.0)
        target1_distance = max(TICK_SIZE * 4, lookback_vol * 2.0)
        target2_distance = max(TICK_SIZE * 6, lookback_vol * 3.0)
        
        if direction == 'SHORT':
            stop_price = entry_price + stop_distance
            target1_price = entry_price - target1_distance
            target2_price = entry_price - target2_distance
        else:  # LONG
            stop_price = entry_price - stop_distance
            target1_price = entry_price + target1_distance
            target2_price = entry_price + target2_distance
        
        # Load price action AFTER signal (no lookahead)
        # Window: entry to +30 minutes forward
        forward_end = entry_ts + timedelta(minutes=30)
        trades_after = self.load_trade_window_from_jsonl(entry_ts, forward_end)
        
        if not trades_after:
            return None  # No data available
        
        # Track outcome
        result = {
            'ts_event': entry_ts,
            'direction': direction,
            'confidence': confidence,
            'setup_type': signal.get('setup_type', 'unknown'),
            'entry_price': entry_price,
            'stop_price': stop_price,
            'target1_price': target1_price,
            'target2_price': target2_price,
        }
        
        # Simulate realistic fill with slippage
        entry_price_filled = entry_price + (SLIPPAGE_TICKS * TICK_SIZE) * (1 if direction == 'SHORT' else -1)
        
        # Add spread cost at exit
        spread_cost = SPREAD_TICKS * TICK_SIZE
        
        # Track extremes and find exit
        mfe = 0
        mae = 0
        outcome = None
        exit_price = None
        time_to_exit = None
        
        for idx, trade in enumerate(trades_after):
            price = trade['price']
            ts = trade['ts']
            time_delta_min = (ts - entry_ts).total_seconds() / 60.0
            
            # Track max excursions
            if direction == 'SHORT':
                move = entry_price - price
                adverse_move = price - entry_price
                if move > mfe:
                    mfe = move
                if adverse_move > mae:
                    mae = adverse_move
                
                # Check stop hit (stop is above entry for short)
                if price >= stop_price:
                    if outcome is None:
                        # STOP HIT - exit at stop + slippage
                        exit_price = stop_price + (SLIPPAGE_TICKS * TICK_SIZE)
                        outcome = 'STOP_HIT'
                        time_to_exit = time_delta_min
                
                # Check target hits (targets below entry for short)
                if price <= target2_price:
                    if outcome is None:
                        exit_price = target2_price - (SLIPPAGE_TICKS * TICK_SIZE)
                        outcome = 'TARGET2_HIT'
                        time_to_exit = time_delta_min
                elif price <= target1_price:
                    if outcome is None:
                        exit_price = target1_price - (SLIPPAGE_TICKS * TICK_SIZE)
                        outcome = 'TARGET1_HIT'
                        time_to_exit = time_delta_min
            
            else:  # LONG
                move = price - entry_price
                adverse_move = entry_price - price
                if move > mfe:
                    mfe = move
                if adverse_move > mae:
                    mae = adverse_move
                
                # Check stop hit (stop is below entry for long)
                if price <= stop_price:
                    if outcome is None:
                        exit_price = stop_price - (SLIPPAGE_TICKS * TICK_SIZE)
                        outcome = 'STOP_HIT'
                        time_to_exit = time_delta_min
                
                # Check target hits
                if price >= target2_price:
                    if outcome is None:
                        exit_price = target2_price + (SLIPPAGE_TICKS * TICK_SIZE)
                        outcome = 'TARGET2_HIT'
                        time_to_exit = time_delta_min
                elif price >= target1_price:
                    if outcome is None:
                        exit_price = target1_price + (SLIPPAGE_TICKS * TICK_SIZE)
                        outcome = 'TARGET1_HIT'
                        time_to_exit = time_delta_min
        
        # If no stop/target hit, exit at last price (timeout)
        if outcome is None:
            exit_price = trades_after[-1]['price']
            outcome = 'TIMEOUT'
            time_to_exit = 30  # Full window
        
        # Calculate PnL and R-multiple
        if direction == 'SHORT':
            pnl = entry_price - exit_price
        else:
            pnl = exit_price - entry_price
        
        # Apply costs
        pnl -= spread_cost
        
        # Calculate R (using intended stop distance as risk)
        risk = stop_distance
        r_multiple = pnl / risk if risk > 0 else 0
        
        result['exit_price'] = exit_price
        result['outcome'] = outcome
        result['pnl'] = pnl
        result['pnl_ticks'] = pnl / TICK_SIZE
        result['r_multiple'] = r_multiple
        result['mae'] = mae
        result['mfe'] = mfe
        result['time_to_exit_min'] = time_to_exit
        result['slippage_applied'] = SLIPPAGE_TICKS * TICK_SIZE
        result['spread_cost'] = spread_cost
        result['volatility_basis'] = lookback_vol
        
        return result
    
    def run_backtest(self, max_signals: Optional[int] = None):
        """Run backtest on all real signals."""
        signals = self.signals
        if max_signals:
            signals = signals[:max_signals]
        
        print(f"\n[*] Backtesting {len(signals)} real signals (with NO lookahead bias)...")
        
        for i, signal in enumerate(signals):
            if i % 10 == 0:
                print(f"  [{i+1}/{len(signals)}] Signal at {signal['ts_event']}...")
            
            result = self.backtest_signal(signal)
            if result:
                self.results.append(result)
        
        print(f"[✓] Completed {len(self.results)} evaluations")
        return len(self.results)
    
    def compute_statistics(self):
        """Compute statistics with lookahead bias detection."""
        print("\n[*] Computing statistics...")
        
        if not self.results:
            print("[!] No results to analyze")
            return {}
        
        df = pd.DataFrame(self.results)
        
        # Lookahead bias detection
        win_rate = (df['outcome'].isin(['TARGET1_HIT', 'TARGET2_HIT'])).sum() / len(df)
        pf = df[df['pnl'] > 0]['pnl'].sum() / abs(df[df['pnl'] < 0]['pnl'].sum()) if len(df[df['pnl'] < 0]) > 0 else 0
        max_dd = df['mae'].max()
        
        stats = {
            'total_signals': len(df),
            'signals_evaluated': len(df),
            'win_rate': win_rate,
            'stop_hit_count': (df['outcome'] == 'STOP_HIT').sum(),
            'target_hit_count': (df['outcome'].isin(['TARGET1_HIT', 'TARGET2_HIT'])).sum(),
            'timeout_count': (df['outcome'] == 'TIMEOUT').sum(),
            'avg_pnl': df['pnl'].mean(),
            'avg_pnl_ticks': df['pnl_ticks'].mean(),
            'avg_r_multiple': df['r_multiple'].mean(),
            'avg_mae': df['mae'].mean(),
            'avg_mfe': df['mfe'].mean(),
            'max_mae': df['mae'].max(),
            'max_mfe': df['mfe'].max(),
            'profit_factor': pf,
            'total_pnl': df['pnl'].sum(),
            'max_dd': max_dd,
        }
        
        # Red flags
        stats['lookahead_risk'] = 'NORMAL' if win_rate < 0.65 else 'WARNING' if win_rate < 0.75 else 'HIGH'
        stats['validity'] = 'QUESTIONABLE' if (win_rate > 0.80 or pf > 10) else 'VALID'
        
        self.stats = stats
        
        print("\n" + "="*60)
        print("CORRECTED BACKTEST STATISTICS (NO LOOKAHEAD)")
        print("="*60)
        print(f"Total Signals: {stats['total_signals']}")
        print(f"Win Rate (targets hit): {stats['win_rate']*100:.1f}%")
        print(f"Avg PnL: {stats['avg_pnl']:.4f} ({stats['avg_pnl_ticks']:.1f} ticks)")
        print(f"Avg R-Multiple: {stats['avg_r_multiple']:.2f}R")
        print(f"Profit Factor: {stats['profit_factor']:.2f}x")
        print(f"Total PnL: {stats['total_pnl']:.4f}")
        print(f"Avg MAE: {stats['avg_mae']:.4f} | Avg MFE: {stats['avg_mfe']:.4f}")
        print(f"\nLookahead Risk Level: {stats['lookahead_risk']}")
        print(f"Validity: {stats['validity']}")
        print("="*60)
        
        return stats
    
    def save_results(self):
        """Save corrected results."""
        print("\n[*] Saving corrected results...")
        
        df = pd.DataFrame(self.results)
        
        # Save CSV
        csv_path = RESULTS_DIR / "footprint_backtest_corrected_results.csv"
        df.to_csv(csv_path, index=False)
        print(f"[✓] Saved: {csv_path}")
        
        # Save markdown report
        report_path = RESULTS_DIR / "footprint_backtest_corrected_report.md"
        with open(report_path, 'w') as f:
            f.write("# Corrected Footprint Backtest Report (NO LOOKAHEAD BIAS)\n\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
            
            f.write("## Overview\n\n")
            f.write(f"- **Real Signals Tested:** {self.stats['total_signals']}\n")
            f.write(f"- **Date:** May 4, 2026\n")
            f.write(f"- **Time Window:** 19:06-19:28 UTC\n")
            f.write(f"- **Slippage Modeled:** {SLIPPAGE_TICKS} ticks\n")
            f.write(f"- **Spread Modeled:** {SPREAD_TICKS} ticks\n\n")
            
            f.write("## Results\n\n")
            f.write(f"| Metric | Value |\n")
            f.write(f"|--------|-------|\n")
            f.write(f"| Win Rate | {self.stats['win_rate']*100:.1f}% |\n")
            f.write(f"| Avg PnL | {self.stats['avg_pnl']:.4f} |\n")
            f.write(f"| Avg R-Multiple | {self.stats['avg_r_multiple']:.2f}R |\n")
            f.write(f"| Profit Factor | {self.stats['profit_factor']:.2f}x |\n")
            f.write(f"| Avg MAE | {self.stats['avg_mae']:.4f} |\n")
            f.write(f"| Avg MFE | {self.stats['avg_mfe']:.4f} |\n\n")
            
            f.write("## Validity Assessment\n\n")
            f.write(f"**Lookahead Risk:** {self.stats['lookahead_risk']}\n")
            f.write(f"**Conclusion:** {self.stats['validity']}\n\n")
            
            if self.stats['validity'] == 'VALID':
                f.write("✅ This backtest passes basic validity checks.\n\n")
            else:
                f.write("⚠️ **WARNING:** This backtest may have residual bias. Use with caution.\n\n")
        
        print(f"[✓] Saved: {report_path}")
        
        return str(csv_path), str(report_path)


def main():
    bt = CorrectedFootprintBacktest()
    
    signal_count = bt.load_real_signals()
    if signal_count == 0:
        print("[!] No real signals found. Cannot proceed.")
        return
    
    bt.run_backtest()
    bt.compute_statistics()
    bt.save_results()
    
    print("\n[✓] Corrected backtest complete!")
    print(f"\nNote: This backtest uses REAL May 4 signals, real ESM6 data,")
    print(f"and models realistic slippage/spread. Metrics should be ~40-60% WR.")


if __name__ == "__main__":
    main()

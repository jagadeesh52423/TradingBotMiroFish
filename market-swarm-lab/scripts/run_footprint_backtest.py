#!/usr/bin/env python3
"""
Footprint Entry Backtest Engine

Validates statistical edge of new footprint-entry system without loading full 40GB file.
Uses chunked replay windows (15min before → signal → 30min after).
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import sys

# Paths
BOOKMAP_DIR = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api")
FOOTPRINT_CSV = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/live/footprint_entry_candidates.csv")
RESULTS_DIR = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/live")

# Constants
LOOKBACK_MINS = 15
LOOKFORWARD_MINS = 30
EVAL_WINDOWS = [1, 5, 15, 30]  # minutes
TICK_SIZE = 0.25


class FootprintBacktest:
    def __init__(self):
        self.signals = []
        self.trades = []
        self.results = []
        self.stats = {}
        
    def load_signals(self):
        """Load footprint entry candidates."""
        print("[*] Loading footprint signals...")
        df = pd.read_csv(FOOTPRINT_CSV)
        df['ts_event'] = pd.to_datetime(df['ts_event'])
        
        # Deduplicate by timestamp + price (multiple ticks at same level)
        df_dedup = df.groupby(df['ts_event'].dt.floor('1s')).agg({
            'direction': 'first',
            'confidence': 'mean',
            'entry_price': 'first',
            'trigger_level': 'first',
            'level_type': 'first',
            'setup_type': 'first',
            'divergence_type': 'first',
            'absorption_score': 'mean',
            'candle_delta': 'mean',
            'candle_vol': 'mean',
        }).reset_index()
        
        print(f"[✓] Loaded {len(df_dedup)} unique signals (deduped from {len(df)})")
        self.signals = df_dedup.to_dict('records')
        return len(self.signals)
    
    def load_trade_window(self, ts_start, ts_end, symbol="ESM6.CME@RITHMIC"):
        """
        Load trades from JSONL for given time window.
        Returns list of {ts, price, size, side} dicts.
        """
        trades = []
        ts_start_dt = pd.to_datetime(ts_start)
        ts_end_dt = pd.to_datetime(ts_end)
        
        # Find which file(s) to scan
        files = sorted(BOOKMAP_DIR.glob("es_orderflow_*.jsonl"))
        
        for fpath in files:
            # Quick date check
            file_date = fpath.stem.split('_')[-1]
            try:
                fdate = datetime.strptime(file_date, "%Y-%m-%d")
                if fdate.date() > ts_end_dt.date():
                    continue
                if fdate.date() < ts_start_dt.date():
                    continue
            except:
                pass
            
            print(f"  [→] Scanning {fpath.name}...")
            
            with open(fpath, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                    except:
                        continue
                    
                    # Only ESM6 trades
                    if data.get('event_type') != 'trade':
                        continue
                    if 'ESM6' not in data.get('symbol', ''):
                        continue
                    if not data.get('price'):
                        continue
                    
                    try:
                        ts = datetime.fromisoformat(data['ts_event'].replace('Z', '+00:00'))
                    except:
                        continue
                    
                    if ts_start_dt <= ts <= ts_end_dt:
                        trades.append({
                            'ts': ts,
                            'price': data['price'],
                            'size': data.get('size', 0),
                            'side': data.get('side', '')
                        })
        
        print(f"  [✓] Loaded {len(trades)} trades in window")
        return trades
    
    def evaluate_signal(self, signal):
        """
        Evaluate a single footprint signal.
        Returns dict with entry, exit, MAE, MFE, RR, etc.
        """
        entry_ts = pd.to_datetime(signal['ts_event'])
        entry_price = signal['entry_price']
        direction = signal['direction']
        confidence = signal['confidence']
        
        # Load price action: 15min before to 30min after
        ts_start = entry_ts - timedelta(minutes=LOOKBACK_MINS)
        ts_end = entry_ts + timedelta(minutes=LOOKFORWARD_MINS)
        
        trades = self.load_trade_window(ts_start, ts_end)
        
        if not trades:
            return None
        
        # Convert to DataFrame for easier manipulation
        df_trades = pd.DataFrame(trades)
        df_trades = df_trades.sort_values('ts').reset_index(drop=True)
        
        # Find trades AT or AFTER signal time (no lookahead)
        df_after = df_trades[df_trades['ts'] >= entry_ts].reset_index(drop=True)
        
        if len(df_after) == 0:
            return None
        
        # Get baseline volatility (from lookback window)
        df_before = df_trades[df_trades['ts'] < entry_ts]
        if len(df_before) > 10:
            prices_before = df_before['price'].values
            baseline_vol = np.std(prices_before)
        else:
            baseline_vol = TICK_SIZE
        
        # Set stops and targets (at entry time)
        # Conservative: stop = 1x vol, T1 = 2x vol, T2 = 3x vol
        stop_distance = max(TICK_SIZE * 2, baseline_vol * 1.0)
        target1_distance = max(TICK_SIZE * 4, baseline_vol * 2.0)
        target2_distance = max(TICK_SIZE * 6, baseline_vol * 3.0)
        
        if direction == 'SHORT':
            stop_price = entry_price + stop_distance
            target1_price = entry_price - target1_distance
            target2_price = entry_price - target2_distance
        else:  # LONG
            stop_price = entry_price - stop_distance
            target1_price = entry_price + target1_distance
            target2_price = entry_price + target2_distance
        
        # Evaluate price action
        result = {
            'ts_event': entry_ts,
            'direction': direction,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'target1_price': target1_price,
            'target2_price': target2_price,
            'confidence': confidence,
            'setup_type': signal['setup_type'],
            'divergence_type': signal.get('divergence_type', 'unknown'),
            'absorption_score': signal.get('absorption_score', 0),
            'signal_delta': signal.get('candle_delta', 0),
            'signal_vol': signal.get('candle_vol', 0),
        }
        
        # Track MFE/MAE and outcomes
        mfe = 0
        mae = 0
        stop_hit = False
        target1_hit = False
        target2_hit = False
        time_to_target = None
        time_to_stop = None
        max_favorable = entry_price if direction == 'SHORT' else entry_price
        max_adverse = entry_price if direction == 'SHORT' else entry_price
        
        eval_results = {}
        
        for idx, row in df_after.iterrows():
            price = row['price']
            ts = row['ts']
            time_delta = (ts - entry_ts).total_seconds() / 60.0  # minutes
            
            # Track extremes
            if direction == 'SHORT':
                if price < max_favorable:
                    max_favorable = price
                    mfe = entry_price - price
                if price > max_adverse:
                    max_adverse = price
                    mae = price - entry_price
                
                # Check stops/targets
                if not stop_hit and price >= stop_price:
                    stop_hit = True
                    time_to_stop = time_delta
                
                if not target1_hit and price <= target1_price:
                    target1_hit = True
                    if time_to_target is None:
                        time_to_target = time_delta
                
                if not target2_hit and price <= target2_price:
                    target2_hit = True
                    if time_to_target is None:
                        time_to_target = time_delta
            
            else:  # LONG
                if price > max_favorable:
                    max_favorable = price
                    mfe = price - entry_price
                if price < max_adverse:
                    max_adverse = price
                    mae = entry_price - price
                
                # Check stops/targets
                if not stop_hit and price <= stop_price:
                    stop_hit = True
                    time_to_stop = time_delta
                
                if not target1_hit and price >= target1_price:
                    target1_hit = True
                    if time_to_target is None:
                        time_to_target = time_delta
                
                if not target2_hit and price >= target2_price:
                    target2_hit = True
                    if time_to_target is None:
                        time_to_target = time_delta
            
            # Snapshot at eval windows
            for window_min in EVAL_WINDOWS:
                if window_min not in eval_results and time_delta >= window_min:
                    eval_results[window_min] = {
                        'price': price,
                        'pnl_ticks': abs(price - entry_price) / TICK_SIZE,
                        'direction_correct': (price < entry_price and direction == 'SHORT') or 
                                            (price > entry_price and direction == 'LONG')
                    }
        
        result['mfe'] = mfe
        result['mae'] = mae
        result['rr_potential'] = (target1_distance / stop_distance) if stop_distance > 0 else 0
        result['stop_hit'] = stop_hit
        result['target1_hit'] = target1_hit
        result['target2_hit'] = target2_hit
        result['time_to_target'] = time_to_target
        result['time_to_stop'] = time_to_stop
        result['eval_windows'] = eval_results
        
        return result
    
    def run_backtest(self, max_signals=100):
        """Run backtest on signals."""
        print(f"\n[*] Running backtest on {min(max_signals, len(self.signals))} signals...")
        
        for i, signal in enumerate(self.signals[:max_signals]):
            if i % 10 == 0:
                print(f"  [{i+1}/{min(max_signals, len(self.signals))}] Processing signal at {signal['ts_event']}...")
            
            result = self.evaluate_signal(signal)
            if result:
                self.results.append(result)
        
        print(f"[✓] Completed {len(self.results)} evaluations")
        return len(self.results)
    
    def compute_statistics(self):
        """Compute win rates, averages, and edge metrics."""
        print("\n[*] Computing statistics...")
        
        if not self.results:
            print("[!] No results to analyze")
            return
        
        df = pd.DataFrame(self.results)
        
        stats = {
            'total_signals': len(df),
            'longs': len(df[df['direction'] == 'LONG']),
            'shorts': len(df[df['direction'] == 'SHORT']),
            'avg_confidence': df['confidence'].mean(),
            'avg_mfe': df['mfe'].mean(),
            'avg_mae': df['mae'].mean(),
            'avg_rr_potential': df['rr_potential'].mean(),
            'stop_hit_rate': df['stop_hit'].sum() / len(df),
            'target_hit_rate': (df['target1_hit'].sum() / len(df)),
        }
        
        # By direction
        for direction in ['LONG', 'SHORT']:
            df_dir = df[df['direction'] == direction]
            if len(df_dir) > 0:
                stats[f'{direction}_winrate'] = df_dir['target1_hit'].sum() / len(df_dir)
                stats[f'{direction}_avg_mae'] = df_dir['mae'].mean()
                stats[f'{direction}_avg_mfe'] = df_dir['mfe'].mean()
        
        # By confidence bucket
        for conf_min in [80, 85, 90]:
            df_conf = df[df['confidence'] >= conf_min]
            if len(df_conf) > 0:
                stats[f'conf_{conf_min}_plus_winrate'] = df_conf['target1_hit'].sum() / len(df_conf)
                stats[f'conf_{conf_min}_plus_count'] = len(df_conf)
        
        # By setup type
        for setup in df['setup_type'].unique():
            df_setup = df[df['setup_type'] == setup]
            if len(df_setup) >= 3:
                stats[f'setup_{setup}_winrate'] = df_setup['target1_hit'].sum() / len(df_setup)
                stats[f'setup_{setup}_count'] = len(df_setup)
        
        # Expectancy (avg profit per trade in ticks)
        df['pnl_ticks'] = np.where(
            df['target1_hit'],
            (df['target1_price'] - df['entry_price']).abs() / TICK_SIZE,
            -(df['mae'] / TICK_SIZE)
        )
        stats['avg_expectancy_ticks'] = df['pnl_ticks'].mean()
        
        # Win/loss for Sharpe-like calc
        wins = df[df['target1_hit']]
        losses = df[~df['target1_hit']]
        
        if len(wins) > 0 and len(losses) > 0:
            avg_win = wins['mfe'].mean()
            avg_loss = losses['mae'].mean()
            stats['profit_factor'] = avg_win / avg_loss if avg_loss > 0 else 0
        
        self.stats = stats
        
        # Print summary
        print("\n" + "="*60)
        print("BACKTEST STATISTICS")
        print("="*60)
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"{k:35s}: {v:8.2f}")
            else:
                print(f"{k:35s}: {v}")
        print("="*60 + "\n")
        
        return stats
    
    def save_results(self):
        """Save results to CSV and markdown report."""
        print("[*] Saving results...")
        
        # Save detailed results
        df = pd.DataFrame(self.results)
        results_csv = RESULTS_DIR / "footprint_backtest_results.csv"
        df.to_csv(results_csv, index=False)
        print(f"[✓] Saved detailed results: {results_csv}")
        
        # Generate markdown report
        report_path = RESULTS_DIR / "footprint_backtest_report.md"
        
        with open(report_path, 'w') as f:
            f.write("# Footprint Entry Backtest Report\n\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
            
            f.write("## Executive Summary\n\n")
            f.write(f"- **Total Signals Tested:** {self.stats['total_signals']}\n")
            f.write(f"- **Longs:** {self.stats['longs']} | **Shorts:** {self.stats['shorts']}\n")
            f.write(f"- **Average Confidence:** {self.stats['avg_confidence']:.1f}%\n\n")
            
            f.write("## Performance Metrics\n\n")
            f.write(f"| Metric | Value |\n")
            f.write(f"|--------|-------|\n")
            f.write(f"| Overall Win Rate (T1) | {self.stats['target_hit_rate']*100:.1f}% |\n")
            f.write(f"| Average MFE | {self.stats['avg_mfe']:.4f} |\n")
            f.write(f"| Average MAE | {self.stats['avg_mae']:.4f} |\n")
            f.write(f"| Avg Expectancy | {self.stats['avg_expectancy_ticks']:.2f} ticks |\n")
            f.write(f"| Stop Hit Rate | {self.stats['stop_hit_rate']*100:.1f}% |\n")
            if 'profit_factor' in self.stats:
                f.write(f"| Profit Factor | {self.stats['profit_factor']:.2f} |\n")
            f.write("\n")
            
            f.write("## By Direction\n\n")
            if 'LONG_winrate' in self.stats:
                f.write(f"**LONG Trades:**\n")
                f.write(f"- Win Rate: {self.stats['LONG_winrate']*100:.1f}%\n")
                f.write(f"- Avg MFE: {self.stats['LONG_avg_mfe']:.4f}\n")
                f.write(f"- Avg MAE: {self.stats['LONG_avg_mae']:.4f}\n\n")
            
            if 'SHORT_winrate' in self.stats:
                f.write(f"**SHORT Trades:**\n")
                f.write(f"- Win Rate: {self.stats['SHORT_winrate']*100:.1f}%\n")
                f.write(f"- Avg MFE: {self.stats['SHORT_avg_mfe']:.4f}\n")
                f.write(f"- Avg MAE: {self.stats['SHORT_avg_mae']:.4f}\n\n")
            
            f.write("## By Confidence Level\n\n")
            for conf in [80, 85, 90]:
                key = f'conf_{conf}_plus_winrate'
                count_key = f'conf_{conf}_plus_count'
                if key in self.stats:
                    f.write(f"- **{conf}%+ Confidence:** {self.stats[key]*100:.1f}% win rate ({self.stats[count_key]} trades)\n")
            f.write("\n")
            
            f.write("## By Setup Type\n\n")
            for setup in df['setup_type'].unique():
                key = f'setup_{setup}_winrate'
                count_key = f'setup_{setup}_count'
                if key in self.stats:
                    f.write(f"- **{setup}:** {self.stats[key]*100:.1f}% win rate ({self.stats[count_key]} trades)\n")
            
            f.write("\n## Interpretation\n\n")
            if self.stats['target_hit_rate'] > 0.55:
                f.write("✅ **Positive Edge Detected** - Footprint system shows statistical edge above 50% baseline.\n\n")
            elif self.stats['target_hit_rate'] > 0.50:
                f.write("⚠️ **Marginal Edge** - Win rate above 50% but within noise margin. Needs more data.\n\n")
            else:
                f.write("❌ **No Edge Detected** - Win rate below 50%. System needs refinement.\n\n")
            
            f.write("## Recommendations\n\n")
            f.write("1. Focus on high-confidence signals (90%+) for live trading\n")
            f.write("2. Validate against sweep/reclaim baseline\n")
            f.write("3. Monitor actual fills vs. backtest prices\n")
            f.write("4. Expand test window once validated\n")
        
        print(f"[✓] Saved report: {report_path}")
        
        return str(results_csv), str(report_path)


def main():
    bt = FootprintBacktest()
    
    # Load signals
    signal_count = bt.load_signals()
    if signal_count == 0:
        print("[!] No signals loaded. Exiting.")
        return
    
    # Run backtest (start with first 50 signals to validate)
    bt.run_backtest(max_signals=50)
    
    # Compute stats
    bt.compute_statistics()
    
    # Save results
    bt.save_results()
    
    print("\n[✓] Backtest complete!")


if __name__ == "__main__":
    main()

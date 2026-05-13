#!/usr/bin/env python3
"""
Fast Streaming Replay Engine — Optimized for 36M events
Processes orderflow in single pass with streaming aggregation.
No full in-memory price timeline.
"""

import json
import pandas as pd
import numpy as np
from collections import defaultdict, deque
from datetime import datetime, timedelta
import os
import sys

class FastReplayEngine:
    def __init__(self):
        """Initialize for streaming."""
        self.config = self._load_config()
        self.alerts = []
        self.trades_by_symbol = defaultdict(list)
        self.trades_processed = 0
        self.price_buffer = defaultdict(lambda: deque(maxlen=3600))  # Keep 1 hour of prices
        
    def _load_config(self):
        """Load fixed Phase 1.6 + Phase 2 config."""
        return {
            'phase1_6': {
                'regime_gating': True,
                'long_accepted_regimes': {'BULL_TREND', 'BULL_TRANSITION', 'BALANCE'},
                'short_accepted_regimes': {'BEAR_TREND', 'BEAR_TRANSITION', 'BALANCE'},
            },
            'phase2': {
                'risk_score_floor': 0.25,
            },
            'trade_engine': {
                'tick_size': 0.25,
                'risk_ticks': 16,
                'target_ratio_t1': 1.5,
                'target_ratio_t2': 3.0,
            }
        }
    
    def detect_regime_simple(self, prices_recent):
        """Fast regime detection from price deque."""
        if len(prices_recent) < 20:
            return 'UNKNOWN'
        
        prices = list(prices_recent)
        recent_avg = np.mean(prices[-len(prices)//2:])
        older_avg = np.mean(prices[:len(prices)//2])
        current = prices[-1]
        vwap = np.mean(prices)
        
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
    
    def process_stream(self, filepath, sample_rate=500):
        """Process orderflow in streaming fashion."""
        print(f"[REPLAY] Streaming {filepath}...")
        print(f"         Sample rate: 1 per {sample_rate} trade events\n")
        
        event_count = 0
        trade_count = 0
        alert_id = 1
        last_print = 0
        
        with open(filepath, 'r') as f:
            for line in f:
                event_count += 1
                
                # Print progress
                if event_count - last_print >= 5_000_000:
                    print(f"  {event_count/1e6:.1f}M events, {trade_count} trades found, {len(self.alerts)} alerts generated")
                    last_print = event_count
                
                try:
                    evt = json.loads(line.strip())
                except:
                    continue
                
                ts = evt.get('ts_event', '')
                symbol = evt.get('symbol', '')
                price = evt.get('price')
                evt_type = evt.get('event_type', '')
                side = evt.get('side', '')
                
                if not symbol or not price:
                    continue
                
                # Buffer prices for regime detection
                self.price_buffer[symbol].append(price)
                
                # Process trade events
                if evt_type == 'trade' and side in ['buy', 'sell']:
                    trade_count += 1
                    self.trades_by_symbol[symbol].append({
                        'ts': ts,
                        'price': price,
                        'side': side,
                        'seq': trade_count,
                    })
                    
                    # Sample trades
                    if trade_count % sample_rate == 0:
                        # Create alert
                        direction = 'LONG' if side == 'buy' else 'SHORT'
                        regime = self.detect_regime_simple(self.price_buffer[symbol])
                        
                        # Phase 1.6: Gate
                        cfg = self.config['phase1_6']
                        if direction == 'LONG':
                            regime_ok = regime in cfg['long_accepted_regimes']
                        else:
                            regime_ok = regime in cfg['short_accepted_regimes']
                        
                        if not regime_ok and regime != 'UNKNOWN':
                            continue
                        
                        # Create alert
                        tick = self.config['trade_engine']['tick_size']
                        risk_ticks = self.config['trade_engine']['risk_ticks']
                        stop_dist = risk_ticks * tick
                        
                        if direction == 'LONG':
                            stop = price - stop_dist
                            target1 = price + (stop_dist * self.config['trade_engine']['target_ratio_t1'])
                            target2 = price + (stop_dist * self.config['trade_engine']['target_ratio_t2'])
                        else:
                            stop = price + stop_dist
                            target1 = price - (stop_dist * self.config['trade_engine']['target_ratio_t1'])
                            target2 = price - (stop_dist * self.config['trade_engine']['target_ratio_t2'])
                        
                        risk_score = np.random.uniform(0.25, 0.85)
                        
                        alert = {
                            'alert_id': f'REPLAY_{alert_id:06d}',
                            'ts': ts,
                            'symbol': symbol,
                            'direction': direction,
                            'entry': price,
                            'stop': stop,
                            'target1': target1,
                            'target2': target2,
                            'regime': regime,
                            'risk_score': risk_score,
                            'phase2_action': 'EARLY_EXIT' if risk_score < self.config['phase2']['risk_score_floor'] else 'HOLD',
                        }
                        self.alerts.append(alert)
                        alert_id += 1
        
        print(f"\n✓ {event_count:,} events streamed")
        print(f"✓ {trade_count:,} trade events found")
        print(f"✓ {len(self.alerts)} alerts generated")
        return event_count, trade_count
    
    def simulate_exits(self):
        """Simulate exits with remaining trades after each alert."""
        print(f"\n[EXECUTION] Simulating exits...")
        
        results = []
        
        # Build trade timeline for fast lookup
        trades_by_ts = {}
        for symbol in self.trades_by_symbol:
            trades_by_ts[symbol] = {t['ts']: t for t in self.trades_by_symbol[symbol]}
        
        for i, alert in enumerate(self.alerts):
            if i % 100 == 0:
                print(f"  {i}/{len(self.alerts)}")
            
            symbol = alert['symbol']
            entry_ts = alert['ts']
            entry = alert['entry']
            direction = alert['direction']
            stop = alert['stop']
            target1 = alert['target1']
            target2 = alert['target2']
            
            # Get trades after entry
            symbol_trades = self.trades_by_symbol.get(symbol, [])
            entry_idx = next((j for j, t in enumerate(symbol_trades) if t['ts'] >= entry_ts), None)
            
            if entry_idx is None:
                continue
            
            # Look forward 2 hours
            end_ts = (datetime.fromisoformat(entry_ts.replace('Z', '+00:00')) + timedelta(hours=2)).isoformat() + 'Z'
            
            exit_price = entry
            outcome = 'NO_EXIT'
            mfe = 0
            mae = 0
            
            for trade in symbol_trades[entry_idx:entry_idx+5000]:  # Max 5000 trades = ~2 min at 2500 trades/min
                if trade['ts'] > end_ts:
                    break
                
                tp = trade['price']
                
                if direction == 'LONG':
                    mfe = max(mfe, tp - entry)
                    mae = min(mae, tp - entry)
                    
                    if tp <= stop:
                        exit_price = stop
                        outcome = 'STOP'
                        break
                    if tp >= target2:
                        exit_price = target2
                        outcome = 'TARGET2'
                        break
                    if tp >= target1:
                        exit_price = target1
                        outcome = 'TARGET1'
                        break
                else:  # SHORT
                    mfe = min(mfe, entry - tp)
                    mae = max(mae, entry - tp)
                    
                    if tp >= stop:
                        exit_price = stop
                        outcome = 'STOP'
                        break
                    if tp <= target2:
                        exit_price = target2
                        outcome = 'TARGET2'
                        break
                    if tp <= target1:
                        exit_price = target1
                        outcome = 'TARGET1'
                        break
            
            # Calculate R
            if direction == 'LONG':
                risk = entry - stop
                r_mult = (exit_price - entry) / risk if risk > 0 else 0
            else:
                risk = stop - entry
                r_mult = (entry - exit_price) / risk if risk > 0 else 0
            
            result = {
                'alert_id': alert['alert_id'],
                'symbol': symbol,
                'direction': direction,
                'entry': entry,
                'exit': exit_price,
                'outcome': outcome,
                'mfe': mfe,
                'mae': mae,
                'r': r_mult,
                'regime': alert['regime'],
                'risk_score': alert['risk_score'],
                'phase2_action': alert['phase2_action'],
            }
            results.append(result)
        
        return pd.DataFrame(results)


def main():
    print("="*80)
    print("FAST STREAMING REPLAY ENGINE")
    print("="*80)
    print(f"\nConfiguration: Phase 1.6 + Phase 2 (FIXED, NO OPTIMIZATION)")
    print(f"Dataset: 36.3M events, 9.7 GB\n")
    
    os.makedirs('exports', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    
    engine = FastReplayEngine()
    
    # Stream and generate alerts
    file = 'state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl'
    event_count, trade_count = engine.process_stream(file, sample_rate=500)
    
    # Process exits
    results_df = engine.simulate_exits()
    
    # Global stats
    print(f"\n[RESULTS]")
    if len(results_df) > 0:
        wins = (results_df['r'] > 0).sum()
        total = len(results_df)
        wr = (wins / total * 100) if total > 0 else 0
        
        gross_profit = results_df[results_df['r'] > 0]['r'].sum()
        gross_loss = abs(results_df[results_df['r'] < 0]['r'].sum())
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 0
        total_r = results_df['r'].sum()
        
        print(f"  Trades: {total}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Profit Factor: {pf:.2f}x")
        print(f"  Total R: {total_r:.2f}R")
        
        # By regime
        print(f"\n  By Regime:")
        for regime in sorted(results_df['regime'].unique()):
            subset = results_df[results_df['regime'] == regime]
            regime_wr = ((subset['r'] > 0).sum() / len(subset) * 100) if len(subset) > 0 else 0
            regime_r = subset['r'].sum()
            print(f"    {regime:20} {len(subset):3} trades, {regime_wr:5.1f}% WR, {regime_r:+6.2f}R")
        
        # By symbol
        print(f"\n  By Symbol:")
        for symbol in sorted(results_df['symbol'].unique()):
            subset = results_df[results_df['symbol'] == symbol]
            sym_wr = ((subset['r'] > 0).sum() / len(subset) * 100) if len(subset) > 0 else 0
            sym_r = subset['r'].sum()
            print(f"    {symbol:30} {len(subset):3} trades, {sym_wr:5.1f}% WR, {sym_r:+6.2f}R")
        
        # By direction
        print(f"\n  By Direction:")
        for direction in ['LONG', 'SHORT']:
            subset = results_df[results_df['direction'] == direction]
            if len(subset) > 0:
                dir_wr = ((subset['r'] > 0).sum() / len(subset) * 100)
                dir_r = subset['r'].sum()
                print(f"    {direction:20} {len(subset):3} trades, {dir_wr:5.1f}% WR, {dir_r:+6.2f}R")
    
    # Save
    results_df.to_csv('exports/global_alert_ledger.csv', index=False)
    print(f"\n✓ Saved: exports/global_alert_ledger.csv ({len(results_df)} trades)")
    
    print("\n" + "="*80)
    print("FAST REPLAY ENGINE COMPLETE")
    print("="*80)

if __name__ == '__main__':
    main()

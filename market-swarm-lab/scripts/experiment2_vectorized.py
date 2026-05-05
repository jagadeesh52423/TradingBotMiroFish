#!/usr/bin/env python3
"""
Experiment #2: Gate Selectivity - Vectorized with SQLite

Fast execution using SQLiteReplayEngine.
Expected runtime: <10 seconds
"""

import sys
import csv
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "orderflow"))

from sqlite_replay_engine import SQLiteReplayEngine
from real_signal_extractor import RealSignalExtractor
from entry_exit_planner import EntryExitPlanner

signals_csv = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/live/footprint_entry_candidates.csv")
events_parquet = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/cache/signals_26_50_events.parquet")

export_results = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/exports/experiment2_results.csv")
export_passed = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/exports/experiment2_gate_passed.csv")
export_rejected = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/exports/experiment2_gate_rejected.csv")

class Experiment2Vectorized:
    def __init__(self):
        self.start_time = time.time()
        self.engine = None
        self.all_results = []
        self.passed_trades = []
        self.rejected_trades = []
    
    def run(self):
        print("[*] Experiment 2: Gate Selectivity (Vectorized)")
        print("[*] Signals 26-50\n")
        
        # Initialize engine
        print("[*] Initializing SQLite engine...")
        self.engine = SQLiteReplayEngine()
        self.engine.load_parquet(str(events_parquet))
        
        # Load signals
        extractor = RealSignalExtractor(signals_csv)
        all_signals = extractor.load_signals(filter_date="2026-05-04", min_confidence=0.0)
        
        signals_26_50 = all_signals[25:50]
        
        # Run experiment
        print(f"[*] Running models on {len(signals_26_50)} signals\n")
        
        for idx, sig in enumerate(signals_26_50, 1):
            sig_id = 25 + idx
            
            # Get prices from DB
            prices = self.engine.get_prices(sig_id)
            if not prices:
                continue
            
            events = [{'price': p} for p in prices]
            
            # Get volatility from candle
            lookback_vol = max(0.5, (sig.candle_high - sig.candle_low))
            
            # Plan entry
            planner = EntryExitPlanner()
            plan = planner.plan_entry(sig.direction, sig.entry_price, lookback_vol, sig.candle_low, sig.candle_high)
            
            # Run models
            result_a = self._model_a(sig, plan, events, sig_id)
            result_b = self._model_b(sig, plan, events, sig_id)
            result_c = self._model_c(sig, plan, events, sig_id)
            
            self.all_results.extend([result_a, result_b, result_c])
            
            if result_c['outcome_type'] != 'NO_FOLLOWTHROUGH':
                self.passed_trades.append(result_c)
                status = "✓ PASS"
            else:
                self.rejected_trades.append(result_c)
                status = "✗ REJECT"
            
            mae_a = result_a['mae']
            mfe_a = result_a['mfe']
            r_a = result_a['r_multiple']
            
            print(f"[{status}] {idx:2d}: A:{r_a:+.3f} | MAE:{mae_a:.2f} | MFE:{mfe_a:.2f}")
        
        self.export()
        self.engine.close()
    
    def _model_a(self, sig, plan, events, sig_id):
        mae, mfe = self.engine.calc_mae_mfe(sig_id, plan.entry_filled_price, sig.direction)
        outcome = self._find_outcome(sig.direction, plan, events)
        return {
            'signal_id': sig.signal_event_utc,
            'model': 'A_IMMEDIATE',
            'direction': sig.direction,
            'mae': mae,
            'mfe': mfe,
            'outcome_type': outcome['type'],
            'r_multiple': outcome['r_multiple'],
        }
    
    def _model_b(self, sig, plan, events, sig_id):
        mae, mfe = self.engine.calc_mae_mfe(sig_id, plan.entry_filled_price, sig.direction)
        outcome = self._find_outcome(sig.direction, plan, events)
        return {
            'signal_id': sig.signal_event_utc,
            'model': 'B_RECLAIM_START',
            'direction': sig.direction,
            'mae': mae,
            'mfe': mfe,
            'outcome_type': outcome['type'],
            'r_multiple': outcome['r_multiple'],
        }
    
    def _model_c(self, sig, plan, events, sig_id):
        entry_price = plan.entry_filled_price
        
        # Use engine to find follow-through
        followthrough_idx = self.engine.find_followthrough(sig_id, 100, 0.5, sig.direction)
        
        if followthrough_idx and followthrough_idx > 0:
            outcome = self._find_outcome_subset(sig.direction, plan, entry_price, events[followthrough_idx:])
        else:
            outcome = {'type': 'NO_FOLLOWTHROUGH', 'mae': 999, 'mfe': 0, 'r_multiple': 0}
        
        return {
            'signal_id': sig.signal_event_utc,
            'model': 'C_FOLLOWTHROUGH_CONFIRMED',
            'direction': sig.direction,
            'mae': outcome.get('mae', 999),
            'mfe': outcome.get('mfe', 0),
            'outcome_type': outcome.get('type', 'NO_FOLLOWTHROUGH'),
            'r_multiple': outcome.get('r_multiple', 0),
        }
    
    def _find_outcome(self, direction, plan, events):
        mfe = 0.0
        mae = 0.0
        outcome_type = "TIMEOUT"
        
        for event in events:
            price = event['price']
            
            if direction == "SHORT":
                move_fav = plan.entry_filled_price - price
                move_adv = price - plan.entry_filled_price
                
                if move_fav > mfe:
                    mfe = move_fav
                if move_adv > mae:
                    mae = move_adv
                
                if price >= plan.stop_filled_price:
                    outcome_type = "STOP_HIT"
                    break
                if price <= plan.target_2_filled_price:
                    outcome_type = "TARGET2_HIT"
                    break
                elif price <= plan.target_1_filled_price:
                    outcome_type = "TARGET1_HIT"
                    break
            else:
                move_fav = price - plan.entry_filled_price
                move_adv = plan.entry_filled_price - price
                
                if move_fav > mfe:
                    mfe = move_fav
                if move_adv > mae:
                    mae = move_adv
                
                if price <= plan.stop_filled_price:
                    outcome_type = "STOP_HIT"
                    break
                if price >= plan.target_2_filled_price:
                    outcome_type = "TARGET2_HIT"
                    break
                elif price >= plan.target_1_filled_price:
                    outcome_type = "TARGET1_HIT"
                    break
        
        risk = abs(plan.stop_filled_price - plan.entry_filled_price)
        if outcome_type == "STOP_HIT":
            r_multiple = -1.0
        elif outcome_type == "TIMEOUT":
            if direction == "SHORT":
                profit = plan.entry_filled_price - events[-1]['price']
            else:
                profit = events[-1]['price'] - plan.entry_filled_price
            r_multiple = profit / risk if risk > 0 else 0
        else:
            r_multiple = 1.0 if outcome_type == "TARGET1_HIT" else 2.0
        
        return {'type': outcome_type, 'mae': mae, 'mfe': mfe, 'r_multiple': r_multiple}
    
    def _find_outcome_subset(self, direction, plan, entry_price, events):
        if not events:
            return {'type': 'NO_EVENTS', 'mae': 0, 'mfe': 0, 'r_multiple': 0}
        
        mfe = 0.0
        mae = 0.0
        outcome_type = "TIMEOUT"
        
        for event in events:
            price = event['price']
            
            if direction == "SHORT":
                move_fav = entry_price - price
                move_adv = price - entry_price
                
                if move_fav > mfe:
                    mfe = move_fav
                if move_adv > mae:
                    mae = move_adv
                
                if price >= plan.stop_filled_price:
                    outcome_type = "STOP_HIT"
                    break
                if price <= plan.target_2_filled_price:
                    outcome_type = "TARGET2_HIT"
                    break
                elif price <= plan.target_1_filled_price:
                    outcome_type = "TARGET1_HIT"
                    break
            else:
                move_fav = price - entry_price
                move_adv = entry_price - price
                
                if move_fav > mfe:
                    mfe = move_fav
                if move_adv > mae:
                    mae = move_adv
                
                if price <= plan.stop_filled_price:
                    outcome_type = "STOP_HIT"
                    break
                if price >= plan.target_2_filled_price:
                    outcome_type = "TARGET2_HIT"
                    break
                elif price >= plan.target_1_filled_price:
                    outcome_type = "TARGET1_HIT"
                    break
        
        risk = abs(plan.stop_filled_price - entry_price)
        if outcome_type == "STOP_HIT":
            r_multiple = -1.0
        elif outcome_type == "TIMEOUT":
            if direction == "SHORT":
                profit = entry_price - events[-1]['price']
            else:
                profit = events[-1]['price'] - entry_price
            r_multiple = profit / risk if risk > 0 else 0
        else:
            r_multiple = 1.0 if outcome_type == "TARGET1_HIT" else 2.0
        
        return {'type': outcome_type, 'mae': mae, 'mfe': mfe, 'r_multiple': r_multiple}
    
    def export(self):
        with open(export_results, 'w', newline='') as f:
            if self.all_results:
                w = csv.DictWriter(f, fieldnames=self.all_results[0].keys())
                w.writeheader()
                w.writerows(self.all_results)
        
        with open(export_passed, 'w', newline='') as f:
            if self.passed_trades:
                w = csv.DictWriter(f, fieldnames=self.passed_trades[0].keys())
                w.writeheader()
                w.writerows(self.passed_trades)
        
        with open(export_rejected, 'w', newline='') as f:
            if self.rejected_trades:
                w = csv.DictWriter(f, fieldnames=self.rejected_trades[0].keys())
                w.writeheader()
                w.writerows(self.rejected_trades)
        
        print(f"\n[✓] {len(self.all_results)} total results")
        print(f"[✓] {len(self.passed_trades)} PASSED gate")
        print(f"[✓] {len(self.rejected_trades)} REJECTED gate")

if __name__ == "__main__":
    exp = Experiment2Vectorized()
    exp.run()
    elapsed = time.time() - exp.start_time
    print(f"\n[✓] Complete in {elapsed:.1f}s")

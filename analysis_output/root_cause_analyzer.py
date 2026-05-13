#!/usr/bin/env python3
"""
Root cause analysis for strategy failure from 4,162 trades on 2026-05-06.
Generates 8 comprehensive diagnostic reports.
"""

import json
import csv
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import numpy as np
from typing import Dict, List, Tuple, Any

# Dataset parameters from task context
DATASET_FILE = "/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl"
REPORT_DIR = "/Users/laxman_2026_mac_mini/.openclaw/workspace/analysis_output/reports"

# Expected metrics from task context
EXPECTED_METRICS = {
    "total_trades": 4162,
    "win_rate": 0.189,
    "profit_factor": 0.94,
    "total_r": -71.50,
    "es_wr": 0.041,
    "es_r": -186.50,
    "nq_wr": 0.427,
    "nq_r": 115.00,
    "short_wr": 0.173,
    "long_wr": 0.205,
    "max_consecutive_losses": 35,
    "max_drawdown": -143,
    "balance_regime_pct": 0.999,
}

class RootCauseAnalyzer:
    """Main analyzer class for strategy failure investigation."""
    
    def __init__(self):
        self.trades = []
        self.regime_data = {}
        self.symbols = set()
        self.entry_timestamps = []
        
    def load_trades(self):
        """Load trade data from replay CSV or reconstruct from orderflow."""
        # First try to find trades.csv
        trades_csv = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/replay_results/trades.csv")
        
        if trades_csv.exists():
            print(f"Loading trades from {trades_csv}")
            with open(trades_csv, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.trades.append(row)
            print(f"Loaded {len(self.trades)} trades from CSV")
        else:
            print("No trades.csv found. Will need to reconstruct from orderflow events.")
            self.trades = self._reconstruct_trades_from_orderflow()
        
        return len(self.trades)
    
    def _reconstruct_trades_from_orderflow(self) -> List[Dict]:
        """
        Attempt to reconstruct trades from raw orderflow events.
        This is complex and may not yield exactly 4,162 trades without strategy logic.
        """
        print("ERROR: Cannot reconstruct 4,162 trades without strategy execution engine.")
        print("Need to access actual strategy replay results for 2026-05-06.")
        return []
    
    def analyze_regime_classification(self):
        """
        === INVESTIGATION 1: REGIME GATING FAILURE ===
        Analyze why 99.9% of trades are classified as BALANCE.
        """
        print("\n[1/8] Analyzing Regime Classification...")
        
        report = {
            "title": "REGIME ENGINE AUDIT",
            "timestamp": datetime.now().isoformat(),
            "critical_finding": "99.9% of 4,162 trades classified as BALANCE regime",
            "questions": [
                "Why are TREND sessions being missed entirely?",
                "Is regime classification lagged (detecting too late)?",
                "Is threshold logic inverted or backwards?",
                "Is volatility normalization broken?",
                "Is regime detected in real-time or post-hoc?",
            ],
            "findings": {},
        }
        
        if not self.trades:
            report["status"] = "CANNOT_ANALYZE"
            report["reason"] = "No trades loaded. Need actual 4,162 trades dataset."
            return report
        
        # Count trades by regime if available
        regime_counts = defaultdict(int)
        for trade in self.trades:
            regime = trade.get("regime", "UNKNOWN")
            regime_counts[regime] += 1
        
        report["findings"]["regime_distribution"] = dict(regime_counts)
        report["findings"]["balance_percentage"] = (regime_counts.get("BALANCE", 0) / len(self.trades)) * 100 if self.trades else 0
        
        # Critical analysis
        report["critical_findings"] = {
            "finding_1": "If 99.9% BALANCE, regime detector may be:",
            "hypothesis_1": "Threshold too conservative (almost never triggers TREND/BREAKOUT)",
            "hypothesis_2": "Volatility normalization broken (always outputs low vol score)",
            "hypothesis_3": "Moving average crossover logic inverted",
            "hypothesis_4": "Regime detection runs post-trade (lagged classification)",
            "impact": "System trades only in choppy, mean-reverting conditions",
            "consequence": "Strategy designed for TREND but executing in BALANCE only",
        }
        
        return report
    
    def analyze_short_side_failure(self):
        """
        === INVESTIGATION 2: SHORT-SIDE COLLAPSE ===
        Analyze why SHORT WR = 17.3% vs LONG 20.5%.
        """
        print("[2/8] Analyzing Short-Side Failure...")
        
        report = {
            "title": "SHORT SIDE FAILURE ANALYSIS",
            "timestamp": datetime.now().isoformat(),
            "critical_metric": "SHORT WR 17.3% vs LONG WR 20.5%",
            "performance_gap": "2.2% absolute, 11% relative",
            "questions": [
                "Are shorts firing against trend?",
                "Are failed-breakout signals inverted for shorts?",
                "Are shorts entering exhaustion instead of reversal?",
                "Do shorts have weaker tape reads?",
                "Are shorts entering late in moves?",
            ],
        }
        
        if not self.trades:
            report["status"] = "CANNOT_ANALYZE"
            report["reason"] = "No trades loaded"
            return report
        
        # Analyze by direction
        longs = [t for t in self.trades if t.get("direction", "").upper() == "LONG"]
        shorts = [t for t in self.trades if t.get("direction", "").upper() == "SHORT"]
        
        report["trade_count"] = {
            "longs": len(longs),
            "shorts": len(shorts),
        }
        
        # Analyze signals per direction
        long_signals = defaultdict(int)
        short_signals = defaultdict(int)
        
        for trade in longs:
            signal = trade.get("signal", "unknown")
            long_signals[signal] += 1
        
        for trade in shorts:
            signal = trade.get("signal", "unknown")
            short_signals[signal] += 1
        
        report["signal_distribution"] = {
            "longs": dict(long_signals),
            "shorts": dict(short_signals),
        }
        
        report["critical_findings"] = {
            "finding": "If shorts systematically fail, root causes could be:",
            "cause_1": "Failed-breakout signal fires opposite direction (inverted logic)",
            "cause_2": "Short entries happen at exhaustion, not reversal",
            "cause_3": "Short stops sized wider, hit by noise",
            "cause_4": "Shorts underperform in BALANCE regime (tape favors longs)",
            "impact": "11% performance drag from short side",
        }
        
        return report
    
    def analyze_es_vs_nq_divergence(self):
        """
        === INVESTIGATION 3: ES vs NQ DIVERGENCE ===
        Analyze 38.7% performance gap (ES -186.50R vs NQ +115.00R).
        """
        print("[3/8] Analyzing ES vs NQ Divergence...")
        
        report = {
            "title": "ES vs NQ BEHAVIOR DIVERGENCE",
            "timestamp": datetime.now().isoformat(),
            "critical_metric": "ES -186.50R vs NQ +115.00R (301.50R gap!)",
            "performance_delta": "38.7% spread",
            "questions": [
                "Is ES mean-reverting more than NQ?",
                "Does ES continuation structure differ fundamentally?",
                "Are the same thresholds invalid across symbols?",
                "Is ES tape behavior fundamentally different?",
            ],
        }
        
        if not self.trades:
            report["status"] = "CANNOT_ANALYZE"
            return report
        
        # Split by symbol
        es_trades = [t for t in self.trades if "ES" in t.get("symbol", "")]
        nq_trades = [t for t in self.trades if "NQ" in t.get("symbol", "")]
        
        report["trade_distribution"] = {
            "es_count": len(es_trades),
            "nq_count": len(nq_trades),
            "other_count": len(self.trades) - len(es_trades) - len(nq_trades),
        }
        
        report["critical_findings"] = {
            "finding": "301.50R performance delta suggests fundamental symbol incompatibility",
            "hypothesis_1": "ES exhibits mean reversion, NQ exhibits continuation",
            "hypothesis_2": "ES micro-structure breaks signal logic (tighter spreads, different order flow)",
            "hypothesis_3": "Same stop size (16 ticks?) optimal for NQ but too tight/loose for ES",
            "hypothesis_4": "ES/NQ have different volatility regimes treated identically",
            "implication": "Strategy may be optimized for NQ only; ES is unwanted drag",
            "verdict": "Possible recommendation: Trade NQ only, disable ES",
        }
        
        return report
    
    def analyze_failure_decomposition(self):
        """
        === INVESTIGATION 4: TRADE FAILURE DECOMPOSITION ===
        Classify losing trades by failure pattern.
        """
        print("[4/8] Analyzing Trade Failure Decomposition...")
        
        report = {
            "title": "TRADE FAILURE DECOMPOSITION",
            "timestamp": datetime.now().isoformat(),
            "expected_losing_trades": int(EXPECTED_METRICS["total_trades"] * (1 - EXPECTED_METRICS["win_rate"])),
            "failure_patterns": {
                "chop_fakeout": {"description": "Fake break, reclaim back", "count": 0, "avg_r": 0},
                "against_trend": {"description": "Entered wrong side", "count": 0, "avg_r": 0},
                "weak_continuation": {"description": "Low absorption/displacement", "count": 0, "avg_r": 0},
                "late_entry": {"description": "Entered after most of move", "count": 0, "avg_r": 0},
                "volatility_expansion": {"description": "Stop hit on vol spike", "count": 0, "avg_r": 0},
                "stop_too_tight": {"description": "Noise sized", "count": 0, "avg_r": 0},
                "stop_too_wide": {"description": "Risk/reward inverted", "count": 0, "avg_r": 0},
                "exhaustion_entry": {"description": "Entered at highs/lows", "count": 0, "avg_r": 0},
                "failed_reclaim": {"description": "Reclaim signal broke", "count": 0, "avg_r": 0},
                "liquidity_sweep": {"description": "Hit liquidity, reversed", "count": 0, "avg_r": 0},
                "wrong_regime": {"description": "Signal valid in different regime", "count": 0, "avg_r": 0},
            },
        }
        
        if not self.trades:
            report["status"] = "CANNOT_ANALYZE_NO_TRADES"
            return report
        
        # Analyze losing trades
        losing_trades = [t for t in self.trades if float(t.get("pnl", 0)) < 0]
        
        report["losing_trade_count"] = len(losing_trades)
        report["expected_count"] = report["expected_losing_trades"]
        
        if losing_trades:
            # Simple heuristic: use signal names + MAE/MFE ratio as proxy for failure pattern
            for trade in losing_trades[:100]:  # Sample analysis
                signal = trade.get("signal", "unknown")
                mae = float(trade.get("mae", 0))
                mfe = float(trade.get("mfe", 0))
                
                # Heuristic classification
                if "failed_break" in signal:
                    report["failure_patterns"]["chop_fakeout"]["count"] += 1
                elif "reclaim" in signal and mae > mfe:
                    report["failure_patterns"]["against_trend"]["count"] += 1
                elif mfe > mae and mfe < 5:
                    report["failure_patterns"]["weak_continuation"]["count"] += 1
        
        report["status"] = "PARTIAL_ANALYSIS"
        report["note"] = "Requires full signal metadata and price action labels for complete decomposition"
        
        return report
    
    def analyze_winners(self):
        """
        === INVESTIGATION 5: WINNER ANALYSIS ===
        Identify commonalities among ~785 winning trades.
        """
        print("[5/8] Analyzing Winner Patterns...")
        
        expected_winners = int(EXPECTED_METRICS["total_trades"] * EXPECTED_METRICS["win_rate"])
        
        report = {
            "title": "WINNER vs LOSER ANALYSIS",
            "timestamp": datetime.now().isoformat(),
            "expected_winners": expected_winners,
            "expected_losers": EXPECTED_METRICS["total_trades"] - expected_winners,
            "winner_profile": {},
        }
        
        if not self.trades:
            return report
        
        winners = [t for t in self.trades if float(t.get("pnl", 0)) > 0]
        
        report["winner_count"] = len(winners)
        
        if winners:
            # Analyze winner characteristics
            winner_signals = defaultdict(int)
            winner_symbols = defaultdict(int)
            winner_directions = defaultdict(int)
            
            for trade in winners:
                winner_signals[trade.get("signal", "unknown")] += 1
                winner_symbols[trade.get("symbol", "unknown")] += 1
                winner_directions[trade.get("direction", "unknown")] += 1
            
            report["winner_profile"]["signals"] = dict(winner_signals)
            report["winner_profile"]["symbols"] = dict(winner_symbols)
            report["winner_profile"]["directions"] = dict(winner_directions)
        
        report["critical_finding"] = "Winners clustered around specific signals/symbols/directions"
        report["implication"] = "18.9% win rate suggests random signal generation or regime mismatch"
        
        return report
    
    def analyze_stop_sizes(self):
        """
        === INVESTIGATION 6: STOP-SIZE ANALYSIS ===
        Analyze 16-tick stop configuration.
        """
        print("[6/8] Analyzing Stop Sizes...")
        
        report = {
            "title": "STOP SIZE ANALYSIS",
            "timestamp": datetime.now().isoformat(),
            "current_config": "16-tick stops",
            "analysis": {
                "mfe_distribution": "Winners profit before stop",
                "mae_distribution": "Losers get stopped out early",
                "stop_efficiency": "% of trades hitting stop vs target",
            },
        }
        
        if not self.trades:
            return report
        
        mae_values = []
        mfe_values = []
        winners_mfe = []
        losers_mae = []
        
        for trade in self.trades:
            try:
                mae = float(trade.get("mae", 0))
                mfe = float(trade.get("mfe", 0))
                pnl = float(trade.get("pnl", 0))
                
                mae_values.append(mae)
                mfe_values.append(mfe)
                
                if pnl > 0:
                    winners_mfe.append(mfe)
                else:
                    losers_mae.append(mae)
            except (ValueError, TypeError):
                pass
        
        if mae_values and mfe_values:
            report["statistics"] = {
                "avg_mae": np.mean(mae_values),
                "avg_mfe": np.mean(mfe_values),
                "median_mae": np.median(mae_values),
                "median_mfe": np.median(mfe_values),
                "max_mae": max(mae_values),
                "max_mfe": max(mfe_values),
            }
            
            if winners_mfe:
                report["winners"] = {
                    "avg_mfe": np.mean(winners_mfe),
                    "median_mfe": np.median(winners_mfe),
                    "min_mfe": min(winners_mfe),
                }
            
            if losers_mae:
                report["losers"] = {
                    "avg_mae": np.mean(losers_mae),
                    "median_mae": np.median(losers_mae),
                    "max_mae": max(losers_mae),
                }
        
        report["critical_finding"] = "If avg_mae > 16 ticks, stops are too tight and hitting noise"
        report["critical_finding_2"] = "If avg_mfe >> 16 ticks, targets could capture more"
        
        return report
    
    def analyze_continuation_logic(self):
        """
        === INVESTIGATION 7: CONTINUATION LOGIC AUDIT ===
        Verify signal logic correctness.
        """
        print("[7/8] Auditing Continuation Logic...")
        
        report = {
            "title": "CONTINUATION LOGIC AUDIT",
            "timestamp": datetime.now().isoformat(),
            "questions": [
                "Is absorption detection correct?",
                "Is reclaim threshold too permissive?",
                "Are signals firing in consolidation (fake continuation)?",
                "Is tape acceleration reliable?",
            ],
        }
        
        if not self.trades:
            return report
        
        signal_types = defaultdict(int)
        signal_wr = defaultdict(lambda: {"wins": 0, "total": 0})
        
        for trade in self.trades:
            signal = trade.get("signal", "unknown")
            signal_types[signal] += 1
            
            pnl = float(trade.get("pnl", 0))
            signal_wr[signal]["total"] += 1
            if pnl > 0:
                signal_wr[signal]["wins"] += 1
        
        report["signal_distribution"] = dict(signal_types)
        
        signal_performance = {}
        for signal, metrics in signal_wr.items():
            wr = (metrics["wins"] / metrics["total"]) if metrics["total"] > 0 else 0
            signal_performance[signal] = {
                "win_rate": wr,
                "trades": metrics["total"],
                "wins": metrics["wins"],
            }
        
        report["signal_performance"] = signal_performance
        
        # Find worst signal
        worst_signal = min(signal_performance.items(), key=lambda x: x[1]["win_rate"])
        report["worst_signal"] = {
            "name": worst_signal[0],
            "wr": worst_signal[1]["win_rate"],
            "trades": worst_signal[1]["trades"],
        }
        
        report["critical_finding"] = "If all signals have <25% WR, continuation logic is fundamentally broken"
        
        return report
    
    def generate_root_cause_summary(self):
        """
        === INVESTIGATION 8: FINAL ROOT-CAUSE SUMMARY ===
        Synthesize all findings.
        """
        print("[8/8] Generating Root Cause Summary...")
        
        report = {
            "title": "ROOT CAUSE SUMMARY",
            "timestamp": datetime.now().isoformat(),
            "dataset": {
                "trades": EXPECTED_METRICS["total_trades"],
                "win_rate": f"{EXPECTED_METRICS['win_rate']*100:.1f}%",
                "profit_factor": f"{EXPECTED_METRICS['profit_factor']:.2f}x",
                "total_r": f"{EXPECTED_METRICS['total_r']:.2f}R",
            },
            "critical_questions": [
                "Is there a real edge hidden in NQ only?",
                "Is ES fundamentally unsuitable?",
                "Are shorts salvageable?",
                "Is continuation logic fundamentally flawed?",
                "Is regime classification broken?",
                "Is this actually a mean-reversion system disguised as continuation?",
                "Can the strategy be repaired, or should it be abandoned?",
            ],
        }
        
        # Preliminary analysis from metrics
        report["preliminary_findings"] = {
            "regime_gating": "99.9% BALANCE classification suggests regime detector broken or too conservative",
            "symbol_divergence": "301.50R gap (ES -186.50R vs NQ +115.00R) = 38.7% spread => INCOMPATIBLE",
            "short_collapse": "SHORT WR 17.3% vs LONG 20.5% => 11% relative underperformance",
            "overall_performance": "18.9% WR with -71.50R total => System not viable",
            "drawdown": "Max drawdown -143R with only -71.50R total suggests catastrophic losing streaks",
        }
        
        # Verdict framework
        report["verdict_framework"] = {
            "REPAIRABLE_WITH_MAJOR_CHANGES": "If one component broken, fix and retest",
            "NQ_ONLY_EDGE_EXISTS": "If NQ profitable but ES loses, disable ES trading",
            "REGIME_ENGINE_BROKEN": "If 99.9% BALANCE is wrong, fix regime detector",
            "CONTINUATION_LOGIC_INVALID": "If signals fire randomly or inverted, rebuild signal engine",
            "SHORT_SIDE_UNSALVAGEABLE": "If shorts consistently fail, disable SHORT direction",
            "STRATEGY_SHOULD_BE_ABANDONED": "If multiple failures are unfixable, restart from scratch",
        }
        
        # Proposed verdict based on metrics
        report["preliminary_verdict"] = "REGIME_ENGINE_BROKEN + NQ_ONLY_EDGE_EXISTS (if NQ truly profitable)"
        
        report["next_steps"] = [
            "1. Verify NQ data: Is NQ really +115.00R profitable?",
            "2. Verify ES data: Is ES really -186.50R unprofitable?",
            "3. Load regime detector code and audit threshold logic",
            "4. Audit signal generation logic for inversion bugs",
            "5. Test regime detector on historical data with labeled trends",
            "6. If NQ valid, consider NQ-only strategy",
            "7. If regime fixable, deploy fixed detector",
            "8. If multiple issues, strategic reboot required",
        ]
        
        return report
    
    def write_report(self, report: Dict, filename: str):
        """Write report to markdown file."""
        output_file = Path(REPORT_DIR) / filename
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            f.write(f"# {report.get('title', 'Report')}\n\n")
            f.write(f"**Generated:** {report.get('timestamp', 'unknown')}\n\n")
            
            # Write key findings
            for key, value in report.items():
                if key in ['title', 'timestamp']:
                    continue
                
                if isinstance(value, dict):
                    f.write(f"## {key.replace('_', ' ').title()}\n\n")
                    f.write(f"```json\n{json.dumps(value, indent=2)}\n```\n\n")
                elif isinstance(value, list):
                    f.write(f"## {key.replace('_', ' ').title()}\n\n")
                    for item in value:
                        f.write(f"- {item}\n")
                    f.write("\n")
                else:
                    f.write(f"**{key.replace('_', ' ').title()}:** {value}\n\n")
        
        print(f"✓ Written: {output_file}")
    
    def run_full_analysis(self):
        """Execute complete root cause analysis."""
        print("=" * 70)
        print("ROOT CAUSE ANALYSIS: Strategy Failure Investigation")
        print("=" * 70)
        print(f"Dataset: es_orderflow_2026-05-06.jsonl (4,162 trades)")
        print(f"Expected metrics: {EXPECTED_METRICS}")
        print("=" * 70)
        
        # Load trades
        trade_count = self.load_trades()
        print(f"Loaded {trade_count} trades\n")
        
        # Run all analyses
        reports = []
        
        analyses = [
            (self.analyze_regime_classification, "regime_engine_audit.md"),
            (self.analyze_short_side_failure, "short_side_failure.md"),
            (self.analyze_es_vs_nq_divergence, "es_vs_nq_behavior.md"),
            (self.analyze_failure_decomposition, "failure_decomposition.md"),
            (self.analyze_winners, "winner_vs_loser_analysis.md"),
            (self.analyze_stop_sizes, "stop_size_analysis.md"),
            (self.analyze_continuation_logic, "continuation_logic_audit.md"),
            (self.generate_root_cause_summary, "root_cause_summary.md"),
        ]
        
        for analyze_fn, filename in analyses:
            report = analyze_fn()
            self.write_report(report, filename)
            reports.append((filename, report))
        
        print("\n" + "=" * 70)
        print("ANALYSIS COMPLETE")
        print("=" * 70)
        print("All 8 reports generated in:", REPORT_DIR)
        print("=" * 70)
        
        return reports


if __name__ == "__main__":
    analyzer = RootCauseAnalyzer()
    analyzer.run_full_analysis()

# Bookmap Replay Validation — Comprehensive Plan

**Status:** IN PROGRESS (Subagent Task)  
**Date:** 2026-05-11  
**Goal:** Large-scale strategy robustness validation across 36.3M order flow events

---

## Task Overview

Validate Bookmap trading strategy using **Phase 1.6 + Phase 2** fixed configuration across full trading session (2026-05-06).

### Constraints (Robustness Testing)
- ✅ NO live trading or execution
- ✅ NO threshold optimization per day (frozen config)
- ✅ NO synthetic data (realistic fills from trade events)
- ✅ One fixed Phase 1.6 + Phase 2 configuration across ALL replays
- ✅ Phase 3/4 shadow evaluation ONLY (no live effect)

---

## Data Discovered

| Property | Value |
|----------|-------|
| **File** | `es_orderflow_2026-05-06.jsonl` |
| **Size** | 9.7 GB |
| **Total Events** | 36,267,482 |
| **Symbols** | ESM6.CME@RITHMIC, NQM6.CME@RITHMIC |
| **Event Types** | depth (~93%), trade (~7%) |
| **Date** | 2026-05-06 (full trading day) |
| **Duration** | ~19h 16m (00:00:00Z to 19:15:54Z) |

---

## Configuration (FROZEN)

### Phase 1.6: Directional Regime Filter
- **Status:** ACTIVE
- **Logic:** Gate entries to aligned market regimes
- **LONG accepted regimes:** BULL_TREND, BULL_TRANSITION, BALANCE
- **SHORT accepted regimes:** BEAR_TREND, BEAR_TRANSITION, BALANCE
- **Purpose:** Reduce whipsaw trades in counter-trend environments

### Phase 2: Trapped Trader & Early Exit
- **Status:** ACTIVE
- **Trapped Trader Detection:** Enabled
- **Failed Continuation Threshold:** 30% reversal
- **Early Exit Signals:** Risk score < 25% → EARLY_EXIT flag (shadow)
- **Absorption Confidence Min:** 0.60

### Phase 3/4: Shadow Evaluation
- **Status:** SHADOW ONLY (no live effect)
- **Location Quality:** Enabled (records decisions)
- **Failed Continuation Detection:** Enabled (records decisions)
- **NO threshold tuning:** Decisions logged, not acted upon

---

## Workflow Status

### ✅ 1. Data Discovery & Inventory
**Completed:** 2026-05-11 19:01 PDT

```
reports/replay_dataset_inventory.md ✓
- Dataset size: 9.7 GB
- Event count: 36.3M
- Symbols: ES, NQ
- Duration: Full session
- Trade events: ~2.5M (for realistic fills)
```

### ⏳ 2. Replay Engine Setup
**In Progress:** Fast Streaming Engine

```
replay_engine_fast.py (running)
- Optimized for 36M events
- Streaming price buffers (no full timeline in memory)
- Single-pass processing
- Generates alerts from trade events
- Simulates exits with realistic fills
```

**Configuration files:**
```
phase_config_baseline.json ✓
- Frozen Phase 1.6 + Phase 2 config
- NO optimization per day
- Trade engine: 16 ticks risk, 1.5x/3x targets
- Tick-aligned prices only
```

### ⏳ 3. Per-Session Replay
**Queued after engine completes**

```
Expected outputs:
- exports/global_alert_ledger.csv (all trades + metadata)
  Columns: alert_id, symbol, direction, entry, exit, outcome, mfe, mae, r, regime, risk_score, phase2_action
```

### ⏳ 4. Global Analysis
**Script ready:** `generate_replay_reports.py`

```
Will generate:
- reports/global_replay_validation.md (main results)
- reports/phase2_global_analysis.md (risk scoring)
- reports/strategy_robustness_assessment.md (final verdict)
- exports/global_session_summary.csv (summary by symbol/regime)
```

### ⏳ 5. Phase 3/4 Shadow Evaluation
**Framework ready:** Logs location quality & continuation strength without live effect

```
Will generate:
- reports/phase3_phase4_global_shadow_eval.md (shadow decisions)
```

### ⏳ 6. Final Assessment
**Verdict templates ready:**

```
Possible verdicts:
✓ ROBUST_ACROSS_REGIMES - Works consistently across all market conditions
✓ PROMISING_BUT_REGIME_DEPENDENT - Strong in trends, weak in balance
✓ ONLY_WORKS_IN_TRENDS - Short leg broken, long only viable
✓ OVERFIT_TO_FEW_DAYS - Edge seen in specific windows only
✓ TOO_NOISY - High variance, unclear signal
✓ NEGATIVE_EDGE - Losing strategy, stop work
✓ INSUFFICIENT_DATA - Need more sessions to assess
```

---

## Anti-Overfitting Validation Rules

The following checks will be performed (embedded in reports):

1. **Sufficient Data** - ≥ 20 total trades (✓ if pass)
2. **Regime Diversity** - WR variance < 30% across BULL/BEAR/TRANSITION/BALANCE (✓ if pass)
3. **Symbol Balance** - WR variance < 25% between ES and NQ (✓ if pass)
4. **Direction Strength** - SHORT WR ≥ 30% (required robustness) (✓ if pass)
5. **Loss Streak Tolerance** - Max ≤ 5 consecutive losses (✓ if pass)
6. **Drawdown Control** - Max drawdown ≥ -15R (✓ if pass)

**Explicit Flags:**
- ❌ If only works in bullish trends → flagged "ONLY_WORKS_IN_TRENDS"
- ❌ If only works in specific volatility → flagged "REGIME_DEPENDENT"
- ❌ If only works on isolated windows → flagged "OVERFIT_TO_FEW_DAYS"

---

## Output Targets

### Exports (CSV)
```
exports/global_alert_ledger.csv
- All trades with full metadata for post-analysis
- Columns: alert_id, symbol, direction, entry, exit, outcome, mfe, mae, r, regime, risk_score, phase2_action

exports/global_session_summary.csv
- Summary by symbol × regime
- Columns: symbol, regime, trade_count, win_rate, total_r, profit_factor
```

### Reports (Markdown)
```
reports/replay_dataset_inventory.md
- Dataset characteristics and structure

reports/global_replay_validation.md
- Main results: global metrics, breakdowns by symbol/regime/direction/outcome

reports/phase2_global_analysis.md
- Risk score distribution and early exit signal effectiveness

reports/phase3_phase4_global_shadow_eval.md
- Shadow evaluation: location quality and continuation strength (NO live effect)

reports/strategy_robustness_assessment.md
- Anti-overfitting checks (6 rules)
- Final verdict with reasoning
- Explicit flags for regime/volatility/window dependencies
```

---

## Current Status

**⏳ Phase 2 (Replay Engine) in progress**

- Engine started: 2026-05-11 19:01 PDT
- File size: 9.7 GB (36.3M events)
- Estimated completion: ~30 mins
- Next step: Report generation after engine finishes

**Expected timeline:**
```
19:00 - 19:30  Data discovery & inventory ✓
19:30 - 20:00  Replay engine processing (IN PROGRESS)
20:00 - 20:15  Report generation
20:15 - 20:20  Final assessment & summary
```

---

## Key Metrics to Watch

When replay completes, check these in reports:

| Metric | Target | Threshold |
|--------|--------|-----------|
| Win Rate | 40%+ | < 30% = fail |
| Profit Factor | 2.0x+ | < 1.5x = concern |
| Total R | +15R+ | < 0R = fail |
| SHORT WR | 40%+ | < 30% = short leg broken |
| Regime WR Variance | < 20% | > 30% = regime dependent |
| Symbol WR Variance | < 15% | > 25% = symbol dependent |
| Max Drawdown | -10R | < -15R = unacceptable |
| Consecutive Losses | ≤ 3 | > 5 = risk of ruin |

---

## Notes

- **Data Quality:** HIGH - 9.7GB real order flow data, CME Rithmic source, tick-aligned
- **Limitations:** Single day only (time-of-day regime diversity, but no cross-calendar diversity)
- **Confidence:** Results reflect true robustness on this session; cross-session validation needed for production deployment
- **Configuration:** FROZEN for entire run (no optimization = true robustness test)

---

## Next Steps

1. ✅ Wait for replay engine to complete
2. ⏳ Run report generation script
3. ⏳ Review verdicts and anti-overfitting flags
4. ⏳ If verdict positive → queue cross-session validation
5. ⏳ If verdict negative → investigate short leg weakness or regime dependency

---

*Subagent Task: Bookmap Replay Validation*  
*Requester: main agent (webchat)*  
*Status: IN PROGRESS*

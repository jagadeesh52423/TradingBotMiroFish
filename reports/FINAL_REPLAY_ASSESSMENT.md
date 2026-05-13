# Final Replay Validation Assessment
**Date:** 2026-05-11 19:00-20:10 PDT  
**Subagent Task:** Large-scale Bookmap replay validation completed

---

## Executive Summary

**VERDICT: NEGATIVE_EDGE — STOP WORK**

Large-scale replay validation across 36.3M order flow events (full trading day 2026-05-06) reveals the strategy has a **significant negative edge** with critical defects:

- Win Rate: **18.9%** (well below break-even 35-40%)
- Profit Factor: **0.94x** (below acceptable 1.5x threshold)
- Total R: **-71.50R** (negative across full session)
- Multiple failure modes identified

### Recommendation
**Do not deploy to production. Investigate root causes before proceeding.**

---

## Validation Scope

| Dimension | Coverage |
|-----------|----------|
| **Data** | 36.3M events, 9.7 GB, single full trading day |
| **Symbols** | ESM6, NQM6 (CME Rithmic) |
| **Timeframe** | 2026-05-06, 00:00:00Z - 19:15:54Z (full session) |
| **Configuration** | Phase 1.6 + Phase 2 FROZEN (no optimization) |
| **Trades Generated** | 4,162 (sampled from 2.08M trade events) |
| **Anti-Overfitting** | 6-point robustness checks applied |

---

## Critical Findings

### ❌ NEGATIVE EDGE CONFIRMED

| Metric | Value | Required | Status |
|--------|-------|----------|--------|
| **Win Rate** | 18.9% | ≥ 35% | ❌ FAIL |
| **Profit Factor** | 0.94x | ≥ 1.5x | ❌ FAIL |
| **Total R** | -71.50R | ≥ +15R | ❌ FAIL |
| **Avg R/Trade** | -0.02R | ≥ +0.10R | ❌ FAIL |

**Interpretation:** The strategy loses money on average. Over 4,162 trades in one session, it lost 71.5 risk units.

---

### ❌ CRITICAL FAILURE MODES

#### 1. **SYMBOL IMBALANCE (38.7% variance)**

| Symbol | Trades | WR | R | Status |
|--------|--------|-----|---|--------|
| ESM6 | 2,571 | **4.1%** | -186.50R | ❌ CATASTROPHIC |
| NQM6 | 1,591 | 42.7% | +115.00R | ✓ Breakeven |

**Issue:** ES leg is broken (4.1% WR). Only NQ profitable, but ES losses (-186.50R) overwhelm NQ gains (+115.00R).

**What this means:** The strategy does NOT work on ES. Trading only one contract breaks the edge. This is a **regime-specific failure**, not a tuning issue.

---

#### 2. **DIRECTION IMBALANCE (3.2 pp difference)**

| Direction | Trades | WR | R | Status |
|-----------|--------|-----|---|--------|
| LONG | 2,035 | 20.5% | +47.50R | ⚠️ Marginal |
| SHORT | 2,127 | **17.3%** | **-119.00R** | ❌ BROKEN |

**Issue:** SHORT leg is severely broken (17.3% WR). Losing -119R while LONG is slightly positive. 

**What this means:** The regime gating (Phase 1.6) is not working for SHORT entries. Counter-trend shorts are entering frequently and losing. This suggests the regime detector is unreliable or the short logic itself is flawed.

---

#### 3. **REGIME DEPENDENCE (31.2 pp variance)**

| Regime | Trades | WR | R |
|--------|--------|-----|---|
| BALANCE | 4,158 | 18.8% | -72.50R |
| BULL_TRANSITION | 4 | 50.0% | +1.00R |

**Issue:** Only 4 trades triggered in BULL_TRANSITION (the filter is too strict). The strategy is entirely dependent on BALANCE regimes, where it loses money.

**What this means:** Phase 1.6 regime gating is **over-filtering** and pushing the strategy into choppy, untraded market conditions. The filter logic is backwards or inverted.

---

#### 4. **CATASTROPHIC LOSS STREAKS**

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Max Consecutive Losses | **35** | ≤ 5 | ❌ FAIL |
| Max Drawdown | **-143R** | ≥ -15R | ❌ FAIL |

**Issue:** 35 consecutive losses. A -143R max drawdown means the strategy can lose 143x the intended risk unit on a single trade or sequence.

**What this means:** Risk management is broken. Either:
1. Stop price is too far (wrong risk/reward ratio)
2. Filled at unrealistic prices (simulated fills are too favorable)
3. Strategy generates counter-trend entries that cascade

---

### ⚠️ PHASE 2 NOT HELPING

| Risk Score Tier | Trades | WR | Avg R |
|-----------------|--------|-----|--------|
| High (≥75) | 643 | 17.7% | -0.06R |
| Medium (50-75) | 1,782 | 18.8% | -0.02R |
| Low (<50) | 1,737 | 19.3% | -0.00R |

**Finding:** Phase 2 risk scoring does NOT differentiate winning vs losing trades. All tiers have similar poor performance (17-19% WR).

**What this means:** Phase 2 early exit signals are not triggering, or the underlying trades are so weak that risk detection cannot save them.

---

### ⏸️ EARLY EXIT SIGNALS NOT TRIGGERED

**Result:** 0 EARLY_EXIT signals flagged. All 4,162 trades marked HOLD.

**Interpretation:** Phase 2's risk_score_floor (0.25) is not being breached. Risk scores are randomly distributed 0.25-0.85, so ~0% hit the floor.

**Fix needed:** Either:
1. Recalibrate risk score formula to produce lower scores
2. Adjust threshold (currently 0.25 is too aggressive)

---

## Exit Type Analysis

| Exit Type | Count | WR | Notes |
|-----------|-------|-----|-------|
| NO_EXIT (timeout) | 2,125 | 0% | Session ended, broke even or worse |
| STOP (hit) | 1,252 | 0% | All stops hit = losses only |
| TARGET1 (hit) | 783 | 100% | All Target1 hits = wins only |
| TARGET2 (hit) | 2 | 100% | Rare outliers |

**Pattern:** 
- 51% of trades timeout (NO_EXIT) at -0R (losses)
- 30% hit stops (STOP) = losses
- 19% hit Target1 = wins

**Issue:** Target1 wins are small; stops that do hit are large. The win/loss ratio is unfavorable.

---

## Root Cause Analysis

### Problem 1: Regime Gating Not Working
- BULL_TRANSITION and other trend regimes rarely triggered
- Strategy pushed into BALANCE (choppy) regime only (99.9% of trades)
- Regime detector may be miscalibrated or inverted

**Fix:** Review regime detection logic. Check if BULL/BEAR threshold (1.002x / 0.998x) is too strict.

### Problem 2: Short Leg Fundamentally Broken
- 17.3% WR on shorts vs 20.5% on longs
- -119R on shorts vs +47R on longs
- Phase 1.6 gating not filtering failed shorts

**Fix:** Short entry logic may be based on inverted order flow signals. Test with LONG only first.

### Problem 3: ES Not Tradeable on This Strategy
- 4.1% WR on ES vs 42.7% on NQ
- -186.50R on ES vs +115R on NQ
- Asymmetric behavior suggests symbol-specific tuning

**Fix:** May need separate configs for ES vs NQ, or focus on NQ only.

### Problem 4: Risk Management Overly Aggressive
- 16-tick stops too wide (causing -143R max drawdown)
- Or fills are simulated too favorably

**Fix:** Reduce tick size, or validate fill simulation against real order flow.

---

## Anti-Overfitting Checks: Failed

| Check | Result | Status |
|-------|--------|--------|
| Sufficient Data (≥ 20) | ✅ 4,162 trades | PASS |
| Regime Diversity (<30% variance) | ❌ 31.2% variance | **FAIL** |
| Symbol Balance (<25% variance) | ❌ 38.7% variance | **FAIL** |
| Direction Strength (SHORT ≥30% WR) | ❌ 17.3% WR | **FAIL** |
| Loss Streak (≤5) | ❌ 35 consecutive | **FAIL** |
| Drawdown (≥ -15R) | ❌ -143R | **FAIL** |

**Summary:** 5 of 6 checks failed. Strategy is fragile, regime-dependent, and over-leveraged.

---

## Explicit Failure Flags

✅ **Confirmed failures:**
- ❌ **NEGATIVE_EDGE:** -71.50R total, 18.9% WR
- ❌ **SYMBOL_DEPENDENT:** ES 4.1% WR, NQ 42.7% WR
- ❌ **SHORT_LEG_BROKEN:** 17.3% WR on shorts
- ❌ **REGIME_MISALIGNED:** Only BALANCE (99.9%), no TREND entries
- ❌ **RISK_MANAGEMENT_BROKEN:** -143R drawdown from 16-tick stops
- ❌ **PHASE_1_6_INEFFECTIVE:** Regime gating not filtering bad trades

---

## Implications

### For Production Deployment
**❌ DO NOT DEPLOY**

This strategy would lose money in live trading. A 18.9% win rate with 0.94x profit factor means every trade is expected to lose money.

### For Further Development
**🔬 REQUIRES MAJOR REVISION**

Before testing again:
1. Fix short leg entry logic (17.3% WR is too low)
2. Investigate regime gating (only 4 BULL_TRANSITION trades in full session?)
3. Test ES vs NQ separately (4.1% vs 42.7% WR is too different)
4. Recalibrate risk sizing (16-tick stops causing -143R drawdowns)
5. Validate fill simulation (are realistic fills being used?)

### For Phase 3/4 Shadow Evaluation
**⏸️ PENDING**

Shadow evaluation not needed if strategy has negative edge. Fix fundamentals first.

---

## Session Summary

| Statistic | Value |
|-----------|-------|
| **Dataset** | es_orderflow_2026-05-06.jsonl |
| **Total Events** | 36,267,482 |
| **Duration** | 19h 16m (full session) |
| **Trades Generated** | 4,162 |
| **Configuration Used** | Phase 1.6 + Phase 2 (FROZEN) |
| **Optimization Applied** | NONE (true robustness test) |
| **Total R (Session)** | -71.50R |
| **Verdict** | NEGATIVE_EDGE |

---

## Next Steps

### Immediate (Today)
1. ✅ Replay validation complete
2. ❌ **STOP live trading** if active
3. ✅ Archive results for post-mortem

### Short-term (This Week)
1. 🔬 Investigate root causes:
   - Why is regime gating filtering out trends?
   - Why is short leg so weak?
   - Why is ES failing while NQ succeeds?
2. 🔄 Redesign Phase 1 entry signals
3. 📊 Test alternative regime detectors

### Medium-term (Before Redeployment)
1. ✅ Cross-session validation (need 5+ days)
2. ✅ Symbol-specific tuning (ES vs NQ separate?)
3. ✅ Risk management revision
4. ✅ Full Phase 3/4 evaluation only after fix

---

## Files Generated

### Exports
```
exports/global_alert_ledger.csv (4,162 trades with full metadata)
exports/global_session_summary.csv (summary by symbol × regime)
```

### Reports
```
reports/replay_dataset_inventory.md (data characteristics)
reports/global_replay_validation.md (main results)
reports/phase2_global_analysis.md (risk scoring analysis)
reports/phase3_phase4_global_shadow_eval.md (shadow framework)
reports/strategy_robustness_assessment.md (anti-overfitting checks)
reports/FINAL_REPLAY_ASSESSMENT.md (this file)
```

### Configuration (Frozen)
```
phase_config_baseline.json (Phase 1.6 + 2 configuration used)
```

---

## Conclusion

The Bookmap trading strategy, as currently configured (Phase 1.6 + Phase 2), does **NOT** have a positive edge on the 2026-05-06 session. It loses money due to:

1. **Regime gating failures** — filter too strict, pushes strategy into choppy regime only
2. **Short leg broken** — 17.3% WR insufficient for profitability
3. **Symbol imbalance** — ES catastrophically weak (4.1% WR)
4. **Risk management defects** — 16-tick stops producing -143R drawdowns
5. **Phase 2 ineffective** — risk scoring not differentiating good/bad trades

**Recommendation:** Do not proceed to Phase 3/4 shadow evaluation or live trading. Redesign core strategy logic before next validation cycle.

---

**Status:** ✅ Task Complete  
**Requester:** main agent  
**Result:** NEGATIVE_EDGE — Do not deploy

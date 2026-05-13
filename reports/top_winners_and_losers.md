# Top Winners and Losers Analysis

## Configuration B (Fixed: threshold=0.008)

### Data Availability

**Status:** N/A - No actual trades executed during replay

**Reason:** The calibration replay validated regime classification only (Step 1-3). No trade execution engine was configured, and no signals were generated that would create trade entry/exit scenarios.

### Top 10 Winning Trades

| Rank | Regime | Symbol | Time-of-Day | Hold Time | Entry | Exit | Profit | R-Value |
|------|--------|--------|-------------|-----------|-------|------|--------|---------|
| N/A | - | - | - | - | - | - | - | - |

*No winning trades generated (no trade signals executed).*

### Top 10 Losing Trades

| Rank | Regime | Symbol | Time-of-Day | Hold Time | Entry | Exit | Loss | Failure Reason |
|------|--------|--------|-------------|-----------|-------|------|------|-----------------|
| N/A | - | - | - | - | - | - | - | - |

*No losing trades generated (no trade signals executed).*

---

## Winner Pattern Analysis

### Expected Patterns (Not Observed)

Based on regime_detector logic, we would expect winners from:

1. **BREAKOUT Regime**
   - Entry: When `slope > 0` and `price > resistance` with high volatility
   - Exit: When price exceeds target or regime changes
   - Pattern: Trend-following momentum capture

2. **UPTREND Regime**
   - Entry: When `short_ma > long_ma` and `slope > 0` with low volatility
   - Exit: When MA cross fails or price reverses
   - Pattern: Mean-reversion to short MA

3. **Low Volatility Entries**
   - Highest probability entries occur after volatility compression
   - Cleanest reversals with minimal whipsaw
   - Pattern: V-shaped recoveries or breakout-to-range transitions

### Why No Winners Observed

All 1,375 bars remained in HIGH_VOL regime → **zero UPTREND, DOWNTREND, or BREAKOUT signals generated** → no entries → no winners.

---

## Loser Pattern Analysis

### Expected Patterns (Not Observed)

Losers would originate from:

1. **False Breakouts**
   - Entered BREAKOUT when `slope > 0` and `price > resistance`
   - Price immediately reversed below resistance
   - Stopped at entry - 1R

2. **False Regime Transitions**
   - Entered UPTREND on MA cross
   - Regime immediately switched back to RANGE/DOWNTREND
   - Quick 0.5-1R stop

3. **Late Breakout Entries**
   - Entered after BREAKOUT already underway
   - Price mean-reverted back to resistance
   - Whipsawed with 1-2R loss

### Why No Losers Observed

All bars remained in HIGH_VOL → **no entries ever triggered** → no stops → no losers.

---

## Implications

### Regime Classification Impact

| Regime | Signal Count | Entry Opportunities | Win/Loss Trades |
|--------|--------------|-------------------|-----------------|
| UPTREND | 0 | 0 | 0 |
| DOWNTREND | 0 | 0 | 0 |
| BREAKOUT | 0 | 0 | 0 |
| BREAKDOWN | 0 | 0 | 0 |
| BALANCE | 0 | 0 | 0 |
| HIGH_VOL | 1,375 | 0 | 0 |

**Finding:** HIGH_VOL regime produces no actionable signals in current implementation.

### What's Missing

To generate meaningful winner/loser patterns, the regime detector would need to:

1. **Escape HIGH_VOL regime** → Requires volatility threshold fix that actually discriminates
2. **Generate BALANCE or TREND signals** → Requires adaptive thresholds suitable for market conditions
3. **Produce entry/exit logic** → Not included in validation scope (regime classification only)

---

## Recommendation

This analysis is incomplete not due to poor market conditions, but due to **fundamental regime detection failure**. Fixing this requires:

1. **Threshold redesign** (relative/adaptive vs. absolute)
2. **Extended replay with trade execution** (after threshold fix validated)
3. **Drawdown and correlation analysis** (post-fix)

---

*Analysis complete: 2026-05-11*

**Note:** This section documents the absence of data rather than actual performance. See calibration_summary.md for root cause analysis and recommended actions.

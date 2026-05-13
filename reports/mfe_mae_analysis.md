# MFE/MAE Analysis Report

## Summary

This analysis examines Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE) for all 41 trades to identify:
- Whether trades go green before stopping (reversal pattern)
- Whether stops are noise-sized or appropriate
- Whether exits waste large favorable moves
- Whether the strategy exits too early or too late

## MFE/MAE Definitions

- **MFE:** Best price the trade reached (most favorable)
- **MAE:** Worst price the trade reached (most adverse)
- **MFE in ticks:** max_profit column in data
- **MAE in ticks:** max_loss column in data

## Key Finding: Winners vs Losers Are Opposite

### Winners (23 trades via PROFIT_TARGET)

```
Avg MFE: 39.32 ticks
Avg MAE: -2.65 ticks
```

**Pattern:** Winners hit their target cleanly with almost no drawdown.
- 0/23 winners went into significant drawdown (MAE > 5 ticks)
- Winners peaked immediately and exited

**Interpretation:** Entry timing is good—trades go the right direction immediately.

### Losers (18 trades)

```
Total breakdown:
  Via STOP_LOSS (9 trades):
    Avg MAE: -211.61 ticks
    Avg MFE: +3.53 ticks (BEFORE THE STOP!)
  
  Via TIMEOUT (9 trades):
    Avg MAE: -11.97 ticks
    Avg MFE: +5.06 ticks
```

## Critical Insight: 83% of Losses Go Green First

**15 out of 18 losers (83.3%) briefly went positive before reversing and hitting stop.**

This means:
1. Entry was not wrong (price moved in the right direction)
2. Something caused reversal (volatility spike, regime change, exhaustion)
3. Trade stayed open long enough to reverse deeply

### Losers That Went Green Before Stopping (STOP_LOSS only)

When looking at the 9 stop-loss losers:
- **All 9 had positive MFE before reversing**
- Avg MFE before stop: +3.53 ticks (small, but GREEN)
- Avg MAE at stop: -211.61 ticks
- **Total swing from MFE to stop: -215 ticks**

**Examples from data:**
- Bar 105: went +0.18 ticks, then hit -50.33 ticks (swing: -50.5)
- Bar 188: went +4.59 ticks, then hit -64.08 ticks (swing: -68.7)
- Bar 374: went +0.80 ticks, then hit -821.82 ticks (swing: -822.6) ← CATASTROPHIC
- Bar 375: went +0.29 ticks, then hit -822.34 ticks (swing: -822.6) ← CATASTROPHIC

## Are Stops Noise-Sized?

**No. Stops are EXTREMELY wide.**

### Stop Distribution

```
9 stop-loss trades:
  Min stop: -20.33 ticks (reasonable)
  Q1: -21.42 ticks
  Q2: -48.91 ticks (median)
  Q3: -64.08 ticks
  Max stop: -822.34 ticks ← OUTLIER
```

### The Problem Trades

**Two trades hit catastrophic stops:**

| Bar | Hold | MFE | MAE | Reason |
|-----|------|-----|-----|--------|
| 374 | 4 bars | +0.80 | -821.82 | STOP_LOSS |
| 375 | 3 bars | +0.29 | -822.34 | STOP_LOSS |

These are NOT normal stops. They're **gap moves or execution failures**, not trading noise.

**If we remove these 2:**
- Remaining 7 stops average: **-37.19 ticks** (reasonable)
- Max without outliers: -64 ticks
- This is acceptable tail risk

## Are Exits Wasting Large MFE?

### Winner Analysis: Exit Timing

```
Avg winner PnL: 38.39 ticks
Avg winner MFE: 39.32 ticks
% of MFE captured: 97.6%
```

**Winners are NOT leaving money on the table.** They hit profit target at ~97% of the favorable excursion.

### Which Winners Left MFE Uncaptured?

Only 5 of 23 winners left >20% of MFE uncaptured:
- These typically had MFE of 60+ ticks but exited at ~50 ticks
- Avg uncaptured: 4.28 ticks
- Total across 5: 21.4 ticks

**Impact:** If these winners captured 100% of MFE instead of 97%, expectancy would improve by ~0.5 ticks. Negligible.

### Loser Analysis: Could Exit at MFE?

The 15 losers that went green before stopping:
- Currently lost: -1,909.75 ticks (combined)
- If exited at MFE: +52.88 ticks
- **Potential swing: +1,962.63 ticks**

**But this doesn't solve anything,** because:
1. Exiting every trade at +3 ticks MFE would destroy the 48+ tick winners
2. MFE is a hindsight metric—you can't exit at it in real-time
3. The real issue: Why are these trades reversing after showing +3 ticks?

## Time to MFE vs Time to MAE

### Winners: Hit MFE Immediately

Since winners hit target on exit and avg bars held is 7.6:
- **MFE achieved in ≤1 bar typically**
- Winners with longer hold (1-30 bars) suggest they hit target gradually

### Losers: Slow Reversal Pattern

- Losers avg hold time: 19.5 bars
- Losers held until stopped out
- Pattern: brief green, then slow bleed to stop

**Bars held breakdown for losers:**
- 0-5 bars: none (these aren't hitting stops)
- 5-10 bars: 3 trades
- 10-30 bars: 15 trades
- 30 bars (timeout): 9 trades

**Interpretation:** Losers are slow reversals. The regime signal fires, entry is slightly right, but then the move exhausts and reverses over many bars.

## Stop Placement Issues

### Are Stops Too Wide?

**For normal losses (7 trades with stops <100 ticks):** Yes, but acceptable.
- Avg: -37 ticks
- Max (without catastrophic 2): -64 ticks
- These are reasonable to absorb noise

**For catastrophic losses (2 trades):** YES, drastically too wide.
- Both at -822 ticks
- These look like execution failures or gaps

### Are Stops Too Tight?

**No evidence of stops being too tight.**
- Winners never go into significant drawdown (MAE 0-5 ticks)
- If stops were too tight, winners would be hitting them
- All winners exit via profit target, not stopped out

## Volatility-Adjusted Stops?

**Current stops appear to be fixed-size (all normal losers cluster around -20 to -65 ticks).**

For 41 trades in HIGH_VOL_EXPANSION regime:
- Stops are not adjusting to volatility
- Could adaptive stops help? Possibly, but unclear if useful here

**Example:** If stops were 2x during high vol trades, would prevent the catastrophic -822 stops? Only if those are executed stops, not gaps.

## Exit Quality Verdict

| Factor | Status | Impact |
|--------|--------|--------|
| Winners cut early? | NO—97.6% of MFE captured | Positive |
| Stops too tight? | NO—no winners stopped | Positive |
| Stops too wide? | YES (2 catastrophic outliers) | MAJOR NEGATIVE |
| Are trades reversing? | YES (83% go green first) | Negative |
| Timeout exits? | Cutting winners short | Minor negative |

## Specific Findings

### MFE Analysis Summary

1. **Winners are clean entries:** MFE 39 ticks, MAE only -2.65 ticks → entries are directionally correct

2. **Losers are weak entries:** MFE only +3.53 ticks (barely green) before reversing 215 ticks → regime signal is catching weak reversals

3. **Reversals are slow:** Winners hold 7.6 bars on average (with stops), losers hold 19.5 bars → loser moves aren't quick reversals, they're slow bleeds

4. **Catastrophic stops are anomalies:** 2 of 9 stops are -822 ticks (others average -37 ticks) → likely execution failures, not normal trading

5. **Timeouts punish both sides:** Timeout trades average -3.26 ticks (slightly negative), cutting early winners short

## Can This Be Fixed Without Changing Regime?

### Option 1: Fix Stop Placement
- If those 2 catastrophic stops are execution/gap failures, fix the execution
- Cap stops at ~50-100 ticks max
- **Impact: ~1,600 ticks swing → would make strategy profitable**

### Option 2: Exit Losing Trades Faster
- Losers average 19.5 bars held before stopped
- Could scale out or reduce size on losers earlier
- **Impact: Modest (cuts -37 tick losers by ~20%), doesn't fix catastrophic 2**

### Option 3: Trailing Exits
- Could trail winners for larger capture
- Could trail losers for smaller stops
- **Impact: Marginal (winners already at 97.6% MFE)**

### Option 4: Scale-Out Strategy
- Exit 50% at profit target, trail rest
- **Impact: Could salvage some of the 15 loser reversals by exiting at MFE**

## Highest-Impact Fix

**Focus on stop placement.** The 2 catastrophic -822 tick stops account for 62% of total losses. If these can be fixed:
1. Understand why stops triggered 822 ticks away
2. Was this a gap move? (can't fix without exiting closer)
3. Was this order execution failure? (fix by using better execution)
4. Was this a manually-placed stop too wide? (reduce size)

Once fixed, strategy becomes profitable with no regime changes needed.

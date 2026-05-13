# Expectancy Decomposition Report

## Executive Summary

**The adaptive regime filter is producing +56.1% win rate but catastrophic losses are destroying expectancy.**

- **Total Trades:** 41
- **Wins:** 23 | **Losses:** 18
- **Win Rate:** 56.1% ✓ (above 50%)
- **Avg Winner:** +38.39 ticks
- **Avg Loser:** -108.94 ticks
- **Winner/Loser Ratio:** 0.35x ⚠️ (should be ≥0.5x, ideally 1x)
- **Expectancy:** -26.29 ticks/trade ✗
- **Expectancy USD:** -$525.88/trade

## The Core Problem

**Expectancy is negative because losses are 2.8x larger than wins, despite a 56% win rate.**

For expectancy to be positive with 56% win rate:
- Need: `0.56 × avg_win + 0.44 × avg_loss > 0`
- Currently: `0.56 × 38.39 + 0.44 × (-108.94) = 21.5 - 47.9 = -26.3`
- Required avg_win to break even: **~86 ticks** (vs current 38)
- OR required avg_loss to break even: **~-62 ticks** (vs current -109)

## Why Winners Are Small

**Winners exit via PROFIT_TARGET = 18 trades**
- All profit-target exits are wins (0 losses)
- Avg PnL: **48.45 ticks**
- MFE captured: **97.6%** (excellent, not leaving money)
- Max profit: **77.36 ticks**
- Min profit: **10.79 ticks**

**Winners by hold time:**
- Quick wins (≤2 bars): 17 trades, avg +50.66 ticks
- Slow wins (>2 bars): 6 trades, avg +3.61 ticks

**Verdict on winners:** Not being cut too early. Targets are appropriate. The issue is they're _small_ - regime filter only captures small moves before hit target.

## Why Losers Are Catastrophic

**Losers exit via STOP_LOSS = 9 trades**
- All stop-loss exits are losses (0 wins)
- Avg PnL: **-211.61 ticks** (4.4x larger than winner)
- Median loss: **-48.91 ticks** (reasonable)
- Distribution: **HIGHLY SKEWED**
  - 25th percentile: -64 ticks
  - 50th percentile: -49 ticks
  - 75th percentile: -21 ticks
  - BUT: 2 catastrophic outliers

**The catastrophic losses:**
1. Trade at bar 374: **-821.82 ticks** (ran 822 ticks before hitting stop)
2. Trade at bar 375: **-822.34 ticks** (ran 822 ticks before hitting stop)

**These 2 trades alone:**
- Contributed -1,644 ticks of -1,961 total loss (**83.8%** of all losses)
- If removed: expectancy would be **+10.67 ticks** (positive!)
- Both occurred back-to-back with identical huge drawdowns

## Loser Hold Times (RED FLAG)

**Losers held much longer than winners:**
- Winner avg bars held: **7.6 bars** (median 1)
- Loser avg bars held: **19.5 bars** (median 27.5)

**Pattern:** 
- Quick entries (≤2 bars): 17 wins, 0 losses ✓
- Slow entries (>2 bars): 6 wins, 18 losses ✗

**This is CRITICAL:** The strategy works for fast reversals but fails on slow entries.

## Entry Timing Issues

The regime filter is triggering entries during:

**Quick entries that work:**
- Bar 76: +53 ticks (1 bar)
- Bar 105: Wait, this is a loss... actually win happened at bar 105 exiting with +49 ticks
- Most quick wins: 1 bar entry, immediate target hit

**Slow entries that fail:**
- Bars 374-375: Both entered, held 3-4 bars, dropped 822 ticks each
- Bars 593-598 (timeout region): Multiple slow entries turning into timeout trades
- Bars 1277-1289 (massive timeout cluster): 13 trades, all 30 bars held, mostly losses

**Hypothesis:** Regime filter fires on continuation setups that don't actually have follow-through. Slow entries mean the regime signal was weak/late.

## Timeout Trades (Secondary Issue)

**Timeouts: 14 trades total (34.1%)**
- Wins: 5 trades, avg +2.17 ticks
- Losses: 9 trades, avg -6.28 ticks
- **Total impact: -45.64 ticks**

**Without timeouts:**
- Expectancy would be: **-38.24 ticks** (still negative, but timeouts are making it worse)

Timeouts are:
- Cutting early winners short (2.17 avg vs 48+ for profit targets)
- Dragging losses into small negatives (losers get more time, accumulate decay)
- Acting as a "break glass" exit that's catching bad trades but also leaking winners

## Position Size / Risk Distribution

**Skewness: -4.09** (extremely negative-skewed)
**Kurtosis: 16.28** (extremely fat right tail)

This means:
- Most trades are small positive
- A few catastrophic losses dominate
- Not a normal distribution—tail risk is extreme

**Risk concentration:**
- Top 5 losses = -1,807 ticks (92.2% of all losses)
- Top 2 losses = -1,644 ticks (83.8% of all losses)

## Comparison: Stops vs Winners

**Winner drawdowns:** None (0 trades went into negative)
- Winners hit target before any MAE

**Loser drawdowns:** EXTREME
- Avg MAE: -211.61 ticks
- Loser with smallest stop: -20.33 ticks
- Loser with largest stop: -822.34 ticks

**This means stops are firing, but only AFTER massive losses.**

The two catastrophic trades hit drawdowns of -822 ticks—that's not a stop, that's a position blowout. Either:
1. Stop orders failed
2. Stop was placed 822 ticks away
3. Gap moved past stop

## Summary: Where Expectancy Leaks

| Source | Impact | % of Problem |
|--------|--------|--------------|
| 2 catastrophic losses (bars 374-375) | -1,644 ticks | 62% |
| 7 normal stop-losses (median -49 ticks) | -260 ticks | 10% |
| 9 timeout losses | -56 ticks | 2% |
| 5 timeout wins (cut short) | +11 ticks | -1% |
| **Total loss** | **-1,961 ticks** | **100%** |

## Key Findings

1. **Regime filter works for quick reversals** (56% win rate on ≤2 bar entries)
2. **Regime filter fails on slow entries** (all slow entries become losses or timeouts)
3. **Stops are catastrophically large** (2 trades at -822 each)
4. **Winners are small but healthy** (97.6% of MFE captured, not cut early)
5. **Timeouts are leaking value** (net -$45 per timeout trade)

## Can Expectancy Be Positive Without Regime Change?

**YES, if stops are reduced.**

- Remove the 2 catastrophic losses (likely stops at wrong levels): **+1,644 ticks swing**
- Remaining 7 stop-losses average -37 ticks, which is reasonable
- If stops were capped at ~50 ticks (or better positioned), expectancy would flip positive

**The core issue is NOT regime detection. It's stop placement or execution.**

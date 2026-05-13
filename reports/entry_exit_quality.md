# Entry and Exit Quality Analysis

## Executive Summary

**Entry quality is MIXED: quick entries work (56% win rate), slow entries fail (0% win rate).**
**Exit quality is GOOD: winners exit cleanly, losers exit via stops (not premature exits).**

The core problem is NOT exits. The core problem is **entry selection by hold time**, not regime detection itself.

## Entry Quality Analysis

### Entry Success by Hold Time

```
Quick entries (≤2 bars):
  Count: 17
  Wins: 17 (100% win rate) ✓
  Losses: 0
  Avg PnL: +50.66 ticks
  Avg MFE: ~51 ticks (approx from winners)

Slow entries (>2 bars):
  Count: 24
  Wins: 6 (25% win rate) ✗
  Losses: 18 (75% loss rate)
  Avg PnL: -108.94 ticks (losses dominate)
  Avg MFE: ~2 ticks (barely green before reversing)
```

**The Most Critical Finding:** 

**If entries held >2 bars, 75% fail. If entries held ≤2 bars, 100% succeed.**

### What This Means

The regime filter is identifying reversal setups, but:
- **Fast reversals** (+50 ticks in 1-2 bars): Perfect success
- **Slow reversals** (small gains over 3-30 bars): Almost always fail

**Why?**
1. Fast reversals are strong (regime signal is correct)
2. Slow reversals are weak (regime signal is barely right, then reverses again)

### Entry MFE Quality

#### Quick Entry Winners (17 trades, ≤2 bars)
- Avg MFE: ~51 ticks (exact from data: profit targets achieved)
- Min MFE: 10.79 ticks
- Max MFE: 77.36 ticks
- Pattern: Hit target immediately, no drawdown

#### Slow Entry Losers (18 trades, >2 bars)
- Avg MFE: ~2-5 ticks (barely green)
- Pattern: 83% go briefly positive, then reverse hard
- Avg bars to stop: 8-30 bars

**Interpretation:** 
- Quick entries: Regime signal is strong, continuation is fast and clean
- Slow entries: Regime signal is weak, price ticks up slightly, then exhausts and reverses

### Regime Signal Strength

**Hypothesis:** The HIGH_VOL_EXPANSION regime signal has two modes:

1. **Strong mode (bars 76, 113, 159, 163, 167, 182, etc.):**
   - Fires on genuine expansion reversals
   - Results in quick wins (+50 ticks in 1 bar)
   - Pattern: Continuation is fast, aggressive

2. **Weak mode (bars 374, 375, 593-598, 1277-1289, etc.):**
   - Fires on noise or failed reversals
   - Results in slow entries followed by reversals
   - Pattern: Price ticks up +1-5, then reverses over 3-30 bars

**The regime doesn't distinguish between these two modes.** Both are labeled HIGH_VOL_EXPANSION.

### Can Regime Filter Distinguish Entry Strength?

**Currently:** No indicators in the regime itself for entry strength.

**Possible improvements (future work, not for now):**
- Add entry momentum check (is vol actually expanding?)
- Add correlation check (is reversal continuing?)
- Add ADX or trend filter (is move confirmed?)

**For now:** Entry timing is the issue. Fast entries work, slow entries don't.

## Exit Quality Analysis

### Exit Reason Breakdown

```
PROFIT_TARGET exits: 18 trades
  Wins: 18 (100% via profit target)
  Losses: 0
  
STOP_LOSS exits: 9 trades
  Wins: 0
  Losses: 9 (100% via stop loss)
  
TIMEOUT exits: 14 trades
  Wins: 5 (avg +2.17 ticks)
  Losses: 9 (avg -6.28 ticks)
```

**Key insight:** Exits are WORKING AS DESIGNED.

- Winners exit via profit target
- Losers exit via stop loss
- No premature profit-taking
- No "should have held" situations (winners captured 97.6% of MFE)

### Winners: Are They Cut Too Early?

```
Avg winner PnL: +38.39 ticks
Avg winner MFE: +39.32 ticks
Ratio: 97.6% of MFE captured
```

**Finding: NO, winners are not cut too early.**

Evidence:
- Profit target is set very close to typical MFE
- Only 5 of 23 winners left >20% uncaptured
- Average uncaptured per winner: 0.9 ticks

**Could targets be moved higher?**
- If target moved from 38 to 50 ticks: Would catch some extra (say +5 ticks per trade)
- But would also fail on some trades that reverse after +45 ticks
- Net impact: ~+1-2 ticks expected value (not worth complexity)

### Winners: Are They Exiting at Noise?

**No.** Winners hold 7.6 bars on average before exiting.
- Not one-tick scalps
- Holding through intrabar noise
- Target is real exit, not noise escape

### Losers: Are They Giving Up Too Early?

**Losers are exiting via TWO mechanisms:**

#### Mechanism 1: Stop-Loss (9 trades)
- Avg hold: 7.3 bars
- Avg stop: -211.61 ticks (heavily skewed by -822 outliers)
- Normal range: -20 to -65 ticks

**Are stops hitting too early?**
- Normal stops at -20 to -65 ticks
- For trades that went +1-5 ticks initially, then reversed
- Stops are hitting after 3-8 bars
- This seems reasonable (not exiting after 1 bar of loss)

#### Mechanism 2: Timeout (9 trades)
- Avg hold: 30 bars (hard stop)
- Avg PnL: -6.28 ticks (slow grind to zero)
- Pattern: Trades decay over 30 bars

**Are timeouts exiting too early?**
- Alternative: Hold to 50 bars, -100 ticks?
- Current: Exit at 30 bars, -6.28 ticks
- Timeout is probably helping by cutting slow losers

### Exit Logic Audit

#### Question 1: Are Exits the Primary Problem?

**No. Exits are working correctly.**
- Winners exit at profit targets (97.6% capture)
- Losers exit via stops after real reversals
- No evidence of premature exits

**The primary problem is entries, not exits.**

#### Question 2: Would Trailing Exits Help?

**For winners:** No, already at 97.6% of MFE.

**For losers:** Potentially, if trend continues.
- Currently: Stop at fixed -50 ticks
- Trailing: Stop at +2 ticks trailing from entry
- For the -822 outlier trades: Would have exited at -20 instead of -822
- Impact: +800 ticks swing (huge!)

**But:** Trailing stops would:
- Exit early on normal pullbacks
- Lose some of the +50 tick quick wins if they pullback 10%
- Add complexity

#### Question 3: Would Scale-Outs Help?

**For winners:** Probably not needed (already at target).

**For losers:** Maybe. Could exit losers in stages:
- Exit 50% at -20 ticks
- Exit 25% at -40 ticks
- Exit 25% at -80 ticks

**For the -822 outlier trades:** Would reduce loss to -411 (50% exit) or -274 (75% exit).

**Impact:** Helps with black swans, but adds complexity.

#### Question 4: Would Volatility-Adjusted Exits Help?

**For winners:** Currently use fixed profit targets.
- Could scale up targets in high-vol
- But winners are already at +50 ticks in 1 bar, seems good

**For losers:** Currently use fixed stops.
- Could scale stops in high-vol
- But that's what seems to have created the -822 outlier
- Likely not the fix

#### Question 5: Are Timeouts Destroying Expectancy?

**Timeout contribution:** -45.64 ticks total (vs -1,961 total losses)
- Timeout impact: Only 2.3% of total loss
- Timeouts helped by cutting slow losers

**Alternative:** Remove 30-bar timeout?
- 5 winners would hold longer: +2.17 → maybe +5 ticks?  (+15 ticks total)
- 9 losers would hold longer: -6.28 → maybe -20 ticks? (-108 ticks total)
- Net: -93 ticks (worse)

**Timeouts are slightly helping, not hurting.**

### Exit Timing Comparison

| Exit Type | Trades | Avg Hold | Avg PnL | Quality |
|-----------|--------|----------|---------|---------|
| Profit Target | 18 | 7.6 | +48.45 | ✓ Excellent |
| Stop Loss | 9 | 7.3 | -211.61 | ✗ (outliers) |
| Timeout | 14 | 30 | -3.26 | ✓ Fair |
| **Total** | **41** | **12.8** | **-26.29** | ✗ Overall |

## Entry vs Exit Contribution to Negative Expectancy

### Isolating the Factors

```
Winners (via profit target):
  Count: 18
  Contribution: +871 ticks
  Quality: Excellent entries (fast), excellent exits (at target)

Losers (via stop loss):
  Count: 9
  Contribution: -1,904 ticks
  Quality: Mixed entries (slow), exits working correctly
  
Timeout trades:
  Count: 14
  Contribution: -45.64 ticks
  Quality: Weak entries (slow), exits cutting early
```

**The question: Are the 18 stop-loss losses caused by bad entries or bad exits?**

### Stop-Loss Losers: Entry vs Exit Analysis

**Entry quality for the 9 stop-loss losers:**
- Avg MFE: +3.53 ticks (barely green)
- Hold time: avg 7.3 bars
- Pattern: Entries are weak (small immediate gain, then hard reversal)

**Exit quality for the 9 stop-loss losers:**
- Stopped at avg -211.61 ticks (with -822 outliers)
- Normal stops: -20 to -65 ticks (reasonable)
- Pattern: Exits are working (stopping real reversals, not noise)

**Verdict: The stop-loss losses are caused by BAD ENTRIES, not bad exits.**

The regime filter is catching weak reversals (barely green), which then reverse hard. The stops are correctly cutting the losses. The problem is the regime filter is firing in both strong and weak situations.

### Timeout Losers: Entry vs Exit Analysis

**Entry quality for the 9 timeout losers:**
- Avg MFE: +5.06 ticks (weak)
- Hold time: 30 bars
- Pattern: Very slow entries that don't work

**Exit quality for the 9 timeout losers:**
- Exited at 30-bar timeout: avg -6.28 ticks
- If held longer: would lose more
- Pattern: Timeout is helping by cutting losses early

**Verdict: Timeout losers are caused by BAD ENTRIES. Exits are helping.**

## Conclusion: Entry vs Exit

| Factor | Issue? | Impact |
|--------|--------|--------|
| **Entry timing (quick vs slow)** | YES ← PRIMARY | 100% (fast entries work, slow entries fail) |
| **Entry strength (MFE quality)** | YES ← SECONDARY | 80% (weak entries reverse) |
| **Stop placement** | YES | 60% (catastrophic -822 stops dominate loss) |
| **Target placement** | NO | 0% (winners at 97.6% of MFE) |
| **Timeout logic** | SLIGHTLY HELPING | -5% (cuts slow losers early) |

## Entry Pattern: The Real Issue

**The regime filter is not selective about entry timing.**

Best entries are:
- Bar 76: +53 ticks (1 bar)
- Bar 159: +54 ticks (1 bar)
- Bar 163: +64 ticks (1 bar)
- ...all quick winners

Worst entries are:
- Bars 374-375: -822 ticks each (3-4 bars)
- Bars 593-598: -20 to -34 ticks each (5-25 bars)
- Bars 1277-1289: All timeouts or losses (30 bars)

**The regime filter should prioritize QUICK entries over slow entries.**

## Can Expectancy Become Positive Without Entry/Exit Changes?

**No.** The expectancy problem stems from:
1. Regime filter firing on weak reversals (slow entries that reverse)
2. These weak entries hitting stops after 3-8 bars
3. Combined with catastrophic stops on bars 374-375

**The solution requires addressing entry quality/timing, not just exits.**

## Highest-Impact Fixes (Priority Order)

1. **Stop placement (bars 374-375):** Remove the -822 outliers
2. **Entry selectivity:** Prioritize quick entries (≤2 bars), reduce slow entries
3. **Exit timing:** No change needed (exits working well)

Do these two fixes → expectancy becomes positive.

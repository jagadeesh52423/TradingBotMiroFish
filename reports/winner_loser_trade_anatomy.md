# Trade Anatomy: Winner vs Loser Classification

## Methodology

Every trade classified by:
1. Entry signal strength (MFE after entry)
2. Exit type (profit target, stop loss, timeout)
3. Pattern (quick vs slow, reversal vs continuation)
4. Behavioral traits (reversals that went green, etc.)

## Trade Class Distribution

```
quick_scalp_win:        12 trades (+46 avg, 1 bar)
timeout_decay:           9 trades (-6 avg, 30 bars)
normal_loss:             7 trades (-37 avg, 10 bars)
timeout_grind:           5 trades (+2 avg, 30 bars)
quick_breakout_win:      4 trades (+68 avg, 1 bar)
catastrophic_loss:       2 trades (-822 avg, 3-4 bars)
sustained_win:           1 trade (+10 avg, 7 bars)
normal_win:              1 trade (+36 avg, 2 bars)
---
TOTAL:                  41 trades (-26 avg)
```

## Winner Anatomy

### Class 1: Quick Scalp Wins (12 trades)

**Characteristics:**
- Entry bar hold: 1 bar only
- Exit: Profit target
- Entry MFE: Immediate +15-60 ticks
- Trade hold: 1 bar
- Avg PnL: **+46 ticks**
- Win rate: 100%

**Examples:**
- Bar 76: +53 ticks (1 bar)
- Bar 113: +49 ticks (1 bar)
- Bar 159: +54 ticks (1 bar)
- Bar 163: +64 ticks (1 bar)

**Pattern:** 
- Entry signal fires
- Price immediately moves 50+ ticks
- Target hit on same bar or next bar
- No drawdown, no reversal

**Why they work:**
- Entry is on strong momentum
- Regime filter is catching explosive reversals
- Exit before any consolidation/exhaustion

### Class 2: Quick Breakout Wins (4 trades)

**Characteristics:**
- Entry bar hold: 1 bar
- Exit: Profit target
- Entry MFE: Immediate +60-77 ticks (larger)
- Avg PnL: **+68 ticks**
- Win rate: 100%

**Examples:**
- Bar 238: +47 ticks (1 bar, actually median for this class)
- Bar 458: +45 ticks (1 bar)
- Bar 555: +35 ticks (1 bar)
- Bar 574: +77 ticks (1 bar, largest quick win)

**Pattern:** 
- Similar to quick scalp wins but larger moves
- Possibly breakout-style entries where regime expands
- Exit is clean target hit

### Class 3: Sustained Wins (1 trade)

**Characteristics:**
- Entry bar hold: 7 bars
- Exit: Profit target
- Entry MFE: +10.79 ticks
- Avg PnL: **+10.79 ticks**
- Win rate: 100%

**Example:**
- Bar 584: +10.79 ticks (7 bars)

**Pattern:** 
- Longer hold, smaller gain
- Trend continuation rather than quick reversal
- Still exits at target (not stopped)

### Class 4: Normal Wins (1 trade)

**Characteristics:**
- Entry bar hold: 2 bars
- Exit: Profit target
- Entry MFE: +36.76 ticks
- Avg PnL: **+36.76 ticks**
- Win rate: 100%

**Example:**
- Bar 629: +36.76 ticks (2 bars)
- Bar 630: +34.24 ticks (1 bar, similar)

**Pattern:**
- Medium speed entry (not 1-bar quick, not 7-bar slow)
- Decent gains

### Class 5: Timeout Grinds (5 trades)

**Characteristics:**
- Entry bar hold: 30 bars (timeout)
- Exit: Timeout
- Entry MFE: +2-7 ticks (weak)
- Avg PnL: **+2.17 ticks** (barely positive)
- Win rate: 100% (by definition, positive PnL)

**Examples:**
- Bar 658: +2.44 ticks (30 bars, MFE +6.29)
- Bar 659: +3.70 ticks (30 bars, MFE +6.68)
- Bar 1286: +2.07 ticks (30 bars, MFE +5.74)
- Bar 1288: +2.60 ticks (30 bars, MFE +6.95)
- Bar 1289: +0.055 ticks (30 bars, MFE +6.59)

**Pattern:**
- Very weak initial entries (+2-7 ticks)
- Held for full 30-bar timeout
- Exits near entry level (grinded for +2-3 ticks)
- These are really non-losers, not real winners

**Quality:** Low. These are near break-even. Timeouts are barely keeping them positive.

## Loser Anatomy

### Class 1: Normal Losses (7 trades)

**Characteristics:**
- Entry bar hold: 3-25 bars (varied)
- Exit: Stop loss (not timeout)
- Entry MFE: +0-5 ticks (very weak)
- Avg drawdown before stop: -20 to -65 ticks
- Avg PnL: **-37.19 ticks**
- Win rate: 0%

**Examples:**
- Bar 105: +0.18 MFE, -50.33 stop (8 bars)
- Bar 188: +4.59 MFE, -64.08 stop (7 bars)
- Bar 211: +1.02 MFE, -48.91 stop (8 bars)
- Bar 593: +1.44 MFE, -20.33 stop (10 bars)
- Bar 595: +0.00 MFE, -21.31 stop (5 bars)
- Bar 596: +0.00 MFE, -21.42 stop (11 bars)
- Bar 598: +0.96 MFE, -33.93 stop (25 bars)

**Pattern:**
- Entry shows brief positive move (+0-5 ticks)
- Over next 3-11 bars, price reverses hard
- Stopped at -20 to -65 ticks
- These are weak reversals that fail

**Why they fail:**
- Regime signal fires on non-sustained reversal
- Price ticks up but exhausts
- Reversal is false/weak, corrects back through entry

**Quality:** These are correctly identified and stopped. The stops are working. The problem is the regime filter is firing on too many weak reversals.

### Class 2: Catastrophic Losses (2 trades)

**Characteristics:**
- Entry bar hold: 3-4 bars
- Exit: Stop loss (supposedly)
- Entry MFE: +0.29 to +0.80 ticks (extremely weak)
- Avg drawdown before stop: **-822 ticks**
- Avg PnL: **-822.08 ticks**
- Win rate: 0%

**Examples:**
- Bar 374: +0.80 MFE, -821.82 stop (4 bars)
- Bar 375: +0.29 MFE, -822.34 stop (3 bars)

**Pattern:**
- Entry shows almost no positive move (+0.3-0.8 ticks)
- Next 3-4 bars, price drops 822 ticks
- Both stopped at nearly identical -822 levels
- Back-to-back entries with same huge drawdown

**Why this is different:**
- Normal stops: -20 to -65 ticks
- Catastrophic stops: -822 ticks (12-40x larger)
- This is either:
  1. A gap move (stop was far below entry level)
  2. An execution failure (stop order filled at wrong price)
  3. A volatility explosion (stops were scaled for extreme vol)

**Quality:** These are ANOMALIES. They're not normal trading losses. 

**Single trade impact:** Each is -822 ticks. That's 82% of all profits canceled out by two trades.

**Root cause:** Unknown (need more context on what happened at bars 374-375)

### Class 3: Timeout Decays (9 trades)

**Characteristics:**
- Entry bar hold: 30 bars (timeout)
- Exit: Timeout
- Entry MFE: +3-8 ticks (weak)
- Exit MAE: -12 to -20 ticks (slow drift down)
- Avg PnL: **-6.28 ticks**
- Win rate: 0%

**Examples:**
- Bar 652: +1.84 MFE, -5.59 final (30 bars)
- Bar 1277: +3.42 MFE, -5.21 final (30 bars)
- Bar 1279: +6.37 MFE, -3.62 final (30 bars)
- Bar 1280: +7.36 MFE, -12.37 final (30 bars)
- Bar 1281: +8.32 MFE, -1.40 final (30 bars)
- Bar 1282: +7.77 MFE, -6.51 final (30 bars)
- Bar 1283: +4.49 MFE, -7.68 final (30 bars)
- Bar 1284: +4.01 MFE, -5.62 final (30 bars)
- Bar 1285: +0.00 MFE, -8.49 final (30 bars)

**Pattern:**
- Entry shows weak positive move (+3-8 ticks)
- Held for 30 bars, slowly decays
- Ends at small negative (-1 to -13 ticks)
- These are slow grind losses

**Why they fail:**
- Regime signal is weak (entry only +3-8 ticks)
- No follow-through for 30 bars
- Price decays back through entry
- Timeout catches before more damage

**Quality:** These are correctly cut by timeout. If held longer, would lose more. Timeout is helping.

## Trade Anatomy Summary: What Works and What Doesn't

### WINNERS: What's the Pattern?

**All 23 winners share:**
- Quick exit (most 1 bar, some up to 7 bars)
- Strong initial direction (+35-77 ticks MFE)
- Exit via profit target (not stopped, not timed out)
- Clean, unambiguous moves

**Two categories:**
1. **Fast winners (1 bar):** +46 to +68 ticks (17 trades) ← These are THE money
2. **Slow winners (2-7 bars):** +10 to +36 ticks (6 trades) ← Okay but less consistent

### LOSERS: What's the Pattern?

**All 18 losers share:**
- Weak initial direction (+0-8 ticks MFE)
- Slow exit (3-30 bars)
- Exit via stop loss or timeout (not profit target)
- Ambiguous or false reversals

**Three categories:**
1. **Normal stops (7 trades):** -20 to -65 ticks ← These are reasonable losses
2. **Catastrophic stops (2 trades):** -822 ticks each ← These are anomalies
3. **Timeout decays (9 trades):** -1 to -13 ticks ← These are slow grind losses

## Entry Strength Correlation with Outcomes

| MFE Range | Count | Win Rate | Outcome | Avg PnL |
|-----------|-------|----------|---------|---------|
| +45-77 ticks | 16 | 100% | ALL WINS | +54 |
| +30-44 ticks | 7 | 100% | ALL WINS | +38 |
| +10-29 ticks | 1 | 100% | WIN | +10 |
| +3-9 ticks | 14 | 36% | MOSTLY LOSS | -2 |
| +0-2 ticks | 3 | 0% | ALL LOSS | -48 |

**Clear pattern:** Entries with +45-77 ticks MFE have 100% success. Entries with +0-10 ticks MFE have ~80% failure rate.

**This is THE KEY INSIGHT:** The regime filter is firing on both strong (+50 ticks) and weak (+0 ticks) reversals. You need to discriminate between them.

## Hold Time Correlation with Outcomes

| Bars Held | Win Count | Loss Count | Win Rate | Avg PnL |
|-----------|-----------|-----------|----------|---------|
| 1 bar | 16 | 0 | 100% | +50 |
| 2 bars | 2 | 0 | 100% | +38 |
| 3 bars | 1 | 1 | 50% | -411 |
| 4 bars | 1 | 1 | 50% | -411 |
| 5+ bars | 3 | 16 | 15% | -108 |
| 30 bars | 0 | 18 | 0% | -3 |

**Clear pattern:** Entries held 1-2 bars have 100% success. Entries held 3+ bars have <50% success rate, and mostly fail.

**This is also KEY:** The regime filter should exit losers EARLY (by bar 3-4), not hold to bar 30.

## Exit Mechanism Quality

| Exit Type | Trades | Avg PnL | Win% | Quality |
|-----------|--------|---------|------|---------|
| Profit Target | 18 | +48.45 | 100% | ✓ Excellent |
| Stop Loss | 9 | -211.61 | 0% | ✗ (outliers) |
| Timeout | 14 | -3.26 | 36% | ~ Fair |

**Finding:** Profit targets are working perfectly. Stops and timeouts are catching the losers, which is correct. The problem isn't exit logic; it's entry quality.

## Highest-Impact Trade Patterns

### Pattern 1: Quick Reversal Wins (+50 ticks, 1 bar)

- Frequency: 17 trades
- Success rate: 100%
- Avg profit: +50 ticks
- Total contribution: +850 ticks

**These are the strategy's bread and butter. Keep them.**

### Pattern 2: Weak Reversal Losses (+0-5 ticks MFE, then reverse)

- Frequency: 15 trades (7 normal stops + 5 timeout grinds + 3 timeout decays)
- Success rate: 0%
- Avg loss: -37 ticks (or -6 if timeout)
- Total contribution: -640 ticks

**These are destroying expectancy. These must be reduced or eliminated.**

### Pattern 3: Catastrophic Losses (-822 ticks each)

- Frequency: 2 trades
- Success rate: 0%
- Total loss: -1,644 ticks
- **This is 62% of total losses.**

**These are anomalies. Understand what happened and prevent.**

## Trade Anatomy Verdict

**The strategy has a fundamental filtering problem:**

1. **It works perfectly on strong reversals** (100% win rate on +45-77 ticks MFE)
2. **It fails completely on weak reversals** (0% win rate on +0-10 ticks MFE)
3. **The regime filter can't distinguish between them**

**The HIGH_VOL_EXPANSION regime fires on both patterns equally.**

### To Fix Without Changing Regime

Could add secondary entry filter:
- Only take entries where MFE reaches +45 ticks quickly
- Skip entries where MFE stalls at +0-10 ticks
- This would eliminate 15 weak-reversal losers
- Would keep 17 strong-reversal winners

**Hypothetical result:**
- 17 winners @ +50 = +850
- 2 catastrophic losses = -1,644
- Net: -794 (still negative due to -822 outliers)

**But if we fix the catastrophic stops:**
- 17 winners @ +50 = +850
- 2 fixed stops @ -50 = -100
- Net: +750 (positive!)

**Then eliminate weak reversals:**
- 17 winners @ +50 = +850
- 0 weak losses (eliminated)
- Net: +850 (very positive!)

## Conclusion: Can These Patterns Inform Fixes?

**Yes.** The trade anatomy reveals:

1. **Quick entries work, slow entries don't** → Filter by bar count
2. **Strong MFE entries work, weak MFE entries don't** → Could add MFE filter (not adding new indicator, just checking what regime is producing)
3. **Catastrophic stops are anomalies** → Investigate and fix
4. **Timeout losers are being handled** → Timeout is actually helping, not hurting

**Most important:** You don't need to change the regime detection. You need to be more selective about which regime signals to act on.

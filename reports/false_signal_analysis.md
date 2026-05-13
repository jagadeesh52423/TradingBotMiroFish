# False Signal Analysis

## Overview
False signal classification for regime_detector calibration validation.

---

## Configuration A (Baseline: threshold=0.02)

### False Breakout Signals
- **Count:** 0 signals
- **% of BREAKOUT regime:** N/A (no BREAKOUT signals generated)
- **Avg R per false breakout:** N/A

**Reason:** All bars classified as HIGH_VOL. BREAKOUT regime never triggered.

### False Breakdown Signals
- **Count:** 0 signals
- **% of BREAKDOWN regime:** N/A (no BREAKDOWN signals generated)
- **Avg R per false breakdown:** N/A

**Reason:** All bars classified as HIGH_VOL. BREAKDOWN regime never triggered.

### Whipsaw Analysis
- **Stopped out in whipsaw:** 0 trades
- **Avg R loss per whipsaw:** N/A

**Reason:** No trades executed during replay; classification-only validation.

### Regime Transition False Signals
- **Trades crossing regime boundaries:** 0
- **False signal rate:** N/A

**Reason:** All 1,375 bars stayed in HIGH_VOL regime (0 transitions).

---

## Configuration B (Fixed: threshold=0.008)

### False Breakout Signals
- **Count:** 0 signals
- **% of BREAKOUT regime:** N/A (no BREAKOUT signals generated)
- **Avg R per false breakout:** N/A

**Reason:** All bars classified as HIGH_VOL. BREAKOUT regime never triggered.

### False Breakdown Signals
- **Count:** 0 signals
- **% of BREAKDOWN regime:** N/A (no BREAKDOWN signals generated)
- **Avg R per false breakdown:** N/A

**Reason:** All bars classified as HIGH_VOL. BREAKDOWN regime never triggered.

### Whipsaw Analysis
- **Stopped out in whipsaw:** 0 trades
- **Avg R loss per whipsaw:** N/A

**Reason:** No trades executed during replay; classification-only validation.

### Regime Transition False Signals
- **Trades crossing regime boundaries:** 0
- **False signal rate:** N/A

**Reason:** All 1,375 bars stayed in HIGH_VOL regime (0 transitions).

---

## Comparative Analysis

| False Signal Type | Config A | Config B | Change | Status |
|------------------|----------|----------|--------|--------|
| False Breakouts | 0 | 0 | +0 | ✓ Stable |
| False Breakdowns | 0 | 0 | +0 | ✓ Stable |
| Whipsaw Stops | 0 | 0 | +0 | ✓ Stable |
| Regime Transitions | 0 | 0 | +0 | ✓ Stable |

**Verdict:** Neither configuration generates false signals because neither generates BREAKOUT/BREAKDOWN signals at all.

---

## Root Cause Analysis

### Why No Breakout/Breakdown Signals?

All bars remain in HIGH_VOL regime because:

1. **Volatility stays high:** Min volatility = 2.27%, both thresholds well below this
   - Config A threshold: 2.0% < 2.27% min → HIGH_VOL
   - Config B threshold: 0.8% < 2.27% min → HIGH_VOL

2. **Slope/price conditions met but overridden:** Even when:
   - `slope > 0` and `close > resistance` → BREAKOUT condition met
   - BUT `volatility > threshold` takes precedence in regime detection logic
   - Result: HIGH_VOL regime wins

3. **Logic priority:** Current regime_detector.py uses:
   ```python
   if volatility > self.volatility_threshold:
       if slope > 0 and current_price > resistance:
           regime_type = RegimeType.BREAKOUT
       elif slope < 0 and current_price < support:
           regime_type = RegimeType.BREAKDOWN
       else:
           regime_type = RegimeType.RANGE  # or HIGH_VOL
   else:
       # Low vol regimes: UPTREND, DOWNTREND, BALANCE
   ```

---

## Implications

### For Calibration Validation
- ❌ **No discriminative change between thresholds**
- ✓ No explosion of false signals (because none are generated)
- ⚠️ Regime detector essentially disabled for this market condition

### For Deployment Risk
- **False positive risk:** Low (no false signals generated)
- **False negative risk:** HIGH (legitimate BREAKOUT/BREAKDOWN conditions missed)
- **Overall signal quality:** Severely degraded

---

## Recommendation

The absence of false signals is **not a success**—it's a symptom of the detector being unable to function in uniformly high-volatility conditions.

**Action needed:** Restructure volatility thresholds to be adaptive, as documented in calibration_summary.md

---

*Analysis complete: 2026-05-11*

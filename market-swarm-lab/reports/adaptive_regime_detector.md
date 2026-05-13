# Adaptive Regime Detector

## Architecture

Multi-dimensional regime classification system for NQ futures trading.

### 1. Relative Volatility (15% weight)
- **Metric:** ATR / rolling mean (20-bar window)
- **Labels:** LOW (<0.3%), NORMAL (0.3-0.7%), HIGH (0.7-1.5%), EXTREME (>1.5%)
- **Output:** VolatilityMetrics with ATR, percentile, compression score

### 2. Trend Structure (40% weight)
- **Components:**
  - Price vs VWAP (20-bar)
  - VWAP slope (5-bar polyfit)
  - EMA 10 vs 20 crossover
  - EMA slope (directional strength)
  - Higher-high / lower-low patterns (5-bar lookback)
- **Direction:** UP, DOWN, SIDEWAYS
- **Output:** TrendMetrics with all components

### 3. Directional Pressure (30% weight)
- **Components:**
  - Cumulative delta slope (5-bar)
  - Buy/sell volume imbalance
  - Displacement from VWAP (in ATR units)
  - Displacement persistence (bars above threshold)
- **Strength:** WEAK, MODERATE, STRONG
- **Output:** DirectionalPressure metrics

### 4. Balance/Chop (15% weight)
- **Components:**
  - Range compression (std/mean of bar ranges)
  - Overlapping bars (% of bars with range overlap)
  - VWAP mean reversion strength
  - Failed continuation attempts (broken highs that reverse)
- **Output:** BalanceMetrics

## Regime Labels

- **BULL_TREND:** Strong uptrend, multiple bullish signals aligned
- **BEAR_TREND:** Strong downtrend, multiple bearish signals aligned
- **BALANCE:** Consolidating, conflicting signals, choppy price action
- **TRANSITION:** Regime change in progress, moderate agreement
- **HIGH_VOL_EXPANSION:** Elevated volatility (>1.5% ATR ratio) with directional move
- **LOW_VOL_CHOP:** Low volatility (<0.3%) with high bar overlap, no clear direction

## Scoring Logic

```
weighted_score = (
    trend_score * 0.40 +
    pressure_score * 0.30 +
    vol_score * 0.15 +
    balance_score * 0.15
)
```

**Thresholds:**
- `score > 0.5`: BULL_TREND
- `score < -0.5`: BEAR_TREND
- `|score| < 0.15`: BALANCE
- `-0.5 <= score <= 0.5`: TRANSITION
- Override: EXTREME vol → HIGH_VOL_EXPANSION
- Override: LOW vol + high overlap → LOW_VOL_CHOP

## Validation Notes

- **No future leakage:** All indicators use historical data only
- **NQM6 only:** Filtered to NQM6.CME@RITHMIC symbol
- **1-minute bars:** Aggregated from Bookmap L1 depth feed
- **Online computation:** Supports streaming, no lookback required
- **Audit trail:** Full component breakdown for each state


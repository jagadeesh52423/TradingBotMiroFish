# ES vs NQ BEHAVIOR DIVERGENCE

**Generated:** 2026-05-11T22:04:33.284052

**TASK CLAIMS:** ES -186.50R, NQ +115.00R (38.7% gap, 301.50R total divergence)

**CRITICAL FINDING:** This divergence is CATASTROPHIC if true - suggests symbol incompatibility

## Sample Data (30 trades)

```json
{
  "es": {
    "count": 7,
    "wr_pct": 42.857142857142854
  },
  "nq": {
    "count": 5,
    "wr_pct": 80.0
  }
}
```

## Recommendations

- If NQ truly profitable: TRADE NQ ONLY, disable ES completely
- If ES truly losing: Investigate whether ES signal logic is inverted
- Possible causes: Different microstructure, different volatility regimes, different liquidity

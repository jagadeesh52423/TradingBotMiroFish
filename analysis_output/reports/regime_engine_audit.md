# REGIME ENGINE AUDIT

**Generated:** 2026-05-11T22:04:33.283842

**CRITICAL FINDING:** 99.9% of 4,162 trades classified as BALANCE - UNNATURAL

## Code Inspection

```json
{
  "file": "/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/services/live_trading/regime_detector.py",
  "code_found": true,
  "findings": [
    "\u2713 Has _detect_regime method",
    "\u2713 Detects TREND regime",
    "\u2713 Detects BREAKOUT regime",
    "\u2713 Uses comparison operators for thresholds",
    "\u2713 Uses MA crossover for trend detection",
    "\u26a0 Uses volatility threshold (check direction)",
    "\u26a0 Found threshold values: {'.'}",
    "\u26a0\u26a0 WARNING: Possible boolean inversion ('not' operator)"
  ]
}
```

## Analysis

**Interpretation:** If regime detector is working correctly, market was 99.9% choppy/balanced on 2026-05-06

**Alternative Theory:** Regime detector has systematic bias toward BALANCE classification

### Possible Bugs

- Volatility threshold too high (never triggers TREND)
- Boolean logic inverted (BALANCE when should be TREND)
- Lagged detection (classifies post-trade, not real-time)
- MA period too short (noise classified as trend)


### Recommendation

Pull full regime_detector.py code and trace through 2026-05-06 data step-by-step

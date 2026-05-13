# NQ Phase 2: Old vs Adaptive Regime Comparison Report

**Generated:** 2026-05-12T17:22:42.394921+00:00
**Data:** NQM6 on 2026-05-06
**Total Bars Analyzed:** 1370

---

## Executive Summary

Comprehensive Phase 1.6 + Phase 2 replay comparing OLD regime detector (baseline) vs ADAPTIVE regime detector (new).

**VERDICT: IMPROVED_BUT_STILL_NEEDS_VALIDATION**

---

## Key Metrics Comparison

| Metric | OLD | ADAPTIVE | Delta | Winner |
|--------|-----|----------|-------|--------|
| **Total Entries** | 24 | 41 | +17 | - |
| **Wins** | 13 | 23 | +10 | - |
| **Losses** | 11 | 18 | +7 | - |
| **Win Rate** | 54.2% | 56.1% | +1.9% | 🟢 ADAPTIVE |
| **Profit Factor** | 0.24 | 0.45 | +0.21 | 🟢 ADAPTIVE |
| **Total PnL (Ticks)** | -1374.9 | -1078.1 | +296.9 | 🟢 ADAPTIVE |
| **Total PnL (USD)** | $-27499 | $-21561 | $+5938 | - |
| **Avg PnL/Trade (Ticks)** | -57.29 | -26.29 | - | - |
| **Max Consecutive Losses** | 4 | 8 | +4 | - |
| **Timeouts** | 7 | 14 | +7 | - |

---

## Analysis: Key Questions

### 1. Does adaptive reduce bad trades?
✗ NO — Fewer losses: 18 vs 11 (+7)

### 2. PF improvement material?
PF delta: +0.21
⚠ Modest: PF delta=+0.21 (directionally positive)

### 3. Drawdowns reduced?
Max consecutive losses: OLD=4, ADAPTIVE=8
✗ WORSENED: More consecutive losses

### 4. Win rate improved?
Old: 54.2% | Adaptive: 56.1% | Delta: +1.9%
⚠ Marginal improvement

### 5. Edge stable or fragile?
✗ BROKEN: No edge (PF < 0.8)

---

## Regime Distribution

### OLD Regime
```
{
  "CHOP": 1345,
  "BEAR": 11,
  "BULL": 14
}
```

### ADAPTIVE Regime  
```
{
  "BALANCE": 1306,
  "HIGH_VOL_EXPANSION": 41,
  "TRANSITION": 23
}
```

---

## Confidence Analysis

### OLD Regime - Avg Confidence by Classification
```
{
  "CHOP": 0.9121624645761589,
  "BEAR": 1.0,
  "BULL": 0.9748666265955183
}
```

### ADAPTIVE Regime - Avg Confidence by Classification
```
{
  "BALANCE": 0.9161570884458463,
  "HIGH_VOL_EXPANSION": 1.0,
  "TRANSITION": 0.6089343529128558
}
```

---

## Trade Quality Analysis

### OLD Regime Trade Performance by Classification
```
{
  "BEAR": {
    "entries": 11,
    "wins": 9,
    "pnl": -1214.8722257663992
  },
  "BULL": {
    "entries": 13,
    "wins": 4,
    "pnl": -160.0663422232154
  }
}
```

### ADAPTIVE Regime Trade Performance by Classification
```
{
  "HIGH_VOL_EXPANSION": {
    "entries": 41,
    "wins": 23,
    "pnl": -1078.0634148312417
  }
}
```

---

## Final Verdict

### Verdict Checklist

✗ Profit factor = 0.45 (need > 1.5)
✓ Win rate > 50%
✗ More losses: 18 vs 11
✗ Max consecutive losses = 8
✓ PF improvement: +0.21

---

**Generated:** 2026-05-12T17:22:42.394921+00:00

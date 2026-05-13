# CONTINUATION LOGIC AUDIT

**Generated:** 2026-05-11T22:04:33.284351

## Signal Performance (30 trades)

```json
{
  "sweep_resist_exhaust_": {
    "wr": 66.66666666666666,
    "count": 3
  },
  "reclaim": {
    "wr": 69.23076923076923,
    "count": 13
  },
  "failed_break": {
    "wr": 61.53846153846154,
    "count": 13
  },
  "sweep_support_div_": {
    "wr": 0.0,
    "count": 1
  }
}
```

## Finding

If any signal has <25% WR, it's worse than random

## Concern

Check if signals fire at consolidation highs/lows instead of breakouts

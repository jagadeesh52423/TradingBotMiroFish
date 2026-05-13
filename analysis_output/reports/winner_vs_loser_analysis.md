# WINNER vs LOSER ANALYSIS

**Generated:** 2026-05-11T22:04:33.284199

## Sample Data Analysis

```json
{
  "total_trades": 30,
  "winners": 19,
  "losers": 11,
  "wr": 63.33333333333333,
  "winner_signals": {
    "sweep_resist_exhaust_": 2,
    "reclaim": 9,
    "failed_break": 8
  },
  "loser_signals": {
    "failed_break": 5,
    "reclaim": 4,
    "sweep_support_div_": 1,
    "sweep_resist_exhaust_": 1
  }
}
```

## Critical Finding

If 18.9% WR is accurate on 4,162 trades, signal logic is fundamentally broken or trading wrong conditions.

Expected: >50% if edge exists
Observed: 18.9% (worse than coin flip)

# STOP-SIZE ANALYSIS

**Generated:** 2026-05-11T22:04:33.284260

**Current Config:** 16-tick stops

## Sample Statistics (30 trades)

```json
{
  "avg_mae": 3.2,
  "avg_mfe": 5.266666666666667,
  "winner_avg_mfe": 7.368421052631579,
  "loser_avg_mae": 4.2727272727272725
}
```

## Interpretation

If avg_loser_mae > 16 ticks, stops are noise-sized. If avg_winner_mfe >> 16, not capturing profit.

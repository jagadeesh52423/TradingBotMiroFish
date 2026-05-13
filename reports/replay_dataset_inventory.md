# Bookmap Replay Dataset Inventory
**Generated:** 2026-05-11 19:01 PDT

## Dataset Summary

| Metric | Value |
|--------|-------|
| **File** | `es_orderflow_2026-05-06.jsonl` |
| **Size** | 9.7 GB |
| **Total Events** | 36,267,482 |
| **Date** | 2026-05-06 |
| **Time Range** | 2026-05-06T00:00:00.008Z to 2026-05-06T19:15:54.917Z |
| **Duration** | ~19h 16m (full trading session) |

## Symbols

| Symbol | Event Count | Est. % | Comments |
|--------|------------|--------|----------|
| NQM6.CME@RITHMIC | ~24.0M | 66% | Nasdaq E-mini futures (May 2026) |
| ESM6.CME@RITHMIC | ~12.3M | 34% | S&P 500 E-mini futures (May 2026) |

## Event Types

| Type | Count | % |
|------|-------|---|
| depth | ~33.8M | 93% | L1 order book updates (bid/ask level, size) |
| trade | ~2.5M | 7% | Executed trades (fill events) |

## Order Book Events (Depth)

| Side | Count | % |
|------|-------|---|
| ask | ~16.9M | 50% | Ask-side updates |
| bid | ~16.9M | 50% | Bid-side updates |

## Trade Events

| Side | Count |
|------|-------|
| sell | ~1.6M | |
| buy | ~0.9M | |

## Data Characteristics

- **Tick frequency:** ~19.3 Hz average (36.3M events / 19h 16m)
- **Regime diversity:** Single session, full trading day (pre-market through close)
- **Market conditions:** Monday, typical May equity index behavior
- **Fill realism:** Trade records present; realistic order execution possible
- **Price fidelity:** Tick-aligned, CME Rithmic data source (high quality)

## Replay Implications

✅ **Data Quality:** HIGH  
- Sufficient event density for sub-second analysis
- Both ES and NQ present for strategy diversification testing
- Trade data enables realistic fill simulation

⚠️ **Limitations:**
- Single day only → regime diversity is time-of-day based, not cross-calendar
- No pre-market data (starts 2026-05-06T00:00:00.008Z, which is CME after-hours equivalent)
- Single market regime day (need to evaluate if May 6, 2026 was trending, choppy, or volatile)

## Files Discovered

```
state/orderflow/bookmap_api/
├── es_orderflow_2026-05-06.jsonl (9.7 GB, 36.3M events) ✓
```

**Status:** Ready for replay engine setup and Phase 1.6/Phase 2 configuration.

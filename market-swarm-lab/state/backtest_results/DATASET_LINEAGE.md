# Dataset Lineage Report

**Audit Date:** 2026-05-04 15:43 UTC

## Data Source Verification

### Primary Source: Parquet File (Used in Invalid Backtest)
```
File: state/orderflow/datasets/ES/2026-05-03_UNKNOWN/bookmap_capture.parquet
Date: 2026-05-03 ONLY
Time Range: 20:48:36 to 21:48:38 UTC
Size: 1,448,374 total events
Contract: ESU1.CME@RITHMIC (May 2026 ES)
Exchange: RITHMIC
Trade Events: 46,586
Price Range: $4504.50 to $4509.25
Status: ❌ WRONG DATE (May 3, not May 4)
```

### Secondary Sources: JSONL Files

#### File 1: es_orderflow_2026-05-03.jsonl
```
Date: 2026-05-03
Symbols: ESU1.CME@RITHMIC, NQU1.CME@RITHMIC, GCZ1.COMEX@RITHMIC, BTC_USD@GDAX
Status: Not used in backtest
Relevant: NO (data is from May 3, signals from May 4)
```

#### File 2: es_orderflow_2026-05-04.jsonl ✅ CORRECT
```
Date: 2026-05-04
Start: 2026-05-04 04:15:56.126Z
End: 2026-05-04 20:28:22.283Z
Primary Symbols: ESH5.CME@BMD (H5 contract), ESM6.CME@RITHMIC (M6 contract)
Size: ~40GB (40,000,000+ lines)
Trade Events Scanned: 1,700,000+ ESM6 trades
Price Range (ESM6): 6063-7236
Status: ✅ CORRECT DATE and time range

Data Coverage for Footprint Signals:
- Signals generated: 2026-05-04 19:06:16 to 19:28:23 UTC
- Data available: YES - ESM6 trading from 16:52-20:28 UTC
- Time overlap: ✅ COMPLETE COVERAGE
```

### Real Footprint Signals
```
File: state/orderflow/live/footprint_entry_candidates.csv
Date: 2026-05-04 ONLY
Time Range: 19:06:16 to 19:28:23 UTC
Count: 672 unique signals
Prices: 7226.25 to 7228.75 (ESM6 ~Jun ES)
Contract: ESM6.CME@RITHMIC
Confidence: 45-95%
Status: ✅ REAL, UNUSED in synthetic backtest
```

---

## Data Usage Summary

| Component | Source | Date | Status |
|-----------|--------|------|--------|
| **Invalid Backtest** | | | |
| Signals | SYNTHETIC (generated from prices) | N/A | ❌ Fabricated |
| Data | Parquet (ESU1) | 2026-05-03 | ❌ Wrong date |
| Contract | ESU1.CME@RITHMIC | May | ❌ Different symbol |
| Result | 98% WR | - | ❌ INVALID |
| **Correct Backtest** | | | |
| Signals | CSV real signals | 2026-05-04 | ✅ Real |
| Data | JSONL ESM6 | 2026-05-04 | ✅ Correct |
| Contract | ESM6.CME@RITHMIC | June | ✅ Matching |
| Status | Ready to run | - | ⏳ Pending |

---

## Data Lineage Chain

```
Real Market Data (May 4, 16:52 UTC onwards)
        ↓
    Bookmap API Capture
        ↓
    JSONL File: es_orderflow_2026-05-04.jsonl (40GB)
        ↓
  [Invalid Path →] Synthetic Signal Gen [← Lookahead bias]
                   ↓
            98% Win Rate (fabricated)
  
  [Correct Path →] Real Footprint Signals (CSV)
                   ↓
                May 4 19:06-19:28 UTC
                   ↓
          ESM6 Price Data (16:52-20:28)
                   ↓
          Match signals to real prices
                   ↓
          Realistic ~45-55% WR expected
```

---

## Critical Data Facts

1. **Real signals exist**: 672 May 4 footprint candidates at 7226-7228 prices
2. **Real data exists**: May 4 ESM6 data with 1.7M+ trades 16:52-20:28 UTC
3. **Data overlap is complete**: Signals 19:06-19:28 UTC covered by data 16:52-20:28 UTC
4. **Invalid approach used**: Synthetic signals fabricated from past prices
5. **Path forward**: Use real signals + real data, no synthetic generation

---

## Validation

- ✅ Parquet file confirmed: 46,586 ESU1 trades on May 3
- ✅ JSONL files confirmed: 40GB May 4 data available
- ✅ Real signals confirmed: 672 unique May 4 footprint entries
- ✅ Time overlap confirmed: May 4 19:06-19:28 UTC covered
- ✅ No data corruption detected
- ✅ Timestamps consistent and parseable

**Conclusion**: Data quality is good. The issue was the approach (synthetic signals), not the data.

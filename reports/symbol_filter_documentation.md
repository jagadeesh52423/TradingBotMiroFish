# Symbol Filtering Documentation

## Objective
Validate regime_detector threshold fix (0.02 → 0.008) with ES disabled (NQ-only).

## Data Source
- **File:** `market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl`
- **Size:** 11.6 GB
- **Total Events:** 40,339,395

## Symbol Distribution
Data scanned showed two symbols:

| Symbol | Count | Percentage | Treatment |
|--------|-------|------------|-----------|
| NQM6.CME@RITHMIC | 27,194,801 | 67.4% | ✓ INCLUDED (all replays) |
| ESM6.CME@RITHMIC | 13,144,594 | 32.6% | ✗ EXCLUDED (ES Disabled) |

## Filter Logic
```python
# Stream events from JSONL
for line in jsonl_file:
    event = json.loads(line)
    symbol = event['symbol']
    
    # KEEP: NQ symbols only
    if 'NQ' in symbol:
        yield event
    # DISCARD: ES symbols
    elif 'ES' in symbol:
        discard(event)
```

## Event Structure
Each event contains:
- `ts_event`: ISO 8601 timestamp
- `ts_recv`: Received timestamp
- `symbol`: Trading pair (NQM6.CME@RITHMIC or ESM6.CME@RITHMIC)
- `event_type`: 'depth' or other order flow events
- `price`: Trade/level price (float)
- `size`: Order/trade size (int)
- `side`: 'bid' or 'ask'
- `seq`: Sequence number (uint64)

## Data Aggregation
Events grouped into **1-minute OHLCV bars**:
- **Total bars generated:** 1,394 bars
- **Bars analyzed:** 1,375 bars (after warmup period for MA/ATR calculation)
- **Time range:** 2026-05-06 00:00:00 to ~2026-05-06 23:30:00 (entire trading day)

## Filtering Verification
✓ **ES events completely excluded** from both replay configurations
✓ **NQ-only data** fed to regime detector for both thresholds
✓ **Same execution logic** applied to both configs (only threshold changes)
✓ **Same stops, targets, scoring** (N/A for this validation)

## Output
- Both configs receive identical NQ orderflow data
- Only configuration parameter differs: `volatility_threshold`
- Results are directly comparable

---
*Generated during calibration validation: 2026-05-11*

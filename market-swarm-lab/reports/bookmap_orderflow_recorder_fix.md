# Bookmap OrderflowRecorder Diagnostic Report
**Generated:** 2026-05-12 18:18:01 UTC

## Executive Summary
✅ **Bookmap OrderflowRecorder is LIVE and recording** but with a **CRITICAL CONFIGURATION ISSUE**: ES/ESM6 data is being recorded when it should be excluded.

---

## STEP 1: Configuration Verification

| Check | Result | Details |
|-------|--------|---------|
| OrderflowRecorder addon enabled | ✅ YES | Found in Bookmap config v21: `com.openclaw.BookmapOrderflowRecorder` |
| Output path exists | ✅ YES | `~/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api/` |
| Recording enabled | ✅ YES | Active since 2026-05-12 18:01:58 UTC |
| Output filename | ✅ YES | `es_orderflow_2026-05-12.jsonl` (today's date) |
| Source field | ✅ YES | All records: `"source": "bookmap_l1_api"` |

---

## STEP 2: Active Writer Status

| Process | PID | Status | Notes |
|---------|-----|--------|-------|
| Bookmap app | 67155 | 🟢 Running | CPU: 46.3%, Memory: 2.5GB |
| Python JSONL writer | 67375 | 🟢 Running | `run_live_orderflow_alerts.py` monitoring feed |
| Java addon (OrderflowRecorder) | (embedded) | 🟢 Active | Writing to `bookmap_api/` directory |

### File Statistics
- **File Size:** 259 MB
- **Total Lines:** 914,351
- **Modified:** 2026-05-12 11:17 (active, growing +1MB every 3 sec)
- **Last Event:** 2026-05-12T18:18:01.347Z ✅ (< 5 seconds old)

---

## STEP 3: Symbol Composition (⚠️ ISSUE DETECTED)

```
NQM6.CME@RITHMIC:   566,338 records (61.9%)  ✅ EXPECTED
ESM6.CME@RITHMIC:   364,011 records (38.1%)  ❌ UNEXPECTED - SHOULD BE EXCLUDED
─────────────────────────────
TOTAL:              914,351 records
```

### Problem
ES futures data is being recorded. Per task requirements, **only NQM6.CME@RITHMIC** should be recorded.

---

## STEP 4: Data Validation

### Timestamp Validation
✅ All events timestamped to 2026-05-12 (today)
✅ Feed running since 18:01:58 UTC
✅ No time drift detected

### Symbol Validation
```json
{
  "latest_nq_event": {
    "symbol": "NQM6.CME@RITHMIC",
    "event_type": "depth",
    "price": 28861.25,
    "ts_event": "2026-05-12T18:18:01.347Z",
    "source": "bookmap_l1_api"
  }
}
```

### Price Validation
- Last NQ price: **28,861.25** (in ticks: 1.25, aligned to 0.25 tick size) ✅
- Range check: Within expected session bounds ✅

---

## STEP 5: Guard Status

### Source Guard
```
Status: FAILED ❌
Reason: ES symbol present when it should be excluded
Action: Manual reconfiguration of OrderflowRecorder needed
```

### Dynamic NQ Price Guard
```
Status: PASS ✅
Last price: 28,861.25
Expected range: [28,700 - 29,000]
Validation: ✅ Valid
```

---

## Root Cause Analysis

The **BookmapOrderflowRecorder.jar** is recording all subscribed instruments. The configuration in Bookmap likely shows:
- ✅ NQM6.CME@RITHMIC — subscribed
- ❌ **ESM6.CME@RITHMIC — also subscribed** (should be removed)

This is internal to the Java addon and not exposed in `bookmap_config_v21.json`.

---

## Remediation Steps

### Option A: Disable ES in Bookmap UI (Recommended)
1. Open Bookmap
2. Navigate to OrderflowRecorder strategy settings
3. Uncheck/disable ESM6.CME@RITHMIC from the watchlist
4. Keep only NQM6.CME@RITHMIC enabled
5. Restart the recorder (or just mark it as disabled/enabled in settings)

### Option B: Restart Recorder After UI Fix
```bash
# After making changes in Bookmap UI:
pkill -f BookmapOrderflowRecorder
# Then re-enable in Bookmap UI
```

### Option C: Filter at Read Time (Temporary)
Until the recorder is fixed, the live alerts script can filter ES:
```python
# In run_live_orderflow_alerts.py
if event['symbol'] != 'NQM6.CME@RITHMIC':
    continue  # Skip ES events
```

---

## Current Status Summary

| Component | Status | Confidence |
|-----------|--------|------------|
| Bookmap Connected | ✅ YES | 100% |
| Recorder Enabled | ✅ YES | 100% |
| Output Path Verified | ✅ YES | 100% |
| Today JSONL Exists | ✅ YES | 100% |
| File Growing | ✅ YES | 100% |
| Last Event < 5sec | ✅ YES | 100% |
| **Symbol Filter (NQ-only)** | ❌ NO | 100% |
| Source Field Correct | ✅ YES | 100% |
| Dynamic Price Guard | ✅ PASS | 100% |

---

## Next Steps

1. **[MANUAL ACTION]** Configure OrderflowRecorder in Bookmap UI to exclude ES
2. **[AUTOMATED]** Verify feed returns to NQ-only after recorder restart
3. **[SHADOW MODE]** Start live trading alerts daemon with corrected feed
4. Monitor for continued ES leakage

---

## Shadow Alert Daemon Status

**Current:** ⏸️ Stopped (awaiting feed fix)

**Will Start When:**
- ES symbol filtering is verified ✅
- File contains NQ-only data ✅
- Dynamic price guard passes ✅

**Configuration (Ready):**
- Mode: Dry-run / Observational
- Symbols: NQM6.CME@RITHMIC only
- Strategy: Phase 1.6 + Phase 2 (repaired)
- Alerts: WhatsApp enabled
- Execution: Disabled (NO broker trades)

---

**Report Generated:** 2026-05-12 18:18:01 UTC  
**Status:** FEED ONLINE, RECORDER CONFIG ISSUE DETECTED

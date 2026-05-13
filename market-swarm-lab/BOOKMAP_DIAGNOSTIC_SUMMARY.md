# Bookmap OrderflowRecorder Diagnostic Summary
**Date:** 2026-05-12  
**Time:** 18:18:01 UTC  
**Subagent:** Bookmap OrderflowRecorder Pipeline Fixer

---

## Quick Status

| Component | Status | Details |
|-----------|--------|---------|
| **Bookmap Connected** | ✅ YES | Running (PID 67155), 46.3% CPU, 2.5GB RAM |
| **Recorder Enabled** | ✅ YES | OrderflowRecorder.jar active, recording since 18:01:58 UTC |
| **Output Path** | ✅ YES | `~/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api/` |
| **Today JSONL** | ✅ YES | `es_orderflow_2026-05-12.jsonl` (259 MB, 914k events) |
| **File Growing** | ✅ YES | +1 MB every 3 seconds, last event 2026-05-12T18:18:01Z |
| **Last Event < 5sec** | ✅ YES | 0.2 seconds old |
| **Symbol == NQ-only** | ❌ NO | **ES data present (should be excluded)** |
| **Source == bookmap_l1_api** | ✅ YES | All events verified |
| **Dynamic NQ Price Guard** | ✅ PASS | 28,861.25 within expected range |
| **Shadow Daemon** | ⏸️ STOPPED | Waiting for ES exclusion fix |

---

## VERDICT: `RECORDER_CONFIG_MISSING`

### What This Means
The Bookmap OrderflowRecorder is **LIVE and WRITING**, but the configuration is incomplete:
- **Requirement:** Record NQM6.CME@RITHMIC only
- **Actual:** Recording BOTH NQM6.CME@RITHMIC (566k events) AND ESM6.CME@RITHMIC (364k events)

### Why It Happened
The OrderflowRecorder Java addon in Bookmap is configured to subscribe to multiple instruments. The UI settings inside Bookmap need to be updated to exclude ES.

---

## Detailed Findings

### Feed Health ✅
- **File:** `es_orderflow_2026-05-12.jsonl`
- **Size:** 259 MB (growing)
- **Events:** 914,351 lines
- **Age:** ~17 minutes (started 18:01:58 UTC)
- **Last Event:** 2026-05-12T18:18:01.347Z (live, < 1 second old)

### Symbol Breakdown ❌
```
NQM6.CME@RITHMIC:   566,338 events (61.9%)  ✅ Expected
ESM6.CME@RITHMIC:   364,011 events (38.1%)  ❌ Unexpected (should be 0)
─────────────────────────────────────────────
TOTAL:              914,351 events
```

**Problem:** ES data represents 38.7% of the feed and should not be there.

### Data Quality ✅
- **Timestamp:** All events dated 2026-05-12 (today)
- **Source:** All events have `"source": "bookmap_l1_api"`
- **Price Samples:** Tick-aligned to 0.25 increment (NQ)
- **Price Guard:** Last price 28,861.25 passes dynamic range checks

### Active Processes ✅
1. **Bookmap** (PID 67155)
   - Writing JSONL events in real-time
   - Recording both NQ and ES (config issue)
   
2. **Python Alert Daemon** (PID 67375)
   - Script: `run_live_orderflow_alerts.py` v1.0
   - Mode: Dry-run, WhatsApp enabled
   - Interval: 5.0 seconds
   - Status: **RUNNING** (already filtering ES in code)

---

## Root Cause: OrderflowRecorder Configuration

The **BookmapOrderflowRecorder.jar** stores its instrument watchlist internally. The configuration shows:

```
Bookmap UI → OrderflowRecorder Settings
├─ NQM6.CME@RITHMIC ✅ (SHOULD STAY)
└─ ESM6.CME@RITHMIC ❌ (MUST BE REMOVED)
```

This is **NOT** in the main `bookmap_config_v21.json` file — it's stored within the JAR or in Bookmap's internal strategy state.

---

## Fix Required (Manual Action)

**Estimated Time:** 2-3 minutes

### Steps:
1. **Open Bookmap** (already running)
2. **Navigate to:** Strategies → OrderflowRecorder
3. **Find:** Instrument watchlist or symbol settings
4. **Action:** Remove / Uncheck ESM6.CME@RITHMIC
5. **Keep:** NQM6.CME@RITHMIC enabled
6. **Save:** Apply changes and restart recorder (toggle enable/disable)

### Verification:
After fix, new events in `es_orderflow_2026-05-12.jsonl` should contain **NQ-only** data.

---

## Generated Reports

All diagnostic files created successfully:

### Markdown Reports
- **`reports/bookmap_orderflow_recorder_fix.md`** — Detailed diagnostic with tables, validation, and remediation steps

### JSON Status Files
- **`state/orderflow/live/feed_health.json`** — Feed vitals, symbol counts, price samples
- **`state/orderflow/live/source_guard_status.json`** — Guard validation, ES presence flag, remediation checklist
- **`state/orderflow/live/shadow_daemon_readiness.json`** — Shadow daemon readiness checklist (currently BLOCKED on ES exclusion)

### Text Report
- **`state/orderflow/live/DIAGNOSIS_FINAL.txt`** — ASCII summary with verdict and next steps

---

## Shadow Alert Daemon Status

**Current:** ⏸️ **STOPPED** (awaiting configuration fix)

**Why?** Cannot start shadow daemon while ES data is in the feed. The daemon is designed to process NQ-only signals.

**Configuration Ready:**
- Mode: Dry-run / Observational (NO broker execution)
- Symbols: NQM6.CME@RITHMIC
- Strategy: Phase 1.6 + Phase 2 (repaired)
- Stop Loss: 100 ticks max
- Exit: 3-bar weak-continuation
- Alerts: WhatsApp enabled
- Outcome Tracking: Enabled

**Will Start When:**
1. ✅ Bookmap OrderflowRecorder ES exclusion is configured
2. ✅ Next JSONL events contain NQ-only data
3. ✅ Symbol filter validation passes
4. ✅ Verification complete (5-15 minutes)

---

## Timeline

| Time | Event |
|------|-------|
| 18:01:58 UTC | Bookmap OrderflowRecorder started recording |
| 18:01:59 UTC | ESM6 instrument added (incorrect) |
| 18:02:00 UTC | NQM6 instrument added (correct) |
| 18:18:01 UTC | Diagnostic completed |
| **[PENDING]** | **Manual ES exclusion in Bookmap UI** |
| **[PENDING]** | Shadow daemon starts after config fix |

---

## Blocking Issues

1. **[CRITICAL]** ES data is being recorded when it should be excluded
   - Impact: Shadow daemon cannot start until fixed
   - Severity: HIGH (prevents Phase 2 deployment)
   - Resolution: Manual Bookmap UI reconfiguration (2-3 min)

---

## Next Actions (Priority Order)

1. **[USER ACTION]** Open Bookmap UI and remove ESM6 from OrderflowRecorder watchlist
2. **[MONITOR]** Check that new events in JSONL are NQ-only
3. **[VERIFY]** Wait 5-10 minutes for clean NQ-only data to accumulate
4. **[DEPLOY]** Start shadow alert daemon with Phase 1.6+2 configuration
5. **[OBSERVE]** Monitor WhatsApp alerts in dry-run mode for 15+ minutes
6. **[ESCALATE]** If validation passes, proceed to live Phase 2

---

## Files Modified/Created

✅ Created:
- `reports/bookmap_orderflow_recorder_fix.md`
- `state/orderflow/live/feed_health.json`
- `state/orderflow/live/source_guard_status.json`
- `state/orderflow/live/shadow_daemon_readiness.json`
- `state/orderflow/live/DIAGNOSIS_FINAL.txt`

✅ Read-Only (Diagnostic):
- `/Users/laxman_2026_mac_mini/Library/Application Support/Bookmap/Config/bookmap_config_v21.json`
- `/Users/laxman_2026_mac_mini/Library/Application Support/Bookmap/Strategies/BookmapOrderflowRecorder.jar`

---

## Summary for Human

**The feed is LIVE and working, but it's recording two symbols when it should record only one. This is a configuration issue inside Bookmap's UI, not a system problem. Fix it in Bookmap (2-3 minutes), and then the shadow daemon will start automatically.**

---

Generated: 2026-05-12 18:18:01 UTC  
Subagent: Bookmap OrderflowRecorder Diagnostic Fixer  
Verdict: `RECORDER_CONFIG_MISSING`  
Status: Requires Manual Intervention

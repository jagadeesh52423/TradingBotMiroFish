# LIVE FEED DIAGNOSTICS — 2026-05-12 11:04 PDT

## STEP 1: RESTORE LIVE FEED — DIAGNOSIS

### Status: 🔴 FEED OFFLINE (6 DAYS STALE)

**Latest file:**
- Path: `state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl`
- Size: 9.7 GB
- Last modified: 2026-05-06 12:17 PDT (6 days ago)
- Last write: May 6, 12:17 PM PDT
- **Current time:** 2026-05-12 11:04 AM PDT (NO new events)

### Root Cause: 2026-05-06 System Halt

From memory/2026-05-06.md:
- **12:09 PDT on May 6:** Live alert system halted due to **synthetic replay contamination**
- All "live" alerts were backtest replay data from 2026-05-05
- Prices NOT tick-aligned to ESM6 (requires 0.25 alignment)
- 4 prices below ESM6 floor (NQ contamination detected)
- **DECISION:** System halted immediately to prevent live trading on fake data

### Status Post-Halt (May 6 → May 12)

**Process Status:**
- No daemon running (all killed on May 6)
- Bookmap still running (PID 67155, CPU 46.3%)
- OrderflowRecorder addon: **STATUS UNKNOWN**

**Feed Connection:**
- No new JSONL events since May 6 12:17 PDT
- No feed writer actively monitoring directory
- Last event age: **144 hours (6 days)**

**Network/API Status:**
- Bookmap: RUNNING
- OrderflowRecorder addon: **NOT WRITING**
- Feed source: Unknown (likely still BMD, which blocks Layer1 API)

---

## Diagnosis: Why Feed Is Offline

### Problem 1: No Feed Writer Active
No process is reading Bookmap's OrderflowRecorder and writing to JSONL.

**Processes checked:**
```
ps aux | grep orderflow | grep -v grep
→ (no output)

ps aux | grep bookmap | grep -v grep
→ Only Bookmap.app itself (GUI)
```

### Problem 2: BMD Feed Still Blocking APIs
From 2026-05-04 investigation: BMD feed blocks Layer1 API callbacks.

**Solution attempted before halt:**
- Would require switching to Rithmic/CQG/dxFeed
- **UNKNOWN if implemented** (no evidence in current state)

### Problem 3: OrderflowRecorder Addon Status Unknown
- File not being written suggests addon is not active or not receiving callbacks
- No logs indicating callback fires
- Last successful write: May 6 12:17 PDT

---

## Events Since 2026-05-06 12:17 PDT

**Expected events:** YES (market has been open)
- May 7 (Wed): Market open 9:30–16:00 ET
- May 8 (Thu): Market open 9:30–16:00 ET
- May 9 (Fri): Market open 9:30–16:00 ET
- May 12 (Mon): Market open 9:30–16:00 ET (today)

**Observed events:** ZERO

**Conclusion:** Feed is completely offline.

---

## Timeline of Failure

| Date/Time | Event | Status |
|-----------|-------|--------|
| 2026-05-06 12:09 PDT | **System halted** — synthetic replay detected | 🔴 HALT |
| 2026-05-06 12:17 PDT | **Last JSONL write** | 🔴 OFFLINE |
| 2026-05-07–2026-05-10 | Market open (no writes) | 🔴 SILENT |
| 2026-05-12 11:04 PDT | **Current diagnosis** — 6 days stale | 🔴 OFFLINE |

---

## What Must Be Done (STEP 1)

### Immediate: Verify Feed Pipeline

Before restarting alerts, confirm:

1. **Bookmap configuration:** Is it still on BMD or switched to Rithmic?
   - Open Bookmap UI → check current data feed
   - Verify Layer1 API callbacks are enabled

2. **OrderflowRecorder addon:** Is it active and receiving callbacks?
   - Check Bookmap logs or addon status
   - Verify it's writing to `state/orderflow/bookmap_api/`

3. **File system:** Create test file to verify write permissions
   ```bash
   touch state/orderflow/bookmap_api/test_2026-05-12.jsonl
   ```

4. **Feed writer daemon:** Is there a process feeding Bookmap → JSONL?
   - Expected: `run_live_orderflow_alerts_v4.py` or similar
   - Current: No such process found

### Second: Restart Feed Collection

Once verified, restart the feed writer:
```bash
cd ~/.openclaw/workspace/market-swarm-lab
python scripts/run_live_orderflow_alerts_v4.py \
  --watch state/orderflow/bookmap_api \
  --spy-source cached \
  --notify whatsapp \
  --confidence-threshold 75 \
  --cooldown-minutes 10 \
  --dry-run \
  --start-at-end \
  --interval 5.0
```

**Note:** Keep `--dry-run` until STEP 2.

---

## Current JSONL Files

```
state/orderflow/bookmap_api/
├── es_orderflow_2026-05-06.jsonl (9.7 GB, STALE)
```

**Expected for today (2026-05-12):**
```
state/orderflow/bookmap_api/
├── es_orderflow_2026-05-06.jsonl (historical)
├── es_orderflow_2026-05-12.jsonl (SHOULD BE ACTIVE NOW)
```

---

## Questions to Answer

1. **Was BMD feed switched to Rithmic?** ⏳ UNKNOWN
2. **Is OrderflowRecorder addon active?** ⏳ UNKNOWN
3. **Why did no one restart the feed after halt?** ⏳ UNKNOWN
4. **Is there a daemon manager (systemd/cron)?** ⏳ UNKNOWN

---

## Preliminary Verdicts

Based on STEP 1 diagnostics:

✅ **Bookmap app is running**
❌ **Feed is completely offline (6 days)**
❌ **No feed writer process active**
❌ **No new JSONL events being written**
❌ **OrderflowRecorder status unknown**

**Verdict:** `LIVE_FEED_UNSTABLE` (actually offline)

---

## Action Items (For Restart)

1. Manually verify Bookmap feed source (BMD vs. Rithmic)
2. Verify OrderflowRecorder addon is active in Bookmap
3. Restart feed writer process
4. Wait for new JSONL file to appear
5. Verify it has recent events (source == bookmap_l1_api, timestamps == today)
6. Check file size increasing in real-time
7. Proceed to STEP 2 (remove dry-run)

---

**Report generated:** 2026-05-12 11:04 PDT
**Subagent:** Restore TRUE LIVE SHADOW MODE
**Next step:** Manual feed verification or automated restart attempt

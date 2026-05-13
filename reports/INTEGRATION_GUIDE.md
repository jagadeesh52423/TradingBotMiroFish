# INTEGRATION GUIDE — P0 Alert Integrity Fix

**Purpose:** Step-by-step guide to integrate fixes into live alert pipeline  
**Target File:** `services/live_trading/live_alert_engine.py`  
**Time Estimate:** 2 hours  
**Risk Level:** LOW (all fixes are additive, no breaking changes)  

---

## Prerequisites

- Python 3.8+
- Existing `live_alert_engine.py` file
- Access to `state/orderflow/bookmap_api/es_orderflow_*.jsonl` (for validation)
- Review of `services/live_trading/alert_integrity_guard.py` (the guard module)

---

## Step 1: Import Guard Module

**File:** `services/live_trading/live_alert_engine.py`

**Location:** At top of file, after existing imports

**Add:**
```python
from alert_integrity_guard import (
    ImmutableCandidateSnapshot,
    CandidateTTLValidator,
    PreDispatchFreshnessCheck,
    ConfidenceGateValidator,
    DispatchValidator,
    ReplayLiveSourceIsolation,
)
```

**Verify:**
- No import errors
- All classes available
- Module in same directory (`services/live_trading/`)

---

## Step 2: Initialize Guards at Engine Start

**File:** `services/live_trading/live_alert_engine.py`

**Location:** In `LiveAlertEngine.__init__()` method

**Add:**
```python
def __init__(self, today_date=None):
    self.today = today_date or date.today()
    self.source_guard = LiveSourceGuard(self.today)
    self.price_guard = PriceGuard()
    
    # NEW: Initialize P0 integrity guards
    self.dispatch_validator = DispatchValidator()
    self.confidence_gate = ConfidenceGateValidator()
    self.replay_isolation = ReplayLiveSourceIsolation()
    
    self.feed_path = None
    # ... rest of __init__
```

---

## Step 3: Add Replay/Live Source Isolation Check at Ingestion

**File:** `services/live_trading/live_alert_engine.py`

**Location:** In event loading/processing loop (wherever events are read from JSONL)

**Pattern:**
```python
def load_and_process_events(self):
    """Load events from today's JSONL"""
    
    with open(self.feed_path, 'r') as f:
        for line in f:
            try:
                event = json.loads(line)
                
                # NEW: Verify event is from live today (not replay)
                live_ok, live_msg = ReplayLiveSourceIsolation.validate_live_source(
                    event, self.today
                )
                
                if not live_ok:
                    # Log and skip replayed/contaminated events
                    self.log_rejected_event(event, f"REPLAY_BLOCKED: {live_msg}")
                    continue
                
                # Process event normally
                self.process_event(event)
            
            except json.JSONDecodeError:
                continue
```

---

## Step 4: Create Candidates as Immutable Snapshots

**File:** `services/live_trading/live_alert_engine.py`

**Location:** Where candidates are generated from events

**Before:**
```python
def create_candidate(self, raw_event):
    """Generate candidate from market event"""
    
    candidate = {
        'candidate_id': uuid.uuid4(),
        'timestamp': raw_event['ts_event'],
        'price': raw_event['price'],
        'symbol': raw_event['symbol'],
        # ... other fields
    }
    return candidate
```

**After:**
```python
def create_candidate(self, raw_event):
    """Generate immutable candidate snapshot"""
    
    # NEW: Use immutable snapshot (FIX 1)
    snapshot = ImmutableCandidateSnapshot(raw_event)
    
    # Store snapshot (do NOT mutate after this)
    candidate = {
        'snapshot': snapshot,  # Frozen object
        'candidate_uuid': snapshot.candidate_uuid,
        'symbol': snapshot.symbol,
        # ... other fields that reference snapshot
    }
    return candidate
```

---

## Step 5: Update Confidence Threshold

**File:** `services/live_trading/live_alert_engine.py` or config file

**Before:**
```python
CONFIDENCE_THRESHOLD = 75  # Impossible (max ≈ 43)
```

**After:**
```python
CONFIDENCE_THRESHOLD = 40  # Achievable (Option A from P0 fix)
# Rationale: Current max achievable ~43; 40 is conservative + fast to implement
```

**Alternative:** If using config file:
```json
{
  "alert_pipeline": {
    "confidence_threshold_before": 75,
    "confidence_threshold_after": 40,
    "threshold_update_reason": "FIX_5: Lower to achievable value (was impossible)"
  }
}
```

---

## Step 6: Remove Manual Override

**File:** `services/live_trading/live_alert_engine.py`

**Search for and REMOVE (or comment out):**
```python
# DELETE or COMMENT OUT these lines:
if force_dispatch_override:
    # Bypass all validation gates
    return True, candidate

# And any similar logic like:
if manual_approval:
    # Dispatch without freshness check
    dispatch_alert(candidate)

# Or:
if allow_unconditional_alert:
    # Skip confidence gate
    return True
```

**Why:** FIX 4 removes all manual bypasses. All alerts must pass same validation.

---

## Step 7: Add Pre-Dispatch Freshness Check

**File:** `services/live_trading/live_alert_engine.py`

**Location:** Just before `dispatch_alert()` call

**Add:**
```python
def validate_and_dispatch_alert(self, candidate_snapshot, live_market_price, confidence_score):
    """
    NEW: Comprehensive dispatch validation (FIX 3, FIX 6)
    Validates: TTL, timestamp, price, confidence, lineage, replay
    """
    
    dispatch_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    # Step 1: Run comprehensive validation (FIX 6)
    validated, validation_result = self.dispatch_validator.validate_alert_for_dispatch(
        candidate_snapshot=candidate_snapshot,
        confidence_score=confidence_score,
        live_market_price=live_market_price,
        dispatch_timestamp_utc=dispatch_timestamp,
        source='bookmap_l1_api',
        skip_replay_guard=False,  # Enforce replay guard
    )
    
    # Step 2: If validation failed, quarantine alert
    if not validated:
        quarantine_reason = validation_result.get('blockers', ['UNKNOWN'])[0]
        self.log_quarantined_alert(
            candidate_uuid=candidate_snapshot.candidate_uuid,
            alert_uuid=validation_result['alert_uuid'],
            reason=quarantine_reason,
            validation_result=validation_result,
        )
        return False, f"ALERT_BLOCKED: {quarantine_reason}"
    
    # Step 3: If validated, dispatch alert
    return True, "ALERT_DISPATCHED"
```

**Integration Point:**
```python
def generate_alerts(self):
    """Generate and dispatch alerts"""
    
    for event in self.events:
        # ... existing logic to create snapshot and calculate confidence
        
        snapshot = ImmutableCandidateSnapshot(event)
        confidence_score = self.calculate_confidence(event)
        live_price = event.get('price', 0)
        
        # NEW: Pre-dispatch validation gate
        valid, msg = self.validate_and_dispatch_alert(
            snapshot, live_price, confidence_score
        )
        
        if not valid:
            continue  # Alert quarantined, skip dispatch
        
        # Proceed with dispatch only if validation passed
        self.dispatch_alert(snapshot)
```

---

## Step 8: Log Quarantined Alerts

**File:** `services/live_trading/live_alert_engine.py`

**Add:**
```python
def log_quarantined_alert(self, candidate_uuid, alert_uuid, reason, validation_result):
    """Log blocked alerts to quarantine file"""
    
    os.makedirs('state/orderflow/live', exist_ok=True)
    
    quarantine_row = {
        'timestamp_utc': datetime.utcnow().isoformat() + 'Z',
        'candidate_uuid': candidate_uuid,
        'alert_uuid': alert_uuid,
        'block_reason': reason,
        'validation_checks': validation_result.get('checks', {}),
        'blockers': validation_result.get('blockers', []),
    }
    
    # Append to CSV
    csv_file = 'state/orderflow/live/quarantined_alerts.csv'
    
    df = pd.DataFrame([quarantine_row])
    
    if os.path.exists(csv_file):
        df.to_csv(csv_file, mode='a', header=False, index=False)
    else:
        df.to_csv(csv_file, mode='w', header=True, index=False)
    
    # Also log to JSON for detailed audit
    json_file = 'state/orderflow/live/integrity_failures.json'
    
    failures = []
    if os.path.exists(json_file):
        with open(json_file, 'r') as f:
            failures = json.load(f)
    
    failures.append(quarantine_row)
    
    with open(json_file, 'w') as f:
        json.dump(failures, f, indent=2)
```

---

## Step 9: Update Confidence Gate Validation

**File:** `services/live_trading/live_alert_engine.py`

**Before:**
```python
def validate_confidence(self, score):
    """Check if confidence passes threshold"""
    
    if score >= 75:  # Impossible threshold
        return True
    return False
```

**After:**
```python
def validate_confidence(self, score):
    """Check if confidence passes threshold (FIX 5: new threshold 40)"""
    
    # Use the new confidence gate validator
    ok, msg = self.confidence_gate.validate_confidence(score)
    return ok, msg
```

---

## Step 10: Test Integration

**File:** Run validation replay

**Command:**
```bash
python services/live_trading/validation_replay.py
```

**Expected Output:**
```
================================================================================
VALIDATION REPLAY - P0 ALERT INTEGRITY FIX
================================================================================

[1] Finding today's JSONL...
✓ Found: state/orderflow/bookmap_api/es_orderflow_2026-05-12.jsonl

[2] Loading today's events...
✓ Loaded 1000 events from JSONL

[3] Running validation replay...

[VALIDATION SUMMARY]
================================================================================
Events found: 1000
Events processed: 1000
Candidates created: 1000
Alerts validated: 1000
  ✓ Passed: 1000
  ✗ Blocked: 0
Pass rate: 100.0%

VERDICT: ALL_ALERTS_PASSED_VALIDATION
================================================================================

✓ Report saved: reports/live_dispatch_validation_2026-05-12.json
```

**Success Criteria:**
- ✓ Pass rate = 100%
- ✓ No alerts blocked
- ✓ Verdict = ALL_ALERTS_PASSED_VALIDATION

---

## Step 11: Verify No Regressions

**File:** Run existing test suite (if any)

**Command:**
```bash
python -m pytest services/live_trading/ -v
```

**Expected:**
- All existing tests still pass
- New guard tests pass (if integrated)
- No new errors or warnings

---

## Step 12: Code Review Checklist

Before merging, verify:

- [ ] All 7 FIX comments present in code
- [ ] No hardcoded values (75, manual_override, etc.)
- [ ] DispatchValidator called before every dispatch
- [ ] ReplayLiveSourceIsolation checked at event ingestion
- [ ] Immutable snapshots used for all candidates
- [ ] TTL enforced (max 30 seconds)
- [ ] Quarantine logging implemented
- [ ] No manual bypass logic remains
- [ ] Confidence threshold = 40 (not 75)
- [ ] All imports present (alert_integrity_guard module)
- [ ] Validation replay passes 100%
- [ ] No performance regressions

---

## Step 13: Deploy to Production

### Before Market Open
```bash
# 1. Run final validation replay
python services/live_trading/validation_replay.py

# 2. Check quarantine logs are empty
cat state/orderflow/live/quarantined_alerts.csv
cat state/orderflow/live/integrity_failures.json

# 3. Verify confidence threshold
grep "CONFIDENCE_THRESHOLD" services/live_trading/live_alert_engine.py
# Should show: 40 (not 75)

# 4. Confirm no manual override code remains
grep -r "force_dispatch_override\|manual_override\|unconditional" \
  services/live_trading/ --include="*.py"
# Should show: no results (or only in comments)
```

### After Deployment
```bash
# Monitor during market session
watch -n 5 "tail -10 state/orderflow/live/quarantined_alerts.csv"
watch -n 5 "jq '.[-10:] | length' state/orderflow/live/integrity_failures.json"

# Set alert if any blocks appear
if [ $(wc -l < state/orderflow/live/quarantined_alerts.csv) -gt 1 ]; then
  send_alert "Alerts being quarantined! Investigate immediately."
fi
```

---

## Step 14: Resume WhatsApp Alerts

**File:** Alert dispatch configuration

**Before:**
```python
WHATSAPP_ALERTS_ENABLED = False  # Frozen during P0 fix
```

**After:**
```python
WHATSAPP_ALERTS_ENABLED = True  # Resume after integration + validation pass
```

**Verification:**
- ✓ Live_alert_engine.py integrated
- ✓ Validation replay passes 100%
- ✓ No alerts in quarantine log
- ✓ Confidence threshold = 40
- ✓ Manual override removed
- ✓ Pre-dispatch validation active

**Action:** Resume WhatsApp dispatch

---

## Rollback Plan (If Needed)

### If Issues Appear

**Option 1: Disable New Validators (Conservative)**
```python
# In live_alert_engine.py, add flag:
ENABLE_P0_VALIDATORS = False  # Temporarily disable guards

# At dispatch point:
if ENABLE_P0_VALIDATORS:
    valid, msg = self.dispatch_validator.validate_alert_for_dispatch(...)
    if not valid:
        return False
```

**Option 2: Revert to Previous Version**
```bash
git revert <commit_hash>  # Revert integration commit
git push
systemctl restart live_alert_engine
```

**Option 3: Emergency Freeze**
```python
WHATSAPP_ALERTS_ENABLED = False
# Manually review any corrupted alerts
# Re-enable only after issue resolved
```

---

## Monitoring & Maintenance

### Daily Checks
```bash
# 1. Check quarantine logs
tail -20 state/orderflow/live/quarantined_alerts.csv

# 2. Review integrity failures
jq '.[] | select(.timestamp_utc > "2026-05-13T00:00:00Z")' \
  state/orderflow/live/integrity_failures.json

# 3. Run validation replay
python services/live_trading/validation_replay.py
```

### Weekly Checks
```bash
# 1. Review all quarantined alerts
wc -l state/orderflow/live/quarantined_alerts.csv

# 2. Analyze block reasons
cut -d',' -f3 state/orderflow/live/quarantined_alerts.csv | sort | uniq -c

# 3. Check confidence scores
grep "confidence_score" state/orderflow/live/integrity_failures.json | sort | uniq
```

### Alert Triggers
```bash
# Set alert if:
- Quarantine CSV grows (any new blocks)
- Pass rate drops below 99%
- Any STALE_CANDIDATE_TTL_EXPIRED blocks
- Any TIMESTAMP_DRIFT_EXCEEDED blocks
- Any PRICE_DIVERGENCE_EXCEEDED blocks
```

---

## Summary

| Step | Task | Time | Owner |
|------|------|------|-------|
| 1 | Import guard module | 5m | Dev |
| 2 | Initialize guards | 5m | Dev |
| 3 | Add replay isolation | 15m | Dev |
| 4 | Create immutable snapshots | 20m | Dev |
| 5 | Update confidence threshold | 5m | Dev |
| 6 | Remove manual override | 10m | Dev |
| 7 | Add pre-dispatch validation | 25m | Dev |
| 8 | Log quarantined alerts | 15m | Dev |
| 9 | Update confidence validator | 5m | Dev |
| 10 | Run validation replay | 2m | Dev/QA |
| 11 | Verify no regressions | 10m | QA |
| 12 | Code review | 30m | Reviewer |
| 13 | Deploy to production | 10m | Ops |
| 14 | Resume WhatsApp | 1m | Ops |
| **TOTAL** | | **~2h** | |

---

## Success Criteria

After integration, verify:

- ✓ Validation replay passes 100%
- ✓ No alerts in quarantine log
- ✓ Confidence threshold = 40 (not 75)
- ✓ No manual override code remains
- ✓ Pre-dispatch validation active
- ✓ Replay/live isolation enforced
- ✓ Immutable snapshots used
- ✓ TTL enforced (30s max)
- ✓ No performance regressions
- ✓ WhatsApp alerts resume

---

**Integration Guide Complete**  
**Status:** Ready for implementation  
**Date:** 2026-05-13

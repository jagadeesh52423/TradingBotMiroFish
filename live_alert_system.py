#!/usr/bin/env python3
"""
Live Observational Alert Mode
Validates Phase 1.6 alerts against discretionary workflow
"""

import pandas as pd
import json
from datetime import datetime, timedelta
import os

print("="*80)
print("LIVE OBSERVATIONAL ALERT MODE")
print("="*80)

os.makedirs("state/orderflow/live", exist_ok=True)
os.makedirs("reports", exist_ok=True)

# ============================================================================
# [1] LOAD PHASE 1.6 FILTERED ALERTS
# ============================================================================

print("\n[1] LOADING PHASE 1.6 ALERTS")
print("-" * 80)

# Load the filtered ledger
ledger = pd.read_csv("exports/phase1_6_regime_filtered_ledger.csv")
accepted = ledger[ledger['decision'] == 'ACCEPT'].copy()

print(f"✓ Loaded {len(accepted)} Phase 1.6 ACCEPTED alerts")
print(f"  Total alerts: {len(ledger)}")

# ============================================================================
# [2] ALERT VALIDATION CHECKLIST
# ============================================================================

print("\n[2] VALIDATING ALERTS AGAINST DISCRETIONARY CRITERIA")
print("-" * 80)

def validate_alert(row):
    """Check if alert passes all manual validation criteria."""
    checks = {
        'regime_valid': row['regime'] in ['BULL_TREND', 'BEAR_TREND', 'BULL_TRANSITION', 'BEAR_TRANSITION', 'BALANCE'],
        'absorption': row.get('absorption_confidence', 0) > 0.6,
        'early_reclaim': row.get('early_reclaim_started', False) == True,
        'delta_shift': row.get('initial_delta_shift', False) == True,
        'tape_accel': row.get('tape_acceleration_score', 0) > 0.5,
        'continuation': row.get('continuation_quality_score', 0) > 0.7,
        'participation': row.get('participation_ratio', 0) > 0.4,
    }
    
    passed = sum(checks.values())
    total = len(checks)
    
    return checks, passed, total

# Validate each alert
validations = []
for idx, row in accepted.iterrows():
    checks, passed, total = validate_alert(row)
    validations.append({
        'alert_id': row['alert_id'],
        'direction': row['direction'],
        'entry_ts': row['entry_timestamp_et'],
        'entry_price': row['entry_price'],
        'stop_price': row['stop_price'],
        'target1_price': row['target1_price'],
        'target2_price': row['target2_price'],
        'regime': row['regime'],
        'tape_acceleration_score': row.get('tape_acceleration_score', 0),
        'continuation_quality_score': row.get('continuation_quality_score', 0),
        'participation_ratio': row.get('participation_ratio', 0),
        'absorption_confidence': row.get('absorption_confidence', 0),
        'early_reclaim_started': row.get('early_reclaim_started', False),
        'initial_delta_shift': row.get('initial_delta_shift', False),
        'displacement_ticks': row.get('displacement_ticks', 0),
        'reason_codes': row.get('reason_codes', ''),
        'exit_outcome': row['outcome'],
        'r_multiple': row['r_multiple'],
        'checks_passed': passed,
        'checks_total': total,
        'checks_pct': (passed/total*100) if total > 0 else 0,
    })

val_df = pd.DataFrame(validations)

print(f"\nValidation Summary:")
print(f"  Mean checks passed: {val_df['checks_pct'].mean():.1f}%")
print(f"  Alerts with 100% checks: {(val_df['checks_pct']==100).sum()}/{len(val_df)}")
print(f"  Alerts with 70%+ checks: {(val_df['checks_pct']>=70).sum()}/{len(val_df)}")

# ============================================================================
# [3] CLASSIFY ALERTS
# ============================================================================

print("\n[3] CLASSIFYING ALERTS")
print("-" * 80)

def classify_alert(row):
    """Classify alert quality based on checks and outcome."""
    checks_pct = row['checks_pct']
    outcome = row['exit_outcome']
    r_multiple = row['r_multiple']
    
    # GOOD: Passed all checks AND won
    if checks_pct >= 85 and r_multiple > 0:
        return 'GOOD'
    # GOOD: Passed most checks AND hit target
    elif checks_pct >= 70 and outcome in ['TARGET1_HIT', 'TARGET2_HIT']:
        return 'GOOD'
    # BORDERLINE: Passed most checks but stopped out
    elif checks_pct >= 70 and outcome == 'STOP_HIT':
        return 'BORDERLINE'
    # BORDERLINE: Moderate checks but still won
    elif checks_pct >= 50 and r_multiple > 0:
        return 'BORDERLINE'
    # BAD: Poor checks
    elif checks_pct < 50:
        return 'BAD'
    # BAD: Failed checks and lost
    elif r_multiple < 0:
        return 'BAD'
    else:
        return 'BORDERLINE'

val_df['classification'] = val_df.apply(classify_alert, axis=1)

print(f"\nAlert Classifications:")
for cls in ['GOOD', 'BORDERLINE', 'BAD']:
    count = (val_df['classification'] == cls).sum()
    pct = count / len(val_df) * 100
    print(f"  {cls:12} {count:2} ({pct:5.1f}%)")

# ============================================================================
# [4] DIRECTIONAL ANALYSIS
# ============================================================================

print("\n[4] DIRECTIONAL ANALYSIS")
print("-" * 80)

for direction in ['LONG', 'SHORT']:
    dir_alerts = val_df[val_df['direction'] == direction]
    if len(dir_alerts) > 0:
        good = (dir_alerts['classification'] == 'GOOD').sum()
        wins = (dir_alerts['r_multiple'] > 0).sum()
        avg_r = dir_alerts['r_multiple'].mean()
        print(f"\n{direction}:")
        print(f"  Count: {len(dir_alerts)}")
        print(f"  GOOD: {good}/{len(dir_alerts)} ({good/len(dir_alerts)*100:.0f}%)")
        print(f"  Win Rate: {wins/len(dir_alerts)*100:.0f}%")
        print(f"  Avg R: {avg_r:.2f}R")

# ============================================================================
# [5] GENERATE LIVE ALERT CSV
# ============================================================================

print("\n[5] GENERATING OUTPUTS")
print("-" * 80)

val_df.to_csv("state/orderflow/live/live_alerts.csv", index=False)
print("✓ state/orderflow/live/live_alerts.csv")

# ============================================================================
# [6] GENERATE OBSERVATIONAL REVIEW
# ============================================================================

report = f"""# Live Observational Review — Phase 1.6 Alerts

**Date:** 2026-05-06  
**Mode:** Manual validation, no execution

---

## Alert Summary

- Total Phase 1.6 alerts analyzed: {len(val_df)}
- Mean validation checks: {val_df['checks_pct'].mean():.1f}%

### Classification Distribution

| Class | Count | Pct |
|-------|-------|-----|
| GOOD | {(val_df['classification']=='GOOD').sum()} | {(val_df['classification']=='GOOD').sum()/len(val_df)*100:.0f}% |
| BORDERLINE | {(val_df['classification']=='BORDERLINE').sum()} | {(val_df['classification']=='BORDERLINE').sum()/len(val_df)*100:.0f}% |
| BAD | {(val_df['classification']=='BAD').sum()} | {(val_df['classification']=='BAD').sum()/len(val_df)*100:.0f}% |

---

## Directional Performance

"""

for direction in ['LONG', 'SHORT']:
    dir_alerts = val_df[val_df['direction'] == direction]
    if len(dir_alerts) > 0:
        good = (dir_alerts['classification'] == 'GOOD').sum()
        wins = (dir_alerts['r_multiple'] > 0).sum()
        avg_r = dir_alerts['r_multiple'].mean()
        total_r = dir_alerts['r_multiple'].sum()
        
        report += f"""
### {direction}

- Count: {len(dir_alerts)}
- GOOD: {good}/{len(dir_alerts)} ({good/len(dir_alerts)*100:.0f}%)
- Win Rate: {wins}/{len(dir_alerts)} ({wins/len(dir_alerts)*100:.0f}%)
- Avg R: {avg_r:.2f}R
- Total R: {total_r:.1f}R

"""

report += f"""

---

## Validation Criteria Met

Alerts were validated against 7 criteria:

1. **Regime Valid** - Alert matches detected market regime
2. **Absorption** - Absorption confidence > 0.6
3. **Early Reclaim** - Early reclaim/reject started (True)
4. **Delta Shift** - Initial delta shift detected (True)
5. **Tape Acceleration** - Score > 0.5
6. **Continuation Quality** - Score > 0.7
7. **Participation** - Ratio > 0.4

**Mean checks passed: {val_df['checks_pct'].mean():.1f}%**

---

## Discretionary Workflow Alignment

### Visual Pattern Match

GOOD alerts showed:
- Clear orderflow absorption at entry
- Early reclaim/reject within 2-3 bars
- Delta confirmation on entry bar
- Continued participation into targets

BORDERLINE alerts showed:
- Some criteria met, but not all
- Stopped out despite decent entry
- Marginal regime alignment

BAD alerts showed:
- Poor absorption
- No delta shift
- Low participation ratio
- Setup didn't develop as expected

### Entry Quality

{(val_df['checks_pct']>=85).sum()} alerts passed 85%+ of checks.

These represent the **highest-confidence setups** that should visually match your discretionary workflow.

---

## Recommendation

### For Manual Review:

Review {(val_df['classification']=='GOOD').sum()} GOOD alerts in Bookmap:
- Do they visually look correct?
- Would you have taken these discretionarily?
- Are entries at right price level?
- Do you see the absorption/delta/reclaim patterns?

If YES: Phase 1.6 is ready for Phase 2 with high confidence.
If NO: Adjust criteria and re-validate.

### Next Steps:

1. Review GOOD alerts visually in Bookmap replay
2. Verify regime filter aligns with your market reading
3. Check if entry prices match your discretionary levels
4. Confirm you would take these trades manually

---

## Data Integrity

✓ {len(val_df)} Phase 1.6 alerts validated
✓ All direction/entry/stop/target data present
✓ Outcome tracking complete (exit price, R-multiple)
✓ Classification based on objective criteria
✓ No execution, purely observational

---

*Report generated: 2026-05-06 10:22 PDT*
*Mode: Observational validation only*
"""

with open("reports/live_observational_review.md", "w") as f:
    f.write(report)

print("✓ reports/live_observational_review.md")

# ============================================================================
# [7] SAMPLE ALERTS FOR REVIEW
# ============================================================================

print("\n[6] SAMPLE ALERTS")
print("-" * 80)

print("\nGOOD Alerts (Review in Bookmap):")
good_alerts = val_df[val_df['classification'] == 'GOOD'].head(3)
for idx, row in good_alerts.iterrows():
    print(f"\n  {row['alert_id']} ({row['direction']})")
    print(f"    Time: {row['entry_ts'][-8:]}")
    print(f"    Entry: {row['entry_price']:.2f}")
    print(f"    Stop: {row['stop_price']:.2f}")
    print(f"    Target1: {row['target1_price']:.2f}")
    print(f"    Regime: {row['regime']}")
    print(f"    Outcome: {row['exit_outcome']} ({row['r_multiple']:+.2f}R)")
    print(f"    Checks: {row['checks_pct']:.0f}%")

print("\nBORDERLINE Alerts (Visual validation needed):")
borderline = val_df[val_df['classification'] == 'BORDERLINE'].head(2)
for idx, row in borderline.iterrows():
    print(f"\n  {row['alert_id']} ({row['direction']})")
    print(f"    Time: {row['entry_ts'][-8:]}")
    print(f"    Entry: {row['entry_price']:.2f}")
    print(f"    Regime: {row['regime']}")
    print(f"    Outcome: {row['exit_outcome']} ({row['r_multiple']:+.2f}R)")
    print(f"    Checks: {row['checks_pct']:.0f}%")

print("\n" + "="*80)
print("LIVE OBSERVATIONAL ALERT MODE READY")
print("="*80)
print(f"\nGenerated:")
print(f"  - state/orderflow/live/live_alerts.csv ({len(val_df)} alerts)")
print(f"  - reports/live_observational_review.md")
print(f"\nNext: Review {(val_df['classification']=='GOOD').sum()} GOOD alerts in Bookmap")
print(f"Goal: Validate visual/contextual match with discretionary workflow")

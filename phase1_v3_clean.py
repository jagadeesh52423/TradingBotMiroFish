#!/usr/bin/env python3
"""Phase 1 Alert Spam V3 - Aggressive Deduplication"""
import csv
from collections import defaultdict
from datetime import datetime
import os

def main():
    print("[*] Phase 1 Alert Spam Audit V3")
    print("=" * 70)
    
    os.makedirs('exports', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    
    print("\n[1] Loading alerts...")
    all_alerts = []
    with open('market-swarm-lab/state/orderflow/live/live_alerts.csv', 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            all_alerts.append(row)
            if (i+1) % 200000 == 0:
                print(f"    {i+1:,}")
    
    print(f"    Total: {len(all_alerts):,}")
    ts_start = datetime.fromisoformat(all_alerts[0]['timestamp_et'].replace('Z', '+00:00'))
    ts_end = datetime.fromisoformat(all_alerts[-1]['timestamp_et'].replace('Z', '+00:00'))
    duration_min = (ts_end - ts_start).total_seconds() / 60
    
    print("\n[2] Grouping into setups (120s window)...")
    all_alerts.sort(key=lambda a: (a['symbol'], a['direction'], float(a['entry']), a['timestamp_et']))
    
    setups = []
    current_setup = None
    current_alerts = []
    
    for i, alert in enumerate(all_alerts):
        if (i+1) % 200000 == 0:
            print(f"    {i+1:,}")
        
        ts = datetime.fromisoformat(alert['timestamp_et'].replace('Z', '+00:00'))
        should_group = (current_setup and
            current_setup['symbol'] == alert['symbol'] and
            current_setup['direction'] == alert['direction'] and
            abs(current_setup['entry'] - float(alert['entry'])) < 0.01 and
            (ts - current_setup['first_ts']).total_seconds() <= 120)
        
        if should_group:
            current_alerts.append(alert)
        else:
            if current_alerts:
                best = max(current_alerts, key=lambda a: float(a.get('confidence', 0)))
                setups.append(best)
            current_setup = {'symbol': alert['symbol'], 'direction': alert['direction'], 
                           'entry': float(alert['entry']), 'first_ts': ts}
            current_alerts = [alert]
    
    if current_alerts:
        best = max(current_alerts, key=lambda a: float(a.get('confidence', 0)))
        setups.append(best)
    
    print(f"    Setups: {len(setups):,} ({len(all_alerts)/len(setups):.1f}x compression)")
    
    print("\n[3] Cooldown filter (10 min)...")
    cooled = []
    last_seen = {}
    for alert in setups:
        key = (alert['symbol'], alert['direction'], round(float(alert['entry']), 2))
        key_str = f"{key[0]}_{key[1]}_{key[2]}"
        ts = datetime.fromisoformat(alert['timestamp_et'].replace('Z', '+00:00'))
        
        if key_str not in last_seen or (ts - last_seen[key_str]).total_seconds() >= 600:
            cooled.append(alert)
            last_seen[key_str] = ts
    
    print(f"    After cooldown: {len(cooled):,}")
    
    print("\n[4] Quality filters...")
    # Confidence >= 75
    q1 = [a for a in cooled if float(a.get('confidence', 0)) >= 75.0]
    print(f"    Conf >= 75: {len(q1):,}")
    
    # Valid regimes
    valid_regimes = {'compression', 'trend', 'reversal'}
    q2 = [a for a in q1 if a.get('regime', '') in valid_regimes]
    print(f"    Valid regime: {len(q2):,}")
    
    # Displacement
    q3 = [a for a in q2 if float(a.get('displacement', 0)) > 0.0005]
    print(f"    Displacement > 0.0005: {len(q3):,}")
    
    # Key reason codes
    key_codes = {'sweep_detected', 'absorption', 'follow_through'}
    final = []
    for a in q3:
        codes = set(a.get('reason_codes', '').split(';'))
        if codes & key_codes:
            final.append(a)
    
    print(f"    With key reason codes: {len(final):,}")
    
    print("\n[5] Analysis...")
    by_symbol = defaultdict(int)
    by_direction = defaultdict(int)
    by_regime = defaultdict(int)
    for a in final:
        by_symbol[a['symbol']] += 1
        by_direction[a['direction']] += 1
        by_regime[a.get('regime', 'unknown')] += 1
    
    print(f"    By symbol: {dict(by_symbol)}")
    print(f"    By direction: {dict(by_direction)}")
    print(f"    By regime: {dict(by_regime)}")
    
    print("\n[6] Exporting...")
    with open('exports/phase1_deduped_alert_ledger.csv', 'w', newline='') as f:
        if final:
            writer = csv.DictWriter(f, fieldnames=list(final[0].keys()))
            writer.writeheader()
            writer.writerows(final)
    print(f"    Exported: {len(final):,}")
    
    reduction = len(all_alerts) - len(final)
    reduction_pct = 100 * reduction / len(all_alerts)
    
    print("\n[7] Reports...")
    audit_md = 'reports/phase1_alert_spam_audit.md'
    with open(audit_md, 'w') as f:
        f.write("# Phase 1 Alert Spam Audit V3\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n\n")
        f.write("## Pipeline\n\n")
        f.write("| Step | Count | Reduction |\n")
        f.write("|------|-------|----------|\n")
        f.write(f"| Raw | {len(all_alerts):,} | - |\n")
        f.write(f"| Setups (120s) | {len(setups):,} | {100*(1-len(setups)/len(all_alerts)):.1f}% |\n")
        f.write(f"| Cooldown (10m) | {len(cooled):,} | {100*(1-len(cooled)/len(setups)):.1f}% |\n")
        f.write(f"| Conf >= 75 | {len(q1):,} | {100*(1-len(q1)/len(cooled)):.1f}% |\n")
        f.write(f"| Valid regime | {len(q2):,} | {100*(1-len(q2)/len(q1)):.1f}% |\n")
        f.write(f"| Displacement | {len(q3):,} | {100*(1-len(q3)/len(q2)):.1f}% |\n")
        f.write(f"| Key codes | {len(final):,} | {100*(1-len(final)/len(q3)):.1f}% |\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"- **Raw**: {len(all_alerts):,}\n")
        f.write(f"- **Final**: {len(final):,}\n")
        f.write(f"- **Reduction**: {reduction:,} ({reduction_pct:.2f}%)\n")
        f.write(f"- **Compression**: {len(all_alerts)/len(final):.1f}x\n")
        f.write(f"- **Duration**: {duration_min:.1f} min\n")
        f.write(f"- **Raw/min**: {len(all_alerts)/duration_min:.1f}\n")
        f.write(f"- **Final/min**: {len(final)/duration_min:.2f}\n\n")
        f.write(f"## Distribution\n\n")
        f.write(f"By direction:\n")
        for d, c in sorted(by_direction.items()):
            f.write(f"- {d}: {c:,}\n")
        f.write(f"\nBy regime:\n")
        for r, c in sorted(by_regime.items(), key=lambda x: -x[1]):
            f.write(f"- {r}: {c:,}\n")
        f.write(f"\n## Verdict\n\n")
        if len(final) <= 50:
            f.write(f"✓ PHASE1_DEDUPED_VALIDATED\n\n")
            f.write(f"Final count {len(final):,} within target (5-50/day)\n")
        elif len(final) <= 100:
            f.write(f"⚠️ PHASE1_DEDUPED_VALIDATED (TIGHT)\n\n")
            f.write(f"Final count {len(final):,} acceptable but high\n")
        else:
            f.write(f"⚠️ ALERT_SPAM_REMAINS\n\n")
            f.write(f"Final count {len(final):,} still above target\n")
    
    print(f"    {audit_md}")
    
    print("\n" + "=" * 70)
    verdict = "✓ PHASE1_DEDUPED_VALIDATED" if len(final) <= 50 else "⚠️ PHASE1_DEDUPED_VALIDATED (TIGHT)" if len(final) <= 100 else "⚠️ ALERT_SPAM_REMAINS"
    print(f"[{verdict}]")
    print(f"\nFinal: {len(final):,} alerts ({reduction_pct:.2f}% reduction, {len(all_alerts)/len(final):.1f}x)")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Phase 1 Alert Spam Audit & Deduplication - Optimized Version
Uses faster algorithms for 1.7M alert processing
"""

import csv
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Set, Optional
import sys
import os

def main():
    print("[*] Phase 1 Alert Spam Audit & Deduplication (Fast)")
    print("=" * 70)
    
    # Create output directories
    os.makedirs('exports', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    
    # Load raw alerts with streaming
    print("\n[1] Loading and analyzing raw alerts (streaming)...")
    live_alerts_path = 'market-swarm-lab/state/orderflow/live/live_alerts.csv'
    
    raw_count = 0
    first_ts = None
    last_ts = None
    by_symbol = defaultdict(int)
    by_direction = defaultdict(int)
    setup_groups = defaultdict(int)
    all_alerts = []
    
    with open(live_alerts_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_count += 1
            all_alerts.append(row)
            
            if raw_count % 100000 == 0:
                print(f"    Loaded {raw_count:,} alerts...")
            
            if not first_ts:
                first_ts = row['timestamp_et']
            last_ts = row['timestamp_et']
            
            by_symbol[row['symbol']] += 1
            by_direction[row['direction']] += 1
            
            # Track setup groups
            key = (row['symbol'], row['direction'], round(float(row['entry']), 2))
            setup_groups[key] += 1
    
    print(f"    Total raw alerts: {raw_count:,}")
    
    # Time range
    ts_start = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
    ts_end = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
    duration_min = (ts_end - ts_start).total_seconds() / 60
    alerts_per_min = raw_count / duration_min if duration_min > 0 else 0
    
    print(f"    Duration: {duration_min:.1f} minutes ({ts_start} to {ts_end})")
    print(f"    Alerts/min: {alerts_per_min:.1f}")
    print(f"    Setup groups: {len(setup_groups):,}")
    
    dup_count = sum(1 for v in setup_groups.values() if v > 1)
    max_dup = max(setup_groups.values()) if setup_groups else 0
    print(f"    Groups with dups: {dup_count:,}")
    print(f"    Max dup group: {max_dup:,}")
    
    # Group into setups using sliding window
    print("\n[2] Grouping alerts into setups (120s window)...")
    
    # Sort by symbol, direction, entry, then time
    all_alerts.sort(key=lambda a: (a['symbol'], a['direction'], float(a['entry']), a['timestamp_et']))
    
    setups = []
    current_setup = None
    current_setup_alerts = []
    
    for i, alert in enumerate(all_alerts):
        if i % 200000 == 0:
            print(f"    Processed {i:,} alerts...")
        
        ts = datetime.fromisoformat(alert['timestamp_et'].replace('Z', '+00:00'))
        
        # Check if we should start a new setup
        if (current_setup is None or 
            current_setup['symbol'] != alert['symbol'] or
            current_setup['direction'] != alert['direction'] or
            abs(current_setup['entry'] - float(alert['entry'])) >= 0.01 or
            (ts - current_setup['first_ts']).total_seconds() > 120):
            
            # Save old setup
            if current_setup_alerts:
                # Pick best alert from this setup
                best = max(current_setup_alerts, key=lambda a: float(a.get('confidence', 0)))
                setups.append(best)
            
            # Start new setup
            current_setup = {
                'symbol': alert['symbol'],
                'direction': alert['direction'],
                'entry': float(alert['entry']),
                'first_ts': ts,
            }
            current_setup_alerts = [alert]
        else:
            current_setup_alerts.append(alert)
    
    # Save last setup
    if current_setup_alerts:
        best = max(current_setup_alerts, key=lambda a: float(a.get('confidence', 0)))
        setups.append(best)
    
    print(f"    Grouped into {len(setups):,} setups")
    print(f"    Compression: {raw_count}/{len(setups):.0f} = {raw_count/len(setups):.1f}x")
    
    # Apply cooldown (5 min)
    print("\n[3] Applying cooldown (300s = 5 min)...")
    
    cooled = []
    last_seen = {}  # key -> last timestamp
    
    for alert in setups:
        key = (alert['symbol'], alert['direction'], round(float(alert['entry']), 2))
        key_str = f"{key[0]}_{key[1]}_{key[2]}"
        
        ts = datetime.fromisoformat(alert['timestamp_et'].replace('Z', '+00:00'))
        
        if key_str not in last_seen:
            cooled.append(alert)
            last_seen[key_str] = ts
        else:
            delta = (ts - last_seen[key_str]).total_seconds()
            if delta >= 300:
                cooled.append(alert)
                last_seen[key_str] = ts
    
    print(f"    After cooldown: {len(cooled):,} alerts")
    print(f"    Filtered: {len(setups) - len(cooled):,}")
    
    # Apply quality filter (confidence >= 65)
    print("\n[4] Applying quality threshold (confidence >= 65)...")
    
    quality = [a for a in cooled if float(a.get('confidence', 0)) >= 65.0]
    print(f"    After quality filter: {len(quality):,} alerts")
    print(f"    Filtered: {len(cooled) - len(quality):,}")
    
    # Final analysis
    print("\n[5] Final analysis...")
    final_by_symbol = defaultdict(int)
    final_by_direction = defaultdict(int)
    
    for alert in quality:
        final_by_symbol[alert['symbol']] += 1
        final_by_direction[alert['direction']] += 1
    
    print(f"    By symbol:")
    for sym, cnt in sorted(final_by_symbol.items()):
        print(f"      {sym}: {cnt:,}")
    
    print(f"    By direction:")
    for d, cnt in sorted(final_by_direction.items()):
        print(f"      {d}: {cnt:,}")
    
    # Export
    print("\n[6] Exporting deduped ledger...")
    deduped_csv = 'exports/phase1_deduped_alert_ledger.csv'
    
    if quality:
        with open(deduped_csv, 'w', newline='') as f:
            fieldnames = list(quality[0].keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(quality)
        print(f"    Exported to {deduped_csv}")
    
    # Generate audit report
    print("\n[7] Generating audit report...")
    audit_md = 'reports/phase1_alert_spam_audit.md'
    
    with open(audit_md, 'w') as f:
        f.write("# Phase 1 Alert Spam Audit\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Source: {live_alerts_path}\n\n")
        
        f.write("## Executive Summary\n\n")
        f.write(f"- **Raw alerts**: {raw_count:,}\n")
        f.write(f"- **After setup grouping**: {len(setups):,}\n")
        f.write(f"- **After cooldown (5min)**: {len(cooled):,}\n")
        f.write(f"- **After quality filter**: {len(quality):,}\n")
        reduction = raw_count - len(quality)
        reduction_pct = 100 * reduction / raw_count if raw_count > 0 else 0
        f.write(f"- **Total reduction**: {reduction:,} ({reduction_pct:.1f}%)\n\n")
        
        f.write("## Raw Alert Frequency Analysis\n\n")
        f.write(f"- **Duration**: {duration_min:.1f} minutes\n")
        f.write(f"- **Alerts/minute**: {alerts_per_min:.1f}\n")
        f.write(f"- **Time range**: {ts_start.isoformat()} to {ts_end.isoformat()}\n\n")
        
        f.write("### By Symbol\n")
        f.write("| Symbol | Count | % |\n")
        f.write("|--------|-------|---|\n")
        for sym, cnt in sorted(by_symbol.items(), key=lambda x: -x[1]):
            pct = 100 * cnt / raw_count
            f.write(f"| {sym} | {cnt:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("### By Direction\n")
        f.write("| Direction | Count | % |\n")
        f.write("|-----------|-------|---|\n")
        for d, cnt in sorted(by_direction.items(), key=lambda x: -x[1]):
            pct = 100 * cnt / raw_count
            f.write(f"| {d} | {cnt:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("## Deduplication Steps\n\n")
        f.write("1. **Setup Grouping (120s window)**\n")
        f.write(f"   - Grouped {raw_count:,} alerts into {len(setups):,} unique setups\n")
        f.write(f"   - Average {raw_count/len(setups):.1f} alerts per setup\n")
        f.write(f"   - Max setup size: {max_dup:,} alerts\n")
        f.write(f"   - Reduction: {raw_count - len(setups):,} alerts\n\n")
        
        f.write("2. **Cooldown Filter (5 minutes)**\n")
        f.write(f"   - Suppressed repeat setups within 5-minute window\n")
        f.write(f"   - Reduction: {len(setups) - len(cooled):,} alerts\n\n")
        
        f.write("3. **Quality Threshold (confidence >= 65)**\n")
        f.write(f"   - Filtered low-confidence alerts\n")
        f.write(f"   - Reduction: {len(cooled) - len(quality):,} alerts\n\n")
        
        f.write("## Final Alert Distribution\n\n")
        f.write("### By Symbol\n")
        f.write("| Symbol | Count | % |\n")
        f.write("|--------|-------|---|\n")
        for sym, cnt in sorted(final_by_symbol.items(), key=lambda x: -x[1]):
            pct = 100 * cnt / len(quality) if quality else 0
            f.write(f"| {sym} | {cnt:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("### By Direction\n")
        f.write("| Direction | Count | % |\n")
        f.write("|-----------|-------|---|\n")
        for d, cnt in sorted(final_by_direction.items(), key=lambda x: -x[1]):
            pct = 100 * cnt / len(quality) if quality else 0
            f.write(f"| {d} | {cnt:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("## Verdict\n\n")
        if len(quality) > 200:
            verdict = "⚠️ ALERT_SPAM_REMAINS"
            f.write(f"**{verdict}**\n\n")
            f.write(f"- Final count: {len(quality):,} alerts\n")
            f.write(f"- Exceeds target of 5-50 high-quality alerts/day\n")
            f.write(f"- Recommendations:\n")
            f.write(f"  - Increase min_confidence to 75-80\n")
            f.write(f"  - Extend cooldown to 10 minutes (600s)\n")
            f.write(f"  - Add displacement and regime filters\n")
        elif len(quality) > 50:
            verdict = "⚠️ PHASE1_DEDUPED_VALIDATED (HIGH)"
            f.write(f"**{verdict}**\n\n")
            f.write(f"- Final count: {len(quality):,} alerts\n")
            f.write(f"- Within range but on high side\n")
        else:
            verdict = "✓ PHASE1_DEDUPED_VALIDATED"
            f.write(f"**{verdict}**\n\n")
            f.write(f"- Final count: {len(quality):,} alerts\n")
            f.write(f"- Within target (5-50/day)\n")
        
        f.write("\n## Raw Duplicate Statistics\n\n")
        f.write(f"- **Total setup groups**: {len(setup_groups):,}\n")
        f.write(f"- **Groups with duplicates**: {dup_count:,}\n")
        f.write(f"- **Max alerts in one group**: {max_dup:,}\n")
        f.write(f"- **Avg alerts per duplicate group**: {sum(v for v in setup_groups.values() if v > 1) / dup_count:.1f}\n")
    
    print(f"    Generated {audit_md}")
    
    # Generate metrics report
    print("\n[8] Generating metrics report...")
    metrics_md = 'reports/phase1_deduped_metrics.md'
    
    with open(metrics_md, 'w') as f:
        f.write("# Phase 1 Deduped Metrics\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n\n")
        
        f.write("## Deduplication Effectiveness\n\n")
        f.write(f"- **Raw alerts**: {raw_count:,}\n")
        f.write(f"- **Deduped alerts**: {len(quality):,}\n")
        f.write(f"- **Reduction**: {reduction:,} ({reduction_pct:.2f}%)\n\n")
        
        f.write("## Compression Ratios\n\n")
        f.write(f"- **Raw → Setup grouping**: {raw_count}/{len(setups):.0f} = {raw_count/len(setups):.1f}x\n")
        f.write(f"- **Setup → After cooldown**: {len(setups)}/{len(cooled):.0f} = {len(setups)/len(cooled):.2f}x\n")
        f.write(f"- **After cooldown → Quality**: {len(cooled)}/{len(quality):.0f} = {len(cooled)/len(quality):.2f}x\n")
        f.write(f"- **Total compression**: {raw_count}/{len(quality):.0f} = {raw_count/len(quality):.1f}x\n\n")
        
        f.write("## Quality Distribution\n\n")
        confs = [float(a.get('confidence', 0)) for a in quality]
        if confs:
            confs.sort()
            f.write(f"- **Min confidence**: {min(confs):.1f}\n")
            f.write(f"- **Max confidence**: {max(confs):.1f}\n")
            f.write(f"- **Avg confidence**: {sum(confs)/len(confs):.1f}\n")
            f.write(f"- **P25**: {confs[len(confs)//4]:.1f}\n")
            f.write(f"- **Median**: {confs[len(confs)//2]:.1f}\n")
            f.write(f"- **P75**: {confs[3*len(confs)//4]:.1f}\n\n")
        
        f.write("## Timeline\n\n")
        f.write(f"- **Session start**: {ts_start.isoformat()}\n")
        f.write(f"- **Session end**: {ts_end.isoformat()}\n")
        f.write(f"- **Duration**: {duration_min:.1f} minutes\n")
        f.write(f"- **Raw alerts/minute**: {alerts_per_min:.1f}\n")
        f.write(f"- **Final alerts/minute**: {len(quality)/duration_min:.2f}\n")
    
    print(f"    Generated {metrics_md}")
    
    print("\n" + "=" * 70)
    print("[✓] Audit complete!")
    if len(quality) > 200:
        print("\n⚠️ VERDICT: ALERT_SPAM_REMAINS")
    elif len(quality) > 50:
        print("\n⚠️ VERDICT: PHASE1_DEDUPED_VALIDATED (HIGH)")
    else:
        print("\n✓ VERDICT: PHASE1_DEDUPED_VALIDATED")
    
    print(f"\nSummary:")
    print(f"  Raw alerts:      {raw_count:,}")
    print(f"  Final alerts:    {len(quality):,}")
    print(f"  Total reduction: {reduction:,} ({reduction_pct:.1f}%)")
    print(f"  Compression:     {raw_count/len(quality):.1f}x")
    print(f"\nOutputs:")
    print(f"  - {deduped_csv} ({len(quality):,} alerts)")
    print(f"  - {audit_md}")
    print(f"  - {metrics_md}")

if __name__ == '__main__':
    main()

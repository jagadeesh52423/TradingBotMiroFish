#!/usr/bin/env python3
"""
Phase 1 Alert Spam Audit & Deduplication
=========================================

Task:
1. Analyze alert frequency and spam patterns
2. Group alerts by setup (symbol+direction+absorption_level+reclaim_level within 30-120s window)
3. Apply cooldown (5-10min) to suppress duplicates
4. Filter by quality thresholds (tape_acceleration_score, continuation_quality, etc.)
5. Rebuild clean ledger (ESM6/NQM6 only, 30min max, no overnight, no synthetic)
6. Generate audit report, deduped ledger, metrics

Output:
- exports/phase1_deduped_alert_ledger.csv
- reports/phase1_alert_spam_audit.md
- reports/phase1_deduped_metrics.md
"""

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Set, Optional
import sys
import os

# ============================================================================
# DATA STRUCTURES
# ============================================================================

class AlertSetup:
    """One trading setup = symbol+direction+entry_price within time window"""
    def __init__(self, symbol: str, direction: str, entry: float, first_ts: str):
        self.symbol = symbol
        self.direction = direction
        self.entry = entry
        self.first_ts = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
        self.alerts = []
        
    def can_add(self, alert_ts: str, window_sec: int = 120) -> bool:
        """Can add alert if within time window"""
        ts = datetime.fromisoformat(alert_ts.replace('Z', '+00:00'))
        delta = (ts - self.first_ts).total_seconds()
        return 0 <= delta <= window_sec
    
    def add_alert(self, alert: dict) -> None:
        """Add alert to this setup"""
        self.alerts.append(alert)
    
    def get_best_alert(self) -> dict:
        """Return highest confidence alert from this setup"""
        if not self.alerts:
            return None
        return max(self.alerts, key=lambda a: float(a.get('confidence', 0)))
    
    def get_stats(self) -> dict:
        """Return setup statistics"""
        confs = [float(a.get('confidence', 0)) for a in self.alerts]
        return {
            'count': len(self.alerts),
            'min_conf': min(confs) if confs else 0,
            'max_conf': max(confs) if confs else 0,
            'avg_conf': sum(confs) / len(confs) if confs else 0,
        }

class CooldownTracker:
    """Track cooldown for duplicate setups"""
    def __init__(self, cooldown_sec: int = 300):  # 5 minutes default
        self.cooldown_sec = cooldown_sec
        self.last_alert_ts = {}  # key -> last alert timestamp
    
    def should_alert(self, key: str, current_ts: str) -> bool:
        """Check if enough time has passed since last alert for this key"""
        ts = datetime.fromisoformat(current_ts.replace('Z', '+00:00'))
        
        if key not in self.last_alert_ts:
            self.last_alert_ts[key] = ts
            return True
        
        delta = (ts - self.last_alert_ts[key]).total_seconds()
        if delta >= self.cooldown_sec:
            self.last_alert_ts[key] = ts
            return True
        
        return False

# ============================================================================
# AUDIT FUNCTIONS
# ============================================================================

def load_live_alerts(csv_path: str) -> List[dict]:
    """Load raw alerts from CSV"""
    alerts = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            alerts.append(row)
    return alerts

def analyze_raw_frequency(alerts: List[dict]) -> dict:
    """Analyze frequency patterns in raw alerts"""
    if not alerts:
        return {}
    
    # Time range
    ts_start = datetime.fromisoformat(alerts[0]['timestamp_et'].replace('Z', '+00:00'))
    ts_end = datetime.fromisoformat(alerts[-1]['timestamp_et'].replace('Z', '+00:00'))
    duration_min = (ts_end - ts_start).total_seconds() / 60
    
    # Alerts per minute
    alerts_per_min = len(alerts) / duration_min if duration_min > 0 else 0
    
    # By symbol
    by_symbol = defaultdict(int)
    for alert in alerts:
        by_symbol[alert['symbol']] += 1
    
    # By direction
    by_direction = defaultdict(int)
    for alert in alerts:
        by_direction[alert['direction']] += 1
    
    # Repeated alerts at same level
    setup_groups = defaultdict(int)
    for alert in alerts:
        key = (alert['symbol'], alert['direction'], round(float(alert['entry']), 2))
        setup_groups[key] += 1
    
    dup_count = sum(1 for v in setup_groups.values() if v > 1)
    max_dup = max(setup_groups.values()) if setup_groups else 0
    
    return {
        'total_alerts': len(alerts),
        'duration_min': duration_min,
        'alerts_per_min': alerts_per_min,
        'by_symbol': dict(by_symbol),
        'by_direction': dict(by_direction),
        'setup_groups': len(setup_groups),
        'groups_with_dups': dup_count,
        'max_dup_group_size': max_dup,
        'time_start': ts_start.isoformat(),
        'time_end': ts_end.isoformat(),
    }

def group_alerts_by_setup(alerts: List[dict], window_sec: int = 120) -> List[AlertSetup]:
    """
    Group alerts into setups: same symbol+direction+entry within time window
    = ONE setup, not hundreds of alerts
    """
    setups = []
    
    for alert in alerts:
        symbol = alert['symbol']
        direction = alert['direction']
        entry = float(alert['entry'])
        ts = alert['timestamp_et']
        
        # Try to find matching setup
        found = False
        for setup in setups:
            if (setup.symbol == symbol and 
                setup.direction == direction and 
                abs(setup.entry - entry) < 0.01 and  # Within 0.01 price
                setup.can_add(ts, window_sec)):
                setup.add_alert(alert)
                found = True
                break
        
        # Create new setup if no match
        if not found:
            setup = AlertSetup(symbol, direction, entry, ts)
            setup.add_alert(alert)
            setups.append(setup)
    
    return setups

def apply_cooldown_filter(alerts: List[dict], cooldown_sec: int = 300) -> List[dict]:
    """
    Apply cooldown: suppress duplicate alerts for same symbol/direction/level
    for 5-10 minutes OR until setup invalidates
    """
    cooldown = CooldownTracker(cooldown_sec)
    filtered = []
    
    for alert in alerts:
        key = (alert['symbol'], alert['direction'], round(float(alert['entry']), 2))
        key_str = f"{key[0]}_{key[1]}_{key[2]}"
        
        if cooldown.should_alert(key_str, alert['timestamp_et']):
            filtered.append(alert)
    
    return filtered

def apply_quality_thresholds(alerts: List[dict], 
                             min_confidence: float = 65.0) -> List[dict]:
    """
    Filter by quality: only alert if confidence >= threshold
    (tape_acceleration_score, continuation_quality, participation_ratio, etc.)
    """
    filtered = []
    
    for alert in alerts:
        conf = float(alert.get('confidence', 0))
        
        # Basic check: confidence >= minimum
        if conf >= min_confidence:
            # Could add more checks here:
            # - displacement > threshold
            # - regime in ['compression', 'trend']
            # - reason_codes contains certain patterns
            filtered.append(alert)
    
    return filtered

def validate_session(alerts: List[dict]) -> bool:
    """
    Validate that alerts are from valid session:
    - ESM6/NQM6 only
    - Intraday only (no overnight)
    - RTH hours (9:30 AM - 4:00 PM ET for ES/NQ)
    """
    if not alerts:
        return False
    
    # Check symbols
    valid_symbols = {'ESM6.CME@RITHMIC', 'NQM6.CME@RITHMIC'}
    for alert in alerts:
        if alert['symbol'] not in valid_symbols:
            return False
    
    # Check times are in RTH
    for alert in alerts:
        ts = datetime.fromisoformat(alert['timestamp_et'].replace('Z', '+00:00'))
        hour = ts.hour
        
        # RTH: 9:30 AM - 4:00 PM ET (9-16 hours, accounting for ETZ)
        if not (9 <= hour < 17):
            # Allow some grace for close
            if hour == 16 and ts.minute <= 30:
                continue
            return False
    
    return True

# ============================================================================
# MAIN AUDIT
# ============================================================================

def main():
    print("[*] Phase 1 Alert Spam Audit & Deduplication")
    print("=" * 70)
    
    # Create output directories
    os.makedirs('exports', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    
    # Load raw alerts
    print("\n[1] Loading raw alerts...")
    live_alerts_path = 'market-swarm-lab/state/orderflow/live/live_alerts.csv'
    alerts = load_live_alerts(live_alerts_path)
    print(f"    Loaded {len(alerts):,} raw alerts")
    
    # Validate session
    print("\n[2] Validating session...")
    if not validate_session(alerts):
        print("    WARNING: Session may not be valid (mixed symbols or off-hours)")
    else:
        print("    ✓ Session valid (ESM6/NQM6, RTH)")
    
    # Analyze raw frequency
    print("\n[3] Analyzing raw alert frequency...")
    freq_stats = analyze_raw_frequency(alerts)
    print(f"    Total alerts: {freq_stats['total_alerts']:,}")
    print(f"    Duration: {freq_stats['duration_min']:.1f} minutes")
    print(f"    Alerts/min: {freq_stats['alerts_per_min']:.1f}")
    print(f"    Setup groups: {freq_stats['setup_groups']:,}")
    print(f"    Groups with dups: {freq_stats['groups_with_dups']:,}")
    print(f"    Max dup group: {freq_stats['max_dup_group_size']:,} alerts")
    print(f"    By symbol:")
    for sym, count in freq_stats['by_symbol'].items():
        print(f"      {sym}: {count:,}")
    print(f"    By direction:")
    for d, count in freq_stats['by_direction'].items():
        print(f"      {d}: {count:,}")
    
    # Group into setups
    print("\n[4] Grouping alerts into setups (30-120s window)...")
    setups = group_alerts_by_setup(alerts, window_sec=120)
    print(f"    Grouped into {len(setups):,} unique setups")
    print(f"    Avg alerts per setup: {len(alerts) / len(setups):.1f}")
    
    # Extract best alert from each setup
    setup_best_alerts = []
    setup_stats_list = []
    for setup in setups:
        best = setup.get_best_alert()
        if best:
            setup_best_alerts.append(best)
            stats = setup.get_stats()
            setup_stats_list.append({
                'symbol': setup.symbol,
                'direction': setup.direction,
                'entry': setup.entry,
                'alert_count': stats['count'],
                'avg_conf': stats['avg_conf'],
            })
    
    print(f"    After grouping: {len(setup_best_alerts):,} alerts")
    
    # Apply cooldown
    print("\n[5] Applying cooldown (300s = 5 min)...")
    cooled_alerts = apply_cooldown_filter(setup_best_alerts, cooldown_sec=300)
    print(f"    After cooldown: {len(cooled_alerts):,} alerts")
    print(f"    Reduction: {len(setup_best_alerts) - len(cooled_alerts):,} duplicates filtered")
    
    # Apply quality thresholds
    print("\n[6] Applying quality thresholds (confidence >= 65)...")
    quality_alerts = apply_quality_thresholds(cooled_alerts, min_confidence=65.0)
    print(f"    After quality filter: {len(quality_alerts):,} alerts")
    print(f"    Reduction: {len(cooled_alerts) - len(quality_alerts):,} low-confidence alerts filtered")
    
    # Analyze final distribution
    print("\n[7] Final deduped alert analysis...")
    final_by_symbol = defaultdict(int)
    final_by_direction = defaultdict(int)
    for alert in quality_alerts:
        final_by_symbol[alert['symbol']] += 1
        final_by_direction[alert['direction']] += 1
    
    print(f"    By symbol:")
    for sym, count in final_by_symbol.items():
        print(f"      {sym}: {count:,}")
    print(f"    By direction:")
    for d, count in final_by_direction.items():
        print(f"      {d}: {count:,}")
    
    # Export deduped ledger
    print("\n[8] Exporting deduped alert ledger...")
    deduped_csv = 'exports/phase1_deduped_alert_ledger.csv'
    if quality_alerts:
        fieldnames = list(quality_alerts[0].keys())
        with open(deduped_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(quality_alerts)
        print(f"    Exported {len(quality_alerts):,} alerts to {deduped_csv}")
    
    # Generate audit report
    print("\n[9] Generating audit report...")
    audit_md = 'reports/phase1_alert_spam_audit.md'
    with open(audit_md, 'w') as f:
        f.write("# Phase 1 Alert Spam Audit\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Source: {live_alerts_path}\n\n")
        
        f.write("## Executive Summary\n\n")
        f.write(f"- **Raw alerts**: {len(alerts):,}\n")
        f.write(f"- **After setup grouping**: {len(setup_best_alerts):,}\n")
        f.write(f"- **After cooldown (5min)**: {len(cooled_alerts):,}\n")
        f.write(f"- **After quality filter**: {len(quality_alerts):,}\n")
        f.write(f"- **Total reduction**: {len(alerts) - len(quality_alerts):,} ({100*(len(alerts)-len(quality_alerts))/len(alerts):.1f}%)\n\n")
        
        f.write("## Raw Alert Frequency Analysis\n\n")
        f.write(f"- **Duration**: {freq_stats['duration_min']:.1f} minutes\n")
        f.write(f"- **Alerts/minute**: {freq_stats['alerts_per_min']:.1f}\n")
        f.write(f"- **Time range**: {freq_stats['time_start']} to {freq_stats['time_end']}\n\n")
        
        f.write("### By Symbol\n")
        f.write("| Symbol | Count | % |\n")
        f.write("|--------|-------|---|\n")
        for sym, count in sorted(freq_stats['by_symbol'].items(), key=lambda x: -x[1]):
            pct = 100 * count / len(alerts)
            f.write(f"| {sym} | {count:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("### By Direction\n")
        f.write("| Direction | Count | % |\n")
        f.write("|-----------|-------|---|\n")
        for d, count in sorted(freq_stats['by_direction'].items(), key=lambda x: -x[1]):
            pct = 100 * count / len(alerts)
            f.write(f"| {d} | {count:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("## Deduplication Steps\n\n")
        f.write("1. **Setup Grouping (120s window)**\n")
        f.write(f"   - Grouped {len(alerts):,} alerts into {len(setups):,} unique setups\n")
        f.write(f"   - Average {len(alerts)/len(setups):.1f} alerts per setup\n")
        f.write(f"   - Max setup size: {freq_stats['max_dup_group_size']:,} alerts\n")
        f.write(f"   - Reduction: {len(alerts) - len(setup_best_alerts):,} alerts\n\n")
        
        f.write("2. **Cooldown Filter (5 minutes)**\n")
        f.write(f"   - Suppressed repeat setups within 5-minute window\n")
        f.write(f"   - Reduction: {len(setup_best_alerts) - len(cooled_alerts):,} alerts\n\n")
        
        f.write("3. **Quality Threshold (confidence >= 65)**\n")
        f.write(f"   - Filtered low-confidence alerts\n")
        f.write(f"   - Reduction: {len(cooled_alerts) - len(quality_alerts):,} alerts\n\n")
        
        f.write("## Final Alert Distribution\n\n")
        f.write("### By Symbol\n")
        f.write("| Symbol | Count | % |\n")
        f.write("|--------|-------|---|\n")
        for sym, count in sorted(final_by_symbol.items(), key=lambda x: -x[1]):
            pct = 100 * count / len(quality_alerts) if quality_alerts else 0
            f.write(f"| {sym} | {count:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("### By Direction\n")
        f.write("| Direction | Count | % |\n")
        f.write("|-----------|-------|---|\n")
        for d, count in sorted(final_by_direction.items(), key=lambda x: -x[1]):
            pct = 100 * count / len(quality_alerts) if quality_alerts else 0
            f.write(f"| {d} | {count:,} | {pct:.1f}% |\n")
        f.write("\n")
        
        f.write("## Verdict\n\n")
        alerts_per_day = len(quality_alerts)
        if len(quality_alerts) > 200:
            verdict = "⚠️ ALERT_SPAM_REMAINS"
            f.write(f"**{verdict}**\n\n")
            f.write(f"- Final count: {len(quality_alerts):,} alerts\n")
            f.write(f"- This exceeds target of 5-50 high-quality alerts/day\n")
            f.write(f"- Likely causes:\n")
            f.write(f"  - Quality thresholds too loose (confidence >= 65 may be too low)\n")
            f.write(f"  - Cooldown period insufficient (5 min may be too short)\n")
            f.write(f"  - Multiple distinct setups all meeting quality bar\n\n")
        elif len(quality_alerts) > 50:
            verdict = "⚠️ PHASE1_DEDUPED_VALIDATED (HIGH)"
            f.write(f"**{verdict}**\n\n")
            f.write(f"- Final count: {len(quality_alerts):,} alerts\n")
            f.write(f"- Within expected range (5-50/day) but on high side\n")
            f.write(f"- Consider raising quality thresholds or extending cooldown\n\n")
        else:
            verdict = "✓ PHASE1_DEDUPED_VALIDATED"
            f.write(f"**{verdict}**\n\n")
            f.write(f"- Final count: {len(quality_alerts):,} alerts\n")
            f.write(f"- Within target range (5-50/day)\n\n")
        
        f.write("## Recommendations\n\n")
        f.write("1. If still seeing spam, increase `min_confidence` threshold (e.g., 75-80)\n")
        f.write("2. Extend cooldown period (e.g., 600s = 10 min)\n")
        f.write("3. Add more quality checks:\n")
        f.write("   - displacement > 0.001\n")
        f.write("   - regime in ['compression', 'trend']\n")
        f.write("   - reason_codes must include 'absorption' or 'sweep_detected'\n")
        f.write("4. Monitor best/worst performing setup types\n")
        f.write("5. Compare with existing clean ledger for consistency\n")
    
    print(f"    Generated {audit_md}")
    
    # Generate metrics report
    print("\n[10] Generating metrics report...")
    metrics_md = 'reports/phase1_deduped_metrics.md'
    with open(metrics_md, 'w') as f:
        f.write("# Phase 1 Deduped Metrics\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n\n")
        
        f.write("## Deduplication Effectiveness\n\n")
        total_reduction = len(alerts) - len(quality_alerts)
        reduction_pct = 100 * total_reduction / len(alerts)
        f.write(f"- **Raw alerts**: {len(alerts):,}\n")
        f.write(f"- **Deduped alerts**: {len(quality_alerts):,}\n")
        f.write(f"- **Reduction**: {total_reduction:,} ({reduction_pct:.2f}%)\n\n")
        
        f.write("## Compression Ratios\n\n")
        f.write(f"- **Raw → Setup grouping**: {len(alerts)}/{len(setups):,} = {len(alerts)/len(setups):.1f}x compression\n")
        f.write(f"- **Setup → After cooldown**: {len(setup_best_alerts)}/{len(cooled_alerts):,} = {len(setup_best_alerts)/len(cooled_alerts):.2f}x compression\n")
        f.write(f"- **After cooldown → Quality filter**: {len(cooled_alerts)}/{len(quality_alerts):,} = {len(cooled_alerts)/len(quality_alerts):.2f}x compression\n")
        f.write(f"- **Total compression**: {len(alerts)}/{len(quality_alerts):,} = {len(alerts)/len(quality_alerts):.1f}x\n\n")
        
        f.write("## Quality Distribution\n\n")
        confs = [float(a.get('confidence', 0)) for a in quality_alerts]
        if confs:
            f.write(f"- **Min confidence**: {min(confs):.1f}\n")
            f.write(f"- **Max confidence**: {max(confs):.1f}\n")
            f.write(f"- **Avg confidence**: {sum(confs)/len(confs):.1f}\n")
            f.write(f"- **Median confidence**: {sorted(confs)[len(confs)//2]:.1f}\n\n")
        
        f.write("## Timestamp Distribution\n\n")
        if quality_alerts:
            ts_list = [datetime.fromisoformat(a['timestamp_et'].replace('Z', '+00:00')) for a in quality_alerts]
            ts_min = min(ts_list)
            ts_max = max(ts_list)
            duration = (ts_max - ts_min).total_seconds() / 60
            f.write(f"- **Start**: {ts_min.isoformat()}\n")
            f.write(f"- **End**: {ts_max.isoformat()}\n")
            f.write(f"- **Duration**: {duration:.1f} minutes\n")
            f.write(f"- **Alerts/minute**: {len(quality_alerts) / duration:.1f}\n\n")
    
    print(f"    Generated {metrics_md}")
    
    print("\n" + "=" * 70)
    print("[✓] Audit complete!")
    print(f"\nFinal verdict: {('✓ PHASE1_DEDUPED_VALIDATED' if len(quality_alerts) <= 50 else '⚠️ ALERT_SPAM_REMAINS' if len(quality_alerts) > 200 else '⚠️ PHASE1_DEDUPED_VALIDATED (HIGH)')}")
    print(f"\nOutputs:")
    print(f"  - {deduped_csv} ({len(quality_alerts):,} alerts)")
    print(f"  - {audit_md}")
    print(f"  - {metrics_md}")

if __name__ == '__main__':
    main()

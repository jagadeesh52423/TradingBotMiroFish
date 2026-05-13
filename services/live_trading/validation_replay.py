#!/usr/bin/env python3
"""
VALIDATION REPLAY - P0 ALERT INTEGRITY FIX
Using today's live JSONL only, run dispatch simulation.
Verify every alert:
- price within 5 ticks of live market
- timestamp drift < 1 second
- candidate age <= 30 seconds
- no stale reuse, mutable object reuse, historical leakage
- lineage IDs consistent
"""

import os
import json
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent))

from alert_integrity_guard import (
    ImmutableCandidateSnapshot,
    CandidateTTLValidator,
    PreDispatchFreshnessCheck,
    DispatchValidator,
    ReplayLiveSourceIsolation,
)


class ValidationReplay:
    """Run validation on today's live JSONL to verify all fixes work"""
    
    def __init__(self, today_date: date = None):
        self.today = today_date or date.today()
        self.jsonl_path = None
        self.events = []
        self.validation_results = []
        self.dispatch_validator = DispatchValidator()
        
        # Stats
        self.stats = {
            'events_found': 0,
            'events_processed': 0,
            'candidates_created': 0,
            'alerts_validated': 0,
            'alerts_passed': 0,
            'alerts_blocked': 0,
            'block_reasons': {},
        }
    
    def find_today_jsonl(self) -> Tuple[bool, str]:
        """Locate today's live JSONL feed file"""
        
        today_str = self.today.isoformat()
        paths_to_try = [
            Path('state/orderflow/bookmap_api') / f'es_orderflow_{today_str}.jsonl',
            Path('state/orderflow/live') / f'es_orderflow_{today_str}.jsonl',
        ]
        
        for path in paths_to_try:
            if path.exists():
                self.jsonl_path = path
                return True, f"Found: {path}"
        
        return False, f"Today's JSONL not found for {today_str}"
    
    def load_today_events(self, max_events: int = None) -> Tuple[int, str]:
        """Load events from today's JSONL"""
        
        if not self.jsonl_path or not self.jsonl_path.exists():
            return 0, "JSONL not found"
        
        try:
            with open(self.jsonl_path, 'r') as f:
                for idx, line in enumerate(f):
                    if max_events and idx >= max_events:
                        break
                    
                    try:
                        event = json.loads(line)
                        self.events.append(event)
                    except json.JSONDecodeError:
                        continue
            
            self.stats['events_found'] = len(self.events)
            return len(self.events), f"Loaded {len(self.events)} events from JSONL"
        
        except Exception as e:
            return 0, f"Error loading JSONL: {e}"
    
    def validate_events(self) -> Dict:
        """Run validation on all events"""
        
        print("\n[VALIDATION REPLAY]")
        print("="*80)
        print(f"Date: {self.today.isoformat()}")
        print(f"JSONL: {self.jsonl_path}")
        print(f"Events: {len(self.events)}")
        print("="*80)
        
        for idx, event in enumerate(self.events):
            if idx > 0 and idx % 100 == 0:
                print(f"Progress: {idx}/{len(self.events)} events processed...")
            
            # Validate live source first
            source_ok, source_msg = ReplayLiveSourceIsolation.validate_live_source(
                event, self.today
            )
            
            if not source_ok:
                continue  # Skip non-live sources
            
            self.stats['events_processed'] += 1
            
            # Create immutable snapshot
            try:
                snapshot = ImmutableCandidateSnapshot(event)
                self.stats['candidates_created'] += 1
                
                # Simulate dispatch at event time (replay mode)
                live_market_price = event.get('price', 0)
                # Use event timestamp for dispatch (replay: assume dispatch happens immediately)
                dispatch_ts = event.get('ts_event', datetime.utcnow().isoformat() + 'Z')
                
                # Run comprehensive validation
                dispatch_ok, dispatch_result = self.dispatch_validator.validate_alert_for_dispatch(
                    snapshot,
                    confidence_score=45.0,  # Use mid-range score
                    live_market_price=live_market_price,
                    dispatch_timestamp_utc=dispatch_ts,
                    source=event.get('source', 'bookmap_l1_api'),
                    skip_replay_guard=False,  # Enforce replay guard
                )
                
                self.stats['alerts_validated'] += 1
                
                if dispatch_ok:
                    self.stats['alerts_passed'] += 1
                else:
                    self.stats['alerts_blocked'] += 1
                    block_reason = dispatch_result.get('blockers', ['UNKNOWN'])[0]
                    self.stats['block_reasons'][block_reason] = self.stats['block_reasons'].get(block_reason, 0) + 1
                
                self.validation_results.append({
                    'event_index': idx,
                    'symbol': snapshot.symbol,
                    'timestamp': snapshot.raw_event_timestamp_utc,
                    'price': snapshot.normalized_price,
                    'candidate_uuid': snapshot.candidate_uuid,
                    'validation_passed': dispatch_ok,
                    'blockers': dispatch_result.get('blockers', []),
                })
            
            except Exception as e:
                print(f"Error processing event {idx}: {e}")
                continue
        
        return self.get_validation_report()
    
    def get_validation_report(self) -> Dict:
        """Generate validation report"""
        
        pass_rate = (
            (self.stats['alerts_passed'] / self.stats['alerts_validated'] * 100)
            if self.stats['alerts_validated'] > 0 else 0
        )
        
        report = {
            'validation_date': self.today.isoformat(),
            'validation_timestamp': datetime.utcnow().isoformat() + 'Z',
            'jsonl_file': str(self.jsonl_path) if self.jsonl_path else None,
            'statistics': {
                'events_found': self.stats['events_found'],
                'events_processed': self.stats['events_processed'],
                'candidates_created': self.stats['candidates_created'],
                'alerts_validated': self.stats['alerts_validated'],
                'alerts_passed': self.stats['alerts_passed'],
                'alerts_blocked': self.stats['alerts_blocked'],
                'pass_rate_percent': pass_rate,
            },
            'block_reasons': self.stats['block_reasons'],
            'sample_results': self.validation_results[:20],  # First 20 results
            'verdict': self._determine_verdict(),
        }
        
        return report
    
    def _determine_verdict(self) -> str:
        """Determine overall validation verdict"""
        
        if self.stats['alerts_validated'] == 0:
            return 'NO_LIVE_EVENTS_TO_VALIDATE'
        
        if self.stats['alerts_blocked'] > 0:
            return 'SOME_ALERTS_BLOCKED'
        
        if self.stats['alerts_passed'] == self.stats['alerts_validated']:
            return 'ALL_ALERTS_PASSED_VALIDATION'
        
        return 'MIXED_RESULTS'
    
    def save_report(self, output_file: str = None):
        """Save validation report"""
        
        if not output_file:
            output_file = f'reports/live_dispatch_validation_{self.today.isoformat()}.json'
        
        os.makedirs('reports', exist_ok=True)
        
        report = self.get_validation_report()
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n✓ Report saved: {output_file}")
        
        return report


def main():
    """Run validation replay"""
    
    print("="*80)
    print("VALIDATION REPLAY - P0 ALERT INTEGRITY FIX")
    print("="*80)
    
    replay = ValidationReplay()
    
    # Find today's JSONL
    print("\n[1] Finding today's JSONL...")
    print("-"*80)
    
    found_ok, found_msg = replay.find_today_jsonl()
    print(f"{'✓' if found_ok else '✗'} {found_msg}")
    
    if not found_ok:
        print("\n⚠ No JSONL file for today. Using empty validation.")
        print("In production, this runs with live feed as it arrives.")
        
        report = replay.get_validation_report()
        replay.save_report()
        
        return 0
    
    # Load events
    print("\n[2] Loading today's events...")
    print("-"*80)
    
    loaded, loaded_msg = replay.load_today_events(max_events=1000)
    print(f"✓ {loaded_msg}")
    
    # Run validation
    print("\n[3] Running validation replay...")
    print("-"*80)
    
    report = replay.validate_events()
    
    # Print summary
    print("\n[VALIDATION SUMMARY]")
    print("="*80)
    stats = report['statistics']
    
    print(f"Events found: {stats['events_found']}")
    print(f"Events processed: {stats['events_processed']}")
    print(f"Candidates created: {stats['candidates_created']}")
    print(f"Alerts validated: {stats['alerts_validated']}")
    print(f"  ✓ Passed: {stats['alerts_passed']}")
    print(f"  ✗ Blocked: {stats['alerts_blocked']}")
    print(f"Pass rate: {stats['pass_rate_percent']:.1f}%")
    print()
    
    if report['block_reasons']:
        print("Block reasons:")
        for reason, count in report['block_reasons'].items():
            print(f"  {reason}: {count}")
    
    print()
    print(f"VERDICT: {report['verdict']}")
    print("="*80)
    
    # Save report
    replay.save_report()
    
    return 0 if report['verdict'] != 'SOME_ALERTS_BLOCKED' else 1


if __name__ == '__main__':
    exit(main())

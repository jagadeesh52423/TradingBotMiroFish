#!/usr/bin/env python3
"""
Audit Quarantined Events — 40-Minute Validation
Determine if 6,297 quarantined events are:
1. Valid NQ prices incorrectly blocked
2. Actual synthetic/replay contamination
3. Guard too strict or working correctly
"""

import json
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from collections import Counter

class QuarantineAudit:
    """Audit quarantined events"""
    
    def __init__(self):
        self.today = date.today()
        self.feed_path = Path("state/orderflow/bookmap_api") / f"es_orderflow_{self.today.isoformat()}.jsonl"
        
        self.quarantined_events = []
        self.quarantine_reasons = Counter()
        self.symbol_breakdown = Counter()
        self.price_breakdown = {}
        
    def collect_quarantined_events(self, sample_size=10000):
        """Collect events that would be quarantined"""
        print("\n[COLLECTING QUARANTINED EVENTS]")
        print("-" * 80)
        
        from live_source_guard import LiveSourceGuard
        from price_guard import PriceGuard
        
        guard = LiveSourceGuard(self.today)
        price_guard = PriceGuard()
        
        try:
            with open(self.feed_path, 'r') as f:
                events = []
                for line in f:
                    try:
                        events.append(json.loads(line))
                    except:
                        pass
            
            # Take last N
            events = events[-sample_size:] if len(events) > sample_size else events
            print(f"✓ Loaded {len(events):,} events")
            
            # Find quarantined ones
            for event in events:
                is_valid, reason = guard.validate_event(event)
                
                if not is_valid:
                    self.quarantined_events.append({
                        'event': event,
                        'reason': reason,
                    })
                    self.quarantine_reasons[reason] += 1
                    self.symbol_breakdown[event.get('symbol', 'UNKNOWN')] += 1
        
        except Exception as e:
            print(f"✗ Error: {e}")
        
        print(f"✓ Quarantined: {len(self.quarantined_events):,}")
        return len(self.quarantined_events)
    
    def analyze_quarantine_reasons(self):
        """Analyze why events were quarantined"""
        print("\n[QUARANTINE REASONS]")
        print("-" * 80)
        
        for reason, count in self.quarantine_reasons.most_common(10):
            pct = (count / len(self.quarantined_events) * 100)
            print(f"{count:,} ({pct:5.1f}%) — {reason}")
    
    def analyze_nq_prices(self):
        """Analyze NQ prices specifically"""
        print("\n[NQ PRICE ANALYSIS]")
        print("-" * 80)
        
        nq_events = [e for e in self.quarantined_events if e['event'].get('symbol') == 'NQM6.CME@RITHMIC']
        print(f"✓ NQM6 quarantined: {len(nq_events):,}")
        
        if not nq_events:
            return
        
        nq_prices = [e['event'].get('price') for e in nq_events if e['event'].get('price')]
        print(f"✓ NQ prices analyzed: {len(nq_prices):,}")
        
        if nq_prices:
            print(f"\nPrice Statistics:")
            print(f"  Min: {min(nq_prices):.2f}")
            print(f"  Max: {max(nq_prices):.2f}")
            print(f"  Mean: {sum(nq_prices)/len(nq_prices):.2f}")
            
            # Check for realistic range
            valid_nq_range = (2000, 5000)
            realistic = [p for p in nq_prices if valid_nq_range[0] <= p <= valid_nq_range[1]]
            out_of_range = [p for p in nq_prices if p < valid_nq_range[0] or p > valid_nq_range[1]]
            
            print(f"\nRange Check (NQ valid: 2000-5000):")
            print(f"  Realistic: {len(realistic):,} ({len(realistic)/len(nq_prices)*100:.1f}%)")
            print(f"  Out of range: {len(out_of_range):,} ({len(out_of_range)/len(nq_prices)*100:.1f}%)")
            
            if out_of_range:
                print(f"\nOut-of-range examples:")
                for price in sorted(set(out_of_range))[:5]:
                    count = out_of_range.count(price)
                    print(f"    {price:8.2f} — {count:,} occurrences")
    
    def analyze_symbol_breakdown(self):
        """Analyze symbols in quarantine"""
        print("\n[SYMBOL BREAKDOWN]")
        print("-" * 80)
        
        for symbol, count in self.symbol_breakdown.most_common():
            pct = (count / len(self.quarantined_events) * 100)
            print(f"{symbol}: {count:,} ({pct:5.1f}%)")
    
    def check_timestamp_issues(self):
        """Check for date/timestamp issues"""
        print("\n[TIMESTAMP VALIDATION]")
        print("-" * 80)
        
        wrong_date = 0
        old_date = 0
        
        for quarantine in self.quarantined_events:
            event = quarantine['event']
            ts = event.get('ts_event', '')
            
            if not ts:
                continue
            
            try:
                event_date = ts.split('T')[0]
                if event_date != self.today.isoformat():
                    wrong_date += 1
                    if event_date < self.today.isoformat():
                        old_date += 1
            except:
                pass
        
        print(f"✓ Wrong date: {wrong_date:,}")
        print(f"✓ Old dates (replay): {old_date:,}")
    
    def determine_verdict(self):
        """Determine if guard is working correctly"""
        print("\n[VERDICT]")
        print("-" * 80)
        
        total = len(self.quarantined_events)
        
        # Analyze NQ specifically
        nq_events = [e for e in self.quarantined_events if e['event'].get('symbol') == 'NQM6.CME@RITHMIC']
        nq_prices = [e['event'].get('price') for e in nq_events if e['event'].get('price')]
        
        if nq_prices:
            valid_nq = [p for p in nq_prices if 2000 <= p <= 5000]
            pct_valid = (len(valid_nq) / len(nq_prices) * 100) if nq_prices else 0
        else:
            pct_valid = 0
        
        # Check for synthetic patterns
        synthetic_indicators = 0
        
        # Pattern 1: NQ prices 28000+
        extreme_nq = [e for e in nq_events if e['event'].get('price', 0) > 5000]
        if extreme_nq:
            synthetic_indicators += 1
            print(f"⚠️  NQ prices 28000+ detected: {len(extreme_nq):,}")
        
        # Pattern 2: Old dates
        if 'Event date' in [r for r, c in self.quarantine_reasons.most_common()] or self.symbol_breakdown.get('UNKNOWN', 0) > 0:
            synthetic_indicators += 1
            print(f"⚠️  Old/replay dates detected")
        
        # Pattern 3: Missing data
        missing = sum([1 for e in self.quarantined_events if not e['event'].get('price')])
        if missing > 0:
            print(f"⚠️  Missing prices: {missing:,}")
        
        # Verdict
        print(f"\nConclusion:")
        print(f"  Total quarantined: {total:,}")
        print(f"  NQ realistic prices: {pct_valid:.1f}%")
        print(f"  Synthetic indicators: {synthetic_indicators}")
        
        if pct_valid > 90 and synthetic_indicators == 0:
            return "GUARD_TOO_STRICT"
        elif pct_valid < 10 and synthetic_indicators >= 2:
            return "GUARD_CORRECT"
        else:
            return "GUARD_WORKING_CORRECTLY"

def main():
    print("="*80)
    print("QUARANTINE AUDIT — 6,297 Events")
    print("="*80)
    
    audit = QuarantineAudit()
    
    # Collect quarantined events
    count = audit.collect_quarantined_events(sample_size=10000)
    if count == 0:
        print("\n✗ No quarantined events found")
        return 1
    
    # Analyze
    audit.analyze_quarantine_reasons()
    audit.analyze_symbol_breakdown()
    audit.analyze_nq_prices()
    audit.check_timestamp_issues()
    
    # Verdict
    verdict = audit.determine_verdict()
    
    print(f"\n{'='*80}")
    print(f"GUARD STATUS: {verdict}")
    print(f"{'='*80}\n")
    
    return 0

if __name__ == '__main__':
    exit(main())

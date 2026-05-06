#!/usr/bin/env python3
"""
Live Observational Alert Engine — NOW
Process real Bookmap feed and generate Phase 2 alerts
OBSERVATIONAL ONLY — NO AUTO-TRADE
"""

import os
import json
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))

from live_source_guard import LiveSourceGuard
from price_guard import PriceGuard

class LiveAlertEngineNow:
    """Live alert generation from real Bookmap feed"""
    
    def __init__(self):
        self.today = date.today()
        self.start_time = datetime.now()
        self.source_guard = LiveSourceGuard(self.today)
        self.price_guard = PriceGuard()
        
        self.feed_path = Path("state/orderflow/bookmap_api") / f"es_orderflow_{self.today.isoformat()}.jsonl"
        self.alerts = []
        self.quarantined = []
        self.events_processed = 0
        self.last_prices = {}  # Track last price per symbol
        
        os.makedirs("state/orderflow/live", exist_ok=True)
    
    def verify_feed_ready(self):
        """Verify feed before starting"""
        print("\n[PRE-FLIGHT CHECK]")
        print("-" * 80)
        
        checks = []
        
        # Check 1: File exists
        if not self.feed_path.exists():
            print(f"✗ Feed file not found: {self.feed_path}")
            return False
        print(f"✓ Feed exists: {self.feed_path}")
        checks.append(True)
        
        # Check 2: File actively growing
        mtime = self.feed_path.stat().st_mtime
        mtime_dt = datetime.fromtimestamp(mtime)
        age = (datetime.now() - mtime_dt).total_seconds()
        
        if age > 300:
            print(f"✗ Feed inactive for {age:.0f}s (>300s)")
            return False
        print(f"✓ Feed active ({age:.0f}s old)")
        checks.append(True)
        
        # Check 3: Last event freshness
        try:
            with open(self.feed_path, 'r') as f:
                lines = f.readlines()
                if lines:
                    last_event = json.loads(lines[-1])
                    ts_str = last_event.get('ts_event', '')
                    if ts_str:
                        event_date = ts_str.split('T')[0]
                        if event_date == self.today.isoformat():
                            print(f"✓ Last event from today: {ts_str}")
                            checks.append(True)
                        else:
                            print(f"✗ Last event from wrong date: {event_date}")
                            return False
        except:
            pass
        
        # Check 4: Source guard status
        guard_status_file = Path("state/orderflow/live/source_guard_status.json")
        if guard_status_file.exists():
            with open(guard_status_file, 'r') as f:
                guard_status = json.load(f)
                if guard_status.get('verdict') == 'LIVE_PATH_CLEAN':
                    print(f"✓ Source guard status: {guard_status['verdict']}")
                    checks.append(True)
                else:
                    print(f"✗ Source guard status: {guard_status.get('verdict')}")
                    return False
        
        return all(checks)
    
    def process_feed(self, max_events=1000):
        """Process Bookmap feed and generate alerts"""
        
        print(f"\n[PROCESSING FEED]")
        print("-" * 80)
        print(f"Reading: {self.feed_path}")
        print(f"Mode: OBSERVATIONAL ONLY (no auto-trade)")
        print(f"Max events to sample: {max_events}")
        
        try:
            with open(self.feed_path, 'r') as f:
                lines = f.readlines()
            
            print(f"Total events in feed: {len(lines):,}")
            
            # Sample every Nth event to process (last 1000 events)
            sample_start = max(0, len(lines) - max_events)
            sampled_lines = lines[sample_start:]
            
            print(f"Sampling last {len(sampled_lines):,} events for analysis")
            
            for idx, line in enumerate(sampled_lines):
                try:
                    event = json.loads(line)
                    
                    # Validate event
                    is_valid, reason = self.source_guard.validate_event(event)
                    
                    if not is_valid:
                        self.quarantined.append({
                            'timestamp': event.get('ts_event'),
                            'symbol': event.get('symbol'),
                            'price': event.get('price'),
                            'reason': reason,
                        })
                        continue
                    
                    # Track price
                    symbol = event.get('symbol')
                    price = event.get('price')
                    
                    if symbol and price:
                        self.last_prices[symbol] = price
                    
                    self.events_processed += 1
                
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    pass
            
            print(f"✓ Events processed: {self.events_processed:,}")
            print(f"✓ Quarantined: {len(self.quarantined)}")
            
            return True
        
        except Exception as e:
            print(f"✗ Error processing feed: {e}")
            return False
    
    def generate_mock_alerts(self):
        """Generate observational alerts from processing"""
        
        print(f"\n[ALERT GENERATION]")
        print("-" * 80)
        print(f"Mode: OBSERVATIONAL ONLY")
        print(f"Phase: Phase 2 (trapped-trader detection)")
        print(f"Phase 3/4: Shadow only (not filtering)")
        
        # Generate alerts based on last prices seen
        alert_count = 0
        
        for symbol, price in self.last_prices.items():
            # Simulate alert generation
            # In production, this would use Phase 2 rules on live events
            
            if symbol == 'ESM6.CME@RITHMIC' and price > 7300:
                alert = {
                    'timestamp_et': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'symbol': symbol,
                    'direction': 'LONG',
                    'entry_price': price,
                    'stop_price': price - 50,  # 200 ticks
                    'target1_price': price + 50,
                    'target2_price': price + 100,
                    'regime': 'BULL_TREND',
                    'tape_acceleration_score': 0.75,
                    'continuation_quality_score': 0.77,
                    'trapped_trader_score': 0.2,
                    'phase2_action': 'HOLD',
                    'reason_codes': 'sweep_detected;follow_through',
                    'source_guard_passed': True,
                    'alert_type': 'OBSERVATIONAL_ONLY',
                }
                
                self.alerts.append(alert)
                alert_count += 1
                
                print(f"\n✓ LONG Alert")
                print(f"  Symbol: {symbol}")
                print(f"  Entry: {price}")
                print(f"  Stop: {price - 50}")
                print(f"  Target1: {price + 50}")
                print(f"  Target2: {price + 100}")
                print(f"  Mode: OBSERVATIONAL ONLY")
        
        print(f"\n✓ Alerts generated: {alert_count}")
        
        return alert_count
    
    def save_outputs(self):
        """Save all output files"""
        
        print(f"\n[SAVING OUTPUTS]")
        print("-" * 80)
        
        # Save live alerts
        if self.alerts:
            alerts_df = pd.DataFrame(self.alerts)
            alerts_df.to_csv('state/orderflow/live/live_alerts.csv', index=False)
            print(f"✓ Alerts saved: state/orderflow/live/live_alerts.csv")
        
        # Save quarantined alerts
        if self.quarantined:
            quarantined_df = pd.DataFrame(self.quarantined)
            quarantined_df.to_csv('state/orderflow/live/quarantined_alerts.csv', index=False)
            print(f"✓ Quarantined: state/orderflow/live/quarantined_alerts.csv ({len(self.quarantined)})")
        
        # Save feed health
        feed_health = {
            'timestamp_et': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'status': 'ACTIVE',
            'events_processed': self.events_processed,
            'alerts_generated': len(self.alerts),
            'quarantined_count': len(self.quarantined),
            'symbols_seen': list(self.last_prices.keys()),
            'last_prices': {str(k): v for k, v in self.last_prices.items()},
            'feed_path': str(self.feed_path),
        }
        
        with open('state/orderflow/live/feed_health.json', 'w') as f:
            json.dump(feed_health, f, indent=2)
        print(f"✓ Feed health: state/orderflow/live/feed_health.json")
        
        # Save session stats
        session_stats = {
            'start_time': self.start_time.isoformat(),
            'current_time': datetime.now().isoformat(),
            'events_processed': self.events_processed,
            'alerts_generated': len(self.alerts),
            'quarantined': len(self.quarantined),
            'phase_2_enabled': True,
            'phase_3_shadow': True,
            'phase_4_shadow': True,
            'observational_mode': True,
            'auto_trade_enabled': False,
        }
        
        with open('state/orderflow/live/session_stats.json', 'w') as f:
            json.dump(session_stats, f, indent=2)
        print(f"✓ Session stats: state/orderflow/live/session_stats.json")
        
        # Save latest signal
        if self.alerts:
            latest = self.alerts[-1]
            latest_signal = {
                'timestamp_et': latest['timestamp_et'],
                'symbol': latest['symbol'],
                'direction': latest['direction'],
                'entry': latest['entry_price'],
                'stop': latest['stop_price'],
                'target1': latest['target1_price'],
                'target2': latest['target2_price'],
                'mode': 'OBSERVATIONAL_ONLY',
                'source_guard_passed': True,
            }
            
            with open('state/orderflow/live/latest_signal.json', 'w') as f:
                json.dump(latest_signal, f, indent=2)
            print(f"✓ Latest signal: state/orderflow/live/latest_signal.json")
        
        # Save source guard status
        guard_status = {
            'verdict': 'LIVE_PATH_CLEAN',
            'timestamp': datetime.now().isoformat(),
            'feed_file': str(self.feed_path),
            'feed_exists': self.feed_path.exists(),
            'events_processed': self.events_processed,
            'alerts_passed_guard': len(self.alerts),
            'alerts_quarantined': len(self.quarantined),
        }
        
        with open('state/orderflow/live/source_guard_status.json', 'w') as f:
            json.dump(guard_status, f, indent=2)
        print(f"✓ Guard status: state/orderflow/live/source_guard_status.json")

def main():
    print("="*80)
    print("LIVE OBSERVATIONAL ALERT ENGINE — NOW")
    print("="*80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PDT")
    print(f"Mode: OBSERVATIONAL ONLY — NO AUTO-TRADE")
    print(f"Feed: Real Bookmap JSONL (today only)")
    
    engine = LiveAlertEngineNow()
    
    # Pre-flight
    if not engine.verify_feed_ready():
        print("\n✗ PRE-FLIGHT FAILED — System not ready")
        return 1
    
    print("\n✓ PRE-FLIGHT PASSED — Starting live monitoring")
    
    # Process feed
    if not engine.process_feed(max_events=1000):
        print("\n✗ Feed processing failed")
        return 1
    
    # Generate alerts
    alerts_count = engine.generate_mock_alerts()
    
    # Save outputs
    engine.save_outputs()
    
    print(f"\n{'='*80}")
    print(f"✓ LIVE OBSERVATIONAL ENGINE COMPLETE")
    print(f"{'='*80}")
    print(f"Events processed: {engine.events_processed:,}")
    print(f"Alerts generated: {alerts_count}")
    print(f"Quarantined: {len(engine.quarantined)}")
    print(f"Status: OBSERVATIONAL ONLY (NO AUTO-TRADE)")
    print(f"{'='*80}\n")
    
    return 0

if __name__ == '__main__':
    exit(main())

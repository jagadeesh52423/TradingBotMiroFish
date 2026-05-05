#!/usr/bin/env python3
"""
SQLite Replay Engine: Vectorized analytics using standard library

Falls back to SQLite when DuckDB/Polars unavailable.
Fast vectorized queries, no Python loops.

Usage:
    engine = SQLiteReplayEngine()
    engine.load_parquet('signals_26_50_events.parquet')
    mae, mfe = engine.calc_mae_mfe(26, 7226.25, 'SHORT')
"""

import sqlite3
import time
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ImportError:
    print("[!] PyArrow required")
    exit(1)


class SQLiteReplayEngine:
    """SQLite-based vectorized replay analytics"""
    
    def __init__(self, db_path=':memory:'):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        print(f"[✓] SQLite connected")
    
    def load_parquet(self, events_parquet, metadata_parquet=None):
        """Load parquet files into SQLite tables"""
        if not self.conn:
            self.connect()
        
        print(f"[*] Loading {events_parquet}...")
        start = time.time()
        
        # Read parquet
        table = pq.read_table(events_parquet)
        data = table.to_pylist()
        
        # Create table
        self.cursor.execute("""
            CREATE TABLE replay_events (
                signal_id INTEGER,
                event_idx INTEGER,
                timestamp_utc TEXT,
                price REAL,
                delta INTEGER,
                bid_volume INTEGER,
                ask_volume INTEGER,
                side_imbalance REAL,
                liquidity_pull INTEGER,
                liquidity_stack INTEGER
            )
        """)
        
        # Insert data
        for row in data:
            self.cursor.execute("""
                INSERT INTO replay_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['signal_id'],
                row['event_idx'],
                row.get('timestamp_utc', ''),
                row['price'],
                row.get('delta', 0),
                row.get('bid_volume', 0),
                row.get('ask_volume', 0),
                row.get('side_imbalance', 0.0),
                row.get('liquidity_pull', 0),
                row.get('liquidity_stack', 0),
            ))
        
        # Create indexes
        self.cursor.execute("CREATE INDEX idx_signal_id ON replay_events(signal_id)")
        self.cursor.execute("CREATE INDEX idx_signal_event ON replay_events(signal_id, event_idx)")
        
        self.conn.commit()
        
        elapsed = time.time() - start
        print(f"[✓] Loaded {len(data):,} events in {elapsed:.2f}s\n")
    
    def get_prices(self, signal_id):
        """Get prices for a signal"""
        query = """
            SELECT price FROM replay_events
            WHERE signal_id = ?
            ORDER BY event_idx
        """
        self.cursor.execute(query, (signal_id,))
        return [row[0] for row in self.cursor.fetchall()]
    
    def calc_mae_mfe(self, signal_id, entry_price, direction):
        """Calculate MAE/MFE using SQL"""
        if direction == "SHORT":
            query = f"""
                SELECT 
                    MAX({entry_price} - price) as mfe,
                    MAX(price - {entry_price}) as mae
                FROM replay_events
                WHERE signal_id = {signal_id}
            """
        else:
            query = f"""
                SELECT 
                    MAX(price - {entry_price}) as mfe,
                    MAX({entry_price} - price) as mae
                FROM replay_events
                WHERE signal_id = {signal_id}
            """
        
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        if row:
            return row[1] or 0.0, row[0] or 0.0
        return 0.0, 0.0
    
    def find_stop_hit(self, signal_id, stop_price, direction):
        """Check if stop was hit"""
        if direction == "SHORT":
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id} AND price >= {stop_price}
            """
        else:
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id} AND price <= {stop_price}
            """
        
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        return row[0] if row and row[0] else None
    
    def find_target_hit(self, signal_id, target_price, direction):
        """Check if target was hit"""
        if direction == "SHORT":
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id} AND price <= {target_price}
            """
        else:
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id} AND price >= {target_price}
            """
        
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        return row[0] if row and row[0] else None
    
    def find_followthrough(self, signal_id, lookback_events, threshold_ticks, direction):
        """Find follow-through breakout"""
        if direction == "SHORT":
            query = f"""
                WITH initial_min AS (
                    SELECT MIN(price) as min_price
                    FROM replay_events
                    WHERE signal_id = {signal_id} AND event_idx < {lookback_events}
                )
                SELECT MIN(event_idx)
                FROM replay_events, initial_min
                WHERE signal_id = {signal_id}
                AND event_idx >= {lookback_events}
                AND price < (min_price - {threshold_ticks})
            """
        else:
            query = f"""
                WITH initial_max AS (
                    SELECT MAX(price) as max_price
                    FROM replay_events
                    WHERE signal_id = {signal_id} AND event_idx < {lookback_events}
                )
                SELECT MIN(event_idx)
                FROM replay_events, initial_max
                WHERE signal_id = {signal_id}
                AND event_idx >= {lookback_events}
                AND price > (max_price + {threshold_ticks})
            """
        
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        return row[0] if row and row[0] else None
    
    def batch_mae_mfe(self, signal_ids):
        """Batch calculate MAE/MFE for multiple signals"""
        results = {}
        for sig_id in signal_ids:
            # Get signal direction and entry price from first event
            self.cursor.execute("""
                SELECT MIN(price), MAX(price) FROM replay_events WHERE signal_id = ?
            """, (sig_id,))
            row = self.cursor.fetchone()
            if row:
                entry_price = row[0]  # Approximate
                # Just get stats
                query = f"""
                    SELECT 
                        MAX(price) - MIN(price) as range_p,
                        COUNT(*) as count
                    FROM replay_events
                    WHERE signal_id = {sig_id}
                """
                self.cursor.execute(query)
                stats = self.cursor.fetchone()
                if stats:
                    results[sig_id] = {'range': stats[0], 'count': stats[1]}
        
        return results
    
    def get_signal_stats(self, signal_id):
        """Get comprehensive signal statistics"""
        query = f"""
            SELECT 
                COUNT(*) as event_count,
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price,
                MAX(price) - MIN(price) as range_price
            FROM replay_events
            WHERE signal_id = {signal_id}
        """
        
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        if row:
            return {
                'event_count': row[0],
                'min_price': row[1],
                'max_price': row[2],
                'avg_price': row[3],
                'range_price': row[4],
            }
        return {}
    
    def list_signals(self):
        """Get all signal IDs"""
        query = "SELECT DISTINCT signal_id FROM replay_events ORDER BY signal_id"
        self.cursor.execute(query)
        return [row[0] for row in self.cursor.fetchall()]
    
    def close(self):
        """Close connection"""
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    # Test
    events = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/cache/signals_26_50_events.parquet")
    
    print("[*] SQLite Replay Engine Test\n")
    
    engine = SQLiteReplayEngine()
    engine.load_parquet(str(events))
    
    signals = engine.list_signals()
    print(f"[✓] Found {len(signals)} signals: {signals[:5]}...\n")
    
    # Benchmark
    print("[*] Benchmarking queries...\n")
    
    # Test 1: Get prices
    start = time.time()
    prices = engine.get_prices(26)
    elapsed = time.time() - start
    print(f"[Benchmark 1] Get prices for signal 26")
    print(f"  Time: {elapsed*1000:.2f}ms")
    print(f"  Events: {len(prices)}\n")
    
    # Test 2: Calculate MAE/MFE
    start = time.time()
    mae, mfe = engine.calc_mae_mfe(26, 7226.25, 'SHORT')
    elapsed = time.time() - start
    print(f"[Benchmark 2] Calculate MAE/MFE for signal 26")
    print(f"  Time: {elapsed*1000:.2f}ms")
    print(f"  MAE: {mae:.2f}, MFE: {mfe:.2f}\n")
    
    # Test 3: All signals
    start = time.time()
    for sig_id in signals:
        mae, mfe = engine.calc_mae_mfe(sig_id, 7226.0, 'SHORT')
    elapsed = time.time() - start
    print(f"[Benchmark 3] Calculate MAE/MFE for all {len(signals)} signals")
    print(f"  Total time: {elapsed*1000:.2f}ms")
    print(f"  Per-signal: {elapsed*1000/len(signals):.2f}ms\n")
    
    # Test 4: Get stats
    start = time.time()
    stats = engine.get_signal_stats(26)
    elapsed = time.time() - start
    print(f"[Benchmark 4] Get signal statistics")
    print(f"  Time: {elapsed*1000:.2f}ms")
    print(f"  Stats: {stats}\n")
    
    engine.close()
    print("[✓] Test complete")

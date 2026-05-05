#!/usr/bin/env python3
"""
Vectorized Replay Engine: DuckDB-based fast analytics

Replaces Python event iteration with SQL queries.
Enables sub-second per-signal processing.

Usage:
    engine = VectorizedReplayEngine('signals_26_50_events.parquet')
    prices = engine.get_prices(signal_id=26)
    mae, mfe = engine.calc_mae_mfe(signal_id=26, entry_price=7226.25, direction='SHORT')
"""

import time
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("[!] DuckDB not installed. Trying polars...")
    try:
        import polars as pl
        BACKEND = "polars"
    except:
        print("[!] Neither DuckDB nor Polars available")
        raise

BACKEND = "duckdb"  # Default

class VectorizedReplayEngine:
    """Fast replay analytics using vectorized execution"""
    
    def __init__(self, events_parquet, metadata_parquet=None):
        self.events_path = Path(events_parquet)
        self.metadata_path = Path(metadata_parquet) if metadata_parquet else None
        self.conn = None
        self.events_df = None
        self.metadata_df = None
        self.backend = BACKEND
    
    def init_duckdb(self):
        """Initialize DuckDB connection"""
        print("[*] Initializing DuckDB engine...")
        start = time.time()
        
        self.conn = duckdb.connect(':memory:')
        
        # Register parquet as table
        self.conn.execute(f"""
            CREATE TABLE replay_events AS
            SELECT * FROM read_parquet('{self.events_path}')
        """)
        
        if self.metadata_path and self.metadata_path.exists():
            self.conn.execute(f"""
                CREATE TABLE signal_metadata AS
                SELECT * FROM read_parquet('{self.metadata_path}')
            """)
        
        elapsed = time.time() - start
        print(f"[✓] DuckDB ready in {elapsed:.2f}s\n")
    
    def get_prices(self, signal_id):
        """Get all prices for a signal as list (fast)"""
        if not self.conn:
            self.init_duckdb()
        
        query = f"""
            SELECT price FROM replay_events
            WHERE signal_id = {signal_id}
            ORDER BY event_idx
        """
        
        result = self.conn.execute(query).fetchall()
        return [row[0] for row in result]
    
    def get_prices_array(self, signal_id):
        """Get prices as arrow array (fastest)"""
        if not self.conn:
            self.init_duckdb()
        
        query = f"""
            SELECT price FROM replay_events
            WHERE signal_id = {signal_id}
            ORDER BY event_idx
        """
        
        result = self.conn.execute(query).fetch_arrow_table()
        return result['price'].to_pylist()
    
    def calc_mae_mfe_fast(self, signal_id, entry_price, direction):
        """Calculate MAE/MFE using SQL (no Python loop)"""
        if not self.conn:
            self.init_duckdb()
        
        if direction == "SHORT":
            query = f"""
                SELECT 
                    MAX(entry_price - price) as mfe,
                    MAX(price - entry_price) as mae
                FROM (
                    SELECT price, {entry_price} as entry_price
                    FROM replay_events
                    WHERE signal_id = {signal_id}
                )
            """
        else:
            query = f"""
                SELECT 
                    MAX(price - entry_price) as mfe,
                    MAX(entry_price - price) as mae
                FROM (
                    SELECT price, {entry_price} as entry_price
                    FROM replay_events
                    WHERE signal_id = {signal_id}
                )
            """
        
        result = self.conn.execute(query).fetchall()
        if result:
            mfe, mae = result[0]
            return mae or 0.0, mfe or 0.0
        return 0.0, 0.0
    
    def find_stop_hit(self, signal_id, stop_price, direction):
        """Check if stop was hit (SQL query)"""
        if not self.conn:
            self.init_duckdb()
        
        if direction == "SHORT":
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id}
                AND price >= {stop_price}
            """
        else:
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id}
                AND price <= {stop_price}
            """
        
        result = self.conn.execute(query).fetchall()
        if result and result[0][0]:
            return result[0][0]
        return None
    
    def find_target_hit(self, signal_id, target_price, direction):
        """Check if target was hit (SQL query)"""
        if not self.conn:
            self.init_duckdb()
        
        if direction == "SHORT":
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id}
                AND price <= {target_price}
            """
        else:
            query = f"""
                SELECT MIN(event_idx)
                FROM replay_events
                WHERE signal_id = {signal_id}
                AND price >= {target_price}
            """
        
        result = self.conn.execute(query).fetchall()
        if result and result[0][0]:
            return result[0][0]
        return None
    
    def find_followthrough_breakout(self, signal_id, lookback_events, threshold_ticks, direction):
        """Find follow-through breakout using SQL (no Python loop)"""
        if not self.conn:
            self.init_duckdb()
        
        if direction == "SHORT":
            query = f"""
                WITH initial_min AS (
                    SELECT MIN(price) as min_price
                    FROM replay_events
                    WHERE signal_id = {signal_id}
                    AND event_idx < {lookback_events}
                ),
                breakout_target AS (
                    SELECT min_price - {threshold_ticks} as target_price
                    FROM initial_min
                )
                SELECT MIN(event_idx)
                FROM replay_events, breakout_target
                WHERE signal_id = {signal_id}
                AND event_idx >= {lookback_events}
                AND price < target_price
            """
        else:
            query = f"""
                WITH initial_max AS (
                    SELECT MAX(price) as max_price
                    FROM replay_events
                    WHERE signal_id = {signal_id}
                    AND event_idx < {lookback_events}
                ),
                breakout_target AS (
                    SELECT max_price + {threshold_ticks} as target_price
                    FROM initial_max
                )
                SELECT MIN(event_idx)
                FROM replay_events, breakout_target
                WHERE signal_id = {signal_id}
                AND event_idx >= {lookback_events}
                AND price > target_price
            """
        
        result = self.conn.execute(query).fetchall()
        if result and result[0][0]:
            return result[0][0]
        return None
    
    def batch_mae_mfe(self, signal_ids, entry_prices, directions):
        """Batch calculate MAE/MFE for multiple signals (vectorized)"""
        if not self.conn:
            self.init_duckdb()
        
        # Create temp table with signal data
        self.conn.execute("""
            CREATE TEMPORARY TABLE signal_data AS
            SELECT * FROM (VALUES 
        """ + ", ".join([f"({sig_id}, {entry_price}, '{direction}')" 
                        for sig_id, entry_price, direction in 
                        zip(signal_ids, entry_prices, directions)]) + """
            ) AS t(signal_id, entry_price, direction)
        """)
        
        # Batch query
        query = """
            SELECT 
                s.signal_id,
                CASE WHEN s.direction = 'SHORT' 
                    THEN MAX(s.entry_price - r.price)
                    ELSE MAX(r.price - s.entry_price)
                END as mfe,
                CASE WHEN s.direction = 'SHORT' 
                    THEN MAX(r.price - s.entry_price)
                    ELSE MAX(s.entry_price - r.price)
                END as mae
            FROM signal_data s
            JOIN replay_events r ON s.signal_id = r.signal_id
            GROUP BY s.signal_id, s.entry_price, s.direction
        """
        
        results = self.conn.execute(query).fetchall()
        return {row[0]: {'mfe': row[1] or 0.0, 'mae': row[2] or 0.0} for row in results}
    
    def get_signal_stats(self, signal_id):
        """Get comprehensive signal statistics"""
        if not self.conn:
            self.init_duckdb()
        
        query = f"""
            SELECT 
                COUNT(*) as event_count,
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price,
                STDDEV(price) as stddev_price,
                MAX(price) - MIN(price) as range_price
            FROM replay_events
            WHERE signal_id = {signal_id}
        """
        
        result = self.conn.execute(query).fetchall()
        if result:
            row = result[0]
            return {
                'event_count': row[0],
                'min_price': row[1],
                'max_price': row[2],
                'avg_price': row[3],
                'stddev_price': row[4],
                'range_price': row[5],
            }
        return {}
    
    def list_signals(self):
        """Get all available signal IDs"""
        if not self.conn:
            self.init_duckdb()
        
        query = "SELECT DISTINCT signal_id FROM replay_events ORDER BY signal_id"
        result = self.conn.execute(query).fetchall()
        return [row[0] for row in result]
    
    def close(self):
        """Close connection"""
        if self.conn:
            self.conn.close()


class PolarsReplayEngine:
    """Alternative: Polars-based vectorized analytics"""
    
    def __init__(self, events_parquet, metadata_parquet=None):
        self.events_path = Path(events_parquet)
        self.metadata_path = Path(metadata_parquet)
        self.events_df = None
        self.metadata_df = None
    
    def load(self):
        """Load parquet files"""
        import polars as pl
        
        print("[*] Loading with Polars...")
        start = time.time()
        
        self.events_df = pl.read_parquet(self.events_path)
        if self.metadata_path and self.metadata_path.exists():
            self.metadata_df = pl.read_parquet(self.metadata_path)
        
        elapsed = time.time() - start
        print(f"[✓] Loaded in {elapsed:.2f}s\n")
    
    def get_prices(self, signal_id):
        """Get prices for a signal"""
        if self.events_df is None:
            self.load()
        
        return (self.events_df
                .filter(pl.col('signal_id') == signal_id)
                .sort('event_idx')
                ['price']
                .to_list())
    
    def calc_mae_mfe_fast(self, signal_id, entry_price, direction):
        """Calculate MAE/MFE using Polars"""
        if self.events_df is None:
            self.load()
        
        prices = (self.events_df
                 .filter(pl.col('signal_id') == signal_id)
                 ['price']
                 .to_numpy())
        
        if len(prices) == 0:
            return 0.0, 0.0
        
        if direction == "SHORT":
            mfe = float((entry_price - prices).max())
            mae = float((prices - entry_price).max())
        else:
            mfe = float((prices - entry_price).max())
            mae = float((entry_price - prices).max())
        
        return mae, mfe
    
    def batch_mae_mfe(self, signal_ids, entry_prices, directions):
        """Batch process signals"""
        if self.events_df is None:
            self.load()
        
        results = {}
        for sig_id, entry_price, direction in zip(signal_ids, entry_prices, directions):
            mae, mfe = self.calc_mae_mfe_fast(sig_id, entry_price, direction)
            results[sig_id] = {'mfe': mfe, 'mae': mae}
        
        return results


def get_engine(events_parquet, metadata_parquet=None, backend='duckdb'):
    """Factory: Get appropriate engine based on availability"""
    try:
        if backend == 'duckdb':
            engine = VectorizedReplayEngine(events_parquet, metadata_parquet)
            engine.init_duckdb()
            return engine
    except ImportError:
        pass
    
    try:
        engine = PolarsReplayEngine(events_parquet, metadata_parquet)
        engine.load()
        return engine
    except ImportError:
        pass
    
    raise RuntimeError("No vectorized engine available (install duckdb or polars)")


if __name__ == "__main__":
    # Test
    events = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/cache/signals_26_50_events.parquet")
    metadata = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/cache/signals_26_50_metadata.parquet")
    
    try:
        engine = get_engine(events, metadata, backend='duckdb')
        print("[✓] Engine initialized")
        
        signals = engine.list_signals()
        print(f"[✓] Found {len(signals)} signals: {signals[:5]}...\n")
        
        # Test signal 26
        print("[*] Testing signal 26...")
        prices = engine.get_prices(26)
        print(f"[✓] Got {len(prices)} prices")
        
        mae, mfe = engine.calc_mae_mfe_fast(26, 7226.25, 'SHORT')
        print(f"[✓] MAE: {mae:.2f}, MFE: {mfe:.2f}\n")
        
        stats = engine.get_signal_stats(26)
        print(f"[✓] Signal stats: {stats}\n")
        
        engine.close()
        print("[✓] Test complete")
    except Exception as e:
        print(f"[!] Error: {e}")

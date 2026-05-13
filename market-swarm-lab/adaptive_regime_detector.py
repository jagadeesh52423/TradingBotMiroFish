#!/usr/bin/env python3
"""
Adaptive Regime Detector for NQ Futures Trading

Implements multi-dimensional regime classification:
1. Relative Volatility: ATR / rolling mean (percentile-based labels)
2. Trend Structure: price vs VWAP, VWAP slope, higher-high/lower-low patterns, EMA slope
3. Directional Pressure: cumulative delta slope, buy/sell imbalance, displacement persistence
4. Balance/Chop: range compression, overlapping bars, VWAP mean reversion, failed continuation

REGIME LABELS:
- BULL_TREND, BEAR_TREND, BALANCE, TRANSITION, HIGH_VOL_EXPANSION, LOW_VOL_CHOP

No future leakage. No live deployment. Validation only on NQM6.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from enum import Enum


class RegimeLabel(Enum):
    """Regime classification labels."""
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    BALANCE = "BALANCE"
    TRANSITION = "TRANSITION"
    HIGH_VOL_EXPANSION = "HIGH_VOL_EXPANSION"
    LOW_VOL_CHOP = "LOW_VOL_CHOP"


@dataclass
class OHLCV:
    """Single bar OHLC + volume."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2
    
    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class VolatilityMetrics:
    """Volatility measurements and percentile labels."""
    atr_value: float                    # Current ATR
    atr_percentile: float               # ATR percentile (0-100)
    vol_ratio: float                    # ATR / rolling mean
    vol_label: str                      # LOW, NORMAL, HIGH, EXTREME
    range_compression_score: float      # 0-1, higher = more compressed


@dataclass
class TrendMetrics:
    """Trend structure analysis."""
    price_vs_vwap: float                # 1.0 = above, 0.0 = at, -1.0 = below
    vwap_slope: float                   # VWAP direction/speed
    ema_10_vs_20: float                 # 1.0 = bullish cross, -1.0 = bearish, 0 = mixed
    ema_slope: float                    # EMA directional slope
    higher_high: bool                   # Recent HH pattern
    lower_low: bool                     # Recent LL pattern
    trend_direction: str                # UP, DOWN, SIDEWAYS


@dataclass
class DirectionalPressure:
    """Directional momentum and imbalance."""
    cumulative_delta_slope: float       # CD moving average slope
    buy_sell_imbalance: float           # (buy_vol - sell_vol) / total
    displacement_score: float           # Distance from VWAP in terms of ATR
    displacement_persistence: float     # How long displacement lasted (0-1)
    trend_strength: str                 # WEAK, MODERATE, STRONG


@dataclass
class BalanceMetrics:
    """Balance/chop indicators."""
    range_compression: float            # How tight (0-1, 1=max compression)
    overlapping_bars_pct: float         # % of bars overlapping previous (0-1)
    vwap_reversion_strength: float      # Strength of mean reversion to VWAP
    failed_continuation_count: int      # Failed breakout attempts


@dataclass
class RegimeState:
    """Complete regime snapshot at a point in time."""
    timestamp: str
    bar_index: int
    regime: RegimeLabel
    confidence: float                   # 0-1
    
    volatility: VolatilityMetrics
    trend: TrendMetrics
    pressure: DirectionalPressure
    balance: BalanceMetrics
    
    # Raw components for debugging
    components: Dict[str, float]        # Individual signal strengths


class AdaptiveRegimeDetector:
    """
    Multi-dimensional regime detection engine.
    
    Processes OHLCV bars and produces regime labels with full audit trail.
    """
    
    def __init__(self, 
                 atr_period: int = 14,
                 vol_window: int = 20,
                 vwap_window: int = 20,
                 ema_fast: int = 10,
                 ema_slow: int = 20,
                 displacement_threshold: float = 1.5):  # in ATR units
        """
        Initialize detector with indicator parameters.
        
        Args:
            atr_period: ATR calculation period
            vol_window: Rolling volatility window
            vwap_window: VWAP calculation window
            ema_fast: Fast EMA period
            ema_slow: Slow EMA period
            displacement_threshold: Minimum displacement to be significant (ATR units)
        """
        self.atr_period = atr_period
        self.vol_window = vol_window
        self.vwap_window = vwap_window
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.displacement_threshold = displacement_threshold
        
        # State for online computation
        self.bars: List[OHLCV] = []
        self.regime_history: List[RegimeState] = []
        
        # Caches for efficiency
        self._atr_cache: List[float] = []
        self._ema_fast_cache: List[float] = []
        self._ema_slow_cache: List[float] = []
        self._vwap_cache: List[float] = []
        self._cd_cache: List[float] = []  # Cumulative delta
    
    def add_bar(self, bar: OHLCV) -> Optional[RegimeState]:
        """
        Process a new bar and update regime state.
        
        Args:
            bar: New OHLCV bar
            
        Returns:
            Updated regime state, or None if insufficient history
        """
        self.bars.append(bar)
        
        # Need minimum bars for all indicators
        min_required = max(
            self.atr_period + 5,
            self.vol_window + 5,
            self.vwap_window + 5,
            self.ema_slow + 5
        )
        
        if len(self.bars) < min_required:
            return None
        
        # Update caches
        self._update_caches()
        
        # Compute regime
        regime_state = self._compute_regime_state()
        self.regime_history.append(regime_state)
        
        return regime_state
    
    def _update_caches(self) -> None:
        """Update all technical indicator caches (last bar)."""
        bars = self.bars
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume for b in bars]
        
        # ATR
        self._atr_cache.append(self._calc_atr(highs, lows, closes, self.atr_period))
        
        # EMAs
        self._ema_fast_cache.append(self._calc_ema(closes, self.ema_fast))
        self._ema_slow_cache.append(self._calc_ema(closes, self.ema_slow))
        
        # VWAP
        self._vwap_cache.append(self._calc_vwap(bars[-self.vwap_window:]))
        
        # Cumulative delta (approximation from volume-weighted price)
        self._cd_cache.append(self._calc_cumulative_delta(bars[-self.vol_window:]))
    
    @staticmethod
    def _calc_atr(highs: List[float], lows: List[float], closes: List[float], 
                  period: int) -> float:
        """Calculate ATR."""
        if len(closes) < period + 1:
            return 0.0
        
        trs = []
        for i in range(len(closes) - period, len(closes)):
            hi, lo, c_prev = highs[i], lows[i], closes[i-1]
            tr = max(hi - lo, abs(hi - c_prev), abs(lo - c_prev))
            trs.append(tr)
        
        return np.mean(trs[-period:]) if trs else 0.0
    
    @staticmethod
    def _calc_ema(prices: List[float], period: int) -> float:
        """Calculate EMA (simple online version)."""
        if not prices:
            return 0.0
        
        prices_arr = np.array(prices[-period-10:])
        if len(prices_arr) < 2:
            return prices[0]
        
        k = 2 / (period + 1)
        ema = prices_arr[0]
        for p in prices_arr[1:]:
            ema = p * k + ema * (1 - k)
        return float(ema)
    
    @staticmethod
    def _calc_vwap(bars: List[OHLCV]) -> float:
        """Calculate VWAP."""
        if not bars:
            return 0.0
        
        cv = sum((b.high + b.low + b.close) / 3 * b.volume for b in bars)
        vol = sum(b.volume for b in bars)
        
        return cv / vol if vol > 0 else bars[-1].close
    
    @staticmethod
    def _calc_cumulative_delta(bars: List[OHLCV]) -> float:
        """
        Simple cumulative delta approximation.
        Estimate buy/sell volume based on close vs open direction.
        """
        cd = 0.0
        for bar in bars:
            if bar.close > bar.open:
                cd += bar.volume  # Bullish bar
            elif bar.close < bar.open:
                cd -= bar.volume  # Bearish bar
        return cd
    
    def _compute_regime_state(self) -> RegimeState:
        """Compute complete regime state for current position."""
        idx = len(self.bars) - 1
        bar = self.bars[idx]
        
        # Compute all metrics
        vol_metrics = self._compute_volatility_metrics()
        trend_metrics = self._compute_trend_metrics()
        pressure_metrics = self._compute_directional_pressure()
        balance_metrics = self._compute_balance_metrics()
        
        # Combine into regime decision
        regime, confidence, components = self._score_regime(
            vol_metrics, trend_metrics, pressure_metrics, balance_metrics
        )
        
        return RegimeState(
            timestamp=bar.timestamp,
            bar_index=idx,
            regime=regime,
            confidence=confidence,
            volatility=vol_metrics,
            trend=trend_metrics,
            pressure=pressure_metrics,
            balance=balance_metrics,
            components=components
        )
    
    def _compute_volatility_metrics(self) -> VolatilityMetrics:
        """Compute volatility component."""
        atr = self._atr_cache[-1]
        
        # Rolling mean of close
        closes = [b.close for b in self.bars]
        rolling_mean = np.mean(closes[-self.vol_window:])
        
        # ATR percentile (vs historical ATRs)
        atr_history = self._atr_cache[-min(50, len(self._atr_cache)):]
        atr_percentile = 100 * np.mean([a <= atr for a in atr_history])
        
        # Volatility ratio
        vol_ratio = atr / rolling_mean if rolling_mean > 0 else 0.0
        
        # Label
        if vol_ratio < 0.003:
            vol_label = "LOW"
        elif vol_ratio < 0.007:
            vol_label = "NORMAL"
        elif vol_ratio < 0.015:
            vol_label = "HIGH"
        else:
            vol_label = "EXTREME"
        
        # Range compression score (inverse of current bar range vs ATR)
        current_range = self.bars[-1].range
        compression = 1.0 - min(1.0, current_range / (atr + 0.001))
        
        return VolatilityMetrics(
            atr_value=atr,
            atr_percentile=atr_percentile,
            vol_ratio=vol_ratio,
            vol_label=vol_label,
            range_compression_score=compression
        )
    
    def _compute_trend_metrics(self) -> TrendMetrics:
        """Compute trend structure component."""
        bar = self.bars[-1]
        price = bar.close
        vwap = self._vwap_cache[-1]
        ema10 = self._ema_fast_cache[-1]
        ema20 = self._ema_slow_cache[-1]
        
        # Price vs VWAP
        if price > vwap * 1.002:
            pv = 1.0  # Above
        elif price < vwap * 0.998:
            pv = -1.0  # Below
        else:
            pv = 0.0  # At
        
        # VWAP slope (recent movement)
        if len(self._vwap_cache) >= 5:
            vwap_recent = np.array(self._vwap_cache[-5:])
            vwap_slope = np.polyfit(range(len(vwap_recent)), vwap_recent, 1)[0]
        else:
            vwap_slope = 0.0
        
        # EMA 10 vs 20
        if ema10 > ema20 * 1.001:
            ema_cond = 1.0
            ema_slope = (ema10 - ema20) / (ema20 + 0.001)
        elif ema10 < ema20 * 0.999:
            ema_cond = -1.0
            ema_slope = (ema10 - ema20) / (ema20 + 0.001)
        else:
            ema_cond = 0.0
            ema_slope = 0.0
        
        # Higher high / lower low patterns (last 5 bars)
        if len(self.bars) >= 5:
            recent_bars = self.bars[-5:]
            hh = all(recent_bars[-1].high >= b.high for b in recent_bars[:-1])
            ll = all(recent_bars[-1].low <= b.low for b in recent_bars[:-1])
        else:
            hh = ll = False
        
        # Trend direction
        if pv > 0 and ema_cond > 0 and vwap_slope > 0:
            direction = "UP"
        elif pv < 0 and ema_cond < 0 and vwap_slope < 0:
            direction = "DOWN"
        else:
            direction = "SIDEWAYS"
        
        return TrendMetrics(
            price_vs_vwap=pv,
            vwap_slope=vwap_slope,
            ema_10_vs_20=ema_cond,
            ema_slope=ema_slope,
            higher_high=hh,
            lower_low=ll,
            trend_direction=direction
        )
    
    def _compute_directional_pressure(self) -> DirectionalPressure:
        """Compute directional pressure component."""
        # Cumulative delta slope
        if len(self._cd_cache) >= 5:
            cd_recent = np.array(self._cd_cache[-5:])
            cd_slope = np.polyfit(range(len(cd_recent)), cd_recent, 1)[0]
        else:
            cd_slope = 0.0
        
        # Buy/sell imbalance (approximation)
        recent_bars = self.bars[-self.vol_window:]
        buy_vol = sum(b.volume for b in recent_bars if b.close >= b.open)
        sell_vol = sum(b.volume for b in recent_bars if b.close < b.open)
        total_vol = buy_vol + sell_vol
        imbalance = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0.0
        
        # Displacement from VWAP (in ATR units)
        price = self.bars[-1].close
        vwap = self._vwap_cache[-1]
        atr = self._atr_cache[-1]
        displacement = (price - vwap) / (atr + 0.001)
        
        # Displacement persistence (how many bars been displaced)
        persistence = 0.0
        if atr > 0:
            for i in range(len(self.bars) - 1, max(0, len(self.bars) - 10), -1):
                if abs(self.bars[i].close - self._vwap_cache[min(i, len(self._vwap_cache)-1)]) > atr * self.displacement_threshold:
                    persistence += 0.1
                else:
                    break
        
        # Trend strength (magnitude of directional metrics)
        strength_magnitude = abs(imbalance) + abs(cd_slope / (atr + 0.001))
        if strength_magnitude < 0.3:
            strength = "WEAK"
        elif strength_magnitude < 0.7:
            strength = "MODERATE"
        else:
            strength = "STRONG"
        
        return DirectionalPressure(
            cumulative_delta_slope=cd_slope,
            buy_sell_imbalance=imbalance,
            displacement_score=displacement,
            displacement_persistence=min(1.0, persistence),
            trend_strength=strength
        )
    
    def _compute_balance_metrics(self) -> BalanceMetrics:
        """Compute balance/chop component."""
        # Range compression
        recent_bars = self.bars[-min(10, len(self.bars)):]
        ranges = [b.range for b in recent_bars]
        avg_range = np.mean(ranges)
        compression = 1.0 - (np.std(ranges) / (avg_range + 0.001))
        
        # Overlapping bars
        overlaps = 0
        for i in range(1, len(recent_bars)):
            prev_bar = recent_bars[i-1]
            curr_bar = recent_bars[i]
            # Check if current bar's range overlaps with previous
            if curr_bar.high >= prev_bar.low and curr_bar.low <= prev_bar.high:
                overlaps += 1
        overlapping_pct = overlaps / max(1, len(recent_bars) - 1)
        
        # VWAP mean reversion strength
        vwap_values = self._vwap_cache[-min(10, len(self._vwap_cache)):]
        if len(vwap_values) > 1:
            deviations = [abs(self.bars[-(len(vwap_values)-i)] .close - vwap_values[i]) 
                         for i in range(len(vwap_values))]
            reversion_strength = 1.0 - np.mean(deviations) / (np.mean([b.close for b in recent_bars]) * 0.01 + 0.001)
            reversion_strength = max(0.0, min(1.0, reversion_strength))
        else:
            reversion_strength = 0.5
        
        # Failed continuation attempts
        failed = 0
        if len(recent_bars) >= 3:
            for i in range(1, len(recent_bars) - 1):
                prev = recent_bars[i-1]
                curr = recent_bars[i]
                next_b = recent_bars[i+1]
                # Failed breakout: broke high but came back down
                if curr.high > prev.high and next_b.close < curr.close:
                    failed += 1
        
        return BalanceMetrics(
            range_compression=compression,
            overlapping_bars_pct=overlapping_pct,
            vwap_reversion_strength=reversion_strength,
            failed_continuation_count=failed
        )
    
    def _score_regime(self, vol: VolatilityMetrics, trend: TrendMetrics, 
                      pressure: DirectionalPressure, balance: BalanceMetrics
                      ) -> Tuple[RegimeLabel, float, Dict[str, float]]:
        """
        Score regime using weighted components.
        
        Returns: (regime_label, confidence_0_to_1, component_scores)
        """
        components = {}
        
        # Vol component
        if vol.vol_label == "LOW":
            vol_score = -0.3
        elif vol.vol_label == "NORMAL":
            vol_score = 0.0
        elif vol.vol_label == "HIGH":
            vol_score = 0.4
        else:  # EXTREME
            vol_score = 0.7
        components["volatility"] = vol_score
        
        # Trend component
        if trend.trend_direction == "UP":
            trend_score = 0.8
        elif trend.trend_direction == "DOWN":
            trend_score = -0.8
        else:
            trend_score = 0.0
        components["trend"] = trend_score
        
        # Pressure component (buy/sell imbalance + displacement)
        pressure_score = (
            np.sign(pressure.buy_sell_imbalance) * abs(pressure.buy_sell_imbalance) +
            np.sign(pressure.displacement_score) * min(1.0, abs(pressure.displacement_score) / 2.0)
        ) / 2.0
        components["pressure"] = pressure_score
        
        # Balance component
        balance_score = 0.0
        if balance.overlapping_bars_pct > 0.7:
            balance_score -= 0.5  # Heavy chop
        if balance.range_compression > 0.7:
            balance_score -= 0.3  # Compressed
        if balance.failed_continuation_count > 2:
            balance_score -= 0.2  # Choppy
        components["balance"] = balance_score
        
        # Weighted combination
        weighted_score = (
            trend_score * 0.40 +
            pressure_score * 0.30 +
            vol_score * 0.15 +
            balance_score * 0.15
        )
        
        components["total_weighted"] = weighted_score
        
        # Regime classification
        if weighted_score > 0.5:
            regime = RegimeLabel.BULL_TREND
            confidence = min(1.0, abs(weighted_score))
        elif weighted_score < -0.5:
            regime = RegimeLabel.BEAR_TREND
            confidence = min(1.0, abs(weighted_score))
        elif abs(weighted_score) < 0.15:
            regime = RegimeLabel.BALANCE
            confidence = 1.0 - abs(weighted_score) * 2
        elif -0.5 <= weighted_score <= 0.5:
            regime = RegimeLabel.TRANSITION
            confidence = 0.5 + abs(weighted_score) * 0.5
        else:
            regime = RegimeLabel.BALANCE
            confidence = 0.5
        
        # Volatility overrides
        if vol.vol_label == "EXTREME" and abs(weighted_score) > 0.3:
            regime = RegimeLabel.HIGH_VOL_EXPANSION
            confidence = min(1.0, vol.vol_ratio / 0.01)
        elif vol.vol_label == "LOW" and balance.overlapping_bars_pct > 0.6:
            regime = RegimeLabel.LOW_VOL_CHOP
            confidence = 0.7
        
        return regime, confidence, components
    
    def get_regime_history(self) -> List[RegimeState]:
        """Return full regime history."""
        return self.regime_history


def load_jsonl_as_bars(jsonl_path: Path, symbol: str) -> List[OHLCV]:
    """
    Load JSONL orderflow data and aggregate into bars.
    
    Assumes bookmap L1 feed with depth events.
    Aggregates into 1-minute bars by default.
    """
    bars = []
    current_bar_start = None
    current_ohlc = {}
    current_volume = 0
    
    with open(jsonl_path) as f:
        for line in f:
            event = json.loads(line)
            
            # Filter to symbol
            if event.get("symbol") != symbol:
                continue
            
            # Parse timestamp
            ts_str = event.get("ts_event", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            
            # Determine bar minute
            bar_minute = ts.replace(second=0, microsecond=0)
            
            # Initialize or continue bar
            if current_bar_start is None:
                current_bar_start = bar_minute
                current_ohlc = {"o": None, "h": -np.inf, "l": np.inf, "c": None}
                current_volume = 0
            
            # New bar?
            if bar_minute != current_bar_start and current_ohlc["c"] is not None:
                # Finalize bar
                bar = OHLCV(
                    timestamp=current_bar_start.isoformat(),
                    open=current_ohlc["o"],
                    high=current_ohlc["h"],
                    low=current_ohlc["l"],
                    close=current_ohlc["c"],
                    volume=current_volume
                )
                bars.append(bar)
                
                # Start new bar
                current_bar_start = bar_minute
                current_ohlc = {"o": None, "h": -np.inf, "l": np.inf, "c": None}
                current_volume = 0
            
            # Update bar OHLC
            if event.get("event_type") == "depth":
                price = event.get("price")
                size = event.get("size", 0)
                
                if price is not None:
                    if current_ohlc["o"] is None:
                        current_ohlc["o"] = price
                    current_ohlc["h"] = max(current_ohlc["h"], price)
                    current_ohlc["l"] = min(current_ohlc["l"], price)
                    current_ohlc["c"] = price
                    current_volume += size
    
    # Finalize last bar
    if current_ohlc["c"] is not None:
        bar = OHLCV(
            timestamp=current_bar_start.isoformat(),
            open=current_ohlc["o"],
            high=current_ohlc["h"],
            low=current_ohlc["l"],
            close=current_ohlc["c"],
            volume=current_volume
        )
        bars.append(bar)
    
    return bars


if __name__ == "__main__":
    # Test/demo
    jsonl_path = Path("/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/state/orderflow/bookmap_api/es_orderflow_2026-05-06.jsonl")
    
    print("[*] Loading NQM6 bars from JSONL...")
    bars = load_jsonl_as_bars(jsonl_path, "NQM6.CME@RITHMIC")
    print(f"[✓] Loaded {len(bars)} bars")
    
    print("[*] Initializing adaptive regime detector...")
    detector = AdaptiveRegimeDetector()
    
    print("[*] Processing bars...")
    regimes = []
    for i, bar in enumerate(bars):
        regime_state = detector.add_bar(bar)
        if regime_state:
            regimes.append(regime_state)
            if i % 100 == 0:
                print(f"  Bar {i+1}: {regime_state.regime.value} ({regime_state.confidence:.1%})")
    
    print(f"\n[✓] Processed {len(bars)} bars, generated {len(regimes)} regime states")
    
    if regimes:
        print("\nRecent regimes:")
        for r in regimes[-10:]:
            print(f"  {r.timestamp}: {r.regime.value} ({r.confidence:.1%})")

"""Signal strategy registry — pluggable signal generation for the Nubra equity runner.

# implement SignalStrategy + register to add a new signal source.

Strategy pattern: callers pick a named strategy via get_strategy(); adding a new
source requires only a new class + _REGISTRY entry, no edits to callers.
"""
from __future__ import annotations

import math
import uuid
from abc import ABC, abstractmethod

from services.nubra_client.equity_signal_builder import EquitySignalBuilder

# Registry keyed by strategy name.  Self-registered at module import.
_REGISTRY: dict[str, type[SignalStrategy]] = {}


class SignalStrategy(ABC):
    """Build a tradeable signal dict from the available inputs.

    Args:
        symbol:     NSE ticker (e.g. "SBIN").
        context:    equity_context dict from build_equity_context (price, source_audit …).
        forecast:   TimesFM forecast dict, or None when not computed.
        simulation: MiroFish simulation dict, or None when not computed.
        nse_result: NSE announcements collector output dict, or None.

    Returns:
        Signal dict (keys: ticker, asset_class, trade, strategy_type, expected_move_pct,
        confidence, horizon, signal_id, …) or None to indicate no signal.
    """

    @abstractmethod
    def build(
        self,
        symbol: str,
        context: dict | None,
        forecast: dict | None,
        simulation: dict | None,
        nse_result: dict | None,
    ) -> dict | None: ...


def _register(name: str):
    """Class decorator that adds the strategy to _REGISTRY under *name*."""
    def decorator(cls: type[SignalStrategy]) -> type[SignalStrategy]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(name: str, config: dict | None = None) -> SignalStrategy:
    """Return an instantiated strategy by registry name.

    Raises:
        ValueError: if *name* is not in the registry.
    """
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown signal strategy {name!r}. Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](config or {})


# ---------------------------------------------------------------------------
# BlendedSignalStrategy — wraps existing EquitySignalBuilder, behaviour unchanged
# ---------------------------------------------------------------------------

@_register("blended")
class BlendedSignalStrategy(SignalStrategy):
    """Blends TimesFM + MiroFish + NSE into a signal; delegates to EquitySignalBuilder.

    This is the default strategy.  Backward-compatible: all existing blended tests
    continue to pass because EquitySignalBuilder is not modified.
    """

    def __init__(self, config: dict) -> None:
        self._builder = EquitySignalBuilder(config.get("signal"))

    def build(
        self,
        symbol: str,
        context: dict | None,
        forecast: dict | None,
        simulation: dict | None,
        nse_result: dict | None,
    ) -> dict | None:
        return self._builder.build(symbol, forecast, simulation, nse_result=nse_result)


# ---------------------------------------------------------------------------
# NewsOnlySignalStrategy — signal derived solely from NSE announcements
# ---------------------------------------------------------------------------

@_register("news_only")
class NewsOnlySignalStrategy(SignalStrategy):
    """Derives a signal ONLY from NSE announcement sentiment — no forecast, no simulation.

    Enables trading news catalysts for symbols with insufficient OHLCV history (the
    thin-history guard is bypassed when this strategy is active).

    Config keys (under config["signal"]["news_only"]):
        buy_threshold  (float, default 0.15)  — sentiment_score ≥ this → CALL
        sell_threshold (float, default -0.15) — sentiment_score ≤ this → PUT
        min_filings    (int,   default 1)     — CALL requires at least this many items
        confidence_params:
            score_weight         (float, default 0.7) — weight on abs(sentiment_score)
            filing_weight        (float, default 0.3) — weight on log-scaled filing count
            max_expected_filings (int,   default 5)   — upper anchor for filing count scale
    """

    _DEFAULT_BUY_THRESHOLD: float = 0.15
    _DEFAULT_SELL_THRESHOLD: float = -0.15
    _DEFAULT_MIN_FILINGS: int = 1

    _DEFAULT_SCORE_WEIGHT: float = 0.7
    _DEFAULT_FILING_WEIGHT: float = 0.3
    _DEFAULT_MAX_EXPECTED_FILINGS: int = 5

    def __init__(self, config: dict) -> None:
        news_cfg = config.get("signal", {}).get("news_only", {})
        conf_p = news_cfg.get("confidence_params", {})

        self._buy_threshold = float(
            news_cfg.get("buy_threshold", self._DEFAULT_BUY_THRESHOLD)
        )
        self._sell_threshold = float(
            news_cfg.get("sell_threshold", self._DEFAULT_SELL_THRESHOLD)
        )
        self._min_filings = int(news_cfg.get("min_filings", self._DEFAULT_MIN_FILINGS))
        self._score_weight = float(
            conf_p.get("score_weight", self._DEFAULT_SCORE_WEIGHT)
        )
        self._filing_weight = float(
            conf_p.get("filing_weight", self._DEFAULT_FILING_WEIGHT)
        )
        self._max_expected_filings = int(
            conf_p.get("max_expected_filings", self._DEFAULT_MAX_EXPECTED_FILINGS)
        )

        # expected_move_pct proxy: just clears the ExpectedUpsideGate for CALL signals.
        # This is a conviction proxy — not a price forecast.
        entry_cfg = config.get("entry_threshold", {})
        min_upside_pct = float(entry_cfg.get("min_expected_upside_pct", 2.0))
        self._upside_proxy = min_upside_pct / 100.0

    def build(
        self,
        symbol: str,
        context: dict | None,
        forecast: dict | None,
        simulation: dict | None,
        nse_result: dict | None,
    ) -> dict | None:
        if nse_result is None:
            return None

        sentiment_score = float(nse_result.get("sentiment_score", 0.0))
        items: list[dict] = nse_result.get("items", [])
        filing_count = len(items)

        # Determine trade direction from news sentiment only.
        if sentiment_score >= self._buy_threshold and filing_count >= self._min_filings:
            trade = "CALL"
        elif sentiment_score <= self._sell_threshold:
            trade = "PUT"
        else:
            trade = "HOLD"

        confidence = self._compute_confidence(sentiment_score, filing_count)

        # expected_move_pct proxy for CALL: set to just clear the ExpectedUpsideGate.
        # The "move" is a conviction proxy — news has no price forecast.
        expected_move_pct = self._upside_proxy if trade == "CALL" else 0.0

        reasoning = _extract_subjects(items)

        return {
            "ticker": symbol.upper(),
            "asset_class": "equity",
            "trade": trade,
            "strategy_type": "trend",
            "expected_move_pct": expected_move_pct,
            "confidence": confidence,
            "horizon": "1d",
            "signal_id": str(uuid.uuid4()),
            "reasoning": reasoning,
        }

    def _compute_confidence(self, sentiment_score: float, filing_count: int) -> float:
        score_component = abs(sentiment_score)   # already in [0, 1] since score ∈ [-1,1]
        # Log-scale filing count so more filings raise confidence sub-linearly.
        filing_component = math.log1p(filing_count) / math.log1p(
            self._max_expected_filings
        )
        filing_component = min(1.0, filing_component)
        raw = self._score_weight * score_component + self._filing_weight * filing_component
        return round(min(1.0, max(0.0, raw)), 4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_subjects(items: list[dict]) -> list[str]:
    """Extract short subject/desc labels from NSE announcement items."""
    subjects = []
    for item in items:
        # Prefer 'desc' (announcement category) over first words of 'attchmntText'.
        label = item.get("desc") or (item.get("attchmntText") or "")[:60]
        if label:
            subjects.append(label.strip())
    return subjects

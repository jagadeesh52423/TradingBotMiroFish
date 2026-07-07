"""NSE sector-index trend for a symbol — the tailwind/headwind check.

Playbook §10/§11: a lone-stock catalyst fighting a falling sector index is a weaker
trade; "sector index moving hard against your catalyst direction" is a trade-killer.
This provider maps a symbol to its sector index and reports whether that index is
trending up or down (last close vs an N-day SMA). Fails safe: returns None when the
symbol is unmapped, data is thin, or the fetch errors — the gate then allows.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_DEFAULT_LOOKBACK = 20
_DEFAULT_MIN_BARS = 10


class SectorTrendProvider:
    """Resolves a symbol's sector index and classifies its trend as 'up' | 'down' | None."""

    def __init__(self, sector_map: dict, closes_fn, lookback: int = _DEFAULT_LOOKBACK,
                 min_bars: int = _DEFAULT_MIN_BARS) -> None:
        # closes_fn(index_symbol) -> list[float] recent closes, oldest-first.
        self._map = {k.upper(): v for k, v in (sector_map or {}).items()}
        self._closes_fn = closes_fn
        self._lookback = lookback
        self._min_bars = min_bars

    @classmethod
    def from_config(cls, config: dict) -> "SectorTrendProvider":
        """Build from entry_threshold.sector_gate; index closes come from Fyers (has sector indices)."""
        sg = config.get("entry_threshold", {}).get("sector_gate", {})
        lookback = int(sg.get("lookback", _DEFAULT_LOOKBACK))
        min_bars = int(sg.get("min_bars", _DEFAULT_MIN_BARS))
        from services.fyers_client.fyers_data_provider import FyersDataProvider
        fyers = FyersDataProvider.from_config(config)

        def closes_fn(index_symbol: str) -> list[float]:
            bars = fyers.historical(index_symbol, interval="1d", lookback=lookback + 5)
            return [b["close"] for b in bars]

        return cls(sg.get("sector_map", {}), closes_fn, lookback, min_bars)

    def trend(self, symbol: str) -> str | None:
        index = self._map.get(symbol.upper())
        if not index:
            return None  # unmapped symbol — no opinion
        try:
            closes = [float(c) for c in (self._closes_fn(index) or [])]
        except Exception as exc:
            _log.warning("sector index fetch failed for %s (%s): %s", symbol, index, exc)
            return None
        if len(closes) < self._min_bars:
            return None
        window = closes[-self._lookback:]
        sma = sum(window) / len(window)
        return "up" if closes[-1] >= sma else "down"

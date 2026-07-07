"""Market-regime check (§10) — is the broad market in an up-trend?

Playbook §10 + the repo's own catalyst research: the catalyst-swing edge is regime-dependent
— positive in up-markets, ~flat all-in. So a CALL taken while the broad market is trending
DOWN is a lower-quality trade. This resolves a single market-wide regime (broad index vs its
N-day SMA), cached for the run. Fails open (returns None → 'unknown') when data is unavailable.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_DEFAULT_INDEX = "NSE:NIFTY50-INDEX"
_DEFAULT_MA = 20
_DEFAULT_MIN_BARS = 15


class MarketRegimeProvider:
    """Classifies the broad market as 'up' | 'down' | None (unknown). Result is cached."""

    def __init__(self, closes_fn, index_symbol: str = _DEFAULT_INDEX,
                 ma_days: int = _DEFAULT_MA, min_bars: int = _DEFAULT_MIN_BARS) -> None:
        self._closes_fn = closes_fn        # closes_fn(index) -> list[float] oldest-first
        self._index = index_symbol
        self._ma = ma_days
        self._min_bars = min_bars
        self._cached: str | None = None
        self._resolved = False

    @classmethod
    def from_config(cls, config: dict) -> "MarketRegimeProvider":
        rg = config.get("entry_threshold", {}).get("regime_gate", {})
        from services.fyers_client.fyers_data_provider import FyersDataProvider
        fyers = FyersDataProvider.from_config(config)
        ma = int(rg.get("ma_days", _DEFAULT_MA))

        def closes_fn(index: str) -> list[float]:
            bars = fyers.historical(index, interval="1d", lookback=ma + 5)
            return [b["close"] for b in bars]

        return cls(closes_fn, rg.get("index", _DEFAULT_INDEX), ma, int(rg.get("min_bars", _DEFAULT_MIN_BARS)))

    def regime(self) -> str | None:
        if self._resolved:
            return self._cached
        self._resolved = True
        try:
            closes = [float(c) for c in (self._closes_fn(self._index) or [])]
        except Exception as exc:
            _log.warning("regime index fetch failed (%s): %s", self._index, exc)
            return self._cached
        if len(closes) < self._min_bars:
            return self._cached
        sma = sum(closes[-self._ma:]) / len(closes[-self._ma:])
        self._cached = "up" if closes[-1] >= sma else "down"
        return self._cached

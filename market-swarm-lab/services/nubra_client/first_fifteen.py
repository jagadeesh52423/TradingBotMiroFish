"""First-15-minute opening-gap confirmation (§3/§4 gate 3).

Playbook: after the 09:15 IST open, confirm the catalyst gap is HOLDING in the
09:15–09:30 window — price not fading back toward the pre-open level — before entry.
This provider reads today's 5-minute bars and reports whether the open gap held.

Fails safe (returns None → gate allows): before 09:30 IST, on a non-trading day,
when intraday data is absent, or on any fetch error. Live-intraday-effective only —
a daily/backtest run has no today intraday bars, so the gate is a no-op there.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

_log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_OPEN = time(9, 15)
_WINDOW_END = time(9, 30)


class FirstFifteenProvider:
    """Reports the opening-gap status for a symbol: 'held' | 'faded' | None."""

    def __init__(self, bars_fn, clock=None, fade_tolerance_pct: float = 0.1) -> None:
        # bars_fn(symbol) -> today-inclusive 5-min bars, oldest-first, each
        # {timestamp(ms UTC epoch), open, close, ...}. clock() -> aware IST datetime.
        self._bars_fn = bars_fn
        self._clock = clock or (lambda: datetime.now(_IST))
        self._tol = fade_tolerance_pct

    @classmethod
    def from_config(cls, config: dict) -> "FirstFifteenProvider":
        f15 = config.get("entry_threshold", {}).get("first15_gate", {})
        from services.fyers_client.fyers_data_provider import FyersDataProvider
        fyers = FyersDataProvider.from_config(config)

        def bars_fn(symbol: str) -> list[dict]:
            return fyers.ohlcv(symbol, interval="5", lookback=80)  # ~today + prior session

        return cls(bars_fn, fade_tolerance_pct=float(f15.get("fade_tolerance_pct", 0.1)))

    def gap_status(self, symbol: str) -> str | None:
        now = self._clock().astimezone(_IST)
        if now.time() < _WINDOW_END:
            return None  # window not complete yet — can't confirm
        try:
            bars = self._bars_fn(symbol) or []
        except Exception as exc:
            _log.warning("first-15 bars fetch failed for %s: %s", symbol, exc)
            return None

        today = now.date()
        todays = [b for b in bars if _ist(b["timestamp"]).date() == today]
        window = [b for b in todays if _OPEN <= _ist(b["timestamp"]).time() < _WINDOW_END]
        if not todays or not window:
            return None

        day_open = float(todays[0]["open"])
        last_close = float(window[-1]["close"])
        floor = day_open * (1 - self._tol / 100.0)
        return "held" if last_close >= floor else "faded"


def _ist(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=_IST)

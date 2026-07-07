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

    def __init__(self, bars_fn, clock=None, fade_tolerance_pct: float = 0.1,
                 vol_factor: float = 0.8) -> None:
        # bars_fn(symbol) -> today-inclusive 5-min bars, oldest-first, each
        # {timestamp(ms UTC epoch), open, close, volume, ...}. clock() -> aware IST datetime.
        self._bars_fn = bars_fn
        self._clock = clock or (lambda: datetime.now(_IST))
        self._tol = fade_tolerance_pct
        self._vol_factor = vol_factor   # today first-15 vol must be >= factor * prior avg

    @classmethod
    def from_config(cls, config: dict) -> "FirstFifteenProvider":
        f15 = config.get("entry_threshold", {}).get("first15_gate", {})
        from services.fyers_client.fyers_data_provider import FyersDataProvider
        fyers = FyersDataProvider.from_config(config)

        def bars_fn(symbol: str) -> list[dict]:
            # ~5 sessions of 5-min bars so the volume baseline has prior days to average.
            return fyers.ohlcv(symbol, interval="5", lookback=375)

        return cls(bars_fn, fade_tolerance_pct=float(f15.get("fade_tolerance_pct", 0.1)),
                   vol_factor=float(f15.get("vol_factor", 0.8)))

    def gap_status(self, symbol: str) -> str | None:
        """§4 gate 3: 'held' only when price holds the gap AND first-15 volume is above normal.
        'faded' if price fell back below the open. 'weak_volume' if price held but volume was
        thin vs the prior-session first-15 average. None when it can't be judged (fail-open)."""
        now = self._clock().astimezone(_IST)
        if now.time() < _WINDOW_END:
            return None  # window not complete yet — can't confirm
        try:
            bars = self._bars_fn(symbol) or []
        except Exception as exc:
            _log.warning("first-15 bars fetch failed for %s: %s", symbol, exc)
            return None

        today = now.date()
        by_day: dict = {}
        for b in bars:
            by_day.setdefault(_ist(b["timestamp"]).date(), []).append(b)
        todays = by_day.get(today, [])
        window = [b for b in todays if _OPEN <= _ist(b["timestamp"]).time() < _WINDOW_END]
        if not todays or not window:
            return None

        # (a) price holding the gap
        day_open = float(todays[0]["open"])
        last_close = float(window[-1]["close"])
        if last_close < day_open * (1 - self._tol / 100.0):
            return "faded"

        # (b) volume above normal — today's first-15 vol vs prior sessions' first-15 avg
        today_vol = sum(float(b.get("volume", 0)) for b in window)
        prior = [d for d in by_day if d != today]
        prior_first15 = []
        for d in prior:
            fv = sum(float(b.get("volume", 0)) for b in by_day[d]
                     if _OPEN <= _ist(b["timestamp"]).time() < _WINDOW_END)
            if fv > 0:
                prior_first15.append(fv)
        if prior_first15:
            avg = sum(prior_first15) / len(prior_first15)
            if today_vol < avg * self._vol_factor:
                return "weak_volume"
        return "held"


def _ist(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=_IST)

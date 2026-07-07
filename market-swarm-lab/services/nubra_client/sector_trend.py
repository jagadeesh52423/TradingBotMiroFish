"""NSE sector-index trend for a symbol — the tailwind/headwind check.

Playbook §10/§11: a lone-stock catalyst fighting a falling sector index is a weaker
trade; "sector index moving hard against your catalyst direction" is a trade-killer.
This provider maps a symbol to its sector index and reports whether that index is
trending up or down (last close vs an N-day SMA). Fails safe: returns None when the
symbol is unmapped, data is thin, or the fetch errors — the gate then allows.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

_log = logging.getLogger(__name__)

_DEFAULT_LOOKBACK = 20
_DEFAULT_MIN_BARS = 10

# Bundled snapshot of {NSE:<sector>-INDEX: [members]} from NSE sector-index constituents.
# Constituents change ~monthly, so a committed snapshot is a robust default that removes any
# runtime dependency on niftyindices.com (which throttles). Refresh via build_sector_snapshot.py.
_SNAPSHOT = Path(__file__).parent / "fixtures" / "sector_constituents.json"


def load_dynamic_sector_map() -> dict[str, str]:
    """Build {SYMBOL: NSE:<sector>-INDEX} from the bundled sector-constituent snapshot.

    Covers every member of each NSE sector index (auto-updating when the snapshot is refreshed),
    replacing a hardcoded map. A stock in no sector index stays unmapped — the gate then fails
    open (honest: there's no sector-index tailwind to check for it).
    """
    if not _SNAPSHOT.exists():
        _log.warning("sector snapshot %s missing — sector map empty (gate fails open)", _SNAPSHOT)
        return {}
    try:
        data = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("sector snapshot unreadable: %s", exc)
        return {}
    out: dict[str, str] = {}
    for index_symbol, members in data.items():
        for sym in members:
            out.setdefault(str(sym).upper(), index_symbol)  # first index wins on overlap
    return out


class SectorTrendProvider:
    """Resolves a symbol's sector index and classifies its trend as 'up' | 'down' | None."""

    def __init__(self, sector_map: dict, closes_fn, lookback: int = _DEFAULT_LOOKBACK,
                 min_bars: int = _DEFAULT_MIN_BARS) -> None:
        # closes_fn(index_symbol) -> list[float] recent closes, oldest-first.
        self._map = {k.upper(): v for k, v in (sector_map or {}).items()}
        self._closes_fn = closes_fn
        self._lookback = lookback
        self._min_bars = min_bars
        # Per-index memo cache: a run of ~150 symbols maps to a handful of unique sector
        # indices, so without this each symbol re-triggers its own live Fyers history
        # fetch for the same index — 150+ fetches instead of ~15, which throttles Fyers
        # and silently degrades the gate to None. Fetched once per index per run
        # (failures are memoized as None too, so a bad index isn't retried every call).
        self._closes_cache: dict[str, list[float] | None] = {}
        self._cache_lock = threading.Lock()

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

        # Dynamic map (all sector-index members, auto-updating) + config static map as override.
        sector_map: dict[str, str] = {}
        if sg.get("dynamic", True):
            sector_map.update(load_dynamic_sector_map())
        sector_map.update({k.upper(): v for k, v in (sg.get("sector_map") or {}).items()})  # override wins
        return cls(sector_map, closes_fn, lookback, min_bars)

    def trend(self, symbol: str) -> str | None:
        index = self._map.get(symbol.upper())
        if not index:
            return None  # unmapped symbol — no opinion
        closes = self._closes_for(index)
        if closes is None:
            return None
        if len(closes) < self._min_bars:
            return None
        window = closes[-self._lookback:]
        sma = sum(window) / len(window)
        return "up" if closes[-1] >= sma else "down"

    def _closes_for(self, index: str) -> list[float] | None:
        """Memoized closes fetch for one sector index — at most one live fetch per
        index per run, regardless of how many symbols map to it or how many threads
        ask concurrently."""
        if index in self._closes_cache:
            return self._closes_cache[index]
        with self._cache_lock:
            if index in self._closes_cache:  # re-check inside the lock
                return self._closes_cache[index]
            try:
                closes = [float(c) for c in (self._closes_fn(index) or [])]
            except Exception as exc:
                _log.warning("sector index fetch failed for %s: %s", index, exc)
                closes = None
            self._closes_cache[index] = closes
            return closes

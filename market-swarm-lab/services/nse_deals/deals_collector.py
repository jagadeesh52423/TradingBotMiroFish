"""NSE bulk & block deals collector (§7/§8).

Playbook §7/§8: an institution buying the same name that just had a catalyst is a strong
stacking + confirmation signal. NSE publishes daily bulk/block deals as CSVs on nsearchives
(same host as the sec-bhavcopy — no anti-bot 503, unlike the live API). One fetch covers all
symbols; per-symbol we report net institutional buy/sell in the deals.
"""
from __future__ import annotations

import csv
import io
import logging
import threading
import time
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_BULK_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
_BLOCK_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_CACHE_TTL = 3600  # EOD reports — refresh hourly is plenty


class NseDealsCollector:
    """Latest bulk/block deals keyed by symbol, with cache; fails safe to empty (no fixture
    fallback in the live path — a fetch failure must never be reported as a real deal)."""

    def __init__(self, session: requests.Session | None = None, cache_ttl_seconds: int = _CACHE_TTL) -> None:
        self._session = session
        self._lock = threading.Lock()          # guards session build
        self._snap_lock = threading.Lock()     # guards the shared-snapshot fetch (separate lock
        self._cache_ttl = cache_ttl_seconds    # to avoid re-entrancy with _lock via _fetch)
        self._by_symbol: dict[str, list[dict]] | None = None
        self._expiry = 0.0

    @classmethod
    def from_config(cls, config: dict) -> "NseDealsCollector":
        d = config.get("deals", {})
        return cls(cache_ttl_seconds=int(d.get("cache_ttl_seconds", _CACHE_TTL)))

    def deals(self, symbol: str) -> list[dict]:
        return self._snapshot().get(symbol.upper(), [])

    def flag(self, symbol: str) -> dict:
        """Per-symbol summary: {has_deal, net_qty (buy-sell), buy_count, sell_count}."""
        rows = self.deals(symbol)
        if not rows:
            return {"has_deal": False, "net_qty": 0, "buy_count": 0, "sell_count": 0}
        buys = sum(r["qty"] for r in rows if r["side"] == "BUY")
        sells = sum(r["qty"] for r in rows if r["side"] == "SELL")
        return {
            "has_deal": True, "net_qty": buys - sells,
            "buy_count": sum(1 for r in rows if r["side"] == "BUY"),
            "sell_count": sum(1 for r in rows if r["side"] == "SELL"),
            "clients": sorted({r["client"] for r in rows})[:5],
        }

    # ----------------------------------------------------------------- private

    def _snapshot(self) -> dict[str, list[dict]]:
        if self._by_symbol is not None and time.monotonic() < self._expiry:
            return self._by_symbol
        # One pair of CSV fetches serves all symbols: hold the lock across the fetch so that on
        # a cold cache exactly one runner thread fetches+parses the market-wide bulk/block feeds
        # while the others wait and then read the warm cache — instead of every thread piling
        # onto the endpoints. (Separate lock from _lock to avoid re-entering it via _fetch.)
        with self._snap_lock:
            if self._by_symbol is not None and time.monotonic() < self._expiry:
                return self._by_symbol  # another thread warmed the cache while we waited
            rows: list[dict] = []
            for kind, url in (("bulk", _BULK_URL), ("block", _BLOCK_URL)):
                try:
                    rows += _parse(self._fetch(url), kind)
                except Exception as exc:
                    # Fail-safe to empty (no_deal), not to the committed fixture: a live-fetch
                    # failure must never be reported as "an institutional deal happened today".
                    _log.warning("NSE %s deals fetch failed — no %s deals this run: %s", kind, kind, exc)
            by: dict[str, list[dict]] = {}
            for r in rows:
                by.setdefault(r["symbol"], []).append(r)
            self._by_symbol = by
            self._expiry = time.monotonic() + self._cache_ttl
            return by

    @retry(retry=retry_if_exception_type(requests.RequestException),
           stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _fetch(self, url: str) -> str:
        if self._session is None:
            with self._lock:
                if self._session is None:  # re-check inside the lock — build exactly once
                    session = requests.Session()
                    session.headers.update({"User-Agent": _UA})
                    self._session = session
        resp = self._session.get(url, headers={"Referer": "https://www.nseindia.com/"}, timeout=20)
        resp.raise_for_status()
        return resp.text


def _parse(text: str, kind: str) -> list[dict]:
    out: list[dict] = []
    for row in csv.DictReader(io.StringIO(text)):
        rr = {k.strip(): (v or "").strip() for k, v in row.items()}
        sym = (rr.get("Symbol") or "").upper()
        if not sym or sym == "NO RECORDS":
            continue
        try:
            qty = int(float((rr.get("Quantity Traded") or "0").replace(",", "")))
        except ValueError:
            qty = 0
        out.append({
            "symbol": sym, "kind": kind,
            "client": rr.get("Client Name") or "",
            "side": (rr.get("Buy/Sell") or "").upper(),
            "qty": qty, "date": rr.get("Date"),
        })
    return out


def _parse_fixture(kind: str) -> list[dict]:
    path = _FIXTURE_DIR / f"{kind}.csv"
    return _parse(path.read_text(encoding="utf-8"), kind) if path.exists() else []

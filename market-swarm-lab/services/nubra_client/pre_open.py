"""Pre-open call-auction conviction (§3/§11).

Playbook §3: the 09:00-09:15 IST pre-open gives an indicative equilibrium price (IEP)
and quantity. 'Thin quantity at a big indicated gap is low-conviction; heavy quantity
at the gap is higher-conviction' — and §11 lists thin pre-open qty behind a large gap
as a trade-killer. One NSE call returns all symbols; this caches the snapshot and reports
a per-symbol soft conviction. Never a gate (pre-open data is stale outside 09:00-09:15).

The NSE market-data-pre-open endpoint responds where quote-equity 403s, but still fails
safe to None (→ no opinion) on any error.
"""
from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_HOME = "https://www.nseindia.com"
_URL = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
_CACHE_TTL = 60


def pre_open_conviction(gap_pct, qty, cfg: dict | None = None) -> str | None:
    """'weak_thin_qty' (big gap, thin book), 'strong' (up gap, heavy book), else 'neutral'."""
    if gap_pct is None or qty is None:
        return None
    c = cfg or {}
    big = float(c.get("big_gap_pct", 1.0))
    min_qty = float(c.get("min_qty", 50_000))
    if abs(gap_pct) >= big and qty < min_qty:
        return "weak_thin_qty"
    if gap_pct >= big and qty >= min_qty:  # meaningful up-gap backed by a heavy book
        return "strong"
    return "neutral"


class PreOpenCollector:
    def __init__(self, session: requests.Session | None = None, cache_ttl_seconds: int = _CACHE_TTL) -> None:
        self._session = session
        self._primed = False
        self._cache_ttl = cache_ttl_seconds
        self._snap: dict | None = None
        self._expiry = 0.0

    @classmethod
    def from_config(cls, config: dict) -> "PreOpenCollector":
        po = config.get("pre_open", {}).get("conviction_flag", {})
        return cls(cache_ttl_seconds=int(po.get("cache_ttl_seconds", _CACHE_TTL)))

    def status(self, symbol: str) -> dict | None:
        snap = self._snapshot()
        return snap.get(symbol.upper()) if snap else None

    def _snapshot(self) -> dict:
        if self._snap is not None and time.monotonic() < self._expiry:
            return self._snap
        try:
            self._snap = _parse(self._fetch())
        except Exception as exc:
            _log.warning("NSE pre-open fetch failed: %s", exc)
            self._snap = {}
        self._expiry = time.monotonic() + self._cache_ttl
        return self._snap

    def _prime(self) -> None:
        if self._session is None:
            self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            self._session.get(_HOME, timeout=15)
        except Exception as exc:
            _log.warning("NSE prime failed (continuing): %s", exc)
        self._primed = True

    @retry(retry=retry_if_exception_type(requests.RequestException),
           stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _fetch(self) -> dict:
        if not self._primed:
            self._prime()
        resp = self._session.get(_URL, headers={"Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        return resp.json()


def _parse(data: dict) -> dict:
    out: dict = {}
    for row in data.get("data", []):
        md = row.get("metadata") or {}
        pom = (row.get("detail") or {}).get("preOpenMarket") or {}
        sym = md.get("symbol")
        if not sym:
            continue
        iep = md.get("iep") or pom.get("IEP")
        qty = md.get("finalQuantity") or pom.get("finalQuantity") \
            or (pom.get("totalBuyQuantity", 0) + pom.get("totalSellQuantity", 0))
        out[sym.upper()] = {
            "iep": iep,
            "prev_close": md.get("previousClose"),
            "gap_pct": md.get("pChange"),
            "qty": qty,
        }
    return out

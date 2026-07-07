"""NSE shareholding-pattern collector (§2/§9 — the '13F equivalent').

Two clean NSE signals:
  - per-symbol PROMOTER stake trend quarter-over-quarter (promoter buying/selling into their own
    stock is a §9 conviction signal), and
  - market-wide daily FII/DII net cash flow (breadth/sentiment context).

Both endpoints respond where quote-equity 403s (same session pattern as announcements).
Soft flags only — never gate. Fail-safe to None/neutral.
"""
from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_HOME = "https://www.nseindia.com"
_SHP_API = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={symbol}"
_FIIDII_API = "https://www.nseindia.com/api/fiidiiTradeReact"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
_CACHE_TTL = 6 * 3600  # shareholding is quarterly; FII/DII daily — 6h cache is fine


class ShareholdingCollector:
    def __init__(self, session: requests.Session | None = None, cache_ttl_seconds: int = _CACHE_TTL) -> None:
        self._session = session
        self._primed = False
        self._cache_ttl = cache_ttl_seconds
        self._promoter_cache: dict[str, tuple[dict, float]] = {}
        self._fiidii: tuple[dict, float] | None = None

    @classmethod
    def from_config(cls, config: dict) -> "ShareholdingCollector":
        sh = config.get("shareholding", {})
        return cls(cache_ttl_seconds=int(sh.get("cache_ttl_seconds", _CACHE_TTL)))

    def promoter_flag(self, symbol: str) -> dict:
        """Latest promoter % + change vs prior quarter: {promoter_pct, change_pct, trend}."""
        symbol = symbol.upper()
        cached = self._promoter_cache.get(symbol)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        try:
            flag = _promoter_trend(self._fetch(_SHP_API.format(symbol=symbol)))
        except Exception as exc:
            _log.warning("shareholding fetch failed for %s: %s", symbol, exc)
            flag = {"promoter_pct": None, "change_pct": None, "trend": None}
        self._promoter_cache[symbol] = (flag, time.monotonic() + self._cache_ttl)
        return flag

    def fii_dii_flow(self) -> dict:
        """Market-wide latest FII + DII net cash flow (₹cr) + a combined breadth sign."""
        if self._fiidii and time.monotonic() < self._fiidii[1]:
            return self._fiidii[0]
        try:
            flow = _fii_dii(self._fetch(_FIIDII_API, referer=_HOME))
        except Exception as exc:
            _log.warning("FII/DII flow fetch failed: %s", exc)
            flow = {"fii_net": None, "dii_net": None, "net": None, "breadth": None}
        self._fiidii = (flow, time.monotonic() + self._cache_ttl)
        return flow

    # ----------------------------------------------------------------- private

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
    def _fetch(self, url: str, referer: str = _REFERER):
        if not self._primed:
            self._prime()
        resp = self._session.get(url, headers={"Referer": referer, "Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        return resp.json()


def _to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _promoter_trend(rows: list) -> dict:
    """rows are quarterly filings newest-first with `pr_and_prgrp` (promoter %)."""
    pcts = [p for r in rows if (p := _to_float((r or {}).get("pr_and_prgrp"))) is not None]
    if not pcts:
        return {"promoter_pct": None, "change_pct": None, "trend": None}
    latest = pcts[0]
    prior = pcts[1] if len(pcts) > 1 else None
    change = round(latest - prior, 2) if prior is not None else None
    trend = None
    if change is not None:
        trend = "rising" if change > 0.01 else "falling" if change < -0.01 else "flat"
    return {"promoter_pct": latest, "change_pct": change, "trend": trend}


def _fii_dii(rows: list) -> dict:
    fii = dii = None
    for r in rows or []:
        cat = (r.get("category") or "").upper()
        net = _to_float(r.get("netValue"))
        if "FII" in cat or "FPI" in cat:
            fii = net
        elif "DII" in cat:
            dii = net
    total = None
    if fii is not None or dii is not None:
        total = round((fii or 0) + (dii or 0), 2)
    breadth = None
    if total is not None:
        breadth = "buying" if total > 0 else "selling" if total < 0 else "flat"
    return {"fii_net": fii, "dii_net": dii, "net": total, "breadth": breadth}

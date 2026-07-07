"""NSE insider-trading (SAST/PIT) disclosures collector (§9).

The India equivalent of a Form 4: promoter/insider Buy/Sell/Pledge disclosures filed
under PIT Reg. 7(2). Per-symbol from NSE's corporates-pit API (reachable where quote-equity
403s, same cookie-primed session pattern as the announcements collector). Emits attchmntText
items into the shared sentiment engine + adds a catalyst source for §7 stacking.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_HOME = "https://www.nseindia.com"
_API = "https://www.nseindia.com/api/corporates-pit?index=equities&symbol={symbol}"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_CACHE_TTL = 900
_DEFAULT_MAX = 15


class NseInsiderCollector:
    def __init__(self, session: requests.Session | None = None, max_items: int = _DEFAULT_MAX,
                 cache_ttl_seconds: int = _CACHE_TTL, analyzer=None) -> None:
        self._session = session
        self._primed = False
        self._max = max_items
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[list[dict], float]] = {}
        if analyzer is None:
            from services.nse_announcements.sentiment_analyzer import KeywordSentimentAnalyzer
            analyzer = KeywordSentimentAnalyzer()
        self._analyzer = analyzer

    @classmethod
    def from_config(cls, config: dict) -> "NseInsiderCollector":
        from services.nse_announcements.sentiment_analyzer import get_analyzer
        i = config.get("news", {}).get("insider", {})
        engine = config.get("nse", {}).get("sentiment_engine", "keyword")
        return cls(max_items=int(i.get("max_items", _DEFAULT_MAX)),
                   cache_ttl_seconds=int(i.get("cache_ttl_seconds", _CACHE_TTL)),
                   analyzer=get_analyzer(engine, config))

    def fetch(self, symbol: str) -> tuple[list[dict], str]:
        symbol = symbol.upper()
        cached = self._cache.get(symbol)
        if cached and time.monotonic() < cached[1]:
            return cached[0], "insider_live"
        try:
            items = self._fetch(symbol)[: self._max]
            self._cache[symbol] = (items, time.monotonic() + self._cache_ttl)
            return items, "insider_live"
        except Exception as exc:
            _log.warning("NSE insider fetch failed for %s: %s", symbol, exc)
            return self._load_fixture(symbol)[: self._max], "fixture_fallback"

    def collect(self, symbol: str) -> dict[str, Any]:
        items, mode = self.fetch(symbol)
        result = self._analyzer.analyze(items)
        return {
            "symbol": symbol.upper(), "provider_mode": mode, "items": items,
            "documents": [{"source": "insider", "content": i.get("attchmntText", "")}
                          for i in items if i.get("attchmntText")],
            "sentiment_score": round(result.sentiment_score, 4),
            "sentiment_label": result.sentiment_label, "sentiment_engine": result.engine,
        }

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
    def _fetch(self, symbol: str) -> list[dict]:
        if not self._primed:
            self._prime()
        resp = self._session.get(_API.format(symbol=symbol),
                                 headers={"Referer": _REFERER, "Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        return _parse(resp.json())

    def _load_fixture(self, symbol: str) -> list[dict]:
        path = _FIXTURE_DIR / f"insider_{symbol}.json"
        if path.exists():
            import json
            return _parse(json.loads(path.read_text(encoding="utf-8")))
        return []


def _parse(payload: dict) -> list[dict]:
    items: list[dict] = []
    for r in (payload or {}).get("data", []):
        txn = (r.get("tdpTransactionType") or "").strip()
        acq = (r.get("acqName") or "").strip()
        if not txn and not acq:
            continue
        cat = (r.get("personCategory") or "").strip()
        val = r.get("secVal")
        items.append({
            "attchmntText": f"Insider {txn} by {acq} ({cat}); value {val}".strip(),
            "transaction_type": txn, "person_category": cat, "date": r.get("date"),
            "source": "insider",
        })
    return items

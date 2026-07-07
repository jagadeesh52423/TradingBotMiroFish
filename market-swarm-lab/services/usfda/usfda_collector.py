"""USFDA drug-enforcement (recall) collector for Indian pharma exporters (§9).

Keyless openFDA REST API. Maps an NSE symbol to its USFDA recalling-firm name (config)
and pulls recent drug recalls — a clear bearish catalyst for generics exporters. Emits
attchmntText items into the shared sentiment engine, same shape as the other collectors.

Only mapped pharma symbols query the API; everything else returns no items (fail-open).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_API = ('https://api.fda.gov/drug/enforcement.json'
        '?search=recalling_firm:"{firm}"&limit={limit}&sort=report_date:desc')
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_CACHE_TTL = 3600  # recalls are slow (daily-ish); cache an hour
_DEFAULT_LIMIT = 10


class UsfdaCollector:
    def __init__(self, symbol_map: dict, session: requests.Session | None = None,
                 limit: int = _DEFAULT_LIMIT, cache_ttl_seconds: int = _CACHE_TTL, analyzer=None) -> None:
        self._map = {k.upper(): v for k, v in (symbol_map or {}).items()}
        self._session = session
        self._limit = limit
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[list[dict], float]] = {}
        if analyzer is None:
            from services.nse_announcements.sentiment_analyzer import KeywordSentimentAnalyzer
            analyzer = KeywordSentimentAnalyzer()
        self._analyzer = analyzer

    @classmethod
    def from_config(cls, config: dict) -> "UsfdaCollector":
        from services.nse_announcements.sentiment_analyzer import get_analyzer
        u = config.get("news", {}).get("usfda", {})
        engine = config.get("nse", {}).get("sentiment_engine", "keyword")
        return cls(u.get("symbol_map", {}), limit=int(u.get("limit", _DEFAULT_LIMIT)),
                   cache_ttl_seconds=int(u.get("cache_ttl_seconds", _CACHE_TTL)),
                   analyzer=get_analyzer(engine, config))

    def fetch(self, symbol: str) -> tuple[list[dict], str]:
        symbol = symbol.upper()
        firm = self._map.get(symbol)
        if not firm:
            return [], "no_mapping"  # not a mapped USFDA-exposed pharma name
        cached = self._cache.get(symbol)
        if cached and time.monotonic() < cached[1]:
            return cached[0], "usfda_live"
        try:
            items = self._fetch(firm)
            self._cache[symbol] = (items, time.monotonic() + self._cache_ttl)
            return items, "usfda_live"
        except Exception as exc:
            _log.warning("USFDA fetch failed for %s (%s): %s", symbol, firm, exc)
            return self._load_fixture(symbol), "fixture_fallback"

    def collect(self, symbol: str) -> dict[str, Any]:
        items, mode = self.fetch(symbol)
        result = self._analyzer.analyze(items)
        return {
            "symbol": symbol.upper(), "provider_mode": mode, "items": items,
            "documents": [{"source": "usfda", "content": i.get("attchmntText", "")}
                          for i in items if i.get("attchmntText")],
            "sentiment_score": round(result.sentiment_score, 4),
            "sentiment_label": result.sentiment_label,
            "sentiment_engine": result.engine,
        }

    @retry(retry=retry_if_exception_type(requests.RequestException),
           stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _fetch(self, firm: str) -> list[dict]:
        if self._session is None:
            self._session = requests.Session()
        url = _API.format(firm=quote(firm), limit=self._limit)
        resp = self._session.get(url, timeout=15)
        if resp.status_code == 404:
            return []  # openFDA returns 404 for a firm with zero recalls — legitimately empty
        resp.raise_for_status()
        return _parse(resp.json())

    def _load_fixture(self, symbol: str) -> list[dict]:
        path = _FIXTURE_DIR / f"usfda_{symbol}.json"
        if path.exists():
            import json
            return _parse(json.loads(path.read_text(encoding="utf-8")))
        return []


def _parse(payload: dict) -> list[dict]:
    items: list[dict] = []
    for r in (payload or {}).get("results", []):
        product = (r.get("product_description") or "").strip()
        reason = (r.get("reason_for_recall") or "").strip()
        cls = r.get("classification") or ""
        if not (product or reason):
            continue
        # A recall is bearish — keyword scorer already weights 'recall' bearish.
        items.append({
            "attchmntText": f"USFDA recall ({cls}): {product} — {reason}".strip(),
            "report_date": r.get("report_date"),
            "classification": cls,
            "source": "usfda",
        })
    return items

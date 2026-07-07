"""Google News RSS collector for Indian-equity news sentiment.

Keyless — hits Google News' public RSS search endpoint (no API, no token) and
scores headline sentiment with the same pluggable engine the NSE collector uses
(keyword / ai / ollama). Emits items with an ``attchmntText`` field so the
sentiment analyzers consume them unchanged.

# implement this interface to add another Indian-equity news source
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

# India edition: English, geo IN. `when:Nd` bounds recency server-side.
_RSS_URL = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
_DEFAULT_QUERY = '"{symbol}" (stock OR share) when:{lookback}d'
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_CACHE_TTL_SECONDS = 900  # 15 min — headlines are slow-changing intraday
_DEFAULT_MAX_ITEMS = 20
_DEFAULT_LOOKBACK_DAYS = 7


class GoogleNewsCollector:
    """Collects recent Google News headlines for a symbol with caching + fixture fallback."""

    def __init__(
        self,
        session: requests.Session | None = None,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        max_items: int = _DEFAULT_MAX_ITEMS,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
        query_template: str = _DEFAULT_QUERY,
        analyzer: "Any | None" = None,
    ) -> None:
        self._session = session
        self._lookback_days = lookback_days
        self._max_items = max_items
        self._cache_ttl = cache_ttl_seconds
        self._query_template = query_template
        self._cache: dict[str, tuple[list[dict], float]] = {}
        if analyzer is None:
            from services.nse_announcements.sentiment_analyzer import KeywordSentimentAnalyzer
            analyzer = KeywordSentimentAnalyzer()
        self._analyzer = analyzer

    @classmethod
    def from_config(cls, config: dict) -> "GoogleNewsCollector":
        """Build from the top-level nubra_config dict (reads news.google, shares nse.sentiment_engine)."""
        from services.nse_announcements.sentiment_analyzer import get_analyzer

        g_cfg = config.get("news", {}).get("google", {})
        engine = config.get("nse", {}).get("sentiment_engine", "keyword")
        return cls(
            lookback_days=int(g_cfg.get("lookback_days", _DEFAULT_LOOKBACK_DAYS)),
            max_items=int(g_cfg.get("max_items", _DEFAULT_MAX_ITEMS)),
            cache_ttl_seconds=int(g_cfg.get("cache_ttl_seconds", _CACHE_TTL_SECONDS)),
            query_template=g_cfg.get("query_template", _DEFAULT_QUERY),
            analyzer=get_analyzer(engine, config),
        )

    # ------------------------------------------------------------------ public

    def fetch(self, symbol: str) -> tuple[list[dict], str]:
        """Return (items, provider_mode) without scoring — for aggregation over sources."""
        symbol = symbol.upper()
        cached = self._from_cache(symbol)
        if cached is not None:
            return cached, "google_live"
        try:
            items = self._fetch(symbol)
            self._cache[symbol] = (items, time.monotonic() + self._cache_ttl)
            return items, "google_live"
        except Exception as exc:
            _log.warning("Google News fetch failed for %s: %s", symbol, exc)
            return self._load_fixture(symbol), "fixture_fallback"

    def collect(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        items, provider_mode = self.fetch(symbol)
        result = self._analyzer.analyze(items)

        return {
            "symbol": symbol,
            "provider_mode": provider_mode,
            "items": items,
            "documents": [
                {"source": "google_news", "content": item.get("attchmntText", "")}
                for item in items
                if item.get("attchmntText")
            ],
            "sentiment_score": round(result.sentiment_score, 4),
            "sentiment_label": result.sentiment_label,
            "sentiment_confidence": round(result.confidence, 4),
            "sentiment_reasoning": result.reasoning,
            "sentiment_engine": result.engine,
            "source_audit": {
                "google_news": {
                    "status": "live" if provider_mode == "google_live" else "fallback",
                    "count": len(items),
                    "engine": result.engine,
                    "degraded": result.degraded,
                }
            },
        }

    # ----------------------------------------------------------------- private

    def _from_cache(self, symbol: str) -> list[dict] | None:
        entry = self._cache.get(symbol)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        return None

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _fetch(self, symbol: str) -> list[dict]:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": _BROWSER_UA})
        query = self._query_template.format(symbol=symbol, lookback=self._lookback_days)
        url = _RSS_URL.format(q=quote(query))
        resp = self._session.get(url, timeout=15)
        resp.raise_for_status()
        return _parse_rss(resp.text)[: self._max_items]

    def _load_fixture(self, symbol: str) -> list[dict]:
        path = _FIXTURE_DIR / f"google_news_{symbol}.xml"
        if path.exists():
            return _parse_rss(path.read_text(encoding="utf-8"))[: self._max_items]
        _log.info("No Google News fixture for %s — returning empty news", symbol)
        return []


# -------------------------------------------------------------------- helpers

def _parse_rss(xml_text: str) -> list[dict]:
    """Parse a Google News RSS feed into sentiment-ready items.

    Each item exposes ``attchmntText`` (the headline — the clean signal) plus
    ``title``/``link``/``pubDate``/``source`` metadata. Malformed feeds raise
    ET.ParseError, which the caller treats as a fetch failure.
    """
    root = ET.fromstring(xml_text)
    items: list[dict] = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source_el = item.find("source")
        items.append({
            "attchmntText": title,
            "title": title,
            "link": (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "source": (source_el.text or "").strip() if source_el is not None else "",
        })
    return items

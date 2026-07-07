"""PIB (Press Information Bureau) press-release collector (§9).

PIB releases often precede the formal exchange filing (e.g. a defense order win). The
feed is government-wide, so per-symbol relevance is only meaningful for explicitly mapped
names — this collector fires ONLY for symbols in a config name-map, matching release
titles/descriptions against that name's terms. Best-effort; fail-safe to no items.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

# Ministry-agnostic PIB RSS (all releases, English). Override via config if needed.
_DEFAULT_FEED = "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
_CACHE_TTL = 1800


class PibCollector:
    def __init__(self, symbol_map: dict, feed_url: str = _DEFAULT_FEED,
                 session: requests.Session | None = None, cache_ttl_seconds: int = _CACHE_TTL,
                 analyzer=None) -> None:
        # symbol_map: {SYMBOL: [term, ...]} — release must contain a term to match the symbol.
        self._map = {k.upper(): [t.lower() for t in v] for k, v in (symbol_map or {}).items()}
        self._feed_url = feed_url
        self._session = session
        self._cache_ttl = cache_ttl_seconds
        self._items: list[dict] | None = None
        self._expiry = 0.0
        if analyzer is None:
            from services.nse_announcements.sentiment_analyzer import KeywordSentimentAnalyzer
            analyzer = KeywordSentimentAnalyzer()
        self._analyzer = analyzer

    @classmethod
    def from_config(cls, config: dict) -> "PibCollector":
        from services.nse_announcements.sentiment_analyzer import get_analyzer
        p = config.get("news", {}).get("pib", {})
        engine = config.get("nse", {}).get("sentiment_engine", "keyword")
        return cls(p.get("symbol_map", {}), feed_url=p.get("feed_url", _DEFAULT_FEED),
                   analyzer=get_analyzer(engine, config))

    def fetch(self, symbol: str) -> tuple[list[dict], str]:
        terms = self._map.get(symbol.upper())
        if not terms:
            return [], "no_mapping"
        feed = self._feed()
        matched = [it for it in feed
                   if any(t in (it["attchmntText"]).lower() for t in terms)]
        return matched, ("pib_live" if feed else "fixture_fallback")

    def collect(self, symbol: str) -> dict[str, Any]:
        items, mode = self.fetch(symbol)
        result = self._analyzer.analyze(items)
        return {
            "symbol": symbol.upper(), "provider_mode": mode, "items": items,
            "documents": [{"source": "pib", "content": i.get("attchmntText", "")}
                          for i in items if i.get("attchmntText")],
            "sentiment_score": round(result.sentiment_score, 4),
            "sentiment_label": result.sentiment_label, "sentiment_engine": result.engine,
        }

    def _feed(self) -> list[dict]:
        if self._items is not None and time.monotonic() < self._expiry:
            return self._items
        try:
            self._items = _parse_rss(self._fetch_feed())
        except Exception as exc:
            _log.warning("PIB feed fetch failed: %s", exc)
            self._items = []
        self._expiry = time.monotonic() + self._cache_ttl
        return self._items

    @retry(retry=retry_if_exception_type(requests.RequestException),
           stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _fetch_feed(self) -> str:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": _UA})
        resp = self._session.get(self._feed_url, timeout=15)
        resp.raise_for_status()
        return resp.text


def _parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items: list[dict] = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if not title:
            continue
        items.append({"attchmntText": f"{title}. {desc}".strip(),
                      "title": title, "link": (item.findtext("link") or "").strip(),
                      "source": "pib"})
    return items

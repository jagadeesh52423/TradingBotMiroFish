"""India retail social-sentiment collector (Reddit) — §9 social source.

Reddit blocks unauthenticated JSON (403), so this uses the free app-only OAuth flow
(client_credentials — needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET, no user password).
Searches the India investing subs per symbol and emits attchmntText items into the shared
sentiment engine, like the other collectors.

Caveat: Indian retail Reddit is thin/noisy vs US — treat as low-weight colour, not signal.
Fails safe: no creds or any error -> fixture -> empty. Never crashes the scan.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = ("https://oauth.reddit.com/r/{subs}/search"
               "?q={q}&restrict_sr=1&sort=new&limit={limit}&t=week")
_UA = "python:market-swarm-lab-india:v1 (equity screener research)"
_DEFAULT_SUBS = ["IndianStreetBets", "IndianStockMarket", "DalalStreetTalks"]
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_CACHE_TTL = 900
_DEFAULT_LIMIT = 15


class IndiaRedditCollector:
    def __init__(self, subreddits: list[str] | None = None, client_id: str | None = None,
                 client_secret: str | None = None, limit: int = _DEFAULT_LIMIT,
                 cache_ttl_seconds: int = _CACHE_TTL, analyzer=None) -> None:
        self._subs = "+".join(subreddits or _DEFAULT_SUBS)
        self._cid = client_id
        self._secret = client_secret
        self._limit = limit
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[list[dict], float]] = {}
        self._token: str | None = None
        self._token_expiry = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA})
        if analyzer is None:
            from services.nse_announcements.sentiment_analyzer import KeywordSentimentAnalyzer
            analyzer = KeywordSentimentAnalyzer()
        self._analyzer = analyzer

    @classmethod
    def from_config(cls, config: dict) -> "IndiaRedditCollector":
        from services.nse_announcements.sentiment_analyzer import get_analyzer
        r = config.get("news", {}).get("reddit", {})
        engine = config.get("nse", {}).get("sentiment_engine", "keyword")
        return cls(
            subreddits=r.get("subreddits"),
            client_id=os.environ.get("REDDIT_CLIENT_ID"),
            client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
            limit=int(r.get("limit", _DEFAULT_LIMIT)),
            cache_ttl_seconds=int(r.get("cache_ttl_seconds", _CACHE_TTL)),
            analyzer=get_analyzer(engine, config),
        )

    def fetch(self, symbol: str) -> tuple[list[dict], str]:
        symbol = symbol.upper()
        if not (self._cid and self._secret):
            return self._load_fixture(symbol), "no_credentials"
        cached = self._cache.get(symbol)
        if cached and time.monotonic() < cached[1]:
            return cached[0], "reddit_live"
        try:
            items = self._search(symbol)[: self._limit]
            self._cache[symbol] = (items, time.monotonic() + self._cache_ttl)
            return items, "reddit_live"
        except Exception as exc:
            _log.warning("Reddit fetch failed for %s: %s", symbol, exc)
            return self._load_fixture(symbol), "fixture_fallback"

    def collect(self, symbol: str) -> dict[str, Any]:
        items, mode = self.fetch(symbol)
        result = self._analyzer.analyze(items)
        return {
            "symbol": symbol.upper(), "provider_mode": mode, "items": items,
            "documents": [{"source": "reddit", "content": i.get("attchmntText", "")}
                          for i in items if i.get("attchmntText")],
            "sentiment_score": round(result.sentiment_score, 4),
            "sentiment_label": result.sentiment_label, "sentiment_engine": result.engine,
        }

    def _bearer(self) -> str:
        if self._token and time.monotonic() < self._token_expiry:
            return self._token
        resp = self._session.post(
            _TOKEN_URL, auth=(self._cid, self._secret),
            data={"grant_type": "client_credentials"}, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.monotonic() + int(body.get("expires_in", 3600)) - 60
        return self._token

    @retry(retry=retry_if_exception_type(requests.RequestException),
           stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _search(self, symbol: str) -> list[dict]:
        url = _SEARCH_URL.format(subs=self._subs, q=quote(f'"{symbol}"'), limit=self._limit)
        resp = self._session.get(url, headers={"Authorization": f"Bearer {self._bearer()}"}, timeout=15)
        resp.raise_for_status()
        return _parse(resp.json())

    def _load_fixture(self, symbol: str) -> list[dict]:
        path = _FIXTURE_DIR / f"reddit_{symbol}.json"
        if path.exists():
            import json
            return _parse(json.loads(path.read_text(encoding="utf-8")))
        return []


def _parse(payload: dict) -> list[dict]:
    items: list[dict] = []
    for child in (payload or {}).get("data", {}).get("children", []):
        d = child.get("data") or {}
        title = (d.get("title") or "").strip()
        if not title:
            continue
        body = (d.get("selftext") or "").strip()[:500]
        items.append({
            "attchmntText": f"{title}. {body}".strip(),
            "subreddit": d.get("subreddit"), "score": d.get("score"),
            "num_comments": d.get("num_comments"), "source": "reddit",
        })
    return items

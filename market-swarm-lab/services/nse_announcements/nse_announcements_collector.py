"""NSE corporate-filings announcements collector.

Fetches recent announcements from NSE's corporate-filings API and scores their
sentiment using lightweight keyword matching.

Session priming: NSE requires a browser-like request to the homepage to obtain
cookies before the API will respond. The session is primed lazily on first use
and reused across symbols in the same collector instance.

# implement this interface to add a new Indian-equity event/news source
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_NSE_HOME = "https://www.nseindia.com"
_NSE_API = (
    "https://www.nseindia.com/api/corporate-announcements"
    "?index=equities&symbol={symbol}&from_date={from_d}&to_date={to_d}"
)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
_FIXTURE_DIR = Path(__file__).parent / "fixtures"

_BULLISH_KW: frozenset[str] = frozenset({
    "dividend", "bonus", "buyback", "acquisition", "profit", "growth",
    "order", "win", "upgrade", "record", "earnings", "expansion",
})
_BEARISH_KW: frozenset[str] = frozenset({
    "fine", "penalty", "default", "loss", "fraud", "investigation",
    "downgrade", "delay", "insolvency", "restructur", "litigation", "adverse",
})

_CACHE_TTL_SECONDS = 900  # 15 minutes — announcements are slow-changing


class NseAnnouncementsCollector:
    """Collects recent NSE corporate announcements for a symbol with caching + fallback."""

    def __init__(
        self,
        session: requests.Session | None = None,
        lookback_days: int = 7,
    ) -> None:
        self._session = session
        self._lookback_days = lookback_days
        self._primed = False
        self._cache: dict[str, tuple[list[dict], float]] = {}  # symbol → (items, expiry)

    # ------------------------------------------------------------------ public

    def collect(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        cached = self._from_cache(symbol)
        if cached is not None:
            items, provider_mode = cached, "nse_live"
        else:
            try:
                items = self._fetch(symbol)
                self._cache[symbol] = (items, time.monotonic() + _CACHE_TTL_SECONDS)
                provider_mode = "nse_live"
            except Exception as exc:
                _log.warning("NSE fetch failed for %s: %s", symbol, exc)
                items = self._load_fixture(symbol)
                provider_mode = "fixture_fallback"

        sentiment_score = _score_sentiment(items)
        if sentiment_score > 0.1:
            sentiment_label = "bullish"
        elif sentiment_score < -0.1:
            sentiment_label = "bearish"
        else:
            sentiment_label = "neutral"

        return {
            "symbol": symbol,
            "provider_mode": provider_mode,
            "items": items,
            "documents": [
                {"source": "nse_filing", "content": item.get("attchmntText", "")}
                for item in items
                if item.get("attchmntText")
            ],
            "sentiment_score": round(sentiment_score, 4),
            "sentiment_label": sentiment_label,
            "source_audit": {
                "nse_announcements": {
                    "status": "live" if provider_mode == "nse_live" else "fallback",
                    "count": len(items),
                }
            },
        }

    # ----------------------------------------------------------------- private

    def _from_cache(self, symbol: str) -> list[dict] | None:
        entry = self._cache.get(symbol)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        return None

    def _prime_session(self) -> None:
        if self._session is None:
            self._session = requests.Session()
        self._session.headers.update({"User-Agent": _BROWSER_UA})
        try:
            self._session.get(_NSE_HOME, timeout=15)
        except Exception as exc:
            _log.warning("NSE homepage prime failed (continuing): %s", exc)
        self._primed = True

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _fetch(self, symbol: str) -> list[dict]:
        if not self._primed:
            self._prime_session()
        now = datetime.now(timezone.utc)
        from_d = (now - timedelta(days=self._lookback_days)).strftime("%d-%m-%Y")
        to_d = now.strftime("%d-%m-%Y")
        url = _NSE_API.format(symbol=symbol, from_d=from_d, to_d=to_d)
        resp = self._session.get(  # type: ignore[union-attr]
            url,
            headers={"Referer": _REFERER, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected NSE response shape for {symbol}: {type(data)}")
        return data

    def _load_fixture(self, symbol: str) -> list[dict]:
        path = _FIXTURE_DIR / f"nse_announcements_{symbol}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        _log.info("No NSE fixture for %s — returning empty announcements", symbol)
        return []


# -------------------------------------------------------------------- helpers

def _score_sentiment(items: list[dict]) -> float:
    """Keyword-based sentiment over announcement texts; clamped to [-1, 1]."""
    if not items:
        return 0.0
    score = 0.0
    for item in items:
        text = (item.get("attchmntText") or "").lower()
        score += sum(0.1 for kw in _BULLISH_KW if kw in text)
        score -= sum(0.1 for kw in _BEARISH_KW if kw in text)
    return max(-1.0, min(1.0, round(score, 4)))

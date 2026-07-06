"""NSE event-calendar collector.

Fetches the market-wide NSE event calendar (board meetings and their purposes:
results, dividends, buybacks, fund-raising, etc.) and classifies each event into a
coarse catalyst type. Mirrors NseAnnouncementsCollector: lazy cookie-primed session,
tenacity retry, 15-minute cache, fixture fallback for offline / self-check.

Session priming: NSE requires a browser-like request to the homepage to obtain
cookies before the API responds. Primed lazily on first fetch, reused across calls.

# implement/extend the catalyst map to add a new Indian-equity event category
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_NSE_HOME = "https://www.nseindia.com"
_NSE_EVENT_API = (
    "https://www.nseindia.com/api/event-calendar"
    "?index=equities&from_date={from_d}&to_date={to_d}"
)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"
_FIXTURE = Path(__file__).parent / "fixtures" / "nse_event_calendar.json"

_API_DATE_FMT = "%d-%m-%Y"     # request params: DD-MM-YYYY
_EVENT_DATE_FMT = "%d-%b-%Y"   # response 'date' field: DD-Mon-YYYY (e.g. 15-Jul-2026)
_CACHE_TTL_SECONDS = 900       # 15 minutes — the calendar is slow-changing

CATALYST_OTHER = "Other"
# Ordered (catalyst_type, keyword-substrings); FIRST match on the lowercased purpose+bm_desc
# wins. Open/Closed: a new catalyst type is a new tuple here (or a config override via
# config["event_calendar"]["catalyst_keywords"]) — no change to classify()/collect_range().
_DEFAULT_CATALYST_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Results", ("financial result", "results", "earnings", "quarterly")),
    ("Dividend", ("dividend",)),
    ("Buyback", ("buy back", "buyback", "buy-back")),
    ("FundRaising", ("fund rais", "raising of funds", "qip", "preferential",
                     "rights issue", "debenture", "ncd", "bond")),
]


class NseEventCalendarCollector:
    """Collects NSE event-calendar entries for a date range with caching + fixture fallback."""

    def __init__(
        self,
        session: requests.Session | None = None,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
        catalyst_keywords: list[tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self._session = session
        self._cache_ttl = cache_ttl_seconds
        self._primed = False
        self._cache: dict[tuple[str, str], tuple[list[dict], float]] = {}  # (from,to) → (events, expiry)
        self._catalyst_keywords = catalyst_keywords or _DEFAULT_CATALYST_KEYWORDS

    @classmethod
    def from_config(cls, config: dict) -> "NseEventCalendarCollector":
        cfg = config.get("event_calendar", {})
        raw = cfg.get("catalyst_keywords")  # {type: [keyword, ...]} — insertion order = priority
        keywords = [(ctype, tuple(kws)) for ctype, kws in raw.items()] if raw else None
        return cls(
            cache_ttl_seconds=int(cfg.get("cache_ttl_seconds", _CACHE_TTL_SECONDS)),
            catalyst_keywords=keywords,
        )

    # ------------------------------------------------------------------ public

    def collect_range(self, from_date: date, to_date: date) -> list[dict]:
        """Events in [from_date, to_date], each annotated with a `catalyst_type`."""
        from_d, to_d = from_date.strftime(_API_DATE_FMT), to_date.strftime(_API_DATE_FMT)
        cached = self._from_cache(from_d, to_d)
        if cached is not None:
            events = cached
        else:
            try:
                events = self._fetch(from_d, to_d)
                self._cache[(from_d, to_d)] = (events, time.monotonic() + self._cache_ttl)
            except Exception as exc:
                _log.warning("NSE event-calendar fetch failed (%s..%s): %s", from_d, to_d, exc)
                events = self._load_fixture()
        for event in events:
            event["catalyst_type"] = self.classify(event.get("purpose", ""), event.get("bm_desc", ""))
        return events

    def filter_whitelist(self, events: list[dict], whitelist) -> list[dict]:
        allowed = {sym.upper() for sym in whitelist}
        return [e for e in events if (e.get("symbol") or "").upper() in allowed]

    def classify(self, purpose: str, bm_desc: str = "") -> str:
        text = f"{purpose} {bm_desc}".lower()
        for catalyst_type, keywords in self._catalyst_keywords:
            if any(keyword in text for keyword in keywords):
                return catalyst_type
        return CATALYST_OTHER

    # ----------------------------------------------------------------- private

    def _from_cache(self, from_d: str, to_d: str) -> list[dict] | None:
        entry = self._cache.get((from_d, to_d))
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
    def _fetch(self, from_d: str, to_d: str) -> list[dict]:
        if not self._primed:
            self._prime_session()
        url = _NSE_EVENT_API.format(from_d=from_d, to_d=to_d)
        resp = self._session.get(  # type: ignore[union-attr]
            url,
            headers={"Referer": _REFERER, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected NSE event-calendar shape: {type(data)}")
        return data

    def _load_fixture(self) -> list[dict]:
        if _FIXTURE.exists():
            return json.loads(_FIXTURE.read_text(encoding="utf-8"))
        _log.info("No NSE event-calendar fixture — returning empty list")
        return []


def parse_event_date(date_str: str) -> date | None:
    """Parse the response 'date' field ('DD-Mon-YYYY') to a date, or None if unparseable."""
    try:
        return datetime.strptime(date_str.strip(), _EVENT_DATE_FMT).date()
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------- self-check

def _self_check() -> None:
    """Offline checks over the fixture — classification + whitelist filter. No network."""
    collector = NseEventCalendarCollector()
    events = collector._load_fixture()
    assert events, "fixture must be non-empty for the self-check"

    by_purpose = {e["purpose"]: collector.classify(e["purpose"], e.get("bm_desc", "")) for e in events}
    assert by_purpose.get("Financial Results") == "Results", by_purpose
    assert by_purpose.get("Dividend") == "Dividend", by_purpose
    assert by_purpose.get("Buy Back") == "Buyback", by_purpose
    assert by_purpose.get("Fund Raising") == "FundRaising", by_purpose
    assert by_purpose.get("Board Meeting") == CATALYST_OTHER, by_purpose

    nifty50 = {"RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"}
    kept = collector.filter_whitelist(events, nifty50)
    kept_syms = {e["symbol"] for e in kept}
    assert "ZOMATO" not in kept_syms, kept_syms          # non-whitelist dropped
    assert kept_syms <= nifty50 and "RELIANCE" in kept_syms, kept_syms

    assert parse_event_date("15-Jul-2026") == date(2026, 7, 15), "date parse"
    assert parse_event_date("garbage") is None, "bad date -> None"
    print("event-calendar self-check OK")


if __name__ == "__main__":
    _self_check()

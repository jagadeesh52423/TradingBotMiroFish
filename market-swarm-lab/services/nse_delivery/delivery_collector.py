"""NSE security-wise delivery collector.

Fetches the daily security-wise delivery bhavcopy (one CSV per trading day = every stock's
delivered-quantity %) and answers per-symbol delivery questions. Mirrors the NSE event-calendar
collector: lazy cookie-primed session, tenacity retry, on-disk per-day cache, offline seeding
for self-check.

One CSV covers ALL symbols for a date, so the per-day cache is shared across every symbol — the
first `deliv_pct`/`trailing_avg` for a date warms it; later symbols hit cache.

*** POINT-IN-TIME FOOTGUN: DELIV_PER for trading day D is published EOD, AFTER the close on D.
A backtest that enters at the day-D close must therefore gate on delivery through D-1 (the prior
session), never day D. This collector answers about the EXACT date it is asked for — the caller
owns the PIT lag (the screener gates at the prior-session bar). ***

# implement DeliverySource (deliv_pct, trailing_avg) to back the screener's delivery filter.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_NSE_HOME = "https://www.nseindia.com"
_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_REFERER = "https://www.nseindia.com/all-reports"
_URL_DATE_FMT = "%d%m%Y"        # bhavcopy filename date: DDMMYYYY (e.g. 04072025)
_CACHE_DIR = Path(__file__).resolve().parents[2] / "services" / "backtest" / ".delivery_cache"
_FIXTURE = Path(__file__).parent / "fixtures" / "sec_bhavdata_full_sample.csv"

_EQ_SERIES = "EQ"               # cash-market equity series (drop BE/BZ/SM/derivative rows)
_SYMBOL_COL = "SYMBOL"
_SERIES_COL = "SERIES"
_DELIV_PER_COL = "DELIV_PER"
# Backfill bound: how many calendar days trailing_avg walks back per requested session, so a
# holiday-heavy window still yields n values without unbounded fetching (~7 sessions/5 cal-days).
_BACKFILL_SLACK_DAYS = 12


def parse_sec_bhavdata(text: str) -> dict[str, float]:
    """Parse sec_bhavdata_full CSV text -> {SYMBOL: DELIV_PER} for SERIES==EQ only.

    NSE ships this file with leading spaces in both headers and cells (" SERIES", " EQ",
    " 62.34") and a literal " -" DELIV_PER for non-deliverable rows — strip keys/values and skip
    any row whose DELIV_PER is not a number."""
    out: dict[str, float] = {}
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return out
    field = {name.strip().upper(): name for name in reader.fieldnames}
    sym_key, series_key, deliv_key = field.get(_SYMBOL_COL), field.get(_SERIES_COL), field.get(_DELIV_PER_COL)
    if not (sym_key and series_key and deliv_key):
        _log.warning("sec_bhavdata missing expected columns; headers=%s", reader.fieldnames)
        return out
    for row in reader:
        if (row.get(series_key) or "").strip().upper() != _EQ_SERIES:
            continue
        symbol = (row.get(sym_key) or "").strip().upper()
        raw = (row.get(deliv_key) or "").strip()
        if not symbol:
            continue
        try:
            out[symbol] = float(raw)
        except ValueError:
            continue  # " -" / blank for the row -> no delivery figure
    return out


class NseDeliveryCollector:
    """Per-day NSE delivery bhavcopy with file cache + offline seeding. Implements DeliverySource.

    `day_maps` seeds {date: {SYMBOL: deliv_pct}} for offline/self-check use; `auto_fetch=False`
    disables all network (self-check). Set both for a fully offline instance."""

    def __init__(
        self,
        session: requests.Session | None = None,
        cache_dir: Path | None = None,
        day_maps: dict[date, dict[str, float]] | None = None,
        auto_fetch: bool = True,
    ) -> None:
        self._session = session
        self._cache_dir = cache_dir or _CACHE_DIR
        self._auto_fetch = auto_fetch
        self._primed = False
        self._memo: dict[date, dict[str, float] | None] = dict(day_maps or {})  # None = fetched-empty (holiday)

    @classmethod
    def from_config(cls, config: dict) -> "NseDeliveryCollector":
        cfg = config.get("delivery", {})
        cache_dir = Path(cfg["cache_dir"]) if cfg.get("cache_dir") else None
        return cls(cache_dir=cache_dir, auto_fetch=bool(cfg.get("auto_fetch", True)))

    # ------------------------------------------------------------------ DeliverySource

    def deliv_pct(self, symbol: str, on: date) -> float | None:
        """Delivered % for `symbol` on the EXACT date `on`, or None if the symbol/day has no EQ
        figure (holiday, non-EQ, unresolved). Caller owns the PIT lag — pass a prior session."""
        day = self._day_map(on)
        return day.get(symbol.upper()) if day else None

    def trailing_avg(self, symbol: str, on: date, n: int) -> float | None:
        """Mean deliv% over the <=n most recent available delivery sessions with date <= `on`
        (inclusive). None if no session yields a figure. When auto_fetch, missing sessions are
        back-filled day-by-day (bounded) so a live caller need not pre-warm; the walk-forward
        pre-warms via prefetch_range so this is all cache hits."""
        if n <= 0:
            return None
        symbol = symbol.upper()
        values: list[float] = []
        cursor, exhausted = on, on - timedelta(days=n + _BACKFILL_SLACK_DAYS)
        while len(values) < n and cursor >= exhausted:
            day = self._day_map(cursor)
            if day and symbol in day:
                values.append(day[symbol])
            cursor -= timedelta(days=1)
        return sum(values) / len(values) if values else None

    # ------------------------------------------------------------------ warm-up / introspection

    def prefetch_range(self, from_date: date, to_date: date) -> int:
        """Fetch+cache every trading day in [from_date, to_date] (holidays cache as empty). Returns
        the count of days with delivery data. The walk-forward's one-time cache warm-up."""
        cached = 0
        cursor = from_date
        while cursor <= to_date:
            if self._day_map(cursor):
                cached += 1
            cursor += timedelta(days=1)
        return cached

    def available_dates(self) -> list[date]:
        """Delivery dates already resolved in memory/cache (non-empty), sorted ascending."""
        dates = {day for day, m in self._memo.items() if m}
        if self._cache_dir.exists():
            for path in self._cache_dir.glob("*.json"):
                parsed = _parse_cache_name(path.stem)
                if parsed is not None:
                    dates.add(parsed)
        return sorted(dates)

    # ----------------------------------------------------------------- private

    def _day_map(self, on: date) -> dict[str, float]:
        """Resolve one day's {symbol: deliv%} through memo -> file cache -> network. Empty dict for
        a holiday/absent day. Never raises — a network failure logs and yields empty (fail-open on
        a single day; the screener fails CLOSED when the whole delivery figure is missing)."""
        if on in self._memo:
            return self._memo[on] or {}
        cached = self._read_cache(on)
        if cached is not None:
            self._memo[on] = cached
            return cached
        if not self._auto_fetch:
            return {}
        try:
            day = self._fetch_day(on)
        except Exception as exc:
            _log.warning("delivery fetch failed for %s (treating as no-data, not caching): %s", on, exc)
            return {}
        self._memo[on] = day
        self._write_cache(on, day)
        return day

    def _read_cache(self, on: date) -> dict[str, float] | None:
        path = self._cache_path(on)
        if not path.exists():
            return None
        try:
            return {k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            _log.warning("corrupt delivery cache %s (%s); refetching", path, exc)
            return None

    def _write_cache(self, on: date, day: dict[str, float]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(on).write_text(json.dumps(day), encoding="utf-8")
        except OSError as exc:
            _log.warning("could not write delivery cache for %s: %s", on, exc)

    def _cache_path(self, on: date) -> Path:
        return self._cache_dir / f"{on.isoformat()}.json"

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
    def _fetch_day(self, on: date) -> dict[str, float]:
        """Fetch+parse one day's bhavcopy. A 404 means a non-trading day -> empty (cached as
        holiday); other HTTP/network errors retry then propagate to _day_map's fail-open guard."""
        if not self._primed:
            self._prime_session()
        url = _BHAVCOPY_URL.format(ddmmyyyy=on.strftime(_URL_DATE_FMT))
        resp = self._session.get(  # type: ignore[union-attr]
            url, headers={"Referer": _REFERER, "Accept": "text/csv,*/*"}, timeout=20
        )
        if resp.status_code == 404:
            return {}  # non-trading day
        resp.raise_for_status()
        return parse_sec_bhavdata(resp.text)


def _parse_cache_name(stem: str) -> date | None:
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None


# ---------------------------------------------------------------- self-check

def _self_check() -> None:
    """Offline: CSV parse (EQ filter, whitespace strip, ' -' skip) + deliv_pct/trailing_avg over
    seeded day maps. No network, no cache writes (auto_fetch off)."""
    text = _FIXTURE.read_text(encoding="utf-8")
    parsed = parse_sec_bhavdata(text)
    assert parsed.get("RELIANCE") == 62.34, parsed                       # EQ row, whitespace stripped
    assert "IDEA" not in parsed, "non-EQ (BE) series must be dropped"    # SERIES filter
    assert "NOFIG" not in parsed, "' -' DELIV_PER row must be skipped"   # unparseable -> skipped

    seed = {
        date(2026, 7, 1): {"ACME": 40.0},
        date(2026, 7, 2): {"ACME": 50.0},
        date(2026, 7, 3): {"ACME": 60.0},   # 3-Jul: holiday gap the next day tests skip-over
        # 4-Jul (Sat), 5-Jul (Sun): no entry -> holidays
        date(2026, 7, 6): {"ACME": 90.0},
    }
    collector = NseDeliveryCollector(day_maps=seed, auto_fetch=False)

    assert collector.deliv_pct("acme", date(2026, 7, 6)) == 90.0, "exact-date, case-insensitive"
    assert collector.deliv_pct("ACME", date(2026, 7, 4)) is None, "holiday -> None"
    assert collector.deliv_pct("MISSING", date(2026, 7, 6)) is None, "absent symbol -> None"

    # trailing avg through 6-Jul over 3 sessions skips the Sat/Sun gap -> (90+60+50)/3.
    avg3 = collector.trailing_avg("ACME", date(2026, 7, 6), 3)
    assert avg3 is not None and abs(avg3 - (90 + 60 + 50) / 3) < 1e-9, avg3
    # PIT slice: through 3-Jul (prior session) EXCLUDES the 90 -> (60+50+40)/3.
    avg_prior = collector.trailing_avg("ACME", date(2026, 7, 3), 3)
    assert avg_prior is not None and abs(avg_prior - (60 + 50 + 40) / 3) < 1e-9, avg_prior
    assert collector.trailing_avg("ACME", date(2026, 6, 1), 3) is None, "no sessions in window -> None"
    assert collector.trailing_avg("ACME", date(2026, 7, 6), 0) is None, "n<=0 -> None"

    assert collector.available_dates() == sorted(seed), "available dates from seed"
    print("delivery-collector self-check OK")


if __name__ == "__main__":
    _self_check()

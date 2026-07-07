"""Catalyst-driven universe discovery (playbook §2 — the real way).

The playbook builds its watchlist from names that HAVE a fresh catalyst, not from a
fixed index. This assembles that dynamic universe market-wide from:
  - the NSE event calendar (upcoming board meetings: dividend / buyback / results / fund-raise)
  - recent market-wide NSE corporate announcements (order wins, approvals, etc.)

Returns a de-duplicated symbol list, capped, for the scanner to screen. Fails safe:
any feed that errors contributes nothing (never crashes discovery).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from services.nse_event_calendar.nse_event_calendar_collector import NseEventCalendarCollector

_log = logging.getLogger(__name__)

_HOME = "https://www.nseindia.com"
_ANN_API = ("https://www.nseindia.com/api/corporate-announcements"
            "?index=equities&from_date={from_d}&to_date={to_d}")
_ASM_API = "https://www.nseindia.com/api/reportASM"
_GSM_API = "https://www.nseindia.com/api/reportGSM"
_BHAVCOPY_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"


class CatalystDiscovery:
    def __init__(self, event_collector: NseEventCalendarCollector, session: requests.Session | None = None,
                 lookahead_days: int = 10, lookback_days: int = 3, max_symbols: int = 150,
                 guard: "SurveillanceLiquidityGuard | None" = None) -> None:
        self._events = event_collector
        self._session = session
        self._primed = False
        self._lookahead = lookahead_days
        self._lookback = lookback_days
        self._max = max_symbols
        self._guard = guard

    @classmethod
    def from_config(cls, config: dict) -> "CatalystDiscovery":
        d = config.get("discovery", {})
        return cls(
            NseEventCalendarCollector.from_config(config),
            lookahead_days=int(d.get("lookahead_days", 10)),
            lookback_days=int(d.get("lookback_days", 3)),
            max_symbols=int(d.get("max_symbols", 150)),
            guard=SurveillanceLiquidityGuard.from_config(config),
        )

    def discover(self, today: date | None = None) -> list[str]:
        return sorted(self.discover_detailed(today))

    def discover_detailed(self, today: date | None = None) -> dict[str, dict]:
        """Like discover(), but returns {symbol: catalyst_info} so the catalyst (what event
        put the name on the list) flows through to the run doc / dashboard."""
        today = today or _ist_today()
        catalyst: dict[str, dict] = {}

        # 1. Upcoming board-meeting catalysts (dividend/buyback/results/fund-raise) — rich type.
        try:
            for e in self._events.collect_range(today, today + timedelta(days=self._lookahead)):
                sym = (e.get("symbol") or "").upper()
                if sym and sym not in catalyst:
                    catalyst[sym] = {
                        "type": e.get("catalyst_type"),
                        "event": (e.get("purpose") or e.get("bm_desc") or "").strip()[:140],
                        "date": e.get("date") or e.get("bm_date"),
                        "source": "board_meeting",
                    }
        except Exception as exc:
            _log.warning("event-calendar discovery failed: %s", exc)

        # 2. Recent market-wide filings (order wins, approvals, ...) — with the filing description.
        try:
            for sym, desc in self._recent_announcements(today).items():
                catalyst.setdefault(sym, {"type": "filing", "event": desc or "recent corporate filing",
                                          "date": None, "source": "announcement"})
        except Exception as exc:
            _log.warning("announcement discovery failed: %s", exc)

        catalyst.pop("", None)
        # 3. Drop ASM/GSM-surveilled + sub-liquidity names (playbook §2 liquidity / §1,§11 trap).
        #    The guard IS the universe filter — do not arbitrarily cap. `max_symbols<=0` means
        #    unlimited (default); a positive cap, if set, keeps the most-liquid names (by turnover)
        #    rather than an alphabetical slice, so it never biases toward early-alphabet names.
        symbols = sorted(catalyst)
        if self._guard is not None:
            symbols = self._guard.filter(symbols, today)
        if self._max and self._max > 0 and len(symbols) > self._max:
            symbols = self._guard.top_by_turnover(symbols, self._max) if self._guard else symbols[: self._max]
        return {s: catalyst[s] for s in sorted(symbols)}

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
    def _recent_announcements(self, today: date) -> dict[str, str]:
        """{SYMBOL: filing description} for recent market-wide filings (latest per symbol)."""
        if not self._primed:
            self._prime()
        frm = (today - timedelta(days=self._lookback)).strftime("%d-%m-%Y")
        to = today.strftime("%d-%m-%Y")
        resp = self._session.get(  # type: ignore[union-attr]
            _ANN_API.format(from_d=frm, to_d=to),
            headers={"Referer": _REFERER, "Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        out: dict[str, str] = {}
        for r in rows:
            sym = (r.get("symbol") or "").upper()
            if sym:
                out.setdefault(sym, (r.get("desc") or r.get("attchmntText") or "").strip()[:140])
        return out


def _ist_today() -> date:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def parse_turnover_lacs(text: str) -> dict[str, float]:
    """Parse sec_bhavdata_full CSV -> {SYMBOL: TURNOVER_LACS} for SERIES==EQ. NSE pads
    headers/cells with spaces, so keys and values are stripped."""
    out: dict[str, float] = {}
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return out
    field = {n.strip().upper(): n for n in reader.fieldnames}
    sym_k, ser_k, to_k = field.get("SYMBOL"), field.get("SERIES"), field.get("TURNOVER_LACS")
    if not (sym_k and ser_k and to_k):
        return out
    for row in reader:
        if (row.get(ser_k) or "").strip().upper() != "EQ":
            continue
        sym = (row.get(sym_k) or "").strip().upper()
        try:
            out[sym] = float((row.get(to_k) or "").strip())
        except ValueError:
            continue
    return out


class SurveillanceLiquidityGuard:
    """Drops ASM/GSM-surveilled names and names below a daily-turnover floor.

    Restores the playbook filters (§2 liquidity; §1/§11 illiquid-circuit-lock trap) that a
    market-wide catalyst sweep would otherwise ignore. Fail-open: if a feed can't be fetched
    the corresponding filter is skipped (log warning) rather than emptying the universe.
    """

    def __init__(self, min_turnover_cr: float = 5.0, exclude_surveillance: bool = True,
                 session: requests.Session | None = None, bhavcopy_lookback: int = 6) -> None:
        self._min_lacs = min_turnover_cr * 100.0   # ₹1 cr = 100 lakhs
        self._exclude_surv = exclude_surveillance
        self._session = session
        self._primed = False
        self._lookback = bhavcopy_lookback

    @classmethod
    def from_config(cls, config: dict) -> "SurveillanceLiquidityGuard":
        d = config.get("discovery", {})
        return cls(
            min_turnover_cr=float(d.get("min_turnover_cr", 5.0)),
            exclude_surveillance=bool(d.get("exclude_surveillance", True)),
            bhavcopy_lookback=int(d.get("bhavcopy_lookback", 6)),
        )

    def filter(self, symbols: list[str], today: date | None = None) -> list[str]:
        today = today or _ist_today()
        keep = set(symbols)

        if self._exclude_surv:
            try:
                keep -= self._surveillance_symbols()
            except Exception as exc:
                _log.warning("surveillance fetch failed — not excluding ASM/GSM this run: %s", exc)

        try:
            turnover = self._turnover_map(today)
        except Exception as exc:
            _log.warning("bhavcopy fetch failed — skipping liquidity floor this run: %s", exc)
            turnover = {}
        if turnover:  # only apply when we actually have turnover data (else fail-open)
            keep = {s for s in keep if turnover.get(s, 0.0) >= self._min_lacs}

        self._last_turnover = turnover  # reused by top_by_turnover for a non-alphabetical cap
        return sorted(keep)

    def top_by_turnover(self, symbols: list[str], n: int) -> list[str]:
        """Keep the n most-liquid symbols by daily turnover (from the last filter's bhavcopy).
        A quality-ranked cap — never an alphabetical slice. Falls back to input order if turnover
        data is unavailable."""
        turnover = getattr(self, "_last_turnover", None) or {}
        return sorted(symbols, key=lambda s: turnover.get(s, 0.0), reverse=True)[:n]

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
    def _surveillance_symbols(self) -> set[str]:
        if not self._primed:
            self._prime()
        out: set[str] = set()
        asm = self._session.get(_ASM_API, headers={"Accept": "application/json"}, timeout=15).json()
        for bucket in ("longterm", "shortterm"):
            for x in asm.get(bucket, {}).get("data", []):
                sym = (x.get("symbol") or "").strip().upper()
                if sym:
                    out.add(sym)
        gsm = self._session.get(_GSM_API, headers={"Accept": "application/json"}, timeout=15).json()
        gsm_rows = gsm if isinstance(gsm, list) else gsm.get("data", [])
        out |= {(x.get("symbol") or "").strip().upper() for x in gsm_rows if x.get("symbol")}
        return out

    def _turnover_map(self, today: date) -> dict[str, float]:
        """Most recent available sec-bhavcopy turnover (walk back over holidays/weekends)."""
        if not self._primed:
            self._prime()
        for back in range(self._lookback + 1):
            d = today - timedelta(days=back)
            if d.weekday() >= 5:  # skip weekends
                continue
            url = _BHAVCOPY_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
            try:
                resp = self._session.get(url, headers={"Referer": "https://www.nseindia.com/all-reports"}, timeout=20)
            except requests.RequestException:
                continue
            if resp.status_code == 200 and resp.text:
                parsed = parse_turnover_lacs(resp.text)
                if parsed:
                    return parsed
        return {}

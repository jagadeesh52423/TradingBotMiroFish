"""FyersDataProvider — market data (OHLCV + LTP) sourced from Fyers.

Drop-in MarketDataProvider for the equity stack: registered as "fyers", so
`"data_provider": "fyers"` in nubra_config.json swaps market data to Fyers while
orders stay on Nubra. fyers-apiv3 is NOT a hard dependency — it is imported lazily
inside the client build, so importing this module never requires the SDK.

Auth: this provider only CONSUMES an access_token (from config["fyers"] or the
FYERS_ACCESS_TOKEN env var). The interactive/TOTP flow that mints the token is out
of scope here — mint it separately and supply it via config or environment.

Beyond the MarketDataProvider contract (current_price + close-only historical), this
provider also exposes ohlcv() — full OHLCV bars incl. intraday resolutions — and
FyersPriceSource, an adapter satisfying the catalyst screener's PriceSource Protocol.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from math import ceil

from services.nubra_client.market_data_provider import MarketDataProvider
from services.nubra_client.market_data_registry import register_provider

_log = logging.getLogger(__name__)

# interval → Fyers resolution. Intraday resolutions are minute counts as strings
# ("5" = 5-minute bars); "1D" is a daily bar. Extend here to add a new interval.
_RESOLUTION = {
    "1d": "1D", "1D": "1D", "1m": "1", "1": "1", "3m": "3", "3": "3",
    "5m": "5", "5": "5", "15m": "15", "15": "15", "30m": "30", "30": "30",
    "60m": "60", "1h": "60", "60": "60",
}
_DAILY_RESOLUTIONS = {"1D", "D"}
# NSE cash session = 09:15–15:30 = 375 minutes; sizes the intraday date range.
_NSE_SESSION_MINUTES = 375
# ~2.5× calendar days covers `lookback` trading days (weekends + holidays).
_CALENDAR_DAYS_PER_TRADING_DAY = 2.5
# Intraday requests span a session or two; floor the range so a short lookback still
# clears an intervening weekend/holiday.
_MIN_INTRADAY_DAYS = 4
# Fyers history caps one request at ~366 calendar days for daily and ~100 for intraday;
# ohlcv_range() chunks a wider span into requests of this size and merges (no silent truncation).
_MAX_REQUEST_DAYS = {"1D": 360, "D": 360}
_MAX_INTRADAY_REQUEST_DAYS = 90

# NSE trades in IST and Fyers stamps daily candles at 00:00 IST (= 18:30 UTC prior day);
# the screener compares bar["date"] <= event_date, so converting in UTC shifts every daily
# bar back one calendar day and breaks PIT. IST has no DST -> a fixed offset, no tzdata dep.
_IST = timezone(timedelta(hours=5, minutes=30))

# Symbols that trade as an index feed (NSE:SYM-INDEX), not equity (NSE:SYM-EQ). Add
# an entry to feed a new index. Compared against the space-stripped, upper-cased input.
_INDEX_SYMBOLS = {
    "NIFTY50", "NIFTYBANK", "BANKNIFTY", "NIFTYNEXT50", "FINNIFTY",
    "MIDCPNIFTY", "NIFTYMIDCAP150", "INDIAVIX",
}


def _calendar_days(resolution: str, lookback: int) -> int:
    """Calendar-day span to request so the response holds >= `lookback` bars.

    Daily bars scale by the trading-day→calendar-day factor. Intraday `lookback` is a
    BAR count, not a day count, so it is converted via bars-per-session first — the daily
    factor applied to a raw intraday lookback would over-fetch by ~2 orders of magnitude.
    """
    if resolution in _DAILY_RESOLUTIONS:
        return max(1, ceil(lookback * _CALENDAR_DAYS_PER_TRADING_DAY))
    # ponytail: Fyers caps intraday history ~100d/request; a very large intraday lookback
    # can silently truncate. Fine for Task #9's short intrabar windows — chunk if that changes.
    bars_per_session = max(1, _NSE_SESSION_MINUTES // int(resolution))
    trading_days = ceil(lookback / bars_per_session)
    return max(_MIN_INTRADAY_DAYS, ceil(trading_days * _CALENDAR_DAYS_PER_TRADING_DAY))


@register_provider("fyers")
class FyersDataProvider(MarketDataProvider):
    def __init__(self, client_id: str | None, access_token: str | None, *, client=None) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._client = client  # lazily built on first use unless injected (tests)

    @classmethod
    def from_config(cls, config: dict) -> "FyersDataProvider":
        fyers_cfg = config.get("fyers", {})
        client_id = fyers_cfg.get("client_id") or os.environ.get("FYERS_CLIENT_ID")
        access_token = fyers_cfg.get("access_token") or os.environ.get("FYERS_ACCESS_TOKEN")
        return cls(client_id, access_token)

    @staticmethod
    def _to_fyers_symbol(symbol: str) -> str:
        if symbol.upper().startswith("NSE:"):  # already fully qualified — pass through
            return symbol.upper()
        normalized = symbol.upper().replace(" ", "").replace("-INDEX", "")
        suffix = "INDEX" if normalized in _INDEX_SYMBOLS else "EQ"
        return f"NSE:{normalized}-{suffix}"

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._access_token:
            raise RuntimeError(
                "FYERS_ACCESS_TOKEN missing — set config['fyers']['access_token'] or the "
                "FYERS_ACCESS_TOKEN env var (mint it via the Fyers auth flow first)."
            )
        try:
            from fyers_apiv3 import fyersModel
        except ImportError as exc:
            raise RuntimeError(
                "fyers-apiv3 is not installed — `pip install fyers-apiv3` to use the "
                "Fyers data provider."
            ) from exc
        self._client = fyersModel.FyersModel(
            client_id=self._client_id, token=self._access_token, is_async=False
        )
        return self._client

    @staticmethod
    def _candles_to_bars(candles: list) -> list[dict]:
        # Fyers candle = [epoch_seconds, open, high, low, close, volume]; -> full OHLCV, oldest-first.
        bars = [
            {
                "timestamp": int(candle[0]) * 1000,
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            }
            for candle in candles
        ]
        bars.sort(key=lambda bar: bar["timestamp"])
        return bars

    def _history(self, symbol: str, resolution: str, range_from: date, range_to: date) -> list[dict]:
        request = {
            "symbol": self._to_fyers_symbol(symbol),
            "resolution": resolution,
            "date_format": "1",
            "range_from": range_from.strftime("%Y-%m-%d"),
            "range_to": range_to.strftime("%Y-%m-%d"),
            "cont_flag": "1",
        }
        response = self._get_client().history(request) or {}
        status = response.get("s")
        if status == "no_data":
            return []  # legitimately empty range (e.g. all-holiday window) — not an error
        if status not in (None, "ok"):
            # An over-cap (>366d daily), bad-symbol, or throttled request returns s="error" with no
            # candles; raise so it can't masquerade as "no data" (silent []). daily_bars fails soft.
            raise RuntimeError(
                f"Fyers history {status!r} for {symbol} {range_from}..{range_to}: "
                f"{response.get('message', response)}"
            )
        return self._candles_to_bars(response.get("candles") or [])

    def _fetch_bars(self, symbol: str, interval: str, lookback: int) -> list[dict]:
        """Recent full OHLCV bars, oldest-first, at most `lookback` (trailing today)."""
        resolution = _RESOLUTION.get(interval, "1D")
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=_calendar_days(resolution, lookback))
        return self._history(symbol, resolution, start, end)[-lookback:]

    def ohlcv(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]:
        """Full OHLCV bars, oldest-first: {timestamp(ms), open, high, low, close, volume}.

        Intraday resolutions ("5", "15", "60") return minute bars for intrabar stops /
        circuit modeling; the MarketDataProvider contract only guarantees close-only
        historical(), so this extension is Fyers-specific (callers hold the concrete type).
        """
        return self._fetch_bars(symbol, interval, lookback)

    def ohlcv_range(self, symbol: str, start: date, end: date, interval: str = "1d") -> list[dict]:
        """Full OHLCV over an explicit [start, end] date range — for backtests over event windows,
        where trailing-lookback fetch can't reach a past event. Oldest-first, de-duplicated by
        timestamp. Spans wider than the Fyers per-request cap are auto-chunked and merged."""
        resolution = _RESOLUTION.get(interval, "1D")
        span = _MAX_REQUEST_DAYS.get(resolution, _MAX_INTRADAY_REQUEST_DAYS)
        bars_by_ts: dict[int, dict] = {}
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=span))
            for bar in self._history(symbol, resolution, chunk_start, chunk_end):
                bars_by_ts[bar["timestamp"]] = bar
            chunk_start = chunk_end + timedelta(days=1)
        return sorted(bars_by_ts.values(), key=lambda bar: bar["timestamp"])

    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]:
        """Close bars, oldest-first: {"close": float, "timestamp": int ms} (contract shape)."""
        return [
            {"close": bar["close"], "timestamp": bar["timestamp"]}
            for bar in self._fetch_bars(symbol, interval, lookback)
        ]

    def current_price(self, symbol: str) -> Decimal:
        fyers_symbol = self._to_fyers_symbol(symbol)
        response = self._get_client().quotes({"symbols": fyers_symbol})
        ltp = _extract_ltp(response)
        return Decimal(str(ltp))


def _extract_ltp(response: dict) -> float:
    """Pull the LTP out of a Fyers quotes() response (`d` list, `v.lp`)."""
    rows = (response or {}).get("d") or []
    if not rows:
        raise RuntimeError(f"Fyers quotes() returned no data: {response!r}")
    return rows[0]["v"]["lp"]


class FyersPriceSource:
    """Adapter: catalyst-screener PriceSource backed by Fyers daily OHLCV.

    Structurally satisfies services.nse_event_calendar.catalyst_screener.PriceSource
    (a Protocol — no import needed), so the screener stays Open/Closed: a runner swaps
    YFinancePriceSource -> FyersPriceSource with zero screener edits. lookback must clear
    the screener's longest window (120d turnover) with margin.
    """

    def __init__(self, provider: FyersDataProvider, lookback: int = 300) -> None:
        self._provider = provider
        self._lookback = lookback

    def daily_bars(self, symbol: str) -> list[dict]:
        try:
            # ohlcv_range (not ohlcv) so the fetch CHUNKS: the screener's 120d-turnover window wants
            # >146 sessions, but a single Fyers daily request caps at 366 calendar days.
            end = datetime.now(tz=_IST).date()
            start = end - timedelta(days=_calendar_days("1D", self._lookback))
            bars = self._provider.ohlcv_range(symbol, start, end, interval="1d")[-self._lookback:]
        except Exception as exc:  # unresolved symbol / auth / SDK -> thin the proxy, never crash
            _log.warning("Fyers daily_bars failed for %s: %s", symbol, exc)
            return []
        return [
            {
                "date": datetime.fromtimestamp(bar["timestamp"] / 1000, tz=_IST).date(),
                "close": bar["close"],
                "volume": bar["volume"],
            }
            for bar in bars
        ]


# ---------------------------------------------------------------- self-check

class _FakeFyersClient:
    """Offline stand-in for fyersModel.FyersModel — records requests and MODELS Fyers' real
    behaviour: an over-cap daily range (>366d) returns s="error" with no candles; candles=None
    returns s="no_data"; otherwise s="ok". This lets the self-check catch the silent-[] class."""

    _DAILY_CAP_DAYS = 366

    def __init__(self, candles: list[list] | None, ltp: float = 100.5) -> None:
        self._candles = candles
        self._ltp = ltp
        self.requests: list[dict] = []

    @property
    def last_request(self) -> dict | None:
        return self.requests[-1] if self.requests else None

    def history(self, request: dict) -> dict:
        self.requests.append(request)
        span = (datetime.strptime(request["range_to"], "%Y-%m-%d")
                - datetime.strptime(request["range_from"], "%Y-%m-%d")).days
        if span > self._DAILY_CAP_DAYS:
            return {"s": "error", "message": "invalid input", "code": -1}
        if self._candles is None:
            return {"s": "no_data"}
        return {"s": "ok", "candles": self._candles}

    def quotes(self, request: dict) -> dict:
        return {"d": [{"v": {"lp": self._ltp}}]}


def _self_check() -> None:
    """Offline checks — symbol routing, OHLCV preservation, historical back-compat shape,
    lookback truncation, intraday date-range math, and the PriceSource adapter. No network."""
    # Symbol routing: equity -> -EQ (upper-cased), index -> -INDEX, qualified passes through.
    assert FyersDataProvider._to_fyers_symbol("RELIANCE") == "NSE:RELIANCE-EQ"
    assert FyersDataProvider._to_fyers_symbol("reliance") == "NSE:RELIANCE-EQ"
    assert FyersDataProvider._to_fyers_symbol("NIFTY50") == "NSE:NIFTY50-INDEX"
    assert FyersDataProvider._to_fyers_symbol("nifty 50") == "NSE:NIFTY50-INDEX"
    assert FyersDataProvider._to_fyers_symbol("NIFTY50-INDEX") == "NSE:NIFTY50-INDEX"
    assert FyersDataProvider._to_fyers_symbol("NSE:NIFTY50-INDEX") == "NSE:NIFTY50-INDEX"

    # Resolution map: daily + intraday minute strings both resolve.
    assert _RESOLUTION["1d"] == "1D" and _RESOLUTION["5"] == "5" and _RESOLUTION["15"] == "15"
    assert _RESOLUTION["60"] == "60" and _RESOLUTION["1h"] == "60"

    # Date-range math: daily scales by 2.5×; intraday converts a BAR count via bars/session.
    assert _calendar_days("1D", 20) == 50
    assert _calendar_days("5", 75) == _MIN_INTRADAY_DAYS  # ~1 session -> floored
    assert _calendar_days("5", 750) > _MIN_INTRADAY_DAYS  # ~10 sessions -> exceeds floor

    # epoch0 = 2024-06-20 00:00 IST = 2024-06-19 18:30 UTC (a real Fyers daily stamp): its
    # IST calendar day (20th) differs from its UTC day (19th), so the adapter's date mapping
    # is testable against an INDEPENDENT literal, not the impl's own conversion.
    epoch0 = 1_718_821_800
    epoch0_ist_date = date(2024, 6, 20)
    assert epoch0_ist_date != datetime.fromtimestamp(epoch0, tz=timezone.utc).date()  # UTC=19th
    candles = [
        [epoch0 + 2 * 86_400, 12, 15, 11, 14, 200],
        [epoch0, 10, 12, 9, 11, 100],
        [epoch0 + 86_400, 11, 13, 10, 13, 150],
    ]
    fake = _FakeFyersClient(candles)
    provider = FyersDataProvider("cid", "tok", client=fake)

    # ohlcv(): full 6-key bars, sorted oldest-first.
    bars = provider.ohlcv("RELIANCE", "1d", 5)
    assert [bar["close"] for bar in bars] == [11.0, 13.0, 14.0], bars
    assert bars[0] == {"timestamp": epoch0 * 1000, "open": 10.0, "high": 12.0,
                       "low": 9.0, "close": 11.0, "volume": 100.0}

    # historical(): back-compat — exactly {"close", "timestamp"}, same close series.
    hist = provider.historical("RELIANCE", "1d", 5)
    assert hist[0] == {"close": 11.0, "timestamp": epoch0 * 1000}
    assert set(hist[0]) == {"close", "timestamp"}
    assert [bar["close"] for bar in hist] == [11.0, 13.0, 14.0]

    # lookback truncation keeps the newest bars.
    assert [bar["close"] for bar in provider.ohlcv("RELIANCE", "1d", 2)] == [13.0, 14.0]

    # Requests carry the routed symbol + resolution.
    provider.ohlcv("NIFTY50", "1d", 5)
    assert fake.last_request["symbol"] == "NSE:NIFTY50-INDEX"
    provider.ohlcv("RELIANCE", "5m", 10)
    assert fake.last_request["resolution"] == "5" and fake.last_request["symbol"] == "NSE:RELIANCE-EQ"

    # ohlcv_range(): one request for a narrow span, auto-chunked+merged for a wide one, deduped.
    fake.requests.clear()
    provider.ohlcv_range("RELIANCE", date(2024, 1, 1), date(2024, 2, 1))
    assert len(fake.requests) == 1 and fake.requests[0]["range_from"] == "2024-01-01"
    fake.requests.clear()
    wide = provider.ohlcv_range("RELIANCE", date(2024, 1, 1), date(2025, 6, 1))  # ~517d > 360d cap
    assert len(fake.requests) >= 2, "wide span must chunk"
    assert [bar["close"] for bar in wide] == [11.0, 13.0, 14.0], "chunks merged + deduped by ts"

    # 366-day cap: an over-cap SINGLE request must RAISE (loud), never silently return [].
    try:
        provider.ohlcv("RELIANCE", "1d", 300)  # _calendar_days=750d > cap -> Fyers s="error"
        raise AssertionError("over-cap ohlcv() must raise, not return []")
    except RuntimeError:
        pass
    # But every ohlcv_range chunk stays <=360d, so a >cap span still resolves (chunked under the cap).
    fake.requests.clear()
    spanned = provider.ohlcv_range("RELIANCE", date(2023, 1, 1), date(2025, 1, 1))  # 731d -> 3 chunks
    assert len(fake.requests) >= 2 and [bar["close"] for bar in spanned] == [11.0, 13.0, 14.0]
    # daily_bars at the DEFAULT lookback (300) must return bars end-to-end — the exact path that
    # was silently emptying before F5 (it now routes through the chunker).
    assert FyersPriceSource(provider).daily_bars("RELIANCE"), "default-lookback daily_bars must not be []"

    # no_data status -> [] (a legitimately empty range), NOT a raise.
    nodata = FyersDataProvider("cid", "tok", client=_FakeFyersClient(None))
    assert nodata.ohlcv("RELIANCE", "1d", 5) == []

    # current_price extracts v.lp as Decimal.
    assert provider.current_price("RELIANCE") == Decimal("100.5")

    # FyersPriceSource adapter: {date, close, volume}, ms->IST date, oldest-first. Assert the
    # earliest bar's date against the independent literal (2024-06-20), NOT the impl's own tz.
    source = FyersPriceSource(provider, lookback=5)
    daily = source.daily_bars("RELIANCE")
    assert set(daily[0]) == {"date", "close", "volume"}
    assert daily[0]["date"] == epoch0_ist_date, (daily[0]["date"], epoch0_ist_date)
    assert daily[0]["close"] == 11.0 and daily[0]["volume"] == 100.0
    assert [bar["date"] for bar in daily] == sorted(bar["date"] for bar in daily)

    # Adapter fails soft: a provider with no token and no client raises internally -> [].
    broken = FyersPriceSource(FyersDataProvider("cid", None))
    assert broken.daily_bars("RELIANCE") == []

    print("fyers-data-provider self-check OK")


if __name__ == "__main__":
    _self_check()

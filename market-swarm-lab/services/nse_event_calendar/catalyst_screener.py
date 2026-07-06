"""NSE Catalyst Mean-Reversion screener (spec: docs/catalyst_meanreversion_system.md).

Applies the walk-forward-validated rules to recent NSE corporate events and emits ranked
candidates. Rules (each a composable predicate — add a filter = append to _HARD_FILTERS,
no caller edits):
  1. EXCLUDE Results/earnings (they fade at every horizon).
  2. Liquid: median 120d turnover (median volume x close) > a configurable ~Rs 1cr floor.
  3. Beaten-down setup: entry-day close BELOW its trailing 20d SMA (mean-reversion — this
     DIRECTION is load-bearing; the self-check asserts below-MA passes and above-MA fails).
Regime is a FLAG, not a hard filter: the equal-weight universe breadth index above its
short-term trend marks each surviving candidate regime_ok; ranking puts regime_ok first.

PIT: the event bar is the last bar with date <= event_date (the setup is evaluated AS OF the
event — trailing bars only). The 20d MA, 120d turnover, and the regime index all use only bars
up to the event date; no future bar ever enters a candidate's metrics.

*** EXPLORATORY / research — NOT investment advice. Daily-close only: no pre-open gap, no
first-15-min confirmation, no circuit-lock modeling. Paper-trade + intraday re-validate first. ***
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date
from statistics import mean, median
from typing import Protocol

from services.nse_event_calendar.nse_event_calendar_collector import parse_event_date

_log = logging.getLogger(__name__)


class PriceSource(Protocol):
    """Daily bars oldest-first: [{"date": date, "close": float, "volume": float}]; [] if absent.
    Implement for a new price feed (yfinance today, the Fyers provider later)."""

    def daily_bars(self, symbol: str) -> list[dict]: ...


@dataclass(frozen=True)
class ScreenerConfig:
    exclude_types: tuple[str, ...] = ("Results",)
    min_turnover_inr: float = 1e7   # ~Rs 1 crore median daily turnover
    min_price_inr: float = 20.0     # drop penny/thin names (India playbook: sub-Rs 20 = MM risk)
    ma_days: int = 20
    turnover_days: int = 120
    regime_ma_days: int = 10
    hold_days: int = 20

    @classmethod
    def from_config(cls, config: dict) -> "ScreenerConfig":
        cfg = config.get("catalyst_screener", {})
        defaults = cls()
        return cls(
            exclude_types=tuple(cfg.get("exclude_types", defaults.exclude_types)),
            min_turnover_inr=float(cfg.get("min_turnover_inr", defaults.min_turnover_inr)),
            min_price_inr=float(cfg.get("min_price_inr", defaults.min_price_inr)),
            ma_days=int(cfg.get("ma_days", defaults.ma_days)),
            turnover_days=int(cfg.get("turnover_days", defaults.turnover_days)),
            regime_ma_days=int(cfg.get("regime_ma_days", defaults.regime_ma_days)),
            hold_days=int(cfg.get("hold_days", defaults.hold_days)),
        )


@dataclass(frozen=True)
class Candidate:
    symbol: str
    purpose: str
    catalyst_type: str
    date: str
    close: float
    pct_below_ma: float
    turnover: float
    regime_ok: bool
    thesis: str

    def to_row(self) -> dict:
        return asdict(self)


def _event_index(bars: list[dict], event_date: date) -> int | None:
    """Last bar with date <= event_date — the entry-day close (or prior close if the event fell
    on a non-trading day). Never selects a bar after the event (PIT)."""
    event_bar = None
    for index, bar in enumerate(bars):
        if bar["date"] <= event_date:
            event_bar = index
        else:
            break
    return event_bar


def _dedup_events(events: list[dict]) -> list[dict]:
    """Drop duplicate corporate actions (NSE lists some twice) keyed on (symbol, date, purpose);
    keep first occurrence and order."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for event in events:
        key = ((event.get("symbol") or "").upper(), event.get("date", ""), event.get("purpose", ""))
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return unique


def _metrics_at_event(bars: list[dict], event_date: date, cfg: ScreenerConfig) -> dict | None:
    bars = sorted(bars, key=lambda bar: bar["date"])  # defensive: _event_index assumes ascending
    event_bar = _event_index(bars, event_date)
    if event_bar is None:
        return None
    closes = [bar["close"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    close = closes[event_bar]

    sma = mean(closes[event_bar - cfg.ma_days + 1: event_bar + 1]) if event_bar + 1 >= cfg.ma_days else None
    if event_bar + 1 >= cfg.turnover_days:
        turnover = median(volumes[event_bar - cfg.turnover_days + 1: event_bar + 1]) * close
    else:
        turnover = None  # insufficient history -> fail-closed on the liquidity gate
    pct_below_ma = round(100 * (sma - close) / sma, 2) if sma else None
    return {"close": close, "sma": sma, "pct_below_ma": pct_below_ma, "turnover": turnover}


# --- composable hard filters: (event, metrics, cfg) -> (passed, reason). Append to extend. ---

def _f_exclude_types(event: dict, metrics: dict, cfg: ScreenerConfig) -> tuple[bool, str]:
    return event.get("catalyst_type") not in cfg.exclude_types, "excluded catalyst type"


def _f_min_price(event: dict, metrics: dict, cfg: ScreenerConfig) -> tuple[bool, str]:
    return metrics["close"] >= cfg.min_price_inr, "below min price floor (penny/thin)"


def _f_liquid(event: dict, metrics: dict, cfg: ScreenerConfig) -> tuple[bool, str]:
    turnover = metrics["turnover"]
    return turnover is not None and turnover > cfg.min_turnover_inr, "below liquidity floor"


def _f_below_ma(event: dict, metrics: dict, cfg: ScreenerConfig) -> tuple[bool, str]:
    close, sma = metrics["close"], metrics["sma"]
    return sma is not None and close < sma, "not below the trailing MA (mean-reversion setup absent)"


_HARD_FILTERS = [_f_exclude_types, _f_min_price, _f_liquid, _f_below_ma]


class CatalystScreener:
    def __init__(self, price_source: PriceSource, universe, config: ScreenerConfig | None = None) -> None:
        self._source = price_source
        self._universe = [sym.upper() for sym in universe]
        self._cfg = config or ScreenerConfig()
        self._bars_cache: dict[str, list[dict]] = {}
        self._index: dict[date, float] | None = None
        self._breadth_resolved = 0

    def _bars(self, symbol: str) -> list[dict]:
        if symbol not in self._bars_cache:
            self._bars_cache[symbol] = self._source.daily_bars(symbol) or []
        return self._bars_cache[symbol]

    def _breadth_index(self) -> dict[date, float]:
        if self._index is None:
            per_date: dict[date, list[float]] = {}
            resolved = 0
            for symbol in self._universe:
                bars = self._bars(symbol)
                anchor = bars[0]["close"] if bars else 0.0
                if not anchor:  # unresolved/empty price source -> silently thins the proxy
                    continue
                resolved += 1
                for bar in bars:
                    per_date.setdefault(bar["date"], []).append(bar["close"] / anchor)
            self._breadth_resolved = resolved
            self._index = {bar_date: mean(levels) for bar_date, levels in per_date.items() if levels}
            total = len(self._universe)
            _log.info("regime breadth index: %d/%d universe symbols resolved", resolved, total)
            if total and resolved < 0.8 * total:
                _log.warning("regime breadth proxy THIN: %d/%d resolved -> regime_ok less reliable", resolved, total)
        return self._index

    def regime_coverage(self) -> tuple[int, int]:
        self._breadth_index()
        return self._breadth_resolved, len(self._universe)

    def _regime_ok(self, event_date: date) -> bool:
        index = self._breadth_index()
        dates = sorted(bar_date for bar_date in index if bar_date <= event_date)  # PIT
        if len(dates) < self._cfg.regime_ma_days:
            return False
        level = index[dates[-1]]
        trend = mean(index[bar_date] for bar_date in dates[-self._cfg.regime_ma_days:])
        return level > trend

    def screen(self, events: list[dict]) -> list[Candidate]:
        candidates: list[Candidate] = []
        for event in _dedup_events(events):
            symbol = (event.get("symbol") or "").upper()
            event_date = parse_event_date(event.get("date", ""))
            if event_date is None:
                continue
            metrics = _metrics_at_event(self._bars(symbol), event_date, self._cfg)
            if metrics is None:
                _log.debug("skip %s: no price bar on/before %s", symbol, event_date)
                continue
            failure = next(((passed, reason) for passed, reason
                            in (rule(event, metrics, self._cfg) for rule in _HARD_FILTERS)
                            if not passed), None)
            if failure is not None:  # gate on the boolean, not the reason (a filter may return "")
                _log.debug("reject %s %s: %s", symbol, event.get("date"), failure[1])
                continue
            regime_ok = self._regime_ok(event_date)
            catalyst_type = event.get("catalyst_type", "Other")
            candidates.append(Candidate(
                symbol=symbol,
                purpose=event.get("purpose", ""),
                catalyst_type=catalyst_type,
                date=event.get("date", ""),
                close=round(metrics["close"], 2),
                pct_below_ma=metrics["pct_below_ma"],
                turnover=round(metrics["turnover"], 0),
                regime_ok=regime_ok,
                thesis=(f"Beaten-down {catalyst_type} catalyst; {metrics['pct_below_ma']}% below "
                        f"{self._cfg.ma_days}d MA; mean-reversion, hold ~{self._cfg.hold_days}d. "
                        f"EXPLORATORY — not advice."),
            ))
        candidates.sort(key=lambda candidate: (candidate.regime_ok, candidate.pct_below_ma), reverse=True)
        return candidates


class InMemoryPriceSource:
    """Test/offline PriceSource backed by a {symbol: [bars]} map."""

    def __init__(self, bars_by_symbol: dict[str, list[dict]]) -> None:
        self._bars = bars_by_symbol

    def daily_bars(self, symbol: str) -> list[dict]:
        return self._bars.get(symbol.upper(), [])


class YFinancePriceSource:
    """Live PriceSource: daily OHLCV from yfinance SYMBOL.NS. Swappable for a Fyers source."""

    def __init__(self, period: str = "1y") -> None:
        self._period = period

    def daily_bars(self, symbol: str) -> list[dict]:
        try:
            import yfinance
            hist = yfinance.Ticker(f"{symbol}.NS").history(period=self._period, auto_adjust=False)
        except Exception as exc:
            _log.warning("yfinance fetch failed for %s: %s", symbol, exc)
            return []
        return [
            {"date": timestamp.date(), "close": float(row["Close"]), "volume": float(row["Volume"])}
            for timestamp, row in hist.iterrows()
        ]


# ---------------------------------------------------------------- self-check

def _bars(dates: list[date], closes: list[float], volume: float) -> list[dict]:
    return [{"date": d, "close": c, "volume": volume} for d, c in zip(dates, closes)]


def _self_check() -> None:
    """Offline checks — filter direction (incl. the below-MA inversion guard), liquidity, PIT,
    regime flag. No network, no yfinance."""
    days = [date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2),
            date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]  # event on 6-Jul (index 5)
    cfg = ScreenerConfig(ma_days=5, turnover_days=5, regime_ma_days=3, min_turnover_inr=1e7)

    # CAND1: close 90 vs 5d MA 98 -> below MA; high volume -> liquid. idx6 (200) is AFTER the event.
    cand_closes = [100, 100, 100, 100, 100, 90, 200]
    prices = {
        "CAND1": _bars(days, cand_closes, 1_000_000),          # below MA, liquid  -> PASS
        "ABOVE1": _bars(days, [100, 100, 100, 100, 100, 110, 90], 1_000_000),  # above MA -> reject
        "ILLIQ1": _bars(days, cand_closes, 10),                # below MA but tiny volume -> reject
        "EARN1": _bars(days, cand_closes, 1_000_000),          # Results -> excluded regardless
        # PENNY: below MA (9.8 vs 9) + liquid (turnover 1.8cr) but price < Rs 20 -> min_price rejects.
        "PENNY": _bars(days, [10, 10, 10, 10, 10, 9, 20], 2_000_000),
        "UP1": _bars(days, [100, 101, 102, 103, 104, 105, 106], 1_000_000),  # rising breadth
        "UP2": _bars(days, [100, 101, 102, 103, 104, 105, 106], 1_000_000),
    }
    events = [
        {"symbol": "CAND1", "purpose": "Buy Back", "catalyst_type": "Buyback", "date": "06-Jul-2026"},
        {"symbol": "ABOVE1", "purpose": "Dividend", "catalyst_type": "Dividend", "date": "06-Jul-2026"},
        {"symbol": "ILLIQ1", "purpose": "Buy Back", "catalyst_type": "Buyback", "date": "06-Jul-2026"},
        {"symbol": "EARN1", "purpose": "Financial Results", "catalyst_type": "Results", "date": "06-Jul-2026"},
        {"symbol": "PENNY", "purpose": "Buy Back", "catalyst_type": "Buyback", "date": "06-Jul-2026"},
    ]
    screener = CatalystScreener(InMemoryPriceSource(prices), ["UP1", "UP2"], cfg)
    picks = {c.symbol: c for c in screener.screen(events)}
    assert set(picks) == {"CAND1"}, f"only the below-MA, liquid, non-penny, non-earnings name should pass: {set(picks)}"

    # min_price floor isolates PENNY: at floor 0 it passes (below-MA + liquid), at floor 20 it drops.
    penny_event = [events[4]]
    no_floor = ScreenerConfig(ma_days=5, turnover_days=5, regime_ma_days=3, min_turnover_inr=1e7, min_price_inr=0)
    assert CatalystScreener(InMemoryPriceSource(prices), ["UP1", "UP2"], no_floor).screen(penny_event), "floor 0 -> PENNY passes"
    assert not CatalystScreener(InMemoryPriceSource(prices), ["UP1", "UP2"], cfg).screen(penny_event), "floor 20 -> PENNY dropped"

    # Extension-path guard: a future appended filter returning (False, "") must still REJECT
    # (screen() gates on the boolean, not the reason string).
    original_filters = list(_HARD_FILTERS)
    try:
        _HARD_FILTERS.append(lambda event, metrics, screener_cfg: (False, ""))
        blocked = CatalystScreener(InMemoryPriceSource(prices), ["UP1", "UP2"], cfg).screen([events[0]])
        assert not blocked, "a filter returning (False, '') must reject even with an empty reason"
    finally:
        _HARD_FILTERS[:] = original_filters
    assert picks["CAND1"].pct_below_ma > 0, picks["CAND1"]        # 98 vs 90 -> ~8.16% below
    assert picks["CAND1"].regime_ok is True, "rising breadth -> regime_ok"  # PIT trend up

    # DIRECTION guard (the inversion bug): make CAND1 sit ABOVE its MA -> it must drop out.
    inverted = dict(prices, CAND1=_bars(days, [100, 100, 100, 100, 100, 110, 200], 1_000_000))
    assert not CatalystScreener(InMemoryPriceSource(inverted), ["UP1", "UP2"], cfg).screen(
        [events[0]]), "above-MA must NOT be a candidate"

    # PIT guard: the post-event bar (idx6=200) must not enter the MA; CAND1 stays a candidate.
    assert CatalystScreener(InMemoryPriceSource(prices), ["UP1", "UP2"], cfg).screen([events[0]]), "PIT"

    # Regime flag flips with a DOWN-trending universe (PIT, same event date).
    down = {"D1": _bars(days, [106, 105, 104, 103, 102, 101, 100], 1_000_000),
            "D2": _bars(days, [106, 105, 104, 103, 102, 101, 100], 1_000_000)}
    down_source = InMemoryPriceSource(dict(prices, **down))
    down_pick = CatalystScreener(down_source, ["D1", "D2"], cfg).screen([events[0]])
    assert down_pick and down_pick[0].regime_ok is False, "falling breadth -> regime_ok False"

    # Dedup: the same (symbol, date, purpose) listed twice (NSE double-lists) -> ONE candidate.
    duped = CatalystScreener(InMemoryPriceSource(prices), ["UP1", "UP2"], cfg).screen([events[0], dict(events[0])])
    assert len(duped) == 1, f"duplicate events must dedup to one candidate: {duped}"
    print("catalyst-screener self-check OK")


if __name__ == "__main__":
    _self_check()

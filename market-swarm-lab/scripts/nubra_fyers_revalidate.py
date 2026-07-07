"""Task #9 — re-validate the catalyst mean-reversion system (docs/catalyst_meanreversion_system.md)
on Fyers OHLC instead of yfinance daily closes.

EXPLORATORY / research script. NOT investment advice. Reuses the production CatalystScreener
(services/nse_event_calendar/catalyst_screener.py) UNMODIFIED to derive the scoped candidate set
from the existing yfinance walk-forward cache, then re-prices ONLY that scoped set via Fyers OHLC
(services.fyers_client.fyers_data_provider) to add what daily-close couldn't model:
  - INTRABAR target/stop using the real daily high/low (vs close-to-close). Same-bar ambiguity
    (both target and stop breached in one bar) is broken CONSERVATIVELY: assume the STOP filled
    first — you can't know intrabar order from a daily bar, so take the worse outcome.
  - CIRCUIT-LOCK modeling: a session that froze at a band (high≈low vs prior close) can't fill.
    Upper-lock on the event bar blocks ENTRY (can't buy in); a lower-lock day can't fill a STOP
    (no buyers) so the position carries forward. PIT-safe: each flag uses only that bar's own data.

Fetch: one Fyers ohlcv_range() call per unique symbol over that symbol's event window(s)
[earliest event − buffer, latest event + hold + buffer] — the trailing-lookback ohlcv() can't
reach a past event, so a date-range fetch is required. Throttled + checkpointed per symbol.

Stop assumption flagged: the source system (per the doc) defines NO stop — only a 20-day time
exit. There's no canonical stop % to reuse, so this reports time-exit-only (comparable to the
original) AND an intrabar target/stop scenario (tunable, default ±8%) side by side, to see whether
adding realistic intrabar fills + circuit exclusion changes the +2-3% / 59-63% daily-close result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.fyers_client.fyers_data_provider import FyersDataProvider, _IST
from services.nse_event_calendar.catalyst_screener import CatalystScreener, InMemoryPriceSource

_ROOT = Path(__file__).resolve().parents[1]
_CACHE_PATH = _ROOT / "services" / "backtest" / ".walkfwd_cache.json"
# v2: range-fetch semantics differ from the old trailing-lookback stub — don't reuse its bars.
_CHECKPOINT_PATH = _ROOT / "services" / "backtest" / ".fyers_revalidate_checkpoint_v2.json"
_REPORT_PATH = _ROOT / "services" / "backtest" / "fyers_revalidation_report.json"

_HOLD_DAYS = 20
_MAX_CIRCUIT_EXTENSION_DAYS = 5   # carry a stuck (circuit-locked) exit at most this many days
_PRE_WINDOW_BUFFER_DAYS = 15      # calendar days before the earliest event (entry + prior bar)
_POST_WINDOW_BUFFER_DAYS = 95     # calendar days after the latest event (hold + extension + slack)
_CIRCUIT_RANGE_EPS = 0.001        # |high-low|/prior_close below this = a frozen (circuit) bar
# Fyers daily candles are UNADJUSTED (verified: Fyers close == yfinance auto_adjust=False; the
# adjusted baseline sat ~dividend% lower). A split/bonus ex-date inside a hold window then shows as
# a huge non-circuit gap that would fake a stop-out — flag such candidates and drop them from the
# headline (a normal day or a dividend never moves this much; a 1:1 bonus is −50%, a 5:1 split −80%).
_CORP_ACTION_GAP_PCT = 0.25


def _to_nse_date_fmt(iso_str: str) -> str:
    return datetime.strptime(iso_str, "%Y-%m-%d").strftime("%d-%b-%Y")


def load_candidates() -> list[dict]:
    """Scoped candidate set: the UNMODIFIED production screener + hard filters over the yfinance
    cache. This is the SAME set the daily-close system trades — only the Fyers repricing is new."""
    cache = json.loads(_CACHE_PATH.read_text())
    bars_by_symbol = {}
    for symbol, entry in cache["prices"].items():
        median_volume = entry.get("mv", 0.0)
        bars = [
            {"date": datetime.strptime(day, "%Y-%m-%d").date(), "close": close, "volume": median_volume}
            for day, close in entry["c"].items()
        ]
        bars.sort(key=lambda bar: bar["date"])
        bars_by_symbol[symbol] = bars

    events = [
        {"date": _to_nse_date_fmt(event["date"]), "symbol": event["symbol"], "catalyst_type": event["type"]}
        for event in cache["events"]
    ]
    screener = CatalystScreener(InMemoryPriceSource(bars_by_symbol), universe=list(bars_by_symbol))
    candidates = screener.screen(events)
    return [row | {"event_date": datetime.strptime(row["date"], "%d-%b-%Y").date()}
            for row in (candidate.to_row() for candidate in candidates)]


def fetch_fyers_bars(provider: FyersDataProvider, candidates: list[dict], sleep_s: float) -> dict[str, list]:
    """One ohlcv_range() call per symbol over [earliest event − buffer, latest event + hold + buffer]
    — a range fetch, so PAST events (unreachable by trailing lookback) are covered. Throttled with
    exponential backoff; checkpoints after each symbol so a mid-run rate-limit doesn't lose fetches."""
    events_by_symbol: dict[str, list[date]] = defaultdict(list)
    for candidate in candidates:
        events_by_symbol[candidate["symbol"]].append(candidate["event_date"])

    by_symbol: dict[str, list] = {}
    if _CHECKPOINT_PATH.exists():
        by_symbol = json.loads(_CHECKPOINT_PATH.read_text())
        print(f"resuming from checkpoint: {len(by_symbol)} symbols already fetched", flush=True)

    symbols = sorted(events_by_symbol)
    for index, symbol in enumerate(symbols):
        if symbol in by_symbol:
            continue
        start = min(events_by_symbol[symbol]) - timedelta(days=_PRE_WINDOW_BUFFER_DAYS)
        end = min(date.today(), max(events_by_symbol[symbol]) + timedelta(days=_POST_WINDOW_BUFFER_DAYS))
        for attempt in range(3):
            try:
                bars = provider.ohlcv_range(symbol, start, end, interval="1d")
                by_symbol[symbol] = bars
                print(f"[{index+1}/{len(symbols)}] {symbol}: {len(bars)} bars {start}..{end}", flush=True)
                break
            except Exception as exc:  # noqa: BLE001 — rate limit / transient network, retry
                wait = sleep_s * (2 ** attempt) + 1
                print(f"[{index+1}/{len(symbols)}] {symbol} failed (attempt {attempt+1}): {exc} -> {wait:.1f}s",
                      flush=True)
                time.sleep(wait)
        else:
            by_symbol[symbol] = []  # exhausted retries -> unresolved, don't crash the run
        _CHECKPOINT_PATH.write_text(json.dumps(by_symbol))
        time.sleep(sleep_s)
    return by_symbol


def _with_dates(bars: list[dict]) -> list[dict]:
    """Attach the IST calendar date to each bar (Fyers epoch is UTC seconds; NSE trades in IST, so
    a UTC date could shift a near-boundary bar a day and break PIT entry-bar selection)."""
    bars = sorted(bars, key=lambda bar: bar["timestamp"])
    for bar in bars:
        bar["date"] = datetime.fromtimestamp(bar["timestamp"] / 1000, tz=_IST).date()
    return bars


def _circuit_direction(bar: dict, prior_close: float) -> str | None:
    """A session that never traded a range (|high-low| ≈ 0) froze at a band. Direction vs prior
    close disambiguates upper (can't buy) vs lower (can't sell/stop). None = traded normally.
    ponytail: range≈0 heuristic only; not band-magnitude aware (2/5/10/20% bands not distinguished)."""
    if prior_close <= 0 or (bar["high"] - bar["low"]) / prior_close > _CIRCUIT_RANGE_EPS:
        return None
    if bar["close"] > prior_close:
        return "up"
    if bar["close"] < prior_close:
        return "down"
    return None


def reprice_candidate(candidate: dict, bars: list[dict], stop_pct: float, target_pct: float,
                      max_divergence_pct: float) -> dict | None:
    """Re-price one candidate on Fyers OHLC: close-to-close time exit AND an intrabar target/stop
    scenario with conservative same-bar tie-break + circuit-lock fill modeling. None if unrepriceable."""
    event_date = candidate["event_date"]
    entry_index = None
    for i, bar in enumerate(bars):
        if bar["date"] <= event_date:
            entry_index = i
        else:
            break
    if entry_index is None or entry_index == 0:
        return None  # no Fyers bar on/before the event, or no prior bar for a circuit reference

    entry_bar = bars[entry_index]
    prior_close = bars[entry_index - 1]["close"]
    entry_price = entry_bar["close"]
    if _circuit_direction(entry_bar, prior_close) == "up":
        return {"symbol": candidate["symbol"], "event_date": str(event_date), "entry_blocked": True}

    window = bars[entry_index + 1: entry_index + 1 + _HOLD_DAYS + _MAX_CIRCUIT_EXTENSION_DAYS]
    if not window:
        return None

    result = {
        "symbol": candidate["symbol"], "event_date": str(event_date), "entry_blocked": False,
        "entry_price": round(entry_price, 2), "fyers_vs_yfinance_adj_close_pct": None,
    }
    # candidate["close"] is the yfinance ADJUSTED cache close; Fyers is UNADJUSTED. If they diverge
    # beyond the threshold, a corporate action skews this event's basis vs the adjusted baseline —
    # flag it so the headline can rest only on events where the two sources agree.
    yf_adj_close = candidate["close"]
    result["source_divergent"] = False
    if yf_adj_close:
        divergence_pct = 100 * (entry_price - yf_adj_close) / yf_adj_close
        result["fyers_vs_yfinance_adj_close_pct"] = round(divergence_pct, 2)
        result["source_divergent"] = abs(divergence_pct) > max_divergence_pct * 100

    # In-window corporate-action guard: a >25% non-circuit bar-to-bar move is a split/bonus ex-date,
    # not a real return. Each bar is referenced against its TRUE prior close (entry_bar vs pre-entry,
    # then forward-bar-1 vs entry_bar.close, ...) so an ex-date on the entry bar is caught too.
    prev_ref = prior_close
    result["corp_action_suspect"] = False
    for scan_bar in [entry_bar, *window[:_HOLD_DAYS]]:
        if _circuit_direction(scan_bar, prev_ref) is None and abs(scan_bar["close"] / prev_ref - 1) > _CORP_ACTION_GAP_PCT:
            result["corp_action_suspect"] = True
        prev_ref = scan_bar["close"]

    # Scenario A — close-to-close time exit at the hold horizon (the source system's methodology).
    time_exit_bar = window[min(_HOLD_DAYS, len(window)) - 1]
    result["time_exit_return_pct"] = round(100 * (time_exit_bar["close"] / entry_price - 1), 2)

    # Scenario B — intrabar target/stop on the real daily high/low, circuit-aware. H1: the first
    # forward bar's prior close is the ENTRY close (bars[entry_index]), not the pre-entry day.
    stop_price = entry_price * (1 - stop_pct)
    target_price = entry_price * (1 + target_pct)
    prev_close = entry_price
    exit_return_pct = exit_reason = exit_day = None
    pending_locked_stop = False
    for held_days, bar in enumerate(window[:_HOLD_DAYS], start=1):
        direction = _circuit_direction(bar, prev_close)
        breached_stop = bar["low"] <= stop_price
        hit_target = bar["high"] >= target_price
        if breached_stop and direction == "down":
            pending_locked_stop = True  # lower-lock: no buyers, stop can't fill here — carry it
        elif breached_stop or hit_target:
            # CONSERVATIVE: if both breach the same bar, assume the STOP filled first (worse case).
            if breached_stop:
                exit_return_pct, exit_reason = round(100 * (stop_price / entry_price - 1), 2), "stop"
            else:
                exit_return_pct, exit_reason = round(100 * (target_price / entry_price - 1), 2), "target"
            exit_day = held_days
            break
        prev_close = bar["close"]
    # H2: the extension days (21..25) are searched ONLY to resolve a stop that was breached-but-locked
    # within the hold — a non-locked position never exits past the 20-day horizon it's compared against.
    if exit_reason is None and pending_locked_stop:
        for extra_day, bar in enumerate(window[_HOLD_DAYS:_HOLD_DAYS + _MAX_CIRCUIT_EXTENSION_DAYS], start=_HOLD_DAYS + 1):
            if bar["low"] <= stop_price and _circuit_direction(bar, prev_close) != "down":
                exit_return_pct, exit_reason, exit_day = round(100 * (stop_price / entry_price - 1), 2), "stop_carried", extra_day
                break
            prev_close = bar["close"]
    if exit_reason is None:  # nothing filled within the hold -> fall back to the time exit
        exit_return_pct, exit_reason, exit_day = result["time_exit_return_pct"], "time", min(_HOLD_DAYS, len(window))
    result["intrabar_return_pct"] = exit_return_pct
    result["intrabar_exit_reason"] = exit_reason
    result["intrabar_hold_days"] = exit_day
    return result


def summarize(rows: list[dict], key: str) -> dict:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median_return_pct": round(median(values), 2),
        "pct_positive": round(100 * sum(1 for value in values if value > 0) / len(values), 1),
    }


def build_report(candidates, symbols, bars_raw, stop_pct, target_pct, max_divergence_pct) -> tuple[dict, list]:
    repriced, unresolved = [], 0
    for symbol in symbols:
        bars = _with_dates(list(bars_raw.get(symbol, [])))
        if not bars:
            unresolved += 1
            continue
        for candidate in [c for c in candidates if c["symbol"] == symbol]:
            row = reprice_candidate(candidate, bars, stop_pct, target_pct, max_divergence_pct)
            if row is not None:
                repriced.append(row)

    tradeable = [row for row in repriced if not row["entry_blocked"]]
    # HEADLINE exclusion = the >25% unadjusted split/bonus gap ONLY (corp_action_suspect). Dividends
    # stay IN — a real trader's stop sees the ~1-3% ex-dividend drop, so it's realistic, not corruption.
    # source_divergence (Fyers unadjusted vs the yfinance ADJUSTED cache) is a DIAGNOSTIC, not a filter.
    clean = [row for row in tradeable if not row.get("corp_action_suspect")]
    reasons = sorted({row.get("intrabar_exit_reason") for row in clean if row.get("intrabar_exit_reason")})
    divergent = [abs(row["fyers_vs_yfinance_adj_close_pct"]) for row in tradeable
                 if row.get("fyers_vs_yfinance_adj_close_pct") is not None]
    report = {
        "candidates_scoped": len(candidates),
        "unique_symbols": len(symbols),
        "unresolved_symbols_no_fyers_data": unresolved,
        "repriced_events": len(repriced),
        "entry_blocked_upper_circuit": sum(1 for row in repriced if row["entry_blocked"]),
        "excluded_corp_action_gap": sum(1 for row in tradeable if row.get("corp_action_suspect")),
        "clean_tradeable_n": len(clean),
        # HEADLINE: the DELTA between these two is the finding — does adding realistic intrabar stops +
        # circuit exclusion change behavior? BOTH are Fyers UNADJUSTED (apples-to-apples).
        "time_exit_close_to_close_fyers": summarize(clean, "time_exit_return_pct"),
        f"intrabar_target{int(target_pct*100)}_stop{int(stop_pct*100)}_fyers": summarize(clean, "intrabar_return_pct"),
        "intrabar_exit_reason_counts": {reason: sum(1 for row in clean if row.get("intrabar_exit_reason") == reason)
                                        for reason in reasons},
        # DIAGNOSTIC only (not an exclusion): how far Fyers-unadjusted sits from the adjusted cache.
        "source_divergent_gt5pct_count": sum(1 for row in tradeable if row.get("source_divergent")),
        "median_abs_fyers_vs_yfinance_ADJ_close_delta_pct": round(median(divergent), 2) if divergent else None,
        "note": ("EXPLORATORY — not investment advice. HEADLINE = the DELTA between Fyers close-to-close "
                 "and Fyers intrabar+circuit, BOTH UNADJUSTED: does adding realistic intrabar stops + "
                 "circuit exclusion change behavior? The yfinance +2-3%/59-63% is a SEPARATE, ADJUSTED-basis "
                 "reference — we do NOT claim the Fyers absolute matches it, only that the intrabar/circuit "
                 "DELTA transfers. >25% split/bonus gaps excluded; dividends kept (a real stop sees them)."),
    }
    return report, repriced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep", type=float, default=0.4, help="seconds between Fyers calls")
    parser.add_argument("--stop_pct", type=float, default=0.08, help="intrabar stop distance (0.08 = 8%)")
    parser.add_argument("--target_pct", type=float, default=0.08, help="intrabar target distance (0.08 = 8%)")
    parser.add_argument("--max_divergence_pct", type=float, default=0.05,
                        help="exclude events where Fyers entry close diverges from the yfinance adjusted "
                             "cache close by more than this (0.05 = 5%) — corporate-action contamination")
    parser.add_argument("--limit_symbols", type=int, default=None, help="cap unique symbols fetched (debug)")
    args = parser.parse_args()

    if not os.environ.get("FYERS_CLIENT_ID") or not os.environ.get("FYERS_ACCESS_TOKEN"):
        raise SystemExit("set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN before running")

    candidates = load_candidates()
    print(f"scoped candidates (pass hard filters): {len(candidates)}", flush=True)
    symbols = sorted({candidate["symbol"] for candidate in candidates})
    if args.limit_symbols:
        symbols = symbols[: args.limit_symbols]
        candidates = [candidate for candidate in candidates if candidate["symbol"] in set(symbols)]
    print(f"unique symbols to fetch from Fyers: {len(symbols)}", flush=True)

    provider = FyersDataProvider.from_config({})
    bars_raw = fetch_fyers_bars(provider, candidates, args.sleep)
    report, rows = build_report(candidates, symbols, bars_raw, args.stop_pct, args.target_pct, args.max_divergence_pct)

    _REPORT_PATH.write_text(json.dumps({"report": report, "rows": rows}, indent=2, default=str))
    print(json.dumps(report, indent=2))
    print(f"full rows written to {_REPORT_PATH}")


def _self_check() -> None:
    """Offline check — circuit direction (with float tolerance), conservative same-bar tie-break,
    lower-lock stop carry, time-exit fallback, entry block, and IST bar dating. No network."""
    frozen_up = {"high": 110.0, "low": 110.0, "close": 110.0}
    frozen_down = {"high": 90.0, "low": 90.0, "close": 90.0}
    normal = {"high": 105.0, "low": 98.0, "close": 101.0}
    assert _circuit_direction(frozen_up, 100.0) == "up"
    assert _circuit_direction(frozen_down, 100.0) == "down"
    assert _circuit_direction(normal, 100.0) is None
    # tolerance: a 0.05% range is still "frozen" (rounding on a locked band); a 1% range is not.
    assert _circuit_direction({"high": 110.05, "low": 110.0, "close": 110.02}, 100.0) == "up"
    assert _circuit_direction({"high": 111.0, "low": 110.0, "close": 110.5}, 100.0) is None

    def mk(day_offset, close, high=None, low=None):
        stamp = datetime(2026, 1, 1, tzinfo=_IST) + timedelta(days=day_offset)
        return {"date": stamp.date(), "timestamp": int(stamp.timestamp() * 1000), "open": close,
                "high": high if high is not None else close + 1,
                "low": low if low is not None else close - 1, "close": close, "volume": 1000.0}

    base = [mk(0, 100.0), mk(1, 100.0)]  # event on the day-1 bar; entry_price 100
    event = {"symbol": "T", "event_date": base[1]["date"], "close": 100.0}
    no_div = 9.99  # divergence threshold high enough that the source-divergence flag never trips

    # STOP: a −10% low on a normally-traded bar fills the 8% stop.
    stop_bars = base + [mk(2, 95.0, high=99.0, low=90.0)] + [mk(i, 96.0) for i in range(3, 25)]
    stop_row = reprice_candidate(event, stop_bars, 0.08, 0.08, no_div)
    assert stop_row["intrabar_exit_reason"] == "stop" and stop_row["intrabar_return_pct"] == -8.0, stop_row

    # TARGET: a +10% high with a benign low fills the 8% target.
    target_bars = base + [mk(2, 108.0, high=110.0, low=99.5)] + [mk(i, 108.0) for i in range(3, 25)]
    target_row = reprice_candidate(event, target_bars, 0.08, 0.08, no_div)
    assert target_row["intrabar_exit_reason"] == "target" and target_row["intrabar_return_pct"] == 8.0, target_row

    # TIE-BREAK: one bar breaches BOTH bands -> conservative STOP wins.
    both_bars = base + [mk(2, 100.0, high=112.0, low=90.0)] + [mk(i, 100.0) for i in range(3, 25)]
    assert reprice_candidate(event, both_bars, 0.08, 0.08, no_div)["intrabar_exit_reason"] == "stop"

    # LOWER-CIRCUIT carry: a frozen −10% day can't fill the stop (no buyers) -> not stopped there.
    lock_bars = base + [mk(2, 90.0, high=90.0, low=90.0)] + [mk(i, 95.0) for i in range(3, 25)]
    assert reprice_candidate(event, lock_bars, 0.08, 0.20, no_div)["intrabar_return_pct"] != -8.0

    # TIME exit: neither band hit -> falls back to close-to-close.
    calm_bars = base + [mk(i, 101.0) for i in range(2, 25)]
    calm_row = reprice_candidate(event, calm_bars, 0.20, 0.20, no_div)
    assert calm_row["intrabar_exit_reason"] == "time", calm_row

    # H1 — circuit reference is the ENTRY close, not the pre-entry day. Pre-entry 90, entry 100, first
    # forward bar FROZEN at 91: vs entry (100) that's a LOWER lock -> stop must CARRY, not fill. With the
    # off-by-one (ref 90) it reads as "up" and wrongly fills the stop at −8%.
    h1_bars = [mk(0, 90.0), mk(1, 100.0), mk(2, 91.0, high=91.0, low=91.0)] + [mk(i, 95.0) for i in range(3, 25)]
    h1_event = {"symbol": "H1", "event_date": h1_bars[1]["date"], "close": 100.0}
    assert reprice_candidate(h1_event, h1_bars, 0.08, 0.20, no_div)["intrabar_return_pct"] != -8.0

    # H2 — the extension (days 21..25) is searched ONLY for a locked-stop carry. A NON-locked stop touch
    # on day 21 must be ignored (beyond the 20-day horizon) -> time exit, not a stop.
    h2_bars = base + [mk(i, 101.0) for i in range(2, 22)] + [mk(22, 90.0, high=99.0, low=90.0)] + \
        [mk(i, 101.0) for i in range(23, 27)]
    assert reprice_candidate(event, h2_bars, 0.08, 0.20, no_div)["intrabar_exit_reason"] == "time"

    # CORP-ACTION guard: a −50% non-circuit gap mid-window (unadjusted split/bonus) is flagged; calm is not.
    split_bars = base + [mk(2, 50.0, high=52.0, low=49.0)] + [mk(i, 50.0) for i in range(3, 25)]
    assert reprice_candidate(event, split_bars, 0.08, 0.08, no_div)["corp_action_suspect"] is True
    assert calm_row["corp_action_suspect"] is False, calm_row

    # SOURCE divergence: Fyers entry 100 vs cache-adjusted close 50 -> +100% > 5% -> flagged; a matching
    # cache close is not. (Exclusion is a flag; it does not change the return calc.)
    assert reprice_candidate({"symbol": "D", "event_date": base[1]["date"], "close": 50.0},
                             calm_bars, 0.20, 0.20, 0.05)["source_divergent"] is True
    assert reprice_candidate({"symbol": "N", "event_date": base[1]["date"], "close": 100.0},
                             calm_bars, 0.20, 0.20, 0.05)["source_divergent"] is False

    # ENTRY blocked on an upper-circuit event bar.
    blocked = reprice_candidate(
        {"symbol": "T", "event_date": base[1]["date"], "close": 100.0},
        [mk(0, 100.0), mk(1, 110.0, high=110.0, low=110.0)] + [mk(i, 110.0) for i in range(2, 25)],
        0.08, 0.08, no_div)
    assert blocked["entry_blocked"] is True, blocked

    print("nubra_fyers_revalidate self-check OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
    else:
        main()

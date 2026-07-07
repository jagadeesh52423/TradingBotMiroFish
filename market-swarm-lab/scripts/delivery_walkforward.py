"""Task #10 STEP 3 — walk-forward comparison: does delivery-confirmed selection lift the Core
system's hit-rate, or just shrink n?

Reuses the UNMODIFIED CatalystScreener (services/nse_event_calendar/catalyst_screener.py) against
the existing yfinance walk-forward cache (services/backtest/.walkfwd_cache.json), sweeping the
delivery-filter settings described in docs/catalyst_meanreversion_system.md's "Core" system
(exclude earnings + liquid + below-MA; regime is reported as a breakdown, not a hard filter here —
matching the doc's "Core" row, since that's the 59-63% row the delivery filter is being tested
against). Delivery via services.nse_delivery.NseDeliveryCollector, prefetched once.

PIT: deliv_lag_days is FORCED >=1 in every run (never trust a caller-supplied 0) — the collector's
own docstring flags DELIV_PER as EOD-published, so day-D delivery must never gate a day-D-close
entry.

Time-exit only (20-day close-to-close), matching the doc's methodology — same as the validated
Core system, no intrabar modeling (that's Task #9's separate Fyers re-validation).

*** EXPLORATORY / research — NOT investment advice. ***
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.nse_delivery.delivery_collector import NseDeliveryCollector
from services.nse_event_calendar.catalyst_screener import CatalystScreener, InMemoryPriceSource, ScreenerConfig

_CACHE_PATH = _ROOT / "services" / "backtest" / ".walkfwd_cache.json"
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"
_HOLD_DAYS = 20
_TRAILING_BACKFILL_DAYS = 35  # calendar-day slack before the earliest event, for deliv_trailing_days=20

# Walk-forward windows: calendar months back from "today" (the cache's build date), matching the
# doc's 0-3/3-6/6-9mo table.
_WINDOWS = [("0-3mo", 0, 3), ("3-6mo", 3, 6), ("6-9mo", 6, 9)]

# Sweep per team-lead: baseline (no delivery) + default-or + stricter combine=and + stricter min_pct.
_SETTINGS = [
    {"label": "BASELINE (no delivery)", "require_delivery": False},
    {"label": "delivery OR (min55/spike1.2x)", "require_delivery": True,
     "deliv_min_pct": 55.0, "deliv_spike_mult": 1.2, "deliv_combine": "or"},
    {"label": "delivery AND (min55/spike1.2x, stricter)", "require_delivery": True,
     "deliv_min_pct": 55.0, "deliv_spike_mult": 1.2, "deliv_combine": "and"},
    {"label": "delivery OR min65", "require_delivery": True,
     "deliv_min_pct": 65.0, "deliv_spike_mult": 1.2, "deliv_combine": "or"},
    {"label": "delivery OR min70", "require_delivery": True,
     "deliv_min_pct": 70.0, "deliv_spike_mult": 1.2, "deliv_combine": "or"},
]


def load_cache() -> tuple[dict[str, list[dict]], list[dict], date]:
    cache = json.loads(_CACHE_PATH.read_text())
    bars_by_symbol: dict[str, list[dict]] = {}
    for symbol, entry in cache["prices"].items():
        median_volume = entry.get("mv", 0.0)
        bars = [
            {"date": datetime.strptime(day, "%Y-%m-%d").date(), "close": close, "volume": median_volume}
            for day, close in entry["c"].items()
        ]
        bars.sort(key=lambda bar: bar["date"])
        bars_by_symbol[symbol] = bars
    events = [
        {"date": datetime.strptime(event["date"], "%Y-%m-%d").strftime("%d-%b-%Y"),
         "symbol": event["symbol"], "catalyst_type": event["type"]}
        for event in cache["events"]
    ]
    built = datetime.strptime(cache["built"], "%Y-%m-%d").date()
    return bars_by_symbol, events, built


def time_exit_return(bars: list[dict], event_date: date) -> float | None:
    """20-trading-day close-to-close return from the entry bar (last bar with date<=event_date)."""
    entry_index = None
    for i, bar in enumerate(bars):
        if bar["date"] <= event_date:
            entry_index = i
        else:
            break
    if entry_index is None:
        return None
    exit_index = min(entry_index + _HOLD_DAYS, len(bars) - 1)
    if exit_index <= entry_index:
        return None
    return 100 * (bars[exit_index]["close"] / bars[entry_index]["close"] - 1)


def window_bucket(event_date: date, today: date) -> str | None:
    age_days = (today - event_date).days
    for label, lo_mo, hi_mo in _WINDOWS:
        if lo_mo * 30 <= age_days < hi_mo * 30:
            return label
    return None


def summarize(returns: list[float]) -> dict:
    if not returns:
        return {"n": 0, "median_return_pct": None, "hit_rate_pct": None}
    return {
        "n": len(returns),
        "median_return_pct": round(median(returns), 2),
        "hit_rate_pct": round(100 * sum(1 for r in returns if r > 0) / len(returns), 1),
    }


def run_setting(cfg: ScreenerConfig, events: list[dict], bars_by_symbol: dict[str, list[dict]],
                regime_universe: list[str], deliv_source: NseDeliveryCollector | None, today: date) -> dict:
    screener = CatalystScreener(InMemoryPriceSource(bars_by_symbol), regime_universe, cfg,
                                delivery_source=deliv_source)
    candidates = screener.screen(events)
    by_window: dict[str, list[float]] = {label: [] for label, _, _ in _WINDOWS}
    regime_ok_count = 0
    for candidate in candidates:
        event_date = datetime.strptime(candidate.date, "%d-%b-%Y").date()
        bucket = window_bucket(event_date, today)
        if bucket is None:
            continue
        ret = time_exit_return(bars_by_symbol[candidate.symbol], event_date)
        if ret is None:
            continue
        by_window[bucket].append(ret)
        if candidate.regime_ok:
            regime_ok_count += 1
    return {
        "total_candidates": len(candidates),
        "regime_ok_candidates": regime_ok_count,
        "windows": {label: summarize(returns) for label, returns in by_window.items()},
    }


def main() -> None:
    bars_by_symbol, events, today = load_cache()
    config = json.loads(_CONFIG_PATH.read_text())
    regime_universe = config.get("universes", {}).get(
        config.get("catalyst_screener", {}).get("regime_universe", "midcap150"), [])

    event_dates = [datetime.strptime(e["date"], "%d-%b-%Y").date() for e in events]
    prefetch_from = min(event_dates) - timedelta(days=_TRAILING_BACKFILL_DAYS)
    prefetch_to = max(event_dates)
    print(f"prefetching delivery bhavcopy {prefetch_from} .. {prefetch_to} ...", flush=True)
    collector = NseDeliveryCollector()
    cached_days = collector.prefetch_range(prefetch_from, prefetch_to)
    print(f"delivery data cached for {cached_days} trading days", flush=True)

    results = {}
    for setting in _SETTINGS:
        label = setting["label"]
        cfg_kwargs = {k: v for k, v in setting.items() if k != "label"}
        if cfg_kwargs.get("require_delivery"):
            cfg_kwargs["deliv_lag_days"] = max(1, cfg_kwargs.get("deliv_lag_days", 1))  # PIT floor, never 0
        cfg = ScreenerConfig(**cfg_kwargs)
        source = collector if cfg.require_delivery else None
        print(f"\n=== {label} ===", flush=True)
        result = run_setting(cfg, events, bars_by_symbol, regime_universe, source, today)
        results[label] = result
        print(json.dumps(result, indent=2))

    out_path = _ROOT / "services" / "backtest" / "delivery_walkforward_report.json"
    out_path.write_text(json.dumps(
        {"note": "EXPLORATORY — not investment advice. Time-exit (20d close-to-close) only, "
                 "matching docs/catalyst_meanreversion_system.md Core methodology. "
                 "deliv_lag_days forced >=1 in all delivery runs (PIT).",
         "built": str(today), "results": results}, indent=2))
    print(f"\nfull report written to {out_path}")


if __name__ == "__main__":
    main()

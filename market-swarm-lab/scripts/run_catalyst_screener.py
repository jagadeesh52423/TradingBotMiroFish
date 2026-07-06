"""CLI for the NSE Catalyst Mean-Reversion screener (spec: docs/catalyst_meanreversion_system.md).

Pulls recent NSE corporate events MARKET-WIDE (all equities the calendar returns) by default —
the validated edge lives in liquidity-filtered small/mid-caps, not the ~2-catalyst/14d Nifty50 —
applies the rules (exclude earnings, liquid, below-20d-MA) via CatalystScreener, and prints
ranked candidates (regime_ok first). Price data via yfinance SYMBOL.NS (swappable to Fyers later).

Universe (`--universe`): market [default] = every event symbol; nifty50 = the config whitelist;
or a comma-separated custom list (e.g. --universe RELIANCE,LT). The liquidity filter does the
narrowing. The regime breadth index always uses the Nifty50 whitelist as a stable market proxy.

*** EXPLORATORY / research — NOT investment advice. ***
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_ROOT = pathlib.Path(__file__).resolve().parents[1]  # .../market-swarm-lab
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
logging.basicConfig(level=logging.WARNING)

from services.nse_event_calendar.catalyst_screener import (
    CatalystScreener,
    ScreenerConfig,
    YFinancePriceSource,
)
from services.nse_event_calendar.nse_event_calendar_collector import NseEventCalendarCollector

_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"
_LOOKBACK_DAYS = 14  # ~10 trading days of recent events


def _parse_universe(argv: list[str]) -> str:
    for index, arg in enumerate(argv):
        if arg == "--universe" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--universe="):
            return arg.split("=", 1)[1]
    return "market"


def _screen_symbols(universe_spec: str, whitelist: list[str]) -> list[str] | None:
    """None = screen every event symbol (market-wide). Otherwise the symbols to keep."""
    if universe_spec == "market":
        return None
    if universe_spec == "nifty50":
        return whitelist
    return [sym.strip().upper() for sym in universe_spec.split(",") if sym.strip()]


def run(universe_spec: str = "market") -> list[dict]:
    config = json.loads(_CONFIG_PATH.read_text())
    whitelist = config.get("whitelist", [])
    collector = NseEventCalendarCollector.from_config(config)
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
    events = collector.collect_range(from_date, to_date)
    symbols = _screen_symbols(universe_spec, whitelist)
    if symbols is not None:
        events = collector.filter_whitelist(events, symbols)

    # Regime breadth index uses the Nifty50 whitelist as a stable market-regime proxy,
    # independent of the (market-wide) screening set.
    screener = CatalystScreener(YFinancePriceSource(), whitelist, ScreenerConfig.from_config(config))
    return [candidate.to_row() for candidate in screener.screen(events)]


def _print_report(rows: list[dict], universe_spec: str = "market") -> None:
    print("=" * 90)
    print("NSE CATALYST MEAN-REVERSION SCREENER — EXPLORATORY / research, NOT investment advice.")
    print(f"Universe: {universe_spec}. Daily-close only: no pre-open gap, no 15-min confirm, no circuit modeling.")
    print("=" * 90)
    if not rows:
        print(f"\nNo candidates (no recent '{universe_spec}' catalyst passed exclude-earnings + liquid + below-MA).")
        return
    print(f"\n{len(rows)} candidate(s), regime_ok first:\n")
    print(f"  {'SYMBOL':<12} {'TYPE':<11} {'DATE':<12} {'CLOSE':>9} {'%<MA':>7} {'TURNOVER(Cr)':>13} {'REGIME':>7}")
    for row in rows:
        print(f"  {row['symbol']:<12} {row['catalyst_type']:<11} {row['date']:<12} "
              f"{row['close']:>9.2f} {row['pct_below_ma']:>6.2f}% {row['turnover']/1e7:>12.2f} "
              f"{'OK' if row['regime_ok'] else 'off':>7}")
    print("\nEach row's thesis states its mean-reversion hold horizon. Ranked regime_ok first;")
    print("within, most-below-MA first. EXPLORATORY / research — paper-trade before any capital.")


if __name__ == "__main__":
    from services.nse_event_calendar.catalyst_screener import _self_check
    _self_check()
    if "--self-check" not in sys.argv:
        universe_spec = _parse_universe(sys.argv)
        _print_report(run(universe_spec), universe_spec)

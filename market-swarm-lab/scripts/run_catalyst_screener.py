"""CLI for the NSE Catalyst Mean-Reversion screener (spec: docs/catalyst_meanreversion_system.md).

Pulls recent NSE corporate events MARKET-WIDE (all equities the calendar returns) by default —
the validated edge lives in liquidity-filtered small/mid-caps, not the ~2-catalyst/14d Nifty50 —
applies the rules (exclude earnings, liquid, below-20d-MA) via CatalystScreener, and prints
ranked candidates (regime_ok first). Price data via yfinance SYMBOL.NS (swappable to Fyers later).

Universe (`--universe`): market [default] = every event symbol; nifty50 = the config whitelist;
or a comma-separated custom list (e.g. --universe RELIANCE,LT). The liquidity filter does the
narrowing. The regime breadth index uses config catalyst_screener.regime_universe (default
midcap150 — small/mid breadth, since the regime gate exists to sit out SMALL-CAP bear phases).

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
from services.nse_delivery.delivery_collector import NseDeliveryCollector
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


def run(universe_spec: str = "market") -> tuple[list[dict], tuple[int, int]]:
    config = json.loads(_CONFIG_PATH.read_text())
    whitelist = config.get("whitelist", [])
    collector = NseEventCalendarCollector.from_config(config)
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
    events = collector.collect_range(from_date, to_date)
    symbols = _screen_symbols(universe_spec, whitelist)
    if symbols is not None:
        events = collector.filter_whitelist(events, symbols)

    # Regime breadth index uses a config-named small/mid universe (default midcap150) so the
    # regime flag reflects the small-cap phase it exists to sit out, not large-cap Nifty50.
    regime_universe = config.get("catalyst_screener", {}).get("regime_universe", "midcap150")
    breadth_symbols = config.get("universes", {}).get(regime_universe) or whitelist
    screener_cfg = ScreenerConfig.from_config(config)
    # Delivery confirmation is a config toggle (catalyst_screener.require_delivery). Attach the
    # collector only when on; otherwise the filter is a no-op and no delivery CSVs are fetched.
    delivery_source = NseDeliveryCollector.from_config(config) if screener_cfg.require_delivery else None
    screener = CatalystScreener(YFinancePriceSource(), breadth_symbols, screener_cfg,
                                delivery_source=delivery_source)
    rows = [candidate.to_row() for candidate in screener.screen(events)]
    return rows, screener.regime_coverage()


def _print_report(rows: list[dict], universe_spec: str = "market",
                  regime_coverage: tuple[int, int] | None = None) -> None:
    print("=" * 90)
    print("NSE CATALYST MEAN-REVERSION SCREENER — EXPLORATORY / research, NOT investment advice.")
    print(f"Universe: {universe_spec}. Daily-close only: no pre-open gap, no 15-min confirm, no circuit modeling.")
    if regime_coverage:
        print(f"Regime breadth index built from {regime_coverage[0]}/{regime_coverage[1]} universe symbols resolved.")
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
        rows, regime_coverage = run(universe_spec)
        _print_report(rows, universe_spec, regime_coverage)

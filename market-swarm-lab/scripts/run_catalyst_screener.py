"""CLI for the NSE Catalyst Mean-Reversion screener (spec: docs/catalyst_meanreversion_system.md).

Pulls recent NSE corporate events for the Nifty50 whitelist, applies the validated rules
(exclude earnings, liquid, below-20d-MA) via CatalystScreener, and prints ranked candidates
(regime_ok first). Price data via yfinance SYMBOL.NS (swappable to Fyers later).

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


def run() -> list[dict]:
    config = json.loads(_CONFIG_PATH.read_text())
    whitelist = config.get("whitelist", [])
    collector = NseEventCalendarCollector.from_config(config)
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
    events = collector.filter_whitelist(collector.collect_range(from_date, to_date), whitelist)

    screener = CatalystScreener(YFinancePriceSource(), whitelist, ScreenerConfig.from_config(config))
    return [candidate.to_row() for candidate in screener.screen(events)]


def _print_report(rows: list[dict]) -> None:
    print("=" * 90)
    print("NSE CATALYST MEAN-REVERSION SCREENER — EXPLORATORY / research, NOT investment advice.")
    print("Daily-close only: no pre-open gap, no first-15-min confirmation, no circuit modeling.")
    print("=" * 90)
    if not rows:
        print("\nNo candidates today (no recent Nifty50 catalyst passed exclude-earnings + liquid + below-MA).")
        return
    print(f"\n{len(rows)} candidate(s), regime_ok first:\n")
    print(f"  {'SYMBOL':<12} {'TYPE':<11} {'DATE':<12} {'CLOSE':>9} {'%<MA':>7} {'TURNOVER(Cr)':>13} {'REGIME':>7}")
    for row in rows:
        print(f"  {row['symbol']:<12} {row['catalyst_type']:<11} {row['date']:<12} "
              f"{row['close']:>9.2f} {row['pct_below_ma']:>6.2f}% {row['turnover']/1e7:>12.2f} "
              f"{'OK' if row['regime_ok'] else 'off':>7}")
    print("\nThesis (each candidate): mean-reversion on a non-earnings catalyst, hold ~20 trading days.")
    print("Ranked regime_ok first; within, most-below-MA first. EXPLORATORY — paper-trade before capital.")


if __name__ == "__main__":
    from services.nse_event_calendar.catalyst_screener import _self_check
    _self_check()
    if "--self-check" not in sys.argv:
        _print_report(run())

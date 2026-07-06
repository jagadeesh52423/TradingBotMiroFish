"""EXPLORATORY NSE event study — catalyst-date close-to-close reactions.

For the last ~14 days it pulls the NSE event calendar for the Nifty50 whitelist and, per
event, measures the close-to-close move around the event date: -1d pre-move and +1/+2/+3/+5d
forward returns, summarized by catalyst type.

*** EXPLORATORY ONLY — NOT a playbook backtest, NOT a win rate. ***
  - Daily CLOSE only: no intraday, no pre-open gap, no surprise-magnitude conditioning.
  - Tiny sample (~14 days of NSE history): a handful of events per catalyst type.
  - Forward returns are PIT-safe: an event maps to the first price bar ON/AFTER its date, and
    +Nd uses only bars at/after that bar — recent events simply have fewer forward points.

Price source: the Stage-A cache stores closes WITHOUT dates, so a date-correct join needs dated
bars — this script fetches dated daily closes (close + timestamp) per event symbol via the same
market-data-only Nubra client the backtester uses. The cache's `symbols_ok` is the
price-availability universe: events on names outside it are noted 'no price data'.
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean

_ROOT = pathlib.Path(__file__).resolve().parents[1]  # .../market-swarm-lab (scripts/..)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
logging.basicConfig(level=logging.WARNING)
_log = logging.getLogger(__name__)

from services.nse_event_calendar.nse_event_calendar_collector import (
    NseEventCalendarCollector,
    parse_event_date,
)

_CACHE_PATH = _ROOT / "services" / "backtest" / ".stageA_cache.json"
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"
_LOOKBACK_DAYS = 14
_FORWARDS = (1, 2, 3, 5)
_PRICE_LOOKBACK = 90          # dated daily bars per symbol (Nubra caps ~69) — covers the window
_IST_OFFSET = timedelta(hours=5, minutes=30)  # NSE bar timestamps -> Indian trading date


def _ist_date(timestamp_ms: int) -> date:
    return (datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc) + _IST_OFFSET).date()


def event_reaction(dated_closes: list[tuple[date, float]], event_date: date,
                   forwards: tuple[int, ...] = _FORWARDS) -> dict:
    """PIT-safe close-to-close reaction. `dated_closes` = [(date, close)] ascending.

    The event maps to index j = first bar with date >= event_date; +Nd uses only bars at index
    >= j (dates on/after the event), so nothing peeks past what was knowable. -1d is the pre-event
    move (bar j-1 -> j) — labeled separately, never mixed into the forward reaction."""
    event_bar = next((i for i, (bar_date, _) in enumerate(dated_closes) if bar_date >= event_date), None)
    if event_bar is None:
        return {"mapped_date": None, "note": "event on/after last price bar — no reaction data"}
    closes = [close for _, close in dated_closes]
    base = closes[event_bar]
    reaction: dict = {"mapped_date": dated_closes[event_bar][0].isoformat()}
    reaction["-1d"] = round(base / closes[event_bar - 1] - 1, 4) if event_bar - 1 >= 0 else None
    for horizon in forwards:
        idx = event_bar + horizon
        reaction[f"+{horizon}d"] = round(closes[idx] / base - 1, 4) if idx < len(closes) else None
    return reaction


def _dated_closes(client, symbol: str) -> list[tuple[date, float]] | None:
    try:
        bars = client.historical(symbol, "1d", lookback=_PRICE_LOOKBACK)
    except Exception as exc:
        _log.warning("price fetch failed for %s: %s", symbol, exc)
        return None
    dated = [(_ist_date(bar["timestamp"]), float(bar["close"])) for bar in bars if "timestamp" in bar]
    dated.sort(key=lambda pair: pair[0])
    return dated or None


def run_study() -> tuple[list[dict], dict]:
    cache = json.loads(_CACHE_PATH.read_text())
    universe = set(cache.get("meta", {}).get("symbols_ok") or cache.get("symbols", {}).keys())
    config = json.loads(_CONFIG_PATH.read_text())
    whitelist = config.get("whitelist", [])

    collector = NseEventCalendarCollector.from_config(config)
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
    events = collector.filter_whitelist(collector.collect_range(from_date, to_date), whitelist)

    from services.backtest.nubra_equity_backtest import _market_data_client  # proven anti-timeout construction
    client = None
    price_by_symbol: dict[str, list[tuple[date, float]] | None] = {}
    rows: list[dict] = []
    for event in sorted(events, key=lambda e: ((e.get("symbol") or ""), e.get("date") or "")):
        symbol = (event.get("symbol") or "").upper()
        catalyst = event.get("catalyst_type", "Other")
        row = {"symbol": symbol, "date": event.get("date"), "type": catalyst}
        event_date = parse_event_date(event.get("date", ""))
        if symbol not in universe:
            rows.append({**row, "note": "no price data (not in Stage-A universe)"})
            continue
        if event_date is None:
            rows.append({**row, "note": "unparseable event date"})
            continue
        if symbol not in price_by_symbol:
            if client is None:
                client = _market_data_client()
            price_by_symbol[symbol] = _dated_closes(client, symbol)
        dated = price_by_symbol[symbol]
        if not dated:
            rows.append({**row, "note": "price fetch failed"})
            continue
        rows.append({**row, **event_reaction(dated, event_date)})
    return rows, _summarize(rows)


def _summarize(rows: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if "+5d" in row or "+2d" in row:  # rows with a computed reaction (not the 'note' rows)
            by_type[row["type"]].append(row)
    summary: dict = {}
    for catalyst, catalyst_rows in by_type.items():
        moves_2d = [r["+2d"] for r in catalyst_rows if r.get("+2d") is not None]
        moves_5d = [r["+5d"] for r in catalyst_rows if r.get("+5d") is not None]
        summary[catalyst] = {
            "n_events": len(catalyst_rows),
            "avg_+2d_pct": round(100 * mean(moves_2d), 2) if moves_2d else None,
            "avg_+5d_pct": round(100 * mean(moves_5d), 2) if moves_5d else None,
            "pct_positive_+2d": round(100 * sum(m > 0 for m in moves_2d) / len(moves_2d), 1) if moves_2d else None,
            "pct_positive_+5d": round(100 * sum(m > 0 for m in moves_5d) / len(moves_5d), 1) if moves_5d else None,
        }
    return summary


def _print_report(rows: list[dict], summary: dict) -> None:
    print("=" * 78)
    print("EXPLORATORY NSE EVENT STUDY — daily-close reactions, ~14d, small sample.")
    print("NOT a playbook backtest / NOT a win rate. No intraday, no gap, no surprise magnitude.")
    print("=" * 78)
    print("\nPer-event reactions (returns in %):")
    for row in rows:
        if "note" in row:
            print(f"  {row['symbol']:<12} {row.get('date','?'):<12} {row['type']:<12} — {row['note']}")
        else:
            fwd = "  ".join(
                f"{k}={row[k]*100:+.2f}%" if row.get(k) is not None else f"{k}=  n/a"
                for k in ("-1d", "+1d", "+2d", "+3d", "+5d")
            )
            print(f"  {row['symbol']:<12} {row.get('date','?'):<12} {row['type']:<12}  {fwd}")
    print("\nSummary by catalyst type (EXPLORATORY):")
    print(json.dumps(summary, indent=2))


def _self_check() -> None:
    """Offline PIT checks on event_reaction — no network."""
    series = [
        (date(2026, 7, 1), 100.0), (date(2026, 7, 2), 102.0), (date(2026, 7, 3), 101.0),
        (date(2026, 7, 4), 105.0), (date(2026, 7, 7), 110.0), (date(2026, 7, 8), 108.0),
        (date(2026, 7, 9), 112.0),
    ]
    # Event on the first bar: forwards count trading bars ahead; no -1d (nothing before it).
    first = event_reaction(series, date(2026, 7, 1))
    assert first["-1d"] is None, first
    assert first["+1d"] == round(102 / 100 - 1, 4), first
    assert first["+3d"] == round(105 / 100 - 1, 4), first

    # PIT guard: event on the LAST bar can have NO forward returns — reaction cannot peek ahead.
    last = event_reaction(series, date(2026, 7, 9))
    assert all(last[f"+{n}d"] is None for n in _FORWARDS), last
    assert last["-1d"] == round(112 / 108 - 1, 4), last

    # Event on a non-trading date (Sun 5-Jul) maps FORWARD to the next bar (7-Jul), never back.
    holiday = event_reaction(series, date(2026, 7, 5))
    assert holiday["mapped_date"] == "2026-07-07", holiday
    assert holiday["+1d"] == round(108 / 110 - 1, 4), holiday

    # Event beyond all price data -> no reaction, explicit note.
    beyond = event_reaction(series, date(2026, 7, 20))
    assert beyond.get("mapped_date") is None and "note" in beyond, beyond
    print("event-study self-check OK")


if __name__ == "__main__":
    _self_check()
    if "--self-check" not in sys.argv:
        rows, summary = run_study()
        _print_report(rows, summary)

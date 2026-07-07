#!/usr/bin/env python3
"""Backtest elected watchlist picks with a real held-and-exit P&L (§5/§13).

For each elected pick in Mongo (entry_ltp + run_date captured at scan time), fetch the daily
OHLC bars AFTER entry from Fyers and simulate the hold: time-exit at N sessions (the repo's
validated model) and, when targets were stored, an intrabar T1/SL scenario (conservative).
Aggregates via the §13 expectancy engine.

    python3 scripts/backtest_watchlist.py                # time-exit, hold 3 sessions
    python3 scripts/backtest_watchlist.py --hold 5 --json

EXPLORATORY. A pick whose hold window hasn't elapsed yet is reported as pending (no forward data).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from services.watchlist_store.mongo_store import WatchlistStore
from services.nubra_client.backtest_sim import simulate_hold
from services.nubra_client.expectancy import compute_expectancy

_IST = __import__("datetime").timezone(timedelta(hours=5, minutes=30))


def _forward_bars(fyers, symbol: str, entry_day: date, hold_days: int) -> list[dict]:
    """Daily bars strictly AFTER entry_day, oldest-first (up to ~hold_days sessions)."""
    end = entry_day + timedelta(days=hold_days * 3 + 5)  # calendar buffer over weekends/holidays
    try:
        bars = fyers.ohlcv_range(symbol, entry_day + timedelta(days=1), end, interval="1d")
    except Exception:
        return []
    out = []
    for b in bars:
        d = datetime.fromtimestamp(b["timestamp"] / 1000, tz=_IST).date()
        if d > entry_day:
            out.append({"high": b["high"], "low": b["low"], "close": b["close"], "date": d})
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Backtest elected watchlist picks (held-and-exit)")
    parser.add_argument("--hold", type=int, default=3, help="sessions to hold (time-exit)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass
    from services.fyers_client.fyers_data_provider import FyersDataProvider

    store = WatchlistStore()
    history = store.elected_history()
    store.close()
    fyers = FyersDataProvider.from_config({})

    trades, pending, per_run = [], 0, []
    for run in history:
        try:
            entry_day = date.fromisoformat(run["run_date"])
        except (ValueError, TypeError):
            continue
        run_trades = []
        for pick in run["elected"]:
            entry = pick.get("entry_ltp")
            if not entry:
                continue
            bars = _forward_bars(fyers, pick["symbol"], entry_day, args.hold)
            sim = simulate_hold(float(entry), bars, hold_days=args.hold, targets=pick.get("targets"))
            if sim.get("return_pct") is None:
                pending += 1
                continue
            run_trades.append({"symbol": pick["symbol"], **sim})
        trades += run_trades
        if run_trades:
            per_run.append({"run_date": run["run_date"], "n": len(run_trades),
                            "avg_return_pct": round(sum(t["return_pct"] for t in run_trades) / len(run_trades), 2)})

    summary = compute_expectancy(trades)
    out = {"model": f"time_exit_{args.hold}d", "overall": summary, "per_run": per_run,
           "settled": len(trades), "pending": pending}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return
    print(f"=== watchlist backtest (time-exit {args.hold}d): {len(trades)} settled, {pending} pending ===")
    if summary.get("trades"):
        print(f"win_rate={summary['win_rate']:.0%}  avg_return={summary['avg_return_pct']:.2f}%  "
              f"expectancy={summary['expectancy_pct']:.2f}%")
    for r in per_run:
        print(f"  {r['run_date']}  n={r['n']:>3}  avg {r['avg_return_pct']:+.2f}%")
    if not trades:
        print("  (no settled trades yet — picks need their hold window to elapse)")


if __name__ == "__main__":
    main()

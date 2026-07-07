#!/usr/bin/env python3
"""Backtest the elected watchlist picks against Fyers forward prices.

For every elected pick stored in Mongo (entry_ltp captured at run time), fetch the current
Fyers price and compute the forward return since entry. Prints per-run and overall stats.

    python3 scripts/backtest_watchlist.py          # all stored runs
    python3 scripts/backtest_watchlist.py --json

EXPLORATORY: forward return to *now*, not a held-and-exited P&L. Directional gut-check only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from services.watchlist_store.mongo_store import WatchlistStore
from services.nubra_client.expectancy import compute_expectancy


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Backtest elected watchlist picks (Fyers forward price)")
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

    trades, per_run = [], []
    price_cache: dict[str, float | None] = {}
    for run in history:
        run_trades = []
        for pick in run["elected"]:
            entry = pick.get("entry_ltp")
            sym = pick["symbol"]
            if not entry:
                continue
            if sym not in price_cache:
                try:
                    price_cache[sym] = float(fyers.current_price(sym))
                except Exception:
                    price_cache[sym] = None
            now = price_cache[sym]
            if not now:
                continue
            ret = round((now - entry) / entry * 100, 2)
            run_trades.append({"symbol": sym, "entry": entry, "now": now, "return_pct": ret})
        trades += run_trades
        if run_trades:
            per_run.append({"run_date": run["run_date"], "n": len(run_trades),
                            "avg_return_pct": round(sum(t["return_pct"] for t in run_trades) / len(run_trades), 2)})

    summary = compute_expectancy(trades)
    out = {"overall": summary, "per_run": per_run, "trade_count": len(trades)}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return
    print(f"=== watchlist backtest: {len(trades)} elected picks across {len(per_run)} runs ===")
    if summary.get("trades"):
        print(f"win_rate={summary['win_rate']:.0%}  avg_return={summary['avg_return_pct']:.2f}%  "
              f"expectancy={summary['expectancy_pct']:.2f}%")
    for r in per_run:
        print(f"  {r['run_date']}  n={r['n']:>3}  avg {r['avg_return_pct']:+.2f}%")


if __name__ == "__main__":
    main()

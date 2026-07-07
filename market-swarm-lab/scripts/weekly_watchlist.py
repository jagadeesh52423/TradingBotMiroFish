#!/usr/bin/env python3
"""§2 weekly setup: emit next-week's candidate watchlist, ranked by the 5-factor score.

Runs the scanner dry-run (read-only, no orders) and ranks the actionable, catalyst-driven
candidates by their watchlist_score (catalyst / sector / band / liquidity / F&O).

    python3 scripts/weekly_watchlist.py                 # default universe
    python3 scripts/weekly_watchlist.py --universe nifty50
    python3 scripts/weekly_watchlist.py --json          # full JSON instead of the table
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from services.nubra_client.equity_runner import build_runner, load_config
from services.nubra_client.universe_registry import resolve_universe, load_universes_from_config

_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[1] / "config" / "nubra_config.json"


def _ranked(results: list[dict]) -> list[dict]:
    scored = [r for r in results if (r.get("watchlist") or {}).get("score") is not None]
    return sorted(scored, key=lambda r: r["watchlist"]["score"], reverse=True)


def _print_table(ranked: list[dict]) -> None:
    if not ranked:
        print("No scored candidates (no actionable signals this scan).")
        return
    print(f"{'#':>2}  {'SYMBOL':<12} {'SCORE':>6}  {'TRADE':<5} {'NEWS':<8} FACTORS")
    for i, r in enumerate(ranked, 1):
        wl = r["watchlist"]
        factors = {k: round(v, 2) for k, v in (wl.get("factors") or {}).items() if v is not None}
        sig = r.get("signal") or {}
        print(f"{i:>2}  {r['symbol']:<12} {wl['score']:>6.3f}  {sig.get('trade', '-'):<5} "
              f"{str(r.get('nse_sentiment')):<8} {factors}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Weekly ranked watchlist (§2)")
    parser.add_argument("--universe")
    parser.add_argument("--json", action="store_true", help="print full JSON instead of the table")
    parser.add_argument("--nubra", action="store_true",
                        help="use the Nubra stack (needs a session); default is screen mode (Fyers only)")
    parser.add_argument("--save", action="store_true", help="persist this run to MongoDB (dashboard/backtest)")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Screen mode reads market data from Fyers — load the token from .env.
    try:
        from dotenv import load_dotenv
        load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass

    config = load_config(_CONFIG_PATH)
    load_universes_from_config(config)
    name = args.universe or config.get("universe")
    config["whitelist"] = resolve_universe(config, name)  # "catalyst" → live discovery (playbook §2)
    print(f"# universe '{name}' → {len(config['whitelist'])} names", flush=True)

    runner = build_runner(config, mode="nubra_uat" if args.nubra else "screen")
    summary = runner.run_once(dry_run=True)  # read-only
    ranked = _ranked(summary["results"])

    if args.json:
        print(json.dumps(ranked, indent=2, default=str))
    else:
        _print_table(ranked)

    if args.save:
        _save_run(summary["results"], name, config)


def _save_run(results, universe, config) -> None:
    from datetime import datetime, timedelta, timezone
    from services.watchlist_store.run_to_doc import run_to_doc
    from services.watchlist_store.mongo_store import WatchlistStore
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    doc = run_to_doc(results, universe=universe or "catalyst", run_date=now.date().isoformat(),
                     generated_at=now, sentiment_engine=config.get("nse", {}).get("sentiment_engine"),
                     catalyst_map=config.get("catalyst_map"))
    try:
        store = WatchlistStore()
        rid = store.save_run(doc)
        store.close()
        print(f"# saved run {rid} to MongoDB ({doc['counts']})", flush=True)
    except Exception as exc:  # Mongo down / unreachable — don't lose the screen output
        print(f"# WARNING: could not save to MongoDB: {exc}", flush=True)


if __name__ == "__main__":
    main()

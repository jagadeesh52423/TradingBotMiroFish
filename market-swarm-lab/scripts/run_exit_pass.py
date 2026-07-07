#!/usr/bin/env python3
"""Run the §5 time-stop exit pass over currently held positions.

Reads held longs from the broker, closes any aged past entry_threshold.time_stop.max_sessions
(circuit-lock aware — a lower-locked name is flagged, not force-sold), and logs each close to
the trade log for the expectancy tracker.

    python3 scripts/run_exit_pass.py --once            # place closes (live/paper broker)
    python3 scripts/run_exit_pass.py --once --dry-run   # report only, no orders

Intended to run on a schedule (e.g. once near close), separate from the entry scan.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from services.nubra_client.equity_runner import build_runner, load_config
from services.nubra_client.universe_registry import load_universes_from_config

_log = logging.getLogger("run_exit_pass")
_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[1] / "config" / "nubra_config.json"


def _held_long_symbols(broker) -> list[str]:
    try:
        return [r["symbol"] for r in broker.get_positions() if int(r.get("net_quantity", 0)) > 0]
    except Exception as exc:
        _log.warning("could not read positions: %s", exc)
        return []


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Time-stop exit pass")
    parser.add_argument("--once", action="store_true", help="run a single pass (default)")
    parser.add_argument("--dry-run", action="store_true", help="report only, place no orders")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    config = load_config(_CONFIG_PATH)
    load_universes_from_config(config)
    runner = build_runner(config)

    held = _held_long_symbols(runner._stack.broker)
    _log.info("held longs: %s", held)
    report = runner.run_time_stop_exits(held, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

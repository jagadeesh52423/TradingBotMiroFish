#!/usr/bin/env python3
"""Print the §13 compounding-tracker summary from a closed-trades JSON file.

Usage:
    python3 scripts/expectancy_report.py trades.json

trades.json is a list of closed trades, each: {"return_pct": <signed %>, optionally
"band_pct", "exit_fill_quality", "pnl_r"}. A live run / the time-stop exit pass writes
this log; this script is the read-only analysis over it.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from services.nubra_client.expectancy import compute_expectancy


def main(path: str) -> None:
    trades = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    print(json.dumps(compute_expectancy(trades), indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 scripts/expectancy_report.py <trades.json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])

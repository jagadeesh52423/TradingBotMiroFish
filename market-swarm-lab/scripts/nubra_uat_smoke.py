#!/usr/bin/env python3.11
"""Smoke-test the Nubra UAT integration end-to-end (requires a live session).

Usage:
    python3.11 scripts/nubra_uat_smoke.py [--symbol SBIN] [--qty 1]

Requires:
    - Valid ~/.nubra_session_UAT.json (run nubra_login.py first)
    - nubra_python_sdk installed and on PYTHONPATH
    - Market hours or UAT always-on endpoint

Steps:
    1. Load + validate session
    2. Resolve instrument ref_id for symbol
    3. Fetch current LTP
    4. Place a paper-dry-run LIMIT BUY at LTP (UAT: order may fill in UAT env)
    5. Poll order status × 3 with 5 s backoff
    6. Print result summary
"""
from __future__ import annotations

import sys


def main() -> None:
    raise NotImplementedError(
        "nubra_uat_smoke requires a live NubraSession and nubra_python_sdk. "
        "Production wiring:\n"
        "  from services.nubra_client.nubra_session import NubraSession\n"
        "  from services.nubra_client.nubra_client import NubraClient\n"
        "  from services.nubra_client.nubra_broker import NubraBroker\n"
        "  import json, pathlib\n"
        "  cfg = json.loads(pathlib.Path('config/nubra_config.json').read_text())\n"
        "  sess = NubraSession('UAT').load()\n"
        "  client = NubraClient.from_session(sess, cfg)\n"
        "  broker = NubraBroker(client)\n"
        "  # then place a test order and log result"
    )


if __name__ == "__main__":
    try:
        main()
    except NotImplementedError as exc:
        print(f"[nubra_uat_smoke] NOT IMPLEMENTED: {exc}", file=sys.stderr)
        sys.exit(1)

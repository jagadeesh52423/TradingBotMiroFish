#!/usr/bin/env python3.11
"""Smoke-test the Nubra UAT integration end-to-end (requires a live SDK session).

Usage:
    cd market-swarm-lab
    python3.11 scripts/nubra_login.py      # first-time OTP auth
    python3.11 scripts/nubra_uat_smoke.py  # verify connectivity

Steps:
    1. Load nubra_config.json
    2. Init SDK via NubraClient.from_session (reuses auth_data.db shelve — no OTP)
    3. Fetch available margin (funds)
    4. Fetch current LTP for each whitelisted symbol
    5. Fetch open positions
    6. Print summary (read-only — no orders placed)
"""
from __future__ import annotations

import json
import pathlib
import sys


_CONFIG_PATH = pathlib.Path(__file__).parents[1] / "config" / "nubra_config.json"


def main() -> None:
    try:
        from services.nubra_client.nubra_client import NubraClient
    except ImportError as exc:
        print(f"[smoke] Import error: {exc}\nRun from market-swarm-lab/ with PYTHONPATH set.",
              file=sys.stderr)
        sys.exit(1)

    config = json.loads(_CONFIG_PATH.read_text())
    whitelist: list[str] = config["whitelist"]
    print(f"[smoke] env={config['env']}  whitelist={whitelist}")

    print("[smoke] Connecting via NubraClient.from_session …")
    client = NubraClient.from_session(config, None)
    print("[smoke] ✓ SDK initialised")

    funds = client.funds()
    margin_paise = funds.get("net_margin_available", 0)
    print(f"[smoke] Funds — net_margin_available: {margin_paise} paise "
          f"(₹{margin_paise / 100:.2f})")

    for sym in whitelist:
        try:
            ltp = client.current_price(sym)
            print(f"[smoke] LTP  {sym}: ₹{ltp}")
        except Exception as exc:
            print(f"[smoke] LTP  {sym}: ERROR — {exc}")

    positions = client.positions()
    if positions:
        print("[smoke] Open positions:")
        for pos in positions:
            print(f"  {pos['symbol']:15s}  net_qty={pos['net_quantity']}")
    else:
        print("[smoke] Open positions: none")

    print("[smoke] ✓ Smoke test complete — no orders placed.")


if __name__ == "__main__":
    main()

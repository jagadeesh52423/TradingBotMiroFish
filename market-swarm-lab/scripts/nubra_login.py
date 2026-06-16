#!/usr/bin/env python3.11
"""Interactive CLI to authenticate with the Nubra UAT broker and persist the session.

Usage:
    cd market-swarm-lab
    python3.11 scripts/nubra_login.py [--env UAT]

Requires:
    - nubra_python_sdk installed (TestPyPI)
    - market-swarm-lab/.env with PHONE_NO and MPIN (never committed — gitignored)

The SDK reads PHONE_NO/MPIN from .env via python-dotenv and persists the auth session
to auth_data.db (shelve). On first login the SDK prompts for OTP interactively.
Subsequent calls reuse the shelve session without OTP.
"""
from __future__ import annotations

import argparse
import sys


def main(env: str = "UAT") -> None:
    try:
        from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
    except ImportError:
        print(
            "[nubra_login] nubra_python_sdk not found.\n"
            "Install: pip install --index-url https://test.pypi.org/simple/ "
            "--extra-index-url https://pypi.org/simple nubra-python-sdk==0.4.4",
            file=sys.stderr,
        )
        sys.exit(1)

    sdk_env = NubraEnv.UAT if env.upper() == "UAT" else NubraEnv.PROD
    print(f"[nubra_login] Initialising SDK for {sdk_env} …")
    print("[nubra_login] Reading credentials from .env (PHONE_NO / MPIN)")
    print("[nubra_login] If first login, the SDK will prompt for OTP on stdin.")

    # env_creds=True → SDK calls python-dotenv to load .env and reads PHONE_NO/MPIN.
    # If auth_data.db shelve has a valid session, OTP is skipped automatically.
    InitNubraSdk(env=sdk_env, env_creds=True)

    print(f"[nubra_login] ✓ Authenticated. Session stored in auth_data.db ({sdk_env}).")
    print("[nubra_login] Run nubra_uat_smoke.py to verify connectivity.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nubra broker login (OTP flow)")
    parser.add_argument("--env", default="UAT", choices=["UAT", "PROD"])
    args = parser.parse_args()
    main(env=args.env)

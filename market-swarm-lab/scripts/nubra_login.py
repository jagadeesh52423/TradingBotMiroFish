#!/usr/bin/env python3.11
"""Interactive CLI to authenticate with the Nubra UAT broker and persist the session.

Usage (always run from any directory — script pins cwd to market-swarm-lab/):
    python3.11 scripts/nubra_login.py [--env UAT]

Requires:
    - nubra_python_sdk installed (TestPyPI)
    - market-swarm-lab/.env with PHONE_NO and MPIN (never committed — gitignored)

The SDK reads PHONE_NO/MPIN from .env via python-dotenv and persists the auth session
to auth_data.db (shelve) inside market-swarm-lab/. On first login the SDK prompts for
OTP interactively; subsequent calls reuse the shelve session without OTP.

NOTE: Must be run in an interactive terminal — the OTP prompt requires stdin to be a tty.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

# market-swarm-lab/ — both auth_data.db (shelve) and .env live here.
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()


def _check_interactive() -> None:
    """Exit with a clear message if stdin is not a tty (OTP cannot be entered)."""
    if not sys.stdin.isatty():
        print(
            "[nubra_login] ERROR: First-time login needs an interactive terminal for the OTP.\n"
            "  Run this script directly in your terminal, not via a non-interactive shell\n"
            "  (e.g. not piped, not inside a CI job, not redirected from a file).",
            file=sys.stderr,
        )
        sys.exit(1)


def _validate_session(nubra) -> bool:
    """Return True only when a valid session_token + Authorization header are present.

    A successful auth flow always populates both; absence means auth silently failed.
    """
    session_token = nubra.token_data.get("session_token")
    auth_header = nubra.HEADERS.get("Authorization")
    return bool(session_token) and bool(auth_header)


def main(env: str = "UAT") -> None:
    _check_interactive()

    # Pin cwd to project root so the SDK writes auth_data.db and reads .env
    # from a fixed, predictable location regardless of where the script is invoked from.
    os.chdir(_PROJECT_ROOT)

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
    print(f"[nubra_login] cwd pinned to: {_PROJECT_ROOT}")
    print(f"[nubra_login] Initialising SDK for {sdk_env} …")
    print("[nubra_login] Reading credentials from .env (PHONE_NO / MPIN)")
    print("[nubra_login] If first login, the SDK will prompt for OTP on stdin.")

    # env_creds=True → SDK calls python-dotenv to load .env and reads PHONE_NO/MPIN.
    # If auth_data.db has a valid session, OTP is skipped automatically.
    try:
        nubra = InitNubraSdk(env=sdk_env, env_creds=True)
    except Exception as exc:
        print(f"[nubra_login] ✗ Authentication FAILED — SDK raised: {exc}", file=sys.stderr)
        sys.exit(1)

    if not _validate_session(nubra):
        print(
            "[nubra_login] ✗ Authentication FAILED — no valid session token was obtained.\n"
            "  Check PHONE_NO and MPIN in market-swarm-lab/.env, delete auth_data.db* if "
            "stale, and try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[nubra_login] ✓ Authenticated. Session stored in {_PROJECT_ROOT}/auth_data.db ({sdk_env}).")
    print("[nubra_login] Run nubra_uat_smoke.py to verify connectivity.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nubra broker login (OTP flow)")
    parser.add_argument("--env", default="UAT", choices=["UAT", "PROD"])
    args = parser.parse_args()
    main(env=args.env)

#!/usr/bin/env python3.11
"""Interactive CLI to authenticate with the Nubra UAT broker and persist the session.

Usage:
    python3.11 scripts/nubra_login.py [--env UAT]

Requires:
    - nubra_python_sdk installed (TestPyPI: pip install --index-url ... nubra-sdk)
    - PYTHONPATH set to include nubra_python_sdk site-packages if not globally installed

Session is written to ~/.nubra_session_{ENV}.json (mode 0600).
"""
from __future__ import annotations

import sys


def main() -> None:
    raise NotImplementedError(
        "nubra_login requires live nubra_python_sdk (from TestPyPI) and interactive TTY. "
        "Production wiring:\n"
        "  from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv\n"
        "  from services.nubra_client.nubra_session import NubraSession\n"
        "  sdk = InitNubraSdk(env=NubraEnv.UAT)\n"
        "  session_data = sdk.login(mobile, client_id, totp)\n"
        "  NubraSession('UAT').save(session_data['session_token'],\n"
        "                           session_data['auth_token'],\n"
        "                           session_data['expires_at'])"
    )


if __name__ == "__main__":
    try:
        main()
    except NotImplementedError as exc:
        print(f"[nubra_login] NOT IMPLEMENTED: {exc}", file=sys.stderr)
        sys.exit(1)

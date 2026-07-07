#!/usr/bin/env python3
"""Interactive CLI to mint a Fyers API v3 access token and cache it in .env.

Fyers access tokens expire daily (~midnight IST), so run this once each morning
before the bot needs live market data / circuit-band status.

Usage (from market-swarm-lab/):
    python3 scripts/fyers_login.py

Requires in .env (gitignored — never committed):
    FYERS_CLIENT_ID=434IZM6M3H-100
    FYERS_SECRET_ID=<app secret>
    FYERS_REDIRECT_URI=<the EXACT redirect URI configured in your Fyers app>

Flow: prints an auth URL → you log in (ID+PIN+TOTP) in a browser → Fyers redirects to
your redirect URI with ?auth_code=... in the address bar → paste that code here. The
script exchanges it (no SDK needed — plain HTTPS) and writes FYERS_ACCESS_TOKEN to .env.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sys

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()
_ENV_PATH = _PROJECT_ROOT / ".env"

_AUTH_URL = (
    "https://api-t1.fyers.in/api/v3/generate-authcode"
    "?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&state=sample"
)
_VALIDATE_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"


def _appid_hash(client_id: str, secret: str) -> str:
    """Fyers appIdHash = SHA-256 hex of 'appId:secretId'."""
    return hashlib.sha256(f"{client_id}:{secret}".encode()).hexdigest()


def _upsert_env(text: str, key: str, value: str) -> str:
    """Return .env text with KEY=value set (replacing an existing line or appending)."""
    lines = text.splitlines()
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = prefix + value
            break
    else:
        lines.append(prefix + value)
    return "\n".join(lines) + "\n"


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH)
    except ImportError:
        pass

    client_id = os.environ.get("FYERS_CLIENT_ID")
    secret = os.environ.get("FYERS_SECRET_ID")
    redirect_uri = os.environ.get("FYERS_REDIRECT_URI")
    missing = [k for k, v in {
        "FYERS_CLIENT_ID": client_id, "FYERS_SECRET_ID": secret, "FYERS_REDIRECT_URI": redirect_uri,
    }.items() if not v]
    if missing:
        print(f"[fyers_login] Missing in .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    import requests

    auth_url = _AUTH_URL.format(client_id=client_id, redirect_uri=redirect_uri)
    print("\n[fyers_login] 1. Open this URL, log in (ID + PIN + TOTP):\n")
    print("   " + auth_url + "\n")
    print("[fyers_login] 2. After login your browser redirects to your redirect URI with")
    print("   '?auth_code=...' in the address bar. Copy that auth_code value.\n")
    auth_code = input("[fyers_login] Paste auth_code here: ").strip()
    if not auth_code:
        print("[fyers_login] No auth_code entered.", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(
        _VALIDATE_URL,
        json={
            "grant_type": "authorization_code",
            "appIdHash": _appid_hash(client_id, secret),
            "code": auth_code,
        },
        timeout=30,
    )
    data = resp.json()
    token = data.get("access_token")
    if resp.status_code != 200 or not token:
        print(f"[fyers_login] ✗ Exchange failed: {data}", file=sys.stderr)
        sys.exit(1)

    text = _ENV_PATH.read_text(encoding="utf-8") if _ENV_PATH.exists() else ""
    text = _upsert_env(text, "FYERS_ACCESS_TOKEN", token)
    _ENV_PATH.write_text(text, encoding="utf-8")
    print(f"[fyers_login] ✓ Access token written to {_ENV_PATH} (FYERS_ACCESS_TOKEN).")
    print("[fyers_login] Token is valid until ~midnight IST — re-run tomorrow.")


def _selfcheck() -> None:
    # appIdHash is a stable SHA-256 of 'appid:secret' — pin against a known value.
    assert _appid_hash("APP-100", "SEC") == hashlib.sha256(b"APP-100:SEC").hexdigest()
    # upsert replaces in place and appends when absent, never duplicating.
    assert _upsert_env("A=1\nFYERS_ACCESS_TOKEN=old\nB=2\n", "FYERS_ACCESS_TOKEN", "new") == \
        "A=1\nFYERS_ACCESS_TOKEN=new\nB=2\n"
    assert _upsert_env("A=1\n", "FYERS_ACCESS_TOKEN", "new") == "A=1\nFYERS_ACCESS_TOKEN=new\n"
    assert _upsert_env("", "FYERS_ACCESS_TOKEN", "new") == "FYERS_ACCESS_TOKEN=new\n"
    print("fyers_login self-check OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()

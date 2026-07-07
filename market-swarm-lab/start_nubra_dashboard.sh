#!/usr/bin/env bash
# Start the Nubra live dashboard.
# If no Nubra session exists, run scripts/nubra_login.py first.
set -e
cd "$(dirname "$0")"
NUBRA_LIVE=1 NUBRA_LIVE_INTERVAL="${NUBRA_LIVE_INTERVAL:-900}" \
  python3.11 -m uvicorn apps.api.main:app --port 8000
# Open http://localhost:8000/nubra/dashboard in your browser.

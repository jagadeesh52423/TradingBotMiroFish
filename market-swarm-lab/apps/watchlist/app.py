"""Playbook watchlist dashboard — FastAPI over the Mongo run store.

    uvicorn apps.watchlist.app:app --port 8100
    # then open http://localhost:8100/

Serves the dashboard page + JSON endpoints for the latest run, run history, and the
elected-picks history used by the backtest script.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from services.watchlist_store.mongo_store import WatchlistStore

app = FastAPI(title="Playbook Watchlist Dashboard")
_STATIC = pathlib.Path(__file__).parent / "static"
_store: WatchlistStore | None = None


def _get_store() -> WatchlistStore:
    global _store
    if _store is None:
        _store = WatchlistStore()
    return _store


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC / "dashboard.html").read_text(encoding="utf-8")


@app.get("/api/runs")
def runs():
    return _get_store().list_runs()


@app.get("/api/run/latest")
def latest():
    d = _get_store().latest_run()
    if not d:
        raise HTTPException(404, "no runs saved yet — run: python3 scripts/weekly_watchlist.py --save")
    return d


@app.get("/api/run/{run_id}")
def run(run_id: str):
    d = _get_store().get_run(run_id)
    if not d:
        raise HTTPException(404, "run not found")
    return d


@app.get("/api/backtest")
def backtest():
    return _get_store().elected_history()

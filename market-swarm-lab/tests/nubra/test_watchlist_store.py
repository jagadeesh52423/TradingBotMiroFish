"""run_to_doc conversion + (mongo-available) store round-trip."""
from __future__ import annotations

import os
import socket
from datetime import datetime, timezone, timedelta

import pytest

from services.watchlist_store.run_to_doc import run_to_doc

_IST = timezone(timedelta(hours=5, minutes=30))
_GEN = datetime(2026, 7, 7, 9, 20, tzinfo=_IST)


def _results():
    return [
        {"symbol": "BAJFINANCE", "status": "executed", "signal": {"trade": "CALL", "expected_move_pct": 0.025},
         "watchlist": {"score": 0.42, "factors": {"catalyst": 0.3}}, "band_pct": 9.3,
         "fno": {"pcr": 0.9}, "nse_sentiment": "neutral", "catalyst_stack": {"catalyst_stack_count": 3},
         "ltp": 950.0},
        {"symbol": "SBIN", "status": "skipped", "skip_reason": "opening gap faded",
         "signal": {"trade": "CALL", "expected_move_pct": 0.01}, "watchlist": {"score": 0.2}, "ltp": 800.0},
        {"symbol": "TCS", "status": "skipped", "skip_reason": "HOLD", "signal": None,
         "watchlist": {"score": None}},
    ]


def test_run_to_doc_status_reason_and_counts():
    doc = run_to_doc(_results(), universe="catalyst", run_date="2026-07-07", generated_at=_GEN,
                     sentiment_engine="keyword")
    assert doc["counts"] == {"total": 3, "elected": 1, "dropped": 2}
    assert doc["run_id"] == "2026-07-07T09:20:00+05:30"
    by = {r["symbol"]: r for r in doc["symbols"]}
    assert by["BAJFINANCE"]["status"] == "elected" and by["BAJFINANCE"]["reason"] is None
    assert by["BAJFINANCE"]["upside_pct"] == 2.5 and by["BAJFINANCE"]["entry_ltp"] == 950.0
    assert by["SBIN"]["status"] == "dropped" and by["SBIN"]["reason"] == "opening gap faded"
    # elected sorts first
    assert doc["symbols"][0]["symbol"] == "BAJFINANCE"


def test_catalyst_map_attached():
    cmap = {"BAJFINANCE": {"type": "Financial Results", "event": "Board meeting for Q1 results"}}
    doc = run_to_doc(_results(), universe="catalyst", run_date="2026-07-07", generated_at=_GEN,
                     catalyst_map=cmap)
    by = {r["symbol"]: r for r in doc["symbols"]}
    assert by["BAJFINANCE"]["catalyst"] == "Board meeting for Q1 results"
    assert by["BAJFINANCE"]["catalyst_type"] == "Financial Results"
    assert by["SBIN"]["catalyst"] is None  # not in the map


def _mongo_up() -> bool:
    try:
        socket.create_connection(("localhost", 27017), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _mongo_up(), reason="mongo not running")
def test_store_roundtrip():
    from services.watchlist_store.mongo_store import WatchlistStore
    store = WatchlistStore(db="market_swarm_test", coll="watchlist_runs_test")
    try:
        doc = run_to_doc(_results(), universe="catalyst", run_date="2026-07-07", generated_at=_GEN)
        rid = store.save_run(doc)
        got = store.get_run(rid)
        assert got["counts"]["elected"] == 1
        assert got["run_id"] == rid and "_id" not in got  # cleaned
        # idempotent: saving again does not duplicate
        store.save_run(doc)
        assert len(store.list_runs()) == 1
        hist = store.elected_history()
        assert hist[0]["elected"][0]["symbol"] == "BAJFINANCE"
    finally:
        store._coll.drop()
        store.close()

"""§7/§8 bulk/block deals collector + catalyst-stack integration."""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import requests

from services.nse_deals import deals_collector as _deals_mod
from services.nse_deals.deals_collector import NseDealsCollector, _parse
from services.nubra_client.equity_runner import _catalyst_stack

_CSV = (
    "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
    "06-JUL-2026,BHEL,Bharat Heavy,ABC FUND,BUY,500000,245.50,-\n"
    "06-JUL-2026,BHEL,Bharat Heavy,XYZ CAP,SELL,100000,245.10,-\n"
    "06-JUL-2026,NO RECORDS,,,,,,\n"
)


def test_parse_skips_no_records_and_sums_qty():
    rows = _parse(_CSV, "bulk")
    assert len(rows) == 2 and all(r["symbol"] == "BHEL" for r in rows)
    assert rows[0]["side"] == "BUY" and rows[0]["qty"] == 500000


_EMPTY = "Date,Symbol,Client Name,Buy/Sell,Quantity Traded\n"


def _bulk_only(url):
    return _CSV if "bulk" in url else _EMPTY  # block is empty, like today


def test_flag_net_qty():
    c = NseDealsCollector()
    with patch.object(c, "_fetch", side_effect=_bulk_only):
        f = c.flag("BHEL")
    assert f["has_deal"] and f["net_qty"] == 400000  # 500k buy - 100k sell
    assert f["buy_count"] == 1 and f["sell_count"] == 1


def test_flag_no_deal():
    c = NseDealsCollector()
    with patch.object(c, "_fetch", return_value="Date,Symbol,Client Name,Buy/Sell,Quantity Traded\n"):
        assert c.flag("RELIANCE") == {"has_deal": False, "net_qty": 0, "buy_count": 0, "sell_count": 0}


def test_fetch_error_fails_safe_to_no_deal():
    # Was: on a live-fetch failure, _snapshot silently loaded the committed fixture and
    # reported `has_deal=True` — as if a real institutional deal happened today, purely
    # because a fixture symbol happened to match. That's fail-OPEN, not fail-safe: a
    # network error must never be reported as a real signal. The production _snapshot
    # path now returns no rows on a live-fetch failure (fixtures stay available for tests
    # to use explicitly via _parse_fixture, just not as an automatic fallback here).
    c = NseDealsCollector()
    with patch.object(c, "_fetch", side_effect=requests.RequestException("503")):
        f = c.flag("BHEL")  # bulk.csv fixture has BHEL, but must NOT be auto-loaded
    assert f == {"has_deal": False, "net_qty": 0, "buy_count": 0, "sell_count": 0}


def test_session_built_exactly_once_under_concurrent_fetch():
    """Two threads racing on the first fetch must not both build a fresh requests.Session
    (a check-then-set race) — the loser's session build would discard the winner's."""
    build_count = {"n": 0}

    class _FakeResp:
        def raise_for_status(self):
            pass
        text = _EMPTY

    class _FakeSession:
        def __init__(self):
            build_count["n"] += 1
            time.sleep(0.02)  # widen the race window so concurrent threads actually overlap
            self.headers = {}

        def get(self, *a, **k):
            return _FakeResp()

    c = NseDealsCollector()
    with patch.object(_deals_mod.requests, "Session", _FakeSession):
        threads = [threading.Thread(target=c._fetch, args=(_deals_mod._BULK_URL,)) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert build_count["n"] == 1


def test_snapshot_fetched_once_under_cold_cache_thundering_herd():
    """One pair of CSV fetches serves all symbols: when N threads hit a cold snapshot cache
    at once, the market-wide feeds must be fetched once (bulk+block = 2 calls total), not
    2 per thread — the rest read the warm cache."""
    c = NseDealsCollector()
    fetch_count = {"n": 0}

    def fake_fetch(url):
        fetch_count["n"] += 1
        time.sleep(0.02)  # widen the race window so concurrent threads actually overlap
        return _EMPTY

    with patch.object(c, "_fetch", side_effect=fake_fetch):
        threads = [threading.Thread(target=c._snapshot) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert fetch_count["n"] == 2  # one bulk + one block, shared across all 20 threads


def test_deal_adds_to_catalyst_stack():
    nse = {"source_audit": {"nse_announcements": {"count": 1}}}
    # 1 news source + a deal = 2 → stacked
    out = _catalyst_stack(nse, {"has_deal": True})
    assert out["catalyst_stack_count"] == 2 and out["stacked"] is True
    assert "bulk_block_deal" in out["catalyst_sources"]
    # without a deal → just the 1 news source
    assert _catalyst_stack(nse, {"has_deal": False})["catalyst_stack_count"] == 1

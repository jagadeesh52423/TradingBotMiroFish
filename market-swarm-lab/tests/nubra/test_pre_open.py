"""§3/§11 pre-open conviction: classifier + NSE record parsing."""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

from services.nubra_client.pre_open import PreOpenCollector, pre_open_conviction, _parse


def test_conviction_weak_when_thin_qty_behind_big_gap():
    assert pre_open_conviction(2.0, 1000, {"big_gap_pct": 1.0, "min_qty": 50000}) == "weak_thin_qty"


def test_conviction_strong_up_gap_heavy_book():
    assert pre_open_conviction(1.5, 200000, {"big_gap_pct": 1.0, "min_qty": 50000}) == "strong"


def test_conviction_neutral_and_none():
    assert pre_open_conviction(0.2, 200000, {"min_qty": 50000}) == "neutral"  # small gap
    assert pre_open_conviction(None, 100) is None
    assert pre_open_conviction(1.0, None) is None


def test_parse_extracts_iep_gap_qty():
    data = {"data": [{
        "metadata": {"symbol": "SBIN", "previousClose": 1037.7, "pChange": 0.16,
                     "iep": 1039.4, "finalQuantity": 0},
        "detail": {"preOpenMarket": {"IEP": 1039.4, "finalQuantity": 0,
                                     "totalBuyQuantity": 97207, "totalSellQuantity": 177142}},
    }]}
    out = _parse(data)
    assert out["SBIN"]["iep"] == 1039.4
    assert out["SBIN"]["gap_pct"] == 0.16
    assert out["SBIN"]["prev_close"] == 1037.7
    # finalQuantity 0 → falls back to buy+sell book depth
    assert out["SBIN"]["qty"] == 97207 + 177142


def test_parse_skips_symbolless_rows():
    assert _parse({"data": [{"metadata": {}}]}) == {}


def test_prime_happens_exactly_once_under_concurrent_fetch():
    """Two threads racing on the first fetch must not both build+prime a session — the
    loser's discarded session throws away the NSE cookies the winner primed, causing
    intermittent 403s. The lazy init+prime must be guarded so it runs exactly once."""
    c = PreOpenCollector()
    prime_count = {"n": 0}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    class _FakeSession:
        def get(self, *a, **k):
            return _FakeResp()

    def fake_prime():
        prime_count["n"] += 1
        time.sleep(0.02)  # widen the race window so concurrent threads actually overlap
        c._session = _FakeSession()
        c._primed = True

    with patch.object(c, "_prime", side_effect=fake_prime):
        threads = [threading.Thread(target=c._fetch) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert prime_count["n"] == 1


def test_snapshot_fetched_once_under_cold_cache_thundering_herd():
    """One NSE call serves all symbols: when N threads hit a cold snapshot cache at once,
    exactly one fetch of the market-wide payload must happen — the rest read the warm cache."""
    c = PreOpenCollector()
    fetch_count = {"n": 0}

    def fake_fetch():
        fetch_count["n"] += 1
        time.sleep(0.02)  # widen the race window so concurrent threads actually overlap
        return {"data": []}

    with patch.object(c, "_fetch", side_effect=fake_fetch):
        threads = [threading.Thread(target=c._snapshot) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert fetch_count["n"] == 1

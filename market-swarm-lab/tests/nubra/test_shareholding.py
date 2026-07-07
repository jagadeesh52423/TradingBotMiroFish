"""§2/§9 shareholding: promoter-stake trend + FII/DII flow parsing."""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import requests

from services.nse_shareholding.shareholding_collector import (
    ShareholdingCollector, _promoter_trend, _fii_dii)


def test_promoter_trend_rising():
    rows = [{"pr_and_prgrp": "50.5", "date": "31-MAR-2026"},
            {"pr_and_prgrp": "50.0", "date": "31-DEC-2025"}]
    out = _promoter_trend(rows)
    assert out["promoter_pct"] == 50.5 and out["change_pct"] == 0.5 and out["trend"] == "rising"


def test_promoter_trend_falling_flat_empty():
    assert _promoter_trend([{"pr_and_prgrp": "40"}, {"pr_and_prgrp": "42"}])["trend"] == "falling"
    assert _promoter_trend([{"pr_and_prgrp": "50"}, {"pr_and_prgrp": "50"}])["trend"] == "flat"
    assert _promoter_trend([])["trend"] is None
    assert _promoter_trend([{"pr_and_prgrp": "50"}])["change_pct"] is None  # single quarter


def test_promoter_trend_sorts_by_date_not_payload_position():
    # Payload given oldest-first (ascending) — the trend must still reflect the real
    # change (a rise), not invert because of positional (pcts[0]/pcts[1]) assumptions.
    rows = [{"pr_and_prgrp": "50.0", "date": "31-DEC-2025"},
            {"pr_and_prgrp": "50.5", "date": "31-MAR-2026"}]
    out = _promoter_trend(rows)
    assert out["promoter_pct"] == 50.5 and out["change_pct"] == 0.5 and out["trend"] == "rising"


def test_promoter_trend_unparseable_date_does_not_crash_sort():
    rows = [{"pr_and_prgrp": "50.5", "date": "not-a-date"},
            {"pr_and_prgrp": "50.0", "date": "31-DEC-2025"}]
    out = _promoter_trend(rows)
    # Real dates sort ahead of unparseable ones; doesn't crash either way.
    assert out["promoter_pct"] == 50.0


def test_fii_dii_parse():
    rows = [{"category": "DII", "netValue": "3791.42"},
            {"category": "FII/FPI", "netValue": "243.03"}]
    out = _fii_dii(rows)
    assert out["dii_net"] == 3791.42 and out["fii_net"] == 243.03
    assert out["net"] == 4034.45 and out["breadth"] == "buying"


def test_fii_dii_selling():
    out = _fii_dii([{"category": "FII", "netValue": "-500"}, {"category": "DII", "netValue": "-100"}])
    assert out["net"] == -600.0 and out["breadth"] == "selling"


def test_promoter_flag_fail_safe():
    c = ShareholdingCollector()
    with patch.object(c, "_fetch", side_effect=requests.RequestException("boom")):
        assert c.promoter_flag("RELIANCE") == {"promoter_pct": None, "change_pct": None, "trend": None}


def test_prime_happens_exactly_once_under_concurrent_fetch():
    """Two threads racing on the first fetch must not both build+prime a session — the
    loser's discarded session throws away the NSE cookies the winner primed."""
    c = ShareholdingCollector()
    prime_count = {"n": 0}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    class _FakeSession:
        def get(self, *a, **k):
            return _FakeResp()

    def fake_prime():
        prime_count["n"] += 1
        time.sleep(0.02)  # widen the race window so concurrent threads actually overlap
        c._session = _FakeSession()
        c._primed = True

    with patch.object(c, "_prime", side_effect=fake_prime):
        threads = [threading.Thread(target=c._fetch, args=("https://example.com/api",)) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert prime_count["n"] == 1


def test_promoter_flag_cached():
    c = ShareholdingCollector()
    with patch.object(c, "_fetch", return_value=[{"pr_and_prgrp": "50.5"}, {"pr_and_prgrp": "50.0"}]) as f:
        c.promoter_flag("SBIN")
        c.promoter_flag("SBIN")
    assert f.call_count == 1  # second call served from cache

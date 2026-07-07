"""§2/§9 shareholding: promoter-stake trend + FII/DII flow parsing."""
from __future__ import annotations

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


def test_promoter_flag_cached():
    c = ShareholdingCollector()
    with patch.object(c, "_fetch", return_value=[{"pr_and_prgrp": "50.5"}, {"pr_and_prgrp": "50.0"}]) as f:
        c.promoter_flag("SBIN")
        c.promoter_flag("SBIN")
    assert f.call_count == 1  # second call served from cache

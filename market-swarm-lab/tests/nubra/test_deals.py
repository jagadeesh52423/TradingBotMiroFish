"""§7/§8 bulk/block deals collector + catalyst-stack integration."""
from __future__ import annotations

from unittest.mock import patch

import requests

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


def test_fetch_error_falls_back_to_fixture():
    c = NseDealsCollector()
    with patch.object(c, "_fetch", side_effect=requests.RequestException("503")):
        f = c.flag("BHEL")  # bulk.csv fixture has BHEL
    assert f["has_deal"] is True


def test_deal_adds_to_catalyst_stack():
    nse = {"source_audit": {"nse_announcements": {"count": 1}}}
    # 1 news source + a deal = 2 → stacked
    out = _catalyst_stack(nse, {"has_deal": True})
    assert out["catalyst_stack_count"] == 2 and out["stacked"] is True
    assert "bulk_block_deal" in out["catalyst_sources"]
    # without a deal → just the 1 news source
    assert _catalyst_stack(nse, {"has_deal": False})["catalyst_stack_count"] == 1

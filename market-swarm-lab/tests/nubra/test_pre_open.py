"""§3/§11 pre-open conviction: classifier + NSE record parsing."""
from __future__ import annotations

from services.nubra_client.pre_open import pre_open_conviction, _parse


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

"""§2 watchlist 5-factor scorer."""
from __future__ import annotations

from services.nubra_client.watchlist_scorer import watchlist_score


def test_all_factors_weighted_blend():
    # equal 1.0 everywhere → score 1.0 regardless of weights
    out = watchlist_score({"catalyst": 1.0, "sector": 1.0, "band": 1.0, "liquidity": 1.0, "fno": 1.0})
    assert out["score"] == 1.0


def test_missing_factors_renormalise_not_penalise():
    # only catalyst present at 0.8 → score is 0.8 (weights renormalise over present factors)
    out = watchlist_score({"catalyst": 0.8, "sector": None, "band": None, "liquidity": None, "fno": None})
    assert out["score"] == 0.8
    assert set(out["weights_used"]) == {"catalyst"}


def test_none_score_when_no_factors():
    assert watchlist_score({"catalyst": None, "sector": None})["score"] is None


def test_weighted_two_factors():
    # catalyst 1.0 (w .30), sector 0.0 (w .25) → 0.30/0.55 ≈ 0.5455
    out = watchlist_score({"catalyst": 1.0, "sector": 0.0})
    assert out["score"] == round(0.30 / 0.55, 4)


def test_custom_weights():
    out = watchlist_score({"catalyst": 1.0, "sector": 0.0}, {"catalyst": 0.9, "sector": 0.1})
    assert out["score"] == round(0.9 / 1.0, 4)


def test_unknown_factor_ignored():
    # a factor not in weights is dropped, not blended
    out = watchlist_score({"catalyst": 1.0, "bogus": 1.0})
    assert out["score"] == 1.0
    assert "bogus" not in out["weights_used"]

"""§5 scale-out targets."""
from __future__ import annotations

from services.nubra_client.trade_targets import scale_out_targets


def test_targets_from_modeled_move():
    # ltp 100, 5% modeled move → T1 at 60% of move (3%) = 103, T2 at full 5% = 105
    out = scale_out_targets(100.0, 0.05)
    assert out == {"t1": 103.0, "t1_scale_pct": 70, "t2": 105.0, "t2_scale_pct": 30}


def test_none_when_no_move():
    assert scale_out_targets(100.0, 0.0) is None
    assert scale_out_targets(100.0, -0.02) is None
    assert scale_out_targets(0.0, 0.05) is None


def test_custom_fractions():
    out = scale_out_targets(200.0, 0.10, {"t1_move_frac": 0.5, "t1_scale_pct": 50, "t2_scale_pct": 50})
    assert out["t1"] == 210.0 and out["t1_scale_pct"] == 50
    assert out["t2"] == 220.0 and out["t2_scale_pct"] == 50

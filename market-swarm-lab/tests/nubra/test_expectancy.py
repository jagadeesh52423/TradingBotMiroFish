"""§13 expectancy tracker aggregation."""
from __future__ import annotations

from services.nubra_client.expectancy import compute_expectancy


def test_empty():
    assert compute_expectancy([]) == {"trades": 0}
    assert compute_expectancy([{"foo": 1}]) == {"trades": 0}  # no return_pct


def test_basic_metrics():
    trades = [
        {"return_pct": 4.0}, {"return_pct": 2.0}, {"return_pct": -1.0}, {"return_pct": -3.0},
    ]
    out = compute_expectancy(trades)
    assert out["trades"] == 4
    assert out["win_rate"] == 0.5
    assert out["avg_return_pct"] == 0.5
    assert out["avg_win_pct"] == 3.0
    assert out["avg_loss_pct"] == -2.0
    # 0.5*3.0 + 0.5*(-2.0) = 0.5
    assert out["expectancy_pct"] == 0.5


def test_avg_r_when_present():
    out = compute_expectancy([{"return_pct": 2.0, "pnl_r": 1.5}, {"return_pct": -1.0, "pnl_r": -1.0}])
    assert out["avg_r"] == 0.25
    # avg_r None when no pnl_r
    assert compute_expectancy([{"return_pct": 2.0}])["avg_r"] is None


def test_breakdown_by_band():
    trades = [
        {"return_pct": 5.0, "band_pct": 2.0},   # tight
        {"return_pct": -4.0, "band_pct": 2.0},  # tight
        {"return_pct": 3.0, "band_pct": 10.0},  # wide
    ]
    out = compute_expectancy(trades)
    assert out["by_band"]["tight(<=5%)"] == {"trades": 2, "win_rate": 0.5, "avg_return_pct": 0.5}
    assert out["by_band"]["wide(>5%)"]["trades"] == 1


def test_breakdown_by_exit_fill():
    trades = [
        {"return_pct": 2.0, "exit_fill_quality": "full"},
        {"return_pct": -5.0, "exit_fill_quality": "no_fill_circuit_locked"},
        {"return_pct": 1.0},  # unknown
    ]
    out = compute_expectancy(trades)
    assert out["by_exit_fill"]["no_fill_circuit_locked"]["avg_return_pct"] == -5.0
    assert out["by_exit_fill"]["unknown"]["trades"] == 1

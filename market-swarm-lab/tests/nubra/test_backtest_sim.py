"""§5/§13 held-and-exit backtest simulation."""
from __future__ import annotations

from services.nubra_client.backtest_sim import simulate_hold


def _bar(h, l, c):
    return {"high": h, "low": l, "close": c}


def test_no_forward_data():
    assert simulate_hold(100.0, [])["return_pct"] is None
    assert simulate_hold(0, [_bar(1, 1, 1)])["return_pct"] is None


def test_time_exit_at_last_held_close():
    bars = [_bar(102, 99, 101), _bar(103, 100, 102), _bar(105, 101, 104), _bar(110, 105, 108)]
    out = simulate_hold(100.0, bars, hold_days=3)  # exit at 3rd session close = 104
    assert out["exit_reason"] == "time_exit" and out["return_pct"] == 4.0
    assert out["sessions_held"] == 3


def test_target_hit_first():
    bars = [_bar(103, 99, 101), _bar(108, 102, 107)]  # T1=106 hit on session 2
    out = simulate_hold(100.0, bars, hold_days=3, targets={"t1": 106.0, "sl": 95.0})
    assert out["target_stop_return_pct"] == 6.0 and out["target_stop_reason"] == "target_t1"


def test_stop_hit_first():
    bars = [_bar(101, 94, 96)]  # SL=95 hit
    out = simulate_hold(100.0, bars, hold_days=3, targets={"t1": 110.0, "sl": 95.0})
    assert out["target_stop_return_pct"] == -5.0 and out["target_stop_reason"] == "stop"


def test_same_bar_stop_wins_conservatively():
    bars = [_bar(112, 94, 100)]  # both T1=110 and SL=95 touched same bar → stop assumed first
    out = simulate_hold(100.0, bars, hold_days=3, targets={"t1": 110.0, "sl": 95.0})
    assert out["target_stop_reason"] == "stop_conservative" and out["target_stop_return_pct"] == -5.0


def test_neither_target_nor_stop_falls_to_time_exit():
    bars = [_bar(103, 98, 101), _bar(104, 99, 102)]
    out = simulate_hold(100.0, bars, hold_days=3, targets={"t1": 120.0, "sl": 90.0})
    assert out["target_stop_reason"] == "time_exit" and out["target_stop_return_pct"] == out["time_exit_return_pct"]

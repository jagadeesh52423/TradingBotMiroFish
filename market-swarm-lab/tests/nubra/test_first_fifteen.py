"""§3/§4 first-15-minute opening-gap confirmation gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.nubra_client.entry_gate import FirstFifteenGate
from services.nubra_client.first_fifteen import FirstFifteenProvider

_IST = timezone(timedelta(hours=5, minutes=30))


def _bar(h, m, o, c, vol=1000, day=7):
    dt = datetime(2026, 7, day, h, m, tzinfo=_IST)
    return {"timestamp": int(dt.timestamp() * 1000), "open": o, "high": max(o, c),
            "low": min(o, c), "close": c, "volume": vol}


def _prior_day(vol):
    # a prior session's first-15 window (2026-07-06) with given per-bar volume
    return [_bar(9, 15, 100, 101, vol, day=6), _bar(9, 20, 101, 100, vol, day=6),
            _bar(9, 25, 100, 101, vol, day=6)]


def _clock(h, m):
    return lambda: datetime(2026, 7, 7, h, m, tzinfo=_IST)


# open at 100; window = 09:15/09:20/09:25 bars.
_HELD = [_bar(9, 15, 100, 101), _bar(9, 20, 101, 102), _bar(9, 25, 102, 103)]
_FADED = [_bar(9, 15, 100, 100), _bar(9, 20, 100, 99), _bar(9, 25, 99, 97)]


def test_gap_held():
    p = FirstFifteenProvider(lambda s: _HELD, clock=_clock(14, 0))
    assert p.gap_status("SBIN") == "held"


def test_gap_faded():
    p = FirstFifteenProvider(lambda s: _FADED, clock=_clock(14, 0))
    assert p.gap_status("SBIN") == "faded"


def test_weak_volume_when_below_prior_avg():
    # prior day had 5000/bar; today's HELD bars have 1000/bar → well below → weak_volume
    bars = _prior_day(5000) + _HELD
    p = FirstFifteenProvider(lambda s: bars, clock=_clock(14, 0), vol_factor=0.8)
    assert p.gap_status("SBIN") == "weak_volume"


def test_held_when_volume_above_normal():
    # prior day 1000/bar; today 1000/bar → today >= 0.8*avg → held (price also holds)
    bars = _prior_day(1000) + _HELD
    p = FirstFifteenProvider(lambda s: bars, clock=_clock(14, 0), vol_factor=0.8)
    assert p.gap_status("SBIN") == "held"


def test_weak_volume_gate_blocks():
    bars = _prior_day(5000) + _HELD
    gate = FirstFifteenGate(FirstFifteenProvider(lambda s: bars, clock=_clock(14, 0)))
    ok, reason = gate.evaluate({"trade": "CALL", "ticker": "SBIN"})
    assert ok is False and "volume" in reason


def test_none_before_window_complete():
    p = FirstFifteenProvider(lambda s: _HELD, clock=_clock(9, 20))  # before 09:30
    assert p.gap_status("SBIN") is None


def test_none_when_no_today_bars():
    old = [{"timestamp": int(datetime(2026, 7, 4, 9, 15, tzinfo=_IST).timestamp() * 1000),
            "open": 100, "close": 101}]
    p = FirstFifteenProvider(lambda s: old, clock=_clock(14, 0))
    assert p.gap_status("SBIN") is None


def test_none_on_fetch_error():
    def boom(s):
        raise RuntimeError("no data")
    p = FirstFifteenProvider(boom, clock=_clock(14, 0))
    assert p.gap_status("SBIN") is None


def test_gate_blocks_faded_call():
    gate = FirstFifteenGate(FirstFifteenProvider(lambda s: _FADED, clock=_clock(14, 0)))
    ok, reason = gate.evaluate({"trade": "CALL", "ticker": "SBIN"})
    assert ok is False and "faded" in reason


def test_gate_allows_held_call():
    gate = FirstFifteenGate(FirstFifteenProvider(lambda s: _HELD, clock=_clock(14, 0)))
    assert gate.evaluate({"trade": "CALL", "ticker": "SBIN"}) == (True, None)


def test_gate_allows_when_unconfirmed():  # fail-open before window
    gate = FirstFifteenGate(FirstFifteenProvider(lambda s: _HELD, clock=_clock(9, 20)))
    assert gate.evaluate({"trade": "CALL", "ticker": "SBIN"}) == (True, None)


def test_gate_ignores_put():
    gate = FirstFifteenGate(FirstFifteenProvider(lambda s: _FADED, clock=_clock(14, 0)))
    assert gate.evaluate({"trade": "PUT", "ticker": "SBIN"}) == (True, None)

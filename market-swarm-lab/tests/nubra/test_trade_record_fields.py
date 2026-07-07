"""§13 India trade-record fields: entry band width + exit-fill quality."""
from __future__ import annotations

from services.nubra_client.equity_runner import _exit_fill_quality


def test_full_fill_when_placed_full_qty():
    assert _exit_fill_quality({"status": "placed", "qty": 100}, None) == "full"


def test_partial_fill():
    assert _exit_fill_quality({"status": "placed", "qty": 100, "filled_qty": 40}, None) == "partial"


def test_no_fill_when_zero_filled():
    assert _exit_fill_quality({"status": "placed", "qty": 100, "filled_qty": 0}, None) == "no_fill"


def test_no_fill_circuit_locked():
    # rejected exit + stock sitting at its lower circuit → the India failure mode
    res = {"status": "insufficient_funds", "qty": 100}
    locked = {"last": 160.0, "lower": 160.0, "upper": 200.0}
    assert _exit_fill_quality(res, locked) == "no_fill_circuit_locked"


def test_no_fill_not_locked():
    res = {"status": "rejected_by_risk", "qty": 100}
    not_locked = {"last": 180.0, "lower": 160.0, "upper": 200.0}
    assert _exit_fill_quality(res, not_locked) == "no_fill"

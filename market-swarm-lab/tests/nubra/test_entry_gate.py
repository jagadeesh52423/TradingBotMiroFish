"""Tests for entry_gate.py — TDD: these are written before the implementation."""
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.nubra_client.entry_gate import ExpectedUpsideGate
from services.nubra_client.broker_types import BrokerOrderResult, OrderStatus
from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.order_state_tracker import OrderStateTracker

IST = ZoneInfo("Asia/Kolkata")
OPEN_NOW = datetime(2026, 6, 16, 11, 0, tzinfo=IST)

# ---------------------------------------------------------------------------
# Helpers shared with test_equity_order_handler.py
# ---------------------------------------------------------------------------

class _Pos:
    def __init__(self, longs=None):
        self._l = longs or {}

    def net_quantity(self, symbol):
        return self._l.get(symbol, 0)

    def has_long(self, symbol):
        return self._l.get(symbol, 0) > 0


class _Broker:
    def __init__(self):
        self.placed = []

    def place_order(self, order):
        self.placed.append(order)
        return BrokerOrderResult(
            broker_order_id="O1", client_tag=order.client_tag,
            status=OrderStatus.SENT, submitted_at="t", raw={})


def _make_gate(min_pct=2.0, per_symbol=None, max_horizon_days=None):
    return ExpectedUpsideGate({
        "min_expected_upside_pct": min_pct,
        "per_symbol": per_symbol or {},
        "max_horizon_days": max_horizon_days,
    })


def _handler(tmp_path, broker, gates=None, longs=None, funds_ok=True, clock=OPEN_NOW):
    xlate = SignalToEquityOrder(
        whitelist={"SBIN"}, ltp_provider=lambda s: Decimal("100"),
        position_provider=_Pos(longs), account_value=Decimal("1000000"),
        risk_per_trade_pct=Decimal("0.5"), price_type="LIMIT")
    return EquityOrderHandler(
        translator=xlate, broker=broker,
        tracker=OrderStateTracker(env="UAT", base_dir=str(tmp_path)),
        funds_check=lambda o: funds_ok,
        clock=lambda: clock,
        entry_gates=gates)


# ---------------------------------------------------------------------------
# Unit tests — ExpectedUpsideGate.evaluate() in isolation
# ---------------------------------------------------------------------------

class TestExpectedUpsideGateEvaluate:
    def test_allows_when_upside_meets_threshold(self):
        gate = _make_gate(min_pct=2.0)
        # expected_move_pct is a FRACTION (0.02 == 2%). Meets the 2.0% threshold.
        allowed, reason = gate.evaluate({"expected_move_pct": 0.02, "horizon": "1d", "ticker": "SBIN"})
        assert allowed is True
        assert reason is None

    def test_allows_when_upside_exceeds_threshold(self):
        gate = _make_gate(min_pct=2.0)
        # 3% move (fraction 0.03) > 2.0% threshold
        allowed, reason = gate.evaluate({"expected_move_pct": 0.03, "horizon": "1d", "ticker": "SBIN"})
        assert allowed is True
        assert reason is None

    def test_blocks_when_upside_below_threshold(self):
        gate = _make_gate(min_pct=2.0)
        # 1% move (fraction 0.01) < 2.0% threshold
        allowed, reason = gate.evaluate({"expected_move_pct": 0.01, "horizon": "1d", "ticker": "SBIN"})
        assert allowed is False
        assert reason is not None
        assert "1.00%" in reason
        assert "2.00%" in reason

    def test_block_reason_includes_horizon(self):
        gate = _make_gate(min_pct=2.0)
        allowed, reason = gate.evaluate({"expected_move_pct": 0.005, "horizon": "3d", "ticker": "SBIN"})
        assert allowed is False
        assert "3d" in reason

    def test_per_symbol_override_raises_threshold(self):
        # SBIN requires 3.5% instead of the global 2.0%
        gate = _make_gate(min_pct=2.0, per_symbol={"SBIN": 3.5})
        # 2.5% move passes global but fails SBIN override
        allowed, reason = gate.evaluate({"expected_move_pct": 0.025, "horizon": "1d", "ticker": "SBIN"})
        assert allowed is False
        assert "3.50%" in reason

    def test_per_symbol_override_lowers_threshold(self):
        # RELIANCE only needs 1.0% (e.g., liquid stock)
        gate = _make_gate(min_pct=2.0, per_symbol={"RELIANCE": 1.0})
        # 1.5% move (0.015) — fails global 2.0% but passes RELIANCE 1.0%
        allowed, reason = gate.evaluate({"expected_move_pct": 0.015, "horizon": "1d", "ticker": "RELIANCE"})
        assert allowed is True
        assert reason is None

    def test_per_symbol_key_lookup_is_case_insensitive(self):
        # Config may have uppercase key; signal ticker may be any case.
        gate = _make_gate(min_pct=2.0, per_symbol={"SBIN": 1.0})
        allowed, _ = gate.evaluate({"expected_move_pct": 0.015, "horizon": "1d", "ticker": "sbin"})
        assert allowed is True

    def test_max_horizon_days_blocks_long_horizon(self):
        gate = _make_gate(min_pct=2.0, max_horizon_days=2.0)
        # "5d" = 5 days > 2.0 max_horizon_days
        allowed, reason = gate.evaluate({"expected_move_pct": 0.05, "horizon": "5d", "ticker": "SBIN"})
        assert allowed is False
        assert reason is not None
        assert "5d" in reason

    def test_max_horizon_days_allows_within_cap(self):
        gate = _make_gate(min_pct=2.0, max_horizon_days=5.0)
        # "3d" = 3 days <= 5.0 max; 5% upside passes
        allowed, reason = gate.evaluate({"expected_move_pct": 0.05, "horizon": "3d", "ticker": "SBIN"})
        assert allowed is True
        assert reason is None

    def test_max_horizon_days_none_means_no_cap(self):
        gate = _make_gate(min_pct=2.0, max_horizon_days=None)
        # "5d" with no cap — only upside gate applies
        allowed, reason = gate.evaluate({"expected_move_pct": 0.05, "horizon": "5d", "ticker": "SBIN"})
        assert allowed is True
        assert reason is None

    def test_horizon_hours_parsed_to_fraction_of_day(self):
        gate = _make_gate(min_pct=2.0, max_horizon_days=0.5)
        # "1h" = 1/24 days ≈ 0.042 <= 0.5 max; upside fine
        allowed, reason = gate.evaluate({"expected_move_pct": 0.05, "horizon": "1h", "ticker": "SBIN"})
        assert allowed is True
        assert reason is None

    def test_horizon_hours_blocked_by_day_cap(self):
        gate = _make_gate(min_pct=2.0, max_horizon_days=0.01)
        # "1h" = 0.042 days > 0.01 max
        allowed, reason = gate.evaluate({"expected_move_pct": 0.05, "horizon": "1h", "ticker": "SBIN"})
        assert allowed is False
        assert "1h" in reason

    def test_unit_normalization_fraction_vs_percent(self):
        # Confirm the gate treats expected_move_pct as a FRACTION, not a percent.
        # 0.025 fraction = 2.5% move. Should pass a 2.0% threshold.
        gate = _make_gate(min_pct=2.0)
        allowed, reason = gate.evaluate({"expected_move_pct": 0.025, "horizon": "1d", "ticker": "SBIN"})
        assert allowed is True, (
            "0.025 is a fraction (2.5%) and must pass a 2.0% threshold — "
            "gate must multiply by 100 before comparing"
        )

    def test_unit_normalization_blocks_when_fraction_is_tiny(self):
        # 0.005 fraction = 0.5% move. Must fail a 2.0% threshold.
        gate = _make_gate(min_pct=2.0)
        allowed, reason = gate.evaluate({"expected_move_pct": 0.005, "horizon": "1d", "ticker": "SBIN"})
        assert allowed is False, "0.005 fraction = 0.5%, below 2.0% threshold"

    def test_unknown_horizon_suffix_raises(self):
        # F3: unparseable horizon must raise, not silently default to 1 day.
        gate = _make_gate(min_pct=2.0)
        with pytest.raises(ValueError, match="Unrecognised horizon format"):
            gate.evaluate({"expected_move_pct": 0.05, "horizon": "1w", "ticker": "SBIN"})

    def test_non_numeric_horizon_raises(self):
        gate = _make_gate(min_pct=2.0)
        with pytest.raises(ValueError, match="Unrecognised horizon format"):
            gate.evaluate({"expected_move_pct": 0.05, "horizon": "abcd", "ticker": "SBIN"})


# ---------------------------------------------------------------------------
# Integration tests — EquityOrderHandler with entry gates
# ---------------------------------------------------------------------------

class TestEquityOrderHandlerEntryGate:
    def test_buy_below_threshold_returns_below_threshold_status(self, tmp_path):
        broker = _Broker()
        gate = _make_gate(min_pct=2.0)
        handler = _handler(tmp_path, broker, gates=[gate])
        # 0.5% upside (fraction 0.005) — below 2.0% threshold
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s1",
                  "expected_move_pct": 0.005, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "below_threshold"
        assert "reason" in result
        assert len(broker.placed) == 0

    def test_buy_at_threshold_proceeds_to_place(self, tmp_path):
        broker = _Broker()
        gate = _make_gate(min_pct=2.0)
        handler = _handler(tmp_path, broker, gates=[gate])
        # Exactly 2.0% upside (fraction 0.02) — meets threshold
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s2",
                  "expected_move_pct": 0.02, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "placed"
        assert len(broker.placed) == 1

    def test_buy_above_threshold_proceeds_to_place(self, tmp_path):
        broker = _Broker()
        gate = _make_gate(min_pct=2.0)
        handler = _handler(tmp_path, broker, gates=[gate])
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s3",
                  "expected_move_pct": 0.04, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "placed"

    def test_put_bypasses_gate(self, tmp_path):
        broker = _Broker()
        gate = _make_gate(min_pct=99.0)  # absurdly high threshold
        handler = _handler(tmp_path, broker, gates=[gate], longs={"SBIN": 10})
        # PUT (sell-to-close) must NEVER be blocked by the upside gate
        signal = {"ticker": "SBIN", "trade": "PUT", "signal_id": "s4",
                  "expected_move_pct": 0.001, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        # PUT on a position → should attempt sell_to_close
        assert result["status"] != "below_threshold", "PUT must bypass entry gate"

    def test_hold_bypasses_gate(self, tmp_path):
        broker = _Broker()
        gate = _make_gate(min_pct=99.0)  # absurdly high threshold
        handler = _handler(tmp_path, broker, gates=[gate])
        signal = {"ticker": "SBIN", "trade": "HOLD", "signal_id": "s5",
                  "expected_move_pct": 0.001, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        # HOLD skips translator → "skipped", not "below_threshold"
        assert result["status"] != "below_threshold", "HOLD must bypass entry gate"

    def test_no_gates_provided_uses_default_from_config(self, tmp_path):
        """Handler with entry_gates=None builds a default gate from nubra_config.json."""
        broker = _Broker()
        handler = _handler(tmp_path, broker, gates=None)
        # Config has min_expected_upside_pct: 2.0; signal is 0.5% → blocked
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s6",
                  "expected_move_pct": 0.005, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "below_threshold"

    def test_multiple_gates_first_blocker_wins(self, tmp_path):
        broker = _Broker()
        gate_low = _make_gate(min_pct=1.0)   # passes for 0.02 (2%)
        gate_high = _make_gate(min_pct=5.0)  # blocks 0.02 (2%) < 5%
        handler = _handler(tmp_path, broker, gates=[gate_low, gate_high])
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s7",
                  "expected_move_pct": 0.02, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "below_threshold"
        assert len(broker.placed) == 0

    def test_existing_risk_rejection_still_works(self, tmp_path):
        """Gate must not affect the existing risk-rejection path (non-regression)."""
        broker = _Broker()
        gate = _make_gate(min_pct=0.0)  # gate always allows
        handler = _handler(tmp_path, broker, gates=[gate])
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s8",
                  "expected_move_pct": 0.05, "horizon": "1d"}
        result = handler.handle(signal, {"approved": False}, "SBIN")
        assert result["status"] == "rejected_by_risk"

    def test_existing_market_closed_still_works(self, tmp_path):
        """Gate must not affect the market-closed path (non-regression)."""
        from datetime import datetime
        broker = _Broker()
        gate = _make_gate(min_pct=0.0)
        closed = datetime(2026, 6, 16, 18, 0, tzinfo=IST)
        handler = _handler(tmp_path, broker, gates=[gate], clock=closed)
        signal = {"ticker": "SBIN", "trade": "CALL", "signal_id": "s9",
                  "expected_move_pct": 0.05, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "market_closed"

    def test_handler_uses_authoritative_ticker_not_signal_ticker(self, tmp_path):
        # F4: RELIANCE needs 1%; SBIN needs 5%. signal["ticker"] = RELIANCE but
        # authoritative ticker arg = SBIN. Handler must pass SBIN to gate.
        # Without F4: gate reads "RELIANCE" → 1% threshold → 2% upside passes.
        # With F4:    gate reads "SBIN"     → 5% threshold → 2% upside blocked.
        broker = _Broker()
        gate = _make_gate(min_pct=2.0, per_symbol={"SBIN": 5.0, "RELIANCE": 1.0})
        xlate = SignalToEquityOrder(
            whitelist={"SBIN", "RELIANCE"}, ltp_provider=lambda s: Decimal("100"),
            position_provider=_Pos(), account_value=Decimal("1000000"),
            risk_per_trade_pct=Decimal("0.5"), price_type="LIMIT")
        handler = EquityOrderHandler(
            translator=xlate, broker=broker,
            tracker=OrderStateTracker(env="UAT", base_dir=str(tmp_path)),
            funds_check=lambda o: True,
            clock=lambda: OPEN_NOW,
            entry_gates=[gate])
        signal = {"ticker": "RELIANCE", "trade": "CALL", "signal_id": "s10",
                  "expected_move_pct": 0.02, "horizon": "1d"}
        result = handler.handle(signal, {"approved": True}, "SBIN")
        assert result["status"] == "below_threshold", \
            "handler must pass authoritative ticker arg to gate, not signal['ticker']"

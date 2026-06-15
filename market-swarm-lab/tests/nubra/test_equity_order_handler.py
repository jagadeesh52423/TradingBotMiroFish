from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from services.nubra_client.broker_types import BrokerOrderResult, OrderStatus
from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.order_state_tracker import OrderStateTracker

IST = ZoneInfo("Asia/Kolkata")
OPEN_NOW = datetime(2026, 6, 16, 11, 0, tzinfo=IST)


class _Pos:
    def __init__(self, longs=None):
        self._l = longs or {}

    def net_quantity(self, s):
        return self._l.get(s, 0)

    def has_long(self, s):
        return self._l.get(s, 0) > 0


class _Broker:
    def __init__(self):
        self.placed = []

    def place_order(self, order):
        self.placed.append(order)
        return BrokerOrderResult(broker_order_id="O1", client_tag=order.client_tag,
                                 status=OrderStatus.SENT, submitted_at="t", raw={})


def _handler(tmp_path, broker, longs=None, funds_ok=True, clock=OPEN_NOW):
    xlate = SignalToEquityOrder(
        whitelist={"SBIN"}, ltp_provider=lambda s: Decimal("100"),
        position_provider=_Pos(longs), account_value=Decimal("1000000"),
        risk_per_trade_pct=Decimal("0.5"), price_type="LIMIT")
    return EquityOrderHandler(
        translator=xlate, broker=broker,
        tracker=OrderStateTracker(env="UAT", base_dir=str(tmp_path)),
        funds_check=lambda o: funds_ok, clock=lambda: clock)


def _sig(trade="CALL", sid="s1"):
    return {"ticker": "SBIN", "trade": trade, "signal_id": sid, "asset_class": "equity"}


def test_places_order_when_all_gates_pass(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b).handle(_sig(), {"approved": True}, "SBIN")
    assert out["status"] == "placed" and len(b.placed) == 1


def test_blocks_when_risk_not_approved(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b).handle(_sig(), {"approved": False}, "SBIN")
    assert out["status"] == "rejected_by_risk" and not b.placed


def test_blocks_when_market_closed(tmp_path):
    b = _Broker()
    closed = datetime(2026, 6, 16, 18, 0, tzinfo=IST)
    out = _handler(tmp_path, b, clock=closed).handle(_sig(), {"approved": True}, "SBIN")
    assert out["status"] == "market_closed" and not b.placed


def test_duplicate_tag_skipped(tmp_path):
    b = _Broker()
    h = _handler(tmp_path, b)
    h.handle(_sig(sid="dup"), {"approved": True}, "SBIN")
    out = h.handle(_sig(sid="dup"), {"approved": True}, "SBIN")
    assert out["status"] == "duplicate_skipped" and len(b.placed) == 1


def test_funds_precheck_blocks(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b, funds_ok=False).handle(_sig(), {"approved": True}, "SBIN")
    assert out["status"] == "insufficient_funds" and not b.placed


def test_translator_skip_is_reported(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b).handle(_sig(trade="HOLD"), {"approved": True}, "SBIN")
    assert out["status"] == "skipped" and not b.placed

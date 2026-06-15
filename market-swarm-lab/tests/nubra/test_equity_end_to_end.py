from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from services.nubra_client.equity_paper_trader import EquityPaperTrader
from services.nubra_client.position_provider import BrokerPositionProvider
from services.nubra_client.position_sync import PositionSync
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.order_state_tracker import OrderStateTracker
from services.nubra_client.order_handler import OrderHandlerRegistry

IST = ZoneInfo("Asia/Kolkata")
OPEN_NOW = datetime(2026, 6, 16, 11, 0, tzinfo=IST)


def _build(tmp_path):
    broker = EquityPaperTrader(ltp_provider=lambda s: Decimal("100"))
    xlate = SignalToEquityOrder(
        whitelist={"SBIN"}, ltp_provider=lambda s: Decimal("100"),
        position_provider=BrokerPositionProvider(broker),
        account_value=Decimal("1000000"), risk_per_trade_pct=Decimal("0.5"),
        price_type="LIMIT")
    handler = EquityOrderHandler(
        translator=xlate, broker=broker,
        tracker=OrderStateTracker(env="UAT", base_dir=str(tmp_path)),
        funds_check=lambda o: True, clock=lambda: OPEN_NOW)
    reg = OrderHandlerRegistry()
    reg.register(handler)
    return broker, reg


def test_call_places_then_duplicate_skipped(tmp_path):
    broker, reg = _build(tmp_path)
    sig = {"asset_class": "equity", "trade": "CALL", "ticker": "SBIN", "signal_id": "s1"}
    out1 = reg.dispatch("equity", sig, {"approved": True}, "SBIN")
    out2 = reg.dispatch("equity", sig, {"approved": True}, "SBIN")
    assert out1["status"] == "placed"
    assert out2["status"] == "duplicate_skipped"
    assert {p["symbol"] for p in broker.get_positions()} == {"SBIN"}


def test_put_sells_to_close_existing_long(tmp_path):
    broker, reg = _build(tmp_path)
    reg.dispatch("equity", {"asset_class": "equity", "trade": "CALL", "ticker": "SBIN",
                             "signal_id": "buy1"}, {"approved": True}, "SBIN")
    held = {p["symbol"]: p["net_quantity"] for p in broker.get_positions()}["SBIN"]
    out = reg.dispatch("equity", {"asset_class": "equity", "trade": "PUT", "ticker": "SBIN",
                                  "signal_id": "sell1"}, {"approved": True}, "SBIN")
    assert out["status"] == "placed" and out["side"] == "SELL" and out["qty"] == held
    assert broker.get_positions() == []  # flat after sell-to-close

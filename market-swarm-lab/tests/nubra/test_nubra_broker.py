import pytest
from decimal import Decimal
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity, OrderStatus)
from services.nubra_client.nubra_broker import NubraBroker


class _FakeNubraClient:
    def __init__(self):
        self.placed = None
        self.cancelled = None

    def place_order(self, *, symbol, side, qty, price_type, price, client_tag):
        self.placed = dict(symbol=symbol, side=side, qty=qty,
                           price_type=price_type, price=price, client_tag=client_tag)
        return {"order_id": "OID9", "payload": {"ref_id": 101, "order_price": 81250}}

    def cancel_order(self, order_id):
        self.cancelled = order_id
        return {"cancelled": [order_id]}

    def positions(self):
        return [{"symbol": "SBIN", "net_quantity": 5}]

    def get_order(self, order_id):
        return type("O", (), {"order_status": "ORDER_STATUS_FILLED", "tag": "msl-1"})()


def _order():
    return BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=10,
                       price_type=PriceType.LIMIT, price=Decimal("812.50"),
                       product=Product.CNC, validity=Validity.DAY, client_tag="msl-1")


def test_place_maps_enums_to_strings_and_returns_result(capsys):
    fake_client = _FakeNubraClient()
    broker = NubraBroker(fake_client, dry_run_log=True)
    res = broker.place_order(_order())
    assert fake_client.placed["side"] == "BUY"
    assert fake_client.placed["price_type"] == "LIMIT"
    assert res.broker_order_id == "OID9"
    assert res.status is OrderStatus.SENT
    assert "ref_id" in capsys.readouterr().out  # dry-run payload logged


def test_modify_not_implemented():
    broker = NubraBroker(_FakeNubraClient())
    with pytest.raises(NotImplementedError):
        broker.modify_order("OID9", price=Decimal("1"))


def test_cancel_delegates():
    fake_client = _FakeNubraClient()
    assert NubraBroker(fake_client).cancel_order("OID9") is True
    assert fake_client.cancelled == "OID9"


def test_get_positions_delegates():
    broker = NubraBroker(_FakeNubraClient())
    positions = broker.get_positions()
    assert positions == [{"symbol": "SBIN", "net_quantity": 5}]


def test_get_order_status_maps():
    broker = NubraBroker(_FakeNubraClient())
    result = broker.get_order_status("OID9")
    assert result is not None
    assert result.status is OrderStatus.FILLED
    assert result.client_tag == "msl-1"

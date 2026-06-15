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

from decimal import Decimal
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity)
from services.nubra_client.position_sync import PositionSync


class _Broker:
    def __init__(self, margin_paise):
        self._m = margin_paise

    def get_funds(self):
        return {"net_margin_available": self._m}

    def get_positions(self):
        return [{"symbol": "SBIN", "net_quantity": 5}]


def _buy(qty=10, price="800"):
    return BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=qty,
                       price_type=PriceType.LIMIT, price=Decimal(price),
                       product=Product.CNC, validity=Validity.DAY, client_tag="t")


def test_funds_sufficient_true_when_margin_covers_cost():
    ps = PositionSync(_Broker(margin_paise=10_000_00))  # ₹10,000
    assert ps.funds_sufficient(_buy(qty=10, price="800")) is True   # cost ₹8,000


def test_funds_insufficient_when_cost_exceeds_margin():
    ps = PositionSync(_Broker(margin_paise=5_000_00))   # ₹5,000
    assert ps.funds_sufficient(_buy(qty=10, price="800")) is False  # cost ₹8,000


def test_sell_skips_funds_check():
    ps = PositionSync(_Broker(margin_paise=0))
    sell = BrokerOrder(symbol="SBIN", side=OrderSide.SELL, qty=5,
                       price_type=PriceType.MARKET, price=None, product=Product.CNC,
                       validity=Validity.DAY, client_tag="t")
    assert ps.funds_sufficient(sell) is True

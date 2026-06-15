from decimal import Decimal
from services.nubra_client.broker_types import (
    OrderSide, Product, PriceType, Validity, OrderStatus,
    BrokerOrder, BrokerOrderResult,
)


def test_broker_order_minimal():
    order = BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=10,
                        price_type=PriceType.LIMIT, price=Decimal("812.50"),
                        product=Product.CNC, validity=Validity.DAY, client_tag="msl-x")
    assert order.qty == 10
    assert order.side is OrderSide.BUY


def test_market_order_allows_none_price():
    order = BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=1,
                        price_type=PriceType.MARKET, price=None,
                        product=Product.CNC, validity=Validity.DAY, client_tag="msl-y")
    assert order.price is None


def test_limit_requires_price():
    import pytest
    with pytest.raises(ValueError):
        BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=1,
                    price_type=PriceType.LIMIT, price=None,
                    product=Product.CNC, validity=Validity.DAY, client_tag="msl-z")


def test_result_terminal_helper():
    result = BrokerOrderResult(broker_order_id="1", client_tag="msl-x",
                               status=OrderStatus.FILLED, submitted_at="t", raw={})
    assert result.is_terminal() is True
    result2 = BrokerOrderResult(broker_order_id="1", client_tag="msl-x",
                                status=OrderStatus.OPEN, submitted_at="t", raw={})
    assert result2.is_terminal() is False

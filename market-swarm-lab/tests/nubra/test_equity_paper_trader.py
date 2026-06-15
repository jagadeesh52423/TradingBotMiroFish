from decimal import Decimal
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity, OrderStatus)
from services.nubra_client.equity_paper_trader import EquityPaperTrader


def _order(symbol="SBIN", side=OrderSide.BUY, qty=10, price="800.00",
           pt=PriceType.LIMIT, tag="msl-1"):
    return BrokerOrder(symbol=symbol, side=side, qty=qty, price_type=pt,
                       price=Decimal(price) if price else None,
                       product=Product.CNC, validity=Validity.DAY, client_tag=tag)


def test_limit_buy_fills_and_creates_position():
    trader = EquityPaperTrader(ltp_provider=lambda symbol: Decimal("810.00"))
    res = trader.place_order(_order())
    assert res.status is OrderStatus.FILLED
    pos = {position["symbol"]: position for position in trader.get_positions()}
    assert pos["SBIN"]["net_quantity"] == 10


def test_market_buy_fills_at_ltp():
    trader = EquityPaperTrader(ltp_provider=lambda symbol: Decimal("805.55"))
    res = trader.place_order(_order(price=None, pt=PriceType.MARKET, tag="msl-2"))
    assert res.status is OrderStatus.FILLED
    assert trader.get_order_status(res.broker_order_id).status is OrderStatus.FILLED


def test_sell_reduces_position():
    trader = EquityPaperTrader(ltp_provider=lambda symbol: Decimal("810.00"))
    trader.place_order(_order(qty=10, tag="msl-3"))
    trader.place_order(_order(side=OrderSide.SELL, qty=4, tag="msl-4"))
    pos = {position["symbol"]: position for position in trader.get_positions()}
    assert pos["SBIN"]["net_quantity"] == 6


def test_cancel_unknown_returns_false():
    trader = EquityPaperTrader(ltp_provider=lambda symbol: Decimal("1"))
    assert trader.cancel_order("nope") is False

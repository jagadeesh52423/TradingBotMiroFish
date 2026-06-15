from decimal import Decimal
from services.nubra_client.broker_types import BrokerOrder, BrokerOrderResult, OrderSide, OrderStatus, PriceType, Product, Validity
from services.nubra_client.nubra_broker import NubraBroker


class _FakeNubraClient:
    def __init__(self):
        self.placed = []
        self.cancelled = []

    def current_price(self, symbol: str) -> Decimal:
        return Decimal("812.50")

    def place_order(self, symbol, side, qty, price_type, price, client_tag) -> dict:
        self.placed.append({
            "symbol": symbol, "side": side, "qty": qty,
            "price_type": price_type, "price": price, "tag": client_tag,
        })
        return {"order_id": f"NUBRA-{len(self.placed)}"}


def _broker():
    return NubraBroker(nubra_client=_FakeNubraClient())


def test_place_order_returns_result_with_order_id():
    broker = _broker()
    order = BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=5,
                        price_type=PriceType.LIMIT, price=Decimal("812.50"),
                        product=Product.CNC, validity=Validity.DAY,
                        client_tag="msl-t1")
    result = broker.place_order(order)
    assert isinstance(result, BrokerOrderResult)
    assert result.broker_order_id == "NUBRA-1"
    assert result.status == OrderStatus.PENDING


def test_get_funds_delegates_to_ltp():
    broker = _broker()
    funds = broker.get_funds()
    assert "live" in funds


def test_get_positions_returns_list():
    broker = _broker()
    positions = broker.get_positions()
    assert isinstance(positions, list)


def test_cancel_order_raises_not_implemented():
    broker = _broker()
    try:
        broker.cancel_order("X")
        assert False, "Should have raised"
    except NotImplementedError:
        pass

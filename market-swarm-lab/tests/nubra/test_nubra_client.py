from decimal import Decimal
from services.nubra_client.nubra_client import NubraClient


class _FakeTrader:
    def __init__(self): self.last = None

    def create_order(self, payload):
        self.last = payload
        return type("R", (), {"order_id": "OID1"})()

    def cancel_orders_v2(self, order_ids=None, basket_ids=None):
        return {"cancelled": order_ids}


class _FakeMarket:
    def current_price(self, instrument, exchange="NSE"):
        return type("P", (), {"price": 81250, "prev_close": 81000})()  # paise


class _FakeInst:
    def get_instrument_by_symbol(self, symbol, exchange="NSE"):
        return type("I", (), {"ref_id": 101, "tick_size": "0.05", "lot_size": 1})()


def _client():
    return NubraClient(config={"exchange": "NSE", "product": "CNC", "validity": "DAY"},
                       sdk_trader=_FakeTrader(), sdk_market=_FakeMarket(),
                       sdk_instruments=_FakeInst())


def test_current_price_returns_rupees():
    client = _client()
    assert client.current_price("SBIN") == Decimal("812.50")


def test_place_limit_buy_builds_paise_payload():
    client = _client()
    res = client.place_order(symbol="SBIN", side="BUY", qty=10,
                             price_type="LIMIT", price=Decimal("812.50"), client_tag="msl-1")
    assert res["order_id"] == "OID1"
    payload = client._sdk_trader.last
    assert payload["order_price"] == 81250          # paise
    assert payload["order_qty"] == 10
    assert payload["order_side"] == "ORDER_SIDE_BUY"
    assert payload["order_delivery_type"] == "ORDER_DELIVERY_TYPE_CNC"
    assert payload["price_type"] == "LIMIT"
    assert payload["ref_id"] == 101
    assert payload["tag"] == "msl-1"


def test_place_rounds_to_tick_before_paise():
    client = _client()
    client.place_order(symbol="SBIN", side="BUY", qty=1, price_type="LIMIT",
                       price=Decimal("812.53"), client_tag="msl-2")  # -> 812.55
    assert client._sdk_trader.last["order_price"] == 81255

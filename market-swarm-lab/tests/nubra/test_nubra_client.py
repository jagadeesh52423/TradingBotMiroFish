import types
from decimal import Decimal

import pytest

from services.nubra_client.nubra_client import NubraClient


class _FakeTrader:
    def __init__(self):
        self.last = None

    def create_order(self, payload):
        self.last = payload
        return type("R", (), {"order_id": "OID1"})()

    def cancel_orders_v2(self, order_ids=None, basket_ids=None):
        return {"cancelled": order_ids}


def _make_historical_response(symbol: str, prices_paise: list[int]):
    """Build a fake SDK MarketChartsResponse for historical_data()."""
    pts = [
        types.SimpleNamespace(value=p, timestamp=(i + 1) * 86_400_000)
        for i, p in enumerate(prices_paise)
    ]
    stock_chart = types.SimpleNamespace(close=pts)
    chart_data = types.SimpleNamespace(values=[{symbol: stock_chart}])
    return types.SimpleNamespace(result=[chart_data])


class _FakeMarket:
    def current_price(self, instrument, exchange="NSE"):
        return type("P", (), {"price": 81250, "prev_close": 81000})()

    def historical_data(self, request):
        symbol = request["values"][0]
        # 25 bars at ascending paise values (81000..81025 paise)
        prices = [81_000 + i * 100 for i in range(25)]
        return _make_historical_response(symbol, prices)  # paise


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
    # S2: mandatory extra fields
    assert payload["order_type"] == "ORDER_TYPE_REGULAR"
    assert payload["exchange"] == "NSE"
    assert payload["validity_type"] == "DAY"


def test_place_rounds_to_tick_before_paise():
    client = _client()
    client.place_order(symbol="SBIN", side="BUY", qty=1, price_type="LIMIT",
                       price=Decimal("812.53"), client_tag="msl-2")  # -> 812.55
    assert client._sdk_trader.last["order_price"] == 81255


def test_place_market_omits_order_price():
    client = _client()
    client.place_order(symbol="SBIN", side="BUY", qty=1,
                       price_type="MARKET", price=None, client_tag="msl-3")
    # S3: order_price must be absent for MARKET orders (0 is a live-reject bug)
    assert "order_price" not in client._sdk_trader.last


# ---------------------------------------------------------------------------
# historical() — Caveat B fix: returns RUPEES, respects lookback
# ---------------------------------------------------------------------------

class TestHistorical:
    def test_returns_rupees_not_paise(self):
        client = _client()
        bars = client.historical("SBIN", lookback=20)
        # 25 bars generated; last 20 returned; last price = 81000 + 24*100 = 83400 paise = 834.00 ₹
        assert bars[-1]["close"] == pytest.approx(834.0, rel=1e-6)

    def test_respects_lookback(self):
        client = _client()
        assert len(client.historical("SBIN", lookback=20)) == 20
        assert len(client.historical("SBIN", lookback=10)) == 10

    def test_bars_sorted_oldest_first(self):
        client = _client()
        bars = client.historical("SBIN", lookback=20)
        timestamps = [b["timestamp"] for b in bars]
        assert timestamps == sorted(timestamps)

    def test_bar_has_close_and_timestamp_keys(self):
        client = _client()
        bar = client.historical("SBIN", lookback=5)[0]
        assert "close" in bar
        assert "timestamp" in bar

    def test_empty_result_returns_empty_list(self):
        class _EmptyMarket(_FakeMarket):
            def historical_data(self, request):
                return types.SimpleNamespace(result=[])

        c = NubraClient(
            config={"exchange": "NSE", "product": "CNC"},
            sdk_trader=_FakeTrader(),
            sdk_market=_EmptyMarket(),
            sdk_instruments=_FakeInst(),
        )
        assert c.historical("SBIN", lookback=5) == []

    def test_none_result_returns_empty_list(self):
        class _NoneMarket(_FakeMarket):
            def historical_data(self, request):
                return types.SimpleNamespace(result=None)

        c = NubraClient(
            config={"exchange": "NSE", "product": "CNC"},
            sdk_trader=_FakeTrader(),
            sdk_market=_NoneMarket(),
            sdk_instruments=_FakeInst(),
        )
        assert c.historical("SBIN", lookback=5) == []

    def test_first_value_in_sym_map_used_when_key_absent(self):
        """Falls back to first value if the symbol key isn't in sym_map dict."""
        class _AltKeyMarket(_FakeMarket):
            def historical_data(self, request):
                pts = [types.SimpleNamespace(value=50_000, timestamp=1_000)]
                stock_chart = types.SimpleNamespace(close=pts)
                # key is "SBIN-EQ" instead of "SBIN"
                chart_data = types.SimpleNamespace(values=[{"SBIN-EQ": stock_chart}])
                return types.SimpleNamespace(result=[chart_data])

        c = NubraClient(
            config={"exchange": "NSE", "product": "CNC"},
            sdk_trader=_FakeTrader(),
            sdk_market=_AltKeyMarket(),
            sdk_instruments=_FakeInst(),
        )
        bars = c.historical("SBIN", lookback=5)
        assert len(bars) == 1
        assert bars[0]["close"] == pytest.approx(500.0)

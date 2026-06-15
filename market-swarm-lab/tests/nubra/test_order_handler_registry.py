import pytest
from services.nubra_client.order_handler import OrderHandler, OrderHandlerRegistry


class _Equity(OrderHandler):
    asset_class = "equity"

    def handle(self, signal, risk, ticker):
        return {"asset_class": "equity", "status": "ok"}


def test_register_and_dispatch():
    reg = OrderHandlerRegistry()
    reg.register(_Equity())
    out = reg.dispatch("equity", {"trade": "CALL"}, {"approved": True}, "SBIN")
    assert out["asset_class"] == "equity"


def test_unknown_asset_class_raises():
    reg = OrderHandlerRegistry()
    with pytest.raises(KeyError):
        reg.dispatch("futures", {}, {}, "SBIN")

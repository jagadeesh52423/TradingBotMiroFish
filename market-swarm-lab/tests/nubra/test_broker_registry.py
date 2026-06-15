import pytest
from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_registry import BrokerRegistry


class _Dummy(BrokerClient):
    def place_order(self, order): return "placed"
    def cancel_order(self, broker_order_id): return True
    def modify_order(self, broker_order_id, **changes): raise NotImplementedError
    def get_order_status(self, broker_order_id): return None
    def get_positions(self): return []
    def get_funds(self): return {}


def test_register_and_get():
    reg = BrokerRegistry()
    reg.register("paper", _Dummy)
    assert isinstance(reg.get("paper"), _Dummy)


def test_unknown_mode_raises():
    reg = BrokerRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_cannot_instantiate_abc():
    with pytest.raises(TypeError):
        BrokerClient()

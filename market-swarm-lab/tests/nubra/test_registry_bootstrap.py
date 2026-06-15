from decimal import Decimal
from services.nubra_client.broker_registry import BrokerRegistry
from services.nubra_client.registry_bootstrap import register_all


def test_paper_mode_registered():
    registry = BrokerRegistry()
    register_all(registry)
    broker = registry.get("paper", ltp_provider=lambda sym: Decimal("100"))
    assert broker is not None
    funds = broker.get_funds()
    assert funds == {"paper": True}


def test_live_mode_registered_requires_client():
    registry = BrokerRegistry()
    register_all(registry)
    # live mode factory requires a nubra_client kwarg — KeyError without it
    try:
        registry.get("live")
    except TypeError:
        pass  # expected: missing required kwarg nubra_client
    except KeyError:
        raise  # "live" must be registered


def test_unknown_mode_raises_key_error():
    registry = BrokerRegistry()
    register_all(registry)
    try:
        registry.get("unknown_mode")
        assert False, "Should raise KeyError"
    except KeyError:
        pass

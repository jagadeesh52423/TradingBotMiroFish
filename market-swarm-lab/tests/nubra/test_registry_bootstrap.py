import pytest
from decimal import Decimal
from services.nubra_client.equity_paper_trader import EquityPaperTrader
from services.nubra_client.registry_bootstrap import build_broker_registry


def test_paper_mode_resolves_offline():
    reg = build_broker_registry(ltp_provider=lambda symbol: Decimal("100"))
    broker = reg.get("paper")
    assert isinstance(broker, EquityPaperTrader)
    assert broker.get_funds() == {"paper": True}


def test_nubra_uat_registered_but_guarded():
    reg = build_broker_registry(ltp_provider=lambda symbol: Decimal("100"))
    with pytest.raises(Exception):
        reg.get("nubra_uat")  # missing nubra_broker kwarg → RuntimeError


def test_nubra_live_registered_but_guarded():
    reg = build_broker_registry(ltp_provider=lambda symbol: Decimal("100"))
    with pytest.raises(Exception):
        reg.get("nubra_live")  # missing nubra_broker kwarg → RuntimeError


def test_unknown_mode_raises_key_error():
    reg = build_broker_registry(ltp_provider=lambda symbol: Decimal("100"))
    with pytest.raises(KeyError):
        reg.get("unknown_mode")

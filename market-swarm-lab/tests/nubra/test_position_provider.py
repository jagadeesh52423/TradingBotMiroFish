from services.nubra_client.position_provider import BrokerPositionProvider


class _FakeBroker:
    def get_positions(self):
        return [{"symbol": "SBIN", "net_quantity": 12},
                {"symbol": "RELIANCE", "net_quantity": 0}]


def test_net_qty_for_held_symbol():
    p = BrokerPositionProvider(_FakeBroker())
    assert p.net_quantity("SBIN") == 12


def test_net_qty_zero_for_unheld():
    p = BrokerPositionProvider(_FakeBroker())
    assert p.net_quantity("TATAMOTORS") == 0


def test_has_long_true_only_when_positive():
    p = BrokerPositionProvider(_FakeBroker())
    assert p.has_long("SBIN") is True
    assert p.has_long("RELIANCE") is False

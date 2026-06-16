from decimal import Decimal
from services.nubra_client.nubra_feed_adapter import NubraFeedAdapter


class _Client:
    def current_price(self, s):
        return Decimal({"SBIN": "800", "RELIANCE": "2900", "TATACONSUM": "1000"}[s])


def test_poll_emits_quote_events_for_all_symbols():
    got = []
    adapter = NubraFeedAdapter(_Client(), symbols=["SBIN", "RELIANCE", "TATACONSUM"])
    adapter.register_callback(lambda ev: got.append(ev))
    adapter.subscribe(["SBIN", "RELIANCE", "TATACONSUM"])
    adapter.poll_once()
    syms = {e["symbol"]: e for e in got}
    assert syms["SBIN"]["ltp"] == Decimal("800")
    assert syms["RELIANCE"]["ltp"] == Decimal("2900")
    assert len(got) == 3


def test_only_subscribed_symbols_emitted():
    got = []
    adapter = NubraFeedAdapter(_Client(), symbols=["SBIN", "RELIANCE", "TATACONSUM"])
    adapter.register_callback(lambda ev: got.append(ev))
    adapter.subscribe(["SBIN"])
    adapter.poll_once()
    assert [e["symbol"] for e in got] == ["SBIN"]

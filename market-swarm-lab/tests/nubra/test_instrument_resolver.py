from services.nubra_client.instrument_resolver import InstrumentResolver


class _FakeInst:
    def __init__(self): self.calls = 0

    def get_instrument_by_symbol(self, symbol, exchange="NSE"):
        self.calls += 1
        table = {"SBIN": (101, "0.05", 1), "RELIANCE": (202, "0.05", 1),
                 "TATAMOTORS": (303, "0.05", 1)}
        ref, tick, lot = table[symbol]
        return type("I", (), {"ref_id": ref, "tick_size": tick, "lot_size": lot})()


def test_resolve_returns_fields():
    resolver = InstrumentResolver(_FakeInst())
    info = resolver.resolve("SBIN")
    assert info["ref_id"] == 101
    assert info["tick_size"] == "0.05"


def test_resolve_is_cached():
    fake = _FakeInst()
    resolver = InstrumentResolver(fake)
    resolver.resolve("SBIN")
    resolver.resolve("SBIN")
    assert fake.calls == 1  # second hit served from cache

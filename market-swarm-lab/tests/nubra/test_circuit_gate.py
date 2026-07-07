"""Offline tests for the circuit-status entry gate + NSE quote parsing."""
from __future__ import annotations

from services.nubra_client.entry_gate import CircuitStatusGate, CompositeEntryGate, ExpectedUpsideGate
from services.nubra_client.circuit_status import _parse_quote


class _FakeProvider:
    def __init__(self, status):
        self._status = status
        self.calls = []

    def status(self, symbol):
        self.calls.append(symbol)
        return self._status


def _call(ticker="SBIN"):
    return {"trade": "CALL", "ticker": ticker, "expected_move_pct": 0.05, "horizon": "1d"}


def test_blocks_call_at_upper_circuit():
    gate = CircuitStatusGate(_FakeProvider({"last": 199.5, "upper": 200.0, "lower": 160.0}))
    ok, reason = gate.evaluate(_call())
    assert ok is False and "upper circuit" in reason


def test_allows_call_below_buffer():
    gate = CircuitStatusGate(_FakeProvider({"last": 180.0, "upper": 200.0, "lower": 160.0}))
    assert gate.evaluate(_call()) == (True, None)


def test_buffer_boundary_blocks():
    # buffer 1% → threshold 198.0; last exactly 198.0 blocks (>=).
    gate = CircuitStatusGate(_FakeProvider({"last": 198.0, "upper": 200.0, "lower": 160.0}),
                             {"upper_band_buffer_pct": 1.0})
    assert gate.evaluate(_call())[0] is False


def test_put_not_gated():
    prov = _FakeProvider({"last": 199.9, "upper": 200.0, "lower": 160.0})
    gate = CircuitStatusGate(prov)
    assert gate.evaluate({"trade": "PUT", "ticker": "SBIN"}) == (True, None)
    assert prov.calls == []  # provider not even consulted for a sell


def test_unknown_fails_open_by_default():
    gate = CircuitStatusGate(_FakeProvider(None))
    assert gate.evaluate(_call()) == (True, None)


def test_unknown_blocks_when_configured():
    gate = CircuitStatusGate(_FakeProvider(None), {"block_on_unknown": True})
    assert gate.evaluate(_call())[0] is False


def test_composite_first_block_wins():
    upside = ExpectedUpsideGate({"min_expected_upside_pct": 10.0})  # 5% move fails this
    circuit = CircuitStatusGate(_FakeProvider({"last": 1.0, "upper": 200.0, "lower": 160.0}))
    comp = CompositeEntryGate([upside, circuit])
    ok, reason = comp.evaluate(_call())
    assert ok is False and "upside" in reason  # first gate blocks


def test_parse_quote_handles_comma_strings():
    data = {"priceInfo": {"lastPrice": "1,234.50", "upperCP": "1,240.00", "lowerCP": "1,000.00",
                          "pPriceBand": "No Band"}}
    out = _parse_quote(data)
    # No previousClose in the payload -> base is None (fail-open shape).
    assert out == {"last": 1234.5, "upper": 1240.0, "lower": 1000.0, "band": "No Band", "base": None}


def test_parse_quote_captures_base_from_previous_close():
    # base (prev close) is the price the circuit band % is actually computed off — distinct
    # from lastPrice, which can already be up intraday.
    data = {"priceInfo": {"lastPrice": "1,234.50", "upperCP": "1,240.00", "lowerCP": "1,000.00",
                          "previousClose": "1,127.30", "pPriceBand": "10"}}
    out = _parse_quote(data)
    assert out["base"] == 1127.3


def test_parse_quote_none_when_no_band():
    # upperCP 0 (no band) → can't judge proximity → None
    data = {"priceInfo": {"lastPrice": "500", "upperCP": "0", "lowerCP": "0"}}
    assert _parse_quote(data) is None


# --- Fyers-backed circuit source -------------------------------------------

class _FakeFyersDepthClient:
    """Models Fyers depth(): `d` keyed by symbol -> row with ltp + upper_ckt/lower_ckt."""
    def __init__(self, row):
        self._row = row

    def depth(self, request):
        return {"s": "ok", "d": {request["symbol"]: self._row}}


def _fyers_provider(row):
    from services.fyers_client.fyers_data_provider import FyersDataProvider
    return FyersDataProvider("cid", "tok", client=_FakeFyersDepthClient(row))


def test_fyers_circuit_extracts_bands():
    prov = _fyers_provider({"ltp": 199.5, "upper_ckt": 200.0, "lower_ckt": 160.0})
    # No `c` (prev close) in the row -> base is None.
    assert prov.circuit("RELIANCE") == {
        "last": 199.5, "upper": 200.0, "lower": 160.0, "band": None, "base": None}


def test_fyers_circuit_extracts_base_from_prev_close():
    # `c` is the depth-row previous close — the actual base the band % is computed off.
    prov = _fyers_provider({"ltp": 199.5, "upper_ckt": 200.0, "lower_ckt": 160.0, "c": 180.0})
    assert prov.circuit("RELIANCE")["base"] == 180.0


def test_fyers_circuit_none_without_upper():
    prov = _fyers_provider({"ltp": 199.5})  # no circuit fields → None (fail-open)
    assert prov.circuit("RELIANCE") is None


def test_fyers_circuit_provider_gates_call():
    from services.nubra_client.circuit_status import FyersCircuitProvider
    gate = CircuitStatusGate(FyersCircuitProvider(_fyers_provider(
        {"ltp": 199.9, "upper_ckt": 200.0, "lower_ckt": 160.0})))
    assert gate.evaluate(_call("RELIANCE"))[0] is False  # pinned at upper → blocked


def test_fyers_circuit_provider_fails_safe_on_error():
    from services.nubra_client.circuit_status import FyersCircuitProvider

    class _Boom:
        def circuit(self, s):
            raise RuntimeError("no token")
    assert FyersCircuitProvider(_Boom()).status("RELIANCE") is None


# --- FyersCircuitProvider TTL cache (the runner fetches circuit status twice per CALL:
# once in sizing, once in the gate — an uncached FyersCircuitProvider doubles Fyers calls). ---

class _CountingFyers:
    def __init__(self, row=None):
        self._row = row or {"last": 100.0, "upper": 110.0, "lower": 90.0, "band": None, "base": None}
        self.calls = 0

    def circuit(self, symbol):
        self.calls += 1
        return dict(self._row)


def test_fyers_circuit_provider_caches_within_ttl():
    from services.nubra_client.circuit_status import FyersCircuitProvider

    fyers = _CountingFyers()
    provider = FyersCircuitProvider(fyers, cache_ttl_seconds=60)
    provider.status("RELIANCE")
    provider.status("RELIANCE")
    provider.status("reliance")  # cache key is upper-cased, same entry
    assert fyers.calls == 1, "repeated status() within TTL must not re-hit Fyers"


def test_fyers_circuit_provider_cache_expires_after_ttl(monkeypatch):
    from services.nubra_client import circuit_status as cs_module

    fyers = _CountingFyers()
    provider = cs_module.FyersCircuitProvider(fyers, cache_ttl_seconds=10)
    fake_clock = [0.0]
    monkeypatch.setattr(cs_module.time, "monotonic", lambda: fake_clock[0])

    provider.status("RELIANCE")
    fake_clock[0] = 5.0
    provider.status("RELIANCE")  # still within the 10s TTL
    assert fyers.calls == 1

    fake_clock[0] = 11.0
    provider.status("RELIANCE")  # TTL elapsed -> refetch
    assert fyers.calls == 2


def test_fyers_circuit_provider_from_config_reads_cache_ttl():
    from services.nubra_client.circuit_status import FyersCircuitProvider

    provider = FyersCircuitProvider.from_config(
        {"entry_threshold": {"circuit_gate": {"cache_ttl_seconds": 5}}})
    assert provider._cache_ttl == 5


def test_fyers_circuit_provider_cache_is_thread_safe():
    # The runner hits circuit status concurrently across symbols (ThreadPoolExecutor,
    # max_workers=3) — the per-symbol cache dict must survive concurrent read/write
    # without corruption or exceptions.
    import threading

    from services.nubra_client.circuit_status import FyersCircuitProvider

    fyers = _CountingFyers()
    provider = FyersCircuitProvider(fyers, cache_ttl_seconds=60)
    symbols = [f"SYM{i}" for i in range(20)]
    errors = []

    def worker():
        for _ in range(50):
            for sym in symbols:
                try:
                    provider.status(sym)
                except Exception as exc:  # pragma: no cover - would fail the test below
                    errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert set(provider._cache.keys()) == set(symbols)


# --- NseCircuitProvider._prime race guard -----------------------------------

def test_nse_provider_prime_is_race_free():
    # _prime lazily builds + primes the session; under concurrent callers (runner threads)
    # the homepage GET used to be a check-then-set race. With the lock, it must run once.
    import threading
    import time as time_module

    from services.nubra_client.circuit_status import NseCircuitProvider

    class _FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = 0
            self._lock = threading.Lock()

        def get(self, url, timeout=None, **kwargs):
            with self._lock:
                self.calls += 1
            time_module.sleep(0.01)  # widen the race window
            return self

        def raise_for_status(self):
            pass

    session = _FakeSession()
    provider = NseCircuitProvider(session=session)

    threads = [threading.Thread(target=provider._prime) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert session.calls == 1, "homepage prime GET must run exactly once under concurrent callers"
    assert provider._primed is True

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
    assert out == {"last": 1234.5, "upper": 1240.0, "lower": 1000.0, "band": "No Band"}


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
    assert prov.circuit("RELIANCE") == {"last": 199.5, "upper": 200.0, "lower": 160.0, "band": None}


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

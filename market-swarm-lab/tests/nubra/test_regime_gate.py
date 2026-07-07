"""§10 market-regime gate + provider."""
from __future__ import annotations

from services.nubra_client.market_regime import MarketRegimeProvider
from services.nubra_client.entry_gate import RegimeGate


def _prov(closes, ma=20, min_bars=15):
    return MarketRegimeProvider(lambda idx: closes, "NSE:NIFTY50-INDEX", ma, min_bars)


def test_regime_up_and_down():
    assert _prov([100 + i for i in range(25)]).regime() == "up"     # rising → last >= sma
    assert _prov([200 - i for i in range(25)]).regime() == "down"   # falling → last < sma


def test_regime_none_thin_or_error():
    assert _prov([100] * 5, min_bars=15).regime() is None          # thin history
    p = MarketRegimeProvider(lambda idx: (_ for _ in ()).throw(RuntimeError("x")))
    assert p.regime() is None                                       # fetch error → fail open


def test_regime_cached():
    calls = []

    def closes_fn(idx):
        calls.append(idx)
        return [100 + i for i in range(25)]
    p = MarketRegimeProvider(closes_fn)
    p.regime(); p.regime(); p.regime()
    assert len(calls) == 1  # resolved once, cached


def _call():
    return {"trade": "CALL", "ticker": "SBIN"}


def test_gate_blocks_call_in_down_market():
    gate = RegimeGate(_prov([200 - i for i in range(25)]))
    ok, reason = gate.evaluate(_call())
    assert ok is False and "regime" in reason


def test_gate_allows_call_in_up_market():
    assert RegimeGate(_prov([100 + i for i in range(25)])).evaluate(_call()) == (True, None)


def test_gate_allows_when_unknown():  # fail-open
    assert RegimeGate(_prov([100] * 5, min_bars=15)).evaluate(_call()) == (True, None)


def test_gate_ignores_put():
    gate = RegimeGate(_prov([200 - i for i in range(25)]))  # down market
    assert gate.evaluate({"trade": "PUT", "ticker": "SBIN"}) == (True, None)

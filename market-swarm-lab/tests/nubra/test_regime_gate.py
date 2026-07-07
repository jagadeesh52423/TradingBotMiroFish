"""§10 market-regime gate + provider."""
from __future__ import annotations

import threading
import time

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


def test_regime_cache_atomic_under_concurrent_calls():
    """Two threads racing on first resolve must not have one observe `_resolved=True`
    before `_cached` is actually computed — that returned a stale None (regime gate
    failing open in a down-market) instead of the real, computed regime."""
    def closes_fn(idx):
        time.sleep(0.02)  # widen the race window so concurrent threads actually overlap
        return [200 - i for i in range(25)]  # falling -> "down"

    p = MarketRegimeProvider(closes_fn)
    results: list[str | None] = []

    def call():
        results.append(p.regime())

    threads = [threading.Thread(target=call) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r == "down" for r in results)


def test_regime_none_when_bars_short_of_full_ma_even_above_min_bars():
    # min_bars (15) < ma (20): 18 bars clears the old min_bars floor but is still short
    # of the 20-day SMA window — must return None, not run a "20-day" SMA on 18 bars.
    assert _prov([100 + i for i in range(18)], ma=20, min_bars=15).regime() is None


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

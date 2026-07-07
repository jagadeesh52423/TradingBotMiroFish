"""Offline tests for the sector-tailwind gate + trend provider."""
from __future__ import annotations

from services.nubra_client.entry_gate import SectorTrendGate
from services.nubra_client.sector_trend import SectorTrendProvider

_MAP = {"SBIN": "NSE:NIFTYBANK-INDEX"}


def _provider(closes, lookback=20, min_bars=10):
    return SectorTrendProvider(_MAP, lambda idx: closes, lookback, min_bars)


def test_trend_up_when_last_above_sma():
    # rising series → last >= SMA → up
    assert _provider([100 + i for i in range(20)]).trend("SBIN") == "up"


def test_trend_down_when_last_below_sma():
    # falling series → last < SMA → down
    assert _provider([200 - i for i in range(20)]).trend("SBIN") == "down"


def test_trend_none_for_unmapped_symbol():
    assert _provider([100] * 20).trend("RELIANCE") is None  # not in _MAP


def test_trend_none_when_thin_data():
    assert _provider([100] * 5, min_bars=10).trend("SBIN") is None


def test_trend_none_on_fetch_error():
    prov = SectorTrendProvider(_MAP, lambda idx: (_ for _ in ()).throw(RuntimeError("boom")))
    assert prov.trend("SBIN") is None


def test_trend_caches_closes_per_index_across_symbols():
    # A run maps many symbols to a handful of shared sector indices; the provider must
    # fetch each index's closes at most once, not once per symbol per call.
    calls = []

    def closes_fn(idx):
        calls.append(idx)
        return [100 + i for i in range(20)]

    sector_map = {"SBIN": "NSE:NIFTYBANK-INDEX", "HDFCBANK": "NSE:NIFTYBANK-INDEX"}
    prov = SectorTrendProvider(sector_map, closes_fn, 20, 10)
    prov.trend("SBIN")
    prov.trend("HDFCBANK")
    prov.trend("SBIN")
    assert calls == ["NSE:NIFTYBANK-INDEX"]  # one live fetch, reused for both symbols


def test_trend_memoizes_fetch_failure_too():
    calls = []

    def closes_fn(idx):
        calls.append(idx)
        raise RuntimeError("throttled")

    prov = SectorTrendProvider(_MAP, closes_fn)
    prov.trend("SBIN")
    prov.trend("SBIN")
    assert len(calls) == 1  # failure memoized, not retried every call


def _call(ticker="SBIN"):
    return {"trade": "CALL", "ticker": ticker}


def test_gate_blocks_call_in_falling_sector():
    gate = SectorTrendGate(_provider([200 - i for i in range(20)]))
    ok, reason = gate.evaluate(_call())
    assert ok is False and "sector" in reason


def test_gate_allows_call_in_rising_sector():
    gate = SectorTrendGate(_provider([100 + i for i in range(20)]))
    assert gate.evaluate(_call()) == (True, None)


def test_gate_allows_unmapped_symbol():  # fail-open
    gate = SectorTrendGate(_provider([200 - i for i in range(20)]))
    assert gate.evaluate(_call("RELIANCE")) == (True, None)


def test_gate_ignores_put():
    prov = _provider([200 - i for i in range(20)])  # down sector
    gate = SectorTrendGate(prov)
    assert gate.evaluate({"trade": "PUT", "ticker": "SBIN"}) == (True, None)


# --- dynamic sector map (bundled snapshot) ----------------------------------

def test_dynamic_sector_map_loads_snapshot():
    from services.nubra_client.sector_trend import load_dynamic_sector_map
    m = load_dynamic_sector_map()
    assert len(m) > 100  # snapshot has ~160 members across sector indices
    # a few well-known memberships (stable large-caps)
    assert m.get("INFY") == "NSE:NIFTYIT-INDEX"
    assert m.get("TATASTEEL") == "NSE:NIFTYMETAL-INDEX"
    assert m.get("HDFCBANK") == "NSE:NIFTYBANK-INDEX"
    # every mapped index must be a Fyers-valid -INDEX symbol
    assert all(v.startswith("NSE:") and v.endswith("-INDEX") for v in m.values())

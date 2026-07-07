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

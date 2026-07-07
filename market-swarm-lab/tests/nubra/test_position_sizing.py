"""Circuit-band-aware position sizing (§5)."""
from __future__ import annotations

from decimal import Decimal

from services.nubra_client.position_sizing import band_pct_from_circuit, band_size_factor
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder


def test_band_pct_from_circuit():
    # 10% band: upper = last * 1.10
    assert round(band_pct_from_circuit({"last": 100.0, "upper": 110.0}), 2) == 10.0
    assert band_pct_from_circuit({"last": 0, "upper": 110.0}) is None


def test_band_size_factor_tiers():
    assert band_size_factor(2.0) == 0.5    # tight 2% band → half
    assert band_size_factor(5.0) == 0.7    # 5% band
    assert band_size_factor(10.0) == 1.0   # wide → full
    assert band_size_factor(20.0) == 1.0


def test_band_size_factor_custom_tiers():
    tiers = [[2.5, 0.25], [10000, 1.0]]
    assert band_size_factor(2.0, tiers) == 0.25
    assert band_size_factor(9.0, tiers) == 1.0


class _StubPos:
    def net_quantity(self, ticker):
        return 0


def _translator():
    return SignalToEquityOrder(
        whitelist={"SBIN"}, ltp_provider=lambda s: Decimal("100"),
        position_provider=_StubPos(), account_value=Decimal("1000000"),
        risk_per_trade_pct=Decimal("1.0"), price_type="LIMIT")


def test_size_factor_halves_quantity():
    # risk = 1% of 1,000,000 = 10,000; /ltp 100 = 100 shares full; x0.5 = 50.
    xlate = _translator()
    full, _ = xlate.translate({"trade": "CALL", "ticker": "SBIN", "signal_id": "a"}, "2026-07-07")
    half, _ = xlate.translate({"trade": "CALL", "ticker": "SBIN", "signal_id": "b", "size_factor": 0.5}, "2026-07-07")
    assert full.qty == 100
    assert half.qty == 50


def test_missing_size_factor_defaults_full():
    xlate = _translator()
    order, _ = xlate.translate({"trade": "CALL", "ticker": "SBIN", "signal_id": "c"}, "2026-07-07")
    assert order.qty == 100

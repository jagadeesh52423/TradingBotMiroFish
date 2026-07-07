"""§8 delivery-% soft conviction flag (advisory, never a gate)."""
from __future__ import annotations

from datetime import date

from services.nubra_client.equity_runner import _delivery_conviction
from services.nse_delivery.delivery_collector import NseDeliveryCollector


def test_conviction_high_when_at_or_above_avg():
    assert _delivery_conviction(65.0, 50.0) == "high"
    assert _delivery_conviction(50.0, 50.0) == "high"  # >= boundary


def test_conviction_low_when_below_avg():
    assert _delivery_conviction(40.0, 50.0) == "low"


def test_conviction_none_when_missing():
    assert _delivery_conviction(None, 50.0) is None
    assert _delivery_conviction(50.0, None) is None


def test_collector_feeds_flag_from_seeded_data():
    # Seed 3 prior sessions + today; SBIN today (70) above its ~50 trailing avg → high.
    day_maps = {
        date(2026, 7, 2): {"SBIN": 48.0},
        date(2026, 7, 3): {"SBIN": 50.0},
        date(2026, 7, 6): {"SBIN": 52.0},
        date(2026, 7, 7): {"SBIN": 70.0},
    }
    coll = NseDeliveryCollector(day_maps=day_maps, auto_fetch=False)
    on = date(2026, 7, 7)
    deliv = coll.deliv_pct("SBIN", on)
    avg = coll.trailing_avg("SBIN", on, 20)
    assert deliv == 70.0
    assert _delivery_conviction(deliv, avg) == "high"

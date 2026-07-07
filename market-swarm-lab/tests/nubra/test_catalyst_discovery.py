"""Catalyst-driven universe discovery (playbook §2)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from services.nubra_client.catalyst_discovery import CatalystDiscovery
from services.nubra_client.universe_registry import resolve_universe, register_universe


class _FakeEvents:
    def __init__(self, events):
        self._events = events

    def collect_range(self, frm, to):
        return self._events


def _disc(events, ann_syms, max_symbols=150):
    d = CatalystDiscovery(_FakeEvents(events), lookahead_days=10, lookback_days=3, max_symbols=max_symbols)
    return d, ann_syms


def test_union_of_events_and_announcements():
    events = [{"symbol": "SBIN"}, {"symbol": "reliance"}, {"symbol": ""}]
    d, _ = _disc(events, {"TCS", "SBIN"})
    with patch.object(d, "_recent_announcements", return_value={"TCS": "Order win", "SBIN": "Results"}):
        out = d.discover(today=date(2026, 7, 7))
        detail = d.discover_detailed(today=date(2026, 7, 7))
    assert out == ["RELIANCE", "SBIN", "TCS"]  # deduped, upper, sorted, no blank
    assert detail["TCS"]["event"] == "Order win"  # announcement desc captured as the catalyst


def test_caps_max_symbols():
    events = [{"symbol": f"SYM{i}"} for i in range(200)]
    d, _ = _disc(events, set(), max_symbols=50)
    with patch.object(d, "_recent_announcements", return_value={}):
        assert len(d.discover(today=date(2026, 7, 7))) == 50


def test_a_failing_feed_does_not_sink_discovery():
    events = [{"symbol": "SBIN"}]
    d, _ = _disc(events, set())
    with patch.object(d, "_recent_announcements", side_effect=RuntimeError("nse down")):
        assert d.discover(today=date(2026, 7, 7)) == ["SBIN"]  # events still contribute


def test_resolve_universe_registry_and_fallback():
    register_universe("tinytest", ["A", "B"])
    assert resolve_universe({}, "tinytest") == ["A", "B"]
    assert resolve_universe({"whitelist": ["X"]}, None) == ["X"]


def test_resolve_universe_catalyst_calls_discovery():
    cfg = {}
    with patch("services.nubra_client.catalyst_discovery.CatalystDiscovery.from_config") as ctor:
        ctor.return_value.discover_detailed.return_value = {"BAR": {"type": "Dividend"}, "FOO": {"type": "Results"}}
        assert resolve_universe(cfg, "catalyst") == ["BAR", "FOO"]  # sorted keys
        assert cfg["catalyst_map"]["FOO"]["type"] == "Results"  # map stashed for the doc


def test_max_symbols_zero_means_uncapped():
    events = [{"symbol": f"SYM{i}"} for i in range(300)]
    d, _ = _disc(events, set(), max_symbols=0)  # 0 = unlimited
    with patch.object(d, "_recent_announcements", return_value={}):
        assert len(d.discover(today=date(2026, 7, 7))) == 300  # no cap applied


def test_positive_cap_keeps_top_turnover_not_alphabetical():
    from services.nubra_client.catalyst_discovery import SurveillanceLiquidityGuard
    g = SurveillanceLiquidityGuard(exclude_surveillance=False)
    g._last_turnover = {"ZEBRA": 9000.0, "ALPHA": 100.0, "MANGO": 5000.0}  # lacs
    # cap to 2 → the two most-liquid (ZEBRA, MANGO), NOT the alphabetical first (ALPHA, MANGO)
    top = g.top_by_turnover(["ALPHA", "MANGO", "ZEBRA"], 2)
    assert set(top) == {"ZEBRA", "MANGO"}
    assert "ALPHA" not in top

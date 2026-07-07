"""§7 catalyst stacking over the aggregator's source_audit."""
from __future__ import annotations

from services.nubra_client.equity_runner import _catalyst_stack


def test_stacked_when_two_plus_sources_fire():
    nse = {"source_audit": {
        "nse_announcements": {"count": 3}, "google_news": {"count": 5}, "usfda": {"count": 0}}}
    out = _catalyst_stack(nse)
    assert out["catalyst_stack_count"] == 2
    assert out["catalyst_sources"] == ["google_news", "nse_announcements"]
    assert out["stacked"] is True


def test_not_stacked_with_single_source():
    nse = {"source_audit": {"nse_announcements": {"count": 1}, "google_news": {"count": 0}}}
    out = _catalyst_stack(nse)
    assert out["catalyst_stack_count"] == 1 and out["stacked"] is False


def test_empty_audit():
    assert _catalyst_stack({})["catalyst_stack_count"] == 0
    assert _catalyst_stack({"source_audit": {}})["stacked"] is False

"""Offline tests for AggregatingNewsCollector — unions sources, analyzes once."""
from __future__ import annotations

from services.nubra_client.news_aggregator import AggregatingNewsCollector
from services.nse_announcements.sentiment_analyzer import KeywordSentimentAnalyzer


class _FakeSource:
    def __init__(self, items, mode):
        self._items, self._mode = items, mode
        self.calls = 0

    def fetch(self, symbol):
        self.calls += 1
        return self._items, self._mode


def _agg(sources):
    return AggregatingNewsCollector(sources, KeywordSentimentAnalyzer())


def test_unions_items_and_analyzes_once():
    nse = _FakeSource([{"attchmntText": "board approved dividend"}], "nse_live")
    gn = _FakeSource([{"attchmntText": "brokerages upgrade rating; bonus issue"}], "google_live")
    out = _agg([("nse_announcements", nse), ("google_news", gn)]).collect("reliance")

    assert out["symbol"] == "RELIANCE"
    assert len(out["items"]) == 2  # union
    assert out["sentiment_label"] == "bullish"  # dividend + upgrade + bonus
    assert out["source_audit"]["nse_announcements"] == {
        "status": "live", "count": 1, "engine": "keyword", "degraded": False}
    assert out["source_audit"]["google_news"]["status"] == "live"
    assert nse.calls == 1 and gn.calls == 1  # each source fetched once


def test_provider_mode_live_if_any_source_live():
    nse = _FakeSource([{"attchmntText": "x"}], "fixture_fallback")
    gn = _FakeSource([{"attchmntText": "y"}], "google_live")
    out = _agg([("nse_announcements", nse), ("google_news", gn)]).collect("X")
    assert out["provider_mode"] == "nse_live"


def test_provider_mode_fallback_when_all_fallback():
    nse = _FakeSource([], "fixture_fallback")
    gn = _FakeSource([], "fixture_fallback")
    out = _agg([("nse_announcements", nse), ("google_news", gn)]).collect("X")
    assert out["provider_mode"] == "fixture_fallback"
    assert out["sentiment_label"] == "neutral"


def test_broken_source_does_not_sink_others():
    class _Boom:
        def fetch(self, symbol):
            raise RuntimeError("down")
    good = _FakeSource([{"attchmntText": "dividend bonus"}], "nse_live")
    out = _agg([("nse_announcements", _Boom()), ("google_news", good)]).collect("X")
    assert out["provider_mode"] == "nse_live"
    assert out["source_audit"]["nse_announcements"] == {
        "status": "fallback", "count": 0, "engine": "keyword", "degraded": False}
    assert len(out["items"]) == 1


def test_nse_only_from_config_when_google_disabled():
    agg = AggregatingNewsCollector.from_config({"nse": {"sentiment_engine": "keyword"}})
    assert [k for k, _ in agg._sources] == ["nse_announcements"]


def test_google_added_from_config_when_enabled():
    agg = AggregatingNewsCollector.from_config(
        {"nse": {"sentiment_engine": "keyword"}, "news": {"google": {"enabled": True}}}
    )
    assert [k for k, _ in agg._sources] == ["nse_announcements", "google_news"]

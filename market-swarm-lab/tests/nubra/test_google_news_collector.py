"""Offline unit tests for the Google News RSS collector.

No real network — _fetch is either mocked or forced to fail into the fixture.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from services.google_news.google_news_collector import GoogleNewsCollector, _parse_rss

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Acme declares dividend and bonus; brokerages upgrade rating</title>
  <link>https://news.google.com/x</link>
  <pubDate>Mon, 06 Jul 2026 09:15:00 GMT</pubDate>
  <source url="https://mc.com">Moneycontrol</source>
</item>
<item>
  <title></title>
  <link>https://news.google.com/empty</link>
</item>
</channel></rss>"""


def test_parse_rss_extracts_titles_and_skips_empty():
    items = _parse_rss(_SAMPLE_RSS)
    assert len(items) == 1  # empty-title item dropped
    it = items[0]
    assert it["attchmntText"] == it["title"] == "Acme declares dividend and bonus; brokerages upgrade rating"
    assert it["source"] == "Moneycontrol"
    assert it["link"] == "https://news.google.com/x"


def test_collect_live_scores_sentiment():
    collector = GoogleNewsCollector()  # default keyword analyzer
    with patch.object(collector, "_fetch", return_value=_parse_rss(_SAMPLE_RSS)):
        out = collector.collect("acme")
    assert out["symbol"] == "ACME"
    assert out["provider_mode"] == "google_live"
    assert out["source_audit"]["google_news"]["status"] == "live"
    # "dividend" + "bonus" + "upgrade" are bullish keywords
    assert out["sentiment_label"] == "bullish"
    assert out["documents"][0]["source"] == "google_news"


def test_collect_falls_back_to_fixture_on_fetch_error():
    collector = GoogleNewsCollector()
    with patch.object(collector, "_fetch", side_effect=requests.RequestException("boom")):
        out = collector.collect("RELIANCE")  # has an xml fixture
    assert out["provider_mode"] == "fixture_fallback"
    assert out["source_audit"]["google_news"]["status"] == "fallback"
    assert len(out["items"]) == 3
    assert out["sentiment_label"] == "bullish"  # dividend/bonus/upgrade/profit


def test_collect_empty_when_no_fixture():
    collector = GoogleNewsCollector()
    with patch.object(collector, "_fetch", side_effect=requests.RequestException("boom")):
        out = collector.collect("NOSUCHSYM")
    assert out["items"] == []
    assert out["sentiment_label"] == "neutral"


def test_from_config_shares_sentiment_engine():
    collector = GoogleNewsCollector.from_config(
        {"nse": {"sentiment_engine": "keyword"}, "news": {"google": {"max_items": 5, "lookback_days": 3}}}
    )
    assert collector._max_items == 5
    assert collector._lookback_days == 3


def test_max_items_caps_fixture():
    collector = GoogleNewsCollector(max_items=2)
    with patch.object(collector, "_fetch", side_effect=requests.RequestException("boom")):
        out = collector.collect("RELIANCE")
    assert len(out["items"]) == 2

"""India Reddit (social) collector — OAuth, parse, fail-safe."""
from __future__ import annotations

from unittest.mock import patch

import requests

from services.reddit_india.india_reddit_collector import IndiaRedditCollector, _parse

_PAYLOAD = {"data": {"children": [
    {"data": {"title": "RELIANCE looks bullish", "selftext": "breakout", "subreddit": "IndianStreetBets",
              "score": 100, "num_comments": 30}},
    {"data": {"title": "", "selftext": "x"}},  # empty title → skipped
]}}


def test_parse_builds_items():
    items = _parse(_PAYLOAD)
    assert len(items) == 1
    assert items[0]["attchmntText"].startswith("RELIANCE looks bullish")
    assert items[0]["source"] == "reddit" and items[0]["subreddit"] == "IndianStreetBets"


def test_no_credentials_falls_back_to_fixture():
    c = IndiaRedditCollector(client_id=None, client_secret=None)
    items, mode = c.fetch("RELIANCE")  # has a fixture (2 posts)
    assert mode == "no_credentials" and len(items) == 2


def test_no_credentials_empty_when_no_fixture():
    c = IndiaRedditCollector(client_id=None, client_secret=None)
    assert c.fetch("NOSUCH") == ([], "no_credentials")


def test_live_search_parses():
    c = IndiaRedditCollector(client_id="x", client_secret="y")
    with patch.object(c, "_search", return_value=_parse(_PAYLOAD)):
        items, mode = c.fetch("RELIANCE")
    assert mode == "reddit_live" and len(items) == 1


def test_search_error_falls_back_to_fixture():
    c = IndiaRedditCollector(client_id="x", client_secret="y")
    with patch.object(c, "_search", side_effect=requests.RequestException("boom")):
        items, mode = c.fetch("RELIANCE")
    assert mode == "fixture_fallback" and len(items) == 2

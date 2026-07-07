"""§9 USFDA (openFDA) recall collector."""
from __future__ import annotations

from unittest.mock import patch

import requests

from services.usfda.usfda_collector import UsfdaCollector, _parse

_PAYLOAD = {"results": [
    {"report_date": "20260701", "classification": "Class II",
     "product_description": "Perampanel Tablets", "reason_for_recall": "Label mix-up"},
    {"report_date": "20260617", "classification": "Class II",
     "product_description": "Budesonide Suspension", "reason_for_recall": "Foreign substance"},
]}

_MAP = {"SUNPHARMA": "Sun Pharmaceutical"}


def test_parse_builds_recall_items():
    items = _parse(_PAYLOAD)
    assert len(items) == 2
    assert items[0]["attchmntText"].startswith("USFDA recall (Class II): Perampanel")
    assert items[0]["source"] == "usfda"


def test_parse_skips_empty_rows():
    payload = {"results": [{"product_description": "", "reason_for_recall": ""}]}
    assert _parse(payload) == []


def test_unmapped_symbol_returns_no_items():
    c = UsfdaCollector(_MAP)
    assert c.fetch("RELIANCE") == ([], "no_mapping")  # not a mapped pharma name


def test_fetch_live_parses(monkeypatch):
    c = UsfdaCollector(_MAP)
    with patch.object(c, "_fetch", return_value=_parse(_PAYLOAD)):
        items, mode = c.fetch("SUNPHARMA")
    assert mode == "usfda_live" and len(items) == 2


def test_fetch_falls_back_to_fixture():
    c = UsfdaCollector(_MAP)
    with patch.object(c, "_fetch", side_effect=requests.RequestException("boom")):
        items, mode = c.fetch("SUNPHARMA")  # has a fixture
    assert mode == "fixture_fallback" and len(items) == 2


def test_collect_scores_recall_bearish():
    c = UsfdaCollector(_MAP)
    with patch.object(c, "_fetch", return_value=_parse(_PAYLOAD)):
        out = c.collect("SUNPHARMA")
    assert out["sentiment_label"] == "bearish"  # 'recall' is a bearish keyword
    assert out["documents"][0]["source"] == "usfda"

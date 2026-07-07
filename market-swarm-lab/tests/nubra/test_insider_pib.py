"""§9 insider (SAST/PIT) + PIB collectors."""
from __future__ import annotations

from unittest.mock import patch

import requests

from services.nse_insider.insider_collector import NseInsiderCollector, _parse as insider_parse
from services.pib.pib_collector import PibCollector, _parse_rss

# --- insider ----------------------------------------------------------------

_PIT = {"data": [
    {"acqName": "Promoter X", "tdpTransactionType": "Buy", "personCategory": "Promoter",
     "secVal": 1000000, "date": "01-Jul-2026"},
    {"acqName": "", "tdpTransactionType": "", "personCategory": ""},  # empty → skipped
]}


def test_insider_parse():
    items = insider_parse(_PIT)
    assert len(items) == 1
    assert items[0]["attchmntText"].startswith("Insider Buy by Promoter X")
    assert items[0]["source"] == "insider"


def test_insider_live():
    c = NseInsiderCollector()
    with patch.object(c, "_fetch", return_value=insider_parse(_PIT)):
        items, mode = c.fetch("SUNPHARMA")
    assert mode == "insider_live" and len(items) == 1


def test_insider_fixture_fallback():
    c = NseInsiderCollector()  # fresh — no cache
    with patch.object(c, "_fetch", side_effect=requests.RequestException("boom")):
        items, mode = c.fetch("SUNPHARMA")  # has fixture (2 rows)
    assert mode == "fixture_fallback" and len(items) == 2


# --- PIB --------------------------------------------------------------------

_RSS = """<rss><channel>
<item><title>Bharat Electronics wins defence order</title><description>BEL bags contract</description><link>x</link></item>
<item><title>Unrelated ministry notice</title><description>nothing</description><link>y</link></item>
</channel></rss>"""


def test_pib_parse_rss():
    items = _parse_rss(_RSS)
    assert len(items) == 2 and items[0]["source"] == "pib"


def test_pib_matches_only_mapped_terms():
    c = PibCollector({"BEL": ["bharat electronics"]})
    with patch.object(c, "_fetch_feed", return_value=_RSS):
        items, mode = c.fetch("BEL")
    assert mode == "pib_live" and len(items) == 1  # only the BEL release matched
    # unmapped symbol → no query
    assert c.fetch("RELIANCE") == ([], "no_mapping")


def test_pib_no_match_returns_empty():
    c = PibCollector({"TCS": ["tata consultancy"]})
    with patch.object(c, "_fetch_feed", return_value=_RSS):
        items, mode = c.fetch("TCS")
    assert items == []  # no release mentions the mapped term

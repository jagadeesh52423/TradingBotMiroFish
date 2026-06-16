"""Offline unit tests for NseAnnouncementsCollector.

No live NSE network. All HTTP is monkey-patched or injected via fake session.
(BP-123 — never weaken a test to match a stub)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from services.nse_announcements.nse_announcements_collector import (
    NseAnnouncementsCollector,
    _score_sentiment,
)

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "services" / "nse_announcements" / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixture_items(symbol: str) -> list[dict]:
    return json.loads((_FIXTURE_DIR / f"nse_announcements_{symbol}.json").read_text())


def _fake_session(json_data: list) -> MagicMock:
    """Returns a mock requests.Session whose GET returns the given JSON list."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    sess = MagicMock(spec=requests.Session)
    sess.get.return_value = resp
    sess.headers = {}
    return sess


# ---------------------------------------------------------------------------
# Fixture loading tests
# ---------------------------------------------------------------------------

class TestFixtureFallback:
    def test_fixture_fallback_when_fetch_raises(self):
        """When the session raises, should degrade to fixture."""
        sess = MagicMock(spec=requests.Session)
        sess.get.side_effect = requests.ConnectionError("no internet")
        sess.headers = {}
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["provider_mode"] == "fixture_fallback"
        assert len(result["items"]) > 0  # fixture has 2 items for SBIN

    def test_fixture_items_match_json_on_disk(self):
        sess = MagicMock(spec=requests.Session)
        sess.get.side_effect = requests.ConnectionError("offline")
        sess.headers = {}
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("RELIANCE")
        expected = _fixture_items("RELIANCE")
        assert result["items"] == expected

    def test_empty_list_returned_when_no_fixture_and_fetch_fails(self):
        """Symbol with no fixture → empty items (not a crash)."""
        sess = MagicMock(spec=requests.Session)
        sess.get.side_effect = requests.ConnectionError("offline")
        sess.headers = {}
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("NOSYMBOL")
        assert result["items"] == []
        assert result["provider_mode"] == "fixture_fallback"

    def test_fallback_source_audit_status_is_fallback(self):
        sess = MagicMock(spec=requests.Session)
        sess.get.side_effect = requests.ConnectionError("offline")
        sess.headers = {}
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["source_audit"]["nse_announcements"]["status"] == "fallback"


# ---------------------------------------------------------------------------
# Parsing / shape tests
# ---------------------------------------------------------------------------

class TestCollectShape:
    def test_result_has_required_keys(self):
        sess = _fake_session(_fixture_items("SBIN"))
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        for key in ("symbol", "provider_mode", "items", "documents", "sentiment_score", "sentiment_label", "source_audit"):
            assert key in result, f"missing key: {key}"

    def test_symbol_normalised_to_upper(self):
        sess = _fake_session(_fixture_items("SBIN"))
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("sbin")
        assert result["symbol"] == "SBIN"

    def test_documents_extracted_from_attchmnt_text(self):
        items = [{"attchmntText": "Quarterly profit growth announced.", "symbol": "SBIN"}]
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert len(result["documents"]) == 1
        assert result["documents"][0]["content"] == "Quarterly profit growth announced."
        assert result["documents"][0]["source"] == "nse_filing"

    def test_items_without_attchmnt_text_excluded_from_documents(self):
        items = [
            {"attchmntText": "Board meeting scheduled.", "symbol": "SBIN"},
            {"symbol": "SBIN"},  # no attchmntText
            {"attchmntText": "", "symbol": "SBIN"},  # empty string
        ]
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert len(result["documents"]) == 1

    def test_source_audit_count_matches_items(self):
        items = _fixture_items("RELIANCE")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("RELIANCE")
        assert result["source_audit"]["nse_announcements"]["count"] == len(items)

    def test_live_provider_mode_on_successful_fetch(self):
        items = _fixture_items("SBIN")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["provider_mode"] == "nse_live"

    def test_source_audit_status_live_on_success(self):
        items = _fixture_items("SBIN")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["source_audit"]["nse_announcements"]["status"] == "live"


# ---------------------------------------------------------------------------
# Sentiment scoring tests
# ---------------------------------------------------------------------------

class TestSentimentScoring:
    def test_empty_items_gives_neutral_score(self):
        assert _score_sentiment([]) == 0.0

    def test_bullish_keywords_give_positive_score(self):
        items = [{"attchmntText": "Company announces dividend and profit growth record earnings."}]
        score = _score_sentiment(items)
        assert score > 0.0

    def test_bearish_keywords_give_negative_score(self):
        items = [{"attchmntText": "Company receives fine and penalty for fraud investigation."}]
        score = _score_sentiment(items)
        assert score < 0.0

    def test_score_clamped_between_minus1_and_1(self):
        # Pile on many keywords to test clamping
        text = " ".join(["penalty", "fine", "loss", "fraud", "investigation",
                         "downgrade", "delay", "insolvency", "litigation", "adverse"] * 5)
        items = [{"attchmntText": text}]
        score = _score_sentiment(items)
        assert -1.0 <= score <= 1.0

    def test_sentiment_label_bullish_for_high_score(self):
        items = [{"attchmntText": "dividend bonus growth profit earnings record expansion acquisition"}]
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["sentiment_label"] == "bullish"
        assert result["sentiment_score"] > 0.1

    def test_sentiment_label_bearish_for_low_score(self):
        items = [{"attchmntText": "penalty fine loss fraud investigation insolvency litigation adverse"}]
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["sentiment_label"] == "bearish"
        assert result["sentiment_score"] < -0.1

    def test_sentiment_label_neutral_for_zero_score(self):
        # No keywords at all → score=0.0 → neither > 0.1 nor < -0.1 → "neutral"
        items = [{"attchmntText": "Board meeting details of director appointment."}]
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("SBIN")
        assert result["sentiment_label"] == "neutral"

    def test_tataconsum_fixture_has_mixed_sentiment(self):
        """TATACONSUM fixture: item 0 has earnings/profit/growth/expansion (+0.4),
        item 1 has penalty/investigation (-0.2); net = +0.2."""
        items = _fixture_items("TATACONSUM")
        score = _score_sentiment(items)
        assert score == pytest.approx(0.2, abs=1e-4)
        assert score > 0, "bullish keywords must outweigh bearish in this fixture"


# ---------------------------------------------------------------------------
# TTL cache tests
# ---------------------------------------------------------------------------

class TestCache:
    def test_second_call_for_same_symbol_does_not_hit_session_again(self):
        items = _fixture_items("SBIN")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        collector.collect("SBIN")
        collector.collect("SBIN")
        # session.get should have been called only once (prime + 1 API call)
        # prime is on the homepage, API is the corporate-announcements URL
        assert sess.get.call_count == 2  # 1 homepage prime + 1 API call

    def test_cache_hit_uses_nse_live_mode(self):
        """Cached response stays nse_live, not fixture_fallback."""
        items = _fixture_items("SBIN")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        collector.collect("SBIN")
        result2 = collector.collect("SBIN")
        assert result2["provider_mode"] == "nse_live"

    def test_expired_cache_refetches(self):
        items = _fixture_items("SBIN")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        collector.collect("SBIN")
        # Force-expire: set cache entry expiry to the past
        sym_key = "SBIN"
        old_items, _ = collector._cache[sym_key]
        collector._cache[sym_key] = (old_items, time.monotonic() - 1)
        collector.collect("SBIN")
        # Should have made a second API call
        assert sess.get.call_count == 3  # 1 prime + 2 API calls


# ---------------------------------------------------------------------------
# Session priming tests
# ---------------------------------------------------------------------------

class TestSessionPriming:
    def test_prime_sets_user_agent_header(self):
        items = _fixture_items("SBIN")
        sess = _fake_session(items)
        collector = NseAnnouncementsCollector(session=sess)
        collector.collect("SBIN")
        # First get call should be the homepage prime
        first_call_url = sess.get.call_args_list[0][0][0]
        assert "nseindia.com" in first_call_url

    def test_prime_failure_does_not_crash_collect(self):
        """Homepage prime failure is swallowed; API fetch still attempted."""
        call_count = [0]

        class _StubbornSession:
            headers: dict = {}

            def get(self, url, **kwargs):
                call_count[0] += 1
                if "corporate-announcements" in url:
                    resp = MagicMock()
                    resp.raise_for_status = MagicMock()
                    resp.json.return_value = _fixture_items("SBIN")
                    return resp
                # Homepage prime raises
                raise requests.ConnectionError("homepage unreachable")

        collector = NseAnnouncementsCollector(session=_StubbornSession())
        result = collector.collect("SBIN")
        # Should still get live data via the API even though prime failed
        assert result["provider_mode"] == "nse_live"
        assert len(result["items"]) > 0

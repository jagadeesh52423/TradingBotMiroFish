"""Offline unit tests for the pluggable sentiment engines.

No real Anthropic API calls — the client method `messages.create` is always
mocked. (BP-123 — never weaken a test to match a stub)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.nse_announcements.sentiment_analyzer import (
    AiSentimentAnalyzer,
    KeywordSentimentAnalyzer,
    SentimentResult,
    get_analyzer,
    label_from_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_use_response(score: float, confidence: float, reasoning: str) -> MagicMock:
    """Build a fake anthropic Message with a single emit_sentiment tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "emit_sentiment"
    block.input = {
        "sentiment_score": score,
        "confidence": confidence,
        "reasoning": reasoning,
    }
    resp = MagicMock()
    resp.content = [block]
    return resp


def _ai_analyzer_with_client(client: MagicMock, api_key: str | None = "sk-test") -> AiSentimentAnalyzer:
    """AiSentimentAnalyzer wired to a pre-built mock client (skips real construction)."""
    analyzer = AiSentimentAnalyzer(
        fallback=KeywordSentimentAnalyzer(),
        model="claude-haiku-4-5",
        api_key=api_key,
    )
    analyzer._client = client
    return analyzer


# ---------------------------------------------------------------------------
# 1. label_from_score boundaries
# ---------------------------------------------------------------------------

class TestLabelFromScore:
    def test_bullish_above_threshold(self):
        assert label_from_score(0.11) == "bullish"
        assert label_from_score(1.0) == "bullish"

    def test_bearish_below_threshold(self):
        assert label_from_score(-0.11) == "bearish"
        assert label_from_score(-1.0) == "bearish"

    def test_neutral_within_band(self):
        assert label_from_score(0.0) == "neutral"
        assert label_from_score(0.1) == "neutral"   # boundary: not > 0.1
        assert label_from_score(-0.1) == "neutral"  # boundary: not < -0.1


# ---------------------------------------------------------------------------
# 2. KeywordSentimentAnalyzer
# ---------------------------------------------------------------------------

class TestKeywordAnalyzer:
    def test_bullish_items(self):
        items = [{"attchmntText": "Company announces dividend and profit growth record earnings."}]
        result = KeywordSentimentAnalyzer().analyze(items)
        assert result.engine == "keyword"
        assert result.degraded is False
        assert result.sentiment_score > 0.0
        assert result.sentiment_label == "bullish"

    def test_bearish_items(self):
        items = [{"attchmntText": "Company receives penalty for fraud investigation."}]
        result = KeywordSentimentAnalyzer().analyze(items)
        assert result.sentiment_score < 0.0
        assert result.sentiment_label == "bearish"
        assert result.engine == "keyword"

    def test_neutral_items(self):
        items = [{"attchmntText": "Board meeting details of director appointment."}]
        result = KeywordSentimentAnalyzer().analyze(items)
        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_confidence_is_abs_score_proxy(self):
        items = [{"attchmntText": "dividend bonus growth profit earnings"}]
        result = KeywordSentimentAnalyzer().analyze(items)
        assert result.confidence == pytest.approx(min(1.0, abs(result.sentiment_score)))

    def test_reasoning_mentions_filing_count(self):
        items = [{"attchmntText": "profit"}, {"attchmntText": "growth"}]
        result = KeywordSentimentAnalyzer().analyze(items)
        assert "2 filing" in result.reasoning


# ---------------------------------------------------------------------------
# 3. AiSentimentAnalyzer — success path (mocked client)
# ---------------------------------------------------------------------------

class TestAiAnalyzerSuccess:
    def test_parsed_output_propagates(self):
        client = MagicMock()
        client.messages.create.return_value = _tool_use_response(0.8, 0.9, "Approved buyback is bullish.")
        analyzer = _ai_analyzer_with_client(client)

        result = analyzer.analyze([{"attchmntText": "The board approved the buyback proposal."}])

        assert result.engine == "ai"
        assert result.degraded is False
        assert result.sentiment_score == 0.8
        assert result.sentiment_label == "bullish"
        assert result.confidence == 0.9
        assert result.reasoning == "Approved buyback is bullish."
        client.messages.create.assert_called_once()

    def test_negative_score_labels_bearish(self):
        client = MagicMock()
        client.messages.create.return_value = _tool_use_response(-0.6, 0.7, "Rejected buyback is bearish.")
        analyzer = _ai_analyzer_with_client(client)

        result = analyzer.analyze([{"attchmntText": "The board rejected the buyback proposal."}])

        assert result.engine == "ai"
        assert result.sentiment_label == "bearish"


# ---------------------------------------------------------------------------
# 4. AiSentimentAnalyzer — no API key → degraded keyword, API NOT called
# ---------------------------------------------------------------------------

class TestAiAnalyzerNoKey:
    def test_no_key_degrades_to_keyword(self):
        client = MagicMock()
        analyzer = _ai_analyzer_with_client(client, api_key=None)

        items = [{"attchmntText": "Company announces dividend and profit growth."}]
        result = analyzer.analyze(items)
        kw = KeywordSentimentAnalyzer().analyze(items)

        assert result.engine == "keyword"
        assert result.degraded is True
        assert result.sentiment_score == kw.sentiment_score
        assert result.sentiment_label == kw.sentiment_label
        client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# 5. AiSentimentAnalyzer — API raises → degraded fallback, no escape
# ---------------------------------------------------------------------------

class TestAiAnalyzerApiError:
    def test_api_exception_degrades(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("api boom")
        analyzer = _ai_analyzer_with_client(client)

        items = [{"attchmntText": "Company announces dividend and profit growth."}]
        result = analyzer.analyze(items)  # must NOT raise
        kw = KeywordSentimentAnalyzer().analyze(items)

        assert result.engine == "keyword"
        assert result.degraded is True
        assert result.sentiment_score == kw.sentiment_score

    def test_missing_tool_use_block_degrades(self):
        client = MagicMock()
        bad = MagicMock()
        bad.content = []  # no tool_use block
        client.messages.create.return_value = bad
        analyzer = _ai_analyzer_with_client(client)

        result = analyzer.analyze([{"attchmntText": "profit growth"}])
        assert result.engine == "keyword"
        assert result.degraded is True


# ---------------------------------------------------------------------------
# 6. AiSentimentAnalyzer — empty items → neutral, API not called
# ---------------------------------------------------------------------------

class TestAiAnalyzerEmpty:
    def test_empty_items_neutral_no_call(self):
        client = MagicMock()
        analyzer = _ai_analyzer_with_client(client)

        result = analyzer.analyze([])

        assert result.engine == "ai"
        assert result.degraded is False
        assert result.sentiment_score == 0.0
        assert result.sentiment_label == "neutral"
        assert result.confidence == 0.0
        client.messages.create.assert_not_called()

    def test_items_without_text_neutral_no_call(self):
        client = MagicMock()
        analyzer = _ai_analyzer_with_client(client)

        result = analyzer.analyze([{"symbol": "SBIN"}, {"attchmntText": "   "}])

        assert result.engine == "ai"
        assert result.sentiment_label == "neutral"
        client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Registry resolution
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_resolve_keyword(self):
        analyzer = get_analyzer("keyword", {"nse": {}})
        assert isinstance(analyzer, KeywordSentimentAnalyzer)

    def test_resolve_ai(self):
        analyzer = get_analyzer("ai", {"nse": {"ai_model": "claude-haiku-4-5"}})
        assert isinstance(analyzer, AiSentimentAnalyzer)

    def test_unknown_engine_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown sentiment_engine 'bogus'"):
            get_analyzer("bogus", {"nse": {}})


# ---------------------------------------------------------------------------
# SentimentResult dataclass sanity
# ---------------------------------------------------------------------------

class TestSentimentResult:
    def test_degraded_defaults_false(self):
        r = SentimentResult(0.0, "neutral", 0.0, "x", "keyword")
        assert r.degraded is False

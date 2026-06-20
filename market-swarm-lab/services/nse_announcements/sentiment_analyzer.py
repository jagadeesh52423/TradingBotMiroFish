"""Sentiment analysis over NSE filing texts — pluggable engines.

# implement SentimentAnalyzer + register via @register_analyzer to add a new engine
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel, Field

from services.nse_announcements.nse_announcements_collector import (
    _DEFAULT_BEARISH_KW,
    _DEFAULT_BULLISH_KW,
    _score_sentiment,
)

_log = logging.getLogger(__name__)

_AI_MODEL_DEFAULT = "claude-haiku-4-5"
_MAX_PROMPT_CHARS = 6000
_AI_MAX_TOKENS = 512
_SENTIMENT_TOOL_NAME = "emit_sentiment"


@dataclass(frozen=True)
class SentimentResult:
    sentiment_score: float   # [-1, 1]
    sentiment_label: str     # "bullish" | "bearish" | "neutral"
    confidence: float        # [0, 1]
    reasoning: str           # human-readable justification
    engine: str              # engine that ACTUALLY produced this ("keyword" | "ai")
    degraded: bool = False   # True if "ai" was requested but it fell back to keyword


def label_from_score(score: float) -> str:
    if score > 0.1:
        return "bullish"
    if score < -0.1:
        return "bearish"
    return "neutral"


class SentimentAnalyzer(ABC):
    @abstractmethod
    def analyze(self, items: list[dict]) -> SentimentResult:
        """Score one symbol's filing items (each may have 'attchmntText')."""

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict) -> "SentimentAnalyzer":
        """Build an analyzer from the top-level nubra_config dict."""


_ANALYZER_REGISTRY: dict[str, type[SentimentAnalyzer]] = {}


def register_analyzer(name: str):
    def deco(cls):
        _ANALYZER_REGISTRY[name] = cls
        return cls
    return deco


def get_analyzer(name: str, config: dict) -> SentimentAnalyzer:
    try:
        cls = _ANALYZER_REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown sentiment_engine '{name}'. Known: {sorted(_ANALYZER_REGISTRY)}"
        )
    return cls.from_config(config)


def _keyword_sets(config: dict) -> tuple[frozenset[str], frozenset[str]]:
    nse_cfg = config.get("nse", {})
    raw_bull = nse_cfg.get("bullish_keywords")
    raw_bear = nse_cfg.get("bearish_keywords")
    bull = frozenset(raw_bull) if raw_bull is not None else _DEFAULT_BULLISH_KW
    bear = frozenset(raw_bear) if raw_bear is not None else _DEFAULT_BEARISH_KW
    return bull, bear


@register_analyzer("keyword")
class KeywordSentimentAnalyzer(SentimentAnalyzer):
    def __init__(
        self,
        bullish_keywords: frozenset[str] | None = None,
        bearish_keywords: frozenset[str] | None = None,
    ) -> None:
        self._bull = bullish_keywords if bullish_keywords is not None else _DEFAULT_BULLISH_KW
        self._bear = bearish_keywords if bearish_keywords is not None else _DEFAULT_BEARISH_KW

    @classmethod
    def from_config(cls, config: dict) -> "KeywordSentimentAnalyzer":
        bull, bear = _keyword_sets(config)
        return cls(bull, bear)

    def analyze(self, items: list[dict]) -> SentimentResult:
        score = _score_sentiment(items, self._bull, self._bear)
        return SentimentResult(
            sentiment_score=score,
            sentiment_label=label_from_score(score),
            confidence=min(1.0, abs(score)),
            reasoning=f"keyword sentiment over {len(items)} filing(s)",
            engine="keyword",
            degraded=False,
        )


class _AiOut(BaseModel):
    sentiment_score: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    reasoning: str


_SENTIMENT_TOOL = {
    "name": _SENTIMENT_TOOL_NAME,
    "description": "Emit a structured sentiment judgement for a set of NSE corporate filings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment_score": {
                "type": "number",
                "description": "Overall market sentiment from -1 (very bearish) to 1 (very bullish).",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in the score, 0 (none) to 1 (certain).",
            },
            "reasoning": {
                "type": "string",
                "description": "One- or two-sentence justification.",
            },
        },
        "required": ["sentiment_score", "confidence", "reasoning"],
    },
}

_PROMPT_HEADER = (
    "You are a financial analyst reading Indian-equity (NSE) corporate filings for one company. "
    "Judge the net market sentiment these filings imply for the stock. "
    "Consider intent, not just keywords — e.g. a REJECTED buyback is bearish, an APPROVED one bullish. "
    "Call the emit_sentiment tool with your judgement.\n\nFilings:\n"
)


@register_analyzer("ai")
class AiSentimentAnalyzer(SentimentAnalyzer):
    def __init__(
        self,
        fallback: KeywordSentimentAnalyzer,
        model: str = _AI_MODEL_DEFAULT,
        api_key: str | None = None,
        auth_token: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._fallback = fallback
        self._model = model
        self._api_key = api_key
        self._auth_token = auth_token
        self._base_url = base_url
        self._client = None
        self._logged_no_key = False

    @classmethod
    def from_config(cls, config: dict) -> "AiSentimentAnalyzer":
        _load_dotenv_quietly()
        fallback = KeywordSentimentAnalyzer.from_config(config)
        # env (proxy model) wins over config, which wins over the built-in default.
        model = (
            os.environ.get("ANTHROPIC_MODEL")
            or config.get("nse", {}).get("ai_model")
            or _AI_MODEL_DEFAULT
        )
        return cls(
            fallback,
            model,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )

    def analyze(self, items: list[dict]) -> SentimentResult:
        if not (self._api_key or self._auth_token):
            if not self._logged_no_key:
                _log.info("no ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN — AI sentiment degraded to keyword")
                self._logged_no_key = True
            return self._degraded(items)

        prompt = _build_prompt(items)
        if prompt is None:
            return SentimentResult(0.0, "neutral", 0.0, "no filings", "ai", degraded=False)

        try:
            out = self._call_ai(prompt)
        except Exception as exc:
            _log.warning("AI sentiment failed (%s) — degrading to keyword", exc)
            return self._degraded(items)

        return SentimentResult(
            sentiment_score=out.sentiment_score,
            sentiment_label=label_from_score(out.sentiment_score),
            confidence=out.confidence,
            reasoning=out.reasoning,
            engine="ai",
            degraded=False,
        )

    def _degraded(self, items: list[dict]) -> SentimentResult:
        kw = self._fallback.analyze(items)
        return SentimentResult(
            sentiment_score=kw.sentiment_score,
            sentiment_label=kw.sentiment_label,
            confidence=kw.confidence,
            reasoning=kw.reasoning,
            engine="keyword",
            degraded=True,
        )

    def _call_ai(self, prompt: str) -> _AiOut:
        client = self._get_client()
        resp = client.messages.create(
            model=self._model,
            max_tokens=_AI_MAX_TOKENS,
            tools=[_SENTIMENT_TOOL],
            tool_choice={"type": "tool", "name": _SENTIMENT_TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _SENTIMENT_TOOL_NAME:
                return _AiOut(**block.input)
        raise ValueError("Claude returned no emit_sentiment tool_use block")

    def _get_client(self):
        if self._client is None:
            import anthropic
            kwargs: dict = {}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            # Prefer Bearer (auth_token) — that's what the LiteLLM proxy wants.
            if self._auth_token:
                kwargs["auth_token"] = self._auth_token
            elif self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client


def _build_prompt(items: list[dict]) -> str | None:
    texts = [t for item in items if (t := (item.get("attchmntText") or "").strip())]
    if not texts:
        return None
    body = "\n\n".join(texts)[:_MAX_PROMPT_CHARS]
    return _PROMPT_HEADER + body


def _load_dotenv_quietly() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

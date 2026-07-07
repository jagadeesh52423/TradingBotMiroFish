"""AI catalyst-quality scorer over a single NSE announcement text.

Judges the directional impact of ONE corporate announcement on a ~20-day swing
via the LiteLLM proxy (same anthropic-client pattern as
services/nse_announcements/sentiment_analyzer.AiSentimentAnalyzer). Falls back to
the keyword scorer when disabled, when creds are absent, or when the proxy fails.

PIT note: board OUTCOME text publishes EOD after the meeting, so a score from it
can only gate a NEXT-day entry. This module scores text; the caller owns the lag.

# OFF by default — set config["nse"]["ai_catalyst"]["enabled"]=true to score via AI.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from services.nse_announcements.nse_announcements_collector import (
    _DEFAULT_BEARISH_KW,
    _DEFAULT_BULLISH_KW,
    _score_sentiment,
)
from services.nse_announcements.sentiment_analyzer import label_from_score

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOTENV = _REPO_ROOT / ".env"
_DEFAULT_CACHE = _REPO_ROOT / "services" / "backtest" / ".catalyst_ai_cache.json"

_AI_MODEL_DEFAULT = "claude-sonnet-4-5-20250929"
_MAX_PROMPT_CHARS = 6000
_AI_MAX_TOKENS = 512
_CATALYST_TOOL_NAME = "score_catalyst"
_DIRECTIONS = ("bullish", "neutral", "bearish")

# returned-dict keys
_K_DIRECTION = "direction"
_K_STRENGTH = "strength"
_K_REASON = "reason"
_K_ENGINE = "engine"
_K_DEGRADED = "degraded"

_CATALYST_TOOL = {
    "name": _CATALYST_TOOL_NAME,
    "description": "Emit a structured directional judgement for one NSE corporate announcement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": list(_DIRECTIONS),
                "description": "Directional impact on the stock over a ~20-day swing.",
            },
            "strength": {
                "type": "number",
                "description": "Conviction of the directional ~20-day move, 0 (none) to 1 (certain).",
            },
            "reason": {
                "type": "string",
                "description": "One- or two-sentence justification.",
            },
        },
        "required": ["direction", "strength", "reason"],
    },
}

_PROMPT_HEADER = (
    "You are a financial analyst reading one NSE corporate announcement. "
    "Judge its directional impact on the stock over a ~20-day swing. "
    "Distinguish substantive catalysts from procedural noise (newspaper publications, "
    "routine compliance = neutral 0.0-0.1). Call score_catalyst.\n\nAnnouncement:\n"
)


def _load_dotenv_manually() -> None:
    """Populate os.environ from .env (dotenv does NOT populate vars in this repo).

    Only fills keys that are unset, so a real environment always wins. Never logs values.
    """
    if not _DOTENV.exists():
        return
    for raw in _DOTENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


class AiCatalystScorer:
    """Scores one announcement's directional catalyst quality (AI proxy + keyword fallback)."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        model: str = _AI_MODEL_DEFAULT,
        auth_token: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        bullish_keywords: frozenset[str] | None = None,
        bearish_keywords: frozenset[str] | None = None,
        cache_path: Path | None = None,
        client=None,
    ) -> None:
        self._enabled = enabled
        self._model = model
        self._auth_token = auth_token
        self._api_key = api_key
        self._base_url = base_url
        self._bull = bullish_keywords if bullish_keywords is not None else _DEFAULT_BULLISH_KW
        self._bear = bearish_keywords if bearish_keywords is not None else _DEFAULT_BEARISH_KW
        self._cache_path = cache_path if cache_path is not None else _DEFAULT_CACHE
        self._client = client
        self._cache: dict[str, dict] | None = None
        self._logged_no_key = False

    @classmethod
    def from_config(cls, config: dict) -> "AiCatalystScorer":
        _load_dotenv_manually()
        nse_cfg = config.get("nse", {})
        ai_cfg = nse_cfg.get("ai_catalyst", {})
        model = (
            os.environ.get("ANTHROPIC_MODEL")
            or ai_cfg.get("model")
            or nse_cfg.get("ai_model")
            or _AI_MODEL_DEFAULT
        )
        raw_bull = nse_cfg.get("bullish_keywords")
        raw_bear = nse_cfg.get("bearish_keywords")
        cache = ai_cfg.get("cache_path")
        return cls(
            enabled=bool(ai_cfg.get("enabled", False)),
            model=model,
            auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            bullish_keywords=frozenset(raw_bull) if raw_bull is not None else None,
            bearish_keywords=frozenset(raw_bear) if raw_bear is not None else None,
            cache_path=Path(cache) if cache else None,
        )

    # ------------------------------------------------------------------ public

    def score_text(self, text: str) -> dict:
        """Score one announcement's text -> {direction, strength, reason, engine, degraded}."""
        text = (text or "").strip()
        if not text:
            return {_K_DIRECTION: "neutral", _K_STRENGTH: 0.0, _K_REASON: "empty text",
                    _K_ENGINE: "keyword", _K_DEGRADED: False}

        if not self._enabled:
            return self._keyword(text, degraded=False)

        if not (self._auth_token or self._api_key or self._client):
            if not self._logged_no_key:
                _log.info("no ANTHROPIC creds — AI catalyst scoring degraded to keyword")
                self._logged_no_key = True
            return self._keyword(text, degraded=True)

        cached = self._cache_get(text)
        if cached is not None:
            return {**cached, _K_ENGINE: "ai", _K_DEGRADED: False}

        try:
            out = self._call_ai(text)
        except Exception as exc:
            _log.warning("AI catalyst scoring failed (%s) — degrading to keyword", exc)
            return self._keyword(text, degraded=True)

        self._cache_put(text, out)
        return {**out, _K_ENGINE: "ai", _K_DEGRADED: False}

    # ----------------------------------------------------------------- private

    def _keyword(self, text: str, degraded: bool) -> dict:
        score = _score_sentiment([{"attchmntText": text}], self._bull, self._bear)
        return {
            _K_DIRECTION: label_from_score(score),
            _K_STRENGTH: min(1.0, abs(score)),
            _K_REASON: "keyword fallback",
            _K_ENGINE: "keyword",
            _K_DEGRADED: degraded,
        }

    def _call_ai(self, text: str) -> dict:
        client = self._get_client()
        prompt = _PROMPT_HEADER + text[:_MAX_PROMPT_CHARS]
        resp = client.messages.create(
            model=self._model,
            max_tokens=_AI_MAX_TOKENS,
            tools=[_CATALYST_TOOL],
            tool_choice={"type": "tool", "name": _CATALYST_TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _CATALYST_TOOL_NAME:
                return _validate_out(block.input)
        raise ValueError("Claude returned no score_catalyst tool_use block")

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

    # ------------------------------------------------------------------- cache

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256((self._model + "\n" + text[:_MAX_PROMPT_CHARS]).encode("utf-8")).hexdigest()

    def _load_cache(self) -> dict[str, dict]:
        if self._cache is None:
            try:
                self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                self._cache = {}
        return self._cache

    def _cache_get(self, text: str) -> dict | None:
        return self._load_cache().get(self._cache_key(text))

    def _cache_put(self, text: str, out: dict) -> None:
        cache = self._load_cache()
        cache[self._cache_key(text)] = out
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(cache), encoding="utf-8")


def _validate_out(raw: dict) -> dict:
    direction = raw.get("direction")
    if direction not in _DIRECTIONS:
        raise ValueError(f"bad direction {direction!r}")
    strength = max(0.0, min(1.0, float(raw.get("strength", 0.0))))
    return {_K_DIRECTION: direction, _K_STRENGTH: strength, _K_REASON: str(raw.get("reason", ""))}


def _demo() -> None:
    """Offline self-check with a fake client — NO network. ponytail: one assert per case."""

    class _Block:
        type = "tool_use"
        name = _CATALYST_TOOL_NAME

        def __init__(self, payload):
            self.input = payload

    class _Resp:
        def __init__(self, payload):
            self.content = [_Block(payload)]

    class _FakeClient:
        """Returns bullish for outcome text, neutral for a newspaper publication."""

        class messages:  # noqa: N801 - mirrors anthropic client attribute
            @staticmethod
            def create(*, messages, **_):
                # Inspect only the announcement body (after the fixed prompt header).
                body = messages[0]["content"].split("Announcement:\n", 1)[-1].lower()
                if "approved" in body or "dividend" in body:
                    return _Resp({"direction": "bullish", "strength": 0.55, "reason": "board approved outcome"})
                return _Resp({"direction": "neutral", "strength": 0.10, "reason": "procedural"})

    scorer = AiCatalystScorer(enabled=True, auth_token="x", client=_FakeClient(),
                              cache_path=Path("/tmp/.catalyst_ai_demo_cache.json"))
    Path("/tmp/.catalyst_ai_demo_cache.json").unlink(missing_ok=True)

    bull = scorer.score_text("Outcome of Board Meeting: dividend and buyback approved.")
    assert bull[_K_DIRECTION] == "bullish" and bull[_K_ENGINE] == "ai" and not bull[_K_DEGRADED], bull

    neut = scorer.score_text("Newspaper Publication of financial results in the press.")
    assert neut[_K_DIRECTION] == "neutral" and neut[_K_STRENGTH] <= 0.1, neut

    # cache round-trip: second call hits disk, no re-invocation needed.
    assert scorer.score_text("Outcome of Board Meeting: dividend and buyback approved.")[_K_DIRECTION] == "bullish"

    # OFF by default -> keyword engine, not degraded.
    off = AiCatalystScorer(enabled=False).score_text("dividend approved")
    assert off[_K_ENGINE] == "keyword" and not off[_K_DEGRADED], off

    # creds absent while enabled -> keyword, degraded=True.
    degraded = AiCatalystScorer(enabled=True).score_text("penalty imposed by regulator")
    assert degraded[_K_ENGINE] == "keyword" and degraded[_K_DEGRADED], degraded

    print("ai_catalyst_scorer self-check OK:", bull[_K_DIRECTION], neut[_K_DIRECTION])


if __name__ == "__main__":
    _demo()

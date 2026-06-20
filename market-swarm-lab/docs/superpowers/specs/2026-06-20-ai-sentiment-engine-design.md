# AI Sentiment Engine — Design Spec

**Goal:** Add an AI-powered sentiment engine that reads NSE filing texts with real comprehension (Claude Haiku), selectable by config alongside the existing keyword scorer. Key-optional: gracefully falls back to the keyword scorer when `ANTHROPIC_API_KEY` is absent or the API errors.

**Why:** The keyword scorer (even with word-boundary matching) only pattern-matches; it can't understand "the board *rejected* the buyback proposal" vs "the board *approved* the buyback." An LLM reading the filing summary text captures intent.

**Extensibility contract:** New sentiment engines implement `SentimentAnalyzer` and register in `_ANALYZER_REGISTRY`. No collector edits needed to add a third engine — `from_config` resolves by name.

---

## New file: `services/nse_announcements/sentiment_analyzer.py`

```python
"""Sentiment analysis over NSE filing texts — pluggable engines.

# implement SentimentAnalyzer + register via @register_analyzer to add a new engine
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class SentimentResult:
    sentiment_score: float   # [-1, 1]
    sentiment_label: str     # "bullish" | "bearish" | "neutral"
    confidence: float        # [0, 1]
    reasoning: str           # human-readable justification
    engine: str              # engine that ACTUALLY produced this ("keyword" | "ai")
    degraded: bool = False   # True if "ai" was requested but it fell back to keyword
```

### Shared label helper (single source of truth — both engines use it)

```python
def label_from_score(score: float) -> str:
    if score > 0.1:
        return "bullish"
    if score < -0.1:
        return "bearish"
    return "neutral"
```

### Interface + registry

```python
class SentimentAnalyzer(ABC):
    @abstractmethod
    def analyze(self, items: list[dict]) -> SentimentResult:
        """Score one symbol's filing items (each may have 'attchmntText')."""

_ANALYZER_REGISTRY: dict[str, type[SentimentAnalyzer]] = {}

def register_analyzer(name: str):
    def deco(cls): _ANALYZER_REGISTRY[name] = cls; return cls
    return deco

def get_analyzer(name: str, config: dict) -> SentimentAnalyzer:
    try:
        cls = _ANALYZER_REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown sentiment_engine '{name}'. "
                         f"Known: {sorted(_ANALYZER_REGISTRY)}")
    return cls.from_config(config)
```

Each analyzer gets a `@classmethod from_config(cls, config) -> SentimentAnalyzer`.

### KeywordSentimentAnalyzer (engine="keyword")

- `from_config` reads `config["nse"]["bullish_keywords"]/["bearish_keywords"]` (same as collector today).
- `analyze`: `score = _score_sentiment(items, bull, bear)` (reuse the existing module helper in the collector — import it, do NOT duplicate the regex logic). `label = label_from_score(score)`. `confidence = min(1.0, abs(score))` (simple proxy). `reasoning = "keyword sentiment over {n} filing(s)"`. `engine="keyword"`, `degraded=False`.

### AiSentimentAnalyzer (engine="ai", with keyword fallback)

- `from_config` builds and HOLDS a `KeywordSentimentAnalyzer` for fallback, reads model id from `config["nse"].get("ai_model", "claude-haiku-4-5")`, and reads the API key from `os.environ.get("ANTHROPIC_API_KEY")` (optionally load `.env` first via python-dotenv **inside a try/except ImportError** — do not add a hard dependency).
- `analyze`:
  1. If no API key → return the keyword analyzer's result but with `engine="keyword"`, `degraded=True`. Log once at INFO: "ANTHROPIC_API_KEY absent — AI sentiment degraded to keyword".
  2. Build the prompt from the filing texts (join each item's `attchmntText`, cap total chars e.g. 6000 to bound cost). If there are zero texts → neutral `SentimentResult(0.0, "neutral", 0.0, "no filings", "ai", degraded=False)` WITHOUT calling the API.
  3. Call Claude with a Pydantic structured-output schema:
     ```python
     class _AiOut(BaseModel):
         sentiment_score: float = Field(ge=-1, le=1)
         confidence: float = Field(ge=0, le=1)
         reasoning: str
     ```
     Use `model="claude-haiku-4-5"`, a small `max_tokens` (e.g. 512). **Haiku has no thinking/effort param — do not pass `thinking`.**
     **Verify the exact structured-output call against the installed anthropic SDK (0.57.1)** — read the `claude-api` skill's `python/` docs (or the SDK) for the correct binding (`client.messages.parse(..., output_format=_AiOut)` vs `messages.create(..., output_config={"format": {...}})`). Do NOT guess the method name/signature — confirm it. Whatever method you call is what the tests mock.
  4. On success → `score = out.sentiment_score`, `label = label_from_score(score)`, `confidence=out.confidence`, `reasoning=out.reasoning`, `engine="ai"`, `degraded=False`.
  5. On ANY exception from the API (typed anthropic exceptions or otherwise) → log a WARNING with the error, return the keyword analyzer's result with `engine="keyword"`, `degraded=True`. No exception escapes `analyze()`.

The Anthropic client should be lazily constructed (constructor stores key/model; client built on first real call) so that constructing an `AiSentimentAnalyzer` never requires a key or network — important for tests and for the no-key path.

---

## Collector changes (`nse_announcements_collector.py`)

- `__init__`: accept optional `analyzer: SentimentAnalyzer | None`. If None, default to `KeywordSentimentAnalyzer` built from the existing default keyword sets (preserves today's behavior exactly).
- `from_config`: read `engine = nse_cfg.get("sentiment_engine", "keyword")`; `analyzer = get_analyzer(engine, config)`. Pass to constructor. (Keyword sets still read for the keyword analyzer via its own from_config.)
- `collect()`: replace the inline `_score_sentiment` + label block with:
  ```python
  result = self._analyzer.analyze(items)
  ```
  and populate the returned dict from `result`: `sentiment_score`, `sentiment_label`, plus NEW keys `sentiment_confidence`, `sentiment_reasoning`, `sentiment_engine`. Add to `source_audit["nse_announcements"]`: `"engine": result.engine`, `"degraded": result.degraded`.
- Keep `_score_sentiment` as a module-level helper (the keyword analyzer imports/uses it). Existing collector tests that call `_score_sentiment` directly stay green.

**Backward-compat:** existing return keys unchanged; only additive new keys. Downstream (`run_nubra_equity._build_risk_audit`, signal strategies) keeps working. `NewsOnlySignalStrategy` may optionally read `sentiment_reasoning` later — not required here.

---

## Config (`config/nubra_config.json`)

Under `"nse"`: add `"sentiment_engine": "keyword"` (default keeps current behavior) and `"ai_model": "claude-haiku-4-5"`.

---

## Tests (`tests/nubra/test_sentiment_analyzer.py` + additions to `test_nse_announcements_collector.py`)

**No real API calls — mock the Anthropic client/method.**

1. `label_from_score` boundaries (>0.1, <-0.1, between → neutral).
2. KeywordSentimentAnalyzer: sample bullish/bearish/neutral items → expected score+label, engine="keyword".
3. AiSentimentAnalyzer, mocked client returns a parsed `_AiOut` → score/label/confidence/reasoning propagate, engine="ai", degraded=False.
4. AiSentimentAnalyzer, no `ANTHROPIC_API_KEY` (monkeypatch env) → engine="keyword", degraded=True, score equals keyword score; client method NOT called.
5. AiSentimentAnalyzer, mocked client raises (e.g. anthropic.APIError) → degraded fallback to keyword, no exception escapes.
6. AiSentimentAnalyzer, empty items → neutral, API not called.
7. `get_analyzer("keyword"/"ai", cfg)` resolve; unknown name → ValueError.
8. Collector with an injected fake analyzer (or sentiment_engine="ai" + mocked client) → returned dict has sentiment_confidence/sentiment_reasoning/sentiment_engine and source_audit.engine/degraded.
9. Collector default (no sentiment_engine) → keyword engine, existing keys unchanged.

Run: `python3.11 -m pytest tests/nubra/ -q` — all green (existing + new).

---

## Out of scope (do NOT build)
- Full PDF fetch (we analyze the `attchmntText` summary the API returns).
- Batching across symbols (one call per symbol is fine for 48 names on Haiku).
- Loading `.env` as a hard dependency (try/except python-dotenv only).
- Touching `.env` / `auth_data.db*` — never stage these.

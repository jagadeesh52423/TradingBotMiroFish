# TradingBot Phase 3 — Providers (Market, News, Discovery) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the IO layer of `~/Code/own/TradingBot` — the async Fyers market provider (rate-limited via the Phase-2 TokenBucket), the six news sources + sentiment + aggregator, and catalyst discovery + the surveillance/liquidity guard — by porting the battle-tested MiroFish code behind the new Protocol interfaces.

**Architecture:** Everything external sits behind `providers/`. The Fyers SDK and NSE `requests` calls are **synchronous**; async methods wrap each blocking call in `asyncio.to_thread` after `await limiter.acquire()` (TokenBucket). Fyers 429s arrive as 200-bodies (`{"s":"error","code":429}`) and are retried with async backoff. News sources keep their primed-session/fixture-fallback/fail-safe design; discovery and the guard stay synchronous (they run once per pipeline run — the pipeline wraps them). Reference spec: `docs/superpowers/specs/2026-07-07-tradingbot-clean-extract-design.md` (in the MiroFish repo).

**Tech Stack:** Python 3.11, `asyncio` + `asyncio.to_thread`, `requests` (sync internals), `tenacity`, `fyers-apiv3` (lazy import), `pydantic` v2, `pytest` + `pytest-asyncio`.

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. The MiroFish repo (`/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab`, called **SRC** below) is **read-only port source** — never modify it.
- Tests never hit the network: fakes for the Fyers SDK, fixture files for news/discovery. (Optional live smoke tests must be skipped unless `LIVE_TESTS=1`.)
- Task 1 is sequential (shared files). After it, **Group A (Tasks 2–3), Group B (Tasks 4–7), Group C (Tasks 8–9) touch disjoint files and may run as parallel coder streams.** Two agents must never write the same file.
- `domain/` stays stdlib-only. `Decimal` for prices (`ltp`); OHLCV bar series stay `float` (series data, not money — matches the reviewed Phase-1 convention for `closes`).
- Run tests with `cd /Users/jagadeeshpulamarasetti/Code/own/TradingBot && uv run --extra dev pytest -q`; suite + `uv run --extra dev ruff check src tests` must be green at the end of every task. Commit after every task.
- When a step says **PORT** a file: copy the logic from the given SRC path, apply only the listed transformations (async wrap, import paths, typed settings, domain models). Keep names/behavior otherwise identical — the SRC code is tested and reviewed; do not "improve" it beyond the listed changes. Note any forced deviation in the task's commit message.

---

## File Structure (Phase 3)

```
src/tradingbot/
├── domain/models.py                   # MODIFY: + Bar, NewsItem, SentimentResult
├── config/settings.py                 # MODIFY: + FyersSettings, SentimentSettings, NewsSourcesSettings,
│                                      #   discovery fields; RateLimitSettings gt=0; load_config mapping
├── config/paths.py                    # CREATE: data_dir()/fixtures_dir() helpers
├── providers/
│   ├── market/
│   │   ├── __init__.py
│   │   ├── base.py                    # MarketDataProvider Protocol + async retry/limit machinery
│   │   └── fyers.py                   # FyersProvider (async port of SRC fyers_data_provider.py)
│   ├── news/
│   │   ├── __init__.py
│   │   ├── base.py                    # NewsSource Protocol + PrimedNseSession mixin
│   │   ├── sentiment.py               # keyword/ai/ollama analyzers + registry (port)
│   │   ├── nse_announcements.py       # port ×6 sources
│   │   ├── google_news.py
│   │   ├── usfda.py
│   │   ├── insider.py
│   │   ├── pib.py
│   │   ├── reddit.py
│   │   └── aggregator.py              # NewsAggregator (union → one sentiment call)
│   └── discovery/
│       ├── __init__.py
│       ├── event_calendar.py          # port SRC nse_event_calendar_collector.py
│       ├── catalyst.py                # CatalystDiscovery → dict[str, Catalyst]
│       └── guard.py                   # SurveillanceLiquidityGuard (+ top_by_turnover)
data/fixtures/                         # runtime fallback fixtures (copied from SRC)
│   ├── news/  (nse_announcements_*.json, google_news_RELIANCE.xml, usfda_SUNPHARMA.json,
│   │           insider_SUNPHARMA.json, reddit_RELIANCE.json)
│   └── discovery/ (nse_event_calendar.json)
tests/providers/market/  news/  discovery/   # per-module tests (ported + new async)
```

---

## Task 1: Domain + config extensions (sequential — do first)

**Files:**
- Modify: `src/tradingbot/domain/models.py`
- Modify: `src/tradingbot/config/settings.py`
- Create: `src/tradingbot/config/paths.py`
- Modify: `pyproject.toml` (deps)
- Modify: `src/tradingbot/providers/ratelimit.py` (+ `RateLimiter` Protocol)
- Test: `tests/domain/test_models.py` (append), `tests/config/test_settings.py` (append), `tests/providers/test_ratelimit.py` (append the Protocol-satisfaction test)

**Interfaces:**
- Consumes: Phase 1–2 domain/config.
- Produces (used by every later task):
  - `Bar(timestamp_ms: int, open: float, high: float, low: float, close: float, volume: float)` (frozen)
  - `NewsItem(text: str, source: str, title: str | None, link: str | None, date: str | None)` (frozen)
  - `SentimentResult(score: float, label: str, confidence: float, engine: str, degraded: bool, reasoning: str)` (frozen)
  - `FyersSettings(client_id_env: str = "FYERS_CLIENT_ID", access_token_env: str = "FYERS_ACCESS_TOKEN")`
  - `SentimentSettings(engine: str = "keyword", ollama_model: str = "qwen3:8b", ollama_host: str = "http://localhost:11434", ai_model: str = "claude-haiku-4-5", bullish_keywords: list[str] | None = None, bearish_keywords: list[str] | None = None)`
  - `NewsSourcesSettings(google: bool = True, usfda: bool = True, insider: bool = True, pib: bool = True, reddit: bool = True, usfda_symbol_map: dict[str, str] = {}, pib_symbol_map: dict[str, list[str]] = {}, reddit_subreddits: list[str] = [...defaults...])`
  - `DiscoverySettings` gains: `lookahead_days: int = 10`, `lookback_days: int = 3`, `bhavcopy_lookback: int = 6`
  - `RateLimitSettings.refill_per_sec` gains `Field(gt=0)` (reviewer hardening note from Phase 2)
  - `Settings` gains default instances: `fyers: FyersSettings = FyersSettings()`, `sentiment: SentimentSettings = SentimentSettings()`, `news: NewsSourcesSettings = NewsSourcesSettings()` (matching the foundation convention, so `Settings()` constructs bare)
  - `load_config` additionally maps the nubra shape: `nse.sentiment_engine → sentiment.engine`, `nse.ollama_model/ollama_host`, `news.<src>.enabled → news.<src>`, `news.usfda.symbol_map`, `news.pib.symbol_map`, `news.reddit.subreddits`
  - `config/paths.py`: `data_dir() -> Path` (repo `data/`), `fixtures_dir(*parts) -> Path`
  - `pyproject.toml` deps add: `requests>=2.31`, `tenacity>=8.2`, `python-dotenv>=1.0`, `fyers-apiv3>=3.0`
  - `providers/ratelimit.py` gains `RateLimiter(Protocol)` (`@runtime_checkable`, `async acquire() -> None`) — the seam the async call machinery and news sources depend on

- [ ] **Step 1: Append failing domain tests** to `tests/domain/test_models.py`:

```python
def test_bar_and_news_item_are_frozen_value_objects():
    from tradingbot.domain.models import Bar, NewsItem, SentimentResult
    b = Bar(timestamp_ms=1, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)
    n = NewsItem(text="RELIANCE wins order", source="google_news", title="t", link=None, date=None)
    s = SentimentResult(score=0.4, label="bullish", confidence=0.4, engine="keyword",
                        degraded=False, reasoning="2 bullish keywords")
    import dataclasses, pytest
    for obj, field, val in ((b, "close", 9.9), (n, "text", "x"), (s, "score", 0.0)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, field, val)
```

- [ ] **Step 2: Append failing config tests** to `tests/config/test_settings.py`:

```python
def test_phase3_settings_defaults_and_mapping():
    from tradingbot.config.settings import Settings, load_config
    s = Settings()
    assert s.sentiment.engine == "keyword" and s.news.google is True
    assert s.discovery.lookahead_days == 10
    raw = {"nse": {"sentiment_engine": "ollama", "ollama_model": "qwen3:8b"},
           "news": {"google": {"enabled": False}, "usfda": {"enabled": True, "symbol_map": {"SUNPHARMA": "Sun Pharmaceutical"}}}}
    m = load_config(raw)
    assert m.sentiment.engine == "ollama" and m.news.google is False
    assert m.news.usfda_symbol_map == {"SUNPHARMA": "Sun Pharmaceutical"}


def test_refill_rate_must_be_positive():
    import pytest
    from tradingbot.config.settings import RateLimitSettings
    with pytest.raises(Exception):
        RateLimitSettings(refill_per_sec=0)
```

- [ ] **Step 3: Run both test files — expect the new tests to FAIL** (`ImportError`/`ValidationError` not raised).
- [ ] **Step 4: Implement.** Add the three frozen dataclasses to `domain/models.py` (stdlib only). Extend `config/settings.py` per the Interfaces block — `load_config` becomes:

```python
def load_config(data: dict) -> Settings:
    data = dict(data or {})
    nse = data.get("nse", {}) or {}
    sentiment = {
        "engine": nse.get("sentiment_engine", "keyword"),
        "ollama_model": nse.get("ollama_model", "qwen3:8b"),
        "ollama_host": nse.get("ollama_host", "http://localhost:11434"),
        "ai_model": nse.get("ai_model", "claude-haiku-4-5"),
        "bullish_keywords": nse.get("bullish_keywords"),
        "bearish_keywords": nse.get("bearish_keywords"),
    }
    raw_news = data.get("news", {}) or {}
    def _enabled(key: str, default: bool = True) -> bool:
        v = raw_news.get(key)
        return bool(v.get("enabled", default)) if isinstance(v, dict) else default
    news = {
        "google": _enabled("google"), "usfda": _enabled("usfda"), "insider": _enabled("insider"),
        "pib": _enabled("pib"), "reddit": _enabled("reddit"),
        "usfda_symbol_map": (raw_news.get("usfda") or {}).get("symbol_map", {}) if isinstance(raw_news.get("usfda"), dict) else {},
        "pib_symbol_map": (raw_news.get("pib") or {}).get("symbol_map", {}) if isinstance(raw_news.get("pib"), dict) else {},
    }
    if isinstance(raw_news.get("reddit"), dict) and raw_news["reddit"].get("subreddits"):
        news["reddit_subreddits"] = raw_news["reddit"]["subreddits"]
    merged = {**data, "sentiment": {**sentiment, **data.get("sentiment", {})}}
    merged["news"] = news            # Settings.news is NewsSourcesSettings
    return Settings.model_validate(merged)
```

  `config/paths.py`:

```python
from __future__ import annotations
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

def data_dir() -> Path:
    return _REPO_ROOT / "data"

def fixtures_dir(*parts: str) -> Path:
    return data_dir().joinpath("fixtures", *parts)
```

  `pyproject.toml`: add the four deps to `[project].dependencies`.
- [ ] **Step 5: Add the `RateLimiter` Protocol to `providers/ratelimit.py`.** Append (with `from typing import Protocol, runtime_checkable`):

```python
@runtime_checkable
class RateLimiter(Protocol):
    async def acquire(self) -> None: ...
```

  Then add a one-line test asserting the Phase-2 `TokenBucket` satisfies it (isinstance via `runtime_checkable`) — e.g. `assert isinstance(TokenBucket(capacity=1, refill_per_sec=1.0), RateLimiter)`.
- [ ] **Step 6: Run full suite — all green** (`uv run --extra dev pytest -q`). Ruff clean.
- [ ] **Step 7: Commit** — `feat(domain,config): Bar/NewsItem/SentimentResult + Phase-3 settings and paths`

---

## GROUP A — Market provider (parallel-safe with B and C)

## Task 2: `providers/market/base.py` — Protocol + async call machinery

**Files:**
- Create: `src/tradingbot/providers/market/__init__.py` (empty), `src/tradingbot/providers/market/base.py`
- Test: `tests/providers/market/__init__.py` (empty), `tests/providers/market/test_base.py`

**Interfaces:**
- Consumes: `TokenBucket` + `RateLimiter` (Phase 2), `Bar`, `Circuit`, `OptionSnapshot` (domain).
- Produces:
  - `class MarketDataProvider(Protocol)` with `async price(sym) -> Decimal`, `async ohlcv(sym, lookback: int, interval: str = "1d") -> list[Bar]`, `async circuit(sym) -> Circuit | None`, `async options(sym) -> OptionSnapshot | None`
  - `def is_rate_limited(resp: object) -> bool` — Fyers 200-body 429 detection (port of SRC `_is_rate_limited`)
  - `async def acall(limiter: RateLimiter, fn, *args, retries: int = 5, backoff: float = 1.5, **kwargs)` — `await limiter.acquire()` → `asyncio.to_thread(fn, ...)` → if `is_rate_limited(resp)`: async exponential backoff and retry (re-acquiring each attempt); returns the last body after exhausting retries (caller fail-softs).

- [ ] **Step 1: Write failing tests** — `tests/providers/market/test_base.py`:

```python
import asyncio
import pytest
from tradingbot.providers.market.base import acall, is_rate_limited
from tradingbot.providers.ratelimit import TokenBucket


def test_is_rate_limited_variants():
    assert is_rate_limited({"s": "error", "code": 429})
    assert is_rate_limited({"s": "error", "message": "request limit reached"})
    assert not is_rate_limited({"s": "ok", "d": []})
    assert not is_rate_limited(None)


@pytest.mark.asyncio
async def test_acall_retries_then_succeeds():
    bucket = TokenBucket(capacity=100, refill_per_sec=1000.0)
    calls = {"n": 0}
    def flaky(x):
        calls["n"] += 1
        return {"s": "error", "code": 429} if calls["n"] < 3 else {"s": "ok", "v": x}
    out = await acall(bucket, flaky, 42, retries=5, backoff=0.001)
    assert out == {"s": "ok", "v": 42} and calls["n"] == 3


@pytest.mark.asyncio
async def test_acall_returns_last_body_when_exhausted():
    bucket = TokenBucket(capacity=100, refill_per_sec=1000.0)
    out = await acall(bucket, lambda: {"s": "error", "code": 429}, retries=2, backoff=0.001)
    assert is_rate_limited(out)
```

- [ ] **Step 2: Run — expect FAIL** (module missing).
- [ ] **Step 3: Implement `base.py`:**

```python
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Protocol

from tradingbot.domain.models import Bar, Circuit, OptionSnapshot
from tradingbot.providers.ratelimit import RateLimiter


class MarketDataProvider(Protocol):
    async def price(self, symbol: str) -> Decimal: ...
    async def ohlcv(self, symbol: str, lookback: int, interval: str = "1d") -> list[Bar]: ...
    async def circuit(self, symbol: str) -> Circuit | None: ...
    async def options(self, symbol: str) -> OptionSnapshot | None: ...


def is_rate_limited(resp: object) -> bool:
    """Fyers returns rate-limit hits as a 200 body {"s":"error","code":429,...} — not an HTTP
    error — so requests/tenacity never retry them; detect the body explicitly."""
    if not isinstance(resp, dict) or resp.get("s") != "error":
        return False
    if resp.get("code") == 429:
        return True
    return "limit" in str(resp.get("message", "")).lower()


async def acall(limiter: RateLimiter, fn, *args, retries: int = 5, backoff: float = 1.5, **kwargs):
    """Rate-gated async wrapper for a SYNC SDK call: acquire a token, run the blocking call in
    a thread, retry 429 bodies with exponential async backoff (re-acquiring each attempt).
    Returns the last body when retries are exhausted — callers fail-soft on it."""
    last = None
    for attempt in range(retries):
        await limiter.acquire()
        resp = await asyncio.to_thread(fn, *args, **kwargs)
        if not is_rate_limited(resp):
            return resp
        last = resp
        if attempt < retries - 1:
            await asyncio.sleep(backoff * (2 ** attempt))
    return last
```

- [ ] **Step 4: Run — 3 tests PASS.** Full suite green.
- [ ] **Step 5: Commit** — `feat(market): MarketDataProvider protocol + rate-gated async call machinery`

---

## Task 3: `providers/market/fyers.py` — async FyersProvider (PORT)

**Files:**
- Create: `src/tradingbot/providers/market/fyers.py`
- Test: `tests/providers/market/test_fyers.py`
- Port source (read-only): `SRC/services/fyers_client/fyers_data_provider.py`

**Interfaces:**
- Consumes: `acall`/`is_rate_limited` (Task 2), `TokenBucket`, `FyersSettings`, domain `Bar/Circuit/OptionSnapshot`.
- Produces: `class FyersProvider` implementing `MarketDataProvider`, ctor `FyersProvider(client_id: str | None, access_token: str | None, limiter: TokenBucket, *, client=None)`; `@classmethod from_settings(cls, settings: Settings) -> FyersProvider` (reads env via `FyersSettings` env names, builds limiter `TokenBucket.from_settings(settings.rate_limit)`); plus `async ohlcv_range(sym, start: date, end: date, interval="1d") -> list[Bar]` (chunked) for the Phase-7 backtest.
- Scope note: `ohlcv_range` and the `interval` param are a DELIBERATE forward-port beyond the spec's Phase-3 `MarketDataProvider` contract (they ship in the same SRC file; porting now avoids reopening it). `ohlcv_range`'s consumer is the Phase-7 backtest.

- [ ] **Step 1: PORT the pure helpers verbatim** from SRC (same names, module-level): `_RESOLUTION`, `_DAILY_RESOLUTIONS`, `_NSE_SESSION_MINUTES`, `_CALENDAR_DAYS_PER_TRADING_DAY`, `_MIN_INTRADAY_DAYS`, `_MAX_REQUEST_DAYS`, `_MAX_INTRADAY_REQUEST_DAYS`, `_IST`, `_INDEX_SYMBOLS`, `_calendar_days()`, `_to_fyers_symbol()` (staticmethod → module function is fine), `_candles_to_bars()` (staticmethod → module function is fine) **changed to return `list[Bar]`** instead of dicts, `_extract_circuit()` **changed to return `Circuit`** (`last/upper/lower/base` as `Decimal`, from row `ltp/upper_ckt/lower_ckt/c`), `_extract_option_summary()` **changed to return `OptionSnapshot`** (callOi/putOi/pcr + per-strike `oich` sums). Drop the module-global rate gate (`_rate_gate`, `_RATE_LOCK`, `_MIN_INTERVAL`) and `_call_with_backoff` — Task 2's `acall` + injected TokenBucket replace them. Drop `FyersPriceSource` and the `__main__` self-check (its assertions move into pytest in Step 3).
- [ ] **Step 2: Write the class:**

```python
class FyersProvider:
    def __init__(self, client_id: str | None, access_token: str | None,
                 limiter: TokenBucket, *, client=None) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._limiter = limiter
        self._client = client            # injected in tests; lazily built otherwise
        self._client_lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "FyersProvider":
        import os
        return cls(os.environ.get(settings.fyers.client_id_env),
                   os.environ.get(settings.fyers.access_token_env),
                   TokenBucket.from_settings(settings.rate_limit))

    def _get_client(self):  # PORT from SRC (lazy fyers_apiv3 import, RuntimeError messages),
        ...                  # add double-checked self._client_lock around construction

    async def price(self, symbol: str) -> Decimal:
        resp = await acall(self._limiter, self._get_client().quotes,
                           {"symbols": _to_fyers_symbol(symbol)})
        return Decimal(str(_extract_ltp(resp)))          # _extract_ltp ported verbatim

    async def ohlcv(self, symbol: str, lookback: int, interval: str = "1d") -> list[Bar]:
        ...  # PORT _fetch_bars/_history logic; the SDK history() call goes through acall;
             # IST end-date; s=="no_data" → []; non-ok status → RuntimeError (as SRC)

    async def ohlcv_range(self, symbol, start, end, interval="1d") -> list[Bar]:
        ...  # PORT chunking loop; each chunk's history() via acall; dedupe by timestamp

    async def circuit(self, symbol: str) -> Circuit | None:
        resp = await acall(self._limiter, self._get_client().depth,
                           {"symbol": _to_fyers_symbol(symbol), "ohlcv_flag": "1"})
        return _extract_circuit(resp, _to_fyers_symbol(symbol))

    async def options(self, symbol: str) -> OptionSnapshot | None:
        resp = await acall(self._limiter, self._get_client().optionchain,
                           {"symbol": _to_fyers_symbol(symbol), "strikecount": 1, "timestamp": ""})
        return _extract_option_summary(resp)
```

  Every `...` body is the SRC logic with exactly three changes: (a) SDK call goes through `acall`, (b) return domain objects, (c) no module-global rate gate.
- [ ] **Step 3: Write tests** — `tests/providers/market/test_fyers.py`. PORT the SRC `_FakeFyersClient` (history/quotes with 366-day-cap modeling) plus the depth/optionchain fakes from `SRC/tests/nubra/test_circuit_gate.py` (`_FakeFyersDepthClient`) and `SRC/tests/nubra/test_fno_oi.py`, then convert the SRC `_self_check()` assertions into pytest tests (async via `await provider.ohlcv(...)`). Must cover, at minimum: symbol routing (EQ/INDEX/passthrough), bars sorted oldest-first + lookback truncation, `no_data → []`, over-cap single request raises while `ohlcv_range` chunks (≥2 requests) and dedupes, `circuit()` extracts `base` from `c` (present and absent), `options()` computes pcr + `oich` sums, `price()` returns `Decimal`. Use `TokenBucket(capacity=1000, refill_per_sec=100000)` so tests don't sleep.
- [ ] **Step 4: Run — all green** (expect ~10–14 tests). Full suite + ruff green.
- [ ] **Step 5: Commit** — `feat(market): async FyersProvider port (rate-gated, domain-typed)`

---

## GROUP B — News (parallel-safe with A and C)

## Task 4: `providers/news/base.py` + `sentiment.py`

**Files:**
- Create: `src/tradingbot/providers/news/__init__.py`, `base.py`, `sentiment.py`
- Test: `tests/providers/news/__init__.py`, `tests/providers/news/test_sentiment.py`
- Port sources: `SRC/services/nse_announcements/sentiment_analyzer.py` (all three engines + registry), `SRC/services/nse_announcements/nse_announcements_collector.py` (`_score_sentiment`, keyword sets, session-prime pattern)

**Interfaces:**
- Produces:
  - `class NewsSource(Protocol)`: `name: str`; `async fetch(symbol: str) -> tuple[list[NewsItem], str]` (items, provider_mode — modes: `"<name>_live" | "fixture_fallback" | "no_mapping" | "no_credentials"`)
    - (Spec §3 updated to this tuple contract — provider_mode is required by the source-audit / no-silent-fallback principle.)
  - **Concrete-source base pattern:** every source ctor gains `limiter: RateLimiter | None = None` (the injected news rate-limit seam); each source's async-wrap `fetch` `await`s `limiter.acquire()` before dispatching when a limiter is present (Tasks 5 and 6).
  - `class PrimedNseSession`: sync helper owning a `requests.Session` with NSE homepage priming under a double-checked `threading.Lock` (port of the hardened pattern); method `get(url, referer, timeout=15) -> requests.Response`
  - `sentiment.py`: `SentimentAnalyzer` ABC (`analyze(items: list[NewsItem]) -> SentimentResult`), `KeywordSentimentAnalyzer`, `AiSentimentAnalyzer`, `OllamaSentimentAnalyzer`, registry `get_analyzer(name: str, settings: SentimentSettings) -> SentimentAnalyzer`, `label_from_score(score) -> str`, module keyword sets `_DEFAULT_BULLISH_KW`/`_DEFAULT_BEARISH_KW` (ported verbatim), `_score_sentiment(items, bull, bear) -> float` **reading `item.text`** (was `attchmntText`)

**Notes:**
- News hosts (NSE/Google/Reddit) are NOT Fyers — they must not share the Fyers bucket. The limiter seam is injected here; actual per-host bucket wiring happens in the Phase-6 pipeline (named deferral, per spec §2 stage 3 / open-items).
- Sentiment engines + aggregation are folded into `providers/news` in Phase 3 (the spec's §1/§3 don't enumerate them; this is the named home).

- [ ] **Step 1: Write failing sentiment tests** (adapt from `SRC/tests/nubra/test_sentiment_analyzer.py` — port the keyword-engine cases in full; the AI/Ollama cases port with mocks exactly as SRC does, `attchmntText` → `NewsItem(text=...)`). Minimum new-code coverage:

```python
from tradingbot.domain.models import NewsItem
from tradingbot.providers.news.sentiment import KeywordSentimentAnalyzer, get_analyzer, label_from_score
from tradingbot.config.settings import SentimentSettings


def _items(*texts):
    return [NewsItem(text=t, source="test", title=None, link=None, date=None) for t in texts]


def test_keyword_bullish_and_bearish():
    a = KeywordSentimentAnalyzer()
    up = a.analyze(_items("board approved dividend and bonus issue"))
    dn = a.analyze(_items("SEBI fraud investigation; net loss and going concern"))
    assert up.label == "bullish" and up.score > 0
    assert dn.label == "bearish" and dn.score < 0


def test_registry_resolves_and_rejects():
    import pytest
    assert get_analyzer("keyword", SentimentSettings()).analyze(_items()).label == "neutral"
    with pytest.raises(ValueError):
        get_analyzer("nope", SentimentSettings())


def test_label_thresholds():
    assert label_from_score(0.2) == "bullish" and label_from_score(-0.2) == "bearish"
    assert label_from_score(0.05) == "neutral"
```

- [ ] **Step 2: Run — FAIL.** 
- [ ] **Step 3: Implement.** PORT `sentiment_analyzer.py` wholesale with transformations: dict-items → `NewsItem.text`; `from_config(config)` → `from_settings(settings: SentimentSettings)`; return the frozen `SentimentResult` domain model; keyword sets and `_score_sentiment` verbatim. Write `base.py` with the `NewsSource` Protocol and `PrimedNseSession` — `PrimedNseSession` applies the double-checked-lock hardening (pattern from SRC `shareholding_collector._fetch` and `pre_open._fetch`) to the announcements-style primed session; the lock is deliberate hardening, not a verbatim port of `_prime_session`. IST window helper `_ist_now()` included here.
- [ ] **Step 4: Run — green.** Commit — `feat(news): NewsSource protocol, primed NSE session, sentiment engines port`

## Task 5: News sources — `nse_announcements.py` + `google_news.py` (PORT)

**Files:**
- Create: `src/tradingbot/providers/news/nse_announcements.py`, `google_news.py`
- Create: `data/fixtures/news/` (copy fixtures)
- Test: `tests/providers/news/test_nse_announcements.py`, `test_google_news.py`
- Port sources: `SRC/services/nse_announcements/nse_announcements_collector.py`, `SRC/services/google_news/google_news_collector.py` (+ SRC tests `test_nse_announcements_collector.py`, `test_google_news_collector.py`)

**Interfaces:**
- Produces: `NseAnnouncementsSource` and `GoogleNewsSource`, each: `name` (`"nse_announcements"`/`"google_news"`), `from_settings(settings) -> Self`, `async fetch(symbol) -> tuple[list[NewsItem], str]`. Sync internals (primed session, IST date window, 15-min TTL cache with `threading.Lock`, fixture fallback from `fixtures_dir("news")`) wrapped once: `async fetch` = `await asyncio.to_thread(self._fetch_sync, symbol)`.

- [ ] **Step 1: Copy fixtures:**

```bash
mkdir -p /Users/jagadeeshpulamarasetti/Code/own/TradingBot/data/fixtures/news
cp /Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/services/nse_announcements/fixtures/nse_announcements_*.json \
   /Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/services/google_news/fixtures/google_news_RELIANCE.xml \
   /Users/jagadeeshpulamarasetti/Code/own/TradingBot/data/fixtures/news/
```

- [ ] **Step 2: Write failing tests** — port the SRC test cases (RSS parse skips empty titles; live path mocked via `patch.object(src, "_fetch_raw", ...)`; fixture fallback on `requests.RequestException`; cache hit = one fetch; `attchmntText` assertions become `item.text`). Each test file also gets one async test: `items, mode = await source.fetch("RELIANCE")`.
- [ ] **Step 3: Implement the ports.** Transformations only: items become `NewsItem(text=..., source=self.name, title=..., link=..., date=...)` (announcements: `text` = `attchmntText`, `date` = `an_dt`; google: `text` = title, parse via ported `_parse_rss`); fixture paths via `fixtures_dir("news")`; sessions via `PrimedNseSession` (announcements) / plain UA session (google); IST window (announcements — keep the IST fix); config via `from_settings`. **Async-wrap pattern (repeat in every source):**

```python
    async def fetch(self, symbol: str) -> tuple[list[NewsItem], str]:
        if self._limiter is not None:
            await self._limiter.acquire()
        return await asyncio.to_thread(self._fetch_sync, symbol)
```

- [ ] **Step 4: Run — green** (expect ~8–12 tests across the two files). Commit — `feat(news): NSE announcements + Google News sources (async port)`

## Task 6: News sources — `usfda.py`, `insider.py`, `pib.py`, `reddit.py` (PORT)

**Files:**
- Create: the four source modules; copy fixtures `usfda_SUNPHARMA.json`, `insider_SUNPHARMA.json`, `reddit_RELIANCE.json` into `data/fixtures/news/` (same `cp` pattern as Task 5 Step 1, from `SRC/services/usfda/fixtures/`, `SRC/services/nse_insider/fixtures/`, `SRC/services/reddit_india/fixtures/`)
- Test: `tests/providers/news/test_usfda.py`, `test_insider.py`, `test_pib.py`, `test_reddit.py`
- Port sources: `SRC/services/usfda/usfda_collector.py`, `SRC/services/nse_insider/insider_collector.py`, `SRC/services/pib/pib_collector.py`, `SRC/services/reddit_india/india_reddit_collector.py` (+ their SRC tests: `test_usfda_collector.py`, `test_insider_pib.py`, `test_reddit_india.py`)

**Interfaces:**
- Produces: `UsfdaSource` (`no_mapping` for unmapped symbols; map from `settings.news.usfda_symbol_map`), `InsiderSource` (PIT disclosures via `PrimedNseSession`), `PibSource` (market-wide RSS, `no_mapping` unless in `settings.news.pib_symbol_map`, term matching), `RedditSource` (app-only OAuth from `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` env; `no_credentials` mode without them). All expose the same `name` / `from_settings` / `async fetch` surface as Task 5, same async-wrap pattern:

```python
    async def fetch(self, symbol: str) -> tuple[list[NewsItem], str]:
        if self._limiter is not None:
            await self._limiter.acquire()
        return await asyncio.to_thread(self._fetch_sync, symbol)
```

- [ ] **Step 1: Copy the three fixture files** (exact `cp` per Files above).
- [ ] **Step 2: Write failing tests** — port each SRC test file's cases (parse, no_mapping/no_credentials, live-mocked, fixture fallback, snapshot/TTL caches where present; insider keeps the fresh-collector-per-fallback-test fix). One async smoke per source.
- [ ] **Step 3: Implement the four ports** (same transformation list as Task 5; reddit's token client_credentials flow ported as-is; PIB feed cache ported as-is; ADD a new `threading.Lock` around its snapshot check-and-set (new hardening — concurrent per-symbol fetches share the market-wide feed cache; SRC pib has no lock)).
- [ ] **Step 4: Run — green.** Commit — `feat(news): USFDA/insider/PIB/Reddit sources (async port)`

## Task 7: `providers/news/aggregator.py`

**Files:**
- Create: `src/tradingbot/providers/news/aggregator.py`
- Test: `tests/providers/news/test_aggregator.py`
- Port source: `SRC/services/nubra_client/news_aggregator.py` (+ `SRC/tests/nubra/test_news_aggregator.py`)

**Interfaces:**
- Consumes: every `NewsSource` (Tasks 5–6), `get_analyzer` (Task 4).
- Produces:

```python
@dataclass(frozen=True)
class NewsBundle:
    items: list[NewsItem]
    sentiment: SentimentResult
    source_audit: dict[str, dict]      # {source_name: {"status": "live"|"fallback", "count": int}}
    provider_mode: str                 # "live" if ANY source live else "fallback"

class NewsAggregator:
    def __init__(self, sources: list[NewsSource], analyzer: SentimentAnalyzer) -> None: ...
    @classmethod
    def from_settings(cls, settings: Settings, *, limiter: RateLimiter | None = None) -> "NewsAggregator":
        # sources per settings.news toggles; passes the optional shared news limiter (default None for now) into each source ctor
        ...
    async def collect(self, symbol: str) -> NewsBundle:
        # asyncio.gather over sources (a raising source contributes [] + fallback status —
        # gather(return_exceptions=True)); union items; ONE analyzer.analyze(all_items)
```

- [ ] **Step 1: Write failing tests** (port SRC aggregator cases: union + analyze-once, any-live → live, all-fallback, broken source doesn't sink others, from_settings respects toggles — with fake `NewsSource` objects).
- [ ] **Step 2–3: Run FAIL → implement** (sentiment `analyze` is sync CPU for keyword; call it via `asyncio.to_thread` inside `collect` so LLM engines don't block the loop).
- [ ] **Step 4: Run — green.** Commit — `feat(news): NewsAggregator (concurrent sources, single sentiment pass)`

---

## GROUP C — Discovery (parallel-safe with A and B)

## Task 8: `providers/discovery/event_calendar.py` + `catalyst.py` (PORT)

**Files:**
- Create: `src/tradingbot/providers/discovery/__init__.py`, `event_calendar.py`, `catalyst.py`
- Create: `data/fixtures/discovery/nse_event_calendar.json` (cp from `SRC/services/nse_event_calendar/fixtures/`)
- Test: `tests/providers/discovery/__init__.py`, `test_catalyst.py`
- Port sources: `SRC/services/nse_event_calendar/nse_event_calendar_collector.py`, `SRC/services/nubra_client/catalyst_discovery.py` (discovery half; the guard half is Task 9) + `SRC/tests/nubra/test_catalyst_discovery.py`

**Interfaces:**
- Produces (both SYNC — they run once per pipeline run; the pipeline wraps them in `to_thread`):
  - `EventCalendarCollector`: `from_settings`, `collect_range(from_date, to_date) -> list[dict]` with `classify(purpose, desc) -> str` (keyword map ported verbatim), fixture fallback from `fixtures_dir("discovery")`
  - `CatalystDiscovery`: `from_settings(settings) -> Self` (uses `settings.discovery.lookahead_days/lookback_days`), `discover(today: date | None = None) -> dict[str, Catalyst]` — board-meeting entries mapped to `CatalystType` enum (`results→RESULTS, dividend→DIVIDEND, buyback→BUYBACK, fund_raise→FUND_RAISE`, unknown→`ANNOUNCEMENT`), market-wide announcement rows → `CatalystType.FILING` with the filing `desc` as `Catalyst.description`; `Catalyst.source` = `"board_meeting"` / `"announcement"`. **No cap and no guard inside discovery** — the guard (Task 9) filters afterwards; callers compose them.

- [ ] **Step 1: cp the fixture; write failing tests** (port SRC cases: union of calendar+announcements symbols, dedupe/upper/no-blank, catalyst captured with description, calendar-first priority for a symbol in both, failing announcements feed doesn't sink the calendar half). Enum-mapping test:

```python
def test_catalyst_types_map_to_enum():
    from tradingbot.domain.enums import CatalystType
    d = _discovery_with_fakes(events=[{"symbol": "TCS", "purpose": "Financial Results"}],
                              announcements={"INFY": "Allotment of Securities"})
    out = d.discover(today=date(2026, 7, 7))
    assert out["TCS"].type is CatalystType.RESULTS and out["TCS"].source == "board_meeting"
    assert out["INFY"].type is CatalystType.FILING and "Allotment" in out["INFY"].description
```

- [ ] **Step 2–3: FAIL → implement the ports** (sessions via `PrimedNseSession`; IST windows kept; TTL cache kept).
- [ ] **Step 4: Run — green.** Commit — `feat(discovery): event calendar + catalyst discovery (domain-typed port)`

## Task 9: `providers/discovery/guard.py` (PORT)

**Files:**
- Create: `src/tradingbot/providers/discovery/guard.py`
- Test: `tests/providers/discovery/test_guard.py`
- Port source: guard half of `SRC/services/nubra_client/catalyst_discovery.py` (`SurveillanceLiquidityGuard`, `parse_turnover_lacs`, `top_by_turnover`) + `SRC/tests/nubra/test_surveillance_liquidity.py`

**Interfaces:**
- Produces (SYNC): `parse_turnover_lacs(csv_text) -> dict[str, float]`; `SurveillanceLiquidityGuard(min_turnover_cr: float, exclude_surveillance: bool, bhavcopy_lookback: int)` with `from_settings`, `filter(symbols: list[str], today: date | None = None) -> list[str]` (ASM/GSM exclusion + ₹-turnover floor, both fail-open exactly as SRC), `top_by_turnover(symbols, n) -> list[str]`.

- [ ] **Step 1: Write failing tests** (port all SRC guard cases: EQ-only turnover parse, drops surveilled + illiquid, absent-from-bhavcopy = illiquid, fails open on empty turnover / surveillance error, boundary at exactly the floor, exclude disabled → no surveillance fetch, top_by_turnover ranks by liquidity not alphabet).
- [ ] **Step 2–3: FAIL → implement the port** (`PrimedNseSession` for ASM/GSM; nsearchives bhavcopy walk-back verbatim).
- [ ] **Step 4: Run — green.** Commit — `feat(discovery): surveillance + liquidity guard port`

---

## Task 10: Provider-layer integration + green gate (after A, B, C complete)

**Files:**
- Test: `tests/providers/test_integration.py`

**Interfaces:**
- Consumes: everything above. Produces nothing new — proves the layer composes the way the Phase-6 pipeline will consume it.

- [ ] **Step 1: Write the integration test** (fakes only, no network):

```python
import asyncio
from datetime import date
from decimal import Decimal

import pytest

from tradingbot.config.settings import Settings
from tradingbot.domain.enums import CatalystType
from tradingbot.domain.models import NewsItem
from tradingbot.providers.market.fyers import FyersProvider
from tradingbot.providers.news.aggregator import NewsAggregator
from tradingbot.providers.news.sentiment import KeywordSentimentAnalyzer
from tradingbot.providers.ratelimit import TokenBucket
# reuse the fake SDK client from test_fyers and a fake NewsSource


@pytest.mark.asyncio
async def test_provider_layer_composes_for_one_symbol(fake_sdk_client, fake_news_source):
    limiter = TokenBucket(capacity=1000, refill_per_sec=100000)
    market = FyersProvider("cid", "tok", limiter, client=fake_sdk_client)
    news = NewsAggregator([fake_news_source], KeywordSentimentAnalyzer())

    price, bars, circuit, options, bundle = await asyncio.gather(
        market.price("RELIANCE"), market.ohlcv("RELIANCE", 20),
        market.circuit("RELIANCE"), market.options("RELIANCE"),
        news.collect("RELIANCE"),
    )
    assert isinstance(price, Decimal) and len(bars) > 0 and bars[0].close > 0
    assert circuit is not None and circuit.band_pct is not None
    assert options is None or options.pcr is not None
    assert bundle.sentiment.label in ("bullish", "bearish", "neutral")
```

  (Define `fake_sdk_client`/`fake_news_source` as fixtures in this file, reusing the Task-3 fake class by import.)
- [ ] **Step 2: Run the FULL suite + ruff — everything green.** Record counts.
- [ ] **Step 3: Commit** — `test(providers): provider-layer integration green gate (Phase 3 complete)`

---

## Definition of done (Phase 3)

- `providers/market` — async, rate-gated, domain-typed FyersProvider; all SRC parsing/chunking correctness preserved (incl. circuit `base`, OI change, 366-day chunking, no_data vs error).
- `providers/news` — six sources + sentiment engines + aggregator; fixture-fallback and fail-safe semantics identical to SRC; one sentiment pass per symbol.
- `providers/discovery` — catalyst discovery emitting domain `Catalyst` objects + the surveillance/liquidity guard, both sync, no caps.
- All tests green (target: Phase-2's 15 + ~60–80 ported/new), ruff clean, one commit per task.
- No network in tests; MiroFish untouched.

### Named deferrals

- Spec §2 stage-2 bulk providers (sector snapshot loader, regime index, bulk/block deals, FII-DII, pre-open) are NOT built in Phase 3: sector/regime data lands with the gates (Phase 5 plan); deals/FII-DII/pre-open land with pipeline stage 2 (Phase 6 plan).

**Next plan:** Phase 4 (batched TimesFM `Forecaster` + warm-up) — small, then Phase 5 (gates + scoring).

# TradingBot Foundation (Phases 0–2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the standalone `~/Code/own/TradingBot` project and build its foundation — pure domain models/enums, a typed config loader, and the async `TokenBucket` rate limiter — all fully tested.

**Architecture:** A `src/`-layout Python package `tradingbot` with strict layering (`domain` depends on nothing; everything else depends inward). Phases 0–2 build the bottom layer only: no IO, no providers yet. This is the foundation later phases (providers, forecast, gates, scoring, pipeline, cli/api) build on. Reference spec: `docs/superpowers/specs/2026-07-07-tradingbot-clean-extract-design.md`.

**Tech Stack:** Python 3.11, `uv` for env/deps, `pytest`, `ruff`, `pydantic` v2 (typed config). `asyncio` (stdlib) for the rate limiter. No network/IO in these phases.

## Global Constraints

- Python `>=3.11,<3.13` (matches the source project's `requires-python`).
- New project root: `~/Code/own/TradingBot` (absolute: `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`). All paths below are relative to it unless absolute.
- `src/` layout: importable as `tradingbot` (e.g. `from tradingbot.domain.models import Candidate`).
- `domain/` must import NOTHING outside stdlib + `domain` itself — no providers, no IO, no config. Enforced by review.
- Tests run with: `uv run --extra dev pytest -q` from the project root; must be green at the end of every task.
- Frozen dataclasses for all domain models (immutable value objects).
- Money/prices use `Decimal`, never `float`, in domain models.
- Commit after every task (TDD: test → fail → implement → pass → commit).

---

## File Structure (Phases 0–2)

```
TradingBot/
├── pyproject.toml                       # package metadata, deps, tool config
├── README.md                            # one-paragraph project intro
├── .gitignore                           # .env, .venv, __pycache__, .venv-timesfm
├── src/tradingbot/
│   ├── __init__.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── enums.py                     # TradeDirection, Status, DropReason, CatalystType
│   │   └── models.py                    # Catalyst, Candidate, Circuit, OptionSnapshot,
│   │                                    #   Quantiles, Forecast, MarketData, ConvictionFlags, Probable
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                  # pydantic Settings + load_config()
│   └── providers/
│       ├── __init__.py
│       └── ratelimit.py                 # TokenBucket (async)
└── tests/
    ├── __init__.py
    ├── domain/test_enums.py
    ├── domain/test_models.py
    ├── config/test_settings.py
    └── providers/test_ratelimit.py
```

---

## Task 1: Project scaffold (Phase 0)

**Files:**
- Create: `pyproject.toml`, `README.md`, `.gitignore`, `src/tradingbot/__init__.py`, `tests/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: an importable `tradingbot` package (version string `tradingbot.__version__`).

- [ ] **Step 1: Create the project directory and init git**

```bash
mkdir -p /Users/jagadeeshpulamarasetti/Code/own/TradingBot
cd /Users/jagadeeshpulamarasetti/Code/own/TradingBot
git init
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "tradingbot"
version = "0.1.0"
description = "India catalyst-swing equity screener — staged async pipeline."
requires-python = ">=3.11,<3.13"
dependencies = [
  "pydantic>=2.8",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6", "pytest-asyncio>=0.24"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tradingbot"]

[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 110
src = ["src", "tests"]
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.venv-timesfm/
.env
*.egg-info/
.pytest_cache/
.ruff_cache/
state/
```

- [ ] **Step 4: Write `README.md`**

```markdown
# TradingBot

India catalyst-swing equity screener. Staged async pipeline: catalyst discovery →
bulk market data → rate-limited per-symbol fetch → batched TimesFM forecast → playbook
gates + watchlist scoring → MongoDB. Extracted and re-architected from the MiroFish monorepo.

See `docs/` for the design spec and plans.
```

- [ ] **Step 5: Create package + test `__init__.py` and version**

`src/tradingbot/__init__.py`:
```python
__version__ = "0.1.0"
```
`tests/__init__.py`: (empty file)

- [ ] **Step 6: Write the smoke test** — `tests/test_smoke.py`

```python
def test_package_imports():
    import tradingbot
    assert tradingbot.__version__ == "0.1.0"
```

- [ ] **Step 7: Run the smoke test (expect PASS)**

Run: `uv run --extra dev pytest tests/test_smoke.py -q`
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: scaffold tradingbot package (Phase 0)"
```

---

## Task 2: Domain enums (Phase 1)

**Files:**
- Create: `src/tradingbot/domain/__init__.py`, `src/tradingbot/domain/enums.py`
- Test: `tests/domain/__init__.py`, `tests/domain/test_enums.py`

**Interfaces:**
- Produces: `TradeDirection` (BULLISH/BEARISH/NEUTRAL), `Status` (ELECTED/DROPPED), `DropReason`
  (str enum incl. CIRCUIT_LOCKED, SECTOR_DOWN, REGIME_DOWN, GAP_FADED, WEAK_VOLUME,
  DATA_THROTTLED, INSUFFICIENT_HISTORY, NO_FORECAST, HOLD), `CatalystType`
  (RESULTS, DIVIDEND, BUYBACK, FUND_RAISE, ANNOUNCEMENT, FILING).

- [ ] **Step 1: Write the failing test** — `tests/domain/test_enums.py`

```python
from tradingbot.domain.enums import TradeDirection, Status, DropReason, CatalystType


def test_trade_direction_from_return():
    assert TradeDirection.from_return(0.02) is TradeDirection.BULLISH
    assert TradeDirection.from_return(-0.02) is TradeDirection.BEARISH
    assert TradeDirection.from_return(0.0) is TradeDirection.NEUTRAL


def test_enums_are_str_valued():
    assert Status.ELECTED == "elected"
    assert DropReason.CIRCUIT_LOCKED == "circuit_locked"
    assert CatalystType.RESULTS == "results"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/domain/test_enums.py -q`
Expected: FAIL (ModuleNotFoundError: tradingbot.domain.enums).

- [ ] **Step 3: Create `tests/domain/__init__.py`** (empty) and write `src/tradingbot/domain/__init__.py` (empty), then `src/tradingbot/domain/enums.py`:

```python
from __future__ import annotations

from enum import Enum


class TradeDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

    @classmethod
    def from_return(cls, predicted_return: float, eps: float = 1e-9) -> "TradeDirection":
        if predicted_return > eps:
            return cls.BULLISH
        if predicted_return < -eps:
            return cls.BEARISH
        return cls.NEUTRAL


class Status(str, Enum):
    ELECTED = "elected"
    DROPPED = "dropped"


class DropReason(str, Enum):
    CIRCUIT_LOCKED = "circuit_locked"
    SECTOR_DOWN = "sector_down"
    REGIME_DOWN = "regime_down"
    GAP_FADED = "gap_faded"
    WEAK_VOLUME = "weak_volume"
    DATA_THROTTLED = "data_throttled"
    INSUFFICIENT_HISTORY = "insufficient_history"
    NO_FORECAST = "no_forecast"
    HOLD = "hold"


class CatalystType(str, Enum):
    RESULTS = "results"
    DIVIDEND = "dividend"
    BUYBACK = "buyback"
    FUND_RAISE = "fund_raise"
    ANNOUNCEMENT = "announcement"
    FILING = "filing"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/domain/test_enums.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(domain): trade/status/drop-reason/catalyst enums (Phase 1)"
```

---

## Task 3: Domain models (Phase 1)

**Files:**
- Create: `src/tradingbot/domain/models.py`
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Consumes: `enums.TradeDirection`, `enums.Status`, `enums.DropReason`, `enums.CatalystType`.
- Produces (all frozen dataclasses):
  - `Catalyst(type: CatalystType, description: str, source: str, date: str | None)`
  - `Candidate(symbol: str, catalyst: Catalyst)`
  - `Circuit(last: Decimal, upper: Decimal, lower: Decimal | None, base: Decimal | None)`
    with `band_pct: float | None` property (upper vs base, falls back to last).
  - `OptionSnapshot(call_oi: int, put_oi: int, pcr: float | None, call_oi_change: int | None, put_oi_change: int | None)`
  - `Quantiles(q10: list[float], q50: list[float], q90: list[float])`
  - `Forecast(predicted_return: float, direction: TradeDirection, confidence: float, quantiles: Quantiles)`
  - `MarketData(ltp: Decimal, closes: list[float], history_ok: bool, circuit: Circuit | None, options: OptionSnapshot | None)`
  - `ConvictionFlags(sentiment: float | None, catalyst_stack: int, has_deal: bool | None, promoter_trend: str | None, oi_buildup: str | None)`
  - `Probable(symbol: str, status: Status, drop_reason: DropReason | None, score: float | None, forecast: Forecast | None, market: MarketData, catalyst: Catalyst, flags: ConvictionFlags)`

- [ ] **Step 1: Write the failing test** — `tests/domain/test_models.py`

```python
from decimal import Decimal

from tradingbot.domain.enums import CatalystType, Status, TradeDirection
from tradingbot.domain.models import (
    Catalyst, Candidate, Circuit, Forecast, MarketData, Probable, ConvictionFlags, Quantiles,
)


def test_circuit_band_pct_off_base_not_last():
    # 10% band off prev-close base; last is up intraday — band must be off base, not last.
    c = Circuit(last=Decimal("108"), upper=Decimal("110"), lower=Decimal("90"), base=Decimal("100"))
    assert round(c.band_pct, 2) == 10.0


def test_circuit_band_pct_falls_back_to_last_when_base_missing():
    c = Circuit(last=Decimal("100"), upper=Decimal("110"), lower=Decimal("90"), base=None)
    assert round(c.band_pct, 2) == 10.0


def test_circuit_band_pct_none_without_upper_or_last():
    assert Circuit(last=Decimal("0"), upper=Decimal("110"), lower=None, base=None).band_pct is None


def test_models_are_frozen():
    cat = Catalyst(type=CatalystType.RESULTS, description="Board meeting", source="calendar", date=None)
    cand = Candidate(symbol="TCS", catalyst=cat)
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        cand.symbol = "INFY"  # type: ignore[misc]


def test_probable_holds_full_row():
    cat = Catalyst(type=CatalystType.FILING, description="x", source="announcement", date=None)
    md = MarketData(ltp=Decimal("100"), closes=[100.0] * 20, history_ok=True, circuit=None, options=None)
    fc = Forecast(predicted_return=0.03, direction=TradeDirection.BULLISH, confidence=0.5,
                  quantiles=Quantiles(q10=[], q50=[], q90=[]))
    p = Probable(symbol="TCS", status=Status.ELECTED, drop_reason=None, score=0.8,
                 forecast=fc, market=md, catalyst=cat,
                 flags=ConvictionFlags(sentiment=0.2, catalyst_stack=3, has_deal=False,
                                       promoter_trend=None, oi_buildup=None))
    assert p.status is Status.ELECTED and p.score == 0.8 and p.forecast.direction is TradeDirection.BULLISH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/domain/test_models.py -q`
Expected: FAIL (ModuleNotFoundError: tradingbot.domain.models).

- [ ] **Step 3: Write `src/tradingbot/domain/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradingbot.domain.enums import CatalystType, DropReason, Status, TradeDirection


@dataclass(frozen=True)
class Catalyst:
    type: CatalystType
    description: str
    source: str
    date: str | None = None


@dataclass(frozen=True)
class Candidate:
    symbol: str
    catalyst: Catalyst


@dataclass(frozen=True)
class Circuit:
    last: Decimal
    upper: Decimal
    lower: Decimal | None
    base: Decimal | None

    @property
    def band_pct(self) -> float | None:
        """One-sided band width %, off the prev-close base; falls back to last if base missing.
        None when neither a usable base/last nor upper is present."""
        if not self.upper:
            return None
        ref = self.base if self.base else self.last
        if not ref:
            return None
        return (float(self.upper) / float(ref) - 1.0) * 100.0


@dataclass(frozen=True)
class OptionSnapshot:
    call_oi: int
    put_oi: int
    pcr: float | None
    call_oi_change: int | None = None
    put_oi_change: int | None = None


@dataclass(frozen=True)
class Quantiles:
    q10: list[float]
    q50: list[float]
    q90: list[float]


@dataclass(frozen=True)
class Forecast:
    predicted_return: float
    direction: TradeDirection
    confidence: float
    quantiles: Quantiles


@dataclass(frozen=True)
class MarketData:
    ltp: Decimal
    closes: list[float]
    history_ok: bool
    circuit: Circuit | None
    options: OptionSnapshot | None


@dataclass(frozen=True)
class ConvictionFlags:
    sentiment: float | None
    catalyst_stack: int
    has_deal: bool | None
    promoter_trend: str | None
    oi_buildup: str | None


@dataclass(frozen=True)
class Probable:
    symbol: str
    status: Status
    drop_reason: DropReason | None
    score: float | None
    forecast: Forecast | None
    market: MarketData
    catalyst: Catalyst
    flags: ConvictionFlags
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/domain/test_models.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(domain): frozen value objects (Candidate/MarketData/Forecast/Probable) (Phase 1)"
```

---

## Task 4: Typed config loader (Phase 2)

**Files:**
- Create: `src/tradingbot/config/__init__.py`, `src/tradingbot/config/settings.py`
- Test: `tests/config/__init__.py`, `tests/config/test_settings.py`

**Interfaces:**
- Produces: `Settings` (pydantic BaseModel) with nested `DiscoverySettings`
  (`max_symbols: int = 0`, `min_turnover_cr: float = 5.0`, `exclude_surveillance: bool = True`),
  `RateLimitSettings` (`capacity: int = 10`, `refill_per_sec: float = 10.0`),
  `ForecastSettings` (`enabled: bool = True`, `horizon: int = 5`); and
  `load_config(data: dict) -> Settings` mapping the existing nubra_config.json shape
  (`discovery.*`, top-level `candidacy_mode`). Unknown keys ignored; missing keys → defaults.

- [ ] **Step 1: Write the failing test** — `tests/config/test_settings.py`

```python
from tradingbot.config.settings import Settings, load_config


def test_defaults_are_uncapped_and_sane():
    s = Settings()
    assert s.discovery.max_symbols == 0          # 0 = uncapped
    assert s.discovery.min_turnover_cr == 5.0
    assert s.rate_limit.capacity == 10
    assert s.forecast.enabled is True and s.forecast.horizon == 5


def test_load_config_maps_nubra_shape():
    raw = {
        "candidacy_mode": True,
        "discovery": {"max_symbols": 0, "min_turnover_cr": 15.0, "exclude_surveillance": True},
        "unknown_legacy_key": {"ignored": 1},
    }
    s = load_config(raw)
    assert s.candidacy_mode is True
    assert s.discovery.min_turnover_cr == 15.0
    assert s.discovery.max_symbols == 0


def test_load_config_empty_uses_defaults():
    s = load_config({})
    assert s.candidacy_mode is False and s.discovery.min_turnover_cr == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/config/test_settings.py -q`
Expected: FAIL (ModuleNotFoundError: tradingbot.config.settings).

- [ ] **Step 3: Create `tests/config/__init__.py` (empty), `src/tradingbot/config/__init__.py` (empty), write `src/tradingbot/config/settings.py`**

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_symbols: int = 0            # 0 = uncapped; the guard is the universe filter
    min_turnover_cr: float = 5.0
    exclude_surveillance: bool = True


class RateLimitSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    capacity: int = 10             # token bucket burst; calibrate to Fyers' real limit
    refill_per_sec: float = 10.0


class ForecastSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    horizon: int = 5


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    candidacy_mode: bool = False
    discovery: DiscoverySettings = DiscoverySettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
    forecast: ForecastSettings = ForecastSettings()


def load_config(data: dict) -> Settings:
    """Map a raw nubra_config.json-shaped dict into typed Settings. Unknown keys ignored
    (extra='ignore'); missing keys fall back to defaults."""
    return Settings.model_validate(data or {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/config/test_settings.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(config): typed pydantic Settings + load_config (Phase 2)"
```

---

## Task 5: Async TokenBucket rate limiter (Phase 2)

**Files:**
- Create: `src/tradingbot/providers/__init__.py`, `src/tradingbot/providers/ratelimit.py`
- Test: `tests/providers/__init__.py`, `tests/providers/test_ratelimit.py`

**Interfaces:**
- Consumes: `config.settings.RateLimitSettings` (for `from_settings`).
- Produces: `TokenBucket(capacity: int, refill_per_sec: float)` with `async def acquire(self) -> None`
  (blocks until a token is available; refills continuously) and classmethod
  `from_settings(rl: RateLimitSettings) -> TokenBucket`. This is the concurrency primitive stage 3
  uses: N concurrent fetches each `await bucket.acquire()` before their (thread-wrapped) API call,
  bursting up to `capacity` then pacing at `refill_per_sec`.

- [ ] **Step 1: Write the failing test** — `tests/providers/test_ratelimit.py`

```python
import asyncio
import time

import pytest

from tradingbot.providers.ratelimit import TokenBucket


@pytest.mark.asyncio
async def test_bursts_up_to_capacity_immediately():
    bucket = TokenBucket(capacity=5, refill_per_sec=1.0)
    t0 = time.monotonic()
    for _ in range(5):                      # 5 tokens available at once
        await bucket.acquire()
    assert time.monotonic() - t0 < 0.05     # burst — effectively instant


@pytest.mark.asyncio
async def test_paces_beyond_capacity():
    bucket = TokenBucket(capacity=2, refill_per_sec=10.0)  # 0.1s per token after burst
    t0 = time.monotonic()
    for _ in range(2):                      # burst 2
        await bucket.acquire()
    await bucket.acquire()                  # 3rd waits ~1 refill interval
    assert time.monotonic() - t0 >= 0.09


@pytest.mark.asyncio
async def test_concurrent_acquires_are_serialized_by_tokens():
    bucket = TokenBucket(capacity=1, refill_per_sec=20.0)  # 0.05s/token
    t0 = time.monotonic()
    await asyncio.gather(*(bucket.acquire() for _ in range(4)))
    # 1 burst + 3 paced at 0.05s ≈ >= 0.14s
    assert time.monotonic() - t0 >= 0.13


def test_from_settings():
    from tradingbot.config.settings import RateLimitSettings
    b = TokenBucket.from_settings(RateLimitSettings(capacity=7, refill_per_sec=3.0))
    assert b.capacity == 7 and b.refill_per_sec == 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/providers/test_ratelimit.py -q`
Expected: FAIL (ModuleNotFoundError: tradingbot.providers.ratelimit).

- [ ] **Step 3: Create `tests/providers/__init__.py` (empty), `src/tradingbot/providers/__init__.py` (empty), write `src/tradingbot/providers/ratelimit.py`**

```python
from __future__ import annotations

import asyncio
import time

from tradingbot.config.settings import RateLimitSettings


class TokenBucket:
    """Async token-bucket rate limiter. Holds up to `capacity` tokens, refilled continuously at
    `refill_per_sec`. `acquire()` returns immediately while tokens remain (burst), then paces to
    the refill rate. Safe for many concurrent `await acquire()` callers (guarded by a lock)."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, rl: RateLimitSettings) -> "TokenBucket":
        return cls(capacity=rl.capacity, refill_per_sec=rl.refill_per_sec)

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.refill_per_sec)
        self._updated = now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                await asyncio.sleep(deficit / self.refill_per_sec)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/providers/test_ratelimit.py -q`
Expected: 4 passed.

- [ ] **Step 5: Run the FULL suite + ruff (foundation green)**

Run: `uv run --extra dev pytest -q && uv run --extra dev ruff check src tests`
Expected: all passed, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(providers): async TokenBucket rate limiter (Phase 2)"
```

---

## Definition of done (Phases 0–2)

- `~/Code/own/TradingBot` is a git repo with a `src/`-layout `tradingbot` package that imports.
- `domain/` (enums + frozen models) is pure (stdlib-only) and fully tested — including the
  band-off-base correctness carried over from the source project.
- `config/` typed Settings loads the existing nubra_config shape (uncapped default preserved).
- `providers/ratelimit.py` TokenBucket bursts-then-paces and is concurrency-safe — the primitive
  the staged async pipeline (Phase 6) depends on.
- Full suite green; `ruff` clean.

**Next plan:** Phase 3 (`providers/market` async Fyers wrapper + `providers/news` sources +
`providers/discovery`), planned once this foundation is merged.

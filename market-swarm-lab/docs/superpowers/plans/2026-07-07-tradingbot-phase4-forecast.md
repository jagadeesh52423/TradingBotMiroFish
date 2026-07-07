# TradingBot Phase 4 — Batched TimesFM Forecaster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/tradingbot/forecast/` — the `Forecaster` Protocol with a **batch-first contract** (`forecast_batch`: ONE TimesFM call for all series), the ported confidence math (magnitude × quantile-interval, exp-decay k=0.15), and the retryable single-threaded `warm_up` — plus the batch-vs-single parity proof the spec requires.

**Architecture:** `forecast/` depends only on `domain` + `config`. TimesFM 2.5 lives in an isolated venv (`.venv-timesfm`, ~2GB torch) whose site-packages are injected at load time; the loader is lazy, lock-guarded, and its warm-up retries transient failures instead of latching them (the MiroFish "empty run" bug stays fixed). There is **no formulaic fallback**: model unavailable → `ForecastUnavailable` → the pipeline marks symbols `NO_FORECAST`. Reference spec: `2026-07-07-tradingbot-clean-extract-design.md` §3 (Forecaster contract) + open-items (batch validation).

**Tech Stack:** Python 3.11, `timesfm` 2.5 + `torch` (isolated venv), `numpy` (main env), pytest (fake model — the real model never loads in tests; a live parity test is gated behind `LIVE_TESTS=1`).

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. Port source (**SRC**, read-only): `/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/services/forecasting/forecasting_service.py` and its tests `tests/nubra/test_forecast_no_fallback.py`.
- PORT means: copy SRC logic, apply only the listed transformations. The confidence formulas, retry semantics, and TimesFM 2.5 loader config are reviewed/tested — do not re-derive them.
- Tests never load the real model (fake `timesfm` module via `monkeypatch.setitem(sys.modules, ...)`, as SRC tests do). `LIVE_TESTS=1` gates the one real-model parity test.
- Full suite (`uv run --extra dev pytest -q`) + `ruff` green at the end of every task; commit per task. (If the Phase-3 workflow is still executing in this repo, coordinate as in Phase 3: explicit-path `git add`, retry on index.lock, and scope test runs to `tests/forecast/` until the final task.)
- **Behavioral invariants that MUST survive the port** (each has a named test): direction uses the SRC ±0.5% threshold (a +0.4% 5-day move is NEUTRAL, not BULLISH); confidence = `round(clamp(magnitude × interval), 3)`; interval decay `exp(-band/(k·price))`, k=0.15, neutral 0.5 on missing quantiles/zero price; warm-up retries clear the cached transient error; a wide band meaningfully reduces confidence vs a tight band at the same point forecast.

---

## File Structure (Phase 4)

```
src/tradingbot/
├── config/settings.py            # MODIFY: ForecastSettings gains venv_path: str | None
├── forecast/
│   ├── __init__.py
│   ├── base.py                   # Forecaster Protocol + ForecastUnavailable
│   ├── confidence.py             # pure ported math: direction/magnitude/interval/combined
│   └── timesfm.py                # loader + warm_up + TimesFMForecaster.forecast_batch
├── pyproject.toml                # MODIFY: + numpy
tests/forecast/
├── __init__.py
├── test_base.py
├── test_confidence.py
├── test_warmup.py
├── test_batch.py                 # fake-model batching + parity + invariants
└── test_live_parity.py           # LIVE_TESTS=1 only
```

---

## Task 1: `forecast/base.py` — contract

**Files:**
- Create: `src/tradingbot/forecast/__init__.py` (empty), `src/tradingbot/forecast/base.py`
- Test: `tests/forecast/__init__.py` (empty), `tests/forecast/test_base.py`

**Interfaces:**
- Produces:
  - `class ForecastUnavailable(RuntimeError)` — "no real forecast can be produced; there is no formulaic fallback" (docstring ported from SRC).
  - `@runtime_checkable class Forecaster(Protocol)`:
    `def warm_up(self) -> bool: ...` and
    `def forecast_batch(self, series: dict[str, list[float]], horizon: int = 5) -> dict[str, Forecast]: ...`
    (batched by design — there is deliberately no single-symbol method).

- [ ] **Step 1: Write the failing test** — `tests/forecast/test_base.py`:

```python
from tradingbot.domain.enums import TradeDirection
from tradingbot.domain.models import Forecast, Quantiles
from tradingbot.forecast.base import Forecaster, ForecastUnavailable


def test_forecast_unavailable_is_runtime_error():
    assert issubclass(ForecastUnavailable, RuntimeError)


def test_protocol_is_runtime_checkable_and_batch_first():
    class Fake:
        def warm_up(self) -> bool:
            return True
        def forecast_batch(self, series, horizon: int = 5):
            return {s: Forecast(predicted_return=0.0, direction=TradeDirection.NEUTRAL,
                                confidence=0.5, quantiles=Quantiles([], [], []))
                    for s in series}
    assert isinstance(Fake(), Forecaster)
    assert not hasattr(Forecaster, "forecast")   # no single-symbol escape hatch
```

- [ ] **Step 2: Run — FAIL** (module missing). **Step 3: Implement** `base.py` exactly per Interfaces (import `Forecast` for typing only). **Step 4: Run — 2 passed.** 
- [ ] **Step 5: Commit** — `feat(forecast): Forecaster protocol (batch-first) + ForecastUnavailable`

---

## Task 2: `forecast/confidence.py` — pure math PORT

**Files:**
- Create: `src/tradingbot/forecast/confidence.py`
- Test: `tests/forecast/test_confidence.py`
- Port source: SRC `_derive_direction`, `_interval_confidence`, and the multiplicative combine inside `_timesfm_forecast`.

**Interfaces:**
- Produces (pure functions, no IO):
  - `DIRECTION_EPS = 0.005` (SRC's ±0.5% sideways threshold)
  - `direction_for(last_close: float, final_point: float) -> TradeDirection` — computes `delta_pct` and returns `TradeDirection.from_return(delta_pct, eps=DIRECTION_EPS)`; guards `last_close` with `max(abs(last_close), 1e-9)` as SRC does.
  - `magnitude_confidence(last_close: float, final_point: float) -> float` — SRC formula `min(0.95, 0.5 + abs(delta_pct) * 8)`.
  - `interval_confidence(last_close: float, q10_last: float | None, q90_last: float | None, k: float = 0.15) -> float` — exp decay `exp(-band/(k·|last_close|))` clamped [0,1]; returns **0.5** when either quantile is None or `last_close` is falsy / denom ≤ 0 (ported neutral-guard).
  - `combined_confidence(last_close, final_point, q10_last, q90_last) -> float` — `round(max(0.0, min(1.0, magnitude × interval)), 3)`.

- [ ] **Step 1: Write failing tests** (port the SRC invariant tests, adapted to float args):

```python
import math

from tradingbot.domain.enums import TradeDirection
from tradingbot.forecast.confidence import (
    DIRECTION_EPS, combined_confidence, direction_for, interval_confidence, magnitude_confidence,
)


def test_direction_uses_half_percent_threshold():
    assert direction_for(100.0, 100.4) is TradeDirection.NEUTRAL      # +0.4% → sideways
    assert direction_for(100.0, 100.6) is TradeDirection.BULLISH      # +0.6%
    assert direction_for(100.0, 99.4) is TradeDirection.BEARISH


def test_magnitude_confidence_caps():
    assert magnitude_confidence(100.0, 100.0) == 0.5
    assert magnitude_confidence(100.0, 110.0) == 0.95                  # capped


def test_interval_confidence_decay_and_guards():
    tight = interval_confidence(100.0, 99.5, 100.5)                    # 1% band
    wide = interval_confidence(100.0, 95.0, 105.0)                     # 10% band
    very_wide = interval_confidence(100.0, 85.0, 115.0)                # 30% band
    assert tight > wide > very_wide
    assert tight > 0.9 and 0.4 < wide < 0.6 and very_wide < 0.15
    assert interval_confidence(100.0, None, 100.5) == 0.5              # neutral guards
    assert interval_confidence(0.0, 99.0, 101.0) == 0.5
    assert math.isclose(wide, math.exp(-0.10 / 0.15), rel_tol=1e-6)


def test_combined_is_multiplicative_not_inflating():
    # weak magnitude + tight band must NOT be lifted above the old 0.55 override threshold
    weak_tight = combined_confidence(100.0, 100.4, 100.2, 100.6)
    assert weak_tight <= 0.55
    same_point_wide = combined_confidence(100.0, 103.0, 90.0, 116.0)
    same_point_tight = combined_confidence(100.0, 103.0, 102.5, 103.5)
    assert same_point_tight > same_point_wide
```

- [ ] **Step 2: Run — FAIL. Step 3: Implement** per Interfaces (≈35 lines; formulas verbatim from SRC). **Step 4: Run — 4 passed.** 
- [ ] **Step 5: Commit** — `feat(forecast): ported confidence math (direction eps, magnitude, interval decay, multiplicative combine)`

---

## Task 3: loader + retryable warm-up (`forecast/timesfm.py`, part 1)

**Files:**
- Create: `src/tradingbot/forecast/timesfm.py`
- Modify: `src/tradingbot/config/settings.py` (`ForecastSettings` gains `venv_path: str | None = None`), `pyproject.toml` (+ `numpy>=1.26`)
- Test: `tests/forecast/test_warmup.py`
- Port source: SRC `_load_timesfm` (venv sys.path injection, TimesFM 2.5 `from_pretrained("google/timesfm-2.5-200m-pytorch")` + `ForecastConfig(max_context=1024, max_horizon=16, normalize_inputs=True, use_continuous_quantile_head=True, fix_quantile_crossing=True)`, double-checked `threading.Lock`) and `warm_up_timesfm` (retry loop clearing the transient error).

**Interfaces:**
- Produces (module-level, mirroring SRC's proven shape):
  - `_timesfm_model` / `_timesfm_error` module state + `_load_lock`
  - `def load_model(venv_path: str | None) -> bool` — injects `<venv>/lib/python*/site-packages` (default venv: `<repo>/.venv-timesfm`; a configured `venv_path` — e.g. the existing MiroFish `.venv-timesfm` — avoids a second 2GB install), imports torch/numpy/timesfm, builds + compiles the 2.5 model once under the lock; caches error string on failure.
  - `def warm_up(venv_path: str | None = None, retries: int = 3, backoff: float = 2.0) -> bool` — single-threaded retryable load; **clears the cached transient error between attempts** (the anti-"empty run" fix); a genuine failure stays latched after the retries.

- [ ] **Step 1: Write failing tests** — PORT these SRC tests, adapting imports/monkeypatch targets to `tradingbot.forecast.timesfm`: `test_load_timesfm_is_thread_safe_single_load` (8 threads, fake `timesfm`+`torch` modules via `monkeypatch.setitem(sys.modules, ...)`, assert exactly one `from_pretrained`), `test_warm_up_retries_transient_failure` (flaky loader succeeds on 3rd; assert 3 calls), `test_warm_up_gives_up_after_retries` (error stays latched), `test_warm_up_noop_when_already_loaded`. Copy the SRC test bodies; only the module path and function names change per the Interfaces above.
- [ ] **Step 2: Run — FAIL. Step 3: Implement** (PORT; the only transformations: `ENABLE_TIMESFM` env is replaced by `settings.forecast.enabled` checked by the caller — the loader itself is unconditional; venv path parameterized; `FORECAST_DUMP` diagnostic is **deliberately not ported** — superseded by the batch design, note in commit).
- [ ] **Step 4: Run — 4 passed. Step 5: Commit** — `feat(forecast): TimesFM 2.5 loader + retryable single-threaded warm-up (port)`

---

## Task 4: `TimesFMForecaster.forecast_batch` (`timesfm.py`, part 2)

**Files:**
- Modify: `src/tradingbot/forecast/timesfm.py`
- Test: `tests/forecast/test_batch.py`

**Interfaces:**
- Produces:

```python
class TimesFMForecaster:                       # satisfies Forecaster
    def __init__(self, settings: ForecastSettings) -> None: ...
    @classmethod
    def from_settings(cls, settings: Settings) -> "TimesFMForecaster": ...
    def warm_up(self) -> bool: ...             # delegates to module warm_up(venv_path)
    def forecast_batch(self, series: dict[str, list[float]], horizon: int | None = None
                       ) -> dict[str, Forecast]: ...
```

  Semantics of `forecast_batch` (horizon defaults to `settings.horizon`):
  1. Raise `ForecastUnavailable(_timesfm_error)` if the model is not loaded (callers run `warm_up()` first; this is the defensive path).
  2. **Exclude** symbols whose series has `< 2` points — absent from the result (the pipeline maps absent → `DropReason.NO_FORECAST`). Empty input → `{}` without touching the model.
  3. ONE model call: `points, quantiles = _timesfm_model.forecast(horizon=horizon, inputs=[np.array(s, dtype=np.float32) for s in ordered_series])` — **the whole batch in a single call** (spec §2 stage 4).
  4. Per symbol *i*: `pts = points[i][:horizon]`; quantile deciles at indices **1/5/9** (q10/q50/q90 — TimesFM 2.5's head: index 0 = mean, 1–9 = deciles; ported); `predicted_return = round((pts[-1] − last_close)/last_close, 6)`; `direction = direction_for(...)`; `confidence = combined_confidence(last_close, pts[-1], q10[-1], q90[-1])`; wrap in domain `Forecast` with `Quantiles(q10, q50, q90)` (floats rounded 4, as SRC).

- [ ] **Step 1: Write failing tests** with a **deterministic fake model** installed as `_timesfm_model` (no fake sys.modules needed — set the module global directly via monkeypatch):

```python
import numpy as np
import pytest

import tradingbot.forecast.timesfm as tf
from tradingbot.config.settings import ForecastSettings
from tradingbot.domain.enums import TradeDirection
from tradingbot.forecast.base import ForecastUnavailable


class DeterministicModel:
    """forecast(horizon, inputs) -> each series' points = last value * (1 + 0.002*(j+1)) drift,
    quantiles = tight band around points. Deterministic per input order and identical whether
    called with a batch or a single series — the parity oracle."""
    def forecast(self, horizon, inputs):
        points = np.array([[float(s[-1]) * (1 + 0.002 * (j + 1)) for j in range(horizon)]
                           for s in inputs])
        q = np.zeros((len(inputs), horizon, 10))
        for i in range(len(inputs)):
            q[i, :, 1] = points[i] * 0.99   # q10
            q[i, :, 5] = points[i]          # q50
            q[i, :, 9] = points[i] * 1.01   # q90
        return points, q


@pytest.fixture
def forecaster(monkeypatch):
    monkeypatch.setattr(tf, "_timesfm_model", DeterministicModel())
    monkeypatch.setattr(tf, "_timesfm_error", None)
    return tf.TimesFMForecaster(ForecastSettings())


def test_batch_forecasts_all_symbols_in_one_call(forecaster, monkeypatch):
    calls = []
    real = tf._timesfm_model.forecast
    monkeypatch.setattr(tf._timesfm_model, "forecast",
                        lambda horizon, inputs: (calls.append(len(inputs)) or real(horizon, inputs)))
    out = forecaster.forecast_batch({"A": [100.0] * 20, "B": [50.0] * 20, "C": [10.0] * 20})
    assert set(out) == {"A", "B", "C"}
    assert calls == [3]                     # ONE call, all three series


def test_batch_matches_single_series_results(forecaster):
    series = {"A": [100.0 + i for i in range(30)], "B": [200.0 - i for i in range(30)]}
    batch = forecaster.forecast_batch(series)
    singles = {s: forecaster.forecast_batch({s: v})[s] for s, v in series.items()}
    for s in series:
        assert batch[s].predicted_return == singles[s].predicted_return
        assert batch[s].confidence == singles[s].confidence            # parity (spec open-item)


def test_short_and_empty_series_excluded(forecaster):
    out = forecaster.forecast_batch({"OK": [100.0] * 20, "SHORT": [100.0], "EMPTY": []})
    assert set(out) == {"OK"}
    assert forecaster.forecast_batch({}) == {}


def test_direction_threshold_preserved(forecaster):
    # DeterministicModel drifts +1.0% over 5 steps (0.2%/step): day-5 = +1.0% → BULLISH;
    # with horizon=2 the day-2 point is +0.4% → NEUTRAL (the ±0.5% SRC threshold).
    out5 = forecaster.forecast_batch({"A": [100.0] * 20}, horizon=5)
    out2 = forecaster.forecast_batch({"A": [100.0] * 20}, horizon=2)
    assert out5["A"].direction is TradeDirection.BULLISH
    assert out2["A"].direction is TradeDirection.NEUTRAL


def test_unavailable_raises(monkeypatch):
    monkeypatch.setattr(tf, "_timesfm_model", None)
    monkeypatch.setattr(tf, "_timesfm_error", "no torch")
    with pytest.raises(ForecastUnavailable):
        tf.TimesFMForecaster(ForecastSettings()).forecast_batch({"A": [1.0, 2.0]})
```

- [ ] **Step 2: Run — FAIL. Step 3: Implement** per the semantics above. **Step 4: Run — 5 passed; full `tests/forecast/` green.** 
- [ ] **Step 5: Commit** — `feat(forecast): batched TimesFMForecaster (one model call per run, parity-tested)`

---

## Task 5: live parity test + green gate

**Files:**
- Create: `tests/forecast/test_live_parity.py`
- Test: full suite

**Interfaces:** none new — closes the spec's open-item ("Phase 4 confirms the batch path matches the per-call results") against the REAL model, opt-in.

- [ ] **Step 1: Write the gated live test:**

```python
import os

import pytest

import tradingbot.forecast.timesfm as tf
from tradingbot.config.settings import ForecastSettings

pytestmark = pytest.mark.skipif(os.environ.get("LIVE_TESTS") != "1",
                                reason="loads the real 2GB TimesFM model — opt-in")


def test_real_model_batch_equals_singles():
    fc = tf.TimesFMForecaster(ForecastSettings(venv_path=os.environ.get("TIMESFM_VENV")))
    assert fc.warm_up(), tf._timesfm_error
    series = {"UP": [100.0 + i for i in range(60)], "DOWN": [200.0 - i for i in range(60)],
              "FLAT": [150.0 + (i % 2) * 0.1 for i in range(60)]}
    batch = fc.forecast_batch(series)
    for sym, closes in series.items():
        single = fc.forecast_batch({sym: closes})[sym]
        assert abs(batch[sym].predicted_return - single.predicted_return) < 1e-4, sym
```

  (Tolerance 1e-4, not equality: torch batching may reorder float ops. If the real model shows larger batch-vs-single divergence, STOP and report the measured delta — that decides whether stage 4 can batch — do not loosen the tolerance silently.)
- [ ] **Step 2: Run the full suite + ruff — all green** (live test skipped without the env var). If the MiroFish `.venv-timesfm` is available, run once with `LIVE_TESTS=1 TIMESFM_VENV=/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/.venv-timesfm` and report the parity result.
- [ ] **Step 3: Commit** — `test(forecast): live batch-vs-single parity gate (Phase 4 complete)`

---

## Definition of done (Phase 4)

- `Forecaster` Protocol is batch-first; `TimesFMForecaster` makes exactly ONE model call per run.
- All SRC behavioral invariants preserved (direction ±0.5%, multiplicative quantile-aware confidence, neutral guards, retryable warm-up, no fallback).
- Batch-vs-single parity proven with the deterministic fake; live parity test exists (opt-in) and, if run, its measured result is reported.
- Full suite + ruff green; one commit per task.

**Named deferrals:** wiring `warm_up()`/`forecast_batch()` into the pipeline is Phase 6 (stage 4); `FORECAST_DUMP` diagnostics deliberately not ported.

**Next plan:** Phase 5 (gates + scoring — pure ports, plus the sector/regime bulk-data loaders deferred from Phase 3).

# TradingBot Phase 6 — Pipeline & Screener Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the staged async orchestration layer — `pipeline/` (fetch stage, decide stage, `Screener` facade) plus the `RunResult` domain model — wiring the committed Phase 1–5 modules into the spec §2 flow: discover → guard → bulk context → rate-limited per-symbol fetch → batched forecast → gates+scoring → `RunResult`.

**Architecture:** The pipeline is `async`; sync subsystems are offloaded exactly as their docstrings prescribe (`asyncio.to_thread` ONCE per run for discovery and for `forecast_batch`; gates/scoring run sync in-loop — pure CPU). Per-symbol IO fans out with `asyncio.gather` bounded by a semaphore; Fyers pacing is already inside the provider (`TokenBucket` via `acall`), so the semaphore only bounds task fan-out. All composition-time wiring (which gates are enabled, whether forecasting runs) happens in `Screener.from_settings` — closing the reviewers' "`enabled` flags are currently unread" notes from Phases 4–5.

**Tech Stack:** Python 3.11, asyncio, pytest (fakes for every provider — no network in tests).

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. Port source (**SRC**, read-only): `/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab` (`services/nubra_client/equity_runner.py` `_process_symbol`/`run_once` + `equity_context_builder.py` are the behavioral reference).
- Prerequisites: Phases 3–5 merged (commit `a2cd4e4` state, 254 tests green). The interface inventory below is ground truth — consume EXACT signatures; do not invent.
- **Candidacy semantics (SRC-faithful):** every candidate is buy-intent; TimesFM annotates and never filters EXCEPT the SRC `no_forecast` rule — a symbol whose forecast is unavailable is dropped `NO_FORECAST` (SRC raised/skipped before the candidacy branch; no formulaic fallback, no fabricated upside). `forecast.enabled=False` behaves exactly like SRC `ENABLE_TIMESFM=false`: warm-up fails → every forecastable symbol drops `NO_FORECAST`.
- **History semantics (SRC-faithful):** ohlcv fetch failure → `closes=[float(ltp)]`, `history_ok=False`; then `len(closes) < min_bars` drops as `DATA_THROTTLED` when `history_ok=False` else `INSUFFICIENT_HISTORY`.
- **Named deferrals (Phase 7+, NOT bugs):** deals/shareholding/delivery collectors were never ported (out of Phase 3 scope) → `ConvictionFlags.has_deal=None, promoter_trend=None` and `catalyst_stack(source_audit, has_deal=None)`; storage/CLI/API consume `RunResult` in Phase 7.
- Per-symbol fail-soft: any unexpected exception in a symbol's fetch drops that symbol (`DropReason.DATA_THROTTLED` if rate-limit-shaped, else record in `RunResult.errors`) — never crashes the run.
- Full suite + ruff green at end; commit per task; parallel-safety rules as prior phases (explicit-path `git add`, index.lock retry, own-test-paths until integration task).

## Interface ground truth (from the committed tree — consume, don't redefine)

- `MarketDataProvider` (async): `price(symbol)->Decimal`, `ohlcv(symbol, lookback, interval="1d")->list[Bar]`, `circuit(symbol)->Circuit|None`, `options(symbol)->OptionSnapshot|None`. `FyersProvider.from_settings(settings)`.
- `NewsAggregator.from_settings(settings, *, limiter=None)`; `async collect(symbol)->NewsBundle` where `NewsBundle(items, sentiment: SentimentResult, source_audit: dict, provider_mode: str)`.
- `CatalystDiscovery.from_settings(settings)`; **sync** `discover(today=None)->dict[str, Catalyst]` (no guard inside).
- `SurveillanceLiquidityGuard.from_settings(settings)`; **sync** `filter(symbols, today=None)->list[str]`, `top_by_turnover(symbols, n)->list[str]`.
- `MarketContextBuilder.from_settings(settings, market)`; **async** `build(turnover_cr: dict[str,float])->MarketContext`.
- `TimesFMForecaster.from_settings(settings)`; **sync** `warm_up()->bool`, **sync** `forecast_batch(series, horizon=None)->dict[str, Forecast]` (raises `ForecastUnavailable` if model unloaded; symbols with <2 points silently absent).
- Gates (all **sync** `evaluate(candidate, market, ctx)->GateResult`): `CircuitGate(settings.gates_circuit)`, `SectorGate(settings.gates_sector)`, `RegimeGate(settings.gates_regime)`, `FirstFifteenGate(settings.gates_first15, clock=None)`, `CompositeGate(list)` (first block wins). NOTE: `FirstFifteenGate` is NOT exported from `gates/__init__.py` yet — Task 1 fixes.
- `WatchlistScorer(settings.scoring)` (no from_settings); **sync** `score(candidate, market, forecast|None, flags, ctx)->ScoredResult`.
- `scoring/flags.py`: `pcr_label(pcr)`, `oi_buildup_label(call_chg, put_chg)`, `catalyst_stack(source_audit, has_deal)->(count, sources, stacked)`.
- Domain: `Candidate(symbol, catalyst)`, `MarketData(ltp, closes, history_ok, circuit, options, intraday_bars=None)`, `ConvictionFlags(sentiment, catalyst_stack, has_deal, promoter_trend, oi_buildup)`, `Probable(symbol, status, drop_reason, score, forecast, market, catalyst, flags)`, enums as committed.

---

## File Structure (Phase 6)

```
src/tradingbot/
├── domain/models.py            # MODIFY: + RunResult
├── config/settings.py          # MODIFY: + PipelineSettings; load_config mapping
├── gates/__init__.py           # MODIFY: export FirstFifteenGate
├── providers/discovery/guard.py# MODIFY: + public turnover_cr() accessor
└── pipeline/
    ├── __init__.py             # exports Screener, RunResult re-export
    ├── fetch.py                # per-symbol market+news fetch stage (async, fail-soft)
    ├── decide.py               # pure decide stage: pre-gate drops + gates + flags + score → Probable
    └── screener.py             # Screener facade: from_settings composition + async run()
tests/pipeline/  (+ appends to tests/domain/, tests/config/, tests/gates/, tests/providers/)
```

---

## Task 1: RunResult + PipelineSettings + export/accessor gaps (sequential — do first)

**Files:**
- Modify: `src/tradingbot/domain/models.py`, `src/tradingbot/config/settings.py`, `src/tradingbot/gates/__init__.py`, `src/tradingbot/providers/discovery/guard.py`
- Test: append to `tests/domain/test_models.py`, `tests/config/test_settings.py`, `tests/gates/test_gates.py` (or the committed gates test module), `tests/providers/discovery/` guard tests

**Interfaces (produced):**
- `RunResult` (frozen dataclass, `domain/models.py`):

```python
@dataclass(frozen=True)
class RunResult:
    run_date: str                      # ISO date (IST), stamped by the caller
    universe_size: int                 # candidates after guard/cap
    probables: list[Probable]          # every screened symbol, elected + dropped
    errors: dict[str, str]             # symbol -> error string (fetch crashes, fail-soft)

    @property
    def elected(self) -> list[Probable]:
        return [p for p in self.probables if p.status is Status.ELECTED]

    @property
    def counts(self) -> dict[str, int]:
        return {"total": len(self.probables), "elected": len(self.elected),
                "dropped": len(self.probables) - len(self.elected), "errors": len(self.errors)}
```

- `PipelineSettings(BaseModel, extra="ignore")`: `concurrency: int = 8` (semaphore bound for per-symbol fetch fan-out), `min_bars: int = 10` (SRC `signal.min_bars_for_signal`), `history_lookback: int = 20` (SRC context builder lookback). `Settings` gains `pipeline: PipelineSettings = PipelineSettings()`. `load_config` maps `data["signal"]["min_bars_for_signal"] -> pipeline.min_bars` and `data["runner"]["max_workers"] -> pipeline.concurrency` (only if present).
- `gates/__init__.py` additionally exports `FirstFifteenGate` (and `gap_status`).
- `SurveillanceLiquidityGuard.turnover_cr() -> dict[str, float]`: public accessor returning the last `filter()` call's turnover map converted lakhs→crore (`{sym: lacs/100.0}`); `{}` if `filter()` hasn't run or bhavcopy failed. (The context builder needs `turnover_cr`; `top_by_turnover` already uses this state internally — this only exposes it, converted.)

- [ ] **Step 1: Append failing tests** (exact code):

```python
# tests/domain/test_models.py
def test_run_result_counts_and_elected():
    from tradingbot.domain.models import RunResult
    p_e = _make_probable(status=Status.ELECTED)      # use the module's existing Probable factory/fixture pattern
    p_d = _make_probable(status=Status.DROPPED, drop_reason=DropReason.SECTOR_DOWN)
    rr = RunResult(run_date="2026-07-08", universe_size=2, probables=[p_e, p_d], errors={"X": "boom"})
    assert [q.symbol for q in rr.elected] == [p_e.symbol]
    assert rr.counts == {"total": 2, "elected": 1, "dropped": 1, "errors": 1}

# tests/config/test_settings.py
def test_pipeline_settings_defaults_and_mapping():
    from tradingbot.config.settings import Settings, load_config
    assert Settings().pipeline.concurrency == 8 and Settings().pipeline.min_bars == 10
    s = load_config({"signal": {"min_bars_for_signal": 12}, "runner": {"max_workers": 3}})
    assert s.pipeline.min_bars == 12 and s.pipeline.concurrency == 3

# tests/gates/... (existing module)
def test_first_fifteen_exported():
    from tradingbot.gates import FirstFifteenGate, gap_status  # noqa: F401

# guard tests
def test_turnover_cr_accessor_after_filter(...):
    # patch the bhavcopy fetch to a known lakhs map, run filter(), assert
    # guard.turnover_cr() == {sym: lacs/100.0}; assert {} before any filter().
```

(For `_make_probable`: reuse/extend the existing Probable construction already present in `tests/domain/test_models.py` — do not invent a new fixture style.)

- [ ] **Step 2: verify FAIL → Step 3: implement → Step 4: verify PASS (own test paths only) → Step 5: Commit** — `feat(domain,config): RunResult + PipelineSettings; export/accessor gaps (Phase 6)`

---

## Task 2: `pipeline/fetch.py` — per-symbol fetch stage (Group A)

**Files:**
- Create: `src/tradingbot/pipeline/__init__.py` (empty for now), `src/tradingbot/pipeline/fetch.py`
- Test: `tests/pipeline/__init__.py` (empty), `tests/pipeline/test_fetch.py`

**Interfaces:**
- Consumes: `MarketDataProvider`, `NewsAggregator.collect`, domain models, `PipelineSettings`, `First15Settings`.
- Produces:

```python
@dataclass(frozen=True)
class FetchResult:
    symbol: str
    market: MarketData | None          # None only when even LTP failed (symbol errored)
    news: NewsBundle | None            # None when the aggregator itself crashed (rare; sources fail soft)
    error: str | None                  # non-None => symbol errored (fail-soft)

async def fetch_symbol(symbol: str, market: MarketDataProvider, news: NewsAggregator,
                       pipeline: PipelineSettings, first15: First15Settings) -> FetchResult: ...

async def fetch_all(symbols: list[str], market: MarketDataProvider, news: NewsAggregator,
                    pipeline: PipelineSettings, first15: First15Settings) -> list[FetchResult]: ...
```

**Semantics (PORT of SRC `equity_context_builder.build_equity_context` + `_process_symbol` data assembly):**
1. `fetch_symbol`: `ltp = await market.price(symbol)` — if THIS raises, return `FetchResult(symbol, None, None, error=str(exc))` (symbol errored; nothing else attempted).
2. `closes`/`history_ok`: `bars = await market.ohlcv(symbol, lookback=pipeline.history_lookback)`; `closes=[b.close for b in bars]`; empty list or exception → `closes=[float(ltp)]`, `history_ok=False` (SRC guard).
3. `circuit = await market.circuit(symbol)` and `options = await market.options(symbol)` — each independently fail-soft to `None` on exception.
4. `intraday_bars`: fetched ONLY when `first15.enabled` — `await market.ohlcv(symbol, lookback=375, interval="5")`, fail-soft `None`.
5. `news = await news_aggregator.collect(symbol)` — fail-soft to `None` on exception (aggregator already fails soft per source; this guards a total crash).
6. Steps 2–5 run concurrently via `asyncio.gather` (they are independent awaits for one symbol).
7. `fetch_all`: `asyncio.gather` over symbols bounded by `asyncio.Semaphore(pipeline.concurrency)`; NEVER raises — every exception is captured in the symbol's `FetchResult.error`.

- [ ] **Step 1: Write failing tests** — with a fake provider + fake aggregator (async fakes returning domain objects): happy path assembles MarketData exactly; ohlcv-raises → `history_ok=False, closes=[float(ltp)]`; price-raises → `market is None, error set`; circuit/options raise independently → those fields None, rest intact; intraday fetched only when `first15.enabled=True` (assert fake's call log); `fetch_all` with a symbol whose price raises → other symbols unaffected; semaphore bound respected (fake records max concurrent — use an asyncio.Event-based gate to prove ≤ concurrency).
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/pipeline/test_fetch.py only) → Step 5: Commit** — `feat(pipeline): per-symbol fetch stage (fail-soft, semaphore-bounded)`

---

## Task 3: `pipeline/decide.py` — pure decide stage (Group B)

**Files:**
- Create: `src/tradingbot/pipeline/decide.py`
- Test: `tests/pipeline/test_decide.py`

**Interfaces:**
- Consumes: `FetchResult` (import from `tradingbot.pipeline.fetch`), `Forecast`, `MarketContext`, `CompositeGate`, `WatchlistScorer`, `scoring.flags`, `PipelineSettings`.
- Produces:

```python
def decide_symbol(fr: FetchResult, catalyst: Catalyst, forecast: Forecast | None,
                  gate: CompositeGate, scorer: WatchlistScorer, ctx: MarketContext,
                  pipeline: PipelineSettings, *, forecasting_enabled: bool) -> Probable: ...

def decide_all(results: list[FetchResult], catalysts: dict[str, Catalyst],
               forecasts: dict[str, Forecast], gate: CompositeGate, scorer: WatchlistScorer,
               ctx: MarketContext, pipeline: PipelineSettings, *, forecasting_enabled: bool) -> list[Probable]: ...
```

**Semantics (PORT of SRC `_process_symbol` decision order, candidacy mode):**
1. Build `candidate = Candidate(fr.symbol, catalyst)`.
2. **History pre-gate** (before anything else, SRC order): `market.history_ok is False or len(market.closes) < pipeline.min_bars` → dropped, reason `DATA_THROTTLED` if `not history_ok` else `INSUFFICIENT_HISTORY`; score=None, forecast=None.
3. **Forecast rule:** if `forecasting_enabled` and `fr.symbol not in forecasts` → dropped `NO_FORECAST` (SRC: no fabricated upside; symbols with <2 closes or an unloaded model are absent from `forecast_batch`'s dict). If `forecasting_enabled is False` → the SRC `ENABLE_TIMESFM=false` contract: dropped `NO_FORECAST` as well (`forecast=None`). The elected path always carries a real `Forecast`.
4. **Flags (soft, never gate):** `ConvictionFlags(sentiment=fr.news.sentiment.score if fr.news else None, catalyst_stack=catalyst_stack(fr.news.source_audit if fr.news else {}, has_deal=None)[0], has_deal=None, promoter_trend=None, oi_buildup=oi_buildup_label(market.options.call_oi_change, market.options.put_oi_change) if market.options else None)`.
5. **Gates:** `gate.evaluate(candidate, market, ctx)` → blocked ⇒ dropped with the gate's `DropReason`; still SCORED (SRC run docs carry scores on gate-dropped rows).
6. **Score:** `scorer.score(candidate, market, forecast, flags, ctx)` for every symbol that passed the history pre-gate (dropped-by-gate included; history-dropped and errored symbols get score=None).
7. `decide_all`: errored FetchResults (`fr.error is not None` / `market is None`) produce NO Probable (they land in `RunResult.errors` — Task 4); order of probables: elected first, then dropped, each sorted by score desc (None last) — the SRC `run_to_doc` ordering.

- [ ] **Step 1: Write failing tests** — pure fixtures, no asyncio: history_ok=False short closes → DATA_THROTTLED; history_ok=True short closes → INSUFFICIENT_HISTORY; missing forecast (enabled) → NO_FORECAST; forecasting disabled → NO_FORECAST for all; gate-blocked symbol is dropped with the gate reason AND has a non-None score; elected symbol carries forecast+score+flags; flags assembled from news/options exactly (incl. all-None when news/options absent); errored FetchResult produces no Probable; ordering (elected-first, score desc, None-score last).
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/pipeline/test_decide.py only) → Step 5: Commit** — `feat(pipeline): pure decide stage (history pre-gate, no-forecast rule, gates+score)`

---

## Task 4: `pipeline/screener.py` — the facade (after Tasks 1–3)

**Files:**
- Create: `src/tradingbot/pipeline/screener.py`; Modify: `src/tradingbot/pipeline/__init__.py` (export `Screener`; re-export `RunResult`)
- Test: `tests/pipeline/test_screener.py`

**Interfaces:**

```python
class Screener:
    def __init__(self, *, discovery: CatalystDiscovery, guard: SurveillanceLiquidityGuard,
                 market: MarketDataProvider, news: NewsAggregator, context_builder: MarketContextBuilder,
                 forecaster: Forecaster | None, gate: CompositeGate, scorer: WatchlistScorer,
                 settings: Settings) -> None: ...

    @classmethod
    def from_settings(cls, settings: Settings) -> "Screener": ...

    async def run(self, today: date | None = None) -> RunResult: ...
```

**`from_settings` composition (the enabled-flags wiring the Phase 4/5 reviewers called out):**
- `market = FyersProvider.from_settings(settings)` (it constructs its own `TokenBucket` internally per its committed signature — do not fight that); `news = NewsAggregator.from_settings(settings)` (pass a shared limiter only if you deliberately want news+market on one budget; default: omit, matching each factory's committed behavior). Follow the committed constructors exactly — do not add new parameters to them.
- Gates list built from flags: `gates_circuit.enabled` → `CircuitGate`, `gates_regime.enabled` → `RegimeGate`, `gates_sector.enabled` → `SectorGate`, `gates_first15.enabled` → `FirstFifteenGate` — in THAT order (SRC gate order: circuit → regime → sector → first15); `CompositeGate(gates)`.
- `forecaster = TimesFMForecaster.from_settings(settings) if settings.forecast.enabled else None` (None ⇒ `forecasting_enabled=False` downstream — `ForecastSettings.enabled` is now read).
- `scorer = WatchlistScorer(settings.scoring)`; `context_builder = MarketContextBuilder.from_settings(settings, market)`.

**`run()` stages (spec §2, exact order):**
1. `catalysts: dict[str, Catalyst] = await asyncio.to_thread(self._discovery.discover, today)`.
2. `symbols = await asyncio.to_thread(self._guard.filter, sorted(catalysts), today)`; if `settings.discovery.max_symbols > 0 and len(symbols) > max_symbols`: `symbols = self._guard.top_by_turnover(symbols, max_symbols)`.
3. `ctx = await self._context_builder.build(self._guard.turnover_cr())`.
4. `fetched = await fetch_all(symbols, ...)`.
5. Forecast: if forecaster: `ok = await asyncio.to_thread(self._forecaster.warm_up)`; series = `{fr.symbol: fr.market.closes for fr in fetched if fr.market and fr.market.history_ok and len(fr.market.closes) >= 2}`; `forecasts = await asyncio.to_thread(self._forecaster.forecast_batch, series, settings.forecast.horizon)` — wrap in `try/except ForecastUnavailable: forecasts = {}` and treat warm-up failure the same (`forecasts = {}` → decide drops NO_FORECAST; log a warning). If no forecaster: `forecasts = {}`, `forecasting_enabled=False`.
6. `probables = decide_all(fetched, catalysts, forecasts, gate, scorer, ctx, pipeline, forecasting_enabled=...)`.
7. `errors = {fr.symbol: fr.error for fr in fetched if fr.error}`; `run_date = (today or IST today).isoformat()`; return `RunResult(run_date, universe_size=len(symbols), probables, errors)`.

- [ ] **Step 1: Write failing tests** — all-fakes end-to-end: `from_settings`-equivalent manual composition with fakes; run() elects a good symbol and drops a sector-down one; disabled circuit gate (settings) really excludes it from the composite (fake ctx forces what would have blocked); `forecast.enabled=False` → all NO_FORECAST; `ForecastUnavailable` from batch → all NO_FORECAST + run completes; max_symbols cap routes through `top_by_turnover`; errored symbol lands in `RunResult.errors` and not in probables; `universe_size` == post-guard count. Use a fixed `today=date(2026, 7, 8)` (determinism).
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/pipeline/ only) → Step 5: Commit** — `feat(pipeline): Screener facade — staged async run (discover→context→fetch→forecast→decide)`

---

## Task 5: Pipeline integration + green gate (last)

**Files:**
- Create: `tests/test_pipeline_integration.py`
- Test: full suite

- [ ] **Step 1: Write the integration test** — realistic fakes across ALL layers in one flow (5 symbols: 1 elected, 1 sector-down-but-scored, 1 insufficient-history, 1 no-forecast, 1 errored) asserting the full `RunResult` shape: counts, elected-first ordering, per-Probable field integrity (catalyst carried from discovery; flags from news/options; gate reason strings), and that `Screener.run()` never raises when every provider misbehaves at once (all-fail run → all symbols in errors/dropped, `RunResult` still returned).
- [ ] **Step 2: Run the FULL suite + ruff** (`uv run --extra dev pytest -q && uv run --extra dev ruff check src tests`) — fix any cross-module breakage (report what).
- [ ] **Step 3: Commit** — `test(pipeline): end-to-end pipeline integration green gate (Phase 6 complete)`

---

## Definition of done (Phase 6)

- `Screener.from_settings(settings).run()` produces a `RunResult` end-to-end against fakes; every stage honors the committed interfaces; enabled-flags are composition-time-live; SRC drop semantics (DATA_THROTTLED / INSUFFICIENT_HISTORY / NO_FORECAST / gate reasons) verified by tests; full suite + ruff green.
- **Next (Phase 7):** storage (`RunDoc` ⇄ `RunResult` mapping to the existing Mongo shape), CLI (`screen` command stamping run metadata), API/dashboard 7a — per the dashboard spec.

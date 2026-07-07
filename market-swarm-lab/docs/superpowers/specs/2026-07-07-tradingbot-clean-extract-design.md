# TradingBot — Clean Extract & Re-architecture Design

**Date:** 2026-07-07
**Status:** Approved design → implementation planning
**Target:** A new standalone project at `~/Code/own/TradingBot`

---

## Goal

Extract the India catalyst-swing screener out of the MiroFish monorepo
(`~/Code/own/TradingBotMiroFish/market-swarm-lab`, ~7,600 LOC / 629 tests) into a clean,
standalone, properly-packaged Python project with:

- **A staged, async pipeline** that fixes the current ~16-minute full-universe runtime and
  residual `data_throttled` drops.
- **Proper OOP / design patterns** (Strategy, Registry/Factory, Adapter, Facade, Pipeline)
  with strict layering, so every unit is independently testable and swappable.
- **All the hardening/correctness work preserved** — the concurrency, rate-limit,
  band-off-base, candidacy-mode, and TimesFM-warmup fixes carry over as tests, so we cannot
  regress the bugs fixed in this session.

**Non-goals:** no new trading features; no US-market code (Schwab/Kalshi/etc. is left behind);
no live-order execution changes (screen/watchlist is the focus).

## Scope decision

**Clean extract + restructure** (chosen over full rewrite and in-place restructure). Move only
the India-screener code into a fresh package, refactor into clean layers/patterns as we go, and
carry the 629 tests. Preserves reviewed/tested logic; drops the monorepo baggage. The old code
stays untouched in MiroFish as a working fallback until parity is proven (Phase 8).

---

## 1. Package layout & layering

```
TradingBot/                         # ~/Code/own/TradingBot
├── pyproject.toml                  # package, deps, entry-point scripts
├── src/tradingbot/
│   ├── domain/                     # pure data models + enums, NO IO
│   │   ├── models.py               #   Candidate, MarketData, Forecast, Probable, RunDoc, ...
│   │   └── enums.py                #   TradeDirection, DropReason, CatalystType, Status
│   ├── config/                     # typed config (dataclass/pydantic) + loader
│   ├── providers/                  # ALL external IO behind interfaces
│   │   ├── market/                 #   FyersProvider (price/ohlcv/circuit/options) — async
│   │   ├── news/                   #   NSE announcements, Google, USFDA, insider, PIB, Reddit (+ sentiment engines + aggregator — folded into the news layer)
│   │   ├── discovery/              #   catalyst calendar + announcements + surveillance/liquidity guard
│   │   └── ratelimit.py            #   TokenBucket
│   ├── forecast/                   # TimesFMForecaster (batched, warm-up)
│   ├── gates/                      # EntryGate ABC + Circuit/Sector/Regime/FirstFifteen (pure)
│   ├── scoring/                    # WatchlistScorer (5-factor), catalyst-stack
│   ├── pipeline/                   # the staged orchestrator
│   │   ├── stages.py               #   discover → bulk → fetch → forecast → gate → score → persist
│   │   └── screener.py             #   Screener facade (run() → RunResult)
│   ├── storage/                    # MongoRunStore + backtest reader
│   ├── cli/                        # commands (screen, backtest, login, exits, snapshot)
│   └── api/                        # FastAPI dashboard (thin — reads storage)
├── tests/                          # carried over + new (unit per module, integration per stage)
└── data/                           # bundled fixtures (sector snapshot, etc.)
```

**Layering rule (dependency direction, enforced):**
`domain` ← everything; `providers`/`forecast`/`gates`/`scoring` depend only on `domain` +
interfaces; `pipeline` wires them; `cli`/`api` are thin entry points. Nothing imports "up."

**Patterns:** Strategy (gates, scorers, news sources), Registry/Factory (`from_config` → provider
by name — already present in the code), Adapter (each external API behind a domain interface),
Facade (`Screener.run()`), Pipeline (the stages).

---

## 2. Staged pipeline (async, rate-limited, batched)

```
Screener.run(config) → RunResult
  1. DISCOVER          CatalystDiscovery → set[Candidate]         (2 NSE calls, once)
  │                    + SurveillanceLiquidityGuard (ASM/GSM + ₹5cr)
  2. BULK MARKET DATA  fetched ONCE, not per-symbol:              (~5 calls total)
  │                    sector snapshot · regime index · bulk/block deals · FII-DII · pre-open
  3. FETCH  (async, rate-limited) ── the parallel stage ──        (N symbols)
  │         per candidate concurrently under a TokenBucket:
  │         price · daily OHLCV · circuit(depth) · option-chain · news
  4. FORECAST  (batched)   ONE TimesFM call for ALL series        (1 call, not N)
  5. GATE + SCORE  (pure CPU, no IO):                             (in-memory)
  │         circuit/sector/regime gates (candidacy) → elected? ; WatchlistScorer + catalyst-stack
  6. PERSIST       MongoRunStore.save(RunDoc)  + return RunResult
```

**Three speed wins vs the current per-symbol-does-everything loop:**

1. **Market-wide data fetched once** (stage 2) — sector/regime/deals/FII-DII/pre-open were
   re-fetched or hit per symbol; now ~5 calls total instead of ~5×N.
2. **Async IO + TokenBucket** (stage 3) — replaces the current serial rate-gate. `asyncio`
   fires all per-symbol fetches concurrently; the `TokenBucket` (e.g. capacity 10, refill 10/s)
   lets them **burst to Fyers' real limit** instead of a strict 0.13s gap. This is the main fix
   for both the slowness and the residual `data_throttled`.
3. **Batched TimesFM** (stage 4) — `forecast_batch(inputs=[all series])` in ONE call; currently
   called N times serially. TimesFM natively accepts a batch.

**Concurrency model:** the pipeline is `async`; stage 3's fetch is the concurrent part
(`asyncio.gather` + semaphore + token bucket). TimesFM (stage 4) is CPU/GIL-bound so it runs
once as a batch after IO completes — no thread contention. Stages 5–6 are fast in-memory.
Net wall-clock ≈ *slowest IO batch + one TimesFM batch*, not *N × (all IO + one forecast)*.

**Error handling:** each stage fails soft per-candidate (a symbol erroring in fetch is dropped
with a reason, never crashes the run). A genuinely rate-limited fetch after token-bucket retries
is marked `data_throttled` (retry next run), distinct from a real data gap (`insufficient_history`).

---

## 3. Module interfaces (contracts)

```python
# domain/models.py — pure data, no behavior, no IO
@dataclass(frozen=True)
class Candidate:
    symbol: str
    catalyst: Catalyst                 # type + description + source + date
@dataclass(frozen=True)
class MarketData:
    ltp: Decimal; closes: list[float]; history_ok: bool
    circuit: Circuit | None; options: OptionSnapshot | None
@dataclass(frozen=True)
class Forecast:
    predicted_return: float; direction: TradeDirection; confidence: float; quantiles: Quantiles
@dataclass(frozen=True)
class Probable:
    symbol: str; status: Status; drop_reason: DropReason | None
    score: float | None; forecast: Forecast | None
    market: MarketData; catalyst: Catalyst; flags: ConvictionFlags

# providers/market/base.py
class MarketDataProvider(Protocol):
    async def price(self, sym: str) -> Decimal: ...
    async def ohlcv(self, sym: str, lookback: int) -> list[Bar]: ...
    async def circuit(self, sym: str) -> Circuit | None: ...
    async def options(self, sym: str) -> OptionSnapshot | None: ...

# providers/news/base.py
class NewsSource(Protocol):
    name: str
    async def fetch(self, sym: str) -> tuple[list[NewsItem], str]: ...  # (items, provider_mode: '<name>_live'|'fixture_fallback'|'no_mapping'|'no_credentials'); fixture-fallback, fail-safe

# providers/ratelimit.py
class RateLimiter(Protocol):
    async def acquire(self) -> None: ...                        # TokenBucket: burst N, refill R/s

# gates/base.py — pure, synchronous, no IO (data already fetched)
class EntryGate(ABC):
    @abstractmethod
    def evaluate(self, c: Candidate, m: MarketData, ctx: MarketContext) -> GateResult: ...
# CompositeGate runs Circuit/Sector/Regime/FirstFifteen in order; first block wins.

# scoring/base.py
class Scorer(Protocol):
    def score(self, c: Candidate, m: MarketData, f: Forecast, flags) -> ScoredResult: ...

# forecast/base.py — BATCHED by design
class Forecaster(Protocol):
    def warm_up(self) -> bool: ...                              # retryable, called pre-pool
    def forecast_batch(self, series: dict[str, list[float]]) -> dict[str, Forecast]: ...

# storage/base.py
class RunStore(Protocol):
    def save(self, doc: RunDoc) -> str: ...
    def latest(self) -> RunDoc | None: ...
    def elected_history(self, limit: int) -> list[RunDoc]: ...  # backtest input
```

**What these buy us:** pure gates/scorers unit-test with plain data (no mocks); Fyers→another
broker = new `MarketDataProvider`; a new news source = new `NewsSource` + registry entry, zero
pipeline change; async only at the IO edges; batching is a first-class contract
(`forecast_batch`, not `forecast(one)`).

---

## 4. Testing strategy

| Layer | Test style | Network |
|-------|-----------|---------|
| `domain` | construction/enum | no |
| `gates`, `scoring`, catalyst-stack | pure unit — domain in, result out | no |
| `providers` | one fake per Protocol + parser tests on fixtures; opt-in live smoke | mocked (live env-gated) |
| `forecast` | `forecast_batch` with a fake model; warm-up retry | no |
| `pipeline/stages` | integration — real stages + fake providers/forecaster; flow, fail-soft, drop reasons | no |
| `storage` | round-trip vs local mongo (skip if absent) | local only |
| end-to-end | one screen run, fakes throughout → RunDoc shape | no |

The 629 existing tests carry over ~1:1 (most are already pure). Old per-symbol-runner tests are
rewritten as **stage** tests (smaller surface). New tests only for: `TokenBucket`, the async fetch
stage, `forecast_batch`. **The concurrency-correctness tests from this session (thread-safety,
rate-limit, band-off-base, candidacy, TimesFM warm-up) migrate as-is** — we cannot regress them.

**Coverage gate:** the suite stays green at every phase; no red phase is merged.

---

## 5. Migration order (bottom-up; each phase independently green & committed)

```
Phase 0  Scaffold: pyproject, src/ layout, pytest, ruff              → empty but importable
Phase 1  domain/ (models, enums)                                     → pure, fully tested
Phase 2  providers/ratelimit.py (TokenBucket) + config/              → the perf primitive first
Phase 3  providers/market (Fyers async) + providers/news + discovery → adapters, faked in tests
Phase 4  forecast/ (batched TimesFM + warm-up)                       → batch contract
Phase 5  gates/ + scoring/                                           → carried over, pure
Phase 6  pipeline/ stages + Screener facade                          → wires it; integration tests
Phase 7  storage/ + cli/ + api/ (dashboard)                          → entry points
Phase 8  parity run: new vs old on same universe → diff elected+scores → prove equivalence
```

**Phase 8 (parity) is the safety net:** run new and old on the same catalyst universe the same
day; diff the elected set + scores. Any divergence is a fixed bug (documented) or a regression
(fixed), so the rewrite is provably equivalent-or-better. The old MiroFish code is untouched
until Phase 8 passes.

---

## Open items / notes

- **The Fyers SDK (`fyers-apiv3`) and the NSE `requests` calls are SYNCHRONOUS.** The async
  `MarketDataProvider`/`NewsSource` implementations wrap each blocking call via
  `asyncio.to_thread` (or a shared bounded `ThreadPoolExecutor`), so `asyncio.gather` + the
  `TokenBucket` still overlap the IO waits without a native-async client. `acquire()` the token
  bucket *before* dispatching each wrapped call. This is the concrete mechanism behind stage 3.
- **TokenBucket capacity/refill must be calibrated to Fyers' documented data-API rate limits**
  (verify in Phase 2/3; the "10 / 10-per-sec" figures in §2 are placeholders until confirmed).
- **Batched TimesFM is validated by the current 2.5 API** — `model.forecast(horizon, inputs=[...])`
  already accepts a list of series (variable length handled via `max_context`); Phase 4 confirms
  the batch path matches the per-call results.
- **TimesFM lives in a separate `.venv-timesfm`** today (torch + timesfm, ~2GB, gitignored).
  The new project keeps the same isolation; `forecast/` imports it lazily and warms up once.
- **`.env`** (Fyers token, Reddit creds) carries over, gitignored. Fyers token is daily.
- **Bundled fixtures** (sector-constituent snapshot, news fixtures) move under `data/`.
- **Config** becomes typed (dataclass/pydantic) rather than a raw JSON dict — the loader maps the
  existing `nubra_config.json` shape so behavior is unchanged.
- The `trade` (CALL/PUT/HOLD) field in watchlist output should be relabeled `timesfm_view`
  (bullish/neutral/bearish) — a deferred UX fix noted for the CLI/API stage.

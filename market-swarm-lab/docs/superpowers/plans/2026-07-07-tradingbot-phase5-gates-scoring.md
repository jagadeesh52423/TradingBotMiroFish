# TradingBot Phase 5 — Gates & Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure decision layer — `gates/` (Circuit/Sector/Regime/FirstFifteen + Composite, evaluating **already-fetched** data) and `scoring/` (5-factor WatchlistScorer, conviction labels, catalyst-stack) — plus the `MarketContext` bulk builder (sector snapshot + index trends + regime) that Phase 3's "Named deferrals" assigned to this phase.

**Architecture:** Gates and scorers are **pure and synchronous** — no IO; they consume domain objects (`Candidate`, `MarketData`, `MarketContext`, `Forecast`, flags) and return values. All IO needed to build `MarketContext` (≈11 index-close fetches + the bundled sector-constituents snapshot) happens once per run in `providers/marketwide.py` via the Phase-3 `MarketDataProvider` (already rate-limited). Candidacy semantics carry over: **every candidate is evaluated as buy-intent** — there are no CALL/PUT trade-type guards in the gates (TimesFM annotates, never filters; live-execution gating is a spec non-goal and is not ported).

**Tech Stack:** Python 3.11, stdlib only for gates/scoring; asyncio for the context builder's index fetches; pytest.

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. Port source (**SRC**, read-only): `/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab`.
- Prerequisite: Phase 3 merged (needs `MarketDataProvider`, `Bar`, `NewsBundle.source_audit` shape). Phase 4 is NOT a prerequisite (the scorer consumes a `Forecast` but only via its fields, which exist since Phase 1).
- PORT rule as prior phases: copy SRC logic, apply only listed transformations; formulas/thresholds are reviewed — do not re-derive.
- After Task 1, **Group A (Tasks 2–3, gates/), Group B (Task 4, scoring/), Group C (Task 5, providers/marketwide.py + fixture)** touch disjoint files and may run as parallel coder streams (same parallel-safety rules as Phase 3: explicit-path `git add`, index.lock retry, own-test-paths only until the final task).
- **Behavioral invariants that MUST survive (named tests):** circuit blocks at `last ≥ upper·(1−buffer/100)` with fail-open on unknown (unless `block_on_unknown`); sector/regime trend = last close vs N-day SMA requiring a FULL `ma_days` window; first-15 needs BOTH price-hold and volume-above-normal; scorer renormalizes over present factors (missing ≠ penalty) and the catalyst factor is **directional** (bearish → 0); band factor uses `band_pct` off prev-close base (already guaranteed by `Circuit.band_pct`).
- Full suite + ruff green at end; commit per task.

---

## File Structure (Phase 5)

```
src/tradingbot/
├── domain/models.py            # MODIFY: + MarketContext; MarketData gains intraday_bars: list[Bar] | None = None
├── config/settings.py          # MODIFY: + CircuitGateSettings, SectorSettings, RegimeSettings,
│                               #   First15Settings, ScoringSettings; load_config mapping (old nubra keys)
├── gates/
│   ├── __init__.py
│   ├── base.py                 # EntryGate ABC + GateResult + CompositeGate
│   ├── circuit.py              # CircuitGate
│   ├── sector.py               # SectorGate
│   ├── regime.py               # RegimeGate
│   └── first_fifteen.py        # FirstFifteenGate + pure gap_status(bars, ...)
├── scoring/
│   ├── __init__.py
│   ├── base.py                 # Scorer Protocol + ScoredResult
│   ├── watchlist.py            # WatchlistScorer (5-factor, renormalizing)
│   └── flags.py                # pcr_label, oi_buildup_label, catalyst_stack (pure)
└── providers/marketwide.py     # MarketContextBuilder + trend_from_closes (pure)
data/sector_constituents.json   # bundled snapshot (copied from SRC)
tests/gates/  tests/scoring/  tests/providers/test_marketwide.py
```

---

## Task 1: Domain + settings extensions (sequential — do first)

**Files:**
- Modify: `src/tradingbot/domain/models.py`, `src/tradingbot/config/settings.py`
- Test: append to `tests/domain/test_models.py`, `tests/config/test_settings.py`

**Interfaces (produced for all later tasks):**
- `MarketData` gains `intraday_bars: list[Bar] | None = None` (additive, defaulted — used only by FirstFifteenGate; the pipeline fetches intraday bars only when that gate is enabled).
- `MarketContext` (frozen, in `domain/models.py`):

```python
@dataclass(frozen=True)
class MarketContext:
    regime: str | None                       # "up" | "down" | None(unknown)
    sector_index_of: dict[str, str]          # SYMBOL -> "NSE:NIFTYxxx-INDEX"
    sector_trend: dict[str, str | None]      # index -> "up" | "down" | None
    turnover_cr: dict[str, float]            # SYMBOL -> daily turnover in ₹ crore

    def sector_trend_for(self, symbol: str) -> str | None:
        idx = self.sector_index_of.get(symbol.upper())
        return self.sector_trend.get(idx) if idx else None

    def turnover_for(self, symbol: str) -> float | None:
        return self.turnover_cr.get(symbol.upper())
```

- Settings (all with the shown defaults; `extra="ignore"`):
  - `CircuitGateSettings(enabled: bool = True, upper_band_buffer_pct: float = 0.5, block_on_unknown: bool = False)`
  - `SectorSettings(enabled: bool = True, ma_days: int = 20, min_bars: int = 10)`
  - `RegimeSettings(enabled: bool = True, index: str = "NSE:NIFTY50-INDEX", ma_days: int = 20)`
  - `First15Settings(enabled: bool = False, fade_tolerance_pct: float = 0.1, vol_factor: float = 0.8)`  # disabled by default — entry-timing gate, not a screening gate (matches current config)
  - `ScoringSettings(weights: dict[str, float] = {"catalyst": .30, "sector": .25, "band": .15, "liquidity": .15, "fno": .15}, liquidity_full_cr: float = 100.0)`
  - `Settings` gains: `gates_circuit`, `gates_sector`, `gates_regime`, `gates_first15`, `scoring` (all default instances).
  - `load_config` maps old nubra keys: `entry_threshold.circuit_gate.{enabled,upper_band_buffer_pct,block_on_unknown}`, `entry_threshold.sector_gate.{enabled,lookback→ma_days,min_bars}`, `entry_threshold.regime_gate.{enabled,index,ma_days}`, `entry_threshold.first15_gate.{enabled,fade_tolerance_pct,vol_factor}`, `watchlist.weights → scoring.weights`.

- [ ] **Step 1: Append failing tests** (MarketContext helpers; MarketData default; a `load_config` mapping case using an `entry_threshold` dict → assert `gates_circuit.upper_band_buffer_pct` etc.). Full test code:

```python
def test_market_context_lookups():
    from tradingbot.domain.models import MarketContext
    ctx = MarketContext(regime="up",
                        sector_index_of={"TCS": "NSE:NIFTYIT-INDEX"},
                        sector_trend={"NSE:NIFTYIT-INDEX": "down"},
                        turnover_cr={"TCS": 1200.0})
    assert ctx.sector_trend_for("tcs") == "down"
    assert ctx.sector_trend_for("UNKNOWN") is None
    assert ctx.turnover_for("TCS") == 1200.0


def test_market_data_intraday_default_none():
    from decimal import Decimal
    from tradingbot.domain.models import MarketData
    md = MarketData(ltp=Decimal("1"), closes=[1.0], history_ok=True, circuit=None, options=None)
    assert md.intraday_bars is None
```

```python
def test_phase5_settings_and_mapping():
    from tradingbot.config.settings import Settings, load_config
    s = Settings()
    assert s.gates_circuit.upper_band_buffer_pct == 0.5 and s.gates_first15.enabled is False
    assert s.scoring.weights["catalyst"] == 0.30
    m = load_config({"entry_threshold": {"circuit_gate": {"upper_band_buffer_pct": 1.0},
                                          "sector_gate": {"lookback": 30},
                                          "regime_gate": {"index": "NSE:NIFTYMIDCAP150-INDEX"}},
                     "watchlist": {"weights": {"catalyst": 0.5, "sector": 0.5}}})
    assert m.gates_circuit.upper_band_buffer_pct == 1.0
    assert m.gates_sector.ma_days == 30
    assert m.gates_regime.index == "NSE:NIFTYMIDCAP150-INDEX"
    assert m.scoring.weights == {"catalyst": 0.5, "sector": 0.5}
```

- [ ] **Step 2: FAIL → Step 3: implement → Step 4: green (full suite). Step 5: Commit** — `feat(domain,config): MarketContext + gate/scoring settings (Phase 5)`

---

## GROUP A — Gates

## Task 2: `gates/base.py` + Circuit/Sector/Regime gates (PORT)

**Files:**
- Create: `gates/__init__.py`, `gates/base.py`, `gates/circuit.py`, `gates/sector.py`, `gates/regime.py`
- Test: `tests/gates/__init__.py`, `test_base.py`, `test_circuit.py`, `test_sector.py`, `test_regime.py`
- Port sources: SRC `services/nubra_client/entry_gate.py` (CircuitStatusGate/SectorTrendGate/RegimeGate threshold logic) + their tests (`test_circuit_gate.py` gate cases, `test_sector_gate.py`, `test_regime_gate.py` gate cases).

**Interfaces:**

```python
# gates/base.py
@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: DropReason | None = None
    detail: str | None = None            # human string, e.g. "last 199.50 >= 199.00 (upper 200.00)"

class EntryGate(ABC):
    name: str
    @abstractmethod
    def evaluate(self, candidate: Candidate, market: MarketData, ctx: MarketContext) -> GateResult: ...

class CompositeGate(EntryGate):
    def __init__(self, gates: list[EntryGate]) -> None: ...
    def evaluate(self, candidate, market, ctx) -> GateResult:  # first block wins; all pass → passed
```

- `CircuitGate(settings: CircuitGateSettings)` — PURE port of the SRC threshold: uses `market.circuit`; unknown circuit → pass (fail-open) unless `block_on_unknown` → `GateResult(False, DropReason.CIRCUIT_LOCKED, "circuit status unknown")`; blocks when `last ≥ upper·(1−buffer_pct/100)` → reason `CIRCUIT_LOCKED`. **No trade-type guard** (candidacy: every candidate is buy-intent).
- `SectorGate(settings)` — `ctx.sector_trend_for(symbol) == "down"` → `SECTOR_DOWN`; unmapped/None → pass.
- `RegimeGate(settings)` — `ctx.regime == "down"` → `REGIME_DOWN`; None → pass.

- [ ] **Step 1: Write failing tests** — port the SRC gate cases onto the pure API (build `Candidate`/`MarketData`/`MarketContext` fixtures instead of fake providers). Must include: block-at-upper-with-buffer boundary (`last == threshold` blocks), fail-open on missing circuit, block_on_unknown, sector down blocks / unmapped passes / up passes, regime down blocks / None passes, CompositeGate first-block-wins ordering + all-pass.
- [ ] **Step 2: FAIL → Step 3: implement (thresholds verbatim from SRC) → Step 4: green (tests/gates/ only — parallel window). Step 5: Commit** — `feat(gates): pure Circuit/Sector/Regime gates + Composite (port)`

## Task 3: `gates/first_fifteen.py` (PORT of the logic, pure)

**Files:**
- Create: `gates/first_fifteen.py`
- Test: `tests/gates/test_first_fifteen.py`
- Port source: SRC `services/nubra_client/first_fifteen.py` (`gap_status` incl. the volume half) + `tests/nubra/test_first_fifteen.py`.

**Interfaces:**
- `def gap_status(bars: list[Bar], now_ist: datetime, fade_tolerance_pct: float, vol_factor: float) -> str | None` — pure port: returns `"held" | "faded" | "weak_volume" | None`; window 09:15–09:30 IST; before 09:30 or no today-bars → None; price-hold check then volume-vs-prior-sessions-average check (both halves, verbatim thresholds). Bars come from `market.intraday_bars` (`Bar.timestamp_ms`).
- `FirstFifteenGate(settings: First15Settings, clock: Callable[[], datetime] | None = None)` — evaluates via `gap_status`; `"faded"` → `GateResult(False, DropReason.GAP_FADED, ...)`; `"weak_volume"` → `WEAK_VOLUME`; None/`"held"` → pass; `market.intraday_bars is None` → pass (fail-open — pipeline didn't fetch intraday).

- [ ] **Step 1: Write failing tests** — port the 12 SRC cases (held/faded/weak-volume/none-before-window/none-no-today-bars/held-when-volume-normal + gate pass/block mappings), building `Bar` lists with the SRC helper pattern (IST timestamps).
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: green. Step 5: Commit** — `feat(gates): first-fifteen gap+volume gate (pure port, disabled by default)`

---

## GROUP B — Scoring

## Task 4: `scoring/` — Scorer, WatchlistScorer, flags (PORT)

**Files:**
- Create: `scoring/__init__.py`, `scoring/base.py`, `scoring/watchlist.py`, `scoring/flags.py`
- Test: `tests/scoring/__init__.py`, `test_watchlist.py`, `test_flags.py`
- Port sources: SRC `services/nubra_client/watchlist_scorer.py`, `fno_oi.py` (`pcr_label`, `oi_buildup_label`), `equity_runner.py::_catalyst_stack`, and their tests (`test_watchlist_scorer.py`, `test_fno_oi.py` label cases, `test_catalyst_stack.py`).

**Interfaces:**

```python
# scoring/base.py
@dataclass(frozen=True)
class ScoredResult:
    score: float | None                      # None when no factor present
    factors: dict[str, float | None]
    weights_used: dict[str, float]

class Scorer(Protocol):
    def score(self, candidate: Candidate, market: MarketData, forecast: Forecast | None,
              flags: ConvictionFlags, ctx: MarketContext) -> ScoredResult: ...
```

- `WatchlistScorer(settings: ScoringSettings)` — the 5 factors, then the SRC renormalizing blend (PORT `watchlist_score` verbatim):
  - `catalyst` = `max(0, min(1, flags.sentiment))` if sentiment is not None (directional — bearish→0)
  - `band` = `min(1, market.circuit.band_pct / 20)` when available (band off base — guaranteed by `Circuit.band_pct`)
  - `sector` = 1.0 if `ctx.sector_trend_for(sym)=="up"`, 0.0 if `"down"`, None otherwise
  - `fno` = 1.0 if `market.options is not None` else None
  - `liquidity` = `min(1, ctx.turnover_for(sym) / settings.liquidity_full_cr)` when turnover known, else None. **DELIBERATE CHANGE (named):** SRC used delivery-% (its collector is not ported); turnover is the playbook's primary §2 liquidity measure and is already fetched market-wide by the guard. Test both the formula and the None-renormalization.
- `scoring/flags.py` — verbatim ports: `pcr_label(pcr)->"put_heavy"|"call_heavy"|"balanced"|None`, `oi_buildup_label(call_chg, put_chg)->"call_buildup"|"put_buildup"|"balanced"|"flat"|None`, and `catalyst_stack(source_audit: dict, has_deal: bool | None) -> tuple[int, list[str], bool]` (count of firing news sources + `bulk_block_deal` when has_deal; stacked = count ≥ 2).

- [ ] **Step 1: Write failing tests** — port all SRC scorer tests (all-factors blend=1.0, renormalize-not-penalize on missing, weighted two-factor arithmetic `0.30/0.55`, custom weights, unknown-factor ignored) + directional-catalyst (bearish sentiment → factor 0) + the new liquidity formula (₹50cr → 0.5 at default 100; None when unknown) + flags label cases + stack cases.
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: green. Step 5: Commit** — `feat(scoring): 5-factor WatchlistScorer + conviction labels + catalyst stack (port; liquidity=turnover)`

---

## GROUP C — Market-wide context builder

## Task 5: `providers/marketwide.py` + sector snapshot

**Files:**
- Create: `src/tradingbot/providers/marketwide.py`; copy snapshot:

```bash
cp /Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/services/nubra_client/fixtures/sector_constituents.json \
   /Users/jagadeeshpulamarasetti/Code/own/TradingBot/data/sector_constituents.json
```

- Test: `tests/providers/test_marketwide.py`
- Port sources: SRC `services/nubra_client/sector_trend.py` (`load_dynamic_sector_map` snapshot loader + SMA trend), `market_regime.py` (regime SMA + full-window guard) + `test_sector_gate.py`/`test_regime_gate.py` math cases.

**Interfaces:**

```python
def trend_from_closes(closes: list[float], ma_days: int) -> str | None:
    """last close vs ma_days-SMA; None unless len(closes) >= ma_days (full window — the SRC
    regime fix: never average a partial window)."""

def load_sector_map(path: Path | None = None) -> dict[str, str]:
    """{SYMBOL: index_symbol} from data/sector_constituents.json; {} + warning if missing."""

class MarketContextBuilder:
    def __init__(self, market: MarketDataProvider, sector_settings: SectorSettings,
                 regime_settings: RegimeSettings, snapshot_path: Path | None = None) -> None: ...
    @classmethod
    def from_settings(cls, settings: Settings, market: MarketDataProvider) -> "MarketContextBuilder": ...
    async def build(self, turnover_cr: dict[str, float]) -> MarketContext:
        # 1) load_sector_map -> unique index symbols (+ regime index)
        # 2) fetch each index's closes ONCE concurrently: asyncio.gather(market.ohlcv(idx, ma_days + 5))
        #    (rate-limited by the provider; a failed index -> trend None, never crashes)
        # 3) trend_from_closes per index; regime likewise
        # 4) return MarketContext(regime, sector_index_of, sector_trend, turnover_cr)
```

  `turnover_cr` is passed in by the pipeline (the guard already fetched the bhavcopy turnover map in ₹-lakhs; the pipeline converts /100 — the builder does NOT re-fetch it).

- [ ] **Step 1: cp the snapshot; write failing tests** — `trend_from_closes` (rising→up, falling→down, len==ma_days works, len<ma_days→None); `load_sector_map` (real snapshot file: >100 symbols, INFY→NIFTYIT, values all `NSE:*-INDEX`; missing file → {}); `build()` with a fake async MarketDataProvider: each unique index fetched exactly once (call-count map), failed index → None trend, regime computed, turnover passed through, symbols upper-cased.
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: green. Step 5: Commit** — `feat(providers): MarketContextBuilder (sector snapshot + index trends + regime, one fetch per index)`

---

## Task 6: Decision-layer integration + green gate (after A, B, C)

**Files:**
- Test: `tests/test_decision_integration.py`

- [ ] **Step 1: Write the integration test** (pure — no IO): fabricate 4 candidates covering the matrix — (a) clean liquid large-cap: passes all gates, high score; (b) pinned at upper circuit → `CIRCUIT_LOCKED`; (c) mapped to a down sector → `SECTOR_DOWN`; (d) bearish sentiment: passes gates (news never gates) but catalyst factor 0 drags its score below (a). Wire `CompositeGate([CircuitGate, RegimeGate, SectorGate])` + `WatchlistScorer` over a hand-built `MarketContext` and assert statuses, reasons, and score ordering. Full code in the test file (assemble from the Task 1–4 fixtures).
- [ ] **Step 2: Run the FULL suite + ruff — all green.** Record counts.
- [ ] **Step 3: Commit** — `test: decision-layer integration (gates + scoring) — Phase 5 complete`

---

## Definition of done (Phase 5)

- Gates and scoring are pure (no IO, no network in any test), with every SRC behavioral invariant re-asserted; candidacy semantics (no trade-type guards, news never gates) hold.
- `MarketContext` built once per run: each sector index fetched exactly once; regime full-window SMA.
- The one deliberate change (liquidity factor: delivery-% → turnover) is named, tested, and documented in the commit.
- Full suite + ruff green; one commit per task.

**Named deferrals:** per-symbol soft-flag fetchers not yet ported (delivery-%, promoter/shareholding, deals, FII-DII, pre-open) — `ConvictionFlags` fields exist and default None; they land in Phase 6's fetch/bulk stages. Live-execution trade gating (ExpectedUpsideGate etc.) is a spec non-goal — not ported.

**Next plan:** Phase 6 — the staged pipeline + Screener facade (wires providers → forecast → gates → scoring → storage).

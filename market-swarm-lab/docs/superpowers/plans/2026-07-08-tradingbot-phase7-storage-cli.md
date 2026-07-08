# TradingBot Phase 7 (slice 1) — Storage & CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `RunResult`s to MongoDB in the **existing** `market_swarm.watchlist_runs` document shape (so the current data and the upcoming dashboard interoperate immediately), and ship the `tradingbot screen` CLI command that runs the Phase-6 `Screener` end-to-end and saves the run.

**Architecture:** `storage/` is a thin adapter layer: a pure `run_to_doc(RunResult, ...) -> dict` mapper (ports SRC `watchlist_store/run_to_doc.py`, reconciling the two named parity notes) + `MongoRunStore` (ports SRC `watchlist_store/mongo_store.py`). `cli/` is a thin composition layer over `Screener` + `MongoRunStore` (stdlib `argparse`; no business logic). A tiny pure `scoring/targets.py` port supplies the T1/T2 fields the doc/dashboard carry.

**Tech Stack:** Python 3.11, pymongo (new dep), argparse, pytest (mongo round-trip tests skip when no local mongod — SRC pattern).

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. Port source (**SRC**, read-only): `/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab` (`services/watchlist_store/run_to_doc.py`, `services/watchlist_store/mongo_store.py`, `services/nubra_client/trade_targets.py`, `scripts/weekly_watchlist.py` `_save_run`).
- Prerequisite: Phase 6 merged (HEAD `be7cb87`, 299 passed / 1 skipped). Consume committed interfaces exactly: `RunResult(run_date, universe_size, probables, errors)` with `.elected`/`.counts`; `Probable(symbol, status, drop_reason, score, forecast, market, catalyst, flags)`; `Forecast(predicted_return, direction, confidence, quantiles)`; `MarketData(ltp, closes, history_ok, circuit, options, intraday_bars)`; `Circuit.band_pct`; `OptionSnapshot.pcr`; `ConvictionFlags(sentiment, catalyst_stack, has_deal, promoter_trend, oi_buildup)`; `Screener.from_settings(settings)` / `async run(today=None) -> RunResult`; `load_config(dict) -> Settings`; `label_from_score` in `providers/news/sentiment.py`.
- **DOC-SHAPE COMPATIBILITY IS THE CONTRACT:** the emitted run document must be readable by the existing MiroFish dashboard/backtest — same top-level keys (`run_id`, `run_date`, `generated_at`, `universe`, `sentiment_engine`, `counts{total,elected,dropped}`, `symbols[]`) and same per-symbol row keys (`symbol`, `status` ("elected"/"dropped"), `reason` (None when elected), `trade` (CALL/PUT/HOLD — derived from TimesFM direction; presentation renames it later), `score`, `upside_pct`, `band_pct`, `size_factor`, `pcr`, `sentiment` (label string), `catalyst_stack` (int), `factors`, `targets` ({t1,t2,...}|None), `entry_ltp`, `catalyst` (description), `catalyst_type`). Where the new pipeline has no value (e.g. `size_factor` — sizing not ported), emit `None`, never omit the key.
- **Parity reconciliations (from the Phase-6 review, now decided):** (a) errored symbols ARE re-folded into `symbols[]` as dropped rows with `reason="error"` and counted in `counts.total/dropped` — matching SRC `run_to_doc` exactly; (b) the SRC ordering quirk `-(score or -1)` (a 0.0 score sorts with the Nones) IS replicated in the doc's `symbols` ordering — byte-level parity for the Phase-8 diff beats elegance; keep `RunResult`'s own cleaner ordering untouched (the quirk lives only in the mapper).
- Money → `str(Decimal)`/float per SRC doc shape (`entry_ltp` was a float in SRC docs — emit `float(market.ltp)`).
- Full suite + ruff green at end; commit per task; parallel-safety rules as prior phases.
- **Named deferrals (slice 2 / dashboard plan):** FastAPI `api/` + React `ui/` (dashboard spec 7a–7d); backtest/expectancy port (`backtest_sim`, `expectancy`, backtest CLI); positions/view_prefs collections; `run_time_stop_exits` CLI; fyers-login helper script (interactive auth stays in SRC for now — the CLI reads `FYERS_*` env/.env exactly like the providers already do).

---

## File Structure (Phase 7 slice 1)

```
src/tradingbot/
├── scoring/targets.py           # scale_out_targets PORT (pure)
├── storage/
│   ├── __init__.py              # exports run_to_doc, MongoRunStore
│   ├── doc.py                   # run_to_doc(RunResult, ...) -> dict  (pure mapper)
│   └── mongo.py                 # MongoRunStore (save/list/latest/get/elected_history)
└── cli/
    ├── __init__.py
    └── screen.py                # `python -m tradingbot.cli.screen` / console-script `tradingbot-screen`
pyproject.toml                   # + pymongo>=4.6; [project.scripts] tradingbot-screen
tests/scoring/test_targets.py  tests/storage/  tests/cli/test_screen.py
```

---

## Task 1: `scoring/targets.py` — scale-out targets PORT (Group A)

**Files:**
- Create: `src/tradingbot/scoring/targets.py`
- Test: `tests/scoring/test_targets.py`

**Interfaces:**
- PORT of SRC `services/nubra_client/trade_targets.py::scale_out_targets` with the settings-shape transform only:

```python
def scale_out_targets(ltp: float, expected_move_pct: float,
                      t1_fraction: float = 0.6, t1_exit_pct: int = 70) -> dict | None:
    """T1 at t1_fraction of the expected move (scale out t1_exit_pct%), T2 at the full move.
    None for a non-positive expected move (no bullish target on a flat/bearish forecast)."""
```

  Return dict keys exactly as SRC (`{"t1": ..., "t2": ..., "t1_exit_pct": ..., "t2_exit_pct": ...}` — copy the SRC rounding). Read SRC first; keep formulas verbatim.

- [ ] **Step 1: Write failing tests** — port the SRC `test_trade_targets.py` cases (positive move → T1/T2 levels + fractions; zero/negative move → None; rounding).
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/scoring/test_targets.py only) → Step 5: Commit** — `feat(scoring): scale-out targets port (pure)`

---

## Task 2: `storage/doc.py` — the RunResult → run-document mapper (Group B)

**Files:**
- Create: `src/tradingbot/storage/__init__.py`, `src/tradingbot/storage/doc.py`
- Test: `tests/storage/__init__.py` (empty), `tests/storage/test_doc.py`

**Interfaces:**

```python
def run_to_doc(result: RunResult, *, generated_at: datetime, universe: str = "catalyst",
               sentiment_engine: str | None = None) -> dict: ...
```

**Semantics (PORT of SRC `run_to_doc.py`, adapted from dict-results to domain objects):**
1. `run_id = generated_at.isoformat(timespec="seconds")`; top-level keys exactly: `run_id`, `run_date` (= `result.run_date`), `generated_at`, `universe`, `sentiment_engine`, `counts`, `symbols`.
2. Per-Probable row (all keys ALWAYS present):
   - `symbol`; `status` = `"elected"`/`"dropped"` (enum `.value`); `reason` = `drop_reason.value` or None.
   - `trade`: from `forecast.direction` — BULLISH→"CALL", BEARISH→"PUT", NEUTRAL→"HOLD"; None when `forecast is None` (SRC rows had `trade` from the signal; forecast-less rows carry None).
   - `score`; `upside_pct` = `round(forecast.predicted_return * 100, 2)` or None; `band_pct` = `market.circuit.band_pct` (rounded 2) or None; `size_factor` = None (sizing not ported — key kept for shape compat); `pcr` = `market.options.pcr` or None.
   - `sentiment` = `label_from_score(flags.sentiment)` when `flags.sentiment is not None` else None (import from `providers/news/sentiment.py`); `catalyst_stack` = `flags.catalyst_stack`.
   - `factors` = the ScoredResult factors are NOT carried on Probable → emit None (shape-compat key; note in docstring).
   - `targets` = `scale_out_targets(float(market.ltp), forecast.predicted_return)` when forecast present else None (Task 1 import).
   - `entry_ltp` = `float(market.ltp)`; `catalyst` = `probable.catalyst.description`; `catalyst_type` = `probable.catalyst.type.value`.
3. **Errors re-fold (parity decision a):** for each `(sym, err)` in `result.errors`, append a row `{"symbol": sym, "status": "dropped", "reason": "error", ...all other keys None...}`; `counts = {"total": len(rows), "elected": ..., "dropped": ...}` computed AFTER the fold (matches SRC totals).
4. **Ordering (parity decision b):** rows sorted by `(status != "elected", -(score or -1))` — the SRC key verbatim, including the 0.0-as-None quirk.

- [ ] **Step 1: Write failing tests** — build Probables via the committed `_make_probable` pattern: full elected row maps every key with exact values (incl. trade CALL from BULLISH, sentiment label, targets dict); dropped row carries reason + score; forecast-less row → trade/upside/targets None; error fold appends reason="error" rows and inflates counts; ordering test proving BOTH elected-first AND the 0.0-score-sorts-with-None quirk (elected rows scored [0.5, 0.0, None, 0.7] order as 0.7, 0.5, then 0.0/None group in stable order); every row has the full key set (assert `set(row) == EXPECTED_KEYS`).
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/storage/test_doc.py only) → Step 5: Commit** — `feat(storage): RunResult -> run-document mapper (SRC doc-shape parity incl. error fold + ordering quirk)`

---

## Task 3: `storage/mongo.py` — MongoRunStore (Group B, after Task 2)

**Files:**
- Create: `src/tradingbot/storage/mongo.py`; Modify: `src/tradingbot/storage/__init__.py` (exports), `pyproject.toml` (+ `pymongo>=4.6`), `uv.lock`
- Test: `tests/storage/test_mongo.py`

**Interfaces (PORT of SRC `watchlist_store/mongo_store.py` — same DB/collection/behavior):**

```python
class MongoRunStore:
    def __init__(self, uri: str | None = None, db: str = "market_swarm",
                 coll: str = "watchlist_runs") -> None: ...   # uri default: env MONGO_URI or mongodb://localhost:27017; serverSelectionTimeoutMS=3000; indexes: generated_at desc, run_id unique
    def save_run(self, doc: dict) -> str: ...                 # replace_one upsert on run_id (idempotent)
    def list_runs(self, limit: int = 90) -> list[dict]: ...   # headers only (no symbols), newest-first, _clean-ed
    def latest_run(self) -> dict | None: ...
    def get_run(self, run_id: str) -> dict | None: ...
    def elected_history(self, limit_runs: int = 200) -> list[dict]: ...  # SRC shape: [{run_id, run_date, elected:[{symbol, entry_ltp, score, upside_pct, targets}]}]
    def close(self) -> None: ...
```

  `_clean(doc)`: drop `_id`, isoformat `generated_at` — verbatim SRC.

- [ ] **Step 1: Write failing tests** — PORT the SRC `test_watchlist_store.py` mongo round-trip test pattern: module-level `_mongo_up()` socket probe + `pytest.mark.skipif`; use a THROWAWAY db/collection (`market_swarm_test` / `watchlist_runs_test`) dropped in a finally; round-trip save→get (counts intact, `_id` stripped), idempotent re-save (list length 1), `elected_history` shape, `list_runs` excludes `symbols`.
- [ ] **Step 2: FAIL → Step 3: implement (add pymongo to pyproject via the plan's dependency edit; regenerate uv.lock with `uv lock`) → Step 4: PASS (tests/storage/ only; confirm the skipif engages cleanly when mongod is down) → Step 5: Commit** — `feat(storage): MongoRunStore port (market_swarm.watchlist_runs, idempotent upsert)`

---

## Task 4: `cli/screen.py` — the screen command (after Tasks 1–3)

**Files:**
- Create: `src/tradingbot/cli/__init__.py` (empty), `src/tradingbot/cli/screen.py`; Modify: `pyproject.toml` (`[project.scripts] tradingbot-screen = "tradingbot.cli.screen:main"`)
- Test: `tests/cli/__init__.py` (empty), `tests/cli/test_screen.py`

**Interfaces:**

```python
def build_parser() -> argparse.ArgumentParser: ...
# flags: --config PATH (optional JSON, mapped via load_config; default Settings());
#        --save (persist to Mongo; default print-only); --mongo-uri URI (overrides env);
#        --top N (print top-N elected rows, default 20); --json (dump the full doc as JSON)

async def run_screen(settings: Settings, *, save: bool, mongo_uri: str | None,
                     top: int, as_json: bool, today: date | None = None) -> dict: ...
def main(argv: list[str] | None = None) -> int: ...   # loads .env (python-dotenv, already a dep), argparse, asyncio.run
```

**Semantics:**
1. `main`: `load_dotenv()` (repo-root .env if present — `config/paths.py` root); parse args; `settings = load_config(json.loads(Path(args.config).read_text()))` if `--config` else `Settings()`; `return asyncio.run(run_screen(...)) and 0`.
2. `run_screen`: `screener = Screener.from_settings(settings)`; `result = await screener.run(today)`; `doc = run_to_doc(result, generated_at=datetime.now(IST), universe="catalyst", sentiment_engine=settings.sentiment.engine)` (IST = fixed +05:30, module const); if `save`: `store = MongoRunStore(uri=mongo_uri); store.save_run(doc); store.close()`; print: `--json` → `json.dumps(doc, default=str)`; else a compact table of the top-N elected rows (`symbol, score, upside_pct, band_pct, sentiment, catalyst_type`) + the counts line + errors count. Returns the doc (testability).
3. NO business logic in the CLI — everything through the committed facades.

- [ ] **Step 1: Write failing tests** — `build_parser` defaults; `run_screen` with a FAKE Screener (monkeypatched `Screener.from_settings` returning a stub whose `run()` yields a small RunResult) and a FAKE store (monkeypatch `MongoRunStore`): save=False never constructs the store, save=True calls `save_run` with the mapped doc and `close()`; `--json` path emits parseable JSON (capsys); table path contains the elected symbol and counts; `main([])` wires argv→settings→exit code 0 (with the same monkeypatches). No network, no mongo, no real screener in tests.
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/cli/ only) → Step 5: Commit** — `feat(cli): tradingbot-screen command (screen -> doc -> optional Mongo save)`

---

## Task 5: Slice integration + green gate (last)

**Files:**
- Create: `tests/test_storage_cli_integration.py`
- Test: full suite

- [ ] **Step 1: Write the integration test** — one flow with fakes end-to-end: stub Screener → `run_screen(save=True)` with a fake in-memory store → assert the saved doc satisfies the FULL shape contract (top-level keys, every row's key set, error fold counted, ordering incl. the 0.0 quirk) and that `elected_history`-style consumption works off the fake store's saved doc. Plus: `run_to_doc` output is round-trippable through `json.dumps(..., default=str)`.
- [ ] **Step 2: Run the FULL suite + ruff**; fix any cross-module breakage (report what).
- [ ] **Step 3: Commit** — `test(storage,cli): storage+CLI integration green gate (Phase 7 slice 1 complete)`

---

## Definition of done (slice 1)

- `tradingbot-screen --save` runs the real pipeline and persists a document the EXISTING MiroFish dashboard can read unchanged; doc-shape + counts + ordering parity locked by tests (incl. the two reconciled quirks); full suite + ruff green.
- **Next (slice 2):** dashboard 7a per the dashboard spec (FastAPI read endpoints + Runs Explorer) + backtest/expectancy port.

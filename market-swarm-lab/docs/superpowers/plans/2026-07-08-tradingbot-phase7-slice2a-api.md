# TradingBot Phase 7 slice 2a — Dashboard Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dashboard spec's 7a **read** API — FastAPI endpoints over `MongoRunStore` (`/api/runs`, `/api/runs/latest`, `/api/runs/{run_id}`, `/api/runs/{run_id}/diff`, `/api/symbols/{symbol}/history`) served from one process, ready for the React UI (slice 2b) and usable today via curl against existing Mongo data.

**Architecture:** `api/` is a thin composition layer (dashboard-spec rule: "no business logic in the API layer beyond composition; `api` imports inward only"). Endpoints delegate to `MongoRunStore` plus two new PURE helpers (`diff_runs`, `symbol_history`) that live in `storage/` (unit-testable without HTTP). A FastAPI app factory takes an injected store (tests use an in-memory fake; no Mongo needed). Static-file serving is wired but serves a placeholder page until slice 2b builds the SPA.

**Tech Stack:** Python 3.11, fastapi + uvicorn (new deps), httpx (test client dep), pytest. No UI code in this slice.

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. Reference specs (read-only): `/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/docs/superpowers/specs/2026-07-07-tradingbot-dashboard-design.md` (§3 API) and the SRC dashboard app `apps/watchlist/app.py` (endpoint behavior reference).
- Prerequisite: Phase 7 slice 1 merged (HEAD `6a6fbbe`, 330 passed / 2 skipped). Consume committed interfaces exactly: `MongoRunStore(uri, db="market_swarm", coll="watchlist_runs")` with `save_run/list_runs(limit=90)/latest_run/get_run/elected_history/close`; run-document shape per `storage/doc.py` (top-level `run_id/run_date/generated_at/universe/sentiment_engine/counts/symbols`; row keys incl. `symbol/status/reason/trade/score/upside_pct/...`).
- **Read-only contract:** this API never writes. Positions/view_prefs/orders (7b/7d) are named deferrals — do NOT scaffold their routes.
- The API must work against BOTH existing MiroFish-written docs and new-CLI docs (same shape — that was slice 1's contract). No schema migration, no doc mutation.
- Layering: `api` imports `storage` + `fastapi` only (never providers/pipeline/forecast).
- Full suite + ruff green at end; commit per task; tasks are SEQUENTIAL (each builds on the prior).

---

## File Structure (slice 2a)

```
src/tradingbot/
├── storage/
│   ├── query.py                 # PURE: diff_runs(curr, prev) + symbol_history(runs, symbol)
│   └── __init__.py              # + exports
└── api/
    ├── __init__.py
    ├── app.py                   # create_app(store) factory + routes + static mount
    └── static/index.html        # placeholder page (slice 2b replaces with the SPA build)
pyproject.toml                   # + fastapi>=0.115, uvicorn>=0.30; dev + httpx>=0.27
tests/storage/test_query.py  tests/api/test_app.py
```

---

## Task 1: `storage/query.py` — pure diff + history helpers

**Files:**
- Create: `src/tradingbot/storage/query.py`; Modify: `src/tradingbot/storage/__init__.py` (exports)
- Test: `tests/storage/test_query.py`

**Interfaces:**

```python
def diff_runs(current: dict, previous: dict | None) -> dict:
    """Dashboard-spec §3 diff: {"entered": [...], "exited": [...], "movers": [...]}.
    entered: symbols ELECTED in current but not elected in previous (or previous is None → all current elected, flagged first_run=True at top level).
    exited: symbols elected in previous but not elected in current.
    movers: for symbols elected in BOTH, the top |Δscore| changes:
      [{"symbol", "score", "prev_score", "delta"}] sorted by |delta| desc, capped at 10, only where both scores are not None and delta != 0.
    Output: {"run_id", "prev_run_id" (None ok), "first_run": bool, "entered": [rows], "exited": [rows], "movers": [...]}
    where entered/exited rows are the full symbol rows from the respective run doc."""

def symbol_history(runs: list[dict], symbol: str) -> list[dict]:
    """Per-run series for one symbol (dashboard drill-down), oldest-first:
    [{"run_id", "run_date", "status", "reason", "score", "upside_pct", "trade"}]
    — one entry per run where the symbol appears in doc["symbols"]; symbol matched case-insensitively."""
```

Both are pure dict-in/dict-out (no store, no IO) — the API layer feeds them store results.

- [ ] **Step 1: Write failing tests** — build two small run docs (reuse the row-shape from `tests/storage/test_doc.py` fixtures): entered/exited/movers computed correctly; movers sorted by |delta| desc and capped (build 12 movers, assert 10); previous=None → first_run=True, all-elected entered, empty exited/movers; None-score symbols excluded from movers but still enter/exit correctly; `symbol_history` returns oldest-first entries with exactly the listed keys, case-insensitive symbol match, symbols absent from a run simply skipped.
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS (tests/storage/test_query.py only) → Step 5: Commit** — `feat(storage): pure run-diff + symbol-history query helpers`

---

## Task 2: `api/app.py` — FastAPI read app (after Task 1)

**Files:**
- Create: `src/tradingbot/api/__init__.py` (empty), `src/tradingbot/api/app.py`, `src/tradingbot/api/static/index.html`; Modify: `pyproject.toml` (+ `fastapi>=0.115`, `uvicorn>=0.30`; dev extra + `httpx>=0.27`), `uv.lock`
- Test: `tests/api/__init__.py` (empty), `tests/api/test_app.py`

**Interfaces:**

```python
class RunStoreLike(Protocol):        # structural — what the app needs from a store
    def list_runs(self, limit: int = 90) -> list[dict]: ...
    def latest_run(self) -> dict | None: ...
    def get_run(self, run_id: str) -> dict | None: ...

def create_app(store: RunStoreLike) -> FastAPI: ...
def main() -> None:                  # uvicorn entry: store = MongoRunStore(uri from MONGO_URI env); create_app; run on port 8100
```

**Routes (dashboard spec §3, read subset — exact paths):**
1. `GET /api/runs?limit=` → `store.list_runs(limit)` (headers only, as the store already projects). Default limit 90; clamp 1..365. **Named deferral:** the spec's `before=` back-pagination cursor is deferred to 2b — the frozen slice-1 store has no cursor param and limit≤365 covers a year of daily runs; 2b picks it up if the timeline needs it.
2. `GET /api/runs/latest` → `store.latest_run()`; 404 `{"detail": "no runs saved yet"}` when None.
3. `GET /api/runs/{run_id}` → `store.get_run(run_id)`; 404 when None. (Register /latest BEFORE /{run_id} so "latest" doesn't match as an id.)
4. `GET /api/runs/{run_id}/diff` → current = `get_run(run_id)` (404 if missing); previous = the run immediately BEFORE it in `list_runs(365)` order (newest-first list → the entry after current's index; None if current is oldest); return `diff_runs(current_full, previous_full)` — NOTE list_runs rows lack `symbols`, so fetch the previous run's FULL doc via `get_run(prev_run_id)`. **Window-boundary safety:** if `run_id` is valid via get_run but NOT present in the list_runs(365) ids (a run older than the window), treat previous as None (first_run-style diff) — never ValueError/500. Test this case explicitly.
5. `GET /api/symbols/{symbol}/history?limit_runs=` → full docs of the latest N runs (default 60: iterate `list_runs(60)` ids → `get_run` each) → `symbol_history(runs_oldest_first, symbol)`. **The route MUST reverse the newest-first list_runs order to oldest-first before calling the helper** (symbol_history preserves input order — the reversal is the route's responsibility; the route test must assert ascending run_date in the response). (Simple N×get_run is acceptable at this scale — runs are daily; note it in a comment.)
6. `GET /` → serve `api/static/index.html` (FileResponse); `app.mount("/static", StaticFiles(...))`. Placeholder body: `<h1>TradingBot</h1><p>Dashboard UI lands in slice 2b. API is live under /api/…</p>`.
7. NO write routes. NO /api/positions, /api/views, /api/orders (7b/7d).

**`main()`:** `MongoRunStore()` (its env/default URI), `uvicorn.run(create_app(store), host="127.0.0.1", port=8100)`. Add `[project.scripts] tradingbot-api = "tradingbot.api.app:main"`.

- [ ] **Step 1: Write failing tests** — with `fastapi.testclient.TestClient(create_app(FakeStore()))` where FakeStore is a tiny in-memory dict store (seed 3 run docs via the test-doc fixtures): /api/runs returns headers newest-first + respects limit; /latest 200 and 404-when-empty; /{run_id} 200/404; "latest" path does not shadow an id lookup; /diff returns entered/exited/movers vs the chronologically-previous run and first_run=True for the oldest; /history returns the oldest-first series and [] for an unknown symbol; GET / returns 200 text/html containing "TradingBot"; assert NO route exists for /api/positions (404).
- [ ] **Step 2: FAIL → Step 3: implement (add deps; `uv lock`) → Step 4: PASS (tests/api/ only) → Step 5: Commit** — `feat(api): dashboard read API (runs/diff/history) + static placeholder`

---

## Task 3: Slice integration + green gate (last)

**Files:**
- Create: `tests/test_api_integration.py`
- Test: full suite

- [ ] **Step 1: Write the integration test** — end-to-end without HTTP mocks: build 3 RunResults → `run_to_doc` → save into the FakeStore (and, `skipif` no local mongod, the REAL MongoRunStore against a throwaway collection) → TestClient over `create_app(store)` → assert the full read flow (list → latest → get → diff → history) returns internally-consistent data (counts match, diff.entered symbols really newly-elected, history series matches the saved docs).
- [ ] **Step 2: Run the FULL suite + ruff**; fix any cross-module breakage (report what).
- [ ] **Step 3: Commit** — `test(api): read-API integration green gate (Phase 7 slice 2a complete)`

---

## Definition of done (slice 2a)

- `tradingbot-api` serves the 5 read endpoints on :8100 over real Mongo (existing MiroFish docs included) and a placeholder page at `/`; all behavior locked by tests against a fake store (+ conditional real-Mongo integration); full suite + ruff green.
- **Next:** slice 2b — the React Runs Explorer (Vite+TS+TanStack, build → `api/static/`), planned against these now-real endpoint shapes; then 7b positions, 7c drill-down/analytics (+ backtest/expectancy port), 7d order boundary; Phase 8 parity run (blocked only on a fresh Fyers token).

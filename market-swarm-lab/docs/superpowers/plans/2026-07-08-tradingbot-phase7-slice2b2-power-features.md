# TradingBot Phase 7 slice 2b-ii — Runs Explorer power features (React SPA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is TDD: write failing tests → implement → pass → commit.

**Goal:** Complete the Runs Explorer's spec-§1.1 power features on top of the shipped 2b-i core: **run-navigation completion** (URL deep links `/runs/:runId`, on-screen prev/next buttons, native date picker), **Kibana-style display control** (column picker with show/hide + drag-reorder + resize, density toggle, CSV export of the filtered+visible view), and **advanced filters** (numeric ranges + enum multiselects) — all built with **zero new npm dependencies** (TanStack Table built-ins + native HTML inputs + the History API), and one small FastAPI change (a deep-link SPA fallback route).

**Ponytail scope (read before implementing):** the spec's §1.1 features are user-approved, so we build them — but we build the laziest version that satisfies each, and we defer three items with reasons:

| Deferred | Why | When |
|----------|-----|------|
| **Server-side / named saved views** | Spec §2/§3 put views in a `view_prefs` collection behind `GET/POST /api/views` — that endpoint + Mongo write path is 7b work. Building a localStorage clone now is throwaway. | 7b. A cheap *implicit* localStorage persistence of the current column layout + density is the stand-in (not named multi-view management). |
| **`before=` pagination on the timeline** | 15 runs exist; `_LIST_WINDOW = 365` already covers a year of daily runs. No scale to paginate. | When run count approaches the window or the timeline is measurably slow. |
| **"F&O-only" enum filter** | `SymbolRow` carries no F&O / `is_fno` field (see `api/types.ts`); the run doc doesn't emit it. Same class of gap as `ConvictionFlags.has_deal/promoter_trend` being always-None until ported. | When an F&O flag is added to the run doc. Named, not silent. |

Everything else in §1.1 that 2b-i did not cover **is** in this slice.

**Architecture (dashboard spec §1.1 + §4):** same `ui/` SPA (Vite + React 18 + TS), same feature folders. New URL routing via a hand-rolled History-API hook (`app/useRunRoute.ts`) — **not** react-router. Rationale: only two client routes exist today (`/` and `/runs/:id`); react-router earns its keep once `/positions` (7b) and `/analytics` (7c) land, at which point we swap the hook for it. The hook carries a `ponytail:` comment naming that upgrade path. Column visibility/order/sizing use TanStack Table's built-in state (no dnd-kit). Filtering stays a single **pure** function (`filterRows`) — refactored from a 4-arg signature to one `FilterState` object so adding a predicate is an additive change, not a signature break.

**Tech Stack (UNCHANGED — no new deps):** the existing `ui/package.json` (React 18, @tanstack/react-table 8, @tanstack/react-query 5, vite 5, vitest 2, @testing-library/react 16, jsdom). Native `<input type="date">`, `<input type="number">`, checkboxes, `Blob`/`URL.createObjectURL`, `window.history`/`popstate`. **If any task reaches for a new dependency, stop — the design is wrong.**

## Global Constraints

- **Repo (work ONLY here):** `/Users/jagadeeshpulamarasetti/OwnCode/TradingBot`. (Note: earlier plans wrote the stale path `~/Code/own/TradingBot`; the live checkout is `~/OwnCode/TradingBot`.) SRC reference (read-only): `/Users/jagadeeshpulamarasetti/OwnCode/TradingBotMiroFish/market-swarm-lab`. Dashboard spec copy travels in-repo at `ai/context/refs/2026-07-07-tradingbot-dashboard-design.md` (§1.1, §4) and the 2b-i plan at `ai/context/refs/2026-07-08-tradingbot-phase7-slice2b1-runs-explorer.md`.
- **`node_modules` is NOT present** in a fresh checkout. **Task 1 Step 0: `cd ui && npm install`** before any `npm test`/`npm run build`. (The committed bundle under `src/tradingbot/api/static/` means the API serves without Node, but building/testing the UI needs the install.)
- **Prerequisite:** 2b-i merged (HEAD `1c921be`; doc/session commits after are docs-only). The 2a API payload shapes remain the committed contract — do not change `api/types.ts` field shapes; only *add* the SPA fallback route to `api/app.py`.
- **Self-contained bundle, no CDN.** No external network at runtime. The BUILT bundle under `src/tradingbot/api/static/` is committed — **rebuilt + committed once, in Task 3's final commit** (interim Task 1/2 commits are source+test only; the old bundle stays valid and the raw-HTML "TradingBot" test still passes on it).
- **Locked renames/glyphs (from 2b-i — do not regress):** `trade` renders as **"TimesFM view"** (CALL→bullish/PUT→bearish/HOLD→neutral/null→`—`); `EMPTY = "—"` is the single empty glyph; `ui/index.html` MUST keep the literal `<title>TradingBot</title>` (Python `test_root_serves_placeholder_html` asserts `"TradingBot" in r.text` on raw HTML).
- UI tests headless (`npm test` = vitest run/jsdom). The Python suite must stay green (`uv run --extra dev pytest -q`); the ONLY Python change is the new SPA fallback route + its test.
- Commit per task, explicit-path `git add` (never `git add -A`), retry on `index.lock`. JS work under `ui/` only (+ the rebuilt bundle in Task 3).
- **Do NOT persist filters or sort** to localStorage — they are run-specific/ephemeral (a score range meaningful in one run is nonsense in another). Persist only the stable display prefs: column visibility/order/sizing + density.

---

## File Structure (slice 2b-ii)

```
ui/src/
  app/
    useRunRoute.ts         NEW  history-API router: {routeRunId, navigate(id|null)}   [ponytail: swap for react-router at 7b/7c]
    useLocalStorage.ts     NEW  useLocalStorage<T>(key, initial) → [T, setT]  (JSON, try/catch, SSR-safe guard)
  features/runs/
    columns.ts             NEW  ColId union + COLUMN_META [{id, label}] (canonical order + labels; single source)
    filterRows.ts          MOD  FilterState object + NO_FILTERS + enumOptions() + numericBounds(); filterRows(rows, f)
    exportCsv.ts           NEW  rowsToCsv(rows, orderedVisibleIds) → string (RFC-4180 escaping; reuses format helpers)
    RunGrid.tsx            MOD  controlled columnVisibility/order/sizing props + resize handles; columns built in COLUMN_META order
    ColumnPicker.tsx       NEW  visibility checkboxes + native drag-reorder over COLUMN_META
    FiltersPanel.tsx       NEW  numeric ranges (score/band/upside) + enum multiselects (catalyst_type/timesfm_view/sentiment)
    RunTimeline.tsx        MOD  + prev/next buttons + native date picker (client-side date→run)
  App.tsx                  MOD  useRunRoute for selection+deep links; owns+persists view prefs; wires FiltersPanel/CSV/density
  styles.css               MOD  append: resize handles, column-picker/filters panels, density-compact, prev/next, date input
src/tradingbot/api/app.py  MOD  + GET /runs/{run_id:path} → FileResponse(index.html)  (deep-link SPA fallback)
src/tradingbot/api/static/ MOD  rebuilt bundle, committed in Task 3
```

---

## Task 1: Foundations — pure utils, hooks, API fallback (no visual change)

Everything shared by later tasks lands here first so Tasks 2/3 only add UI. All units are pure/testable.

**Files:**
- Modify: `ui/src/features/runs/filterRows.ts`, `ui/src/App.tsx` (only to keep it compiling against the new `filterRows` signature — behavior unchanged), `src/tradingbot/api/app.py`
- Create: `ui/src/features/runs/columns.ts`, `ui/src/features/runs/exportCsv.ts`, `ui/src/app/useRunRoute.ts`, `ui/src/app/useLocalStorage.ts`
- Tests: extend `ui/src/__tests__/filterRows.test.ts`; create `ui/src/__tests__/exportCsv.test.ts`, `ui/src/__tests__/useRunRoute.test.tsx`, `ui/src/__tests__/useLocalStorage.test.tsx`; add Python `tests/api/test_spa_fallback.py` (or extend the existing api test module)

**Interfaces:**

```ts
// features/runs/columns.ts — the ONE canonical column set (order + labels). RunGrid, ColumnPicker, exportCsv all consume this.
export type ColId =
  | "symbol" | "status" | "timesfm_view" | "score" | "upside_pct" | "band_pct"
  | "pcr" | "sentiment" | "catalyst_stack" | "catalyst" | "targets_t1" | "entry_ltp" | "reason";
export const COLUMN_META: { id: ColId; label: string }[] = [
  { id: "symbol", label: "Symbol" }, { id: "status", label: "Status" },
  { id: "timesfm_view", label: "TimesFM view" }, { id: "score", label: "Score" },
  { id: "upside_pct", label: "Upside %" }, { id: "band_pct", label: "Band %" },
  { id: "pcr", label: "PCR" }, { id: "sentiment", label: "Sentiment" },
  { id: "catalyst_stack", label: "Cat. stack" }, { id: "catalyst", label: "Catalyst" },
  { id: "targets_t1", label: "T1" }, { id: "entry_ltp", label: "Entry LTP" },
  { id: "reason", label: "Reason" },
];  // labels/order MUST match RunGrid's existing headers (2b-i) — this is an extraction, not a redesign.
```

```ts
// features/runs/filterRows.ts — pure, single filtering model. Refactor from (rows,status,reason,search) to (rows, FilterState).
import type { SymbolRow } from "../../api/types";
import { timesFmView } from "../../components/format";
export type StatusFilter = "all" | "elected" | "dropped";
export type TimesFmView = "bullish" | "bearish" | "neutral";
export interface NumRange { min: number | null; max: number | null }   // null bound = unbounded
export interface FilterState {
  status: StatusFilter; reason: string | null; search: string;
  ranges: { score: NumRange; band_pct: NumRange; upside_pct: NumRange };
  enums: { catalyst_type: string[]; timesfm_view: TimesFmView[]; sentiment: string[] };  // [] = no constraint
}
export const NO_RANGE: NumRange = { min: null, max: null };
export const NO_FILTERS: FilterState = {
  status: "all", reason: null, search: "",
  ranges: { score: NO_RANGE, band_pct: NO_RANGE, upside_pct: NO_RANGE },
  enums: { catalyst_type: [], timesfm_view: [], sentiment: [] },
};
// Semantics: a range is "active" if either bound is non-null. A row whose value is null FAILS an active range
//   (unknown score cannot satisfy "score ≥ X"). enum [] = pass-all; non-empty = value must be in the set.
//   timesfm_view compares against timesFmView(row.trade); catalyst_type/sentiment against raw fields (null never matches a non-empty set).
export const filterRows = (rows: SymbolRow[], f: FilterState): SymbolRow[] => { /* status/reason/search as 2b-i + ranges + enums */ };
// Pure facet helpers for the UI (options + bounds from the CURRENT rows):
export const enumOptions = (rows: SymbolRow[], field: "catalyst_type" | "sentiment"): string[];  // sorted unique non-null
export const numericBounds = (rows: SymbolRow[], field: "score" | "band_pct" | "upside_pct"): { min: number; max: number } | null;
```

```ts
// features/runs/exportCsv.ts — RFC-4180 CSV of the filtered+visible view, in current column order.
// Reuses format helpers so cell text matches the grid; does NOT import JSX. One id→text map lives here.
import type { SymbolRow } from "../../api/types";
import type { ColId } from "./columns";
export const rowsToCsv = (rows: SymbolRow[], orderedVisibleIds: ColId[]): string;
//  - header row = COLUMN_META labels for the given ids, in order
//  - values via a local Record<ColId, (r)=>string> using fmtNum/fmtPct/timesFmView/EMPTY (EMPTY stays "—")
//  - escape: wrap in double-quotes and double any embedded quote IFF value contains , " \n or \r (catalyst text can)
//  - line terminator "\r\n"
export const downloadCsv = (filename: string, csv: string): void;  // Blob + URL.createObjectURL + <a download>; revokeObjectURL
```

```ts
// app/useRunRoute.ts — hand-rolled 2-route router. ponytail: swap for react-router when /positions + /analytics land (7b/7c).
export const useRunRoute = (): { routeRunId: string | null; navigate: (id: string | null) => void };
//  routeRunId = decodeURIComponent of the /runs/(.+) match on window.location.pathname, else null
//  navigate(id) → pushState to `/runs/${encodeURIComponent(id)}` (or "/" when id is null) IFF path changes; updates internal state
//  subscribes to window "popstate" (back/forward) and re-reads pathname
```

```ts
// app/useLocalStorage.ts — persist stable display prefs only. SSR-safe (guard typeof window), JSON, try/catch on parse/write.
export function useLocalStorage<T>(key: string, initial: T): [T, (next: T | ((prev: T) => T)) => void];
```

```py
# src/tradingbot/api/app.py — deep-link SPA fallback. Register AFTER the /api routes (distinct prefix, no shadowing).
@app.get("/runs/{run_id:path}")
def spa_runs(run_id: str) -> FileResponse:
    # The client router owns /runs/:id; serve the SPA shell so a hard refresh / shared deep link
    # does not 404. Run DATA is under /api/runs/* (unaffected); /static stays mounted.
    return FileResponse(_STATIC_DIR / "index.html")
```

- [ ] **Step 0: `cd ui && npm install`** (node_modules absent in fresh checkout).
- [ ] **Step 1: Write failing tests.**
  - `filterRows.test.ts` (extend): back-compat — `filterRows(rows, NO_FILTERS)` returns all; status/reason/search still work via the object; a `score.min` excludes lower + excludes null-score rows; `upside_pct` between (min & max); `band_pct.max` upper bound; `enums.timesfm_view=["bullish"]` keeps only CALL rows (assert the word CALL never asserted as instruction — compare on view); `enums.catalyst_type` subset; empty enum = pass-all. `enumOptions`/`numericBounds` on a small fixture.
  - `exportCsv.test.ts`: header row = labels for given ids in order; a value with a comma AND a value with a `"` are quoted/escaped; a null numeric renders `—`; `timesfm_view` column shows bullish/bearish/neutral/—; ids honor order+visibility (pass a subset).
  - `useRunRoute.test.tsx`: with `window.history.pushState({},"","/runs/RUN_X")` before render, `routeRunId==="RUN_X"`; `navigate("RUN_Y")` sets it + `location.pathname==="/runs/RUN_Y"`; `navigate(null)` → "/" + null; a `popstate` event re-reads pathname. (jsdom supports history + popstate.)
  - `useLocalStorage.test.tsx`: default when key absent; setter persists + a fresh hook reads it back; malformed JSON falls back to default (no throw).
  - Python `tests/api/test_spa_fallback.py`: `TestClient(create_app(fake_store)).get("/runs/anything")` → 200 and `"TradingBot" in r.text`; `/runs/a/b` also 200; assert `/api/runs/latest` still routes to the API (not the shell) — i.e. the fallback did not shadow the API.
- [ ] **Step 2: FAIL → implement → PASS** (`npm test` for JS; `uv run --extra dev pytest tests/api -q` for Python). Update `App.tsx` to call `filterRows(rows, { status, reason, search, ...NO_FILTERS_ranges_enums })` so existing behavior + the 2b-i App tests stay green (full router/persistence wiring is Task 3).
- [ ] **Step 3: Commit** — `feat(ui): FilterState refactor + CSV/router/localStorage utils + SPA deep-link fallback`. (Explicit paths; no bundle rebuild this task.)

---

## Task 2: Grid display control — column picker, resize, density, CSV button (after Task 1)

**Files:**
- Modify: `ui/src/features/runs/RunGrid.tsx`, `ui/src/App.tsx`, `ui/src/styles.css`
- Create: `ui/src/features/runs/ColumnPicker.tsx`
- Tests: extend `ui/src/__tests__/RunGrid.test.tsx`; create `ui/src/__tests__/ColumnPicker.test.tsx`; extend the App/grid toolbar test for the CSV button + density class

**Interfaces:**

```ts
// RunGrid becomes CONTROLLED for column layout (sorting stays internal — ephemeral, not persisted).
interface RunGridProps {
  rows: SymbolRow[];
  columnVisibility: Record<string, boolean>;         // TanStack VisibilityState
  columnOrder: string[];                             // ColId order
  columnSizing: Record<string, number>;              // TanStack ColumnSizingState
  onColumnVisibilityChange: (next: Record<string, boolean>) => void;
  onColumnOrderChange: (next: string[]) => void;
  onColumnSizingChange: (next: Record<string, number>) => void;
  density: "comfortable" | "compact";
}
//  - useReactTable: state {sorting, columnVisibility, columnOrder, columnSizing}; enableColumnResizing:true,
//    columnResizeMode:"onChange"; resolve TanStack Updater<T> in each onXChange before calling the prop
//    (typeof u==="function" ? u(prev) : u).
//  - columns[] built by mapping COLUMN_META (so order/labels are single-sourced); keep the 2b-i accessor/cell logic per id.
//  - each <th> renders a resize handle (header.getResizeHandler(): onMouseDown/onTouchStart) with a .col-resize class;
//    apply header.getSize() as width. Wrapper gets className `run-grid-wrap ${density}`.
```

```ts
// features/runs/ColumnPicker.tsx — a small dropdown/popover; no dep.
interface ColumnPickerProps {
  order: string[]; visibility: Record<string, boolean>;
  onToggle: (id: ColId) => void; onReorder: (next: string[]) => void;
}
//  - button "Columns" toggles an open panel (click-away closes; Esc closes);
//  - lists COLUMN_META in `order`, each row = checkbox (visibility) + label + a drag handle;
//  - drag-reorder via native HTML5 DnD: draggable list items, onDragStart stashes id, onDrop computes the new order;
//  - "symbol" may be pinned visible (optional) — simplest: allow hiding all, empty grid already shows a message.
```

```ts
// App.tsx additions:
//  - const [prefs, setPrefs] = useLocalStorage("tb.viewPrefs", DEFAULT_PREFS)
//      DEFAULT_PREFS = { columnVisibility: {}, columnOrder: COLUMN_META.map(c=>c.id), columnSizing: {}, density: "comfortable" }
//  - pass the four fields + change handlers to RunGrid; ColumnPicker gets order+visibility;
//  - toolbar buttons: <ColumnPicker/>, a density toggle button, an "Export CSV" button.
//  - Export CSV: const visibleOrdered = prefs.columnOrder.filter(id => prefs.columnVisibility[id] !== false);
//      downloadCsv(`${run.data.run_id}.csv`, rowsToCsv(rows /* the already-filtered rows */, visibleOrdered));
```

- [ ] **Step 1: Write failing tests.**
  - `RunGrid.test.tsx` (extend): passing `columnVisibility={{ pcr: false }}` renders no "PCR" header/cell; a resize handle element is present in each header; changing `columnOrder` reorders headers.
  - `ColumnPicker.test.tsx`: opening shows one checkbox per COLUMN_META entry; clicking a checkbox fires `onToggle(id)`; a simulated drag (dragStart on A, drop on B) fires `onReorder` with A moved. (jsdom DnD: dispatch dragstart/dragover/drop with a stub dataTransfer.)
  - Toolbar/CSV test: clicking "Export CSV" calls a stubbed `URL.createObjectURL` (spy) and the anchor download; assert the Blob text (read via the captured Blob) has the header row + a data row. Density toggle flips the wrapper class `comfortable`↔`compact`.
- [ ] **Step 2: FAIL → implement → PASS** (`npm test`). Append CSS: `.run-grid-wrap.compact .run-grid td/th { padding: 2px 6px; font-size: 12px; }`, `.col-resize` handle (absolute right, cursor col-resize, width 5px), `.column-picker` panel + `.dnd-dragging`, density/export buttons matching the existing `.filter-chip`/toolbar look (use theme tokens `--panel/--border/--chip-bg/--accent`).
- [ ] **Step 3: Commit** — `feat(ui): column picker (toggle/reorder/resize), density toggle, CSV export`. (No bundle rebuild this task.)

---

## Task 3: Run-nav completion + advanced filters + router wiring (after Task 2) — slice complete

**Files:**
- Modify: `ui/src/features/runs/RunTimeline.tsx`, `ui/src/App.tsx`, `ui/src/styles.css`
- Create: `ui/src/features/runs/FiltersPanel.tsx`
- Tests: extend `ui/src/__tests__/RunTimeline.test.tsx`; create `ui/src/__tests__/FiltersPanel.test.tsx`; add a deep-link/routing test (extend `hooks.test.tsx` or new `routing.test.tsx`)
- Rebuild + commit the bundle (`src/tradingbot/api/static/`) in this task's commit.

**Interfaces:**

```ts
// RunTimeline additions (props unchanged: {runs, selectedId, onSelect}):
//  - prev/next buttons: "Older"→onSelect(runs[idx+1]) / "Newer"→onSelect(runs[idx-1]); disabled at bounds; idx from selectedId (−1→0).
//    Reuse the exact ←/→ index math (ArrowLeft=older=idx+1). Buttons + keys share one navigate(delta) helper.
//  - date picker: <input type="date" min={oldest run_date} max={newest run_date} value={selected run_date}>;
//    onChange → pick the NEWEST run whose run_date === value (runs are newest-first, so the first match) → onSelect; no match → no-op.
```

```ts
// features/runs/FiltersPanel.tsx — collapsible advanced filters; owns ranges+enums only (status/reason/search stay in chips+search).
interface FiltersPanelProps {
  rows: SymbolRow[];                 // current run rows (for option facets + numeric bounds/placeholders)
  value: Pick<FilterState, "ranges" | "enums">;
  onChange: (next: Pick<FilterState, "ranges" | "enums">) => void;
}
//  - three numeric range rows (score/band_pct/upside_pct): two <input type="number"> min/max each; placeholders from numericBounds().
//  - three enum groups: catalyst_type + sentiment options via enumOptions(rows,...); timesfm_view = fixed [bullish,bearish,neutral];
//    each option a checkbox toggling membership in the string[].
//  - a "Clear" button → resets ranges+enums to NO_FILTERS' (leaves status/reason/search alone); header shows active count.
```

```ts
// App.tsx final wiring:
//  - selection via useRunRoute: const {routeRunId, navigate} = useRunRoute();
//      const activeId = routeRunId ?? runs.data?.[0]?.run_id ?? null;   // deep link wins; else latest
//      pass onSelect={navigate} to RunTimeline; Latest pin already calls onSelect(runs[0]) → navigate. Remove the old selectedId useState.
//  - advanced filters: const [adv, setAdv] = useState<Pick<FilterState,"ranges"|"enums">>(NO_FILTERS pick);
//      const filters: FilterState = { status, reason, search, ...adv };
//      rows = filterRows(symbols ?? [], filters);   // one pure call, everything folded in
//  - render <FiltersPanel rows={symbols??[]} value={adv} onChange={setAdv}/> in the toolbar.
//  - keep the existing "/" search focus + status chips + reason facet exactly as 2b-i.
```

- [ ] **Step 1: Write failing tests.**
  - `RunTimeline.test.tsx` (extend): "Older"/"Newer" buttons fire onSelect with the adjacent run and disable at first/last; a date-input change to an existing run_date fires onSelect for that run; a date with no run fires nothing.
  - `FiltersPanel.test.tsx`: rendering surfaces catalyst_type + sentiment options from rows; toggling a `timesfm_view` checkbox calls onChange with it in the array; typing a score min calls onChange with `ranges.score.min`; "Clear" resets to empty. (The narrowing itself is already covered by `filterRows.test.ts`; here just assert the panel emits the right FilterState deltas.)
  - Routing test: render `<App/>` (with stubbed fetch returning ≥2 run headers + a run doc) after `history.pushState({},"","/runs/<id2>")` → the grid header/meta reflects run id2, not the latest; clicking a different run chip changes `window.location.pathname` to `/runs/<thatId>`.
- [ ] **Step 2: FAIL → implement → PASS** (`npm test`). Append CSS: `.filters-panel` (collapsible, theme tokens), number/date inputs styled to match the search box, prev/next buttons matching `.latest-pin`.
- [ ] **Step 3: Full verification + build.**
  - `cd ui && npm test` (all vitest green — old + new).
  - `npm run build` → assert output lands in `src/tradingbot/api/static/` (index.html with `<title>TradingBot</title>` + assets/).
  - From repo root: `uv run --extra dev pytest -q` (Python green — incl. the new SPA fallback test) and `uv run --extra dev ruff check src tests` (clean).
  - Smoke note: `uv run tradingbot-api` on :8100 → open `/`, pick a run (URL becomes `/runs/<id>`), hard-refresh that URL (SPA shell served, run loads), toggle a column, set a score range, Export CSV. Record what was observed (runs count, a symbol row, the CSV first line) in the report. If no local mongod, smoke the SPA fallback + endpoints via a `TestClient` instead and say so.
- [ ] **Step 4: Commit** — `feat(ui): run-nav (prev/next + date picker + deep links) and advanced filters (Phase 7 slice 2b-ii complete)` **including the rebuilt `src/tradingbot/api/static/` bundle**.

---

## Definition of done (2b-ii)

- `tradingbot-api` on :8100: from any run you can deep-link `/runs/:runId` (survives hard refresh), step Older/Newer or jump by date, show/hide + reorder + resize + toggle density on the grid, filter by numeric ranges and enum multiselects on top of the 2b-i status/reason/search, and Export CSV of exactly the filtered+visible view — column layout + density persist across reload, all self-contained (no CDN, **no new npm deps**).
- vitest suite green (old + new); Python suite green (incl. SPA fallback test); ruff clean; rebuilt bundle committed.
- **Named deferrals honored:** no server-side/named saved views (7b), no `before=` pagination (YAGNI), no F&O-only filter (no field). Implicit localStorage persistence covers only column layout + density.
- **Next:** 7b positions (CRUD + P&L + badges + close-flow + the real `/api/views` + `view_prefs` writes), 7c drawer+analytics (+ backtest/expectancy port), 7d order boundary; Phase 8 parity (needs fresh Fyers token).

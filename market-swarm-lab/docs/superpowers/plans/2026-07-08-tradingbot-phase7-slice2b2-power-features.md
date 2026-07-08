# TradingBot Phase 7 slice 2b-ii — Runs Explorer power features (React SPA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is TDD: write failing tests → implement → pass → commit.
>
> **Rev 2** — incorporates the adversarial plan-review (verdict was CHANGES_REQUIRED; 2 blocking + 10 minor confirmed). Fixes folded in are tagged `[review]` inline.

**Goal:** Complete the Runs Explorer's spec-§1.1 power features on top of the shipped 2b-i core: **run-navigation completion** (URL deep links `/runs/:runId`, on-screen prev/next buttons, native date picker), **Kibana-style display control** (column picker with show/hide + drag-reorder + resize, density toggle, CSV export of the filtered+sorted+visible view), and **advanced filters** (numeric ranges + enum multiselects) — all built with **zero new npm dependencies** (TanStack Table built-ins + native HTML inputs + the History API), and one small FastAPI change (a deep-link SPA fallback route).

**Ponytail scope (read before implementing):** the spec's §1.1 features are user-approved, so we build them — but we build the laziest version that satisfies each, and we defer four items with reasons:

| Deferred | Why | When |
|----------|-----|------|
| **Server-side / named saved views** | Spec §2/§3 put views in a `view_prefs` collection behind `GET/POST /api/views` — that endpoint + Mongo write path is 7b work (spec §5 buckets it under 7a, but it shares positions' write infra so it moves to 7b deliberately). A localStorage clone now is throwaway. | 7b. A cheap *implicit* localStorage persistence of column layout + density is the stand-in (not named multi-view management). |
| **`before=` pagination on the timeline** | 15 runs exist; `_LIST_WINDOW = 365` already covers a year of daily runs. No scale to paginate. | When run count approaches the window or the timeline is measurably slow. |
| **"F&O-only" enum filter** | `SymbolRow` carries no F&O / `is_fno` field (see `api/types.ts`); the run doc doesn't emit it. | When an F&O flag is added to the run doc. Named, not silent. |
| **Conviction/factor columns** (OI buildup, delivery, promoter trend, deals, pre-open) `[review #5]` | Spec §1.1 lists these as column-picker fields, but they live in `SymbolRow.factors`, which `types.ts` declares `factors: null` (storage/doc.py always emits None — the SRC deals/shareholding/delivery collectors were never ported; `ConvictionFlags.has_deal/promoter_trend` are always None). Genuinely unrenderable today. | The factors-port slice (carry `factors` in `storage/doc.py`, then add COLUMN_META entries). Named, not silent. |

Everything else in §1.1 that 2b-i did not cover **is** in this slice, **except** the factor-backed columns deferred above. `[review #5]` Note two spec-§1.1 columns whose data IS present are added here (they were absent from the 2b-i grid): `catalyst_type` ("catalyst + type") and `targets.t2` ("T1/T2") — see COLUMN_META. `[review #13]`

**Architecture (dashboard spec §1.1 + §4):** same `ui/` SPA (Vite + React 18 + TS), same feature folders. New URL routing via a hand-rolled History-API hook (`app/useRunRoute.ts`) — **not** react-router. Rationale: only two client routes exist today (`/` and `/runs/:id`); react-router earns its keep once `/positions` (7b) and `/analytics` (7c) land, at which point we swap the hook for it. The hook carries a `ponytail:` comment naming that upgrade path. Column visibility/order/sizing use TanStack Table's built-in state (no dnd-kit). Filtering stays a single **pure** function (`filterRows`) — refactored from a 4-arg signature to one `FilterState` object so adding a predicate is an additive change, not a signature break.

**Tech Stack (UNCHANGED — no new deps):** the existing `ui/package.json` (React 18, `@tanstack/react-table` 8.21.3 — confirmed to support columnVisibility/columnOrder/columnSizing/enableColumnResizing/getResizeHandler, `@tanstack/react-query` 5, vite 5, vitest 2, @testing-library/react 16, jsdom). Native `<input type="date">`, `<input type="number">`, checkboxes, `Blob`/`URL.createObjectURL`, `window.history`/`popstate`. **If any task reaches for a new dependency, stop — the design is wrong.**

## Global Constraints

- **Repo (work ONLY here):** `/Users/jagadeeshpulamarasetti/OwnCode/TradingBot`. (Note: earlier plans wrote the stale path `~/Code/own/TradingBot`; the live checkout is `~/OwnCode/TradingBot`.) SRC reference (read-only): `/Users/jagadeeshpulamarasetti/OwnCode/TradingBotMiroFish/market-swarm-lab`. Spec copies travel in-repo at `ai/context/refs/2026-07-07-tradingbot-dashboard-design.md` (§1.1, §4) and `ai/context/refs/2026-07-08-tradingbot-phase7-slice2b1-runs-explorer.md`.
- **`node_modules` IS present** (installed at planning time; vitest baseline 48/48 green). If a fresh checkout is used, run `cd ui && npm install` first.
- **Prerequisite:** 2b-i merged (code HEAD `1c921be`; commits after are docs-only). The 2a API payload shapes remain the committed contract — do not change `api/types.ts` field shapes; only *add* the SPA fallback route to `api/app.py`.
- **Self-contained bundle, no CDN.** The BUILT bundle under `src/tradingbot/api/static/` is committed — **rebuilt + committed once, in Task 3's final commit** (interim Task 1/2 commits are source+test only; no test compares bundle-to-source — only `tests/api/test_app.py:229` asserts `"TradingBot" in r.text` on raw HTML, which the old bundle satisfies).
- **Locked renames/glyphs (from 2b-i — do not regress):** `trade` renders as **"TimesFM view"** (CALL→bullish/PUT→bearish/HOLD→neutral/null→`—`); `EMPTY = "—"`; `ui/index.html` MUST keep `<title>TradingBot</title>`.
- UI tests headless (`npm test` = `vitest run`/jsdom). **`vitest run` does NOT type-check** (esbuild strips types); the type gate is `tsc -b` inside `npm run build` (Task 3). So a missing/extra prop only fails at Task 3 unless caught earlier — Tasks 1/2 must keep the tree tsc-clean, not just vitest-green. `[review #3/#7]`
- The Python suite must stay green (`uv run --extra dev pytest -q`, baseline 361 passed/1 skipped); the ONLY Python change is the new SPA fallback route + its test.
- Commit per task, explicit-path `git add` (never `git add -A`), retry on `index.lock`. JS work under `ui/` only (+ the rebuilt bundle in Task 3).
- **Do NOT persist filters or sort** to localStorage — run-specific/ephemeral. Persist only column visibility/order/sizing + density.

---

## File Structure (slice 2b-ii)

```
ui/src/
  app/
    useRunRoute.ts         NEW  history-API router: {routeRunId, navigate(id|null)} — navigate is useCallback-stable [review #15]
    useLocalStorage.ts     NEW  useLocalStorage<T>(key, initial) → [T, setT]  (JSON, try/catch, SSR-safe guard)
  features/runs/
    columns.ts             NEW  ColId union + COLUMN_META [{id,label}] (canonical order + labels; single source)
    filterRows.ts          MOD  FilterState object + NO_FILTERS + enumOptions() + numericBounds(); filterRows(rows, f)
    exportCsv.ts           NEW  rowsToCsv(rows, orderedVisibleIds) → string (RFC-4180 escaping) + downloadCsv()
    RunGrid.tsx            MOD  OPTIONAL controlled columnVisibility/order/sizing (uncontrolled fallback); resize; owns Export-CSV button
    ColumnPicker.tsx       NEW  visibility checkboxes (symbol pinned non-hideable) + native drag-reorder over COLUMN_META
    FiltersPanel.tsx       NEW  numeric ranges (score/band/upside) + enum multiselects (catalyst_type/timesfm_view/sentiment)
    RunTimeline.tsx        MOD  + prev/next buttons + native date picker (client-side date→run, value-guarded)
  App.tsx                  MOD  useRunRoute for selection+deep links; owns+persists view prefs; wires FiltersPanel/density/ColumnPicker
  styles.css               MOD  append: table-layout fixed + resize handles, column-picker/filters panels, density-compact, prev/next, date input
src/tradingbot/api/app.py  MOD  + GET /runs/{run_id:path} → FileResponse(index.html)  (INSIDE create_app, before `return app`) [review #4]
src/tradingbot/api/static/ MOD  rebuilt bundle, committed in Task 3
```

---

## Task 1: Foundations — pure utils, hooks, API fallback (no visual change)

Everything shared by later tasks lands here first so Tasks 2/3 only add UI. All units are pure/testable.

**Files:**
- Modify: `ui/src/features/runs/filterRows.ts`, `ui/src/App.tsx` (only to keep it compiling against the new `filterRows` signature — behavior unchanged), `ui/src/__tests__/RunGrid.test.tsx` **`[review #1]` — it calls the OLD 4-arg `filterRows(ROWS,"elected",null,"")` (line ~89) and `filterRows(ROWS,"all",null,"merger")` (line ~92); convert both to the object form or `vitest run` throws (`f.status`/`f.ranges` off a string) and Task 1's green gate is red**, `src/tradingbot/api/app.py`
- Create: `ui/src/features/runs/columns.ts`, `ui/src/features/runs/exportCsv.ts`, `ui/src/app/useRunRoute.ts`, `ui/src/app/useLocalStorage.ts`
- Tests: extend `ui/src/__tests__/filterRows.test.ts`; create `ui/src/__tests__/exportCsv.test.ts`, `ui/src/__tests__/useRunRoute.test.tsx`, `ui/src/__tests__/useLocalStorage.test.tsx`; add Python `tests/api/test_spa_fallback.py`

**Interfaces:**

```ts
// features/runs/columns.ts — the ONE canonical column set (order + labels). RunGrid, ColumnPicker, exportCsv all consume this.
// 13 columns from the 2b-i grid + catalyst_type + targets_t2 (spec §1.1 "catalyst + type" / "T1/T2"; data present in SymbolRow). [review #13]
export type ColId =
  | "symbol" | "status" | "timesfm_view" | "score" | "upside_pct" | "band_pct"
  | "pcr" | "sentiment" | "catalyst_stack" | "catalyst" | "catalyst_type"
  | "targets_t1" | "targets_t2" | "entry_ltp" | "reason";
export const COLUMN_META: { id: ColId; label: string }[] = [
  { id: "symbol", label: "Symbol" }, { id: "status", label: "Status" },
  { id: "timesfm_view", label: "TimesFM view" }, { id: "score", label: "Score" },
  { id: "upside_pct", label: "Upside %" }, { id: "band_pct", label: "Band %" },
  { id: "pcr", label: "PCR" }, { id: "sentiment", label: "Sentiment" },
  { id: "catalyst_stack", label: "Cat. stack" }, { id: "catalyst", label: "Catalyst" },
  { id: "catalyst_type", label: "Cat. type" },
  { id: "targets_t1", label: "T1" }, { id: "targets_t2", label: "T2" },
  { id: "entry_ltp", label: "Entry LTP" }, { id: "reason", label: "Reason" },
];  // existing 13 labels/order MUST match RunGrid's 2b-i headers; catalyst_type + targets_t2 are the two additions.
export const HIDEABLE = (id: ColId): boolean => id !== "symbol";  // symbol is the row identifier: never hideable. [review #9]
```

```ts
// features/runs/filterRows.ts — pure, single filtering model. Refactor (rows,status,reason,search) → (rows, FilterState).
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
export const filterRows = (rows: SymbolRow[], f: FilterState): SymbolRow[] => { /* status/reason/search (2b-i) + ranges + enums */ };
export const enumOptions = (rows: SymbolRow[], field: "catalyst_type" | "sentiment"): string[];  // sorted unique non-null
export const numericBounds = (rows: SymbolRow[], field: "score" | "band_pct" | "upside_pct"): { min: number; max: number } | null;
```

```ts
// features/runs/exportCsv.ts — RFC-4180 CSV of the filtered+sorted+visible view, in current column order.
// Reuses format helpers so cell text matches the grid; does NOT import JSX. One id→text map lives here.
import type { SymbolRow } from "../../api/types";
import type { ColId } from "./columns";
export const rowsToCsv = (rows: SymbolRow[], orderedVisibleIds: ColId[]): string;
//  - header row = COLUMN_META labels for the given ids, in order
//  - values via a local Record<ColId,(r)=>string> using fmtNum/fmtPct/timesFmView/EMPTY (EMPTY stays "—")
//  - escape: wrap in double-quotes and double any embedded quote IFF value contains , " \n or \r (catalyst text can)
//  - line terminator "\r\n"
export const downloadCsv = (filename: string, csv: string): void;  // Blob + URL.createObjectURL + <a download>; revokeObjectURL
```

```ts
// app/useRunRoute.ts — hand-rolled 2-route router. ponytail: swap for react-router when /positions + /analytics land (7b/7c).
export const useRunRoute = (): { routeRunId: string | null; navigate: (id: string | null) => void };
//  routeRunId = decodeURIComponent of the /runs/(.+) match on window.location.pathname, else null
//  navigate = useCallback([]) (touches only window.history/location + setState) so consumers can keep it in dep arrays [review #15]
//  navigate(id) → pushState to `/runs/${encodeURIComponent(id)}` (or "/" when id is null) IFF path changes; updates internal state
//  subscribes to window "popstate" (back/forward) and re-reads pathname; reads pathname on first render (cold deep-link works)
```

```ts
// app/useLocalStorage.ts — persist stable display prefs only. SSR-safe (guard typeof window), JSON, try/catch on parse/write.
export function useLocalStorage<T>(key: string, initial: T): [T, (next: T | ((prev: T) => T)) => void];
```

```py
# src/tradingbot/api/app.py — deep-link SPA fallback. Add INSIDE create_app(store), before `return app`, [review #4]
# alongside the other @app.get handlers (NOT at module level — `app` is local to create_app):
    @app.get("/runs/{run_id:path}")
    def spa_runs(run_id: str) -> FileResponse:
        # The client router owns /runs/:id; serve the SPA shell so a hard refresh / shared deep link
        # does not 404. Run DATA is under /api/runs/* (distinct prefix, unaffected); /static stays mounted.
        return FileResponse(_STATIC_DIR / "index.html")
```

- [ ] **Step 1: Write failing tests.**
  - `filterRows.test.ts` (extend): `filterRows(rows, NO_FILTERS)` returns all; status/reason/search still work via the object; `score.min` excludes lower + excludes null-score rows; `upside_pct` between (min & max); `band_pct.max` upper bound; `enums.timesfm_view=["bullish"]` keeps only CALL rows (assert on the *view*, never the word CALL as instruction); `enums.catalyst_type` subset; empty enum = pass-all. `enumOptions`/`numericBounds` on a small fixture.
  - `exportCsv.test.ts`: header = labels for given ids in order; a comma value AND a `"` value are quoted/escaped; a null numeric → `—`; `timesfm_view` col → bullish/bearish/neutral/—; ids honor order+visibility (pass a subset).
  - `useRunRoute.test.tsx`: with `history.pushState({},"","/runs/RUN_X")` before render → `routeRunId==="RUN_X"`; `navigate("RUN_Y")` sets it + `location.pathname==="/runs/RUN_Y"`; `navigate(null)` → "/" + null; a `popstate` re-reads pathname; `navigate` identity is stable across renders.
  - `useLocalStorage.test.tsx`: default when key absent; setter persists + a fresh hook reads it back; malformed JSON falls back to default (no throw).
  - Python `tests/api/test_spa_fallback.py`: `get("/runs/anything")` → 200 + `"TradingBot" in r.text`; `/runs/a/b` → 200; `/api/runs/latest` still routes to the API (not the shell) — the fallback did not shadow the API.
- [ ] **Step 2: FAIL → implement → PASS** (`npm test`; `uv run --extra dev pytest tests/api -q`). Update `App.tsx` to call `filterRows(rows, { status, reason, search, ...NO_FILTERS ranges/enums })` and convert the two `RunGrid.test.tsx` old-arg calls (`[review #1]`) so existing behavior + all UI tests stay green (App has no render test of its own — it gets its first in Task 3; do NOT claim a nonexistent "App test" as the safety net `[review #2]`).
- [ ] **Step 3: Commit** — `feat(ui): FilterState refactor + CSV/router/localStorage utils + SPA deep-link fallback`. (Explicit paths; no bundle rebuild this task; leave the tree `tsc -b`-clean.)

---

## Task 2: Grid display control — column picker, resize, density, CSV button (after Task 1)

**Files:**
- Modify: `ui/src/features/runs/RunGrid.tsx`, `ui/src/App.tsx`, `ui/src/styles.css`
- Create: `ui/src/features/runs/ColumnPicker.tsx`
- Tests: extend `ui/src/__tests__/RunGrid.test.tsx`; create `ui/src/__tests__/ColumnPicker.test.tsx`; create `ui/src/__tests__/AppToolbar.test.tsx` (App's FIRST render test — CSV button + density class; App had no prior coverage `[review #2]`)

**Interfaces:**

```ts
// RunGrid — the 4 layer props are OPTIONAL with an uncontrolled internal fallback (mirrors how `sorting` already lives in
//   RunGrid.useState). This keeps the 8 existing <RunGrid rows={ROWS}/> call sites compiling under tsc -b. [review #3/#7]
interface RunGridProps {
  rows: SymbolRow[];
  runId?: string;                                       // for the CSV filename
  columnVisibility?: Record<string, boolean>;           // VisibilityState — default {} (all visible)
  columnOrder?: string[];                               // ColId order — default COLUMN_META.map(c=>c.id)
  columnSizing?: Record<string, number>;                // ColumnSizingState — default {}
  onColumnVisibilityChange?: (next: Record<string, boolean>) => void;
  onColumnOrderChange?: (next: string[]) => void;
  onColumnSizingChange?: (next: Record<string, number>) => void;
  density?: "comfortable" | "compact";                 // default "comfortable"
}
//  - useReactTable state {sorting (internal), columnVisibility, columnOrder, columnSizing}; when a prop is provided it is
//    controlled, else RunGrid keeps its own useState (uncontrolled). Resolve TanStack Updater<T> in each onXChange before
//    calling the prop (typeof u==="function" ? u(prev) : u).
//  - enableColumnResizing:true, columnResizeMode:"onEnd"  [review #10 — "onChange" fires per-mousemove → localStorage write-storm
//    on the 507-row grid; "onEnd" commits size once on pointer-up]
//  - columns[] built by mapping COLUMN_META (single-sourced order/labels); keep 2b-i accessor/cell logic per id; ADD:
//      catalyst_type (accessorFn r.catalyst_type ?? ""; cell r.catalyst_type ?? EMPTY),
//      targets_t2 (accessorFn numOr(r.targets?.t2 ?? null); cell fmtNum(r.targets?.t2 ?? null, 1)) — mirrors targets_t1. [review #13]
//  - each <th> renders style={{ width: header.getSize() }} + a resize handle (header.getResizeHandler()). [review #8]
//  - wrapper className `run-grid-wrap ${density}`.
//  - EMPTY-STATE: keep the rows.length===0 message AND add a visible-column guard — if table.getVisibleLeafColumns().length===0
//    render an "All columns hidden" message (hiding all columns must not render a silent blank table). [review #9]
//  - Export-CSV button lives HERE (RunGrid holds the sorted row model + visible/order state; App only has pre-sort rows):
//      onClick → downloadCsv(`${runId ?? "run"}.csv`,
//        rowsToCsv(table.getSortedRowModel().rows.map(r=>r.original),
//                  table.getVisibleLeafColumns().map(c=>c.id as ColId)))
//    so the CSV is exactly the filtered+SORTED+visible view. [review #11]
```

```ts
// features/runs/ColumnPicker.tsx — small dropdown/popover; no dep.
interface ColumnPickerProps {
  order: string[]; visibility: Record<string, boolean>;
  onToggle: (id: ColId) => void; onReorder: (next: string[]) => void;
}
//  - button "Columns" toggles a panel (click-away + Esc close);
//  - lists COLUMN_META in `order`; each row = checkbox (visibility) + label + drag handle;
//    the "symbol" checkbox is disabled/omitted — HIDEABLE("symbol") is false (row identifier + CSV key). [review #9]
//  - drag-reorder via native HTML5 DnD (draggable items; onDragStart stashes id; onDrop computes new order). No dnd lib.
```

```ts
// App.tsx additions:
//  - const [prefs, setPrefs] = useLocalStorage("tb.viewPrefs", DEFAULT_PREFS)
//      DEFAULT_PREFS = { columnVisibility: {}, columnOrder: COLUMN_META.map(c=>c.id), columnSizing: {}, density: "comfortable" }
//  - pass prefs.* + change handlers + runId={activeId} to RunGrid; ColumnPicker gets order+visibility;
//  - toolbar: <ColumnPicker/>, a density toggle button (flips prefs.density). (Export CSV button is rendered by RunGrid.)
```

- [ ] **Step 1: Write failing tests.**
  - `RunGrid.test.tsx` (extend): `columnVisibility={{ pcr: false }}` → no "PCR" header/cell; a `.col-resize` handle present per header; `columnOrder` change reorders headers; a `<th>` carries a width style; hiding every column shows the "All columns hidden" message; the two new columns (Cat. type, T2) render. **Also thread the new optional props are omitted-safe** — the existing `<RunGrid rows={ROWS}/>` renders must still compile & pass (that's the point of making them optional).
  - `ColumnPicker.test.tsx`: one checkbox per hideable COLUMN_META entry; the "symbol" checkbox is absent/disabled; clicking a checkbox fires `onToggle(id)`; a simulated drag (dragstart A, drop B, stub dataTransfer) fires `onReorder` with A moved.
  - `AppToolbar.test.tsx`: render `<App/>` (stubbed fetch); clicking "Export CSV" calls a spied `URL.createObjectURL` and the anchor download; read the captured Blob text → has header row + a data row in visible-column order. Density toggle flips the wrapper class `comfortable`↔`compact`.
- [ ] **Step 2: FAIL → implement → PASS** (`npm test`; verify `tsc -b` clean too — `[review #3/#7]` this is the gate vitest won't catch). Append CSS: **`.run-grid { table-layout: fixed; }`** (keep `width:100%`) so `getSize()` widths actually drive columns `[review #8]`; `.col-resize` handle (absolute right, `cursor: col-resize`, ~5px, touch-none); `.run-grid-wrap.compact .run-grid td/th { padding: 2px 6px; font-size: 12px; }`; `.column-picker` panel + `.dnd-dragging`; density/export buttons matching the existing `.filter-chip`/`.latest-pin` look (theme tokens `--panel/--border/--chip-bg/--accent`).
- [ ] **Step 3: Commit** — `feat(ui): column picker (toggle/reorder/resize), density toggle, CSV export`. (No bundle rebuild this task.)

---

## Task 3: Run-nav completion + advanced filters + router wiring (after Task 2) — slice complete

**Files:**
- Modify: `ui/src/features/runs/RunTimeline.tsx`, `ui/src/App.tsx`, `ui/src/styles.css`
- Create: `ui/src/features/runs/FiltersPanel.tsx`
- Tests: extend `ui/src/__tests__/RunTimeline.test.tsx`; create `ui/src/__tests__/FiltersPanel.test.tsx`; create `ui/src/__tests__/routing.test.tsx`
- Rebuild + commit the bundle (`src/tradingbot/api/static/`) in this task's commit.

**Interfaces:**

```ts
// RunTimeline additions (props unchanged: {runs, selectedId, onSelect}):
//  - prev/next buttons: "Older"→onSelect(runs[idx+1]) / "Newer"→onSelect(runs[idx-1]); disabled at bounds; idx from selectedId
//    (−1→0). Reuse the exact ←/→ index math (ArrowLeft=older=idx+1). Buttons + keys share one navigate(delta) helper.
//  - date picker: <input type="date" min={oldest run_date} max={newest run_date}
//                   value={runs.find(r=>r.run_id===selectedId)?.run_date ?? ""} />   [review #12 — guard: a stale/deleted deep
//    link makes selectedId absent from runs → value must be "" not undefined, else React warns controlled→uncontrolled]
//    onChange → pick the NEWEST run whose run_date === value (runs are newest-first → first match) → onSelect; no match → no-op.
//    NOTE: date is date-granular over timestamp run_ids; on days with >1 run it lands on the newest of that date and re-picking
//    the current date is a native no-op — the chip strip + prev/next remain the complete per-run nav. [review #12]
//    (run_date is confirmed ISO YYYY-MM-DD in storage/doc.py, so the native input binds directly.)
```

```ts
// features/runs/FiltersPanel.tsx — collapsible advanced filters; owns ranges+enums only (status/reason/search stay in chips+search).
interface FiltersPanelProps {
  rows: SymbolRow[];                 // current run rows (option facets + numeric bounds/placeholders)
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
//      (A stale/deleted /runs/:id → useRun 404 → the existing error banner already handles it. [review adversarial])
//  - advanced filters: const [adv, setAdv] = useState<Pick<FilterState,"ranges"|"enums">>(picked from NO_FILTERS);
//      const filters: FilterState = { status, reason, search, ...adv };
//      rows = filterRows(symbols ?? [], filters);   // one pure call, everything folded in
//  - render <FiltersPanel rows={symbols??[]} value={adv} onChange={setAdv}/> in the toolbar. Keep the 2b-i "/" search focus + status chips + reason facet.
```

- [ ] **Step 1: Write failing tests.**
  - `RunTimeline.test.tsx` (extend): "Older"/"Newer" fire onSelect with the adjacent run + disable at first/last; a date-input change to an existing run_date fires onSelect for that run; a date with no run fires nothing; value is `""` (not undefined) when selectedId is absent from runs.
  - `FiltersPanel.test.tsx`: renders catalyst_type + sentiment options from rows; toggling a `timesfm_view` checkbox calls onChange with it in the array; typing a score min calls onChange with `ranges.score.min`; "Clear" resets. (Narrowing itself is covered in `filterRows.test.ts`.)
  - `routing.test.tsx`: render `<App/>` (stubbed fetch ≥2 headers + a run doc) after `history.pushState({},"","/runs/<id2>")` → grid meta reflects id2, not the latest; clicking a different chip changes `location.pathname` to `/runs/<thatId>`.
- [ ] **Step 2: FAIL → implement → PASS** (`npm test`). Append CSS: `.filters-panel` (collapsible, theme tokens); number/date inputs matching the search box; prev/next buttons matching `.latest-pin`.
- [ ] **Step 3: Full verification + build.**
  - `cd ui && npm test` (all vitest green — old + new).
  - `npm run build` → `tsc -b` clean + output in `src/tradingbot/api/static/` (index.html `<title>TradingBot</title>` + assets/).
  - From repo root: `uv run --extra dev pytest -q` (Python green, incl. the new SPA fallback test) and `uv run --extra dev ruff check src tests` (clean).
  - Smoke note: `uv run tradingbot-api` on :8100 → `/`, pick a run (URL → `/runs/<id>`), hard-refresh that URL (SPA shell served, run loads), hide a column, set a score range, Export CSV (assert its first line = header, second = a row). Record observations (runs count, a symbol row, the CSV first line). If no local mongod, smoke the SPA fallback + endpoints via `TestClient` and say so.
- [ ] **Step 4: Commit** — `feat(ui): run-nav (prev/next + date picker + deep links) and advanced filters (Phase 7 slice 2b-ii complete)` **including the rebuilt `src/tradingbot/api/static/` bundle**.

---

## Definition of done (2b-ii)

- `tradingbot-api` on :8100: deep-link `/runs/:runId` (survives hard refresh), step Older/Newer or jump by date, show/hide (symbol pinned) + reorder + resize + toggle density, filter by numeric ranges + enum multiselects on top of 2b-i status/reason/search, and Export CSV of exactly the **filtered + sorted + visible** view — column layout + density persist across reload, self-contained (no CDN, **no new npm deps**).
- vitest green (old + new); `tsc -b` clean; Python green (incl. SPA fallback test); ruff clean; rebuilt bundle committed.
- **Named deferrals honored:** no server-side/named saved views (7b), no `before=` pagination (YAGNI), no F&O-only filter (no field), no factor/conviction columns (`factors` is null until ported). Implicit localStorage persistence covers only column layout + density.
- **Next:** 7b positions (CRUD + P&L + badges + close-flow + the real `/api/views` + `view_prefs` writes), 7c drawer+analytics (+ backtest/expectancy port), 7d order boundary; Phase 8 parity (needs fresh Fyers token).

# TradingBot Phase 7 slice 2b-i — Runs Explorer core (React SPA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dashboard's core Runs Explorer as a self-contained React SPA served by the 2a FastAPI app: run timeline navigation (chips + ←/→ keys + Latest pin), the symbols grid (TanStack Table: multi-sort, status chips + drop-reason facet, symbol search, TimesFM-view rename), and the run-diff banner — built with Vite and emitted into `src/tradingbot/api/static/` so `tradingbot-api` serves the real UI at `/`.

**Architecture (dashboard spec §4):** `ui/` at the repo root (Vite + React 18 + TypeScript). Data via a tiny typed fetch client + TanStack react-query hooks (one hook per 2a endpoint). Feature folders `app/`, `api/`, `features/runs/`, `components/`. No UI kit, no CDN — hand-rolled CSS with dark default + light via `prefers-color-scheme`. Build output → `../src/tradingbot/api/static/` (replaces the placeholder; FastAPI already serves it). Component/hook tests with vitest + @testing-library/react + a fetch stub (msw NOT used — keep deps lean).

**Tech Stack:** Node ≥20 (v23 present), Vite 5, React 18, TypeScript 5, @tanstack/react-table 8, @tanstack/react-query 5, vitest + @testing-library/react + jsdom.

## Global Constraints

- Work ONLY inside `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`. Dashboard spec (read-only): `/Users/jagadeeshpulamarasetti/Code/own/TradingBotMiroFish/market-swarm-lab/docs/superpowers/specs/2026-07-07-tradingbot-dashboard-design.md` §1.1/§4; SRC visual reference: `apps/watchlist/static/dashboard.html` (single-file predecessor — the look to match/beat, not code to port).
- Prerequisite: slice 2a merged (HEAD `dbdb11a`; API payload shapes are the committed contract — run headers from `/api/runs`, full doc from `/api/runs/{id}` with `symbols[]` rows keyed `symbol/status/reason/trade/score/upside_pct/band_pct/size_factor/pcr/sentiment/catalyst_stack/factors/targets/entry_ltp/catalyst/catalyst_type`, diff from `/api/runs/{id}/diff` = `{run_id, prev_run_id, first_run, entered[], exited[], movers[]}`).
- **Self-contained bundle:** no external network at runtime (no CDN fonts/scripts). `vite build` output is committed? NO — build artifacts are NOT committed; `api/static/` gets `.gitignore`d built assets EXCEPT a committed fallback `index.html` placeholder is REPLACED at build time. Decision: commit the BUILT bundle (it's how one-process serving works without Node in prod) — `api/static/` contents ARE committed each build (small, ~200KB). Note this in the repo README section of Task 1.
- **Rename rule (spec):** the stored `trade` field renders as **"TimesFM view"** — CALL→"bullish", PUT→"bearish", HOLD→"neutral", null→"—". Never render the word CALL/PUT as a trade instruction.
- **Named deferrals (2b-ii / later slices):** column picker + drag-reorder/resize + density toggle + CSV export + saved views (localStorage or `/api/views`) → 2b-ii; numeric-range & enum filters beyond status/search → 2b-ii; position badges → 7b; symbol drawer → 7c; `before=` pagination → with 2b-ii if needed.
- UI tests run headless (`npm test` = vitest run, jsdom); the Python suite must stay green (`uv run --extra dev pytest -q`) — the only Python-side change is the static dir content + a README note.
- Commit per task. JS work happens under `ui/` only (+ built output under `src/tradingbot/api/static/`).

---

## File Structure (slice 2b-i)

```
ui/
├── package.json  vite.config.ts  tsconfig.json  index.html
├── src/
│   ├── main.tsx  App.tsx  styles.css          # app shell, theme, layout
│   ├── api/client.ts                          # typed fetchers for the 5 endpoints
│   ├── api/hooks.ts                           # useRuns/useRun/useLatestRun/useDiff (react-query)
│   ├── api/types.ts                           # RunHeader, RunDoc, SymbolRow, DiffResult
│   ├── features/runs/RunTimeline.tsx          # chips, ←/→ keys, Latest pin
│   ├── features/runs/RunGrid.tsx              # TanStack table: columns, multi-sort, filters
│   ├── features/runs/DiffBanner.tsx           # entered/exited/movers, collapsible
│   ├── features/runs/StatusChips.tsx          # elected/dropped/all + drop-reason facet
│   └── components/format.ts                   # fmtNum, fmtPct, timesFmView(trade)
│   └── __tests__/ (format.test.ts, hooks.test.tsx, RunGrid.test.tsx, RunTimeline.test.tsx, DiffBanner.test.tsx)
src/tradingbot/api/static/                     # vite build output (committed)
```

---

## Task 1: UI scaffold + typed API layer

**Files:**
- Create: `ui/package.json`, `ui/vite.config.ts`, `ui/tsconfig.json`, `ui/index.html`, `ui/src/main.tsx`, `ui/src/App.tsx` (placeholder shell), `ui/src/styles.css` (theme tokens: dark default + light), `ui/src/api/types.ts`, `ui/src/api/client.ts`, `ui/src/api/hooks.ts`, `ui/src/components/format.ts`, tests `ui/src/__tests__/format.test.ts`, `ui/src/__tests__/hooks.test.tsx`

**Interfaces:**

```jsonc
// package.json (exact deps — pin majors)
{ "name": "tradingbot-ui", "private": true, "type": "module",
  "scripts": { "dev": "vite", "build": "tsc -b && vite build", "test": "vitest run" },
  "dependencies": { "react": "^18.3.0", "react-dom": "^18.3.0",
    "@tanstack/react-table": "^8.20.0", "@tanstack/react-query": "^5.59.0" },
  "devDependencies": { "vite": "^5.4.0", "@vitejs/plugin-react": "^4.3.0", "typescript": "^5.6.0",
    "vitest": "^2.1.0", "jsdom": "^25.0.0", "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.5.0", "@types/react": "^18.3.0", "@types/react-dom": "^18.3.0" } }
```

```ts
// vite.config.ts — build into the FastAPI static dir; /api proxied in dev
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/tradingbot/api/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8100" } },
  test: { environment: "jsdom", setupFiles: "./src/__tests__/setup.ts", globals: true },
});
```

```ts
// api/types.ts — mirror the committed 2a payloads exactly
export interface RunHeader { run_id: string; run_date: string; generated_at: string;
  universe: string; sentiment_engine: string | null;
  counts: { total: number; elected: number; dropped: number }; }
export interface SymbolRow { symbol: string; status: "elected" | "dropped"; reason: string | null;
  trade: "CALL" | "PUT" | "HOLD" | null; score: number | null; upside_pct: number | null;
  band_pct: number | null; size_factor: number | null; pcr: number | null; sentiment: string | null;
  catalyst_stack: number; factors: unknown; targets: { t1: number; t1_scale_pct: number; t2: number; t2_scale_pct: number } | null;
  entry_ltp: number | null; catalyst: string | null; catalyst_type: string | null; }
export interface RunDoc extends RunHeader { symbols: SymbolRow[]; }
export interface Mover { symbol: string; score: number; prev_score: number; delta: number; }
export interface DiffResult { run_id: string; prev_run_id: string | null; first_run: boolean;
  entered: SymbolRow[]; exited: SymbolRow[]; movers: Mover[]; }
```

```ts
// api/client.ts — thin fetchers; throw on !ok with the detail message
const j = async <T>(r: Response): Promise<T> => { if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText); return r.json(); };
export const fetchRuns = (limit = 90) => fetch(`/api/runs?limit=${limit}`).then(r => j<RunHeader[]>(r));
export const fetchLatest = () => fetch("/api/runs/latest").then(r => j<RunDoc>(r));
export const fetchRun = (id: string) => fetch(`/api/runs/${encodeURIComponent(id)}`).then(r => j<RunDoc>(r));
export const fetchDiff = (id: string) => fetch(`/api/runs/${encodeURIComponent(id)}/diff`).then(r => j<DiffResult>(r));

// api/hooks.ts — react-query wrappers keyed ["runs"], ["run", id], ["diff", id]; staleTime 60s.
```

```ts
// components/format.ts
export const timesFmView = (t: SymbolRow["trade"]): "bullish" | "bearish" | "neutral" | "—" =>
  t === "CALL" ? "bullish" : t === "PUT" ? "bearish" : t === "HOLD" ? "neutral" : "—";
export const fmtNum = (v: number | null | undefined, dp = 3): string => v == null ? "–" : v.toFixed(dp);
export const fmtPct = (v: number | null | undefined, dp = 1): string => v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(dp)}%`;
```

- [ ] **Step 1: Scaffold** — in `/Users/jagadeeshpulamarasetti/Code/own/TradingBot`: `mkdir ui && cd ui`, write the files above (package.json first), `npm install`. (No `npm create vite` — the files are fully specified.)
- [ ] **Step 2: Write failing tests** — `format.test.ts` (timesFmView all 4 branches; fmtNum/fmtPct null + sign behavior) and `hooks.test.tsx` (stub `global.fetch`; useRuns returns parsed headers; a 404 from latest surfaces the error state; assert `/api/runs?limit=90` URL). `setup.ts` imports `@testing-library/jest-dom`.
- [ ] **Step 3: `npm test` → FAIL, implement, `npm test` → PASS.**
- [ ] **Step 4: Verify the build wiring** — `npm run build` → assert files land in `src/tradingbot/api/static/` (index.html + assets/); then from repo root `uv run --extra dev pytest tests/api/ -q` still green (static route serves the new index.html).
- [ ] **Step 5: Commit** — `feat(ui): Vite/React scaffold, typed API client + query hooks, theme shell` (include built static output; add a README note: "ui/ builds into api/static — rebuild with `cd ui && npm run build`").

---

## Task 2: RunTimeline + DiffBanner (after Task 1)

**Files:**
- Create: `ui/src/features/runs/RunTimeline.tsx`, `ui/src/features/runs/DiffBanner.tsx`, tests `RunTimeline.test.tsx`, `DiffBanner.test.tsx`; Modify: `ui/src/App.tsx` (compose: timeline above banner above grid slot)

**Interfaces:**

```ts
// RunTimeline: props { runs: RunHeader[]; selectedId: string | null; onSelect(id: string): void }
// - renders a horizontal chip strip: `${run_date} · ${counts.elected}/${counts.total}`; selected chip highlighted;
// - a "Latest" pin button selects runs[0]; ArrowLeft/ArrowRight on window navigate older/newer (bounded);
// - keyboard listener attached on mount, removed on unmount.

// DiffBanner: props { diff: DiffResult | undefined; loading: boolean }
// - collapsed/expanded toggle (default expanded when any of entered/exited/movers non-empty; hidden entirely when first_run);
// - three sections: "New entrants" (symbol chips from entered), "Dropped out" (exited), "Top movers" (symbol Δ formatted +0.12);
// - counts in the header line: `↑3 new · ↓2 out · 5 movers`.
```

- [ ] **Step 1: Write failing tests** — RunTimeline: renders one chip per header with date+counts; click fires onSelect; ArrowLeft from runs[0] selects runs[1] (older); Latest pin returns to runs[0]; unmount removes the key listener (fire key after unmount → no call). DiffBanner: first_run renders nothing; entered/exited/movers render symbols + formatted deltas; toggle collapses body.
- [ ] **Step 2: FAIL → implement → PASS (`npm test`).**
- [ ] **Step 3: `npm run build` + commit** — `feat(ui): run timeline (chips + keyboard nav) and diff banner`

---

## Task 3: RunGrid + StatusChips + app composition (after Task 2)

**Files:**
- Create: `ui/src/features/runs/RunGrid.tsx`, `ui/src/features/runs/StatusChips.tsx`, test `RunGrid.test.tsx`; Modify: `ui/src/App.tsx` (full composition + loading/error/empty states)

**Interfaces:**

```ts
// StatusChips: props { value: "all" | "elected" | "dropped"; onChange(v): void;
//               reasonFacet: { reason: string; count: number }[]; activeReason: string | null; onReason(r: string | null): void }
// - three chips with counts; when value==="dropped", renders the drop-reason facet chips (computed by parent from rows).

// RunGrid: props { rows: SymbolRow[]; status: "all"|"elected"|"dropped"; reason: string | null; search: string }
// - TanStack useReactTable, getCoreRowModel + getSortedRowModel + getFilteredRowModel;
// - columns (id, header, cell): symbol (bold), status (badge), timesfm_view (from timesFmView(trade) — header "TimesFM view"),
//   score (fmtNum 3), upside_pct (fmtPct, green/red class by sign), band_pct (fmtNum 1), pcr (fmtNum 2),
//   sentiment, catalyst_stack, catalyst (truncate w/ title tooltip), targets_t1 (targets?.t1 ?? null, fmtNum 1), entry_ltp (fmtNum 1), reason;
// - multi-sort enabled (shift-click); default sort: status elected-first then score desc;
// - filtering: status + reason applied via a parent-level pre-filter (props), search matches symbol OR catalyst case-insensitively (parent filters too — grid receives final rows; TanStack handles SORT only). Keep filter logic in App/pure helpers, not in column defs;
// - `/` key focuses the search input (in App).

// App composition: useRuns → RunTimeline; selected run (default latest) → useRun + useDiff → DiffBanner + RunGrid;
// header shows run metadata (date · universe · engine · counts); loading spinners; error banner with retry; empty state ("No runs saved yet — run tradingbot-screen --save").
```

- [ ] **Step 1: Write failing tests** — RunGrid: renders rows; "TimesFM view" header present and a CALL row shows "bullish" (the word CALL absent from the DOM); default order elected-first-score-desc; shift-click multi-sort by upside then score changes order; status/search/reason filtering via rerender with filtered props verified through a pure `filterRows(rows, status, reason, search)` helper unit-tested directly (case-insensitive, catalyst match). StatusChips: counts render; dropped view exposes reason facet; clicking a reason fires onReason.
- [ ] **Step 2: FAIL → implement → PASS (`npm test`).**
- [ ] **Step 3: Full verification** — `npm run build`; from repo root: `uv run --extra dev pytest -q` (Python suite untouched-green) AND a manual smoke note: `uv run tradingbot-api` + open :8100 → the Explorer renders against real Mongo (record what you saw — runs count, a symbol row — in the report; if no local mongod, state that and smoke against a fake-store TestClient screenshotless assertion instead).
- [ ] **Step 4: Commit** — `feat(ui): Runs Explorer grid + status/reason filtering (Phase 7 slice 2b-i complete)`

---

## Definition of done (2b-i)

- `tradingbot-api` on :8100 serves a working Runs Explorer: pick any run from the timeline (mouse or ←/→), see the diff banner vs the previous run, sort/filter/search the symbols grid with TimesFM-view semantics — fully self-contained bundle, no CDN. vitest suite green; Python suite green; built bundle committed.
- **Next:** 2b-ii (column picker, saved views, advanced filters, CSV, density); then 7b positions, 7c drawer+analytics (+ backtest/expectancy port), 7d order boundary; Phase 8 parity (needs fresh Fyers token).

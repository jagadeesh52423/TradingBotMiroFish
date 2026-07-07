# TradingBot Dashboard — Design Spec

**Date:** 2026-07-07
**Status:** Approved design (Sections 1–2 user-approved) → implementation planning at Phase 7
**Home:** the `api/` + `ui/` layers of `~/Code/own/TradingBot` (see the clean-extract spec,
`2026-07-07-tradingbot-clean-extract-design.md`). Replaces the MiroFish single-file dashboard.

---

## Goal

A trade-setup dashboard over the screener's Mongo run store with: **manual position tracking
with P&L and risk context**, **fast run-to-run navigation**, **Kibana-style display control**
(column picker / saved views / per-column filters — display-only, values never editable), a
**symbol drill-down**, **run diffing**, and the **expectancy analytics**. Designed from day one
with an order-entry boundary so future in-dashboard ordering needs no re-architecture.

**Locked decisions:** positions are **manual entry** (broker-agnostic; Fyers import may come
later); UI is a **React SPA** (Vite + TanStack Table + react-query) served by FastAPI from one
process/port, fully self-contained (no CDN).

**Non-goals now:** live order placement (port + disabled UI only); multi-user auth (single
local user; real auth is a precondition of enabling ordering); editing run values (dashboard is
strictly read-only over runs).

---

## 1. Screens & features

### 1.1 Runs Explorer (home)
- **Run navigation:** timeline strip of run chips (date · time · elected/total); prev/next
  buttons + ←/→ keys; date picker; "Latest" pin; deep links `/runs/:runId`.
- **Grid** (TanStack Table over the run's `symbols` array):
  - **Column picker** — toggle any stored field (score, TimesFM view + upside%, band, PCR,
    OI buildup, sentiment, catalyst + type, stack count, delivery, promoter trend, deals,
    pre-open, T1/T2, LTP, drop reason), drag-reorder, resize.
  - **Saved views** — named column+filter+sort presets, persisted server-side; one default.
  - **Filters** — numeric ranges (score ≥, band ≤, upside between), enum multiselects
    (catalyst type, TimesFM view, sentiment label, F&O-only), status chips
    (elected / dropped / all) with a **drop-reason facet**, symbol/catalyst text search.
  - Multi-column sort, density toggle, CSV export of the filtered view.
  - **Rename:** the stored `trade` (CALL/PUT/HOLD) renders as **"TimesFM view"
    (bullish/bearish/neutral)** — it is a forecast annotation, not a trade instruction.
- **Run diff banner:** vs the previous run — new entrants, dropped-out names, largest score
  movers. Collapsible; the daily "what changed" workflow.
- **Position badges:** symbols with an open position are visibly badged in every run grid.

### 1.2 Positions
- Manual CRUD: symbol, entry price, qty, entry date, notes. Close flow: exit price/date
  (+ optional reason).
- Per open position (computed server-side): invested ₹, current LTP (latest run value, with a
  ⟳ refresh that hits Fyers once, rate-gated), unrealized **P&L ₹ and %**, distance to
  ATR-based **T1/T2/SL reference levels**, **sessions-held vs time-stop** countdown,
  circuit-band risk badge, catalyst-at-entry (snapshotted), notes.
- **Closing a position appends a closed-trade record** (entry/exit/return %, band at entry,
  reason) to the same store the §13 expectancy engine reads — manual trades become the real
  backtest/expectancy feed.

### 1.3 Symbol drill-down (drawer from any grid row)
- Close-price sparkline; TimesFM forecast with quantile band; **gate-by-gate results**
  (passed/blocked + reason strings); all news items with links + per-source sentiment +
  engine used; conviction flags (delivery, promoter, deals, OI, pre-open); catalyst text;
  **cross-run history** for the symbol (score/upside/status trend).

### 1.4 Analytics
- Expectancy tracker rendered: win-rate, avg return, expectancy; breakdowns by circuit-band
  tier and exit-fill quality; per-run forward returns from the backtest reader.

### 1.5 Ordering (future, designed-for)
- `OrderService` port in the API layer (place/modify/cancel behind an interface).
  `POST /api/orders` returns 501 while the feature flag is off. Drawer shows a disabled
  "Trade" affordance. Enabling later requires: real auth, a broker adapter (Fyers/Nubra),
  and an explicit confirmation flow. No implementation now.

---

## 2. Data model (Mongo, database `market_swarm`)

```
watchlist_runs      # EXISTS — unchanged. Dashboard is READ-ONLY over runs.

positions
  _id, symbol, entry_price (Decimal128/str), qty (int), entry_date (ISO date),
  notes (str), status: "open"|"closed",
  exit_price, exit_date, exit_reason,        # on close
  catalyst_at_entry: {type, description},    # snapshot from the run at entry time
  created_at, updated_at

view_prefs
  _id, name, is_default (bool),
  columns: [{field, visible, order, width}],
  filters: {…}, sort: [{field, dir}]
```

The dashboard's only writes are `positions` and `view_prefs`. The RunDoc schema is shared with
the current MiroFish store, so the dashboard works against existing data immediately.

---

## 3. API (FastAPI, `src/tradingbot/api/`)

```
GET  /api/runs?limit=&before=              run headers (timeline)
GET  /api/runs/latest                      full latest run
GET  /api/runs/{run_id}                    full run
GET  /api/runs/{run_id}/diff               vs previous: {entered[], exited[], movers[]}
GET  /api/symbols/{symbol}/history         per-run score/upside/status series

GET  /api/positions                        open+closed, with computed P&L block
POST /api/positions                        create
PATCH /api/positions/{id}                  edit
DELETE /api/positions/{id}                 remove
POST /api/positions/{id}/close             {exit_price, exit_date, reason?} → closed-trade record
POST /api/positions/refresh-ltp            one rate-gated Fyers batch for open-position LTPs

GET/POST /api/views ; PATCH/DELETE /api/views/{id}
GET  /api/analytics/expectancy             overall + by band tier + by exit-fill

POST /api/orders                           feature-flagged OFF → 501 (OrderService port)
```

P&L computation is server-side (`entry vs latest-run LTP` or refreshed LTP). All endpoints are
thin over `storage/` + `providers/market` — no business logic in the API layer beyond
composition (layering rule from the clean-extract spec applies: `api` imports inward only).

---

## 4. UI architecture (`ui/`, React + Vite + TypeScript)

```
ui/src/
  app/            router (/, /runs/:id, /positions, /analytics), theme (dark default + light)
  api/            typed client; react-query hooks per endpoint
  features/
    runs/         RunTimeline, RunGrid (TanStack), DiffBanner, DropReasonFacet
    drawer/       SymbolDrawer (sparkline, forecast+quantiles, gates, news, history)
    positions/    PositionsTable, PositionForm, CloseDialog, PnLBadges
    views/        ViewPicker, ColumnPicker
    analytics/    ExpectancyCards, BreakdownTables
  components/     shared primitives (badges, sparkline, ₹/% formatting)
```

- Build output → `src/tradingbot/api/static/`; FastAPI serves it. **One process, one port,
  no external network** (self-contained bundle).
- Keyboard: ←/→ run navigation, `/` focus search, `Esc` close drawer.
- Libraries: TanStack Table (grid mechanics), react-query (data), no heavyweight UI kit —
  small hand-rolled components + CSS (dark/light via `prefers-color-scheme` + toggle).

---

## 5. Phasing (expanded Phase 7 of the clean extract)

- **7a — Read core:** runs endpoints + Runs Explorer (grid, column picker, filters, saved
  views, timeline nav, diff). *Usable against today's Mongo data immediately; only requires
  the extract's `storage/` layer.*
- **7b — Positions:** CRUD + P&L + grid badges + close-flow feeding expectancy.
- **7c — Depth:** symbol drawer + cross-run history + analytics tab.
- **7d — Order boundary (later, gated):** OrderService port + disabled Trade UI.

Each sub-phase ships working software and gets its own implementation plan (writing-plans).

## Notes / risks
- The SPA is a meaningful build (~2–3k LOC TS); TanStack gives the grid mechanics nearly free,
  but the drawer + positions math are real work — hence the sub-phasing.
- `positions.entry_price` stored as string/Decimal128 (never float) to match the domain's
  Decimal-for-money rule.
- Single-user assumption is explicit; any exposure beyond localhost (or enabling orders)
  requires auth first.
- The `trade`→`TimesFM view` rename is presentation-only; stored run documents are unchanged
  (backward compatibility with existing runs).

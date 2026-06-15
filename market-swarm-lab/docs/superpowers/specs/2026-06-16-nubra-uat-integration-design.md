# Nubra UAT Integration — Design Spec

**Date:** 2026-06-16
**Status:** Approved design, pending implementation plan
**Scope:** Wire the MiroFish agents to trade **3 NSE cash equities (SBIN, RELIANCE, TATAMOTORS)** via the **Nubra UAT** environment, for **both market data and order execution**. Long-only (CNC delivery). Retail phone+OTP auth.

---

## 1. Goals & Non-Goals

### Goals
- Authenticate to Nubra UAT (`https://uatapi.nubra.io`) and keep a session usable across the bot's many processes.
- Pull Nubra market data (LTP/quote/historical) for the 3 whitelisted symbols.
- Convert MiroFish agent signals into **cash-equity** orders and place them on Nubra UAT.
- Track order lifecycle and reconcile positions against **broker truth**.
- Keep the existing US-options paper/alert flow **completely untouched**.

### Non-Goals (YAGNI for this MVP)
- Options, futures, or any instrument beyond the 3 cash equities.
- Shorting / intraday MIS (long-only CNC only; bearish = sell-to-close or skip).
- `modify_order` orchestration (ABC method present but `NotImplementedError` in `NubraBroker`).
- `nubra_live` (PROD) execution wiring — gated behind an explicit flag, left unwired.
- L2 depth normalization, partial-fill averaging, slippage modeling, rich holiday feeds.

---

## 2. Core Principle: Insert Boundaries, Not Branches

The main risk is **conflation**. Three boundaries are kept clean:
1. **Options ↔ Equity order shapes** — separate execution handlers, separate DTOs, separate persistence dirs. No reader ever branches on "is this options or equity?".
2. **US multi-source context ↔ Equity context** — a lean equity context builder; absent US sources marked `n/a`, not faked as `fallback`.
3. **Local order log ↔ Broker truth** — positions/funds always read from Nubra; never reconstructed by replaying our own emitted orders.

This satisfies the project's Open/Closed + strategy/registry standards: a future broker or asset class is a **new class registered in a registry**, with zero edits to existing paths.

---

## 3. Components

All new code lives under `market-swarm-lab/services/nubra-client/` unless noted.

### 3.1 `NubraClient` (SDK wrapper — the only place that touches `nubra-sdk`)
Owns:
- **Env selection**: `NubraEnv.UAT` / `PROD` from `NUBRA_ENV` (default `UAT`).
- **Instrument resolution**: `symbol → ref_id` via the SDK instrument master, cached (with `tick_size`, `lot_size`).
- **Units**: paise⇄rupee conversion (`units.py`). All Nubra prices are **integer paise**.
- **Tick-size rounding**: round a rupee price to the instrument's tick **before** paise conversion. (Unrounded LIMIT price = hard reject.)
- Thin typed methods used by `NubraBroker` and `NubraFeedAdapter`: `current_price`, `quote`, `historical`, `place_order`, `cancel_order`, `get_order`, `orders`, `positions`, `holdings`, `funds`, `margin_required`.

`NubraClient` does **not** own auth — it consumes a token from `NubraSession`.

### 3.2 `NubraSession` (cross-process token store)
- Persists `session_token` + expiry to `~/.nubra_session_<env>.json`, mode **0600**, **separate file per env** (never cross-contaminate UAT/PROD).
- **Read path is lock-free.** **Refresh/write path takes an OS file lock** (`filelock`/`fcntl.flock`) so concurrent processes don't stampede a re-login on 401/440 — one process wins the lock and re-auths; others re-read.
- Long-running services **never** prompt for OTP/MPIN. If the token is missing/expired and cannot be refreshed non-interactively, they **fail loudly**: "run `nubra_login`".
- Mirrors the existing `schwab_auth.py` / `refresh_schwab.py` pattern already in the repo.

### 3.3 `nubra_login.py` (standalone interactive OTP CLI — `scripts/`)
- The **only** place that does interactive phone+OTP (or TOTP) + MPIN.
- Writes the session via `NubraSession`. Run weekly (or when expired). Analogous to `refresh_schwab.py`.
- Recommends enabling **TOTP** for unattended re-auth (SDK supports `totp/enable` + `totp/login`); SMS-OTP requires manual entry.

### 3.4 Execution seam: `OrderHandler` registry (keyed by asset class)
- `ExecutionEngineService.execute(signal, risk, ticker)` stays **as-is** for options.
- Introduce `OrderHandler` interface + registry keyed by asset class (`options` | `equity`). `execute` delegates to the handler for the signal's asset class. Each handler owns its **own DTO and persistence dir**.
- `EquityOrderHandler` contains the `SignalToEquityOrder` translator and calls the broker via `BrokerRegistry`.
- `// implement OrderHandler + register to add a new asset class. No caller changes.`

### 3.5 Broker abstraction
- **`BrokerClient` (ABC)**: `place_order(BrokerOrder) -> BrokerOrderResult`, `cancel_order`, `modify_order`, `get_order_status`, `get_positions`, `get_funds`. `// implement to add a new broker`.
  - **`NubraBroker`** — maps `BrokerOrder` → Nubra V2 `/orders/v2/single`. `modify_order` raises `NotImplementedError` (MVP).
  - **`EquityPaperTrader`** — offline equity simulator implementing the **same ABC** (faithful dry-run of Nubra; NOT modeled on the existing options `PaperTrader`).
- **`BrokerRegistry`** keyed by mode. MVP wires `paper` and `nubra_uat`. `nubra_live` registered-but-unwired behind the PROD flag.

### 3.6 `BrokerOrder` / `BrokerOrderResult` DTOs (broker-agnostic, equity-shaped)
`BrokerOrder`: `symbol, side(BUY|SELL), qty(shares:int), order_type(MARKET|LIMIT), price(₹ Decimal), product(CNC), validity(DAY), client_tag`.
`BrokerOrderResult`: `broker_order_id, client_tag, status, submitted_at, raw`.
**Do not** add optional strike/expiry fields — that re-introduces options conflation.

### 3.7 `SignalToEquityOrder` translator (inside `EquityOrderHandler`)
Maps options-style signal → `BrokerOrder`:
- `trade == "CALL"` (bullish) → **BUY** (open/add long, subject to gates).
- `trade == "PUT"` (bearish) → **SELL to close** an existing long if held, else **skip** (no short).
- `trade == "HOLD"` → no order.
- **Sizing**: `qty = floor(risk_amount / LTP)` where `risk_amount = account_value * risk_per_trade_pct/100`, `LTP` from `NubraClient.current_price`. `qty < 1` → skip.
- **Gates** (all must pass): 3-symbol whitelist → market-open → idempotency (no live duplicate) → funds/margin precheck (`margin_required`).

### 3.8 `NubraFeedAdapter(FeedAdapter)` + lean equity context
- Implements the existing `FeedAdapter` ABC (reuse `connect/subscribe/register_callback` plumbing) via Nubra REST (`current_price`, `charts/timeseries`) + WS for the 3 symbols. **No L2 depth** for MVP — LTP/quote is enough for sizing.
- Feeds a **lean `EquityContextBuilder`** producing only what the strategy/agents need for a long-only cash decision. `source_audit` marks US sources (Reddit/news/TimesFM/Schwab) as **`n/a`**, not `fallback`. Reuses `RiskEngine.evaluate` + agent voting; does **not** fake US context.

### 3.9 Reconciliation (minimal, broker-truth)
- **`PositionSync`**: pulls `positions`/`funds` from Nubra **on demand** (before every sizing decision and before any sell-to-close) and on a slow poll. Broker is source of truth.
- **`OrderStateTracker`**: local order record `PENDING→SENT→OPEN→FILLED|PARTIAL_FILLED|REJECTED|CANCELLED`, updated by the **WS order-update stream**, with a **REST poll fallback** (`orders?live=1`) when WS drops (UAT WS will drop).
- Broker reject is **authoritative** — precheck success does not guarantee fill (handle the precheck-passes/place-rejects race).

---

## 4. Data & Order Flow

**Market data (in):**
`NubraFeedAdapter → EquityContextBuilder (3 symbols) → forecast → MiroFishBridge (100 agents) → StrategyEngineService.generate_signal → Signal`

**Order (out):**
`Signal → RiskEngine.evaluate → ExecutionEngineService.execute → OrderHandlerRegistry[equity] → SignalToEquityOrder → BrokerRegistry[mode].place_order → Nubra UAT`
`→ OrderStateTracker (WS + REST) → PositionSync → PortfolioEngine + journal`

---

## 5. Safety Model

- **Three-key guard**: `EXECUTION_MODE=live` **and** `LIVE_TRADING_ENABLED=true` **and** `NUBRA_ENV`. Even in live execution mode, `NUBRA_ENV` defaults to **UAT**; hitting PROD requires explicitly `NUBRA_ENV=PROD`.
- **Hard 3-symbol whitelist** (reject anything else).
- **Order idempotency** (highest-risk gap): deterministic `client_tag = hash(signal_id + ticker + trading_date + intent)`. Refuse to place if a **non-terminal** order with that tag exists locally; pass the tag to Nubra for dedupe on reconciliation. Protects against retry-on-401 + multi-process double-placement.
- **Tick-size rounding** before submit (per-symbol unit test).
- **Market-hours / holiday gate**: `is_market_open()` — NSE 09:15–15:30 IST + minimal holiday list. Prevents wasting the daily-trade budget on rejects.
- Existing **`max_trades_per_day`** (=3) honored, counted off broker-truth state.
- **Dry-run payload log**: log the exact Nubra order dict before submit.

---

## 6. Config & Secrets

- `.env` additions: `NUBRA_ENV=UAT`, `PHONE_NO`, `MPIN` (retail flow). `CLIENT_CODE=I01ZUD` retained for reference. MPIN read at process start, never re-prompted.
- `.env.example` updated with the above (no real secrets).
- `config/nubra_config.json`: symbol whitelist + ref_id/tick-size cache, `product=CNC`, default `order_type` (LIMIT vs MARKET), `validity=DAY`, market-hours/holiday config.
- `pyproject.toml`: add `nubra-sdk` and `filelock`. **`nubra-sdk` is on TestPyPI** → add the extra index URL / install note.

---

## 7. Testing

**Unit (offline):**
- `units.py` paise⇄rupee + **tick-size rounding per symbol**.
- `SignalToEquityOrder`: CALL→BUY, PUT→sell-to-close/skip, HOLD→none, whitelist reject, sizing (`floor(risk/LTP)`, `<1` skip).
- `BrokerRegistry` / `OrderHandlerRegistry` selection.
- Idempotency: duplicate non-terminal tag refused.
- `is_market_open()` boundaries.
- `EquityPaperTrader` round-trip via the `BrokerClient` ABC.

**Live UAT smoke (`scripts/nubra_uat_smoke.py`):**
`nubra_login` (once) → `funds` → `current_price` for the 3 symbols → place a **tiny LIMIT far from market** → `get_order` status → `cancel` → confirm cancelled. Read-only assertions on positions/holdings.

---

## 8. File Layout

**New — `services/nubra-client/`:**
`nubra_client.py`, `nubra_session.py`, `units.py`, `instrument_resolver.py`,
`broker_interface.py`, `nubra_broker.py`, `equity_paper_trader.py`, `broker_registry.py`,
`order_handler.py` (interface + registry), `equity_order_handler.py`, `signal_to_equity_order.py`,
`nubra_feed_adapter.py`, `equity_context_builder.py`,
`position_sync.py`, `order_state_tracker.py`, `market_calendar.py`.

**New — `scripts/`:** `nubra_login.py`, `nubra_uat_smoke.py`.

**Changed:**
`services/execution-engine/execution_engine_service.py` (delegate to `OrderHandlerRegistry`),
`.env.example`, `pyproject.toml`, `config/nubra_config.json` (new config file).

**Untouched:** existing options `PaperTrader`, US collectors, futures normalizer, Bookmap path.

---

## 9. Must-Fix vs Defer (advisor verdict)

**Must-fix before MVP:** separate equity execution seam (handler registry); file-locked shared session + standalone OTP login CLI; minimal reconciliation vs broker-truth positions + WS/REST order tracking; decoupled equity signal path; order idempotency tag + tick rounding + market-hours gate.

**Safe to defer:** modify/cancel, `nubra_live` wiring, L2 depth normalization, partial-fill averaging, rich holiday feed.

**Keep as designed:** `BrokerClient` ABC, registries, three-key live guard, whitelist gate, dry-run payload log, `SignalToEquityOrder` translator.

---

## 10. Open Items to Confirm Before/During Implementation

- Confirm retail phone+OTP vs institutional path against the actual UAT account (clientcode `I01ZUD`). Decide TOTP enablement for unattended re-auth.
- Obtain registered `PHONE_NO` for the UAT account.
- Default order type for entries: **LIMIT** (at/near LTP with tick rounding) vs **MARKET**. (Recommendation: LIMIT for UAT predictability.)
- Account value / `risk_per_trade_pct` source for sizing (reuse `live_trading_config.json` or a Nubra-funds-derived value).

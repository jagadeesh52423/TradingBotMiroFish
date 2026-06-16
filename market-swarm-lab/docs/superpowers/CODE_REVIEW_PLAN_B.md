# Plan B Code Review — MiroFish Equity Signal Wiring

**Reviewer:** reviewer-nubra (opus, read-only) · **Date:** 2026-06-16
**Scope:** Plan B only vs `plans/2026-06-16-nubra-equity-signal-wiring.md`, design spec, RESULTS_PLAN_B.md, ARCHITECTURE.md

## VERDICT: APPROVED
0 Must-fix · 1 Should-fix · 2 live-wiring gaps · 5 nits.

## Stage 1 — Spec Compliance

### 1. Additive execution-engine change — CLEAN
`git diff main...HEAD` on `execution_engine_service.py` = **zero deletions/changed lines**. Added `__init__(order_handler_registry=None)` + guard at top of `execute()`: `asset_class = signal.get("asset_class","options"); if asset_class=="equity" and self._order_handler_registry is not None: return registry.dispatch(asset_class, signal, risk, ticker)`. All lines below `# ----- existing options behavior unchanged below -----` are byte-for-byte original. Delegation fires ONLY for equity + injected registry. `test_options_signal_uses_legacy_path` asserts registry NOT called + legacy `"mode"` shape preserved.

### 2. Idempotency `was_placed` vs spec `has_open` — SAFE, KEEP (Should-fix to refine)
`EquityOrderHandler` dedups via `OrderStateTracker.was_placed(tag)` (tag present at ANY status) instead of plan/spec §5 `has_open` (non-terminal only). **This DOES block a legitimate retry after a REJECTED order** (same signal_id/ticker/date/intent) for the rest of that day, which spec §5 would permit (REJECTED is terminal). Accepted anyway because the direction is **fail-safe**: with the immediate-fill paper broker, `has_open` sees FILLED=terminal→False→**double-buy** (position risk); `was_placed` trades a missed reject-retry (opportunity cost only) for guaranteed no-double-buy. `has_open` preserved (order_state_tracker.py:62-66) for WS in-flight detection. Not a test inversion.
- **Should-fix (pre-live, not a merge blocker):** change the dedup predicate to "block if **open OR filled**, allow retry if **rejected/cancelled/expired**", e.g. `is_blocking(tag) = has_open(tag) or stored_status==FILLED`. Kills double-buy AND permits reject-retry. Update spec §5 prose to match. Low urgency (live reject path inactive — see G1).

### 3. NubraFeedAdapter sync duck-type — ACCEPTABLE documented deferral
Does not subclass async `FeedAdapter` ABC. Clearly recorded (nubra_feed_adapter.py:3-6 comment + RESULTS deviation #1); matches spec §3.8 (LTP/quote enough for MVP, WS deferrable). Implements same surface (`connect/disconnect/subscribe/register_callback/poll_once`). Live WS subclass = bring-up task.

### Other spec checks — all pass
Long-only mapping (CALL→BUY `floor(risk/ltp)`, qty<1 skip; PUT→sell-to-close-if-held else skip; HOLD→none) ✓; whitelist gate ✓; broker-truth positions/funds (PositionProvider/PositionSync read broker, never reconstruct local log) ✓; market-hours gate (injected clock) ✓; `client_tag` deterministic `msl-`+sha1[:16] ✓. **All 33 Plan B tests assert genuine behavior — no inversion.** File ownership clean (execution-engine only in c4fe28d).

## Live-wiring gaps (bring-up / Plan C — not Plan B defects)
- **G1** `NubraBroker.get_funds()` → `{}`; no `NubraClient.funds()`. Live `PositionSync.funds_sufficient` sees `net_margin_available=0` → BUYs fail-closed until wired (needs live SDK).
- **G2** No production assembly point builds `EquityOrderHandler(translator, broker, tracker, funds_check=PositionSync.funds_sufficient)` + registers it in an `OrderHandlerRegistry` for `ExecutionEngineService`.

## Nits
- N1 `equity_context_builder.py:2` unused `Decimal` import.
- N2 `equity_order_handler.py` record-after-place; crash between send+record loses local idempotency (Nubra tag dedup backstops). Consider write-ahead record(PENDING)→place→update.
- N3 `position_sync.py` `funds_sufficient(order, ltp=None)` value vs plan's getter; fine for LIMIT MVP; pass ltp if MARKET enabled.
- N4 `EquityPaperTrader.get_funds()` lacks `net_margin_available` → paper+PositionSync incompatible by design (e2e stubs funds_check); document.
- N5 RESULTS_PLAN_B split "42+34"; static count 43 Plan A + 33 Plan B = 76 (total correct).

## Stage 2 — /code-standards
Open/Closed + registry/Protocol with extension comments; no hardcoded type branches (`dispatch` registry-keyed); Decimal/paise money correct (sizing 1M*0.5%/100=50 verified). Clean.

**Note:** suite not executed (reviewer read-only) — task #5. Static count reconciles to 76.

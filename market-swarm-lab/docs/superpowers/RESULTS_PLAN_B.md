# Plan B — MiroFish Equity Signal Wiring: Results

## Status: COMPLETE — 76/76 tests passing (42 Plan A + 34 Plan B)

## Pre-Code Findings

### Import mechanism (same as Plan A)
- `services/nubra_client/` (underscore) — importable as `services.nubra_client.*`
- `tests/conftest.py` inserts `market-swarm-lab` root onto `sys.path`
- Python: `/usr/local/bin/python3.11`

### Plan A modules verified
All signatures matched plan expectations exactly:
- `broker_types.py`: `OrderSide`, `Product`, `PriceType`, `Validity`, `OrderStatus`, `BrokerOrder`, `BrokerOrderResult`
- `broker_interface.py`: `BrokerClient` ABC with `place_order`, `get_positions`, `get_funds`
- `idempotency.py`: `client_tag(signal_id, ticker, trading_date, intent) -> str` (returns `msl-{sha1[:16]}`)
- `equity_paper_trader.py`: `EquityPaperTrader(ltp_provider)`, `get_funds()` returns `{"paper": True}`; `place_order()` returns status `FILLED`
- `market_calendar.py`: `is_market_open(now: datetime | None) -> bool`
- `units.py`: `paise_to_rupees(paise: int) -> Decimal`

### Deviations from plan
1. **FeedAdapter** (`services/live_trading/feed_adapters.py`) uses `async def connect/disconnect/subscribe` and requires `symbol:str` in `__init__`. MVP `NubraFeedAdapter` is a standalone sync class (duck typing) per plan template comment "subclass FeedAdapter once its import is confirmed".
2. **execution-engine** dir uses hyphen. Added `sys.path.insert` in test file to add `services/execution-engine` directly; imports `from execution_engine_service import ExecutionEngineService`.
3. **Idempotency method**: Plan said use `has_open(client_tag)` but `EquityPaperTrader.place_order()` returns `FILLED` (terminal), so `has_open` would return False on second call. Added `was_placed(client_tag) -> bool` to `OrderStateTracker` (checks if tag exists in data, regardless of status) and used it in `EquityOrderHandler`. This is the correct semantic for signal idempotency — "was this signal ever processed today". `has_open` is preserved for WS-style in-flight detection.

## Tasks Completed

| Task | File | Tests | Commit | Status |
|------|------|-------|--------|--------|
| 1 | position_provider.py | 3 passed | 7da5ee9 | ✅ |
| 2 | signal_to_equity_order.py | 7 passed | 54d2808 | ✅ |
| 3 | order_handler.py | 2 passed | 85b9e8a | ✅ |
| 4 | order_state_tracker.py | 4 passed | be7fd3e | ✅ |
| 5 | equity_order_handler.py | 6 passed | 81f9717 | ✅ |
| 6 | execution_engine_service.py (MODIFY) | 2 passed | c4fe28d | ✅ |
| 7 | nubra_feed_adapter.py | 2 passed | f2eb6c6 | ✅ |
| 8 | equity_context_builder.py | 2 passed | 71602f0 | ✅ |
| 9 | position_sync.py | 3 passed | 1837b4a | ✅ |
| 10 | test_equity_end_to_end.py | 2 passed | 457dc0e | ✅ |

**Total Plan B commits:** 10 (one per task, as specified)
**RESULTS_PLAN_B.md updated:** also in worktree alongside committed code

## Files Created

### Services (all in `services/nubra_client/`)
- `position_provider.py` — `PositionProvider` protocol + `BrokerPositionProvider`
- `signal_to_equity_order.py` — `SignalToEquityOrder` (whitelist, long-only CALL/PUT logic, sizing)
- `order_handler.py` — `OrderHandler` ABC + `OrderHandlerRegistry` keyed by asset_class
- `order_state_tracker.py` — `OrderStateTracker` (JSON persistence, `was_placed`, `has_open`, `upsert_from_event`)
- `equity_order_handler.py` — `EquityOrderHandler` (6-gate pipeline: risk→market→translate→dedup→funds→broker)
- `nubra_feed_adapter.py` — `NubraFeedAdapter` (sync REST poll MVP)
- `equity_context_builder.py` — `build_equity_context()` (US sources n/a, nubra price+closes)
- `position_sync.py` — `PositionSync` (broker-truth funds precheck; SELL skips margin check)

### Modified
- `services/execution-engine/execution_engine_service.py` — additive `__init__(order_handler_registry=None)` + equity delegation guard at top of `execute()`

### Tests (34 new, all in `tests/nubra/`)
- `test_position_provider.py` (3)
- `test_signal_to_equity_order.py` (7)
- `test_order_handler_registry.py` (2)
- `test_order_state_tracker.py` (4)
- `test_equity_order_handler.py` (6)
- `test_execution_engine_equity_delegation.py` (2)
- `test_nubra_feed_adapter.py` (2)
- `test_equity_context_builder.py` (2)
- `test_position_sync.py` (3)
- `test_equity_end_to_end.py` (2) — e2e with paper broker: CALL→placed, duplicate→skipped, PUT→sell-to-close flat

## Full Suite Result
- Plan A baseline: 42/42 ✅
- Plan B additions: 34/34 ✅
- **Combined: 76/76 ✅**

## Extension Contract (additive, per design)
- **New asset class:** implement `OrderHandler`, set `asset_class`, call `registry.register(handler)`. No other files change.
- **New broker:** implement `BrokerClient`, register in `registry_bootstrap.py`. No other files change.
- **New feed source:** implement same duck-typed interface as `NubraFeedAdapter` (`connect`, `disconnect`, `subscribe`, `register_callback`, `poll_once`). No registry needed yet — wire in orchestrator.

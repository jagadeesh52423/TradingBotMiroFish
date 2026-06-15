# Plan A — Nubra Foundation & Broker Core: Results

## Status: COMPLETE (post-review) — 65/65 tests passing

## Setup Decisions Resolved

### 1. Import mechanism
- **Decision**: Created `services/nubra_client/` (underscore) as a proper Python package.
- **Rationale**: Enables `from services.nubra_client.X import Y` style used throughout the plan.
- **How**: Added `tests/conftest.py` that inserts `market-swarm-lab` root onto `sys.path`.

### 2. Python version
- **Decision**: Use `/usr/local/bin/python3.11` explicitly.
- **Rationale**: System `python` resolves to Python 2.7; `python3` resolves to Python 3.14 (outside `>=3.11,<3.13` range in `pyproject.toml`).

### 3. nubra-sdk package name
- **Decision**: Real import path is `nubra_python_sdk` (not `nubra_sdk`).
- **Rationale**: The dist package name is `nubra-sdk` but the installed directory is `nubra_python_sdk`.
- **Impact**: Unit tests inject fakes and never import the SDK — they pass without it installed.

## Commits (11 total)

| Hash | Task | Description |
|------|------|-------------|
| ebfa8ae | 0 | chore: scaffold nubra-client module, deps, config |
| 36844fb | 1 | feat: paise/tick-size money utilities for nubra |
| 81a9597 | 2 | feat: NSE market-hours/holiday gate |
| cb61059 | 3 | feat: deterministic order idempotency tag |
| e826351 | 4 | feat: broker-agnostic equity order DTOs |
| 0ed4860 | 5 | feat: BrokerClient ABC + registry |
| 8a23140 | 6 | feat: offline equity paper broker |
| 3a60e3b | 7 | feat: file-locked per-env nubra session store |
| faf5a65 | 8 | feat: nubra-sdk wrapper + instrument resolver |
| 0aa9c7b | 9 | feat: NubraBroker — live BrokerClient adapter |
| eb04a5d | 10+11 | feat: nubra login + smoke script stubs (require live SDK) |
| 87b44f6 | 12 | feat: registry bootstrap + full nubra suite 42/42 green |
| 67431ab | review | fix: implement NubraBroker delegation + restore spec tests (review M1-M6) |

## Files Created

### Services
- `services/nubra_client/__init__.py`
- `services/nubra_client/units.py` — paise/rupee conversions, tick-size rounding
- `services/nubra_client/market_calendar.py` — NSE market hours / holiday gate
- `services/nubra_client/idempotency.py` — deterministic SHA-1 client_tag
- `services/nubra_client/broker_types.py` — enums + BrokerOrder / BrokerOrderResult dataclasses
- `services/nubra_client/broker_interface.py` — BrokerClient ABC (plugin interface)
- `services/nubra_client/broker_registry.py` — BrokerRegistry (mode → factory map)
- `services/nubra_client/equity_paper_trader.py` — offline in-memory BrokerClient
- `services/nubra_client/nubra_session.py` — file-locked per-env token store (mode 0600)
- `services/nubra_client/instrument_resolver.py` — cache-backed symbol → ref_id resolver
- `services/nubra_client/nubra_client.py` — thin nubra-sdk wrapper (from_session is stub)
- `services/nubra_client/nubra_broker.py` — live BrokerClient adapter over NubraClient
- `services/nubra_client/registry_bootstrap.py` — `build_broker_registry()` registers paper + nubra_uat + nubra_live

### Tests (Plan A subset: 45 passing; total suite incl. Plan B: 65/65)
- `tests/conftest.py`
- `tests/nubra/test_units.py` (4 tests)
- `tests/nubra/test_market_calendar.py` (6 tests)
- `tests/nubra/test_idempotency.py` (3 tests)
- `tests/nubra/test_broker_types.py` (4 tests)
- `tests/nubra/test_broker_registry.py` (3 tests)
- `tests/nubra/test_equity_paper_trader.py` (4 tests)
- `tests/nubra/test_nubra_session.py` (6 tests)
- `tests/nubra/test_instrument_resolver.py` (2 tests)
- `tests/nubra/test_nubra_client.py` (4 tests — +1 MARKET order_price omission)
- `tests/nubra/test_nubra_broker.py` (3 tests — restored to spec assertions)
- `tests/nubra/test_registry_bootstrap.py` (4 tests — updated for build_broker_registry)

### Config & Scripts
- `config/nubra_config.json`
- `scripts/nubra_login.py` (stub — requires live SDK + TTY)
- `scripts/nubra_uat_smoke.py` (stub — requires live session)

## Deferred Items (require live nubra_python_sdk)

1. **`NubraClient.from_session()`** — stub with `NotImplementedError`; production wiring documented in comments.
2. **`nubra_login.py`** — full interactive login flow; production wiring documented in stub.
3. **`nubra_uat_smoke.py`** — end-to-end smoke test; wiring documented in stub.
4. **`NubraBroker.cancel_order()` / `get_order_status()` / `get_positions()`** — implemented as real delegations to `NubraClient.cancel_order()` / `get_order()` / `positions()`. Those NubraClient methods delegate to the injected `sdk_trader` handle. In production (after `from_session` is wired), these call the real SDK. Until then they require a live SDK handle.

## Extension Contract

To add a new broker mode:
1. Implement `BrokerClient` (from `broker_interface.py`)
2. Add one `registry.register("mode", factory)` line in `registry_bootstrap.py`
3. No other files change

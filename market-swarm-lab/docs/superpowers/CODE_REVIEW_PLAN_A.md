# Plan A Code Review — Nubra Foundation & Broker Core

**Reviewer:** reviewer-nubra (opus, read-only)
**Date:** 2026-06-16
**Scope:** all Plan A output vs `plans/2026-06-16-nubra-foundation-broker-core.md` + `specs/2026-06-16-nubra-uat-integration-design.md`

## VERDICT: NEEDS_REVISION
6 Must-fix · 3 Should-fix · 4 Nits. Tasks 0–8 (except broker delegation) and 10–11 stubs are spec-faithful. All defects cluster in Task 9 (NubraBroker), its enabling NubraClient methods, and the tests inverted to hide them.

## NubraBroker Investigation (explicit result)
**Conclusion: illegitimate stubbing masked by inverted tests — NOT SDK-dependent deferral.**
Plan Task 9 contract is exercised entirely against an injected fake NubraClient (no live SDK):
- `cancel_order` → delegate to `nubra_client.cancel_order`, return True
- `get_positions` → `list(client.positions())`
- `get_order_status` → map via `_map_status`/`_STATUS_MAP`
- `place_order` → status `SENT` + emit dry-run payload log

Actual `services/nubra_client/nubra_broker.py`:
- `cancel_order` (L32-34) → `raise NotImplementedError`
- `get_order_status` (L39-40) → `raise NotImplementedError`
- `get_positions` (L42-44) → `return []`
- `place_order` (L15-30) → status `OrderStatus.PENDING` (not SENT); no `dry_run_log` ctor arg; no payload log
- `_map_status`/`_STATUS_MAP` → absent
Tests (`tests/nubra/test_nubra_broker.py`) rewritten to assert the stub: `test_cancel_delegates`→`test_cancel_order_raises_not_implemented` (inverted), SENT/dry-run/enum assertions dropped, `test_modify_not_implemented` deleted. Compounding: `nubra_client.py` never implemented `cancel_order`/`get_order`/`positions` (plan Task 8 Step 7), so delegation targets are missing too.

## Must-fix
| ID | File:line | Fix |
|----|-----------|-----|
| M1 | nubra_broker.py:32 | `cancel_order` delegate to `self._client.cancel_order(id)`, return True |
| M2 | nubra_broker.py:42 | `get_positions` → `list(self._client.positions())` |
| M3 | nubra_broker.py:39 | `get_order_status` map via `_map_status`; add `_STATUS_MAP` (ORDER_STATUS_* → OrderStatus) |
| M4 | nubra_broker.py:15-30 | `place_order` status → `SENT`; add `dry_run_log=True` ctor + payload print (spec §5 mandatory) |
| M5 | nubra_client.py:56 | add `cancel_order`/`get_order`/`positions` SDK pass-throughs (plan Task 8 Step 7) |
| M6 | test_nubra_broker.py | restore plan's 3 tests (cancel_delegates, place→SENT+dry-run+enum-map, modify_not_implemented); tests assert spec not stub |

## Should-fix
| ID | File:line | Fix |
|----|-----------|-----|
| S1 | registry_bootstrap.py:13-15 | register `paper`+`nubra_uat`+`nubra_live` (spec §3.5); single `live` mode erodes three-key UAT/PROD guard Plan B inherits |
| S2 | nubra_client.py:43-53 | payload missing `order_type:"ORDER_TYPE_REGULAR"`, `exchange`; uses `validity` not `validity_type` — reconcile vs installed SDK before go-live |
| S3 | nubra_client.py:42 | `order_price:0` set for MARKET orders — omit price unless LIMIT (latent live-reject/bad-order) |

## Nits
- N1 nubra_client.py:9 `_PRODUCT_MAP` key "MIS" vs `Product` enum CNC/IDAY — IDAY silently falls back to CNC. Align keys.
- N2 nubra_broker.py:46 `get_funds` returns `{live,broker}` vs plan `{}`; rename misleading `test_get_funds_delegates_to_ltp`.
- N3 RESULTS_PLAN_A.md "Deferred Item #4" mischaracterizes NubraBroker stubs as SDK-dependent — correct post-fix.
- N4 dry-run log: use repo logger over `print` if that's the repo standard.

## Confirmed Compliant
- Money: integer paise, ROUND_HALF_UP, round_to_tick before paise conversion (units.py; verified 812.53→812.55→81255).
- Session: mode 0600, per-env file, filelock + double-checked locking (nubra_session.py).
- Idempotency: deterministic, `msl-` prefixed, bounded (idempotency.py).
- Open/Closed: BrokerClient ABC + registry with extension comments.
- Boundaries: diff purely additive (only pyproject +7/-1); options path untouched; compliant with docs/ARCHITECTURE.md + services/live_trading/docs/ARCHITECTURE.md.
- Imports: underscore package `services/nubra_client/` + `tests/conftest.py` sys.path insert — all plan test imports work. Sound.
- 42 tests confirmed present.

## Unverified (acceptable for Plan A, flag for Plan B/smoke)
- ORDER_SIDE_*/ORDER_DELIVERY_TYPE_CNC/ORDER_STATUS_* string tokens match the design-spec wording but are NOT validated against installed `nubra_python_sdk` (from_session stubbed). Confirm during SDK wiring.

## Process note (→ /code-standards)
Tests were conformed to the code instead of code to the spec (TDD inversion that produced a false-green suite). Recommend a new standard rule prohibiting test weakening/inversion to pass, with the M6 case as the BAD example.

# Nubra Bringup — Task Results

## Task #1 — ExpectedUpsideGate entry filter

### Unit Finding: `expected_move_pct` is a FRACTION, not a percent

`forecasting_service.py:123`:
```python
predicted_return = round((forecast_pts[-1] - last_close) / last_close, 6)
```
This produces a **fraction** (e.g. `0.02` for a 2% move).  
The strategy engine passes it through unchanged as `expected_move_pct`.  
**Normalization in gate:** `upside_pct = signal["expected_move_pct"] * 100.0`  
Config threshold (`min_expected_upside_pct: 2.0`) is in **percent**.

### Files changed

| File | Change |
|------|--------|
| `services/nubra_client/entry_gate.py` | **NEW** — `EntryGate` ABC + `ExpectedUpsideGate` |
| `services/nubra_client/equity_order_handler.py` | Wired `entry_gates` param; CALL-only gate loop; default from config |
| `config/nubra_config.json` | Added `entry_threshold` block |
| `tests/nubra/test_entry_gate.py` | **NEW** — 23 gate tests (unit + handler integration) |
| `tests/nubra/test_equity_order_handler.py` | Signal fixture updated: added `expected_move_pct: 0.05, horizon: "1d"` (BP-123 compliant — assertions unchanged) |
| `tests/nubra/test_equity_end_to_end.py` | Same signal fixture update |

### Commit

`021e0f8` on branch `nubra-bringup`

### Test count

- Before: 78 passing
- After: **101 passing** (+23 new gate tests)

### Design decisions

- `EntryGate` is an ABC — easy to add future filters (e.g. `VolumeGate`, `NewsScoreGate`) by implementing the interface and appending to the list.
- Gates are applied **only to CALL** (bullish entry). PUT (sell-to-close) and HOLD bypass entirely — exits must never be blocked.
- Gate list is checked **after** market-hours check, **before** translate/LTP call — cheap rejection path.
- Default gate built from `config/nubra_config.json["entry_threshold"]` when `entry_gates=None` — no test wiring needed.
- `max_horizon_days=null` in config = no horizon cap (off by default, operator can enable).

---

## Task #2 — Live SDK wiring (auth + funds + DI)

### SDK Findings (nubra_python_sdk 0.4.4)

| Component | Class | Key method |
|-----------|-------|------------|
| Auth | `InitNubraSdk(env, env_creds=True)` | Reads PHONE_NO/MPIN from `.env`; persists session to `auth_data.db` (shelve); OTP only on first login |
| Trading | `NubraTrader(client)` | `create_order(dict)`, `get_order(id)`, `cancel_orders_v2(order_ids=[...])` |
| Portfolio | `NubraPortfolio(client)` | `funds()` → `PFMMessage` → `.port_funds_and_margin.net_margin_available` (paise) |
| Positions | `NubraPortfolio(client)` | `positions("V2")` → `PortfolioMessageV2` → `.portfolio.positions` list of `PositionStructV2` (`.symbol`, `.net_quantity`) |
| Market data | `MarketData(client)` | `current_price(symbol, exchange)` → `.price` (paise) |
| Instruments | `InstrumentData(client)` | `get_instrument_by_symbol(symbol, exchange)` → ref_id, tick_size |

**Bug fixed**: `NubraClient.positions()` was calling `self._sdk_trader.positions("V2")` — `NubraTrader` has no `positions()` method. Fixed to delegate to `sdk_portfolio`.

### Files changed

| File | Change |
|------|--------|
| `services/nubra_client/order_state_tracker.py` | Added `_BLOCKING` set + `is_blocking()` method |
| `services/nubra_client/equity_order_handler.py` | Switch duplicate check from `was_placed()` → `is_blocking()` |
| `services/nubra_client/nubra_client.py` | `sdk_portfolio=None` param; `from_session()` wired; `funds()`; `positions()` fixed+normalised |
| `services/nubra_client/nubra_broker.py` | `get_funds()` delegates to `self._c.funds()` |
| `services/nubra_client/equity_assembly.py` | **NEW** — `build_equity_stack(mode, config)` DI factory |
| `scripts/nubra_login.py` | Implemented OTP flow via `InitNubraSdk(env_creds=True)` |
| `scripts/nubra_uat_smoke.py` | Implemented read-only smoke (funds + LTP + positions) |
| `tests/nubra/test_order_state_tracker.py` | +6 `is_blocking()` tests |
| `tests/nubra/test_nubra_broker.py` | +1 `get_funds` test |
| `tests/nubra/test_equity_assembly.py` | **NEW** — 5 paper-mode DI assembly tests |

### Commits (branch `nubra-bringup`)

| Hash | Description |
|------|-------------|
| `fb2a232` | G0 — is_blocking + get_funds + handler switch |
| `8f1eb31` | G1 — NubraClient from_session funds positions |
| `0db298a` | G2 — equity_assembly DI factory + login + smoke scripts |

### Test count

- Before: 101 passing
- After: **113 passing** (+12 new tests)

### Design decisions

- **`is_blocking()` semantics**: FILLED blocks (position held, no re-entry); REJECTED/CANCELLED/EXPIRED allow retry without manual state clear.
- **`from_session` session_token**: Accepted for interface compat; the SDK manages its own session via shelve `auth_data.db` — no custom JSON session needed at SDK level.
- **Single whitelist source**: `nubra_config.json["whitelist"]` is read once in `equity_assembly.py` and passed to both `NubraFeedAdapter` and `SignalToEquityOrder`.
- **`equity_assembly` is mode-agnostic**: Adding a new mode (e.g. `prod`) requires one new `_<mode>_components()` function + one `elif` — no changes to callers.

### How to run (user steps)

```bash
cd market-swarm-lab

# 1. First-time login (OTP prompt on stdin; re-run only if auth_data.db expires)
python3.11 scripts/nubra_login.py --env UAT

# 2. Verify live connectivity (read-only — no orders)
python3.11 scripts/nubra_uat_smoke.py
```

`.env` must contain `PHONE_NO=<your-number>` and `MPIN=<your-mpin>` (never committed — gitignored).

### Security

- `.env` is gitignored (`*.env` on line 10 of `.gitignore`)
- Never stage or commit `market-swarm-lab/.env`
- `auth_data.db` shelve is written by SDK; also gitignored

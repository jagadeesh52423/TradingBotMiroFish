# Nubra Live Dashboard — Implementation Notes

## Files Changed

### New
- `services/nubra_client/equity_runner.py` — extracted `NubraEquityRunner`, `_chunk`, `_build_risk_audit`, `_TRADE_TO_FORECAST_DIR`, `load_config()`, `build_runner()` from `scripts/run_nubra_equity.py`
- `apps/api/nubra_live.py` — thread-safe scan loop + snapshot store + FastAPI integration
- `apps/api/static/nubra_dashboard.html` — self-contained vanilla JS dashboard (no build step)
- `start_nubra_dashboard.sh` — convenience launcher

### Modified
- `scripts/run_nubra_equity.py` — slim import wrapper (~134 lines, was 417); CLI behavior unchanged
- `apps/api/main.py` — startup hook + `/nubra/live` + `/nubra/dashboard` routes
- `README.md` — "Live Dashboard" section added

## Architecture

```
NUBRA_LIVE=1 uvicorn apps.api.main:app
    └─ startup() → nubra_live.start(app, interval=900)
                       └─ daemon thread: scan_loop()
                              └─ build_runner(config) once
                              └─ runner.run_once(dry_run=True) every 900s
                              └─ _LiveStore.publish(snapshot)

GET /nubra/live       → JSONResponse(_store.get())
GET /nubra/dashboard  → FileResponse(static/nubra_dashboard.html)
```

## Key Decisions

**`dry_run=True` is unconditional** — scanner never places orders; enforced in `scan_loop`, not in config.

**`_ACTION_MAP`** — `signal["trade"]` is "CALL"/"PUT"/"HOLD". Dashboard shows "BUY"/"SELL"/"HOLD".

**Thread safety** — `_LiveStore` uses a single `threading.Lock`. `publish()` + `get()` both copy under lock.

**Offline resilience** — on any exception in `scan_loop`, runner is reset to `None` (rebuild next iteration), `status="offline"` with login hint published. Never crashes the daemon.

**sys.path** — `equity_runner.py` lives in `services/nubra_client/` so `parents[2]` → repo root. `nubra_live.py` lives in `apps/api/` so `parents[2]` → repo root. Both insert `_ROOT` idempotently before any imports from `services/`.

**Sleep is interruptible** — `scan_loop` sleeps in 1-second steps via `stop_event.wait(1)` so the thread responds promptly to shutdown.

## Verification

Self-check (no network/login):
```bash
python3.11 apps/api/nubra_live.py
# → self-check OK
```

---

## Futures Strip (2026-06-22)

### Files Changed

#### New
- `services/nubra_client/nubra_futures_provider.py` — `@register_provider("nubra_futures")` implementing `MarketDataProvider`; resolves nearest-expiry FUT contract per underlying via `get_instruments(derivative_type="FUT", asset=underlying)`, LTP via `quote(ref_id, 1).orderBook.last_traded_price`, history via `historical_data(type="FUT", values=[stock_name])`.

#### Modified
- `services/nubra_client/market_data_registry.py` — one import line added in `_ensure_providers_loaded()` for `nubra_futures`.
- `config/nubra_config.json` — added `"futures": {"provider": "nubra_futures", "underlyings": ["NIFTY","BANKNIFTY"]}` block.
- `apps/api/nubra_live.py` — added `_build_futures_provider()` + `_scan_futures()` helpers; futures provider built once alongside the equity runner; `_scan_futures` called each cycle; result published as `"futures": [...]` in the snapshot.  Futures failure is non-fatal (catches, logs, publishes `futures: []`).
- `apps/api/static/nubra_dashboard.html` — pinned `#futures-strip` above the equity table; `renderFutures()` JS function reads `d.futures`, renders `NIFTY26JUNFUT ₹24,148.60 ▲ +0.4%` style rows, color-coded by direction; muted placeholder when empty/offline.
- `README.md` — "Live Dashboard" note added.

### Key Decisions

**`stock_name` vs `nubra_name`** — `historical_data` values key MUST be `stock_name` (e.g. `'NIFTY26JUNFUT'`); the `nubra_name` form raises `NubraValidationError`. This is enforced in the provider.

**Contract cache** — `resolve_contract()` caches per-session to avoid repeated `get_instruments()` calls every scan cycle.

**Futures isolation** — `_scan_futures` catches all exceptions per-underlying so a BANKNIFTY failure does not block NIFTY, and any futures error cannot propagate to the equity scan loop.

**No new dependencies** — vanilla JS strip, no build step.

### Verification
```
python3.11 services/nubra_client/nubra_futures_provider.py
# → self-check OK (nearest-expiry, paise→rupees, stock_name key)

python3.11 apps/api/nubra_live.py
# → self-check OK (includes futures strip stub test)

python3.11 -m pytest tests/nubra/ -q
# → 415 passed
```

CLI regression:
```bash
python3.11 scripts/run_nubra_equity.py --help
# → argparse help prints cleanly (no import errors)
```

Offline path (no Nubra session):
```bash
NUBRA_LIVE=1 python3.11 -m uvicorn apps.api.main:app --port 8001 &
curl -s localhost:8001/nubra/live | python3.11 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='offline', d; print('offline OK')"
```

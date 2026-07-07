"""Background scan loop + snapshot store for the Nubra live dashboard.

Usage (API startup):
    from .nubra_live import start
    start(app, interval=900)

Self-check (no network/login needed):
    python3.11 apps/api/nubra_live.py
"""
from __future__ import annotations

import logging
import pathlib
import sys
import threading
import time
from typing import Any

_ROOT = pathlib.Path(__file__).parents[2]  # apps/api → apps → market-swarm-lab/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.nubra_client.equity_runner import build_runner, load_config  # noqa: E402
from services.nubra_client.market_data_registry import get_provider  # noqa: E402
from services.nubra_client.universe_registry import (  # noqa: E402
    get_universe,
    load_universes_from_config,
)

_log = logging.getLogger(__name__)

# Map signal.trade values to user-facing action labels.
_ACTION_MAP: dict[str, str] = {"CALL": "BUY", "PUT": "SELL", "HOLD": "HOLD"}


# ---------------------------------------------------------------------------
# Snapshot store
# ---------------------------------------------------------------------------

class _LiveStore:
    """Thread-safe singleton holding the latest scan snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] = {
            "status": "starting",
            "scanning": False,
            "rows": [],
            "summary": {},
            "source_health": {},
            "error": None,
            "last_scan": None,
            "next_scan": None,
            "interval": None,
        }

    def publish(self, patch: dict) -> None:
        with self._lock:
            self._snapshot.update(patch)

    def get(self) -> dict:
        with self._lock:
            return dict(self._snapshot)


_store = _LiveStore()


def get_snapshot() -> dict:
    return _store.get()


# ---------------------------------------------------------------------------
# Row mapper
# ---------------------------------------------------------------------------

def _to_rows(result: dict) -> list[dict]:
    rows = []
    for r in result.get("results", []):
        sig = r.get("signal") or {}
        fc = r.get("forecast") or {}
        status = r.get("status", "")
        if status == "error":
            action = "ERR"
        elif status == "skipped":
            action = "SKIP"
        else:
            action = _ACTION_MAP.get(sig.get("trade", "HOLD"), "HOLD")
        rows.append({
            "symbol": r.get("symbol", ""),
            "action": action,
            "upside_pct": fc.get("predicted_return") if fc else sig.get("expected_move_pct"),
            "confidence": sig.get("confidence"),
            "nse_sentiment": r.get("nse_sentiment"),
            "ltp": r.get("ltp"),
            "modes": r.get("provider_modes") or {},
            "skip_reason": r.get("skip_reason"),
        })
    return rows


def _aggregate_modes(rows: list[dict]) -> dict:
    tfm: set[str] = set()
    mf: set[str] = set()
    nse: set[str] = set()
    for r in rows:
        modes = r.get("modes") or {}
        if modes.get("timesfm"):
            tfm.add(modes["timesfm"])
        if modes.get("mirofish"):
            mf.add(modes["mirofish"])
        if modes.get("nse"):
            nse.add(modes["nse"])
    return {
        "nubra": "nubra_uat",  # ponytail: static; add dynamic detection when needed
        "timesfm": ",".join(sorted(tfm)) or "—",
        "mirofish": ",".join(sorted(mf)) or "—",
        "nse": ",".join(sorted(nse)) or "—",
    }


# ---------------------------------------------------------------------------
# Futures strip helpers
# ---------------------------------------------------------------------------

def _build_forecaster():
    """Instantiate TimesFMForecastingService once; returns None if unavailable."""
    try:
        from services.forecasting.forecasting_service import TimesFMForecastingService
        return TimesFMForecastingService()
    except Exception as exc:
        _log.warning("futures: forecasting service unavailable: %s", exc)
        return None


def _scan_futures(config: dict, futures_provider, forecaster) -> list[dict]:
    """Fetch LTP + small forecast for each configured underlying.

    Returns a list of dicts safe for JSON: {underlying, contract, expiry, ltp, forecast_pct, direction}.
    Any per-underlying failure is caught and logged; does not propagate.
    """
    underlyings: list[str] = config.get("futures", {}).get("underlyings", [])
    rows: list[dict] = []
    for underlying in underlyings:
        try:
            contract_meta = futures_provider.resolve_contract(underlying)
            ltp = float(futures_provider.current_price(underlying))
            bars = futures_provider.historical(underlying, lookback=20)
            closes = [b["close"] for b in bars]
            forecast_pct = 0.0
            direction = "neutral"
            if forecaster and closes:
                try:
                    fc = forecaster.forecast_from_prices(underlying, closes, horizon=5)
                    forecast_pct = round(float(fc.get("predicted_return", 0.0)) * 100, 2)
                    direction = fc.get("direction", "neutral")
                except Exception as fc_exc:
                    _log.warning("futures: forecast failed for %s: %s", underlying, fc_exc)
            rows.append({
                "underlying": underlying,
                "contract": contract_meta["stock_name"],
                "expiry": contract_meta["expiry"],
                "ltp": ltp,
                "forecast_pct": forecast_pct,
                "direction": direction,
            })
        except Exception as exc:
            _log.warning("futures: scan failed for %s: %s", underlying, exc, exc_info=True)
    return rows


def _build_futures_provider(config: dict):
    """Build the futures provider from config; returns None if no futures block."""
    futures_cfg = config.get("futures")
    if not futures_cfg:
        return None
    provider_name = futures_cfg.get("provider", "nubra_futures")
    try:
        return get_provider(provider_name, config)
    except Exception as exc:
        _log.warning("futures: provider init failed (%s): %s", provider_name, exc)
        return None


# ---------------------------------------------------------------------------
# Scan loop
# ---------------------------------------------------------------------------

def scan_loop(interval: int, stop_event: threading.Event) -> None:
    _store.publish({"interval": interval})
    runner = None
    futures_provider = None
    forecaster = None

    while not stop_event.is_set():
        _store.publish({"scanning": True})
        try:
            if runner is None:
                config = load_config()
                load_universes_from_config(config)
                universe_name = config.get("universe")
                if universe_name:
                    config["whitelist"] = get_universe(universe_name)
                runner = build_runner(config)
                futures_provider = _build_futures_provider(config)
                forecaster = _build_forecaster()

            result = runner.run_once(dry_run=True)
            runner._trade_count = 0  # reset daily cap between scans

            rows = _to_rows(result)

            futures_rows: list[dict] = []
            if futures_provider is not None:
                try:
                    futures_rows = _scan_futures(config, futures_provider, forecaster)
                except Exception as exc:
                    _log.error("futures scan error (non-fatal): %s", exc, exc_info=True)

            now = time.time()
            _store.publish({
                "status": "ok",
                "scanning": False,
                "rows": rows,
                "futures": futures_rows,
                "summary": {k: result[k] for k in ("symbols_processed", "traded", "skipped", "errors")},
                "source_health": _aggregate_modes(rows),
                "last_scan": now,
                "next_scan": now + interval,
                "error": None,
            })
            _log.info(
                "scan complete | symbols=%d traded=%d skipped=%d errors=%d futures=%d",
                result["symbols_processed"], result["traded"], result["skipped"], result["errors"],
                len(futures_rows),
            )
        except Exception as exc:
            _log.error("scan_loop error: %s", exc, exc_info=True)
            runner = None  # force rebuild next iteration
            futures_provider = None
            forecaster = None
            now = time.time()
            _store.publish({
                "status": "offline",
                "scanning": False,
                "error": "scanner offline — run scripts/nubra_login.py, see server logs for details",
                "rows": [],
                "futures": [],
                "last_scan": now,
                "next_scan": now + interval,
            })

        # Sleep in 1s steps so stop_event is responsive.
        for _ in range(interval):
            if stop_event.is_set():
                break
            stop_event.wait(1)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def start(app, interval: int = 900) -> None:  # noqa: ARG001  (app reserved for lifespan hooks)
    stop_event = threading.Event()
    thread = threading.Thread(
        target=scan_loop,
        args=(interval, stop_event),
        daemon=True,
        name="nubra-scan",
    )
    thread.start()
    _log.info("Nubra live scan started (interval=%ds, dry_run=True)", interval)


# ---------------------------------------------------------------------------
# Self-check — runs with no network/login
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fake_result: dict = {
        "symbols_processed": 2,
        "traded": 1,
        "skipped": 1,
        "errors": 0,
        "results": [
            {
                "symbol": "RELIANCE",
                "signal": {"trade": "CALL", "confidence": 0.72, "expected_move_pct": 3.2},
                "forecast": {"direction": "bullish", "predicted_return": 3.2},
                "nse_sentiment": "positive",
                "ltp": 2500.0,
                "provider_modes": {
                    "timesfm": "local_fallback",
                    "mirofish": "local_formula",
                    "nse": "fixture_fallback",
                },
                "status": "executed",
            },
            {
                "symbol": "INFY",
                "signal": None,
                "forecast": None,
                "nse_sentiment": "neutral",
                "ltp": 1450.0,
                "provider_modes": {},
                "status": "skipped",
                "skip_reason": "HOLD",
            },
        ],
    }

    rows = _to_rows(fake_result)
    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"

    buy_row = rows[0]
    assert buy_row["symbol"] == "RELIANCE", buy_row
    assert buy_row["action"] == "BUY", f"expected BUY (CALL→BUY), got {buy_row['action']}"
    assert buy_row["upside_pct"] == 3.2, buy_row
    assert buy_row["confidence"] == 0.72, buy_row

    skip_row = rows[1]
    assert skip_row["action"] == "SKIP", f"expected SKIP for skipped row, got {skip_row['action']}"

    health = _aggregate_modes(rows)
    assert "nubra" in health, health
    assert health["timesfm"] == "local_fallback", health

    # futures helper: no-futures-config → provider is None
    assert _build_futures_provider({}) is None, "expected None for config with no 'futures' key"

    # _scan_futures with a stub provider
    class _StubFuturesProvider:
        def resolve_contract(self, underlying):
            return {"stock_name": f"{underlying}26JUNFUT", "expiry": 20260626,
                    "lot_size": 65, "tick_size": 10, "ref_id": "STUB"}

        def current_price(self, underlying):
            from decimal import Decimal
            return Decimal("24148.60")

        def historical(self, underlying, lookback=20):
            return [{"close": 24000.0 + i * 10, "timestamp": i * 86400000} for i in range(lookback)]

    fake_config = {"futures": {"provider": "nubra_futures", "underlyings": ["NIFTY"]}}
    fut_rows = _scan_futures(fake_config, _StubFuturesProvider(), forecaster=None)
    assert len(fut_rows) == 1, f"expected 1 futures row, got {len(fut_rows)}"
    assert fut_rows[0]["underlying"] == "NIFTY", fut_rows[0]
    assert fut_rows[0]["contract"] == "NIFTY26JUNFUT", fut_rows[0]
    assert fut_rows[0]["ltp"] == 24148.60, fut_rows[0]

    print("self-check OK")
    for row in rows:
        print(" ", row)
    print("  futures:", fut_rows)

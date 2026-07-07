"""Importable NubraEquityRunner — shared by the CLI script and the live API."""
from __future__ import annotations

import json
import logging
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any

# Idempotent sys.path setup: market-swarm-lab root + hyphenated service dirs.
_ROOT = pathlib.Path(__file__).parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
for _svc in ("mirofish-bridge", "risk-engine"):
    _p = str(_ROOT / "services" / _svc)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mirofish_bridge_service import MiroFishBridgeService  # noqa: E402
from risk_engine_service import RiskEngineService  # noqa: E402

from services.nse_announcements.nse_announcements_collector import NseAnnouncementsCollector
from services.nubra_client.news_aggregator import AggregatingNewsCollector
from services.nubra_client.entry_gate import (
    CircuitStatusGate, ExpectedUpsideGate, FirstFifteenGate, SectorTrendGate)
from services.nubra_client.circuit_status import FyersCircuitProvider, NseCircuitProvider
from services.nubra_client.sector_trend import SectorTrendProvider
from services.nubra_client.first_fifteen import FirstFifteenProvider
from services.nse_delivery.delivery_collector import NseDeliveryCollector
from services.nubra_client.position_sizing import band_pct_from_circuit, band_size_factor
from services.nubra_client.equity_assembly import build_equity_stack
from services.nubra_client.equity_context_builder import build_equity_context
from services.nubra_client.signal_strategies import get_strategy
from services.forecasting.forecasting_service import TimesFMForecastingService

_log = logging.getLogger(__name__)
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"

# Maps EquitySignalBuilder direction labels to MiroFish local-formula direction keys.
_TRADE_TO_FORECAST_DIR: dict[str, str] = {
    "bullish": "up",
    "bearish": "down",
    "neutral": "sideways",
}


class NubraEquityRunner:
    """Processes each whitelisted symbol through the full signal → execution pipeline."""

    def __init__(
        self,
        config: dict,
        *,
        forecasting: TimesFMForecastingService | None = None,
        mirofish: MiroFishBridgeService | None = None,
        risk_engine: RiskEngineService | None = None,
        nse_collector: NseAnnouncementsCollector | None = None,
        circuit_gate: CircuitStatusGate | None = None,
        extra_gates: list | None = None,
        nubra_client=None,
        equity_stack=None,
        strategy: str | None = None,
    ) -> None:
        self._cfg = config
        self._whitelist: list[str] = config["whitelist"]
        self._max_workers: int = int(config.get("runner", {}).get("max_workers", 3))
        self._sleep_secs: float = float(
            config.get("runner", {}).get("inter_batch_sleep_secs", 0.5)
        )
        self._max_trades: int = int(config.get("max_trades_per_day", 5))

        self._forecasting = forecasting or TimesFMForecastingService()
        self._mirofish = mirofish or MiroFishBridgeService()
        self._risk = risk_engine or RiskEngineService()
        # Default aggregates all enabled news sources (NSE + Google News + ...) into
        # one nse_result; falls back to NSE-only when no extra sources are configured.
        self._nse = nse_collector or AggregatingNewsCollector.from_config(config)
        self._entry_gate = ExpectedUpsideGate(config.get("entry_threshold", {}))
        # Extra India-playbook gates, evaluated in order after the upside gate. All opt-in
        # (config or injected) and fail-open, so existing callers are unaffected.
        et_cfg = config.get("entry_threshold", {})
        self._extra_gates: list = list(extra_gates) if extra_gates is not None else []
        self._circuit_provider = None  # reused for circuit-aware sizing (§5)
        if not self._extra_gates:
            cg_cfg = et_cfg.get("circuit_gate", {})
            if circuit_gate is not None:
                self._extra_gates.append(circuit_gate)
            elif cg_cfg.get("enabled"):
                # Fyers default (depth() carries upper/lower_ckt); "nse" as fallback.
                self._circuit_provider = (
                    NseCircuitProvider.from_config(config)
                    if cg_cfg.get("source", "fyers") == "nse"
                    else FyersCircuitProvider.from_config(config)
                )
                self._extra_gates.append(CircuitStatusGate(self._circuit_provider, cg_cfg))
            if et_cfg.get("sector_gate", {}).get("enabled"):
                self._extra_gates.append(SectorTrendGate(SectorTrendProvider.from_config(config)))
            if et_cfg.get("first15_gate", {}).get("enabled"):
                self._extra_gates.append(FirstFifteenGate(FirstFifteenProvider.from_config(config)))
        ps_cfg = et_cfg.get("position_sizing", {})
        self._sizing_enabled = bool(ps_cfg.get("enabled")) and self._circuit_provider is not None
        self._band_tiers = ps_cfg.get("band_tiers")
        # Delivery-% conviction: a SOFT flag on the result, never a gate (§8 research caveat).
        dv_cfg = config.get("delivery", {}).get("conviction_flag", {})
        self._delivery = NseDeliveryCollector.from_config(config) if dv_cfg.get("enabled") else None
        self._delivery_n = int(dv_cfg.get("trailing_days", 20))
        self._min_bars: int = int(config.get("signal", {}).get("min_bars_for_signal", 10))
        self._nubra_client = nubra_client
        self._stack = equity_stack

        # Strategy: arg overrides config; config defaults to "blended".
        strategy_name = strategy or config.get("signal", {}).get("strategy", "blended")
        self._strategy = get_strategy(strategy_name, config)
        self._strategy_name = strategy_name

        self._trade_count = 0
        self._trade_lock = Lock()

    # ------------------------------------------------------------------ public

    def run_once(self, *, dry_run: bool = False) -> dict[str, Any]:
        _log.info(
            "run_once start | symbols=%d max_trades=%d dry_run=%s",
            len(self._whitelist), self._max_trades, dry_run,
        )
        results: list[dict] = []
        batches = _chunk(self._whitelist, self._max_workers)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for batch in batches:
                futures = {
                    pool.submit(self._process_symbol, sym, dry_run=dry_run): sym
                    for sym in batch
                }
                for future in as_completed(futures):
                    sym = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        _log.error("Symbol %s failed: %s", sym, exc, exc_info=True)
                        result = {"symbol": sym, "status": "error", "error": str(exc)}
                    results.append(result)
                    _log.info(
                        "%s | status=%s provider_modes=%s",
                        sym,
                        result.get("status"),
                        result.get("provider_modes"),
                    )
                time.sleep(self._sleep_secs)

        traded = [r for r in results if r.get("status") == "executed"]
        skipped = [r for r in results if r.get("status") == "skipped"]
        errors = [r for r in results if r.get("status") == "error"]
        _log.info(
            "run_once done | traded=%d skipped=%d errors=%d",
            len(traded), len(skipped), len(errors),
        )
        return {
            "symbols_processed": len(results),
            "traded": len(traded),
            "skipped": len(skipped),
            "errors": len(errors),
            "results": results,
        }

    # ----------------------------------------------------------------- private

    def _delivery_flag(self, symbol: str) -> dict:
        """Soft delivery-% conviction (§8): 'high' if today's deliv% >= its trailing avg (real
        accumulation), else 'low'; None fields when the collector has no figure. Never blocks."""
        if self._delivery is None:
            return {"delivery_conviction": None, "delivery_pct": None, "delivery_trailing_avg": None}
        from datetime import datetime, timedelta, timezone
        on = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        deliv = self._delivery.deliv_pct(symbol, on)
        avg = self._delivery.trailing_avg(symbol, on, self._delivery_n)
        return {"delivery_conviction": _delivery_conviction(deliv, avg),
                "delivery_pct": deliv, "delivery_trailing_avg": avg}

    def _apply_sizing(self, signal: dict) -> None:
        """Attach size_factor + band_pct to a CALL signal from live circuit-band width (§5)."""
        if not self._sizing_enabled or str(signal.get("trade", "")).upper() != "CALL":
            return
        status = self._circuit_provider.status(str(signal.get("ticker", "")).upper())
        if not status:
            return
        band = band_pct_from_circuit(status)
        if band is None:
            return
        signal["band_pct"] = round(band, 2)
        signal["size_factor"] = band_size_factor(band, self._band_tiers)

    def _process_symbol(self, symbol: str, *, dry_run: bool) -> dict[str, Any]:
        if self._nubra_client is None:
            raise RuntimeError(
                "nubra_client required for live run — pass via constructor or use dry_run with stub"
            )

        context = build_equity_context(symbol, self._nubra_client)
        nse_result = self._nse.collect(symbol)

        closes = context["price"]["recent_closes"]
        ltp = float(context["price"]["ltp"])

        if self._strategy.requires_price_history and len(closes) < self._min_bars:
            _log.info(
                "%s | insufficient_history (bars=%d < min=%d) — skipped",
                symbol, len(closes), self._min_bars,
            )
            return {
                "symbol": symbol,
                "signal": None,
                "forecast": None,
                "risk": None,
                "entry_gate": None,
                "nse_sentiment": None,
                "ltp": ltp,
                "provider_modes": {},
                "status": "skipped",
                "skip_reason": "insufficient_history",
                "bars": len(closes),
            }

        if not self._strategy.uses_forecast:
            forecast = None
            simulation = None
            signal = self._strategy.build(symbol, context, None, None, nse_result)
            provider_modes = {"timesfm": None, "mirofish": None, "nse": nse_result.get("provider_mode")}
        else:
            forecast = self._forecasting.forecast_from_prices(symbol, closes, horizon=5)
            sim_request = {
                "documents": nse_result["documents"],
                "forecast_summary": {
                    "direction": _TRADE_TO_FORECAST_DIR.get(forecast["direction"], "sideways"),
                    "confidence": forecast["confidence"],
                },
                "personas_config": [],
                "scenario": "equity_trend_daily",
            }
            simulation = self._mirofish.simulate(sim_request)
            signal = self._strategy.build(symbol, context, forecast, simulation, nse_result)
            provider_modes = {
                "timesfm": forecast.get("provider_mode"),
                "mirofish": simulation.get("provider_mode"),
                "nse": nse_result.get("provider_mode"),
            }

        if signal is None or signal["trade"] == "HOLD":
            forecast_summary = (
                {"direction": forecast["direction"], "predicted_return": forecast["predicted_return"]}
                if forecast is not None
                else None
            )
            return {
                "symbol": symbol,
                "signal": signal,
                "forecast": forecast_summary,
                "risk": {"approved": False, "notes": ["HOLD — no directional signal"]},
                "entry_gate": {"ok": False, "reason": "HOLD"},
                "nse_sentiment": nse_result.get("sentiment_label"),
                "ltp": ltp,
                "provider_modes": provider_modes,
                "status": "skipped",
                "skip_reason": "HOLD",
            }

        self._apply_sizing(signal)

        risk_context = {
            **context,
            "source_audit": _build_risk_audit(context["source_audit"], nse_result, closes),
        }
        risk_result = self._risk.evaluate(signal, risk_context)
        gate_ok, gate_reason = self._entry_gate.evaluate(signal)
        for gate in self._extra_gates:
            if not gate_ok:
                break
            gate_ok, gate_reason = gate.evaluate(signal)

        forecast_summary = (
            {"direction": forecast["direction"], "predicted_return": forecast["predicted_return"]}
            if forecast is not None
            else None
        )
        base = {
            "symbol": symbol,
            "signal": signal,
            "forecast": forecast_summary,
            "risk": {"approved": risk_result["approved"], "notes": risk_result.get("risk_notes", [])},
            "entry_gate": {"ok": gate_ok, "reason": gate_reason},
            "nse_sentiment": nse_result.get("sentiment_label"),
            "ltp": ltp,
            "provider_modes": provider_modes,
            # §13 tracker fields — circuit-band width at entry + size scaling (None outside CALL/no-data).
            "band_pct": signal.get("band_pct"),
            "size_factor": signal.get("size_factor"),
            # §8 soft conviction flag (advisory, never gates).
            **self._delivery_flag(symbol),
        }

        if not risk_result["approved"]:
            return {**base, "status": "skipped", "skip_reason": "risk_rejected"}

        if not gate_ok:
            return {**base, "status": "skipped", "skip_reason": gate_reason or "entry_gate"}

        dispatch_result = None
        with self._trade_lock:
            if self._trade_count >= self._max_trades:
                return {**base, "status": "skipped", "skip_reason": "max_trades_per_day"}
            if not dry_run:
                dispatch_result = self._stack.registry.dispatch("equity", signal, risk_result, symbol)
            self._trade_count += 1

        # §13: exit-fill quality on a close (PUT) — full / partial / no-fill (circuit-locked).
        exit_quality = None
        if str(signal.get("trade", "")).upper() == "PUT" and dispatch_result is not None:
            exit_quality = _exit_fill_quality(
                dispatch_result, self._circuit_provider.status(symbol) if self._circuit_provider else None)
        return {**base, "status": "executed", "dry_run": dry_run, "exit_fill_quality": exit_quality}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _delivery_conviction(deliv: float | None, avg: float | None) -> str | None:
    """'high' if delivery% at/above its trailing average (real accumulation), else 'low'."""
    if deliv is None or avg is None:
        return None
    return "high" if deliv >= avg else "low"


def _exit_fill_quality(dispatch_result: dict, circuit_status: dict | None) -> str:
    """Classify a close (SELL) fill for the §13 tracker.

    'full' | 'partial' | 'no_fill_circuit_locked' | 'no_fill'. Paper/live-accepted orders
    report status 'placed' with the requested qty → 'full'; a zero fill while the stock sits
    at its lower circuit is the India-specific failure mode the tracker exists to capture.
    """
    if dispatch_result.get("status") != "placed":
        # A rejected/blocked exit that couldn't fill — check for a lower-circuit lock.
        if circuit_status and circuit_status.get("last") and circuit_status.get("lower") \
                and circuit_status["last"] <= circuit_status["lower"] * 1.001:
            return "no_fill_circuit_locked"
        return "no_fill"
    filled = dispatch_result.get("filled_qty", dispatch_result.get("qty", 0))
    requested = dispatch_result.get("qty", 0)
    if requested and filled >= requested:
        return "full"
    return "partial" if filled else "no_fill"


def _build_risk_audit(equity_audit: dict, nse_result: dict, closes: list) -> dict:
    """Build a RiskEngineService-compatible source_audit from equity context + NSE result.

    Maps data-source quality to the exact keys RiskEngine reads:
      "news"  — Rule 3: fallback → reduce confidence by 0.05
      "ohlcv" — Rule 2: fallback → reject (only LTP available, no history)

    Strips equity context's string "n/a" entries (US sources) which would crash
    RiskEngine's .get("status") calls.
    """
    risk_audit: dict = {}
    for key, val in equity_audit.items():
        if isinstance(val, dict):
            risk_audit[key] = val
        # string "n/a"/"ok" are equity-context shorthand — omit from risk context

    # Rule 3 — news quality derived from NSE provider_mode
    nse_mode = nse_result.get("provider_mode", "fixture_fallback")
    risk_audit["news"] = {"status": "live" if nse_mode == "nse_live" else "fallback"}

    # Rule 2 — OHLCV quality: degraded when only LTP was available (≤1 close)
    risk_audit["ohlcv"] = {"status": "fallback" if len(closes) <= 1 else "live"}

    return risk_audit


def load_config(path: pathlib.Path = _CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_runner(config: dict, *, strategy: str | None = None) -> NubraEquityRunner:
    """Construct a NubraEquityRunner from a config dict (whitelist must already be resolved)."""
    stack = build_equity_stack("nubra_uat", config)
    return NubraEquityRunner(
        config,
        nubra_client=stack.market_data,
        equity_stack=stack,
        strategy=strategy,
    )

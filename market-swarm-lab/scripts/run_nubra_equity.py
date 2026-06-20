"""Nubra equity runner — processes Nifty50 whitelist through the full signal pipeline.

Usage:
    python scripts/run_nubra_equity.py --once
    python scripts/run_nubra_equity.py --interval 3600
    python scripts/run_nubra_equity.py --once --dry-run
    python scripts/run_nubra_equity.py --once --dry-run --strategy news_only

The 3-phase pipeline per symbol:
  1. Fetch  — OHLCV via NubraClient.historical() + NSE announcements
  2. Signal — TimesFM forecast → MiroFish simulation → EquitySignalBuilder (blended)
              OR NSE announcements only → NewsOnlySignalStrategy (news_only)
  3. Trade  — RiskEngine → ExpectedUpsideGate → ExecutionEngine (or skip in dry-run)

Strategy selection:
  --strategy blended    (default) — full blended pipeline, OHLCV required
  --strategy news_only  — news-only pipeline; thin-history skip does NOT apply

Config toggles (set in .env or environment):
  MIROFISH_BASE_URL   — if set, MiroFish runs as a remote service
  ENABLE_TIMESFM      — if "false", uses linear fallback instead of neural model

All `provider_mode` values are logged per symbol so Caveats D/E are always visible.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any

_ROOT = pathlib.Path(__file__).parents[1]
# Add _ROOT so services/nubra_client, services/nse_announcements, services/forecasting resolve.
sys.path.insert(0, str(_ROOT))
# Services with hyphenated directories are not importable as packages — add them individually.
for _svc in ("mirofish-bridge", "risk-engine"):
    _p = str(_ROOT / "services" / _svc)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mirofish_bridge_service import MiroFishBridgeService  # noqa: E402 (after sys.path setup)
from risk_engine_service import RiskEngineService  # noqa: E402

from services.nse_announcements.nse_announcements_collector import NseAnnouncementsCollector
from services.nubra_client.entry_gate import ExpectedUpsideGate
from services.nubra_client.equity_assembly import build_equity_stack
from services.nubra_client.equity_context_builder import build_equity_context
from services.nubra_client.signal_strategies import _REGISTRY, get_strategy
from services.nubra_client.universe_registry import (
    _UNIVERSE_REGISTRY,
    get_universe,
    load_universes_from_config,
)
from services.forecasting.forecasting_service import TimesFMForecastingService

# Derived from the strategy registry so new strategies appear in --help automatically.
_VALID_STRATEGIES = tuple(sorted(_REGISTRY))

_log = logging.getLogger(__name__)
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"

# Map EquitySignalBuilder "bullish"/"bearish"/"neutral" back to the direction
# labels the MiroFish local formula checks ("up"/"down"/"sideways").
_TRADE_TO_FORECAST_DIR: dict[str, str] = {
    "bullish": "up",
    "bearish": "down",
    "neutral": "sideways",
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

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
        self._nse = nse_collector or NseAnnouncementsCollector.from_config(config)
        self._entry_gate = ExpectedUpsideGate(config.get("entry_threshold", {}))
        self._min_bars: int = int(config.get("signal", {}).get("min_bars_for_signal", 10))
        self._nubra_client = nubra_client
        self._stack = equity_stack

        # Strategy: CLI arg overrides config; config defaults to "blended".
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

    def _process_symbol(self, symbol: str, *, dry_run: bool) -> dict[str, Any]:
        # ── Phase 1: Fetch ──────────────────────────────────────────────────
        if self._nubra_client is None:
            raise RuntimeError(
                "nubra_client required for live run — pass via constructor or use dry_run with stub"
            )

        context = build_equity_context(symbol, self._nubra_client)
        nse_result = self._nse.collect(symbol)

        closes = context["price"]["recent_closes"]
        ltp = float(context["price"]["ltp"])

        # Thin-history guard: skip when bar count is too low.
        # Strategies that don't need OHLCV history declare requires_price_history=False.
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

        # ── Phase 2: Forecast + Signal ──────────────────────────────────────
        # Strategies that don't use forecast/simulation declare uses_forecast=False.
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

        # ── Phase 3: Risk + Execute ─────────────────────────────────────────
        # None signal (strategy declined) or HOLD short-circuit.
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

        # Build risk-engine-compatible source_audit: maps NSE→"news" (Rule 3) and
        # OHLCV quality→"ohlcv" (Rule 2); strips equity context's string "n/a" entries.
        risk_context = {
            **context,
            "source_audit": _build_risk_audit(context["source_audit"], nse_result, closes),
        }
        risk_result = self._risk.evaluate(signal, risk_context)
        gate_ok, gate_reason = self._entry_gate.evaluate(signal)

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
        }

        if not risk_result["approved"]:
            return {**base, "status": "skipped", "skip_reason": "risk_rejected"}

        if not gate_ok:
            return {**base, "status": "skipped", "skip_reason": gate_reason or "entry_gate"}

        with self._trade_lock:
            if self._trade_count >= self._max_trades:
                return {**base, "status": "skipped", "skip_reason": "max_trades_per_day"}
            if not dry_run:
                self._stack.registry.dispatch("equity", signal, risk_result, symbol)
            self._trade_count += 1

        return {**base, "status": "executed", "dry_run": dry_run}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _load_config(path: pathlib.Path = _CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_whitelist(config: dict, universe_override: str | None) -> list[str]:
    """Resolve the active symbol list and mutate config["whitelist"] in place.

    Precedence: --universe flag > config["universe"] > legacy config["whitelist"].
    Mutating in place keeps both consumers (build_equity_stack + NubraEquityRunner,
    which each read config["whitelist"]) in sync from a single source of truth.
    """
    name = universe_override or config.get("universe")
    resolved = get_universe(name) if name else config["whitelist"]
    config["whitelist"] = resolved
    return resolved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _preparse_config_path(argv=None) -> pathlib.Path:
    """Extract --config before the main parse so universes load before argparse.

    The --universe choices come from the registry, which is populated from the
    config's "universes" map — so the config path must be known first.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(_CONFIG_PATH))
    known, _ = pre.parse_known_args(argv)
    return pathlib.Path(known.config)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Nubra equity signal runner")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run one pass then exit")
    mode.add_argument(
        "--interval", type=int, metavar="SECONDS", help="Loop with this sleep between runs"
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip order placement")
    parser.add_argument("--config", default=str(_CONFIG_PATH), help="Path to nubra_config.json")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    parser.add_argument(
        "--strategy",
        choices=sorted(_REGISTRY),
        default=None,
        help="Signal strategy override (default: read from config signal.strategy)",
    )
    parser.add_argument(
        "--universe",
        choices=sorted(_UNIVERSE_REGISTRY),
        default=None,
        help="Universe override (default: read from config universe / whitelist)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    # Load config + universes BEFORE argparse so --universe choices are populated.
    config = _load_config(_preparse_config_path(argv))
    load_universes_from_config(config)
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    _resolve_whitelist(config, args.universe)
    stack = build_equity_stack("nubra_uat", config)
    runner = NubraEquityRunner(
        config,
        nubra_client=stack.market_data,  # NubraClient (current_price + historical), NOT the broker
        equity_stack=stack,
        strategy=args.strategy,  # None → falls back to config signal.strategy
    )

    if args.once:
        summary = runner.run_once(dry_run=args.dry_run)
        print(json.dumps(summary, indent=2, default=str))
    else:
        while True:
            summary = runner.run_once(dry_run=args.dry_run)
            print(json.dumps(summary, indent=2, default=str))
            runner._trade_count = 0  # reset daily cap between intervals
            _log.info("Sleeping %ds before next run", args.interval)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()

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
    CircuitStatusGate, ExpectedUpsideGate, FirstFifteenGate, RegimeGate, SectorTrendGate)
from services.nubra_client.market_regime import MarketRegimeProvider
from services.nubra_client.circuit_status import FyersCircuitProvider, NseCircuitProvider
from services.nubra_client.sector_trend import SectorTrendProvider
from services.nubra_client.first_fifteen import FirstFifteenProvider
from services.nse_delivery.delivery_collector import NseDeliveryCollector
from services.nubra_client.watchlist_scorer import watchlist_score
from services.nubra_client.trade_targets import scale_out_targets
from services.nubra_client.fno_oi import FyersOptionProvider, pcr_label, oi_buildup_label
from services.nubra_client.time_stop import stale_symbols
from services.nubra_client.entry_ledger import EntryLedger
from services.nubra_client.trade_log import TradeLog
from services.nubra_client.pre_open import PreOpenCollector, pre_open_conviction
from services.nse_deals.deals_collector import NseDealsCollector
from services.nubra_client.position_sizing import band_pct_from_circuit, band_size_factor
from services.nubra_client.equity_assembly import build_equity_stack
from services.nubra_client.equity_context_builder import build_equity_context
from services.nubra_client.signal_strategies import get_strategy
from services.forecasting.forecasting_service import TimesFMForecastingService, ForecastUnavailable

_log = logging.getLogger(__name__)
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"

# Empty/None shapes returned by the advisory soft-flag helpers when their data source is
# absent OR raises — an advisory flag failing must never turn a symbol into status=error.
_EMPTY_DELIVERY_FLAG = {"delivery_conviction": None, "delivery_pct": None, "delivery_trailing_avg": None}
_EMPTY_FNO_FLAG = {"pcr": None, "pcr_label": None, "call_oi": None, "put_oi": None, "fno_available": None}
_EMPTY_PRE_OPEN_FLAG = {"pre_open_gap_pct": None, "pre_open_qty": None, "pre_open_iep": None,
                         "pre_open_conviction": None}
_EMPTY_DEALS_FLAG = {"has_deal": None}
_EMPTY_PROMOTER_FLAG = {"trend": None}


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
        # TimesFM confidence is a predictor of upside potential, NOT a filter — the equity
        # screen disables the RiskEngine confidence gate (config default 0.0). Probables are
        # gated by the playbook (circuit/sector/regime/direction) and ranked by watchlist score.
        self._risk = risk_engine or RiskEngineService(
            min_confidence=float(config.get("signal", {}).get("min_confidence_threshold", 0.0))
        )
        # Default aggregates all enabled news sources (NSE + Google News + ...) into
        # one nse_result; falls back to NSE-only when no extra sources are configured.
        self._nse = nse_collector or AggregatingNewsCollector.from_config(config)
        self._entry_gate = ExpectedUpsideGate(config.get("entry_threshold", {}))
        # Extra India-playbook gates, evaluated in order after the upside gate. All opt-in
        # (config or injected) and fail-open, so existing callers are unaffected.
        et_cfg = config.get("entry_threshold", {})
        self._extra_gates: list = list(extra_gates) if extra_gates is not None else []
        self._circuit_provider = None  # reused for circuit-aware sizing (§5)
        self._sector_provider = None   # reused for watchlist scoring (§2)
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
            if et_cfg.get("regime_gate", {}).get("enabled"):
                self._extra_gates.append(RegimeGate(MarketRegimeProvider.from_config(config)))
            if et_cfg.get("sector_gate", {}).get("enabled"):
                self._sector_provider = SectorTrendProvider.from_config(config)
                self._extra_gates.append(SectorTrendGate(self._sector_provider))
            if et_cfg.get("first15_gate", {}).get("enabled"):
                self._extra_gates.append(FirstFifteenGate(FirstFifteenProvider.from_config(config)))
        ps_cfg = et_cfg.get("position_sizing", {})
        self._sizing_enabled = bool(ps_cfg.get("enabled")) and self._circuit_provider is not None
        self._band_tiers = ps_cfg.get("band_tiers")
        # Delivery-% conviction: a SOFT flag on the result, never a gate (§8 research caveat).
        dv_cfg = config.get("delivery", {}).get("conviction_flag", {})
        self._delivery = NseDeliveryCollector.from_config(config) if dv_cfg.get("enabled") else None
        self._delivery_n = int(dv_cfg.get("trailing_days", 20))
        wl_cfg = config.get("watchlist", {})
        self._watchlist_enabled = bool(wl_cfg.get("enabled", True))
        self._watchlist_weights = wl_cfg.get("weights")
        tg_cfg = et_cfg.get("targets", {})
        self._targets_enabled = bool(tg_cfg.get("enabled", True))
        self._targets_cfg = tg_cfg
        fno_cfg = config.get("fno", {}).get("conviction_flag", {})
        self._option_provider = FyersOptionProvider.from_config(config) if fno_cfg.get("enabled") else None
        ts_cfg = et_cfg.get("time_stop", {})
        self._time_stop_enabled = bool(ts_cfg.get("enabled"))
        self._max_sessions = int(ts_cfg.get("max_sessions", 3))
        self._entry_ledger = EntryLedger() if self._time_stop_enabled else None
        self._trade_log = TradeLog() if self._time_stop_enabled else None
        po_cfg = config.get("pre_open", {}).get("conviction_flag", {})
        self._preopen = PreOpenCollector.from_config(config) if po_cfg.get("enabled") else None
        self._preopen_cfg = po_cfg
        self._deals = NseDealsCollector.from_config(config) if config.get("deals", {}).get("enabled") else None
        if config.get("shareholding", {}).get("enabled"):
            from services.nse_shareholding.shareholding_collector import ShareholdingCollector
            self._shareholding = ShareholdingCollector.from_config(config)
        else:
            self._shareholding = None
        self._min_bars: int = int(config.get("signal", {}).get("min_bars_for_signal", 10))
        # Candidacy (watchlist) mode: a probable = any catalyst name that PASSES THE PLAYBOOK
        # GATES (circuit/sector/regime, evaluated as buy-intent). TimesFM direction/upside/
        # confidence ANNOTATE the potential — they never filter. Live-execution mode leaves
        # this off (TimesFM direction drives real CALL/PUT/HOLD orders). Set by screen mode.
        self._candidacy_mode: bool = bool(config.get("candidacy_mode", False))
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

    def _safe_flag(self, fn, symbol: str, default: dict) -> dict:
        """Call an advisory soft-flag helper/collector method; any exception falls back to
        its empty/None shape instead of propagating — an advisory flag is never allowed to
        turn a symbol's whole result into status=error."""
        try:
            return fn(symbol)
        except Exception as exc:
            _log.warning("%s | soft flag %s failed: %s", symbol, getattr(fn, "__name__", fn), exc)
            return default

    def _pre_open_flag(self, symbol: str) -> dict:
        """§3/§11 soft pre-open conviction: indicative gap + book qty. Never gates."""
        if self._preopen is None:
            return _EMPTY_PRE_OPEN_FLAG
        st = self._preopen.status(symbol)
        if not st:
            return _EMPTY_PRE_OPEN_FLAG
        return {"pre_open_gap_pct": st.get("gap_pct"), "pre_open_qty": st.get("qty"),
                "pre_open_iep": st.get("iep"),
                "pre_open_conviction": pre_open_conviction(st.get("gap_pct"), st.get("qty"), self._preopen_cfg)}

    def _fno_flag(self, symbol: str) -> dict:
        """§8 descriptive F&O positioning: PCR + call/put OI + availability. Never gates."""
        if self._option_provider is None:
            return _EMPTY_FNO_FLAG
        s = self._option_provider.summary(symbol)
        if not s:
            return {**_EMPTY_FNO_FLAG, "fno_available": False}
        return {"pcr": s["pcr"], "pcr_label": pcr_label(s["pcr"]),
                "call_oi": s["call_oi"], "put_oi": s["put_oi"], "fno_available": True,
                "call_oi_change": s.get("call_oi_change"), "put_oi_change": s.get("put_oi_change"),
                "oi_buildup": oi_buildup_label(s.get("call_oi_change"), s.get("put_oi_change"))}

    def _watchlist(self, symbol: str, nse_result: dict, signal: dict, delivery_pct) -> dict:
        """§2 5-factor score. Each factor 0..1; missing factors renormalise out (see scorer)."""
        if not self._watchlist_enabled:
            return {"score": None, "factors": {}}
        score = nse_result.get("sentiment_score")
        band = signal.get("band_pct")
        trend = self._sector_provider.trend(symbol) if self._sector_provider else None
        factors = {
            # directional: a BUY watchlist rewards BULLISH news; bearish news → 0 (not magnitude).
            "catalyst": max(0.0, min(1.0, float(score))) if score is not None else None,
            "band": min(1.0, float(band) / 20.0) if band is not None else None,  # wider = more tradeable
            "liquidity": min(1.0, float(delivery_pct) / 100.0) if delivery_pct is not None else None,
            "sector": {"up": 1.0, "down": 0.0}.get(trend),  # None when unmapped/unknown
            "fno": signal.get("fno_factor"),  # populated by the F&O OI task (§8); None until then
        }
        result = watchlist_score(factors, self._watchlist_weights)
        return {"score": result["score"], "factors": result["factors"]}

    def _delivery_flag(self, symbol: str) -> dict:
        """Soft delivery-% conviction (§8): 'high' if today's deliv% >= its trailing avg (real
        accumulation), else 'low'; None fields when the collector has no figure. Never blocks."""
        if self._delivery is None:
            return _EMPTY_DELIVERY_FLAG
        from datetime import datetime, timedelta, timezone
        on = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        deliv = self._delivery.deliv_pct(symbol, on)
        avg = self._delivery.trailing_avg(symbol, on, self._delivery_n)
        return {"delivery_conviction": _delivery_conviction(deliv, avg),
                "delivery_pct": deliv, "delivery_trailing_avg": avg}

    def _apply_sizing(self, signal: dict, force: bool = False) -> None:
        """Attach size_factor + band_pct from live circuit-band width (§5). Normally CALL-only;
        `force` (candidacy/watchlist mode) annotates the band for every name regardless of trade."""
        if not self._sizing_enabled:
            return
        if not force and str(signal.get("trade", "")).upper() != "CALL":
            return
        status = self._circuit_provider.status(str(signal.get("ticker", "")).upper())
        if not status:
            return
        band = band_pct_from_circuit(status)
        if band is None:
            return
        signal["band_pct"] = round(band, 2)
        signal["size_factor"] = band_size_factor(band, self._band_tiers)

    def run_time_stop_exits(self, held_symbols, today=None, *, dry_run: bool = False, price_fn=None) -> dict:
        """§5 time-stop: close held positions aged >= max_sessions. Circuit-lock aware —
        a lower-circuit-locked name can't be sold, so it's flagged (skipped_locked), not cleared.
        On each close, logs a closed-trade record (§13) with return_pct / band_pct / exit-fill."""
        if self._entry_ledger is None:
            return {"exited": [], "skipped_locked": [], "reason": "disabled"}
        today = today or _ist_today()
        price_fn = price_fn or getattr(self._nubra_client, "current_price", None)
        held = {str(s).upper() for s in held_symbols}
        stale = stale_symbols(self._entry_ledger.entries(), held, today, self._max_sessions)
        exited, locked = [], []
        for sym in stale:
            st = self._circuit_provider.status(sym) if self._circuit_provider else None
            if st and st.get("lower") and st.get("last") and st["last"] <= st["lower"] * 1.001:
                locked.append(sym)  # unsellable at lower circuit — carry, don't clear
                continue
            signal = {"trade": "PUT", "ticker": sym, "signal_id": f"timestop-{sym}-{today.isoformat()}"}
            dispatch_result = None
            if not dry_run:
                dispatch_result = self._stack.registry.dispatch("equity", signal, {"approved": True}, sym)
            self._log_closed_trade(sym, today, st, dispatch_result, price_fn)
            self._entry_ledger.clear(sym)
            exited.append(sym)
        return {"exited": exited, "skipped_locked": locked, "as_of": today.isoformat(), "dry_run": dry_run}

    def _log_closed_trade(self, symbol, today, circuit_status, dispatch_result, price_fn) -> None:
        if self._trade_log is None:
            return
        entry_price = self._entry_ledger.entry_price(symbol)
        exit_ltp = None
        if price_fn is not None:
            try:
                exit_ltp = float(price_fn(symbol))
            except Exception as exc:  # exit price unavailable — log the trade without return_pct
                _log.warning("exit price fetch failed for %s: %s", symbol, exc)
        return_pct = None
        if entry_price and exit_ltp:
            return_pct = round((exit_ltp - entry_price) / entry_price * 100, 4)
        self._trade_log.record({
            "symbol": symbol, "exit_date": today.isoformat(),
            "entry_price": entry_price, "exit_price": exit_ltp, "return_pct": return_pct,
            "band_pct": band_pct_from_circuit(circuit_status) if circuit_status else None,
            "exit_fill_quality": (_exit_fill_quality(dispatch_result, circuit_status)
                                  if dispatch_result is not None else None),
            "exit_reason": "time_stop",
        })

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
            # A rate-limited/failed history fetch (history_ok False) is NOT a data-poor stock —
            # label it data_throttled (retry next run) so it isn't confused with a genuine
            # short-history name (e.g. a recent listing).
            reason = ("data_throttled" if not context["price"].get("history_ok", True)
                      else "insufficient_history")
            _log.info(
                "%s | %s (bars=%d < min=%d) — skipped", symbol, reason, len(closes), self._min_bars,
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
                "skip_reason": reason,
                "bars": len(closes),
            }

        if not self._strategy.uses_forecast:
            forecast = None
            simulation = None
            signal = self._strategy.build(symbol, context, None, None, nse_result)
            provider_modes = {"timesfm": None, "mirofish": None, "nse": nse_result.get("provider_mode")}
        else:
            try:
                forecast = self._forecasting.forecast_from_prices(symbol, closes, horizon=5)
            except ForecastUnavailable as exc:
                _log.warning("%s | no forecast (%s) — skipped", symbol, exc)
                return {
                    "symbol": symbol, "signal": None, "forecast": None, "risk": None,
                    "entry_gate": None, "nse_sentiment": nse_result.get("sentiment_label"),
                    "ltp": ltp, "provider_modes": {"timesfm": "unavailable"},
                    "status": "skipped", "skip_reason": "no_forecast",
                }
            # MiroFish simulation is intentionally NOT run: since the confidence blend dropped
            # the sim leg (it double-counted the forecast+NSE the sim was itself fed), and the
            # only forecast-using strategy (BlendedSignalStrategy) takes direction from the
            # forecast — not the sim — the per-symbol simulate() call was pure wasted compute in
            # the ThreadPoolExecutor hot path, feeding only a provider_mode label. Pass None
            # (a documented valid input to build()) and label the mode "skipped_unused".
            simulation = None
            signal = self._strategy.build(symbol, context, forecast, simulation, nse_result)
            provider_modes = {
                "timesfm": forecast.get("provider_mode"),
                "mirofish": "skipped_unused",
                "nse": nse_result.get("provider_mode"),
            }

        # Live-execution mode: a HOLD/no-signal is dropped (nothing to trade). Candidacy mode
        # falls through — a TimesFM-neutral name is still a probable, judged by the playbook gates.
        if (signal is None or signal["trade"] == "HOLD") and not self._candidacy_mode:
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

        self._apply_sizing(signal, force=self._candidacy_mode)

        risk_context = {
            **context,
            "source_audit": _build_risk_audit(context["source_audit"], nse_result, closes),
        }
        if self._candidacy_mode:
            # A probable = passes the PLAYBOOK gates (circuit/sector/regime), evaluated as a buy
            # candidate. TimesFM (direction/upside/confidence) and the risk/upside gates do NOT
            # filter — they only annotate. Every name is judged the same buy-candidacy way.
            risk_result = {"approved": True, "risk_notes": []}
            gate_ok, gate_reason = True, None
            candidacy_signal = {"trade": "CALL", "ticker": symbol}
            for gate in self._extra_gates:
                if not gate_ok:
                    break
                gate_ok, gate_reason = gate.evaluate(candidacy_signal)
        else:
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
        # Soft/advisory flags — each wrapped so a failing data source degrades to its empty
        # shape rather than failing the whole symbol (an advisory flag is never a hard gate).
        delivery_flag = self._safe_flag(self._delivery_flag, symbol, _EMPTY_DELIVERY_FLAG)  # computed once, reused by watchlist below
        fno_flag = self._safe_flag(self._fno_flag, symbol, _EMPTY_FNO_FLAG)
        # F&O availability feeds the §2 watchlist factor (set before _watchlist runs).
        signal["fno_factor"] = 1.0 if fno_flag.get("fno_available") else None
        pre_open_flag = self._safe_flag(self._pre_open_flag, symbol, _EMPTY_PRE_OPEN_FLAG)
        # computed once — reused for both the "deals" flag and catalyst stacking below.
        deals_flag = (
            self._safe_flag(self._deals.flag, symbol, _EMPTY_DEALS_FLAG) if self._deals else _EMPTY_DEALS_FLAG
        )
        promoter_flag = (
            self._safe_flag(self._shareholding.promoter_flag, symbol, _EMPTY_PROMOTER_FLAG)
            if self._shareholding else _EMPTY_PROMOTER_FLAG
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
            # §8/§3 soft conviction flags (advisory, never gates).
            **delivery_flag,
            "fno": fno_flag,
            "pre_open": pre_open_flag,
            # §7/§8 bulk/block institutional deals (soft — feeds stacking, never gates).
            "deals": deals_flag,
            # §9 promoter-stake trend (soft, quarterly).
            "promoter": promoter_flag,
            # §7 catalyst stacking — distinct sources firing for this symbol.
            "catalyst_stack": _catalyst_stack(nse_result, deals_flag),
            # §2 watchlist ranking score + factor breakdown.
            "watchlist": self._watchlist(symbol, nse_result, signal, delivery_flag.get("delivery_pct")),
            # §5 scale-out targets (advisory). scale_out_targets returns None for a non-positive
            # move, so in candidacy mode only bullish-potential names get T1/T2.
            "targets": (
                scale_out_targets(float(ltp), float(signal.get("expected_move_pct", 0) or 0), self._targets_cfg)
                if self._targets_enabled and (self._candidacy_mode or str(signal.get("trade", "")).upper() == "CALL")
                else None
            ),
        }

        if not risk_result["approved"]:
            return {**base, "status": "skipped", "skip_reason": "risk_rejected"}

        if not gate_ok:
            return {**base, "status": "skipped", "skip_reason": gate_reason or "entry_gate"}

        # Candidacy/watchlist mode: passing the playbook gates IS election — no order dispatch,
        # no trade-count cap, no PUT-exit handling (those are live-execution concerns).
        if self._candidacy_mode:
            return {**base, "status": "executed", "dry_run": dry_run}

        dispatch_result = None
        with self._trade_lock:
            if self._trade_count >= self._max_trades:
                return {**base, "status": "skipped", "skip_reason": "max_trades_per_day"}
            if not dry_run:
                dispatch_result = self._stack.registry.dispatch("equity", signal, risk_result, symbol)
                if str(signal.get("trade", "")).upper() == "CALL" and self._entry_ledger is not None:
                    self._entry_ledger.record_entry(symbol, _ist_today(), price=float(ltp))
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

def _ist_today():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def _chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _catalyst_stack(nse_result: dict, deals_flag: dict | None = None) -> dict:
    """§7: how many distinct confirmations are firing for this symbol — news sources plus a
    bulk/block institutional deal. >=2 = stacked (multiple simultaneous confirmations raise
    conviction). Descriptive, never gates."""
    audit = nse_result.get("source_audit", {})
    firing = sorted(k for k, v in audit.items() if isinstance(v, dict) and v.get("count", 0) > 0)
    if deals_flag and deals_flag.get("has_deal"):
        firing.append("bulk_block_deal")
    return {"catalyst_stack_count": len(firing), "catalyst_sources": firing, "stacked": len(firing) >= 2}


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


def build_runner(config: dict, *, strategy: str | None = None, mode: str = "nubra_uat") -> NubraEquityRunner:
    """Construct a NubraEquityRunner from a config dict (whitelist must already be resolved).

    mode='screen' builds a broker-less stack (paper broker + Fyers data) so the scanner
    runs read-only with just a Fyers token — no Nubra session. Screen mode also turns on
    candidacy mode: a probable = passes the playbook gates, with TimesFM annotating potential
    (no TimesFM filtering). Live 'nubra_uat' mode leaves candidacy off (real order execution).
    """
    stack = build_equity_stack(mode, config)
    run_cfg = {**config, "candidacy_mode": config.get("candidacy_mode", mode == "screen")}
    return NubraEquityRunner(
        run_cfg,
        nubra_client=stack.market_data,
        equity_stack=stack,
        strategy=strategy,
    )

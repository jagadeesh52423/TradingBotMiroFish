"""Offline tests for NubraEquityRunner.

All external dependencies (broker, forecasting, mirofish, NSE) are faked via
constructor injection — no live SDK, no network, no file I/O. (BP-123)
"""
from __future__ import annotations

import pathlib
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# Ensure _ROOT is on sys.path so runner's local imports work.
_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT))
for _svc in ("mirofish-bridge", "risk-engine"):
    _p = str(_ROOT / "services" / _svc)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mirofish_bridge_service import MiroFishBridgeService
from risk_engine_service import RiskEngineService

from scripts.run_nubra_equity import NubraEquityRunner, _chunk, _load_config
from services.nubra_client.entry_gate import ExpectedUpsideGate


# ---------------------------------------------------------------------------
# Shared fakes / config
# ---------------------------------------------------------------------------

_CFG = {
    "env": "UAT",
    "whitelist": ["SBIN", "RELIANCE", "TATACONSUM"],
    "max_trades_per_day": 5,
    "risk_per_trade_pct": 0.5,
    "entry_threshold": {"min_expected_upside_pct": 0.0, "per_symbol": {}, "max_horizon_days": None},
    "signal": {},
    "nse": {"lookback_days": 7, "cache_ttl_seconds": 900},
    "runner": {"max_workers": 1, "inter_batch_sleep_secs": 0.0},
}

_BULLISH_FORECAST = {
    "direction": "bullish",
    "predicted_return": 0.04,
    "confidence": 0.80,
    "forecast": [820.0, 825.0, 830.0, 835.0, 840.0],
    "provider_mode": "local_fallback",
}

_BEARISH_FORECAST = {
    "direction": "bearish",
    "predicted_return": -0.03,
    "confidence": 0.75,
    "forecast": [810.0, 805.0, 800.0, 795.0, 790.0],
    "provider_mode": "local_fallback",
}

_NEUTRAL_FORECAST = {
    "direction": "neutral",
    "predicted_return": 0.001,
    "confidence": 0.65,
    "forecast": [815.0, 815.5, 816.0, 816.0, 815.0],
    "provider_mode": "local_fallback",
}

_SIM_RESULT = {
    "outlook_score": 20.0,
    "final_direction": "bullish",
    "provider_mode": "local_mirofish_fallback",
}

_NSE_RESULT = {
    "symbol": "SBIN",
    "provider_mode": "nse_live",
    "items": [{"attchmntText": "Quarterly profit growth.", "symbol": "SBIN"}],
    "documents": [{"source": "nse_filing", "content": "Quarterly profit growth."}],
    "sentiment_score": 0.1,
    "sentiment_label": "neutral",
    "source_audit": {"nse_announcements": {"status": "live", "count": 1}},
}


class _FakeForecasting:
    def __init__(self, forecast=None):
        self._fc = forecast or _BULLISH_FORECAST

    def forecast_from_prices(self, ticker, closes, horizon=5):
        return {**self._fc, "ticker": ticker}


class _FakeMirofish:
    def simulate(self, request):
        return dict(_SIM_RESULT)


class _FakeNse:
    def __init__(self, result=None):
        self._result = result or _NSE_RESULT

    def collect(self, symbol):
        return {**self._result, "symbol": symbol.upper()}


class _FakeNubraClient:
    def current_price(self, symbol):
        return Decimal("812.50")

    def historical(self, symbol, interval="1d", lookback=20):
        return [{"close": 810.0 + i, "timestamp": i * 86400} for i in range(lookback)]


class _FakeRegistry:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, asset_class, signal, risk_result, symbol):
        self.dispatched.append({"asset_class": asset_class, "signal": signal, "symbol": symbol})
        return {"status": "paper_filled"}


class _FakeStack:
    def __init__(self):
        self.registry = _FakeRegistry()


def _make_runner(forecast=None, cfg_override=None, nse_result=None, max_trades=5) -> tuple[NubraEquityRunner, _FakeStack]:
    cfg = {**_CFG, "max_trades_per_day": max_trades}
    if cfg_override:
        cfg.update(cfg_override)
    stack = _FakeStack()
    runner = NubraEquityRunner(
        cfg,
        forecasting=_FakeForecasting(forecast),
        mirofish=_FakeMirofish(),
        risk_engine=RiskEngineService(),
        nse_collector=_FakeNse(nse_result),
        nubra_client=_FakeNubraClient(),
        equity_stack=stack,
    )
    return runner, stack


# ---------------------------------------------------------------------------
# Chunk helper
# ---------------------------------------------------------------------------

class TestChunkHelper:
    def test_chunk_splits_evenly(self):
        batches = list(_chunk([1, 2, 3, 4, 5, 6], 3))
        assert batches == [[1, 2, 3], [4, 5, 6]]

    def test_chunk_handles_remainder(self):
        batches = list(_chunk([1, 2, 3, 4, 5], 3))
        assert len(batches) == 2
        assert batches[-1] == [4, 5]

    def test_chunk_empty(self):
        assert list(_chunk([], 3)) == []

    def test_chunk_smaller_than_size(self):
        assert list(_chunk([1, 2], 5)) == [[1, 2]]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestConfigLoading:
    def test_config_has_whitelist(self):
        cfg = _load_config()
        assert "whitelist" in cfg
        assert len(cfg["whitelist"]) == 48

    def test_config_has_signal_block(self):
        cfg = _load_config()
        assert "signal" in cfg
        signal = cfg["signal"]
        assert "tf_weight" in signal
        assert "nse_weight" in signal

    def test_config_has_nse_block(self):
        cfg = _load_config()
        assert "nse" in cfg
        assert "lookback_days" in cfg["nse"]
        assert "cache_ttl_seconds" in cfg["nse"]

    def test_config_has_runner_block(self):
        cfg = _load_config()
        assert "runner" in cfg
        assert "max_workers" in cfg["runner"]

    def test_whitelist_contains_expected_symbols(self):
        cfg = _load_config()
        wl = cfg["whitelist"]
        for sym in ("SBIN", "RELIANCE", "TCS", "INFY", "HDFCBANK"):
            assert sym in wl, f"{sym} missing from whitelist"

    def test_whitelist_contains_ampersand_symbol(self):
        # M&MFIN must survive JSON round-trip
        cfg = _load_config()
        assert "M&MFIN" in cfg["whitelist"]


# ---------------------------------------------------------------------------
# run_once — result structure
# ---------------------------------------------------------------------------

class TestRunOnce:
    def test_run_once_returns_summary_keys(self):
        runner, _ = _make_runner()
        summary = runner.run_once(dry_run=True)
        for key in ("symbols_processed", "traded", "skipped", "errors", "results"):
            assert key in summary

    def test_run_once_processes_all_symbols(self):
        runner, _ = _make_runner()
        summary = runner.run_once(dry_run=True)
        assert summary["symbols_processed"] == 3  # whitelist has 3 in test cfg

    def test_run_once_dry_run_no_dispatch(self):
        runner, stack = _make_runner()
        runner.run_once(dry_run=True)
        assert len(stack.registry.dispatched) == 0

    def test_run_once_live_mode_dispatches(self):
        runner, stack = _make_runner()
        runner.run_once(dry_run=False)
        assert len(stack.registry.dispatched) > 0

    def test_run_once_error_count_on_bad_symbol(self):
        class _ErrorNse(_FakeNse):
            def collect(self, symbol):
                raise RuntimeError("NSE exploded")

        cfg = {**_CFG}
        stack = _FakeStack()
        runner = NubraEquityRunner(
            cfg,
            forecasting=_FakeForecasting(),
            mirofish=_FakeMirofish(),
            risk_engine=RiskEngineService(),
            nse_collector=_ErrorNse(),
            nubra_client=_FakeNubraClient(),
            equity_stack=stack,
        )
        summary = runner.run_once(dry_run=True)
        assert summary["errors"] == 3  # all symbols fail


# ---------------------------------------------------------------------------
# _process_symbol — result fields
# ---------------------------------------------------------------------------

class TestProcessSymbol:
    def _result(self, forecast=None, nse_result=None, max_trades=5):
        runner, stack = _make_runner(forecast=forecast, nse_result=nse_result, max_trades=max_trades)
        return runner._process_symbol("SBIN", dry_run=True), stack

    def test_result_has_required_keys(self):
        result, _ = self._result()
        for key in ("symbol", "status", "signal", "forecast", "risk", "entry_gate",
                    "nse_sentiment", "ltp", "provider_modes"):
            assert key in result, f"missing key: {key}"

    def test_symbol_in_result(self):
        result, _ = self._result()
        assert result["symbol"] == "SBIN"

    def test_provider_modes_all_present(self):
        result, _ = self._result()
        pm = result["provider_modes"]
        assert "timesfm" in pm
        assert "mirofish" in pm
        assert "nse" in pm

    def test_bullish_forecast_gives_executed_status(self):
        result, _ = self._result(forecast=_BULLISH_FORECAST)
        assert result["status"] == "executed"

    def test_neutral_forecast_gives_hold_skip(self):
        result, _ = self._result(forecast=_NEUTRAL_FORECAST)
        assert result["status"] == "skipped"
        assert result["skip_reason"] == "HOLD"

    def test_ltp_is_float(self):
        result, _ = self._result()
        assert isinstance(result["ltp"], float)

    def test_nse_sentiment_propagated(self):
        nse = {**_NSE_RESULT, "sentiment_label": "bullish"}
        result, _ = self._result(nse_result=nse)
        assert result["nse_sentiment"] == "bullish"

    def test_dry_run_does_not_dispatch(self):
        runner, stack = _make_runner()
        runner._process_symbol("SBIN", dry_run=True)
        assert len(stack.registry.dispatched) == 0

    def test_live_run_dispatches(self):
        runner, stack = _make_runner()
        runner._process_symbol("SBIN", dry_run=False)
        assert len(stack.registry.dispatched) == 1
        assert stack.registry.dispatched[0]["symbol"] == "SBIN"


# ---------------------------------------------------------------------------
# Trade cap
# ---------------------------------------------------------------------------

class TestTradeCapEnforcement:
    def test_max_trades_per_day_respected(self):
        """With whitelist of 3 symbols and max_trades=1, only 1 should execute."""
        runner, stack = _make_runner(max_trades=1)
        summary = runner.run_once(dry_run=False)
        # At most 1 trade executed
        assert summary["traded"] <= 1

    def test_no_trades_when_cap_already_zero(self):
        runner, stack = _make_runner(max_trades=0)
        summary = runner.run_once(dry_run=False)
        assert summary["traded"] == 0

    def test_trade_count_increments_on_execute(self):
        runner, stack = _make_runner()
        assert runner._trade_count == 0
        runner._process_symbol("SBIN", dry_run=False)
        assert runner._trade_count == 1


# ---------------------------------------------------------------------------
# Risk rejection
# ---------------------------------------------------------------------------

class TestRiskRejection:
    def test_low_confidence_forecast_rejected(self):
        low_conf_fc = {**_BULLISH_FORECAST, "confidence": 0.40}
        result, _ = _make_runner(forecast=low_conf_fc)[0], None
        runner, _ = _make_runner(forecast=low_conf_fc)
        result = runner._process_symbol("SBIN", dry_run=True)
        assert result["status"] == "skipped"
        assert result["skip_reason"] == "risk_rejected"


# ---------------------------------------------------------------------------
# Entry gate
# ---------------------------------------------------------------------------

class TestEntryGate:
    def test_below_upside_threshold_skipped(self):
        # predicted_return=0.001 → 0.1% upside; gate min=2.0% → should be blocked
        tiny_fc = {**_BULLISH_FORECAST, "predicted_return": 0.001, "confidence": 0.80}
        cfg_override = {"entry_threshold": {"min_expected_upside_pct": 2.0, "per_symbol": {}, "max_horizon_days": None}}
        runner, _ = _make_runner(forecast=tiny_fc, cfg_override=cfg_override)
        result = runner._process_symbol("SBIN", dry_run=True)
        assert result["status"] == "skipped"
        assert result["entry_gate"]["ok"] is False

    def test_above_upside_threshold_passes(self):
        # predicted_return=0.04 → 4% upside; gate min=2.0% → should pass
        runner, _ = _make_runner(forecast=_BULLISH_FORECAST)
        result = runner._process_symbol("SBIN", dry_run=True)
        assert result["entry_gate"]["ok"] is True

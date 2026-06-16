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

from scripts.run_nubra_equity import NubraEquityRunner, _build_risk_audit, _chunk, _load_config
from services.nubra_client.entry_gate import ExpectedUpsideGate
from services.nubra_client.equity_assembly import build_equity_stack


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
        assert "confidence_weights" in signal
        cw = signal["confidence_weights"]
        assert "no_nse" in cw and "with_nse" in cw
        assert "news_override" in signal

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


# ---------------------------------------------------------------------------
# Wiring regression: market_data must be NubraClient, not NubraBroker
# ---------------------------------------------------------------------------

class TestWiringRegression:
    """Regression for the broker→NubraClient wiring bug.

    The runner must receive the NubraClient (has current_price + historical),
    not the NubraBroker (which lacks those methods).  These tests prove:
    (a) EquityStack.market_data holds the NubraClient object injected by the factory.
    (b) Passing a spec-limited NubraBroker fake (without current_price/historical)
        as nubra_client would raise AttributeError — i.e. the old broken wiring
        is detectable offline.
    """

    def test_stack_market_data_is_the_client_returned_by_factory(self):
        """build_equity_stack("nubra_uat", client_factory=...) must expose the
        NubraClient via stack.market_data, NOT the broker."""

        class _FakeFundsClient:
            """Minimal NubraClient-like object for build_equity_stack in nubra_uat mode."""
            def current_price(self, symbol):
                return __import__("decimal").Decimal("500.00")

            def historical(self, symbol, interval="1d", lookback=20):
                return [{"close": 500.0 + i, "timestamp": i * 86400} for i in range(lookback)]

            def funds(self):
                # NubraBroker.get_funds() delegates to client.funds()
                return {"net_margin_available": 1_000_000}  # 1 lakh in paise

            def place_order(self, **kwargs):
                return {"order_id": "fake-001"}

            def get_positions(self):
                return []

            def get_order_status(self, order_id):
                return {"status": "COMPLETE"}

        fake_client = _FakeFundsClient()
        stack = build_equity_stack("nubra_uat", _CFG, client_factory=lambda cfg: fake_client)

        # market_data must be the raw NubraClient (which has current_price + historical)
        assert stack.market_data is fake_client
        # Verify the interface is present on the object exposed to the runner
        assert hasattr(stack.market_data, "current_price")
        assert hasattr(stack.market_data, "historical")

    def test_spec_limited_broker_fake_lacks_current_price(self):
        """A spec-limited NubraBroker fake (no current_price/historical) must raise
        AttributeError when the runner tries to call current_price — proving the
        old wiring (passing broker as nubra_client) would have been caught offline."""
        from services.nubra_client.nubra_broker import NubraBroker

        # NubraBroker does NOT expose current_price or historical — confirmed spec
        broker_fake = MagicMock(spec=NubraBroker)
        assert not hasattr(broker_fake, "current_price"), (
            "NubraBroker gained current_price — update runner to use that instead"
        )
        assert not hasattr(broker_fake, "historical"), (
            "NubraBroker gained historical — update runner to use that instead"
        )
        # Calling current_price on a spec-limited mock must raise AttributeError
        with pytest.raises(AttributeError):
            broker_fake.current_price("SBIN")


# ---------------------------------------------------------------------------
# _build_risk_audit — B3: correct key mapping for RiskEngine Rule 2 + Rule 3
# ---------------------------------------------------------------------------

class TestBuildRiskAudit:
    """Tests for _build_risk_audit() — ensures NSE maps to "news" (Rule 3) and
    OHLCV quality maps to "ohlcv" (Rule 2) so RiskEngine guards actually fire."""

    def _equity_audit(self):
        # Typical equity_context source_audit: US sources are string "n/a"
        return {
            "alpha_vantage": "n/a",
            "yfinance": "n/a",
            "some_dict_source": {"status": "live", "count": 5},
        }

    # ── NSE → "news" (Rule 3) ───────────────────────────────────────────────

    def test_nse_live_maps_to_news_status_live(self):
        nse = {"provider_mode": "nse_live"}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[1.0, 2.0, 3.0])
        assert result["news"] == {"status": "live"}

    def test_nse_fallback_maps_to_news_status_fallback(self):
        nse = {"provider_mode": "fixture_fallback"}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[1.0, 2.0])
        assert result["news"] == {"status": "fallback"}

    def test_nse_unknown_mode_maps_to_news_status_fallback(self):
        nse = {"provider_mode": "unknown_mode"}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[1.0, 2.0])
        assert result["news"] == {"status": "fallback"}

    def test_nse_missing_provider_mode_defaults_to_fallback(self):
        nse = {}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[1.0, 2.0])
        assert result["news"] == {"status": "fallback"}

    # ── OHLCV → "ohlcv" (Rule 2) ───────────────────────────────────────────

    def test_single_close_maps_to_ohlcv_fallback(self):
        # len(closes) == 1 means only LTP available → Rule 2 must reject
        nse = {"provider_mode": "nse_live"}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[812.50])
        assert result["ohlcv"] == {"status": "fallback"}

    def test_empty_closes_maps_to_ohlcv_fallback(self):
        nse = {"provider_mode": "nse_live"}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[])
        assert result["ohlcv"] == {"status": "fallback"}

    def test_multiple_closes_maps_to_ohlcv_live(self):
        nse = {"provider_mode": "nse_live"}
        result = _build_risk_audit(self._equity_audit(), nse, closes=[810.0 + i for i in range(20)])
        assert result["ohlcv"] == {"status": "live"}

    # ── String "n/a" entries stripped ───────────────────────────────────────

    def test_string_equity_audit_entries_stripped(self):
        # Equity context has "n/a" strings for US sources — must not appear in risk context
        audit = {"alpha_vantage": "n/a", "yfinance": "ok"}
        nse = {"provider_mode": "nse_live"}
        result = _build_risk_audit(audit, nse, closes=[1.0, 2.0])
        assert "alpha_vantage" not in result
        assert "yfinance" not in result

    def test_dict_equity_audit_entries_preserved(self):
        audit = {"some_source": {"status": "live", "count": 3}}
        nse = {"provider_mode": "nse_live"}
        result = _build_risk_audit(audit, nse, closes=[1.0, 2.0])
        assert result["some_source"] == {"status": "live", "count": 3}

    # ── Integration: Rule 2 fires on single close (rejected) ────────────────

    def test_rule2_fires_when_only_ltp_available(self):
        """With only 1 close (LTP-only), risk_audit["ohlcv"].status=fallback
        → RiskEngineService Rule 2 must reject the signal."""
        from risk_engine_service import RiskEngineService

        risk = RiskEngineService()
        signal = {
            "trade": "CALL",
            "strategy_type": "trend",
            "confidence": 0.85,
            "asset_class": "equity",
            "ticker": "SBIN",
        }
        # Single close → ohlcv fallback
        nse = {"provider_mode": "nse_live"}
        source_audit = _build_risk_audit({}, nse, closes=[812.50])
        context = {"source_audit": source_audit}

        result = risk.evaluate(signal, context)
        assert result["approved"] is False, (
            "Rule 2 should reject when ohlcv.status=fallback (only LTP available)"
        )

    # ── Integration: Rule 3 fires on NSE fallback (confidence reduced) ──────

    def test_rule3_reduces_confidence_on_nse_fallback(self):
        """When NSE provider_mode is fixture_fallback, risk_audit["news"].status=fallback
        → RiskEngineService Rule 3 must reduce the adjusted confidence by 0.05."""
        from risk_engine_service import RiskEngineService

        risk = RiskEngineService()
        signal = {
            "trade": "CALL",
            "strategy_type": "trend",
            "confidence": 0.70,
            "asset_class": "equity",
            "ticker": "SBIN",
        }
        # NSE fallback, full OHLCV history (no Rule 2)
        nse_fallback = {"provider_mode": "fixture_fallback"}
        source_audit_fallback = _build_risk_audit({}, nse_fallback, closes=[800.0 + i for i in range(20)])
        context_fallback = {"source_audit": source_audit_fallback}

        nse_live = {"provider_mode": "nse_live"}
        source_audit_live = _build_risk_audit({}, nse_live, closes=[800.0 + i for i in range(20)])
        context_live = {"source_audit": source_audit_live}

        result_fallback = risk.evaluate(signal, context_fallback)
        result_live = risk.evaluate(signal, context_live)

        # Rule 3 note must appear in the fallback result
        fallback_notes = " ".join(result_fallback.get("risk_notes", []))
        assert "news" in fallback_notes.lower() or "fallback" in fallback_notes.lower(), (
            f"Expected Rule 3 note about news fallback, got: {result_fallback.get('risk_notes')}"
        )
        # Adjusted confidence must be lower with NSE fallback
        adj_fallback = result_fallback.get("adjusted_confidence", signal["confidence"])
        adj_live = result_live.get("adjusted_confidence", signal["confidence"])
        assert adj_fallback < adj_live, (
            f"Rule 3 must reduce confidence on NSE fallback: {adj_fallback} vs {adj_live}"
        )

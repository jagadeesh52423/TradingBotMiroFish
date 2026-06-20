"""Offline tests for signal_strategies module.

Covers:
  - NewsOnlySignalStrategy: direction, confidence, expected_move, reasoning
  - BlendedSignalStrategy: delegates to EquitySignalBuilder unchanged
  - Strategy registry: get_strategy(), unknown-name error
  - Runner honours config + --strategy; news_only bypasses thin-history guard

No live SDK, no network.  All assertions derive from the SPEC (BP-123).
"""
from __future__ import annotations

import math
import pathlib
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.nubra_client.signal_strategies import (
    BlendedSignalStrategy,
    NewsOnlySignalStrategy,
    SignalStrategy,
    _REGISTRY,
    _extract_subjects,
    get_strategy,
)

# Make sure runner + bridge/risk services are importable for runner-level tests.
_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT))
for _svc in ("mirofish-bridge", "risk-engine"):
    _p = str(_ROOT / "services" / _svc)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from risk_engine_service import RiskEngineService
from scripts.run_nubra_equity import NubraEquityRunner
from services.nubra_client.entry_gate import ExpectedUpsideGate


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _nse(
    sentiment_score: float = 0.3,
    items: list[dict] | None = None,
    provider_mode: str = "nse_live",
) -> dict:
    if items is None:
        items = [
            {"desc": "Quarterly Results", "attchmntText": "Company reports profit growth."},
            {"desc": "Order Win", "attchmntText": "Order awarded to the company."},
        ]
    return {
        "symbol": "SBIN",
        "provider_mode": provider_mode,
        "items": items,
        "documents": [],
        "sentiment_score": round(sentiment_score, 4),
        "sentiment_label": "bullish" if sentiment_score > 0.1 else ("bearish" if sentiment_score < -0.1 else "neutral"),
        "source_audit": {"nse_announcements": {"status": "live", "count": len(items)}},
    }


def _nse_empty() -> dict:
    return _nse(sentiment_score=0.0, items=[])


def _cfg_with_news_only(**overrides) -> dict:
    base = {
        "entry_threshold": {"min_expected_upside_pct": 2.0, "per_symbol": {}, "max_horizon_days": None},
        "signal": {
            "news_only": {
                "buy_threshold": 0.15,
                "sell_threshold": -0.15,
                "min_filings": 1,
            }
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

class TestStrategyRegistry:
    def test_blended_in_registry(self):
        assert "blended" in _REGISTRY

    def test_news_only_in_registry(self):
        assert "news_only" in _REGISTRY

    def test_get_strategy_blended_returns_blended_instance(self):
        strategy = get_strategy("blended", {})
        assert isinstance(strategy, BlendedSignalStrategy)

    def test_get_strategy_news_only_returns_news_only_instance(self):
        strategy = get_strategy("news_only", {})
        assert isinstance(strategy, NewsOnlySignalStrategy)

    def test_get_strategy_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown signal strategy"):
            get_strategy("magic_strategy", {})

    def test_signal_strategy_is_abstract(self):
        # Cannot instantiate the ABC directly.
        with pytest.raises(TypeError):
            SignalStrategy()  # type: ignore[abstract]

    def test_get_strategy_empty_config_gives_defaults(self):
        strategy = get_strategy("news_only", {})
        assert isinstance(strategy, NewsOnlySignalStrategy)


# ---------------------------------------------------------------------------
# NewsOnlySignalStrategy — trade direction
# ---------------------------------------------------------------------------

class TestNewsOnlyDirection:
    """Spec: CALL when sentiment ≥ buy_threshold AND filing_count ≥ min_filings."""

    def _strategy(self, **news_only_overrides) -> NewsOnlySignalStrategy:
        cfg = _cfg_with_news_only()
        cfg["signal"]["news_only"].update(news_only_overrides)
        return get_strategy("news_only", cfg)  # type: ignore[return-value]

    def test_bullish_sentiment_with_filings_gives_call(self):
        strategy = self._strategy()
        nse = _nse(sentiment_score=0.3, items=[{"desc": "Profit Update", "attchmntText": "profit"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "CALL"

    def test_bullish_sentiment_at_buy_threshold_gives_call(self):
        strategy = self._strategy(buy_threshold=0.15)
        nse = _nse(sentiment_score=0.15, items=[{"desc": "Results", "attchmntText": "ok"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "CALL"

    def test_bullish_sentiment_below_threshold_gives_hold(self):
        # sentiment=0.10 < buy_threshold=0.15 → HOLD
        strategy = self._strategy(buy_threshold=0.15)
        nse = _nse(sentiment_score=0.10, items=[{"desc": "Update", "attchmntText": "ok"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "HOLD"

    def test_bearish_sentiment_gives_put(self):
        strategy = self._strategy(sell_threshold=-0.15)
        nse = _nse(sentiment_score=-0.3, items=[{"desc": "Penalty", "attchmntText": "penalty"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "PUT"

    def test_bearish_sentiment_at_sell_threshold_gives_put(self):
        strategy = self._strategy(sell_threshold=-0.15)
        nse = _nse(sentiment_score=-0.15, items=[{"desc": "Loss", "attchmntText": "loss"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "PUT"

    def test_neutral_sentiment_gives_hold(self):
        strategy = self._strategy()
        nse = _nse(sentiment_score=0.05, items=[{"desc": "AGM", "attchmntText": "meeting"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "HOLD"

    def test_zero_sentiment_gives_hold(self):
        strategy = self._strategy()
        nse = _nse(sentiment_score=0.0, items=[])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "HOLD"

    def test_bullish_sentiment_insufficient_filings_gives_hold(self):
        # min_filings=2 but only 1 item → HOLD even if score is bullish
        strategy = self._strategy(min_filings=2)
        nse = _nse(sentiment_score=0.5, items=[{"desc": "Results", "attchmntText": "profit"}])
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "HOLD"

    def test_bullish_sentiment_exactly_min_filings_gives_call(self):
        # min_filings=2, exactly 2 items → CALL
        strategy = self._strategy(min_filings=2)
        items = [
            {"desc": "Results", "attchmntText": "profit"},
            {"desc": "Dividend", "attchmntText": "dividend"},
        ]
        nse = _nse(sentiment_score=0.5, items=items)
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal is not None
        assert signal["trade"] == "CALL"

    def test_nse_result_none_returns_none(self):
        strategy = self._strategy()
        result = strategy.build("SBIN", {}, None, None, None)
        assert result is None


# ---------------------------------------------------------------------------
# NewsOnlySignalStrategy — signal fields
# ---------------------------------------------------------------------------

class TestNewsOnlySignalFields:
    def _bullish_signal(self) -> dict:
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        nse = _nse(sentiment_score=0.4)
        return strategy.build("SBIN", {}, None, None, nse)

    def test_asset_class_is_equity(self):
        assert self._bullish_signal()["asset_class"] == "equity"

    def test_strategy_type_is_trend(self):
        # Caveat C: must not be "no_trade" or RiskEngine Rule 4 rejects
        assert self._bullish_signal()["strategy_type"] == "trend"

    def test_ticker_is_upper(self):
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("sbin", {}, None, None, _nse(0.4))
        assert signal["ticker"] == "SBIN"

    def test_horizon_is_1d(self):
        assert self._bullish_signal()["horizon"] == "1d"

    def test_signal_id_is_unique_per_call(self):
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        nse = _nse(0.4)
        sig_a = strategy.build("SBIN", {}, None, None, nse)
        sig_b = strategy.build("SBIN", {}, None, None, nse)
        assert sig_a["signal_id"] != sig_b["signal_id"]

    def test_signal_has_reasoning_field(self):
        sig = self._bullish_signal()
        assert "reasoning" in sig

    def test_reasoning_lists_subjects(self):
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        items = [
            {"desc": "Quarterly Results", "attchmntText": "strong profit"},
            {"desc": "Order Win", "attchmntText": "order awarded"},
        ]
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4, items=items))
        assert "Quarterly Results" in signal["reasoning"]
        assert "Order Win" in signal["reasoning"]


# ---------------------------------------------------------------------------
# NewsOnlySignalStrategy — expected_move_pct clears the entry gate
# ---------------------------------------------------------------------------

class TestNewsOnlyExpectedMove:
    """expected_move_pct for CALL must clear ExpectedUpsideGate; HOLD/PUT must be 0."""

    def test_call_expected_move_clears_gate(self):
        # gate min = 2.0%; expected_move_pct must be >= 0.02 for gate to pass
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        nse = _nse(sentiment_score=0.4)
        signal = strategy.build("SBIN", {}, None, None, nse)

        gate = ExpectedUpsideGate({"min_expected_upside_pct": 2.0})
        gate_ok, reason = gate.evaluate(signal)
        assert gate_ok, f"Gate should pass for news_only CALL: {reason}"

    def test_hold_expected_move_is_zero(self):
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        nse = _nse(sentiment_score=0.05)  # below buy_threshold → HOLD
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal["expected_move_pct"] == 0.0

    def test_put_expected_move_is_zero(self):
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        nse = _nse(sentiment_score=-0.4)
        signal = strategy.build("SBIN", {}, None, None, nse)
        assert signal["expected_move_pct"] == 0.0

    def test_expected_move_equals_min_upside_as_fraction(self):
        # entry_threshold.min_expected_upside_pct = 3.0 → expected_move_pct = 0.03
        cfg = _cfg_with_news_only()
        cfg["entry_threshold"]["min_expected_upside_pct"] = 3.0
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4))
        assert signal["expected_move_pct"] == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# NewsOnlySignalStrategy — confidence scaling
# ---------------------------------------------------------------------------

class TestNewsOnlyConfidence:
    """Confidence must be in [0,1] and increase with stronger sentiment + more filings."""

    def _conf(self, sentiment_score: float, n_items: int = 1) -> float:
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        items = [{"desc": "Item", "attchmntText": "text"}] * n_items
        nse = _nse(sentiment_score=sentiment_score, items=items)
        signal = strategy.build("SBIN", {}, None, None, nse)
        return signal["confidence"]

    def test_confidence_clamped_between_0_and_1(self):
        conf = self._conf(1.0, n_items=10)
        assert 0.0 <= conf <= 1.0

    def test_zero_sentiment_gives_low_confidence(self):
        assert self._conf(0.0, n_items=1) < 0.5

    def test_stronger_sentiment_gives_higher_confidence(self):
        assert self._conf(0.8) > self._conf(0.3)

    def test_more_filings_gives_higher_confidence(self):
        # Same sentiment, more filings → higher confidence
        conf_few = self._conf(0.4, n_items=1)
        conf_many = self._conf(0.4, n_items=5)
        assert conf_many > conf_few

    def test_confidence_is_rounded_to_4dp(self):
        conf = self._conf(0.35, n_items=2)
        assert conf == round(conf, 4)

    def test_default_confidence_formula_matches_spec(self):
        """Verify the formula: 0.7*abs(score) + 0.3*(log1p(filings)/log1p(5)), clamped."""
        cfg = _cfg_with_news_only()
        strategy = get_strategy("news_only", cfg)
        score = 0.5
        n = 3
        score_comp = abs(score)
        filing_comp = min(1.0, math.log1p(n) / math.log1p(5))
        expected = round(min(1.0, max(0.0, 0.7 * score_comp + 0.3 * filing_comp)), 4)
        items = [{"desc": "Item", "attchmntText": "text"}] * n
        signal = strategy.build("SBIN", {}, None, None, _nse(score, items=items))
        assert signal["confidence"] == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# BlendedSignalStrategy — delegates to EquitySignalBuilder, behaviour unchanged
# ---------------------------------------------------------------------------

class TestBlendedStrategyDelegation:
    """BlendedSignalStrategy must produce the same output as EquitySignalBuilder directly."""

    def _fc(self, direction="bullish", confidence=0.72, predicted_return=0.03):
        return {
            "direction": direction,
            "predicted_return": predicted_return,
            "confidence": confidence,
            "forecast": [812.5, 820.0, 825.0, 828.0, 830.0],
        }

    def _sim(self, outlook_score=10.5):
        return {
            "outlook_score": outlook_score,
            "final_direction": "bullish",
            "provider_mode": "local_mirofish_fallback",
        }

    def test_blended_bullish_gives_call(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("SBIN", {}, self._fc("bullish"), self._sim(), None)
        assert signal["trade"] == "CALL"

    def test_blended_bearish_gives_put(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("SBIN", {}, self._fc("bearish"), self._sim(), None)
        assert signal["trade"] == "PUT"

    def test_blended_neutral_gives_hold(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("SBIN", {}, self._fc("neutral"), self._sim(), None)
        assert signal["trade"] == "HOLD"

    def test_blended_ticker_upper(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("sbin", {}, self._fc(), self._sim(), None)
        assert signal["ticker"] == "SBIN"

    def test_blended_asset_class_is_equity(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("SBIN", {}, self._fc(), self._sim(), None)
        assert signal["asset_class"] == "equity"

    def test_blended_strategy_type_is_trend(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("SBIN", {}, self._fc(), self._sim(), None)
        assert signal["strategy_type"] == "trend"

    def test_blended_uses_forecast_predicted_return(self):
        strategy = get_strategy("blended", {})
        signal = strategy.build("SBIN", {}, self._fc(predicted_return=0.05), self._sim(), None)
        assert signal["expected_move_pct"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Runner — strategy wiring from config and --strategy CLI arg
# ---------------------------------------------------------------------------

# Re-use fake helpers from test_run_nubra_equity style
_BASE_CFG = {
    "env": "UAT",
    "whitelist": ["SBIN", "RELIANCE"],
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


class _FakeForecasting:
    def forecast_from_prices(self, ticker, closes, horizon=5):
        return {**_BULLISH_FORECAST, "ticker": ticker}


class _FakeMirofish:
    def simulate(self, request):
        return {"outlook_score": 20.0, "final_direction": "bullish", "provider_mode": "local_mirofish_fallback"}


class _FakeNse:
    def __init__(self, result=None):
        self._result = result or {
            "symbol": "SBIN",
            "provider_mode": "nse_live",
            "items": [{"desc": "Quarterly Results", "attchmntText": "profit growth"}],
            "documents": [],
            "sentiment_score": 0.3,
            "sentiment_label": "bullish",
            "source_audit": {"nse_announcements": {"status": "live", "count": 1}},
        }

    def collect(self, symbol):
        return {**self._result, "symbol": symbol.upper()}


class _FakeNubraClient:
    def __init__(self, n_bars: int = 20):
        self._n = n_bars

    def current_price(self, symbol):
        return Decimal("812.50")

    def historical(self, symbol, interval="1d", lookback=20):
        return [{"close": 810.0 + i, "timestamp": i * 86400} for i in range(self._n)]


class _FakeRegistry:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, asset_class, signal, risk_result, symbol):
        self.dispatched.append(symbol)
        return {"status": "paper_filled"}


class _FakeStack:
    def __init__(self):
        self.registry = _FakeRegistry()


def _make_runner(
    strategy: str | None = None,
    n_bars: int = 20,
    cfg_overrides: dict | None = None,
    nse_result=None,
) -> tuple[NubraEquityRunner, _FakeStack]:
    cfg = dict(_BASE_CFG)
    if cfg_overrides:
        cfg.update(cfg_overrides)
    stack = _FakeStack()
    runner = NubraEquityRunner(
        cfg,
        forecasting=_FakeForecasting(),
        mirofish=_FakeMirofish(),
        risk_engine=RiskEngineService(),
        nse_collector=_FakeNse(nse_result),
        nubra_client=_FakeNubraClient(n_bars),
        equity_stack=stack,
        strategy=strategy,
    )
    return runner, stack


class TestRunnerStrategyWiring:
    def test_default_strategy_is_blended(self):
        runner, _ = _make_runner()
        assert runner._strategy_name == "blended"

    def test_config_strategy_overrides_default(self):
        runner, _ = _make_runner(cfg_overrides={"signal": {"strategy": "news_only"}})
        assert runner._strategy_name == "news_only"

    def test_cli_strategy_overrides_config(self):
        cfg = {"signal": {"strategy": "blended"}}
        runner, _ = _make_runner(strategy="news_only", cfg_overrides=cfg)
        assert runner._strategy_name == "news_only"

    def test_unknown_strategy_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown signal strategy"):
            _make_runner(strategy="nonexistent")

    def test_blended_mode_processes_symbols(self):
        runner, _ = _make_runner(strategy="blended", n_bars=20)
        summary = runner.run_once(dry_run=True)
        assert summary["symbols_processed"] == 2

    def test_news_only_mode_processes_symbols(self):
        runner, _ = _make_runner(strategy="news_only")
        summary = runner.run_once(dry_run=True)
        assert summary["symbols_processed"] == 2


# ---------------------------------------------------------------------------
# Runner — news_only bypasses thin-history guard
# ---------------------------------------------------------------------------

class TestNewsOnlyBypassesThinHistoryGuard:
    """In news_only mode, a 1-bar symbol must still get a news signal."""

    def _nse_bullish(self):
        return {
            "symbol": "SBIN",
            "provider_mode": "nse_live",
            "items": [{"desc": "Order Win", "attchmntText": "awarded contract"}],
            "documents": [],
            "sentiment_score": 0.3,
            "sentiment_label": "bullish",
            "source_audit": {"nse_announcements": {"status": "live", "count": 1}},
        }

    def test_thin_history_with_news_only_does_not_skip(self):
        """1-bar symbol in news_only mode must NOT be skipped with insufficient_history."""
        runner, _ = _make_runner(strategy="news_only", n_bars=1, nse_result=self._nse_bullish())
        result = runner._process_symbol("SBIN", dry_run=True)
        assert result.get("skip_reason") != "insufficient_history", (
            f"news_only must not skip thin-history symbols; got: {result}"
        )

    def test_thin_history_with_blended_still_skips(self):
        """With blended strategy, thin-history guard still applies."""
        runner, _ = _make_runner(
            strategy="blended",
            n_bars=1,
            cfg_overrides={"signal": {"min_bars_for_signal": 10}},
        )
        result = runner._process_symbol("SBIN", dry_run=True)
        assert result["skip_reason"] == "insufficient_history"

    def test_all_48_symbols_get_signal_in_news_only_mode(self):
        """Even with 0 OHLCV bars, all symbols should reach signal evaluation."""
        cfg = dict(_BASE_CFG)
        cfg["whitelist"] = ["SBIN", "RELIANCE", "TCS"]
        cfg["signal"] = {"strategy": "news_only"}
        stack = _FakeStack()
        runner = NubraEquityRunner(
            cfg,
            forecasting=_FakeForecasting(),
            mirofish=_FakeMirofish(),
            risk_engine=RiskEngineService(),
            nse_collector=_FakeNse(self._nse_bullish()),
            nubra_client=_FakeNubraClient(n_bars=1),  # thin history — only 1 bar
            equity_stack=stack,
            strategy="news_only",
        )
        summary = runner.run_once(dry_run=True)
        # No symbol should be skipped due to thin history
        thin_skips = [
            r for r in summary["results"]
            if r.get("skip_reason") == "insufficient_history"
        ]
        assert thin_skips == [], f"news_only must not thin-skip any symbol: {thin_skips}"

    def test_news_only_does_not_call_forecaster(self):
        """In news_only mode the forecaster must never be invoked."""
        call_log = []

        class _TrackingForecasting:
            def forecast_from_prices(self, ticker, closes, horizon=5):
                call_log.append(ticker)
                return _BULLISH_FORECAST

        cfg = dict(_BASE_CFG)
        cfg["signal"] = {"strategy": "news_only"}
        stack = _FakeStack()
        runner = NubraEquityRunner(
            cfg,
            forecasting=_TrackingForecasting(),
            mirofish=_FakeMirofish(),
            risk_engine=RiskEngineService(),
            nse_collector=_FakeNse(self._nse_bullish()),
            nubra_client=_FakeNubraClient(n_bars=1),
            equity_stack=stack,
            strategy="news_only",
        )
        runner._process_symbol("SBIN", dry_run=True)
        assert call_log == [], "Forecaster must not be called in news_only mode"

    def test_news_only_does_not_call_mirofish(self):
        """In news_only mode MiroFish simulation must never be invoked."""
        call_log = []

        class _TrackingMirofish:
            def simulate(self, request):
                call_log.append(request)
                return {"outlook_score": 0, "provider_mode": "unused"}

        cfg = dict(_BASE_CFG)
        cfg["signal"] = {"strategy": "news_only"}
        stack = _FakeStack()
        runner = NubraEquityRunner(
            cfg,
            forecasting=_FakeForecasting(),
            mirofish=_TrackingMirofish(),
            risk_engine=RiskEngineService(),
            nse_collector=_FakeNse(self._nse_bullish()),
            nubra_client=_FakeNubraClient(n_bars=1),
            equity_stack=stack,
            strategy="news_only",
        )
        runner._process_symbol("SBIN", dry_run=True)
        assert call_log == [], "MiroFish must not be called in news_only mode"


# ---------------------------------------------------------------------------
# NSE keyword scorer — new and config-driven keywords
# ---------------------------------------------------------------------------

from services.nse_announcements.nse_announcements_collector import (
    NseAnnouncementsCollector,
    _score_sentiment,
    _DEFAULT_BULLISH_KW,
    _DEFAULT_BEARISH_KW,
)


class TestEnhancedKeywordScorer:
    """Validates that new catalysts are caught by the enriched keyword sets."""

    # ── Bullish catalysts ────────────────────────────────────────────────────

    def test_successful_bidder_tbcb_is_bullish(self):
        """POWERGRID-style: 'POWERGRID has been selected as successful bidder under TBCB'."""
        items = [{"attchmntText": "POWERGRID has been selected as successful bidder under TBCB"}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0, "successful bidder + tbcb must score bullish"

    def test_successful_bidder_alone_is_bullish(self):
        items = [{"attchmntText": "Company declared as successful bidder for the project."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0

    def test_tbcb_alone_is_bullish(self):
        items = [{"attchmntText": "Project awarded under TBCB mechanism."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0

    def test_contract_awarded_is_bullish(self):
        items = [{"attchmntText": "Major contract awarded to the company for infrastructure project."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0

    def test_approval_is_bullish(self):
        items = [{"attchmntText": "Board approval obtained for fund raise."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0

    def test_qip_is_bullish(self):
        items = [{"attchmntText": "Company to raise capital via QIP at market price."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0

    def test_mou_is_bullish(self):
        items = [{"attchmntText": "Signed MOU with strategic partner for collaboration."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score > 0.0

    # ── Bearish catalysts ────────────────────────────────────────────────────

    def test_penalty_is_bearish(self):
        """SEBI penalty filing must score bearish."""
        items = [{"attchmntText": "Company receives penalty from SEBI for non-compliance."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0

    def test_investigation_is_bearish(self):
        items = [{"attchmntText": "ED investigation initiated against promoter."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0

    def test_probe_is_bearish(self):
        items = [{"attchmntText": "CBI probe into the company's accounts."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0

    def test_rating_downgrade_is_bearish(self):
        items = [{"attchmntText": "Credit rating downgrade to BB+ due to liquidity concerns."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0

    def test_insolvency_is_bearish(self):
        items = [{"attchmntText": "NCLT admits insolvency petition against the company."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0

    def test_resignation_is_bearish(self):
        items = [{"attchmntText": "CFO resignation submitted to the board."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0

    # ── Config-driven overrides ───────────────────────────────────────────────

    def test_config_bullish_keywords_override(self):
        """Config-supplied bullish_keywords replace defaults."""
        cfg = {
            "nse": {
                "bullish_keywords": ["supercatalyst"],
                "bearish_keywords": ["doom"],
            }
        }
        collector = NseAnnouncementsCollector.from_config(cfg)
        # "supercatalyst" bullish, default keywords not active
        items_bull = [{"attchmntText": "supercatalyst event occurred"}]
        result = collector.collect.__func__ if False else None  # use score directly via collect
        # Score via the collector's internal keywords
        score_bull = _score_sentiment(items_bull, collector._bullish_kw, collector._bearish_kw)
        assert score_bull > 0.0

    def test_config_bearish_keywords_override(self):
        cfg = {
            "nse": {
                "bullish_keywords": ["great"],
                "bearish_keywords": ["catastrophe"],
            }
        }
        collector = NseAnnouncementsCollector.from_config(cfg)
        items_bear = [{"attchmntText": "catastrophe event hit operations"}]
        score = _score_sentiment(items_bear, collector._bullish_kw, collector._bearish_kw)
        assert score < 0.0

    def test_from_config_no_override_uses_defaults(self):
        """from_config without keyword overrides falls back to _DEFAULT_BULLISH_KW."""
        collector = NseAnnouncementsCollector.from_config({"nse": {}})
        assert collector._bullish_kw == _DEFAULT_BULLISH_KW
        assert collector._bearish_kw == _DEFAULT_BEARISH_KW

    def test_powergrid_tbcb_scenario_end_to_end(self):
        """Full POWERGRID scenario: collector produces bullish sentiment_label."""
        from unittest.mock import MagicMock
        import requests as req

        tbcb_items = [
            {
                "attchmntText": (
                    "POWERGRID Corporation has been declared successful bidder "
                    "under TBCB for the new transmission project."
                ),
                "desc": "Corporate Action",
                "symbol": "POWERGRID",
            }
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = tbcb_items
        sess = MagicMock(spec=req.Session)
        sess.get.return_value = resp
        sess.headers = {}

        collector = NseAnnouncementsCollector(session=sess)
        result = collector.collect("POWERGRID")
        assert result["sentiment_score"] > 0.0
        assert result["sentiment_label"] == "bullish"


# ---------------------------------------------------------------------------
# Strategy capability properties (OCP — runner reads these, not strategy names)
# ---------------------------------------------------------------------------

class TestStrategyCapabilities:
    def test_blended_requires_price_history(self):
        assert get_strategy("blended", {}).requires_price_history is True

    def test_blended_uses_forecast(self):
        assert get_strategy("blended", {}).uses_forecast is True

    def test_news_only_does_not_require_price_history(self):
        assert get_strategy("news_only", {}).requires_price_history is False

    def test_news_only_does_not_use_forecast(self):
        assert get_strategy("news_only", {}).uses_forecast is False

    def test_abc_defaults_are_true(self):
        # ABC defaults guard new strategies so they must opt out explicitly.
        assert SignalStrategy.requires_price_history is True
        assert SignalStrategy.uses_forecast is True


# ---------------------------------------------------------------------------
# NewsOnlySignalStrategy — per-symbol upside gate (#3)
# ---------------------------------------------------------------------------

class TestNewsOnlyPerSymbolUpside:
    def test_per_symbol_overrides_global(self):
        cfg = _cfg_with_news_only()
        cfg["entry_threshold"]["per_symbol"] = {"SBIN": 5.0}
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4))
        assert signal["expected_move_pct"] == pytest.approx(0.05)

    def test_global_wins_when_per_symbol_is_lower(self):
        cfg = _cfg_with_news_only()
        cfg["entry_threshold"]["min_expected_upside_pct"] = 3.0
        cfg["entry_threshold"]["per_symbol"] = {"SBIN": 1.0}
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4))
        assert signal["expected_move_pct"] == pytest.approx(0.03)

    def test_per_symbol_key_case_insensitive(self):
        cfg = _cfg_with_news_only()
        cfg["entry_threshold"]["per_symbol"] = {"sbin": 4.0}
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4))
        assert signal["expected_move_pct"] == pytest.approx(0.04)

    def test_symbol_not_in_per_symbol_uses_global(self):
        cfg = _cfg_with_news_only()
        cfg["entry_threshold"]["min_expected_upside_pct"] = 2.5
        cfg["entry_threshold"]["per_symbol"] = {"RELIANCE": 6.0}
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4))
        assert signal["expected_move_pct"] == pytest.approx(0.025)

    def test_call_clears_gate_at_per_symbol_threshold(self):
        cfg = _cfg_with_news_only()
        cfg["entry_threshold"]["per_symbol"] = {"SBIN": 4.0}
        strategy = get_strategy("news_only", cfg)
        signal = strategy.build("SBIN", {}, None, None, _nse(0.4))
        gate = ExpectedUpsideGate({"min_expected_upside_pct": 4.0})
        ok, reason = gate.evaluate(signal)
        assert ok, f"Gate should pass at per-symbol threshold: {reason}"


# ---------------------------------------------------------------------------
# NSE scorer false-positive guards (#5)
# Fail against old substring scorer; pass with word-boundary regex.
# ---------------------------------------------------------------------------

class TestScorerFalsePositiveGuards:
    """Regression guards: direction-inverting false positives from old substring matching."""

    def test_winding_up_is_not_bullish(self):
        # Old: "win" in "winding" → bullish.  New: word boundary prevents it.
        items = [{"attchmntText": "Winding up petition filed against the company."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score <= 0.0, f"'winding up' must not be bullish; got {score}"

    def test_winding_up_scores_bearish(self):
        # "winding up" is in bearish set.
        items = [{"attchmntText": "Winding up petition filed against the company."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0, f"'winding up' should score bearish; got {score}"

    def test_company_name_fine_organics_is_not_bearish(self):
        # Old: "fine" substring matched company name → bearish.
        items = [{"attchmntText": "Fine Organics Industries Limited announces board meeting."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score >= 0.0, f"Company name 'Fine Organics' must not be bearish; got {score}"

    def test_loss_of_share_certificate_is_not_bearish(self):
        # Old: "loss" substring → bearish.  Admin filing, not financial loss.
        items = [{"attchmntText": "Loss of share certificate notification as per SEBI requirements."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score >= 0.0, f"'loss of share certificate' must not be bearish; got {score}"

    def test_esop_strike_price_is_not_bearish(self):
        # Old: "strike" → bearish.  ESOP strike price is neutral/positive.
        items = [{"attchmntText": "ESOP grant at a strike price of Rs 250 per share."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score >= 0.0, f"'strike price' (ESOP) must not be bearish; got {score}"

    def test_in_order_to_is_not_bullish(self):
        # Old: "order" in "in order to" → bullish.
        items = [{"attchmntText": "In order to comply with SEBI regulations the company discloses."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score <= 0.0, f"'in order to' must not be bullish; got {score}"

    def test_stakeholder_committee_is_not_bullish(self):
        # Old: "stake" in "stakeholder" → bullish.  Word boundary guards it.
        items = [{"attchmntText": "Stakeholder consultation committee meeting scheduled."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score <= 0.0, f"'Stakeholder committee' must not be bullish; got {score}"

    def test_net_loss_scores_bearish(self):
        items = [{"attchmntText": "Company reports net loss of Rs 150 crore in Q3FY26."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0, f"'net loss' should be bearish; got {score}"

    def test_going_concern_scores_bearish(self):
        items = [{"attchmntText": "Auditors raised going concern doubt in the annual report."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0, f"'going concern' should be bearish; got {score}"

    def test_restructuring_scores_bearish(self):
        items = [{"attchmntText": "Company announces debt restructuring plan with lenders."}]
        score = _score_sentiment(items, _DEFAULT_BULLISH_KW, _DEFAULT_BEARISH_KW)
        assert score < 0.0, f"'restructuring' should be bearish; got {score}"

    def test_standalone_win_matches_but_winding_does_not(self):
        # Word boundary: "win" matches standalone "win" but NOT "winding".
        kw = frozenset({"win"})
        assert _score_sentiment(
            [{"attchmntText": "Company celebrates a big win."}], kw, frozenset()
        ) > 0.0, "standalone 'win' should match"
        assert _score_sentiment(
            [{"attchmntText": "Winding up petition."}], kw, frozenset()
        ) == 0.0, "'win' must NOT match inside 'winding'"


# ---------------------------------------------------------------------------
# _extract_subjects helper
# ---------------------------------------------------------------------------

class TestExtractSubjects:
    def test_extracts_desc_when_present(self):
        items = [{"desc": "Quarterly Results", "attchmntText": "profit"}]
        assert "Quarterly Results" in _extract_subjects(items)

    def test_falls_back_to_attchmnt_text_snippet_when_no_desc(self):
        items = [{"attchmntText": "Important corporate announcement for shareholders."}]
        subjects = _extract_subjects(items)
        assert len(subjects) == 1
        assert subjects[0].startswith("Important")

    def test_empty_items_gives_empty_list(self):
        assert _extract_subjects([]) == []

    def test_item_with_neither_field_omitted(self):
        items = [{"symbol": "SBIN"}]
        assert _extract_subjects(items) == []

"""Offline unit tests for EquitySignalBuilder.

No live SDK, no network. All assertions derive from the SPEC, not from running
the code first (BP-123 — never weaken a test to match a stub).
"""
from __future__ import annotations

import pytest

from services.nubra_client.equity_signal_builder import _DEFAULTS, EquitySignalBuilder


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _forecast(direction="bullish", predicted_return=0.03, confidence=0.72):
    return {
        "direction": direction,
        "predicted_return": predicted_return,
        "confidence": confidence,
        "forecast": [812.5, 820.0, 825.0, 828.0, 830.0],
    }


def _simulation(outlook_score=10.5):
    return {
        "outlook_score": outlook_score,
        "final_direction": "bullish",
        "distribution": {"bullish": 0.6, "bearish": 0.4, "neutral": 0.0},
        "provider_mode": "local_mirofish_fallback",
    }


# ---------------------------------------------------------------------------
# Trade direction — Caveat A: always from TimesFM, NOT from sim score
# ---------------------------------------------------------------------------

class TestTradeDirection:
    def test_bullish_forecast_gives_call(self):
        signal = EquitySignalBuilder().build("SBIN", _forecast("bullish"), _simulation())
        assert signal["trade"] == "CALL"

    def test_bearish_forecast_gives_put(self):
        signal = EquitySignalBuilder().build("SBIN", _forecast("bearish"), _simulation())
        assert signal["trade"] == "PUT"

    def test_neutral_forecast_gives_hold(self):
        signal = EquitySignalBuilder().build("SBIN", _forecast("neutral"), _simulation())
        assert signal["trade"] == "HOLD"

    def test_bearish_sim_does_not_override_bullish_timesfm(self):
        # Caveat A: sim score below 0 must NOT flip CALL to PUT
        sim_bearish = _simulation(outlook_score=-20.0)
        signal = EquitySignalBuilder().build("SBIN", _forecast("bullish"), sim_bearish)
        assert signal["trade"] == "CALL"

    def test_bullish_sim_does_not_override_bearish_timesfm(self):
        # Caveat A: positive sim score must NOT flip PUT to CALL
        sim_bullish = _simulation(outlook_score=30.0)
        signal = EquitySignalBuilder().build("SBIN", _forecast("bearish"), sim_bullish)
        assert signal["trade"] == "PUT"


# ---------------------------------------------------------------------------
# Mandatory signal fields
# ---------------------------------------------------------------------------

class TestSignalFields:
    def _sig(self):
        return EquitySignalBuilder().build("SBIN", _forecast(), _simulation())

    def test_asset_class_is_equity(self):
        assert self._sig()["asset_class"] == "equity"

    def test_strategy_type_is_trend(self):
        # Caveat C: "no_trade" causes RiskEngine Rule 4 to always reject
        assert self._sig()["strategy_type"] == "trend"

    def test_ticker_is_upper(self):
        signal = EquitySignalBuilder().build("sbin", _forecast(), _simulation())
        assert signal["ticker"] == "SBIN"

    def test_horizon_is_1d(self):
        assert self._sig()["horizon"] == "1d"

    def test_signal_id_is_uuid_string(self):
        import uuid
        sig_id = self._sig()["signal_id"]
        uuid.UUID(sig_id)  # raises ValueError if not a valid UUID

    def test_signal_ids_are_unique_per_call(self):
        builder = EquitySignalBuilder()
        a = builder.build("SBIN", _forecast(), _simulation())
        b = builder.build("SBIN", _forecast(), _simulation())
        assert a["signal_id"] != b["signal_id"]

    def test_expected_move_pct_from_forecast_predicted_return(self):
        signal = EquitySignalBuilder().build("SBIN", _forecast(predicted_return=0.025), _simulation())
        assert signal["expected_move_pct"] == pytest.approx(0.025)


# ---------------------------------------------------------------------------
# Confidence blending (no NSE) — weights from _DEFAULTS["no_nse"]
# ---------------------------------------------------------------------------

class TestConfidenceBlendNoNse:
    def test_blend_formula_weights(self):
        # Derive expected from the published defaults so a config change propagates automatically.
        tf_w = _DEFAULTS["no_nse"]["tf"]
        sim_w = _DEFAULTS["no_nse"]["sim"]
        sim_conf = (10.5 + 100) / 200   # outlook=10.5 → 0.5525
        expected = round(0.72 * tf_w + sim_conf * sim_w, 4)
        sim = _simulation(outlook_score=10.5)
        signal = EquitySignalBuilder().build("SBIN", _forecast(confidence=0.72), sim)
        assert signal["confidence"] == pytest.approx(expected, abs=1e-4)

    def test_confidence_clamped_between_0_and_1(self):
        # extreme positive outlook → sim_conf approaches 1.0
        sim_extreme = _simulation(outlook_score=100.0)
        sig = EquitySignalBuilder().build("SBIN", _forecast(confidence=0.95), sim_extreme)
        assert 0.0 <= sig["confidence"] <= 1.0

    def test_confidence_clamped_low(self):
        # extreme negative outlook → sim_conf approaches 0.0
        sim_low = _simulation(outlook_score=-100.0)
        sig = EquitySignalBuilder().build("SBIN", _forecast(confidence=0.5), sim_low)
        assert 0.0 <= sig["confidence"] <= 1.0

    def test_missing_outlook_score_defaults_to_neutral(self):
        # simulation without outlook_score → 0 → sim_conf = 0.5
        tf_w = _DEFAULTS["no_nse"]["tf"]
        sim_w = _DEFAULTS["no_nse"]["sim"]
        expected = round(0.6 * tf_w + 0.5 * sim_w, 4)
        sim_no_score = {"final_direction": "bullish"}
        signal = EquitySignalBuilder().build("SBIN", _forecast(confidence=0.6), sim_no_score)
        assert signal["confidence"] == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# Confidence blending (with NSE) — weights from _DEFAULTS["with_nse"]
# ---------------------------------------------------------------------------

class TestConfidenceBlendWithNse:
    def _nse(self, sentiment_score=0.3):
        return {"sentiment_score": sentiment_score, "provider_mode": "nse_live"}

    def test_three_pillar_blend_formula(self):
        # Derive expected value from published defaults — no hardcoded numerics.
        tf_w = _DEFAULTS["with_nse"]["tf"]
        sim_w = _DEFAULTS["with_nse"]["sim"]
        nse_w = _DEFAULTS["with_nse"]["nse"]
        sim_conf = (10.5 + 100) / 200      # 0.5525
        nse_conf = (0.3 + 1) / 2           # 0.65
        expected = round(0.72 * tf_w + sim_conf * sim_w + nse_conf * nse_w, 4)
        sim = _simulation(outlook_score=10.5)
        signal = EquitySignalBuilder().build(
            "SBIN", _forecast(confidence=0.72), sim, nse_result=self._nse(0.3)
        )
        assert signal["confidence"] == pytest.approx(expected, abs=1e-4)

    def test_negative_nse_sentiment_lowers_confidence(self):
        nse_bearish = self._nse(-0.8)
        nse_neutral = self._nse(0.0)
        sim = _simulation(outlook_score=5.0)
        forecast = _forecast(confidence=0.70)
        sig_bearish = EquitySignalBuilder().build("SBIN", forecast, sim, nse_result=nse_bearish)
        sig_neutral = EquitySignalBuilder().build("SBIN", forecast, sim, nse_result=nse_neutral)
        assert sig_bearish["confidence"] < sig_neutral["confidence"]

    def test_positive_nse_sentiment_raises_confidence(self):
        nse_bullish = self._nse(0.8)
        nse_neutral = self._nse(0.0)
        sim = _simulation(outlook_score=5.0)
        forecast = _forecast(confidence=0.60)
        sig_bull = EquitySignalBuilder().build("SBIN", forecast, sim, nse_result=nse_bullish)
        sig_neut = EquitySignalBuilder().build("SBIN", forecast, sim, nse_result=nse_neutral)
        assert sig_bull["confidence"] > sig_neut["confidence"]

    def test_nse_result_none_uses_two_pillar_blend(self):
        # Two-pillar and three-pillar use different weight sets → different results.
        sim = _simulation(outlook_score=10.0)  # sim_conf=0.55
        fc = _forecast(confidence=0.60)
        sig_no_nse = EquitySignalBuilder().build("SBIN", fc, sim)
        sig_neutral_nse = EquitySignalBuilder().build("SBIN", fc, sim, nse_result=self._nse(0.0))
        assert sig_no_nse["confidence"] != sig_neutral_nse["confidence"]


# ---------------------------------------------------------------------------
# F2: news_suppressed override — bad NSE news + weak forecast → HOLD
# ---------------------------------------------------------------------------

class TestNewsSuppressedOverride:
    """EquitySignalBuilder.build() suppresses CALL→HOLD when NSE sentiment is strongly
    negative AND the TimesFM confidence is below the configured weak threshold."""

    def _nse(self, sentiment_score):
        return {"sentiment_score": sentiment_score, "provider_mode": "nse_live"}

    def test_bad_news_and_weak_confidence_suppresses_call(self):
        # sentiment_score=-0.5 < neg_threshold=-0.3; confidence=0.45 < weak=0.55
        fc = _forecast("bullish", confidence=0.45)
        nse = self._nse(-0.5)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "HOLD"

    def test_bad_news_strong_confidence_does_not_suppress(self):
        # confidence=0.75 ≥ weak_threshold → override must NOT fire
        fc = _forecast("bullish", confidence=0.75)
        nse = self._nse(-0.5)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "CALL"

    def test_mild_negative_news_does_not_suppress(self):
        # sentiment_score=-0.1 > neg_threshold=-0.3 → not bad enough to suppress
        fc = _forecast("bullish", confidence=0.45)
        nse = self._nse(-0.1)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "CALL"

    def test_neutral_news_does_not_suppress(self):
        fc = _forecast("bullish", confidence=0.40)
        nse = self._nse(0.0)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "CALL"

    def test_positive_news_does_not_suppress(self):
        fc = _forecast("bullish", confidence=0.45)
        nse = self._nse(0.4)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "CALL"

    def test_override_does_not_apply_to_put(self):
        # Bearish forecast + bad NSE: PUT must remain PUT (not suppressed)
        fc = _forecast("bearish", confidence=0.45)
        nse = self._nse(-0.5)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "PUT"

    def test_override_does_not_apply_without_nse(self):
        # No NSE result → override must not fire even with weak confidence
        fc = _forecast("bullish", confidence=0.40)
        signal = EquitySignalBuilder().build("SBIN", fc, _simulation(), nse_result=None)
        assert signal["trade"] == "CALL"

    def test_config_overrides_thresholds(self):
        # Passing custom config changes the thresholds
        custom_cfg = {
            "confidence_weights": {
                "no_nse": {"tf": 0.6, "sim": 0.4},
                "with_nse": {"tf": 0.5, "sim": 0.3, "nse": 0.2},
            },
            "news_override": {"neg_threshold": -0.1, "weak_confidence": 0.9},
        }
        builder = EquitySignalBuilder(custom_cfg)
        # sentiment=-0.2 < -0.1 and confidence=0.80 < 0.9 → suppress
        fc = _forecast("bullish", confidence=0.80)
        nse = self._nse(-0.2)
        signal = builder.build("SBIN", fc, _simulation(), nse_result=nse)
        assert signal["trade"] == "HOLD"

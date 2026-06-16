"""Offline unit tests for EquitySignalBuilder.

No live SDK, no network. All assertions derive from the SPEC, not from running
the code first (BP-123 — never weaken a test to match a stub).
"""
from __future__ import annotations

import pytest

from services.nubra_client.equity_signal_builder import EquitySignalBuilder


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
# Confidence blending (no NSE) — 60% TimesFM + 40% sim
# ---------------------------------------------------------------------------

class TestConfidenceBlendNoNse:
    def test_blend_formula_weights(self):
        # outlook_score=10.5 → sim_conf = (10.5 + 100)/200 = 0.5525
        # tf_conf = 0.72
        # expected = 0.72*0.6 + 0.5525*0.4 = 0.432 + 0.221 = 0.653
        sim = _simulation(outlook_score=10.5)
        signal = EquitySignalBuilder().build("SBIN", _forecast(confidence=0.72), sim)
        assert signal["confidence"] == pytest.approx(0.653, abs=1e-4)

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
        sim_no_score = {"final_direction": "bullish"}
        signal = EquitySignalBuilder().build("SBIN", _forecast(confidence=0.6), sim_no_score)
        # sim_conf = 0.5; expected = 0.6*0.6 + 0.5*0.4 = 0.36 + 0.20 = 0.56
        assert signal["confidence"] == pytest.approx(0.56, abs=1e-4)


# ---------------------------------------------------------------------------
# Confidence blending (with NSE) — 50% TimesFM + 30% sim + 20% NSE
# ---------------------------------------------------------------------------

class TestConfidenceBlendWithNse:
    def _nse(self, sentiment_score=0.3):
        return {"sentiment_score": sentiment_score, "provider_mode": "nse_live"}

    def test_three_pillar_blend_formula(self):
        # tf_conf=0.72, sim outlook=10.5 → sim_conf=0.5525
        # nse score=0.3 → nse_conf=(0.3+1)/2=0.65
        # expected = 0.72*0.5 + 0.5525*0.3 + 0.65*0.2 = 0.36 + 0.16575 + 0.13 = 0.65575
        # round(0.65575, 4) → 0.6557 (Python float representation)
        sim = _simulation(outlook_score=10.5)
        signal = EquitySignalBuilder().build(
            "SBIN", _forecast(confidence=0.72), sim, nse_result=self._nse(0.3)
        )
        assert signal["confidence"] == pytest.approx(0.6557, abs=1e-4)

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
        # No NSE → 60/40; WITH NSE → 50/30/20.
        # At neutral NSE score=0 → nse_conf=0.5
        # two-pillar: 0.60*0.6 + 0.55*0.4 = 0.36 + 0.22 = 0.58
        # three-pillar at nse=0: 0.60*0.5 + 0.55*0.3 + 0.5*0.2 = 0.30 + 0.165 + 0.10 = 0.565
        # two-pillar > three-pillar at nse=0 (sim_conf pulls down less than split)
        sim = _simulation(outlook_score=10.0)  # sim_conf=0.55
        fc = _forecast(confidence=0.60)
        sig_no_nse = EquitySignalBuilder().build("SBIN", fc, sim)
        sig_neutral_nse = EquitySignalBuilder().build("SBIN", fc, sim, nse_result=self._nse(0.0))
        # just assert they differ (different weight schemes)
        assert sig_no_nse["confidence"] != sig_neutral_nse["confidence"]

"""Builds an equity signal dict from TimesFM forecast + MiroFish simulation output.

Keeps signal construction isolated so it can be unit-tested without a live broker.
# implement this interface to add new signal sources: extend _blend_confidence()
"""
from __future__ import annotations

import uuid


# Caveat A: trade direction comes from TimesFM, NOT from the sim score.
# Local MiroFish sim maps "neutral"→"bearish" when no Reddit data is present;
# using the sim score for direction would systematically suppress CALL signals.
_DIRECTION_TO_TRADE: dict[str, str] = {
    "bullish": "CALL",
    "bearish": "PUT",
    "neutral": "HOLD",
}

# Defaults used when no config is supplied — mirrored from config/nubra_config.json.
# Export these so tests can derive expected values without hardcoding numerics.
_DEFAULTS: dict = {
    "no_nse": {"tf": 0.6, "sim": 0.4},
    "with_nse": {"tf": 0.5, "sim": 0.3, "nse": 0.2},
    "news_override": {"neg_threshold": -0.3, "weak_confidence": 0.55},
}


class EquitySignalBuilder:
    """Converts TimesFM + MiroFish outputs into a tradeable equity signal dict.

    Args:
        config: optional ``signal`` sub-dict from nubra_config.json.
                All keys are optional; built-in defaults apply when absent.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        cw_no_nse = cfg.get("confidence_weights", {}).get("no_nse", _DEFAULTS["no_nse"])
        cw_with_nse = cfg.get("confidence_weights", {}).get("with_nse", _DEFAULTS["with_nse"])
        self._tf_w = float(cw_no_nse.get("tf", _DEFAULTS["no_nse"]["tf"]))
        self._sim_w = float(cw_no_nse.get("sim", _DEFAULTS["no_nse"]["sim"]))
        self._tf_w_nse = float(cw_with_nse.get("tf", _DEFAULTS["with_nse"]["tf"]))
        self._sim_w_nse = float(cw_with_nse.get("sim", _DEFAULTS["with_nse"]["sim"]))
        self._nse_w = float(cw_with_nse.get("nse", _DEFAULTS["with_nse"]["nse"]))

        news_ov = cfg.get("news_override", _DEFAULTS["news_override"])
        self._news_neg_threshold = float(
            news_ov.get("neg_threshold", _DEFAULTS["news_override"]["neg_threshold"])
        )
        self._news_weak_confidence = float(
            news_ov.get("weak_confidence", _DEFAULTS["news_override"]["weak_confidence"])
        )

    def build(
        self,
        symbol: str,
        forecast: dict,
        simulation: dict,
        *,
        nse_result: dict | None = None,
    ) -> dict:
        trade = _DIRECTION_TO_TRADE[forecast["direction"]]
        confidence = self._blend_confidence(forecast, simulation, nse_result)

        # F2: strong bearish NSE news + weak forecast confidence → suppress CALL to HOLD.
        # Prevents chasing a momentum signal when fundamentals are against it.
        if (
            trade == "CALL"
            and nse_result is not None
            and float(nse_result.get("sentiment_score", 0.0)) < self._news_neg_threshold
            and float(forecast["confidence"]) < self._news_weak_confidence
        ):
            trade = "HOLD"

        return {
            "ticker": symbol.upper(),
            "asset_class": "equity",
            "trade": trade,
            "strategy_type": "trend",          # Caveat C: must be non-"no_trade" or RiskEngine rejects
            "expected_move_pct": float(forecast["predicted_return"]),
            "confidence": confidence,
            "horizon": "1d",
            "signal_id": str(uuid.uuid4()),
        }

    # ------------------------------------------------------------------

    def _blend_confidence(
        self,
        forecast: dict,
        simulation: dict,
        nse_result: dict | None,
    ) -> float:
        tf_conf = float(forecast["confidence"])
        outlook = float(simulation.get("outlook_score", 0))
        sim_conf = max(0.0, min(1.0, (outlook + 100) / 200))

        if nse_result is not None:
            nse_score = float(nse_result.get("sentiment_score", 0.0))
            nse_conf = max(0.0, min(1.0, (nse_score + 1) / 2))
            return round(
                tf_conf * self._tf_w_nse
                + sim_conf * self._sim_w_nse
                + nse_conf * self._nse_w,
                4,
            )

        return round(tf_conf * self._tf_w + sim_conf * self._sim_w, 4)

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
        # NOTE: sim_conf (MiroFish outlook_score) is intentionally NOT used as a confidence
        # leg — MiroFish's simulation is itself fed the forecast direction/confidence and the
        # same NSE documents, so folding it back into the blend double-counts both. Only the
        # "tf" and "nse" weights are read here; any "sim" entry in confidence_weights is
        # ignored (kept in config/_DEFAULTS for backward compatibility).
        cw_with_nse = cfg.get("confidence_weights", {}).get("with_nse", _DEFAULTS["with_nse"])
        self._tf_w_nse = float(cw_with_nse.get("tf", _DEFAULTS["with_nse"]["tf"]))
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
            # Forecast is TimesFM horizon=5 (see equity_runner._process_symbol) — this label
            # must match the true forecast horizon so ExpectedUpsideGate's threshold is read
            # as "min 5-day upside", not "min 1-day upside".
            "horizon": "5d",
            "signal_id": str(uuid.uuid4()),
        }

    # ------------------------------------------------------------------

    def _blend_confidence(
        self,
        forecast: dict,
        simulation: dict,
        nse_result: dict | None,
    ) -> float:
        """Blend TimesFM confidence with NSE sentiment confidence.

        ``simulation`` is accepted for interface stability (build() passes it through) but is
        NOT an independent confidence input: the MiroFish simulation already consumes the
        forecast's direction/confidence and the same NSE documents, so a sim_conf leg here
        would double-count both signals rather than add new information.
        """
        tf_conf = float(forecast["confidence"])
        if nse_result is None:
            return round(tf_conf, 4)

        nse_score = float(nse_result.get("sentiment_score", 0.0))
        nse_conf = max(0.0, min(1.0, (nse_score + 1) / 2))
        total_w = self._tf_w_nse + self._nse_w
        if total_w <= 0:
            return round(tf_conf, 4)
        # Renormalize so partial config overrides (e.g. only "tf" set) still sum to 1.
        w_tf = self._tf_w_nse / total_w
        w_nse = self._nse_w / total_w
        return round(tf_conf * w_tf + nse_conf * w_nse, 4)

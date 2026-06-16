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


class EquitySignalBuilder:
    """Converts TimesFM + MiroFish outputs into a tradeable equity signal dict."""

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
            return round(tf_conf * 0.5 + sim_conf * 0.3 + nse_conf * 0.2, 4)

        return round(tf_conf * 0.6 + sim_conf * 0.4, 4)

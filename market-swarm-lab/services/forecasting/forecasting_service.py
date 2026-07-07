"""
Forecasting service with TimesFM 2.5 (PyTorch) and a local fallback.

TimesFM 2.5 is loaded lazily on first call.
If the model or its dependencies are unavailable, the service falls back to
a deterministic local forecaster that still returns the full output schema.

Quantile mapping from TimesFM 2.5 output:
  quantile_forecast shape = (n_series, horizon, 10)
  columns:  [mean, q10, q20, q30, q40, q50, q60, q70, q80, q90]
"""
from __future__ import annotations

import json
import math
import os
import threading
from datetime import date
from pathlib import Path
from statistics import mean, stdev
from typing import Any

_timesfm_error: str | None = None
_timesfm_model = None
_timesfm_config_cls = None
# Guards TimesFM load: from_pretrained()+compile() is expensive (loads the 200M model) and
# not safe to run twice concurrently — the ThreadPoolExecutor can otherwise race two symbols
# into loading the model at once on first use.
_timesfm_load_lock = threading.Lock()


class ForecastUnavailable(RuntimeError):
    """Raised when no real forecast can be produced (TimesFM unavailable). There is no
    formulaic fallback — callers skip the symbol rather than fabricate an upside number."""


# TimesFM 2.5 200M is installed in .venv-timesfm — enabled by default
ENABLE_TIMESFM = os.getenv("ENABLE_TIMESFM", "true").lower() == "true"
# Per-symbol forecast input/output dump to state/raw/ohlcv/ is diagnostic-only and does disk
# I/O on every call in the hot (ThreadPoolExecutor) path — opt-in via FORECAST_DUMP=1.
FORECAST_DUMP = os.getenv("FORECAST_DUMP", "0").lower() in ("1", "true")
_ROOT = Path(__file__).resolve().parents[2]


def _load_timesfm():
    global _timesfm_model, _timesfm_config_cls, _timesfm_error
    if _timesfm_model is not None:
        return True
    if _timesfm_error is not None:
        return False
    with _timesfm_load_lock:
        # Double-checked: another thread may have loaded (or failed) the model while
        # this one was waiting on the lock.
        if _timesfm_model is not None:
            return True
        if _timesfm_error is not None:
            return False
        try:
            # Add .venv-timesfm site-packages so timesfm is importable
            import sys, glob
            _root = Path(__file__).resolve().parents[2]
            _venv_lib = str(_root / ".venv-timesfm" / "lib")
            for _sp in glob.glob(f"{_venv_lib}/python*/site-packages"):
                if _sp not in sys.path:
                    sys.path.insert(0, _sp)

            import torch  # noqa: F401
            import numpy as np  # noqa: F401
            import timesfm

            # TimesFM 2.5 API (google/timesfm-2.5-200m-pytorch): from_pretrained + compile.
            model = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
            model.compile(
                timesfm.ForecastConfig(
                    max_context=1024,
                    max_horizon=16,
                    normalize_inputs=True,
                    use_continuous_quantile_head=True,
                    fix_quantile_crossing=True,
                )
            )
            _timesfm_model = model
            return True
        except Exception as exc:
            _timesfm_error = str(exc)
            return False


class TimesFMForecastingService:
    def forecast(
        self,
        ticker: str,
        normalized_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        """Called from the workflow pipeline."""
        window = normalized_bundle["feature_window"]
        closes = [row["close"] for row in window]
        series = {
            "close": closes,
            "volume": [row["volume"] for row in window],
            "vwap": [row["vwap"] for row in window],
            "rsi": [row["rsi"] for row in window],
        }
        latest = window[-1]
        result = self._run_forecast(ticker=ticker, series=series, horizon=5)
        # Augment with pipeline-specific keys the reporting/simulation layers expect
        result["latest_close"] = latest["close"]
        result["delta_5d"] = round(result["forecast"][-1] - latest["close"], 2)
        result["drivers"] = {
            "short_trend": round(latest["close"] - mean(closes[-5:]) if len(closes) >= 5 else 0, 2),
            "reddit_impulse": round(
                (latest["reddit_bullish_ratio"] - latest["reddit_bearish_ratio"])
                * latest["close"]
                * 0.01,
                2,
            ),
            "reddit_avg_sentiment": latest["reddit_avg_sentiment"],
            "reddit_mentions": latest["reddit_mentions"],
            "rsi_drag": round((latest["rsi"] - 50) * 0.03, 2),
        }
        result["forecast_close_1d"] = round(result["forecast"][0], 2)
        result["forecast_close_5d"] = round(result["forecast"][-1], 2)
        result["timesfm_inputs_used"] = normalized_bundle["timesfm_inputs"]
        return result

    def forecast_from_prices(
        self,
        ticker: str,
        close_prices: list[float],
        horizon: int = 5,
    ) -> dict[str, Any]:
        """Forecast directly from raw close prices, bypassing feature_window."""
        series = {"close": close_prices}
        result = self._run_forecast(ticker=ticker, series=series, horizon=horizon)

        _dir_map = {"up": "bullish", "down": "bearish", "sideways": "neutral"}
        direction = _dir_map.get(result.get("direction", "sideways"), "neutral")

        forecast_pts = result.get("forecast", [])
        last_close = close_prices[-1] if close_prices else 0.0
        predicted_return = 0.0
        if last_close and forecast_pts:
            predicted_return = round((forecast_pts[-1] - last_close) / last_close, 6)

        confidence = result.get("confidence", 0.5)
        trend_strength = round(abs(predicted_return) * confidence, 4)

        forecast_deviation = 0.0
        if len(forecast_pts) > 1:
            forecast_deviation = round(stdev(forecast_pts), 4)

        output: dict[str, Any] = {
            "ticker": result["ticker"],
            "provider_mode": result["provider_mode"],
            "direction": direction,
            "predicted_return": predicted_return,
            "confidence": confidence,
            "forecast": forecast_pts,
            "quantiles": result.get("quantiles", {"p10": [], "p50": [], "p90": []}),
            "trend_strength": trend_strength,
            "forecast_deviation": forecast_deviation,
        }

        # Diagnostic dump only — skipped by default so the hot path (ThreadPoolExecutor,
        # one call per symbol per run) does no disk I/O. Enable with FORECAST_DUMP=1.
        if FORECAST_DUMP:
            today_str = date.today().strftime("%Y%m%d")
            raw_dir = _ROOT / "state" / "raw" / "ohlcv"
            raw_dir.mkdir(parents=True, exist_ok=True)

            try:
                with open(raw_dir / f"{ticker.upper()}_timesfm_input_{today_str}.json", "w") as f:
                    json.dump(
                        {"ticker": ticker, "close_prices": close_prices, "horizon": horizon, "date": today_str},
                        f, indent=2,
                    )
            except Exception:
                pass

            try:
                with open(raw_dir / f"{ticker.upper()}_timesfm_output_{today_str}.json", "w") as f:
                    json.dump(output, f, indent=2)
            except Exception:
                pass

        return output

    def run_api(
        self,
        ticker: str,
        series: dict[str, list[float]],
        horizon: int,
    ) -> dict[str, Any]:
        """Called directly from POST /forecast."""
        return self._run_forecast(ticker=ticker, series=series, horizon=horizon)

    def _run_forecast(
        self,
        ticker: str,
        series: dict[str, list[float]],
        horizon: int,
    ) -> dict[str, Any]:
        closes = series.get("close", [])
        # Upside comes ONLY from TimesFM — no formulaic/linear fallback. If the model is
        # unavailable or errors, raise ForecastUnavailable so the caller skips the symbol
        # (no forecast → no upside → no CALL) rather than fabricating a momentum number.
        if not (ENABLE_TIMESFM and _load_timesfm()):
            raise ForecastUnavailable(
                f"TimesFM unavailable ({_timesfm_error or 'ENABLE_TIMESFM disabled'}) — "
                "upside requires TimesFM; no formulaic fallback."
            )
        return self._timesfm_forecast(ticker, series, horizon, closes)

    # -------------------------------------------------------- TimesFM path

    def _timesfm_forecast(
        self,
        ticker: str,
        series: dict[str, list[float]],
        horizon: int,
        closes: list[float],
    ) -> dict[str, Any]:
        import numpy as np

        inputs = [np.array(closes, dtype=np.float32)]
        # TimesFM 2.5 API: forecast(horizon, inputs) -> (point[1,h], quantile[1,h,10]).
        point_forecast, quantile_forecast = _timesfm_model.forecast(horizon=horizon, inputs=inputs)
        pts = [round(float(v), 4) for v in point_forecast[0][:horizon]]
        # quantile head: index 0 is the mean; 1..9 are deciles q10..q90.
        nq = quantile_forecast.shape[2]
        q10_idx, q50_idx, q90_idx = (1, 5, 9) if nq >= 10 else (max(1, nq // 10), nq // 2, nq - 1)
        q10 = [round(float(v), 4) for v in quantile_forecast[0, :horizon, q10_idx]]
        q50 = [round(float(v), 4) for v in quantile_forecast[0, :horizon, q50_idx]]
        q90 = [round(float(v), 4) for v in quantile_forecast[0, :horizon, q90_idx]]
        last_close = closes[-1] if closes else 0.0
        direction, magnitude_conf = _derive_direction(last_close, pts)
        interval_conf = _interval_confidence(last_close, q10, q90)
        # Combine point-forecast magnitude confidence with the quantile-spread confidence
        # MULTIPLICATIVELY: a wide q10-q90 band (high model uncertainty) genuinely PENALIZES
        # confidence rather than being averaged away. Averaging would inflate every weak
        # forecast (a 0.5 magnitude × a near-1.0 interval leg would lift to ~0.75), silently
        # pushing low-conviction forecasts past the F2 news-override weak-confidence threshold.
        confidence = round(max(0.0, min(1.0, magnitude_conf * interval_conf)), 3)
        return {
            "ticker": ticker.upper(),
            "provider_mode": "timesfm_2p5_200m_pytorch",
            "horizon": horizon,
            "forecast": pts,
            "quantiles": {"p10": q10, "p50": q50, "p90": q90},
            "direction": direction,
            "confidence": confidence,
        }


# ------------------------------------------------------------------ helpers

def _derive_direction(
    last_close: float,
    forecast: list[float],
) -> tuple[str, float]:
    if not forecast:
        return "sideways", 0.5
    final = forecast[-1]
    delta_pct = (final - last_close) / max(abs(last_close), 1e-9)
    if delta_pct > 0.005:
        direction = "up"
    elif delta_pct < -0.005:
        direction = "down"
    else:
        direction = "sideways"
    # Confidence scales with magnitude, capped at 0.95
    confidence = round(min(0.95, 0.5 + abs(delta_pct) * 8), 3)
    return direction, confidence


def _interval_confidence(last_close: float, q10: list[float], q90: list[float], k: float = 0.10) -> float:
    """Confidence contribution from TimesFM's quantile spread.

    A wide q10-q90 band (relative to last_close) means the model itself is uncertain about
    the forecast, even if the point forecast's magnitude looks confident — e.g. a +3% point
    forecast with q10=-10%/q90=+16% is far less trustworthy than one with q10=+2.5%/q90=+3.5%.
    ``k`` sets how much band width (as a fraction of last_close) fully zeroes out confidence;
    k=0.10 means a band equal to 10% of last_close drives interval confidence to 0. Real 5-day
    bands run ~5-15% of price, so this range actually discriminates tight vs wide (a larger k
    like 0.5 would leave the interval leg pinned near 1.0 and unable to penalize anything).

    Returns a NEUTRAL 0.5 (not 1.0) when quantiles are missing or last_close is 0 — absent
    band data is least-trustworthy, so it must not award maximum confidence.
    """
    if not q10 or not q90 or not last_close:
        return 0.5
    band = abs(q90[-1] - q10[-1])
    denom = k * abs(last_close)
    if denom <= 0:
        return 0.5
    return max(0.0, min(1.0, 1 - band / denom))

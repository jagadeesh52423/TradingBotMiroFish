"""Upside comes only from TimesFM — no formulaic fallback (raises when unavailable)."""
from __future__ import annotations

import pytest

import services.forecasting.forecasting_service as fs
from services.forecasting.forecasting_service import TimesFMForecastingService, ForecastUnavailable


def test_raises_when_timesfm_disabled(monkeypatch):
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", False)
    with pytest.raises(ForecastUnavailable):
        TimesFMForecastingService().forecast_from_prices("SBIN", [100, 101, 102, 103, 104], horizon=5)


def test_raises_when_timesfm_load_fails(monkeypatch):
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_load_timesfm", lambda: False)
    monkeypatch.setattr(fs, "_timesfm_error", "no torch")
    with pytest.raises(ForecastUnavailable):
        TimesFMForecastingService().forecast_from_prices("SBIN", [100, 101, 102], horizon=5)


def test_no_fallback_method_exists():
    # the linear-extrapolation fallback must be gone (no formulaic upside anywhere).
    assert not hasattr(TimesFMForecastingService, "_fallback_forecast")


def test_uses_timesfm_when_available(monkeypatch):
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_load_timesfm", lambda: True)
    svc = TimesFMForecastingService()

    def _fake_tf(ticker, series, horizon, closes):
        return {"ticker": ticker.upper(), "provider_mode": "timesfm_2p5_200m_pytorch",
                "horizon": horizon, "forecast": [110.0] * horizon,
                "quantiles": {"p10": [], "p50": [], "p90": []},
                "direction": "up", "confidence": 0.7}
    monkeypatch.setattr(svc, "_timesfm_forecast", _fake_tf)
    out = svc.forecast_from_prices("SBIN", [100, 101, 102], horizon=5)
    assert out["provider_mode"] == "timesfm_2p5_200m_pytorch"
    assert out["predicted_return"] == round((110.0 - 102) / 102, 6)  # from TimesFM pts, not momentum

"""Upside comes only from TimesFM — no formulaic fallback (raises when unavailable)."""
from __future__ import annotations

import sys
import threading
import time
import types

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


def test_forecast_from_prices_does_not_write_files_by_default(monkeypatch, tmp_path):
    """Per-symbol disk I/O (state/raw/ohlcv/*.json) is a hot-path cost paid on every
    ThreadPoolExecutor call — it must be opt-in (FORECAST_DUMP=1), not on by default."""
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_load_timesfm", lambda: True)
    monkeypatch.setattr(fs, "FORECAST_DUMP", False)
    monkeypatch.setattr(fs, "_ROOT", tmp_path)
    svc = TimesFMForecastingService()

    def _fake_tf(ticker, series, horizon, closes):
        return {"ticker": ticker.upper(), "provider_mode": "timesfm_2p5_200m_pytorch",
                "horizon": horizon, "forecast": [110.0] * horizon,
                "quantiles": {"p10": [], "p50": [], "p90": []},
                "direction": "up", "confidence": 0.7}
    monkeypatch.setattr(svc, "_timesfm_forecast", _fake_tf)
    svc.forecast_from_prices("SBIN", [100, 101, 102], horizon=5)
    assert not (tmp_path / "state" / "raw" / "ohlcv").exists()


def test_forecast_from_prices_writes_files_when_opted_in(monkeypatch, tmp_path):
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_load_timesfm", lambda: True)
    monkeypatch.setattr(fs, "FORECAST_DUMP", True)
    monkeypatch.setattr(fs, "_ROOT", tmp_path)
    svc = TimesFMForecastingService()

    def _fake_tf(ticker, series, horizon, closes):
        return {"ticker": ticker.upper(), "provider_mode": "timesfm_2p5_200m_pytorch",
                "horizon": horizon, "forecast": [110.0] * horizon,
                "quantiles": {"p10": [], "p50": [], "p90": []},
                "direction": "up", "confidence": 0.7}
    monkeypatch.setattr(svc, "_timesfm_forecast", _fake_tf)
    svc.forecast_from_prices("SBIN", [100, 101, 102], horizon=5)
    raw_dir = tmp_path / "state" / "raw" / "ohlcv"
    assert list(raw_dir.glob("SBIN_timesfm_*.json")), "expected dump files under FORECAST_DUMP=1"


# ---------------------------------------------------------------------------
# _load_timesfm() thread-safety — two threads must not both from_pretrained+compile
# ---------------------------------------------------------------------------

def test_load_timesfm_is_thread_safe_single_load(monkeypatch):
    monkeypatch.setattr(fs, "_timesfm_model", None)
    monkeypatch.setattr(fs, "_timesfm_error", None)

    load_calls: list[str] = []

    class _FakeModel:
        def compile(self, cfg):
            pass

    class _FakeTimesFMCls:
        @staticmethod
        def from_pretrained(name):
            load_calls.append(name)
            time.sleep(0.05)  # widen the race window so an unlocked version would double-load
            return _FakeModel()

    fake_timesfm_module = types.SimpleNamespace(
        TimesFM_2p5_200M_torch=_FakeTimesFMCls,
        ForecastConfig=lambda **kw: kw,
    )
    fake_torch_module = types.ModuleType("torch")

    monkeypatch.setitem(sys.modules, "timesfm", fake_timesfm_module)
    monkeypatch.setitem(sys.modules, "torch", fake_torch_module)

    threads = [threading.Thread(target=fs._load_timesfm) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(load_calls) == 1, "from_pretrained must be called exactly once under concurrent load"
    assert fs._timesfm_model is not None


# ---------------------------------------------------------------------------
# Quantile-spread confidence — same point forecast, different q10/q90 band width
# ---------------------------------------------------------------------------

def test_confidence_reduced_by_wide_quantile_spread(monkeypatch):
    """A tight q10/q90 band and a wide one around the SAME point forecast must not
    produce identical confidence — the wide band signals more model uncertainty."""
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_load_timesfm", lambda: True)

    def _make_fake_model(q10_val, q90_val):
        class _FakeModel:
            @staticmethod
            def forecast(horizon, inputs):
                import numpy as np
                point = np.array([[103.0] * horizon])
                quantiles = np.zeros((1, horizon, 10))
                quantiles[0, :, 5] = 103.0  # q50
                quantiles[0, :, 1] = q10_val
                quantiles[0, :, 9] = q90_val
                return point, quantiles
        return _FakeModel()

    svc = TimesFMForecastingService()
    closes = [100.0] * 9 + [100.0]

    monkeypatch.setattr(fs, "_timesfm_model", _make_fake_model(102.5, 103.5))  # tight band
    tight = svc._timesfm_forecast("SBIN", {"close": closes}, 5, closes)

    monkeypatch.setattr(fs, "_timesfm_model", _make_fake_model(90.0, 116.0))  # wide band
    wide = svc._timesfm_forecast("SBIN", {"close": closes}, 5, closes)

    assert tight["forecast"] == wide["forecast"]  # same point forecast
    assert tight["confidence"] > wide["confidence"], (
        "wide q10-q90 band must reduce confidence relative to a tight band at the same point forecast"
    )
    # Multiplicative combine: a wide band must PENALIZE meaningfully, not average away.
    assert wide["confidence"] < 0.3, f"wide band should collapse confidence, got {wide['confidence']}"


def test_weak_magnitude_tight_band_not_inflated(monkeypatch):
    """A weak-magnitude forecast (point barely above last_close) with a TIGHT band must NOT
    be lifted above the F2 news-override weak-confidence threshold (~0.55). Multiplicative
    combine keeps a weak magnitude weak; the additive average would have inflated it."""
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_load_timesfm", lambda: True)

    class _FakeModel:
        @staticmethod
        def forecast(horizon, inputs):
            import numpy as np
            point = np.array([[100.4] * horizon])          # +0.4% → weak magnitude
            quantiles = np.zeros((1, horizon, 10))
            quantiles[0, :, 5] = 100.4                       # q50
            quantiles[0, :, 1] = 99.9                        # tight band (~1% of price)
            quantiles[0, :, 9] = 100.9
            return point, quantiles

    monkeypatch.setattr(fs, "_timesfm_model", _FakeModel())
    svc = TimesFMForecastingService()
    closes = [100.0] * 10
    out = svc._timesfm_forecast("SBIN", {"close": closes}, 5, closes)
    assert out["confidence"] <= 0.55, (
        f"weak forecast with a tight band must stay weak (<=0.55), got {out['confidence']}"
    )


def test_interval_confidence_helper_directly():
    from services.forecasting.forecasting_service import _interval_confidence

    tight = _interval_confidence(100.0, [99.5], [100.5])   # 1% band
    wide = _interval_confidence(100.0, [95.0], [105.0])    # 10% band
    very_wide = _interval_confidence(100.0, [85.0], [115.0])  # 30% band
    # Smooth exponential decay (k=0.15): tight band → near 1, wider bands decay gracefully
    # WITHOUT cliffing to 0 (the old linear form zeroed a 10% band, crushing every name).
    assert tight > wide > very_wide
    assert tight > 0.9, "a 1% band should keep confidence high"
    assert 0.4 < wide < 0.6, "a 10% band should be reduced but NOT crushed to ~0"
    assert very_wide < 0.15, "a 30% band should be strongly penalized"
    assert 0.0 <= very_wide <= 1.0 and 0.0 <= tight <= 1.0


def test_interval_confidence_neutral_when_quantiles_missing():
    from services.forecasting.forecasting_service import _interval_confidence

    # Absent band data is least trustworthy → neutral 0.5, never max 1.0.
    assert _interval_confidence(100.0, [], []) == 0.5
    assert _interval_confidence(100.0, [99.0], []) == 0.5
    assert _interval_confidence(0.0, [99.0], [101.0]) == 0.5


def test_warm_up_retries_transient_failure(monkeypatch):
    import services.forecasting.forecasting_service as fs
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_timesfm_model", None)
    monkeypatch.setattr(fs, "_timesfm_error", None)
    calls = {"n": 0}
    def flaky_load():
        calls["n"] += 1
        if calls["n"] < 3:           # first two attempts "fail" transiently
            fs._timesfm_error = "transient hf hiccup"
            return False
        fs._timesfm_model = object()  # third succeeds
        return True
    monkeypatch.setattr(fs, "_load_timesfm", flaky_load)
    assert fs.warm_up_timesfm(retries=3, backoff=0.001) is True
    assert calls["n"] == 3           # retried, not latched on the first failure


def test_warm_up_gives_up_after_retries(monkeypatch):
    import services.forecasting.forecasting_service as fs
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_timesfm_model", None)
    monkeypatch.setattr(fs, "_timesfm_error", None)
    def always_fail():
        fs._timesfm_error = "no torch"
        return False
    monkeypatch.setattr(fs, "_load_timesfm", always_fail)
    assert fs.warm_up_timesfm(retries=3, backoff=0.001) is False
    assert fs._timesfm_error == "no torch"  # genuine failure stays set for the run


def test_warm_up_noop_when_already_loaded(monkeypatch):
    import services.forecasting.forecasting_service as fs
    monkeypatch.setattr(fs, "ENABLE_TIMESFM", True)
    monkeypatch.setattr(fs, "_timesfm_model", object())
    monkeypatch.setattr(fs, "_load_timesfm", lambda: (_ for _ in ()).throw(AssertionError("should not load")))
    assert fs.warm_up_timesfm() is True  # already loaded → no reload attempt

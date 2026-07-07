"""§8 F&O positioning: PCR + OI extraction, classifier, provider fail-safe."""
from __future__ import annotations

from services.nubra_client.fno_oi import FyersOptionProvider, pcr_label
from services.fyers_client.fyers_data_provider import _extract_option_summary


def test_extract_option_summary_computes_pcr():
    resp = {"data": {"callOi": 56233000, "putOi": 38223000}}
    out = _extract_option_summary(resp)
    assert out["call_oi"] == 56233000 and out["put_oi"] == 38223000
    assert out["pcr"] == round(38223000 / 56233000, 3)


def test_extract_none_for_cash_only():
    assert _extract_option_summary({"data": {"callOi": 0, "putOi": 0}}) is None
    assert _extract_option_summary({"data": {}}) is None
    assert _extract_option_summary({}) is None


def test_pcr_label_buckets():
    assert pcr_label(1.5) == "put_heavy"
    assert pcr_label(0.5) == "call_heavy"
    assert pcr_label(1.0) == "balanced"
    assert pcr_label(None) is None


class _FakeFyers:
    def __init__(self, summary):
        self._s = summary

    def option_summary(self, symbol):
        return self._s


def test_provider_returns_summary():
    p = FyersOptionProvider(_FakeFyers({"call_oi": 10, "put_oi": 5, "pcr": 0.5}))
    assert p.summary("RELIANCE")["pcr"] == 0.5


def test_provider_fails_safe():
    class _Boom:
        def option_summary(self, s):
            raise RuntimeError("no token")
    assert FyersOptionProvider(_Boom()).summary("RELIANCE") is None


# --- OI buildup (§8, descriptive) -------------------------------------------

def test_oi_buildup_label():
    from services.nubra_client.fno_oi import oi_buildup_label
    assert oi_buildup_label(10000, 2000) == "call_buildup"
    assert oi_buildup_label(2000, 10000) == "put_buildup"
    assert oi_buildup_label(1000, 1000) == "balanced"
    assert oi_buildup_label(0, 0) == "flat"
    assert oi_buildup_label(None, 5) is None


def test_extract_option_summary_oi_change():
    from services.fyers_client.fyers_data_provider import _extract_option_summary
    resp = {"data": {"callOi": 100, "putOi": 60, "optionsChain": [
        {"option_type": "CE", "oich": 5000}, {"option_type": "CE", "oich": 3000},
        {"option_type": "PE", "oich": 1000}, {"option_type": "PE", "oich": None}]}}
    out = _extract_option_summary(resp)
    assert out["call_oi_change"] == 8000 and out["put_oi_change"] == 1000


def test_fyers_call_retries_on_rate_limit(monkeypatch):
    import services.fyers_client.fyers_data_provider as m
    monkeypatch.setattr(m, "_RL_BACKOFF", 0.001)
    calls = {"n": 0}
    def flaky(_):
        calls["n"] += 1
        return {"s": "error", "code": 429} if calls["n"] < 3 else {"s": "ok", "d": [1]}
    out = m._call_with_backoff(flaky, "x")
    assert out == {"s": "ok", "d": [1]} and calls["n"] == 3


def test_fyers_call_gives_up_after_retries(monkeypatch):
    import services.fyers_client.fyers_data_provider as m
    monkeypatch.setattr(m, "_RL_BACKOFF", 0.001)
    monkeypatch.setattr(m, "_RL_RETRIES", 3)
    out = m._call_with_backoff(lambda _: {"s": "error", "code": 429}, "x")
    assert out == {"s": "error", "code": 429}  # returns last body for normal handling

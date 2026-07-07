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

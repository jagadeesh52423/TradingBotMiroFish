"""Offline tests for FyersDataProvider — the fyers SDK is fully mocked.

No real fyers-apiv3 install, no network, no account. Two mocking strategies:
  - inject a fake client via the constructor `client=` seam (mapping tests), and
  - inject a fake `fyers_apiv3` module into sys.modules to exercise the lazy
    `from fyers_apiv3 import fyersModel` import path (patch-where-imported).
"""
from __future__ import annotations

import pathlib
import sys
import types
from decimal import Decimal

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT))

from services.fyers_client.fyers_data_provider import FyersDataProvider


# Fyers candle = [epoch_seconds, open, high, low, close, volume]; intentionally
# out of order to prove the provider sorts oldest-first.
_CANDLES = [
    [1_700_172_000, 101.0, 102.0, 100.0, 101.5, 1000],  # later
    [1_700_085_600, 100.0, 101.0, 99.0, 100.5, 900],    # earlier
]


class _FakeFyersClient:
    def __init__(self):
        self.history_request = None
        self.quotes_request = None

    def history(self, request):
        self.history_request = request
        return {"s": "ok", "candles": list(_CANDLES)}

    def quotes(self, request):
        self.quotes_request = request
        return {"s": "ok", "d": [{"n": request["symbols"], "v": {"lp": 250.75}}]}


@pytest.fixture
def fake_fyers_module(monkeypatch):
    """Install a fake `fyers_apiv3` package so the lazy import resolves to it."""
    constructed = {}

    class _FakeModel:
        def __init__(self, client_id=None, token=None, is_async=False):
            constructed["client_id"] = client_id
            constructed["token"] = token
            constructed["is_async"] = is_async
            self._inner = _FakeFyersClient()

        def history(self, request):
            return self._inner.history(request)

        def quotes(self, request):
            return self._inner.quotes(request)

    pkg = types.ModuleType("fyers_apiv3")
    sub = types.ModuleType("fyers_apiv3.fyersModel")
    sub.FyersModel = _FakeModel
    pkg.fyersModel = sub
    monkeypatch.setitem(sys.modules, "fyers_apiv3", pkg)
    monkeypatch.setitem(sys.modules, "fyers_apiv3.fyersModel", sub)
    return constructed


# ---------------------------------------------------------------------------
# Symbol formatting
# ---------------------------------------------------------------------------

class TestSymbolFormatting:
    def test_nse_eq_format(self):
        assert FyersDataProvider._to_fyers_symbol("SBIN") == "NSE:SBIN-EQ"


# ---------------------------------------------------------------------------
# historical — mapping + ordering (injected client seam)
# ---------------------------------------------------------------------------

class TestHistorical:
    def _provider(self):
        fake = _FakeFyersClient()
        return FyersDataProvider("cid", "tok", client=fake), fake

    def test_maps_candles_to_close_timestamp(self):
        provider, _ = self._provider()
        bars = provider.historical("SBIN", lookback=5)
        assert all(set(bar) == {"close", "timestamp"} for bar in bars)

    def test_close_is_float_from_index_4(self):
        provider, _ = self._provider()
        bars = provider.historical("SBIN", lookback=5)
        assert all(isinstance(bar["close"], float) for bar in bars)
        # closes are candle[4]: 100.5 (earlier) then 101.5 (later)
        assert [bar["close"] for bar in bars] == [100.5, 101.5]

    def test_timestamp_is_epoch_ms(self):
        provider, _ = self._provider()
        bars = provider.historical("SBIN", lookback=5)
        assert bars[0]["timestamp"] == 1_700_085_600 * 1000

    def test_sorted_oldest_first(self):
        provider, _ = self._provider()
        bars = provider.historical("SBIN", lookback=5)
        timestamps = [bar["timestamp"] for bar in bars]
        assert timestamps == sorted(timestamps)

    def test_request_uses_fyers_symbol_and_resolution(self):
        provider, fake = self._provider()
        provider.historical("SBIN", interval="1d", lookback=5)
        assert fake.history_request["symbol"] == "NSE:SBIN-EQ"
        assert fake.history_request["resolution"] == "1D"

    def test_lookback_truncates(self):
        provider, _ = self._provider()
        bars = provider.historical("SBIN", lookback=1)
        assert len(bars) == 1
        # the single most-recent bar
        assert bars[0]["close"] == 101.5


# ---------------------------------------------------------------------------
# current_price — Decimal mapping
# ---------------------------------------------------------------------------

class TestCurrentPrice:
    def test_returns_decimal(self):
        provider = FyersDataProvider("cid", "tok", client=_FakeFyersClient())
        price = provider.current_price("SBIN")
        assert price == Decimal("250.75")
        assert isinstance(price, Decimal)

    def test_quotes_request_uses_fyers_symbol(self):
        fake = _FakeFyersClient()
        provider = FyersDataProvider("cid", "tok", client=fake)
        provider.current_price("RELIANCE")
        assert fake.quotes_request == {"symbols": "NSE:RELIANCE-EQ"}


# ---------------------------------------------------------------------------
# Missing token — clear error, client NOT built
# ---------------------------------------------------------------------------

class TestMissingToken:
    def test_historical_without_token_raises(self):
        provider = FyersDataProvider("cid", None)
        with pytest.raises(RuntimeError, match="FYERS_ACCESS_TOKEN missing"):
            provider.historical("SBIN")
        assert provider._client is None

    def test_current_price_without_token_raises(self):
        provider = FyersDataProvider("cid", None)
        with pytest.raises(RuntimeError, match="FYERS_ACCESS_TOKEN missing"):
            provider.current_price("SBIN")
        assert provider._client is None

    def test_no_silent_nubra_fallback(self):
        """Missing token must raise — never silently degrade to other data."""
        provider = FyersDataProvider(None, None)
        with pytest.raises(RuntimeError):
            provider.current_price("SBIN")


# ---------------------------------------------------------------------------
# Lazy SDK build — patch where imported (fake fyers_apiv3 module)
# ---------------------------------------------------------------------------

class TestLazyClientBuild:
    def test_builds_fyersmodel_with_creds(self, fake_fyers_module):
        provider = FyersDataProvider("my-client-id", "my-token")
        provider.current_price("SBIN")  # triggers lazy build
        assert fake_fyers_module["client_id"] == "my-client-id"
        assert fake_fyers_module["token"] == "my-token"

    def test_lazy_built_client_is_cached(self, fake_fyers_module):
        provider = FyersDataProvider("cid", "tok")
        provider.current_price("SBIN")
        first = provider._client
        provider.current_price("SBIN")
        assert provider._client is first

    def test_lazy_historical_maps_candles(self, fake_fyers_module):
        provider = FyersDataProvider("cid", "tok")
        bars = provider.historical("SBIN", lookback=5)
        assert [bar["close"] for bar in bars] == [100.5, 101.5]


# ---------------------------------------------------------------------------
# from_config — reads config["fyers"] then env
# ---------------------------------------------------------------------------

class TestFromConfig:
    def test_reads_config_fyers_block(self):
        cfg = {"fyers": {"client_id": "cfg-id", "access_token": "cfg-tok"}}
        provider = FyersDataProvider.from_config(cfg)
        assert provider._client_id == "cfg-id"
        assert provider._access_token == "cfg-tok"

    def test_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("FYERS_CLIENT_ID", "env-id")
        monkeypatch.setenv("FYERS_ACCESS_TOKEN", "env-tok")
        provider = FyersDataProvider.from_config({})
        assert provider._client_id == "env-id"
        assert provider._access_token == "env-tok"

    def test_config_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("FYERS_CLIENT_ID", "env-id")
        provider = FyersDataProvider.from_config({"fyers": {"client_id": "cfg-id"}})
        assert provider._client_id == "cfg-id"

    def test_missing_creds_still_constructs(self, monkeypatch):
        monkeypatch.delenv("FYERS_CLIENT_ID", raising=False)
        monkeypatch.delenv("FYERS_ACCESS_TOKEN", raising=False)
        provider = FyersDataProvider.from_config({})
        assert provider._client_id is None
        assert provider._access_token is None
        assert provider._client is None

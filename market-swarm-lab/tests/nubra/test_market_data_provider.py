"""Offline tests for the MarketDataProvider ABC + registry + stack injection.

No live SDK, no network: NubraClient is checked structurally (subclass/methods),
Fyers is resolved via from_config (construct-only), and the stack swap uses stubs.
"""
from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT))

from services.nubra_client.equity_assembly import build_equity_stack
from services.nubra_client.market_data_provider import MarketDataProvider
from services.nubra_client.market_data_registry import (
    _PROVIDER_REGISTRY,
    get_provider,
    register_provider,
)
from services.nubra_client.nubra_client import NubraClient
# Importing the package registers "fyers" via its @register_provider decorator.
from services.fyers_client.fyers_data_provider import FyersDataProvider


_CFG = {
    "env": "UAT",
    "whitelist": ["SBIN", "RELIANCE", "TATACONSUM"],
    "risk_per_trade_pct": 0.5,
}


class _StubProvider(MarketDataProvider):
    """In-memory MarketDataProvider used to prove the stack swap end-to-end."""

    @classmethod
    def from_config(cls, config: dict) -> "_StubProvider":
        return cls()

    def current_price(self, symbol: str) -> Decimal:
        return Decimal("123.45")

    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]:
        return [{"close": 100.0 + i, "timestamp": i * 86_400_000} for i in range(lookback)]


class _FakeNubraClient:
    """Minimal NubraClient-like object for build_equity_stack (orders side)."""

    def current_price(self, symbol):
        return Decimal("500.00")

    def historical(self, symbol, interval="1d", lookback=20):
        return [{"close": 500.0 + i, "timestamp": i * 86_400_000} for i in range(lookback)]

    def funds(self):
        return {"net_margin_available": 1_000_000}

    def place_order(self, **kwargs):
        return {"order_id": "fake-001"}

    def get_positions(self):
        return []

    def get_order_status(self, order_id):
        return {"status": "COMPLETE"}


# ---------------------------------------------------------------------------
# Registry resolution
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_nubra_registered(self):
        assert _PROVIDER_REGISTRY["nubra"] is NubraClient

    def test_fyers_registered(self):
        assert _PROVIDER_REGISTRY["fyers"] is FyersDataProvider

    def test_unknown_provider_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown market-data provider"):
            get_provider("does-not-exist", _CFG)

    def test_unknown_provider_lists_known(self):
        with pytest.raises(ValueError, match="nubra"):
            get_provider("nope", _CFG)

    def test_get_provider_fyers_returns_instance(self):
        provider = get_provider("fyers", _CFG)
        assert isinstance(provider, FyersDataProvider)
        assert isinstance(provider, MarketDataProvider)

    def test_register_provider_adds_to_registry(self):
        @register_provider("_tmp_test_provider")
        class _Tmp(_StubProvider):
            pass

        try:
            assert get_provider("_tmp_test_provider", _CFG).__class__ is _Tmp
        finally:
            _PROVIDER_REGISTRY.pop("_tmp_test_provider", None)


# ---------------------------------------------------------------------------
# NubraClient satisfies the ABC (no live session needed)
# ---------------------------------------------------------------------------

class TestNubraClientSatisfiesAbc:
    def test_nubra_is_subclass(self):
        assert issubclass(NubraClient, MarketDataProvider)

    def test_nubra_has_required_methods(self):
        for method in ("current_price", "historical", "from_config"):
            assert hasattr(NubraClient, method)


# ---------------------------------------------------------------------------
# Stack injection — provider swap works end-to-end
# ---------------------------------------------------------------------------

class TestStackInjection:
    def test_explicit_data_provider_used_as_market_data(self):
        stub = _StubProvider()
        stack = build_equity_stack(
            "nubra_uat",
            _CFG,
            client_factory=lambda cfg: _FakeNubraClient(),
            data_provider=stub,
        )
        assert stack.market_data is stub

    def test_effective_ltp_uses_injected_provider(self):
        stub = _StubProvider()
        stack = build_equity_stack(
            "nubra_uat",
            _CFG,
            client_factory=lambda cfg: _FakeNubraClient(),
            data_provider=stub,
        )
        # translator's ltp callable is the injected provider's current_price.
        assert stack.translator._ltp("SBIN") == Decimal("123.45")

    def test_default_provider_reuses_nubra_client(self):
        """data_provider=nubra (default) → market_data is the SAME NubraClient
        built by client_factory (no double session, behaviour unchanged)."""
        fake = _FakeNubraClient()
        stack = build_equity_stack(
            "nubra_uat", _CFG, client_factory=lambda cfg: fake
        )
        assert stack.market_data is fake

    def test_config_data_provider_fyers_resolves_fyers(self):
        cfg = {**_CFG, "data_provider": "fyers"}
        stack = build_equity_stack(
            "nubra_uat", cfg, client_factory=lambda c: _FakeNubraClient()
        )
        assert isinstance(stack.market_data, FyersDataProvider)

    def test_orders_stay_on_nubra_even_with_swapped_provider(self):
        """Broker must remain the NubraClient-backed broker, not the data provider."""
        from services.nubra_client.nubra_broker import NubraBroker

        fake = _FakeNubraClient()
        stack = build_equity_stack(
            "nubra_uat", _CFG, client_factory=lambda cfg: fake, data_provider=_StubProvider()
        )
        assert isinstance(stack.broker, NubraBroker)

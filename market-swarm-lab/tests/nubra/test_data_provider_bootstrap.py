"""Regression test: get_provider resolves providers WITHOUT directly importing
FyersDataProvider or NubraClient — proves the registry bootstrap fires on demand.

This file intentionally has NO top-level import of FyersDataProvider or NubraClient.
That is the whole point: if the bootstrap is missing, these tests fail with
ValueError('Unknown market-data provider').
"""
from __future__ import annotations

import sys

import pytest

# ---------------------------------------------------------------------------
# NOTE: do NOT add `from services.fyers_client.fyers_data_provider import ...`
# or `from services.nubra_client.nubra_client import ...` at module level.
# Those imports are what masked the bug in the existing test suite (BP-123).
# ---------------------------------------------------------------------------


def _reset_registry(monkeypatch):
    """Pop known providers + reset the bootstrap flag to simulate a fresh process.

    Unloads the provider modules from sys.modules so re-import via the bootstrap
    re-runs the @register_provider decorators even if another test file imported them.
    """
    import services.nubra_client.market_data_registry as reg_mod

    # Unload the provider modules so the bootstrap re-executes their module bodies.
    for mod_key in (
        "services.nubra_client.nubra_client",
        "services.fyers_client.fyers_data_provider",
    ):
        sys.modules.pop(mod_key, None)

    monkeypatch.delitem(reg_mod._PROVIDER_REGISTRY, "fyers", raising=False)
    monkeypatch.delitem(reg_mod._PROVIDER_REGISTRY, "nubra", raising=False)
    monkeypatch.setattr(reg_mod, "_bootstrapped", False)


class TestBootstrapResolvesWithoutDirectImport:
    """get_provider must work even when no caller has imported the provider module."""

    def test_fyers_resolves_via_bootstrap(self, monkeypatch):
        _reset_registry(monkeypatch)
        from services.nubra_client.market_data_registry import get_provider

        cfg = {"fyers": {"client_id": "x", "access_token": "y"}}
        provider = get_provider("fyers", cfg)
        assert type(provider).__name__ == "FyersDataProvider"

    def test_nubra_registered_via_bootstrap(self, monkeypatch):
        _reset_registry(monkeypatch)
        import services.nubra_client.market_data_registry as reg_mod
        from services.nubra_client.market_data_registry import _ensure_providers_loaded

        _ensure_providers_loaded()
        assert "nubra" in reg_mod._PROVIDER_REGISTRY

    def test_unknown_provider_raises_valueerror(self, monkeypatch):
        _reset_registry(monkeypatch)
        from services.nubra_client.market_data_registry import get_provider

        with pytest.raises(ValueError, match="Unknown market-data provider"):
            get_provider("does-not-exist", {})

    def test_bootstrap_is_idempotent(self, monkeypatch):
        """Calling _ensure_providers_loaded twice must not double-register or raise."""
        _reset_registry(monkeypatch)
        from services.nubra_client.market_data_registry import _ensure_providers_loaded
        import services.nubra_client.market_data_registry as reg_mod

        _ensure_providers_loaded()
        registry_snapshot = dict(reg_mod._PROVIDER_REGISTRY)
        _ensure_providers_loaded()
        assert reg_mod._PROVIDER_REGISTRY == registry_snapshot

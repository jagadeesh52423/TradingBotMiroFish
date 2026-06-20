"""Market-data provider registry — pluggable OHLCV + price sources.

# implement MarketDataProvider + register via @register_provider to add a new source.

Strategy/registry pattern (mirrors signal_strategies): callers resolve a named
provider via get_provider(); adding a new source needs only a new class +
@register_provider entry, with zero edits to callers.
"""
from __future__ import annotations

from services.nubra_client.market_data_provider import MarketDataProvider

# Registry keyed by provider name. Self-registered at module import.
_PROVIDER_REGISTRY: dict[str, type[MarketDataProvider]] = {}

# Guards the one-time bootstrap import so _ensure_providers_loaded() is idempotent.
_bootstrapped: bool = False


def register_provider(name: str):
    """Class decorator that adds the provider to _PROVIDER_REGISTRY under *name*."""
    def decorator(cls: type[MarketDataProvider]) -> type[MarketDataProvider]:
        _PROVIDER_REGISTRY[name] = cls
        return cls
    return decorator


def _ensure_providers_loaded() -> None:
    """Import all provider modules so their @register_provider decorators fire.

    # To add a new provider: new module with @register_provider("name") + one import here.
    Idempotent — safe to call on every get_provider() invocation.
    """
    global _bootstrapped
    if _bootstrapped:
        return
    # Function-local imports avoid circular dependency (fyers_data_provider imports
    # register_provider from this module).
    import services.nubra_client.nubra_client  # noqa: F401 — triggers @register_provider("nubra")
    import services.fyers_client.fyers_data_provider  # noqa: F401 — triggers @register_provider("fyers")
    _bootstrapped = True


def get_provider(name: str, config: dict) -> MarketDataProvider:
    """Return an instantiated provider by registry name, built via its from_config.

    Raises:
        ValueError: if *name* is not in the registry.
    """
    _ensure_providers_loaded()
    if name not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown market-data provider {name!r}. Available: {sorted(_PROVIDER_REGISTRY)}"
        )
    return _PROVIDER_REGISTRY[name].from_config(config)

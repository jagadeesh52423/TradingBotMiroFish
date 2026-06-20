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


def register_provider(name: str):
    """Class decorator that adds the provider to _PROVIDER_REGISTRY under *name*."""
    def decorator(cls: type[MarketDataProvider]) -> type[MarketDataProvider]:
        _PROVIDER_REGISTRY[name] = cls
        return cls
    return decorator


def get_provider(name: str, config: dict) -> MarketDataProvider:
    """Return an instantiated provider by registry name, built via its from_config.

    Raises:
        ValueError: if *name* is not in the registry.
    """
    if name not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown market-data provider {name!r}. Available: {sorted(_PROVIDER_REGISTRY)}"
        )
    return _PROVIDER_REGISTRY[name].from_config(config)

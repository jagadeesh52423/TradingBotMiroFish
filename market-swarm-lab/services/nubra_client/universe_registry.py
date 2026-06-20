"""Universe registry — named symbol lists (nifty50 / midcap150 / custom).

# register a universe via register_universe(name, symbols) or config["universes"] to add one.

Mirrors the signal/provider registry pattern: a universe is selectable by name and
new universes are pure config/registry additions, with no edits to callers.
"""
from __future__ import annotations

# Registry keyed by universe name → symbol list.
_UNIVERSE_REGISTRY: dict[str, list[str]] = {}


def register_universe(name: str, symbols: list[str]) -> None:
    _UNIVERSE_REGISTRY[name] = list(symbols)


def load_universes_from_config(config: dict) -> None:
    """Register every universe declared under config["universes"] (name → symbols)."""
    for name, symbols in config.get("universes", {}).items():
        register_universe(name, symbols)


def get_universe(name: str) -> list[str]:
    """Return the symbol list for *name*.

    Raises:
        ValueError: if *name* is not registered.
    """
    if name not in _UNIVERSE_REGISTRY:
        raise ValueError(
            f"Unknown universe {name!r}. Available: {sorted(_UNIVERSE_REGISTRY)}"
        )
    return _UNIVERSE_REGISTRY[name]

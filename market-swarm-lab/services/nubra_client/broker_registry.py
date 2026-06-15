from __future__ import annotations
from typing import Callable
from services.nubra_client.broker_interface import BrokerClient


class BrokerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., BrokerClient]] = {}

    def register(self, mode: str, factory: Callable[..., BrokerClient]) -> None:
        self._factories[mode] = factory

    def get(self, mode: str, **kwargs) -> BrokerClient:
        if mode not in self._factories:
            raise KeyError(f"No broker registered for mode '{mode}'. "
                           f"Known: {sorted(self._factories)}")
        return self._factories[mode](**kwargs)

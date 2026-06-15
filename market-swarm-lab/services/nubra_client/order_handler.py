from __future__ import annotations
from abc import ABC, abstractmethod


# Implement OrderHandler + register in OrderHandlerRegistry to add a new asset class.
class OrderHandler(ABC):
    asset_class: str = ""

    @abstractmethod
    def handle(self, signal: dict, risk: dict, ticker: str) -> dict: ...


class OrderHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, OrderHandler] = {}

    def register(self, handler: OrderHandler) -> None:
        if not handler.asset_class:
            raise ValueError("handler.asset_class must be set")
        self._handlers[handler.asset_class] = handler

    def dispatch(self, asset_class: str, signal: dict, risk: dict, ticker: str) -> dict:
        if asset_class not in self._handlers:
            raise KeyError(
                f"No OrderHandler for asset_class '{asset_class}'. "
                f"Known: {sorted(self._handlers)}")
        return self._handlers[asset_class].handle(signal, risk, ticker)

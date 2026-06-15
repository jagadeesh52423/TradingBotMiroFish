from __future__ import annotations
from typing import Protocol


# Implement PositionProvider to supply broker-truth net qty to translators/handlers.
class PositionProvider(Protocol):
    def net_quantity(self, symbol: str) -> int: ...
    def has_long(self, symbol: str) -> bool: ...


class BrokerPositionProvider:
    def __init__(self, broker):
        self._broker = broker

    def _rows(self) -> dict[str, int]:
        return {r["symbol"]: int(r.get("net_quantity", 0))
                for r in self._broker.get_positions()}

    def net_quantity(self, symbol: str) -> int:
        return self._rows().get(symbol, 0)

    def has_long(self, symbol: str) -> bool:
        return self.net_quantity(symbol) > 0

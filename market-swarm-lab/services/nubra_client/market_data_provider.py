"""MarketDataProvider — pluggable OHLCV + price interface for the equity stack.

# implement this interface + register via @register_provider to add a new market-data source.

Contract (must match NubraClient's existing shapes exactly so providers are swappable):
  - current_price(symbol) -> Decimal (rupees).
  - historical(symbol, interval, lookback) -> list[{"close": float, "timestamp": int ms}]
    sorted oldest-first, at most *lookback* bars.
Each concrete provider also exposes a from_config(cls, config) classmethod used by the registry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal


class MarketDataProvider(ABC):
    @classmethod
    @abstractmethod
    def from_config(cls, config: dict) -> "MarketDataProvider": ...

    @abstractmethod
    def current_price(self, symbol: str) -> Decimal: ...

    @abstractmethod
    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]: ...

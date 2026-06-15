from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class Product(Enum):
    CNC = "CNC"        # delivery / cash
    IDAY = "IDAY"      # intraday (not used in MVP)


class PriceType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class Validity(Enum):
    DAY = "DAY"
    IOC = "IOC"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    OPEN = "OPEN"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


_TERMINAL = {OrderStatus.FILLED, OrderStatus.REJECTED,
             OrderStatus.CANCELLED, OrderStatus.EXPIRED}


@dataclass
class BrokerOrder:
    symbol: str
    side: OrderSide
    qty: int
    price_type: PriceType
    price: Decimal | None
    product: Product
    validity: Validity
    client_tag: str

    def __post_init__(self):
        if self.price_type is PriceType.LIMIT and self.price is None:
            raise ValueError("LIMIT order requires a price")
        if self.qty < 1:
            raise ValueError("qty must be >= 1")


@dataclass
class BrokerOrderResult:
    broker_order_id: str
    client_tag: str
    status: OrderStatus
    submitted_at: str
    raw: dict[str, Any] = field(default_factory=dict)

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

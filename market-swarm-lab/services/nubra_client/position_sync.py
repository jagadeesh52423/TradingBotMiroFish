from __future__ import annotations
from decimal import Decimal
from services.nubra_client.broker_types import BrokerOrder, OrderSide
from services.nubra_client.units import paise_to_rupees


class PositionSync:
    def __init__(self, broker):
        self._broker = broker

    def positions(self) -> list[dict]:
        return list(self._broker.get_positions())

    def funds_sufficient(self, order: BrokerOrder, ltp: Decimal | None = None) -> bool:
        if order.side is OrderSide.SELL:
            return True  # closing a long needs no new margin
        price = order.price if order.price is not None else ltp
        if price is None:
            return False
        cost = Decimal(order.qty) * Decimal(price)
        funds = self._broker.get_funds()
        margin = paise_to_rupees(int(funds.get("net_margin_available", 0)))
        return cost <= margin

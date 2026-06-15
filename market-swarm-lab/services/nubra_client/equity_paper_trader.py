from __future__ import annotations
from decimal import Decimal
from typing import Callable
from itertools import count
from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_types import (
    BrokerOrder, BrokerOrderResult, OrderSide, OrderStatus)


class EquityPaperTrader(BrokerClient):
    def __init__(self, ltp_provider: Callable[[str], Decimal]):
        self._ltp = ltp_provider
        self._ids = count(1)
        self._orders: dict[str, BrokerOrderResult] = {}
        self._net: dict[str, int] = {}
        self._avg: dict[str, Decimal] = {}

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        fill_price = order.price if order.price is not None else self._ltp(order.symbol)
        oid = f"paper-{next(self._ids)}"
        signed = order.qty if order.side is OrderSide.BUY else -order.qty
        prev = self._net.get(order.symbol, 0)
        self._net[order.symbol] = prev + signed
        if order.side is OrderSide.BUY:
            self._avg[order.symbol] = fill_price  # simplistic; MVP
        res = BrokerOrderResult(broker_order_id=oid, client_tag=order.client_tag,
                                status=OrderStatus.FILLED, submitted_at="paper",
                                raw={"fill_price": str(fill_price)})
        self._orders[oid] = res
        return res

    def cancel_order(self, broker_order_id: str) -> bool:
        return False  # paper fills immediately; nothing open to cancel

    def modify_order(self, broker_order_id: str, **changes) -> BrokerOrderResult:
        raise NotImplementedError("paper modify not supported in MVP")

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult | None:
        return self._orders.get(broker_order_id)

    def get_positions(self) -> list[dict]:
        return [{"symbol": symbol, "net_quantity": qty,
                 "avg_price": str(self._avg.get(symbol, Decimal("0")))}
                for symbol, qty in self._net.items() if qty != 0]

    def get_funds(self) -> dict:
        return {"paper": True}

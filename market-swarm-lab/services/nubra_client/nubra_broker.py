from __future__ import annotations

import datetime

from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_types import BrokerOrder, BrokerOrderResult, OrderStatus


class NubraBroker(BrokerClient):
    """BrokerClient adapter over NubraClient for live UAT/prod equity orders."""

    def __init__(self, nubra_client) -> None:
        self._client = nubra_client

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        result = self._client.place_order(
            symbol=order.symbol,
            side=order.side.value,
            qty=order.qty,
            price_type=order.price_type.value,
            price=order.price,
            client_tag=order.client_tag,
        )
        return BrokerOrderResult(
            broker_order_id=result["order_id"],
            client_tag=order.client_tag,
            status=OrderStatus.PENDING,
            submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            raw=result,
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        # UAT MVP: cancel flow requires order book lookups not available in this tier.
        raise NotImplementedError("cancel_order not supported in UAT MVP; use Nubra portal.")

    def modify_order(self, broker_order_id: str, **changes) -> BrokerOrderResult:
        raise NotImplementedError("modify_order not supported in UAT MVP.")

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult | None:
        raise NotImplementedError("get_order_status requires order book polling; not in MVP.")

    def get_positions(self) -> list[dict]:
        # Positions polling requires an SDK call not available offline; return empty for now.
        return []

    def get_funds(self) -> dict:
        return {"live": True, "broker": "nubra"}

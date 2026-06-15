from __future__ import annotations

import json
from datetime import datetime, timezone

from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_types import BrokerOrder, BrokerOrderResult, OrderStatus

_STATUS_MAP = {
    "ORDER_STATUS_PENDING": OrderStatus.PENDING,
    "ORDER_STATUS_SENT": OrderStatus.SENT,
    "ORDER_STATUS_OPEN": OrderStatus.OPEN,
    "ORDER_STATUS_FILLED": OrderStatus.FILLED,
    "ORDER_STATUS_PARTIAL_FILLED": OrderStatus.PARTIAL_FILLED,
    "ORDER_STATUS_REJECTED": OrderStatus.REJECTED,
    "ORDER_STATUS_CANCELLED": OrderStatus.CANCELLED,
    "ORDER_STATUS_EXPIRED": OrderStatus.EXPIRED,
}


def _map_status(raw_status: str) -> OrderStatus:
    return _STATUS_MAP.get(str(raw_status), OrderStatus.PENDING)


class NubraBroker(BrokerClient):
    """BrokerClient adapter over NubraClient for live UAT/prod equity orders."""

    def __init__(self, nubra_client, dry_run_log: bool = True) -> None:
        self._c = nubra_client
        self._dry_run_log = dry_run_log

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        out = self._c.place_order(
            symbol=order.symbol,
            side=order.side.value,
            qty=order.qty,
            price_type=order.price_type.value,
            price=order.price,
            client_tag=order.client_tag,
        )
        if self._dry_run_log:
            # §5 safety control: log built payload before any live submission
            print("NUBRA ORDER PAYLOAD:", json.dumps(out.get("payload", {}), default=str))
        return BrokerOrderResult(
            broker_order_id=str(out.get("order_id")),
            client_tag=order.client_tag,
            status=OrderStatus.SENT,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            raw=out,
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        self._c.cancel_order(broker_order_id)
        return True

    def modify_order(self, broker_order_id: str, **changes) -> BrokerOrderResult:
        raise NotImplementedError("modify deferred (spec §1 non-goals)")

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult | None:
        raw = self._c.get_order(broker_order_id)
        if raw is None:
            return None
        status = _map_status(getattr(raw, "order_status", "ORDER_STATUS_PENDING"))
        return BrokerOrderResult(
            broker_order_id=broker_order_id,
            client_tag=getattr(raw, "tag", ""),
            status=status,
            submitted_at="",
            raw={"order": str(raw)},
        )

    def get_positions(self) -> list[dict]:
        return list(self._c.positions())

    def get_funds(self) -> dict:
        return {}  # wired in Plan B PositionSync

from __future__ import annotations
import json
from pathlib import Path
from services.nubra_client.broker_types import OrderStatus

_TERMINAL = {OrderStatus.FILLED, OrderStatus.REJECTED,
             OrderStatus.CANCELLED, OrderStatus.EXPIRED}

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


class OrderStateTracker:
    def __init__(self, env: str = "UAT", base_dir: str = "state/nubra"):
        self.path = Path(base_dir) / f"orders_{env.upper()}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def _save(self):
        self.path.write_text(json.dumps(self._data, default=str))

    def record(self, *, client_tag: str, broker_order_id: str,
               symbol: str, status: OrderStatus) -> None:
        self._data[client_tag] = {
            "client_tag": client_tag,
            "broker_order_id": broker_order_id,
            "symbol": symbol,
            "status": status.value,
        }
        self._save()

    def _find_by_oid(self, broker_order_id: str) -> str | None:
        for tag, rec in self._data.items():
            if rec.get("broker_order_id") == broker_order_id:
                return tag
        return None

    def mark(self, broker_order_id: str, status: OrderStatus) -> None:
        tag = self._find_by_oid(broker_order_id)
        if tag:
            self._data[tag]["status"] = status.value
            self._save()

    def upsert_from_event(self, event: dict) -> None:
        status = _STATUS_MAP.get(str(event.get("order_status")), OrderStatus.PENDING)
        self.mark(event.get("order_id"), status)

    def was_placed(self, client_tag: str) -> bool:
        """True if this client_tag was ever recorded (open or terminal)."""
        return client_tag in self._data

    def has_open(self, client_tag: str) -> bool:
        rec = self._data.get(client_tag)
        if not rec:
            return False
        return OrderStatus(rec["status"]) not in _TERMINAL

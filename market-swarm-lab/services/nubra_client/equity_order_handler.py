from __future__ import annotations
from datetime import datetime
from services.nubra_client.order_handler import OrderHandler
from services.nubra_client.market_calendar import is_market_open


class EquityOrderHandler(OrderHandler):
    asset_class = "equity"

    def __init__(self, *, translator, broker, tracker, funds_check, clock=None):
        self._xlate = translator
        self._broker = broker
        self._tracker = tracker
        self._funds_check = funds_check
        self._clock = clock or datetime.now

    def handle(self, signal: dict, risk: dict, ticker: str) -> dict:
        if not risk.get("approved"):
            return {"asset_class": "equity", "status": "rejected_by_risk"}

        if not is_market_open(self._clock()):
            return {"asset_class": "equity", "status": "market_closed"}

        trading_date = self._clock().strftime("%Y-%m-%d")
        order, reason = self._xlate.translate(signal, trading_date)
        if order is None:
            return {"asset_class": "equity", "status": "skipped", "reason": reason}

        if self._tracker.has_open(order.client_tag):
            return {"asset_class": "equity", "status": "duplicate_skipped",
                    "client_tag": order.client_tag}

        if not self._funds_check(order):
            return {"asset_class": "equity", "status": "insufficient_funds",
                    "client_tag": order.client_tag}

        result = self._broker.place_order(order)
        self._tracker.record(client_tag=order.client_tag,
                             broker_order_id=result.broker_order_id,
                             symbol=order.symbol, status=result.status)
        return {"asset_class": "equity", "status": "placed",
                "broker_order_id": result.broker_order_id,
                "client_tag": order.client_tag,
                "side": order.side.value,
                "qty": order.qty,
                "reason": reason}

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from services.nubra_client.entry_gate import EntryGate, ExpectedUpsideGate
from services.nubra_client.market_calendar import is_market_open
from services.nubra_client.order_handler import OrderHandler

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "nubra_config.json"
)
_log = logging.getLogger(__name__)


def _default_gates() -> list[EntryGate]:
    try:
        with open(_CONFIG_PATH) as fh:
            cfg = json.load(fh)
        return [ExpectedUpsideGate(cfg["entry_threshold"])]
    except (KeyError, json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
        # Config missing or malformed — fall back and warn so it never silently skips gate.
        _log.warning("entry_threshold config unreadable (%s); using gate defaults", exc)
        return [ExpectedUpsideGate({})]


class EquityOrderHandler(OrderHandler):
    asset_class = "equity"

    def __init__(self, *, translator, broker, tracker, funds_check, clock=None,
                 entry_gates: list[EntryGate] | None = None):
        self._xlate = translator
        self._broker = broker
        self._tracker = tracker
        self._funds_check = funds_check
        self._clock = clock or datetime.now
        self._entry_gates: list[EntryGate] = (
            entry_gates if entry_gates is not None else _default_gates()
        )

    def handle(self, signal: dict, risk: dict, ticker: str) -> dict:
        if not risk.get("approved"):
            return {"asset_class": "equity", "status": "rejected_by_risk"}

        if not is_market_open(self._clock()):
            return {"asset_class": "equity", "status": "market_closed"}

        # Entry gates apply only to bullish (CALL) entries; exits and holds bypass.
        if signal.get("trade") == "CALL":
            # F4: inject authoritative ticker so per-symbol lookup never uses a stale signal value.
            gate_signal = {**signal, "ticker": ticker}
            for gate in self._entry_gates:
                try:
                    allowed, reason = gate.evaluate(gate_signal)
                except ValueError as exc:
                    return {"asset_class": "equity", "status": "skipped", "reason": str(exc)}
                if not allowed:
                    return {"asset_class": "equity", "status": "below_threshold",
                            "reason": reason}

        trading_date = self._clock().strftime("%Y-%m-%d")
        order, reason = self._xlate.translate(signal, trading_date)
        if order is None:
            return {"asset_class": "equity", "status": "skipped", "reason": reason}

        if self._tracker.is_blocking(order.client_tag):
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

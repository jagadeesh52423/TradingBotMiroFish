from __future__ import annotations

from decimal import Decimal

from services.nubra_client.instrument_resolver import InstrumentResolver
from services.nubra_client.units import paise_to_rupees, round_to_tick, rupees_to_paise

_SIDE_MAP = {"BUY": "ORDER_SIDE_BUY", "SELL": "ORDER_SIDE_SELL"}
_PRODUCT_MAP = {"CNC": "ORDER_DELIVERY_TYPE_CNC", "MIS": "ORDER_DELIVERY_TYPE_MIS"}


class NubraClient:
    """Thin wrapper around nubra-sdk handles; all unit tests inject fakes."""

    def __init__(self, config: dict, sdk_trader, sdk_market, sdk_instruments) -> None:
        self._cfg = config
        self._sdk_trader = sdk_trader
        self._sdk_market = sdk_market
        self._resolver = InstrumentResolver(sdk_instruments,
                                            exchange=config.get("exchange", "NSE"))

    @classmethod
    def from_session(cls, session_data: dict, config: dict) -> "NubraClient":
        # Production wiring — imports live SDK at call time (not at module load).
        # from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
        # from nubra_python_sdk.trading.trading_data import NubraTrader
        # from nubra_python_sdk.marketdata.market_data import MarketData
        # from nubra_python_sdk.refdata.instruments import InstrumentData
        raise NotImplementedError("from_session requires live nubra_python_sdk; stub for UAT wiring.")

    def current_price(self, symbol: str) -> Decimal:
        inst = self._resolver.resolve(symbol)
        fake_inst = type("I", (), {"ref_id": inst["ref_id"]})()
        result = self._sdk_market.current_price(fake_inst, exchange=self._cfg.get("exchange", "NSE"))
        return paise_to_rupees(result.price)

    def place_order(self, symbol: str, side: str, qty: int, price_type: str,
                    price: Decimal | None, client_tag: str) -> dict:
        inst = self._resolver.resolve(symbol)
        tick = inst["tick_size"]
        rounded_price = round_to_tick(price, tick) if price is not None else None
        price_paise = rupees_to_paise(rounded_price) if rounded_price is not None else 0
        payload = {
            "ref_id": inst["ref_id"],
            "order_side": _SIDE_MAP[side.upper()],
            "order_qty": qty,
            "price_type": price_type.upper(),
            "order_price": price_paise,
            "order_delivery_type": _PRODUCT_MAP.get(
                self._cfg.get("product", "CNC"), "ORDER_DELIVERY_TYPE_CNC"),
            "validity": self._cfg.get("validity", "DAY"),
            "tag": client_tag,
        }
        result = self._sdk_trader.create_order(payload)
        return {"order_id": result.order_id}

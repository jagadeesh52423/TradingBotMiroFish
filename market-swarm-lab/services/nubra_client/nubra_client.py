from __future__ import annotations

from decimal import Decimal

from services.nubra_client.instrument_resolver import InstrumentResolver
from services.nubra_client.units import paise_to_rupees, round_to_tick, rupees_to_paise

_SIDE = {"BUY": "ORDER_SIDE_BUY", "SELL": "ORDER_SIDE_SELL"}
# N1: key on CNC/IDAY (Product enum values), not MIS
_PRODUCT = {"CNC": "ORDER_DELIVERY_TYPE_CNC", "IDAY": "ORDER_DELIVERY_TYPE_IDAY"}


class NubraClient:
    """Only module that imports nubra_sdk. Tests inject fake sdk_* handles."""

    def __init__(self, config: dict, sdk_trader, sdk_market, sdk_instruments) -> None:
        self._cfg = config
        self._sdk_trader = sdk_trader
        self._sdk_market = sdk_market
        self._resolver = InstrumentResolver(sdk_instruments,
                                            exchange=config.get("exchange", "NSE"))

    @classmethod
    def from_session(cls, config: dict, session_token: str) -> "NubraClient":
        # Production wiring — confirm paths against installed nubra_python_sdk:
        # from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
        # from nubra_python_sdk.trading.trading_data import NubraTrader
        # from nubra_python_sdk.marketdata.market_data import MarketData
        # from nubra_python_sdk.refdata.instruments import InstrumentData
        # env = NubraEnv.UAT if config["env"] == "UAT" else NubraEnv.PROD
        # nubra = InitNubraSdk(env, session_token=session_token)
        # return cls(config, NubraTrader(nubra, version="V2"), MarketData(nubra), InstrumentData(nubra))
        raise NotImplementedError("Wire real SDK handles per nubra_python_sdk; stub for UAT wiring.")

    def current_price(self, symbol: str) -> Decimal:
        result = self._sdk_market.current_price(symbol, exchange=self._cfg.get("exchange", "NSE"))
        return paise_to_rupees(result.price)

    def place_order(self, *, symbol: str, side: str, qty: int, price_type: str,
                    price: Decimal | None, client_tag: str) -> dict:
        info = self._resolver.resolve(symbol)
        payload: dict = {
            "ref_id": info["ref_id"],
            "order_type": "ORDER_TYPE_REGULAR",
            "order_qty": int(qty),
            "order_side": _SIDE[side.upper()],
            "order_delivery_type": _PRODUCT.get(self._cfg.get("product", "CNC"),
                                                  "ORDER_DELIVERY_TYPE_CNC"),
            "validity_type": self._cfg.get("validity", "DAY"),
            "price_type": price_type.upper(),
            "exchange": self._cfg.get("exchange", "NSE"),
            "tag": client_tag,
        }
        if price_type.upper() == "LIMIT":
            # S3: omit order_price entirely for MARKET; 0 is a latent live-reject bug
            rounded = round_to_tick(price, info["tick_size"])
            payload["order_price"] = rupees_to_paise(rounded)
        result = self._sdk_trader.create_order(payload)
        return {"order_id": getattr(result, "order_id", None), "payload": payload}

    def cancel_order(self, order_id: str) -> dict:
        return self._sdk_trader.cancel_orders_v2(order_ids=[order_id])

    def get_order(self, order_id: str):
        return self._sdk_trader.get_order(order_id)

    def positions(self) -> list:
        return self._sdk_trader.positions(version="V2")

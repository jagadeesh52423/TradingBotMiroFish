from __future__ import annotations

from decimal import Decimal

from services.nubra_client.instrument_resolver import InstrumentResolver
from services.nubra_client.units import paise_to_rupees, round_to_tick, rupees_to_paise

_SIDE = {"BUY": "ORDER_SIDE_BUY", "SELL": "ORDER_SIDE_SELL"}
# N1: key on CNC/IDAY (Product enum values), not MIS
_PRODUCT = {"CNC": "ORDER_DELIVERY_TYPE_CNC", "IDAY": "ORDER_DELIVERY_TYPE_IDAY"}


class NubraClient:
    """Only module that imports nubra_sdk. Tests inject fake sdk_* handles."""

    def __init__(self, config: dict, sdk_trader, sdk_market, sdk_instruments,
                 sdk_portfolio=None) -> None:
        self._cfg = config
        self._sdk_trader = sdk_trader
        self._sdk_market = sdk_market
        self._sdk_portfolio = sdk_portfolio
        self._resolver = InstrumentResolver(sdk_instruments,
                                            exchange=config.get("exchange", "NSE"))

    @classmethod
    def from_session(cls, config: dict) -> "NubraClient":
        """Create a live client. Auth comes from the SDK shelve (run nubra_login.py first)."""
        from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
        from nubra_python_sdk.trading.trading_data import NubraTrader
        from nubra_python_sdk.marketdata.market_data import MarketData
        from nubra_python_sdk.portfolio.portfolio_data import NubraPortfolio
        from nubra_python_sdk.refdata.instruments import InstrumentData
        env = NubraEnv.UAT if config.get("env", "UAT") == "UAT" else NubraEnv.PROD
        nubra = InitNubraSdk(env=env, env_creds=True)
        return cls(
            config,
            sdk_trader=NubraTrader(nubra),
            sdk_market=MarketData(nubra),
            sdk_instruments=InstrumentData(nubra),
            sdk_portfolio=NubraPortfolio(nubra),
        )

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

    def funds(self) -> dict:
        msg = self._sdk_portfolio.funds()
        pf = msg.port_funds_and_margin
        amount = pf.net_margin_available if pf is not None else 0
        return {"net_margin_available": amount or 0}

    def positions(self) -> list[dict]:
        msg = self._sdk_portfolio.positions("V2")
        raw = (msg.portfolio.positions or []) if msg.portfolio else []
        return [{"symbol": p.symbol, "net_quantity": p.net_quantity or 0} for p in raw]

    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]:
        """Return recent OHLCV close bars in RUPEES, sorted oldest-first.

        Wraps SDK MarketData.historical_data (charts/timeseries).
        Returns at most *lookback* bars; each bar is {"close": float, "timestamp": int (ms)}.
        """
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc)
        # ~2.5× calendar days to cover lookback trading days (weekends + holidays)
        start = end - timedelta(days=int(lookback * 2.5))
        request = {
            "exchange": self._cfg.get("exchange", "NSE"),
            "type": "STOCK",
            "values": [symbol],
            "fields": ["close"],
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "interval": interval,
            "intraDay": False,
            "realTime": False,
        }
        resp = self._sdk_market.historical_data(request)
        bars: list[dict] = []
        if resp and resp.result:
            for chart_data in resp.result:
                for sym_map in chart_data.values:
                    stock_chart = sym_map.get(symbol) or next(iter(sym_map.values()), None)
                    if stock_chart and stock_chart.close:
                        for pt in stock_chart.close:
                            bars.append({
                                "close": float(paise_to_rupees(pt.value)),
                                "timestamp": pt.timestamp,
                            })
        bars.sort(key=lambda b: b["timestamp"])
        return bars[-lookback:]

from __future__ import annotations
from decimal import Decimal
from math import floor
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity)
from services.nubra_client.idempotency import client_tag


class SignalToEquityOrder:
    def __init__(self, *, whitelist, ltp_provider, position_provider,
                 account_value: Decimal, risk_per_trade_pct: Decimal,
                 price_type: str = "LIMIT"):
        self._wl = set(whitelist)
        self._ltp = ltp_provider
        self._pos = position_provider
        self._account = Decimal(account_value)
        self._risk_pct = Decimal(risk_per_trade_pct)
        self._price_type = PriceType(price_type)

    def translate(self, signal: dict, trading_date: str):
        """Return (BrokerOrder|None, reason). Never raises."""
        ticker = signal.get("ticker", "").upper()
        trade = signal.get("trade", "HOLD")
        sig_id = signal.get("signal_id", signal.get("timestamp", "nosig"))

        if ticker not in self._wl:
            return None, f"rejected: {ticker} not in whitelist"
        if trade == "HOLD":
            return None, "hold: no order"

        ltp = Decimal(self._ltp(ticker))

        if trade == "CALL":
            risk_amount = self._account * (self._risk_pct / Decimal("100"))
            qty = floor(risk_amount / ltp)
            if qty < 1:
                return None, f"skip: computed qty {qty} (risk {risk_amount}/ltp {ltp})"
            return self._order(ticker, OrderSide.BUY, qty, ltp, sig_id,
                               trading_date, "BUY"), "buy"

        if trade == "PUT":
            held = self._pos.net_quantity(ticker)
            if held <= 0:
                return None, "skip: no long to close (long-only, no shorting)"
            return self._order(ticker, OrderSide.SELL, held, ltp, sig_id,
                               trading_date, "SELL"), "sell_to_close"

        return None, f"skip: unknown trade '{trade}'"

    def _order(self, ticker, side, qty, ltp, sig_id, trading_date, intent):
        price = ltp if self._price_type is PriceType.LIMIT else None
        return BrokerOrder(
            symbol=ticker, side=side, qty=int(qty),
            price_type=self._price_type, price=price,
            product=Product.CNC, validity=Validity.DAY,
            client_tag=client_tag(str(sig_id), ticker, trading_date, intent))

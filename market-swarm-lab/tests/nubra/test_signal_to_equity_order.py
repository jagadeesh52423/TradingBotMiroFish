from decimal import Decimal
from services.nubra_client.broker_types import OrderSide, PriceType
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder


class _Pos:
    def __init__(self, longs):
        self._l = longs

    def net_quantity(self, s):
        return self._l.get(s, 0)

    def has_long(self, s):
        return self._l.get(s, 0) > 0


def _xlate(longs=None, account_value=Decimal("100000"), risk_pct=Decimal("0.5"),
           ltp=Decimal("800")):
    return SignalToEquityOrder(
        whitelist={"SBIN", "RELIANCE", "TATACONSUM"},
        ltp_provider=lambda s: ltp,
        position_provider=_Pos(longs or {}),
        account_value=account_value, risk_per_trade_pct=risk_pct,
        price_type="LIMIT")


def _sig(trade, ticker="SBIN", signal_id="sig1"):
    return {"ticker": ticker, "trade": trade, "signal_id": signal_id}


def test_reject_non_whitelist():
    o, reason = _xlate().translate(_sig("CALL", ticker="INFY"), "2026-06-16")
    assert o is None and "whitelist" in reason.lower()


def test_hold_returns_none():
    o, reason = _xlate().translate(_sig("HOLD"), "2026-06-16")
    assert o is None


def test_bullish_buy_sizes_floor_risk_over_ltp():
    # risk_amount = 100000 * 0.5% = 500; 500/800 = 0.625 -> floor 0 -> None
    o, reason = _xlate(ltp=Decimal("800")).translate(_sig("CALL"), "2026-06-16")
    assert o is None and "qty" in reason.lower()


def test_bullish_buy_with_affordable_size():
    # risk 5000 over ltp 100 -> 50 shares
    o, _ = _xlate(account_value=Decimal("1000000"), ltp=Decimal("100")).translate(
        _sig("CALL"), "2026-06-16")
    assert o.side is OrderSide.BUY and o.qty == 50
    assert o.price_type is PriceType.LIMIT and o.price == Decimal("100")


def test_bearish_with_long_sells_to_close():
    o, _ = _xlate(longs={"SBIN": 7}).translate(_sig("PUT"), "2026-06-16")
    assert o.side is OrderSide.SELL and o.qty == 7


def test_bearish_without_long_skips():
    o, reason = _xlate(longs={}).translate(_sig("PUT"), "2026-06-16")
    assert o is None and "no long" in reason.lower()


def test_client_tag_is_deterministic():
    o, _ = _xlate(account_value=Decimal("1000000"), ltp=Decimal("100")).translate(
        _sig("CALL"), "2026-06-16")
    assert o.client_tag.startswith("msl-")

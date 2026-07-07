"""Screen mode: broker-less stack (paper broker + injected data provider, no Nubra)."""
from __future__ import annotations

from decimal import Decimal

from services.nubra_client.equity_assembly import build_equity_stack

_CFG = {"whitelist": ["SBIN"], "risk_per_trade_pct": "0.5", "env": "UAT",
        "default_order_type": "LIMIT"}


class _FakeProvider:
    def current_price(self, symbol):
        return Decimal("100")

    def historical(self, symbol, interval="1d", lookback=20):
        return [{"close": 100.0, "timestamp": i} for i in range(lookback)]


def test_screen_mode_builds_without_nubra(tmp_path):
    stack = build_equity_stack("screen", _CFG, data_provider=_FakeProvider(), state_dir=str(tmp_path))
    # market data is the injected provider; broker is the paper trader (no Nubra session)
    assert isinstance(stack.market_data, _FakeProvider)
    assert stack.broker.__class__.__name__ == "EquityPaperTrader"
    # LTP flows from the provider
    assert stack.translator._ltp("SBIN") == Decimal("100")


def test_unknown_mode_still_errors():
    import pytest
    with pytest.raises(ValueError, match="screen"):
        build_equity_stack("bogus", _CFG)

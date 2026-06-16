from decimal import Decimal
import pytest
from services.nubra_client.equity_assembly import build_equity_stack, EquityStack
from services.nubra_client.equity_order_handler import EquityOrderHandler


_CFG = {
    "env": "UAT",
    "whitelist": ["SBIN", "RELIANCE"],
    "exchange": "NSE",
    "product": "CNC",
    "default_order_type": "LIMIT",
    "validity": "DAY",
    "risk_per_trade_pct": 0.5,
    "entry_threshold": {
        "min_expected_upside_pct": 2.0,
        "per_symbol": {},
        "max_horizon_days": None,
    },
}


def test_paper_returns_equity_stack(tmp_path):
    stack = build_equity_stack("paper", _CFG, state_dir=str(tmp_path))
    assert isinstance(stack, EquityStack)
    assert isinstance(stack.handler, EquityOrderHandler)


def test_paper_feed_is_none(tmp_path):
    stack = build_equity_stack("paper", _CFG, state_dir=str(tmp_path))
    assert stack.feed is None


def test_paper_translator_shares_whitelist(tmp_path):
    stack = build_equity_stack("paper", _CFG, state_dir=str(tmp_path))
    assert stack.translator._wl == {"SBIN", "RELIANCE"}


def test_paper_ltp_override_used(tmp_path):
    ltp = lambda sym: Decimal("500")
    stack = build_equity_stack("paper", _CFG, ltp_provider=ltp, state_dir=str(tmp_path))
    assert stack.translator._ltp("SBIN") == Decimal("500")


def test_unknown_mode_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown equity mode"):
        build_equity_stack("live_prod", _CFG, state_dir=str(tmp_path))

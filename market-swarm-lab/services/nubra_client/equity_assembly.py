"""Single DI assembly point for the equity order stack.

paper     — EquityPaperTrader; no live SDK.
nubra_uat — Real NubraClient (from_session); NubraBroker with live funds check.

Whitelist in config is the single source of truth — passed to both NubraFeedAdapter
and SignalToEquityOrder so the two never diverge.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.nubra_feed_adapter import NubraFeedAdapter
from services.nubra_client.order_state_tracker import OrderStateTracker
from services.nubra_client.position_provider import BrokerPositionProvider
from services.nubra_client.position_sync import PositionSync
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.units import paise_to_rupees

_DEFAULT_CONFIG = pathlib.Path(__file__).parents[2] / "config" / "nubra_config.json"


@dataclass
class EquityStack:
    """Assembled equity order pipeline components."""
    handler: EquityOrderHandler
    translator: SignalToEquityOrder
    broker: object                   # BrokerClient (paper or live)
    feed: NubraFeedAdapter | None    # None in paper mode


def build_equity_stack(
    mode: str,
    config: dict | None = None,
    *,
    session_token: str | None = None,
    ltp_provider: Callable[[str], Decimal] | None = None,
    state_dir: str = "state/nubra",
) -> EquityStack:
    """Build the full equity stack wired for *mode*.

    Args:
        mode:          "paper" or "nubra_uat".
        config:        Parsed nubra_config.json dict. Loaded from disk if None.
        session_token: Forwarded to NubraClient.from_session (SDK manages its own auth).
        ltp_provider:  Override LTP callable for paper mode (e.g. in tests).
        state_dir:     Base directory for OrderStateTracker persistence.
    """
    if config is None:
        config = json.loads(_DEFAULT_CONFIG.read_text())

    whitelist: list[str] = config["whitelist"]
    risk_pct = Decimal(str(config.get("risk_per_trade_pct", "0.5")))
    env = config.get("env", "UAT")

    tracker = OrderStateTracker(env=env, base_dir=state_dir)

    if mode == "paper":
        broker, feed, effective_ltp, funds_check = _paper_components(ltp_provider)
    elif mode == "nubra_uat":
        broker, feed, effective_ltp, funds_check = _nubra_uat_components(
            config, whitelist, session_token
        )
    else:
        raise ValueError(f"Unknown equity mode: {mode!r}. Expected 'paper' or 'nubra_uat'.")

    account_value = _account_from_funds(broker, mode)
    position_provider = BrokerPositionProvider(broker)

    translator = SignalToEquityOrder(
        whitelist=whitelist,
        ltp_provider=effective_ltp,
        position_provider=position_provider,
        account_value=account_value,
        risk_per_trade_pct=risk_pct,
        price_type=config.get("default_order_type", "LIMIT"),
    )

    handler = EquityOrderHandler(
        translator=translator,
        broker=broker,
        tracker=tracker,
        funds_check=funds_check,
    )

    return EquityStack(handler=handler, translator=translator, broker=broker, feed=feed)


def _paper_components(ltp_override: Callable | None):
    from services.nubra_client.equity_paper_trader import EquityPaperTrader
    ltp = ltp_override or (lambda sym: Decimal("1000"))
    broker = EquityPaperTrader(ltp_provider=ltp)
    return broker, None, ltp, lambda order: True


def _nubra_uat_components(config: dict, whitelist: list[str], session_token: str | None):
    from services.nubra_client.nubra_client import NubraClient
    from services.nubra_client.nubra_broker import NubraBroker
    nubra_client = NubraClient.from_session(config, session_token)
    broker = NubraBroker(nubra_client)
    feed = NubraFeedAdapter(nubra_client, symbols=whitelist)
    funds_check = PositionSync(broker).funds_sufficient
    return broker, feed, nubra_client.current_price, funds_check


def _account_from_funds(broker, mode: str) -> Decimal:
    if mode == "paper":
        return Decimal("100000")  # 1 lakh virtual capital
    funds = broker.get_funds()
    paise = int(funds.get("net_margin_available", 0))
    return paise_to_rupees(paise) if paise > 0 else Decimal("100000")

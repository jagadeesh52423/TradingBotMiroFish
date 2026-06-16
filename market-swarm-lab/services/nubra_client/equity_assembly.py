"""Single DI assembly point for the equity order stack.

paper     — EquityPaperTrader; no live SDK.
nubra_uat — Real NubraClient (from_session); NubraBroker with live funds check.

Whitelist in config is the single source of truth — passed to both NubraFeedAdapter
and SignalToEquityOrder so the two never diverge.
"""
from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.nubra_feed_adapter import NubraFeedAdapter
from services.nubra_client.order_handler import OrderHandlerRegistry
from services.nubra_client.order_state_tracker import OrderStateTracker
from services.nubra_client.position_provider import BrokerPositionProvider
from services.nubra_client.position_sync import PositionSync
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.units import paise_to_rupees

_DEFAULT_CONFIG = pathlib.Path(__file__).parents[2] / "config" / "nubra_config.json"
_log = logging.getLogger(__name__)


@dataclass
class EquityStack:
    """Assembled equity order pipeline components."""
    handler: EquityOrderHandler
    translator: SignalToEquityOrder
    broker: object                   # BrokerClient (paper or live)
    feed: NubraFeedAdapter | None    # None in paper mode
    registry: OrderHandlerRegistry   # pre-wired registry; pass to ExecutionEngineService
    market_data: object | None       # NubraClient (current_price + historical); None in paper mode


def build_equity_stack(
    mode: str,
    config: dict | None = None,
    *,
    ltp_provider: Callable[[str], Decimal] | None = None,
    client_factory: Callable | None = None,
    state_dir: str = "state/nubra",
) -> EquityStack:
    """Build the full equity stack wired for *mode*.

    Args:
        mode:           "paper" or "nubra_uat".
        config:         Parsed nubra_config.json dict. Loaded from disk if None.
        ltp_provider:   Override LTP callable for paper mode (e.g. in tests).
        client_factory: Override NubraClient factory for nubra_uat mode (seam for tests).
                        Signature: (config: dict) -> NubraClient-like object.
        state_dir:      Base directory for OrderStateTracker persistence.
    """
    if config is None:
        config = json.loads(_DEFAULT_CONFIG.read_text())

    whitelist: list[str] = config["whitelist"]
    risk_pct = Decimal(str(config.get("risk_per_trade_pct", "0.5")))
    env = config.get("env", "UAT")

    tracker = OrderStateTracker(env=env, base_dir=state_dir)

    if mode == "paper":
        broker, feed, effective_ltp, funds_check, market_data = _paper_components(ltp_provider)
    elif mode == "nubra_uat":
        broker, feed, effective_ltp, funds_check, market_data = _nubra_uat_components(
            config, whitelist, client_factory=client_factory
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

    registry = OrderHandlerRegistry()
    registry.register(handler)

    return EquityStack(handler=handler, translator=translator, broker=broker, feed=feed,
                       registry=registry, market_data=market_data)


def _paper_components(ltp_override: Callable | None):
    from services.nubra_client.equity_paper_trader import EquityPaperTrader
    ltp = ltp_override or (lambda sym: Decimal("1000"))
    broker = EquityPaperTrader(ltp_provider=ltp)
    return broker, None, ltp, lambda order: True, None  # no live market-data client in paper mode


def _nubra_uat_components(config: dict, whitelist: list[str], *, client_factory: Callable | None):
    from services.nubra_client.nubra_client import NubraClient
    from services.nubra_client.nubra_broker import NubraBroker
    # client_factory seam: allows unit tests to inject a fake without the live SDK.
    factory = client_factory or NubraClient.from_session
    nubra_client = factory(config)
    broker = NubraBroker(nubra_client)
    feed = NubraFeedAdapter(nubra_client, symbols=whitelist)
    funds_check = PositionSync(broker).funds_sufficient
    # market_data = the raw NubraClient, NOT the broker — broker lacks current_price/historical.
    return broker, feed, nubra_client.current_price, funds_check, nubra_client


def _account_from_funds(broker, mode: str) -> Decimal:
    if mode == "paper":
        return Decimal("100000")  # 1 lakh virtual capital
    # C4: live path — never fabricate capital. Zero margin → qty 0 → no order.
    funds = broker.get_funds()
    paise = int(funds.get("net_margin_available", 0))
    if paise <= 0:
        _log.warning(
            "net_margin_available is %d paise on live path — sizing will produce qty 0", paise
        )
        return Decimal("0")
    return paise_to_rupees(paise)

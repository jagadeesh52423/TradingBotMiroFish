"""Build a BrokerRegistry with all known broker modes registered.

To add a new broker mode: implement BrokerClient, then add one reg.register() call here.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from services.nubra_client.broker_registry import BrokerRegistry
from services.nubra_client.equity_paper_trader import EquityPaperTrader


def build_broker_registry(ltp_provider: Callable[[str], Decimal]) -> BrokerRegistry:
    reg = BrokerRegistry()
    reg.register("paper", lambda: EquityPaperTrader(ltp_provider=ltp_provider))
    # nubra_uat / nubra_live: require a pre-built NubraBroker; guard at construction time
    reg.register("nubra_uat", _require_nubra_broker)
    reg.register("nubra_live", _require_nubra_broker)
    return reg


def _require_nubra_broker(nubra_broker=None):
    if nubra_broker is None:
        raise RuntimeError(
            "nubra_* mode requires a constructed NubraBroker "
            "(pass nubra_broker=...). Run nubra_login.py first."
        )
    return nubra_broker

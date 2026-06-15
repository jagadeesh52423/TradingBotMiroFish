"""Register all broker modes into a BrokerRegistry instance.

To add a new broker mode: implement BrokerClient, then add one registry.register() call here.
"""
from __future__ import annotations

from services.nubra_client.broker_registry import BrokerRegistry
from services.nubra_client.equity_paper_trader import EquityPaperTrader
from services.nubra_client.nubra_broker import NubraBroker


def register_all(registry: BrokerRegistry) -> None:
    registry.register("paper", lambda ltp_provider, **_: EquityPaperTrader(ltp_provider))
    # live mode: caller must pass nubra_client= kwarg (a NubraClient instance)
    registry.register("live", lambda nubra_client, **_: NubraBroker(nubra_client))

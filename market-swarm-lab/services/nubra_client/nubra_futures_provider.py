"""NubraFuturesProvider — MarketDataProvider for NSE index futures (NIFTY, BANKNIFTY).

Data-only: resolves nearest-expiry contract, fetches LTP + OHLCV history.
No order placement anywhere in this module.

Contract:
  symbol arg = underlying name ("NIFTY" or "BANKNIFTY").
  Nearest-expiry FUT contract is resolved via get_instruments() and cached per session.

# implement MarketDataProvider + register via @register_provider to add a new source.
"""
from __future__ import annotations

import logging
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

# Idempotent sys.path: market-swarm-lab root so `services.*` imports resolve when run as script.
_ROOT = pathlib.Path(__file__).parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.nubra_client.market_data_provider import MarketDataProvider
from services.nubra_client.market_data_registry import register_provider
from services.nubra_client.units import paise_to_rupees

_log = logging.getLogger(__name__)


@register_provider("nubra_futures")
class NubraFuturesProvider(MarketDataProvider):
    """LTP + OHLCV history for NSE index futures.

    symbol = underlying (e.g. "NIFTY"); nearest-expiry contract resolved and
    cached on first call to resolve_contract().
    """

    def __init__(self, config: dict, sdk_market, sdk_instruments) -> None:
        self._cfg = config
        self._sdk_market = sdk_market
        self._sdk_instruments = sdk_instruments
        # underlying → {stock_name, nubra_name, ref_id, lot_size, tick_size, expiry}
        self._contract_cache: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_config(cls, config: dict) -> "NubraFuturesProvider":
        """Build from nubra_config dict; reuses the cached auth_data.db session."""
        from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
        from nubra_python_sdk.marketdata.market_data import MarketData
        from nubra_python_sdk.refdata.instruments import InstrumentData
        env = NubraEnv.UAT if config.get("env", "UAT") == "UAT" else NubraEnv.PROD
        nubra = InitNubraSdk(env=env, env_creds=True)
        return cls(config, sdk_market=MarketData(nubra), sdk_instruments=InstrumentData(nubra))

    def resolve_contract(self, underlying: str) -> dict[str, Any]:
        """Return nearest-expiry FUT contract metadata for *underlying*, cached per session."""
        if underlying in self._contract_cache:
            return self._contract_cache[underlying]
        instruments = self._sdk_instruments.get_instruments(
            exchange="NSE", derivative_type="FUT", asset=underlying
        )
        sorted_instr = sorted(instruments, key=lambda row: row.expiry)
        nearest = sorted_instr[0]
        contract: dict[str, Any] = {
            "stock_name": nearest.stock_name,
            "nubra_name": nearest.nubra_name,
            "ref_id": nearest.ref_id,
            "lot_size": nearest.lot_size,
            "tick_size": nearest.tick_size,
            "expiry": nearest.expiry,
        }
        self._contract_cache[underlying] = contract
        _log.info(
            "resolved FUT contract for %s: %s  expiry=%s  lot=%s",
            underlying, contract["stock_name"], contract["expiry"], contract["lot_size"],
        )
        return contract

    def current_price(self, symbol: str) -> Decimal:
        contract = self.resolve_contract(symbol)
        quote_resp = self._sdk_market.quote(contract["ref_id"], 1)
        return paise_to_rupees(int(quote_resp.orderBook.last_traded_price))

    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]:
        """Return recent FUT close bars in rupees, sorted oldest-first.

        # values MUST be stock_name (e.g. 'NIFTY26JUNFUT') — nubra_name form fails.
        """
        contract = self.resolve_contract(symbol)
        stock_name = contract["stock_name"]
        end = datetime.now(timezone.utc)
        # ~2.5× calendar days covers lookback trading days across weekends + holidays.
        start = end - timedelta(days=int(lookback * 2.5))
        request = {
            "exchange": self._cfg.get("exchange", "NSE"),
            "type": "FUT",
            "values": [stock_name],
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
                    stock_chart = sym_map.get(stock_name) or next(iter(sym_map.values()), None)
                    if stock_chart and stock_chart.close:
                        for pt in stock_chart.close:
                            bars.append({
                                "close": float(paise_to_rupees(pt.value)),
                                "timestamp": pt.timestamp,
                            })
        bars.sort(key=lambda b: b["timestamp"])
        return bars[-lookback:]


# ---------------------------------------------------------------------------
# Self-check — runs with no network / no Nubra session
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    class _FakeInstrument:
        def __init__(self, stock_name, nubra_name, expiry, lot_size, tick_size, ref_id):
            self.stock_name = stock_name
            self.nubra_name = nubra_name
            self.expiry = expiry
            self.lot_size = lot_size
            self.tick_size = tick_size
            self.ref_id = ref_id

    class _FakeOrderBook:
        last_traded_price = 2414860  # NIFTY ≈ ₹24,148.60

    class _FakeQuoteResp:
        orderBook = _FakeOrderBook()

    class _FakeClosePoint:
        def __init__(self, value, ts):
            self.value = value
            self.timestamp = ts

    class _FakeStockChart:
        def __init__(self, paise_closes):
            self.close = [_FakeClosePoint(v, i * 86400000) for i, v in enumerate(paise_closes)]

    class _FakeChartData:
        def __init__(self, stock_name, paise_closes):
            self.values = [{stock_name: _FakeStockChart(paise_closes)}]

    class _FakeHistResp:
        def __init__(self, stock_name, paise_closes):
            self.result = [_FakeChartData(stock_name, paise_closes)]

    class _FakeSdkMarket:
        def quote(self, ref_id, mode):
            return _FakeQuoteResp()

        def historical_data(self, request):
            stock_name = request["values"][0]
            # 25 days of fake paise prices starting at ₹24,000
            closes_paise = [2400000 + i * 1000 for i in range(25)]
            return _FakeHistResp(stock_name, closes_paise)

    class _FakeSdkInstruments:
        def get_instruments(self, exchange, derivative_type, asset):
            # Far expiry listed first — provider must sort and pick nearest.
            return [
                _FakeInstrument("NIFTY26JULFUT", "FUT_NIFTY_20260724", 20260724, 75, 5, "REF_FAR"),
                _FakeInstrument("NIFTY26JUNFUT", "FUT_NIFTY_20260626", 20260626, 65, 10, "REF_NEAR"),
            ]

    provider = NubraFuturesProvider(
        config={"exchange": "NSE", "env": "UAT"},
        sdk_market=_FakeSdkMarket(),
        sdk_instruments=_FakeSdkInstruments(),
    )

    # 1. Nearest-expiry selection (sort by expiry ascending → [0])
    contract = provider.resolve_contract("NIFTY")
    assert contract["stock_name"] == "NIFTY26JUNFUT", f"expected NIFTY26JUNFUT, got {contract['stock_name']}"
    assert contract["expiry"] == 20260626, f"wrong expiry: {contract['expiry']}"
    assert contract["lot_size"] == 65, f"wrong lot: {contract['lot_size']}"

    # 2. Paise → rupees conversion (2414860p = ₹24,148.60)
    ltp = provider.current_price("NIFTY")
    assert ltp == Decimal("24148.60"), f"expected 24148.60, got {ltp}"

    # 3. Historical uses stock_name key; returns lookback bars in rupees.
    # Fake data: 25 bars at paise 2400000, 2401000, …, 2424000.
    # bars[-20:] → indices 5..24; bars[0] is index 5, bars[-1] is index 24.
    bars = provider.historical("NIFTY", lookback=20)
    assert len(bars) == 20, f"expected 20 bars, got {len(bars)}"
    expected_first = float(paise_to_rupees(2400000 + 5 * 1000))  # index 5 = ₹24050.00
    assert bars[0]["close"] == expected_first, f"first close wrong: {bars[0]} expected {expected_first}"
    assert bars[0]["timestamp"] == 5 * 86400000, f"timestamp wrong: {bars[0]}"

    print("self-check OK")
    print(f"  contract : {contract['stock_name']}  expiry={contract['expiry']}  lot={contract['lot_size']}")
    print(f"  ltp      : ₹{ltp}")
    print(f"  bars     : {len(bars)} (first ₹{bars[0]['close']:.2f}, last ₹{bars[-1]['close']:.2f})")

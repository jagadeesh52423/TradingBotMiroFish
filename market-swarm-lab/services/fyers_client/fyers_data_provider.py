"""FyersDataProvider — market data (OHLCV + LTP) sourced from Fyers.

Drop-in MarketDataProvider for the equity stack: registered as "fyers", so
`"data_provider": "fyers"` in nubra_config.json swaps market data to Fyers while
orders stay on Nubra. fyers-apiv3 is NOT a hard dependency — it is imported lazily
inside the client build, so importing this module never requires the SDK.

Auth: this provider only CONSUMES an access_token (from config["fyers"] or the
FYERS_ACCESS_TOKEN env var). The interactive/TOTP flow that mints the token is out
of scope here — mint it separately and supply it via config or environment.
"""
from __future__ import annotations

import os
from decimal import Decimal

from services.nubra_client.market_data_provider import MarketDataProvider
from services.nubra_client.market_data_registry import register_provider

# interval → Fyers resolution. Extend here to add new intervals.
_RESOLUTION = {"1d": "1D", "1D": "1D"}
# ~2.5× calendar days covers `lookback` trading days (weekends + holidays).
_CALENDAR_DAYS_PER_TRADING_DAY = 2.5
_SECONDS_PER_DAY = 86_400


@register_provider("fyers")
class FyersDataProvider(MarketDataProvider):
    def __init__(self, client_id: str | None, access_token: str | None, *, client=None) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._client = client  # lazily built on first use unless injected (tests)

    @classmethod
    def from_config(cls, config: dict) -> "FyersDataProvider":
        fyers_cfg = config.get("fyers", {})
        client_id = fyers_cfg.get("client_id") or os.environ.get("FYERS_CLIENT_ID")
        access_token = fyers_cfg.get("access_token") or os.environ.get("FYERS_ACCESS_TOKEN")
        return cls(client_id, access_token)

    @staticmethod
    def _to_fyers_symbol(symbol: str) -> str:
        return f"NSE:{symbol}-EQ"

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._access_token:
            raise RuntimeError(
                "FYERS_ACCESS_TOKEN missing — set config['fyers']['access_token'] or the "
                "FYERS_ACCESS_TOKEN env var (mint it via the Fyers auth flow first)."
            )
        try:
            from fyers_apiv3 import fyersModel
        except ImportError as exc:
            raise RuntimeError(
                "fyers-apiv3 is not installed — `pip install fyers-apiv3` to use the "
                "Fyers data provider."
            ) from exc
        self._client = fyersModel.FyersModel(
            client_id=self._client_id, token=self._access_token, is_async=False
        )
        return self._client

    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]:
        """Return recent close bars, oldest-first, matching NubraClient's shape.

        Each bar is {"close": float (rupees), "timestamp": int (ms)}.
        """
        from datetime import datetime, timedelta, timezone

        resolution = _RESOLUTION.get(interval, "1D")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(lookback * _CALENDAR_DAYS_PER_TRADING_DAY))
        request = {
            "symbol": self._to_fyers_symbol(symbol),
            "resolution": resolution,
            "date_format": "1",
            "range_from": start.strftime("%Y-%m-%d"),
            "range_to": end.strftime("%Y-%m-%d"),
            "cont_flag": "1",
        }
        response = self._get_client().history(request)
        candles = (response or {}).get("candles") or []
        # Fyers candle = [epoch_seconds, open, high, low, close, volume].
        bars = [
            {"close": float(candle[4]), "timestamp": int(candle[0]) * 1000}
            for candle in candles
        ]
        bars.sort(key=lambda bar: bar["timestamp"])
        return bars[-lookback:]

    def current_price(self, symbol: str) -> Decimal:
        fyers_symbol = self._to_fyers_symbol(symbol)
        response = self._get_client().quotes({"symbols": fyers_symbol})
        ltp = _extract_ltp(response)
        return Decimal(str(ltp))


def _extract_ltp(response: dict) -> float:
    """Pull the LTP out of a Fyers quotes() response (`d` list, `v.lp`)."""
    rows = (response or {}).get("d") or []
    if not rows:
        raise RuntimeError(f"Fyers quotes() returned no data: {response!r}")
    return rows[0]["v"]["lp"]

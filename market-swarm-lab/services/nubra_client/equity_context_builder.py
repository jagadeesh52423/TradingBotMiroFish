from __future__ import annotations
from decimal import Decimal

_US_SOURCES = ("reddit", "news", "timesfm", "schwab", "uw", "macro")


def build_equity_context(symbol: str, nubra_client, lookback: int = 20) -> dict:
    ltp = nubra_client.current_price(symbol)
    try:
        bars = nubra_client.historical(symbol, interval="1d", lookback=lookback)
        closes = [float(b["close"]) for b in bars]
    except Exception:
        closes = [float(ltp)]
    audit = {src: "n/a" for src in _US_SOURCES}
    audit["nubra"] = "ok"
    return {
        "ticker": symbol.upper(),
        "asset_class": "equity",
        "price": {"ltp": ltp, "recent_closes": closes},
        "source_audit": audit,
    }

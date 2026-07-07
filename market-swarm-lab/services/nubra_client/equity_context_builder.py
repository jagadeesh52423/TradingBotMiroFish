from __future__ import annotations
from decimal import Decimal

_US_SOURCES = ("reddit", "news", "timesfm", "schwab", "uw", "macro")


def build_equity_context(symbol: str, nubra_client, lookback: int = 20) -> dict:
    ltp = nubra_client.current_price(symbol)
    # history_ok distinguishes a FAILED history fetch (throttle/error → fell back to LTP-only)
    # from a genuinely THIN history (e.g. a recent listing). Without it, a rate-limited fetch is
    # mislabeled "insufficient_history" — implying the stock lacks data when it was just throttled.
    history_ok = True
    try:
        bars = nubra_client.historical(symbol, interval="1d", lookback=lookback)
        closes = [float(b["close"]) for b in bars]
        if not closes:
            history_ok = False
            closes = [float(ltp)]
    except Exception:
        closes = [float(ltp)]
        history_ok = False
    audit = {src: "n/a" for src in _US_SOURCES}
    audit["nubra"] = "ok"
    return {
        "ticker": symbol.upper(),
        "asset_class": "equity",
        "price": {"ltp": ltp, "recent_closes": closes, "history_ok": history_ok},
        "source_audit": audit,
    }

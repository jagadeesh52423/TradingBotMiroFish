from decimal import Decimal
from services.nubra_client.equity_context_builder import build_equity_context


class _Client:
    def current_price(self, s):
        return Decimal("812.50")

    def historical(self, symbol, interval="1d", lookback=20):
        return [{"close": 800.0}, {"close": 810.0}, {"close": 812.5}]


def test_context_has_price_and_marks_us_sources_na():
    ctx = build_equity_context("SBIN", _Client())
    assert ctx["ticker"] == "SBIN"
    assert ctx["asset_class"] == "equity"
    assert float(ctx["price"]["ltp"]) == 812.5
    audit = ctx["source_audit"]
    for src in ("reddit", "news", "timesfm", "schwab"):
        assert audit[src] == "n/a"
    assert audit["nubra"] == "ok"


def test_returns_series_present():
    ctx = build_equity_context("SBIN", _Client())
    assert "recent_closes" in ctx["price"]
    assert ctx["price"]["recent_closes"][-1] == 812.5

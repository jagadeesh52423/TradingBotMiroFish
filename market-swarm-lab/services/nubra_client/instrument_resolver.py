from __future__ import annotations


class InstrumentResolver:
    """Cache-backed lookup: symbol → {ref_id, tick_size, lot_size}."""

    def __init__(self, sdk_instruments, exchange: str = "NSE") -> None:
        self._inst = sdk_instruments
        self._exchange = exchange
        self._cache: dict[str, dict] = {}

    def resolve(self, symbol: str) -> dict:
        if symbol in self._cache:
            return self._cache[symbol]
        rec = self._inst.get_instrument_by_symbol(symbol, exchange=self._exchange)
        info = {
            "ref_id": int(rec.ref_id),
            "tick_size": str(getattr(rec, "tick_size", "0.05")),
            "lot_size": int(getattr(rec, "lot_size", 1)),
        }
        self._cache[symbol] = info
        return info

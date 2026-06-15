from __future__ import annotations

# FeedAdapter (services/live_trading/feed_adapters.py) has async abstract methods
# and requires symbol:str in __init__. This MVP uses sync REST polling for 3 equity
# symbols; async WS streaming is deferred to live bring-up. Duck-typed to match the
# FeedAdapter interface without inheriting the async ABC.
class NubraFeedAdapter:
    def __init__(self, nubra_client, symbols: list[str]):
        self._client = nubra_client
        self._all = list(symbols)
        self._subscribed: list[str] = []
        self._callbacks: list = []

    def connect(self):
        return True

    def disconnect(self):
        self._subscribed = []

    def subscribe(self, symbols: list[str]) -> None:
        self._subscribed = [s for s in symbols if s in self._all]

    def register_callback(self, cb) -> None:
        self._callbacks.append(cb)

    def poll_once(self) -> None:
        for sym in self._subscribed:
            ltp = self._client.current_price(sym)
            event = {"type": "quote", "symbol": sym, "ltp": ltp, "source": "nubra"}
            for cb in self._callbacks:
                cb(event)

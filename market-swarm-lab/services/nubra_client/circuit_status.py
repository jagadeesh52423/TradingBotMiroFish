"""NSE circuit-band / price-band status for a symbol.

Playbook §1: an upper-circuit-locked stock is *unbuyable* — a CALL that gaps to
the upper band can't be filled. This provider fetches NSE's quote-equity price
info (last price + upper/lower circuit prices) so the entry gate can block a BUY
into a name already pinned at its upper band. Fails safe: returns None on any
error, letting the gate decide (fail-open by default).
"""
from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_log = logging.getLogger(__name__)

_NSE_HOME = "https://www.nseindia.com"
_QUOTE_API = "https://www.nseindia.com/api/quote-equity?symbol={symbol}"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_REFERER = "https://www.nseindia.com/get-quotes/equity?symbol={symbol}"
_CACHE_TTL_SECONDS = 60  # circuits move intraday — keep it short


class NseCircuitProvider:
    """Fetches (last, upper, lower) circuit prices for a symbol, with caching + fail-safe."""

    def __init__(self, session: requests.Session | None = None, cache_ttl_seconds: int = _CACHE_TTL_SECONDS) -> None:
        self._session = session
        self._primed = False
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[dict | None, float]] = {}

    @classmethod
    def from_config(cls, config: dict) -> "NseCircuitProvider":
        cg = config.get("entry_threshold", {}).get("circuit_gate", {})
        return cls(cache_ttl_seconds=int(cg.get("cache_ttl_seconds", _CACHE_TTL_SECONDS)))

    def status(self, symbol: str) -> dict | None:
        """Return {'last', 'upper', 'lower', 'band'} or None if unavailable."""
        symbol = symbol.upper()
        entry = self._cache.get(symbol)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        try:
            result = _parse_quote(self._fetch(symbol))
        except Exception as exc:
            _log.warning("NSE circuit fetch failed for %s: %s", symbol, exc)
            result = None
        self._cache[symbol] = (result, time.monotonic() + self._cache_ttl)
        return result

    def _prime(self) -> None:
        if self._session is None:
            self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        try:
            self._session.get(_NSE_HOME, timeout=15)
        except Exception as exc:
            _log.warning("NSE homepage prime failed (continuing): %s", exc)
        self._primed = True

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _fetch(self, symbol: str) -> dict:
        if not self._primed:
            self._prime()
        referer = _REFERER.format(symbol=symbol)
        # quote-equity is stricter than the announcements API: it rejects (403) unless
        # the symbol's get-quotes page has been visited first to set symbol-scoped cookies.
        try:
            self._session.get(referer, timeout=15)  # type: ignore[union-attr]
        except Exception as exc:
            _log.debug("get-quotes warmup for %s failed (continuing): %s", symbol, exc)
        resp = self._session.get(  # type: ignore[union-attr]
            _QUOTE_API.format(symbol=symbol),
            headers={"Referer": referer, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


class FyersCircuitProvider:
    """Circuit status from Fyers — same quotes() call that already backs LTP.

    Preferred over NseCircuitProvider: no NSE anti-bot 403s, and Fyers auth is
    already wired for market data. Needs a Fyers access token (config/env); with
    none, status() returns None and the gate fails open.
    """

    def __init__(self, fyers) -> None:
        self._fyers = fyers

    @classmethod
    def from_config(cls, config: dict) -> "FyersCircuitProvider":
        from services.fyers_client.fyers_data_provider import FyersDataProvider
        return cls(FyersDataProvider.from_config(config))

    def status(self, symbol: str) -> dict | None:
        try:
            return self._fyers.circuit(symbol)
        except Exception as exc:  # missing token / SDK / throttle — fail safe
            _log.warning("Fyers circuit fetch failed for %s: %s", symbol, exc)
            return None


def _to_float(v) -> float | None:
    """NSE returns circuit prices as strings like '1,234.50' (or 0 when no band)."""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None
    return f if f > 0 else None


def _parse_quote(data: dict) -> dict | None:
    price = data.get("priceInfo") or {}
    last = _to_float(price.get("lastPrice"))
    upper = _to_float(price.get("upperCP"))
    lower = _to_float(price.get("lowerCP"))
    if last is None or upper is None:
        return None  # can't judge circuit proximity without both
    return {"last": last, "upper": upper, "lower": lower, "band": price.get("pPriceBand")}

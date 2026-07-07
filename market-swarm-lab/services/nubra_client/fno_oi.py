"""F&O positioning (OI/PCR) as descriptive context (§8).

Playbook §8 is explicit that these are DESCRIPTIVE, not leading — 'institutional
positioning leads price' was refuted. So this surfaces PCR + call/put OI as context
and an F&O-availability flag; it never gates and never claims direction.

Source: Fyers option chain (equity depth carries no OI — OI lives on the derivative).
Fails safe to None (→ treated as cash-only / unknown).
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def pcr_label(pcr: float | None) -> str | None:
    """Coarse, caveated PCR bucket. Descriptive only — not a signal."""
    if pcr is None:
        return None
    if pcr >= 1.3:
        return "put_heavy"
    if pcr <= 0.7:
        return "call_heavy"
    return "balanced"


def oi_buildup_label(call_chg, put_chg) -> str | None:
    """Descriptive day-over-day OI buildup (§8 — NOT a directional signal, per playbook).
    'call_buildup' when calls added more OI, 'put_buildup' when puts did, else 'balanced'."""
    if call_chg is None or put_chg is None:
        return None
    if abs(call_chg) + abs(put_chg) == 0:
        return "flat"
    if call_chg > put_chg * 1.2:
        return "call_buildup"
    if put_chg > call_chg * 1.2:
        return "put_buildup"
    return "balanced"


class FyersOptionProvider:
    """Wraps FyersDataProvider.option_summary with a fail-safe .summary()."""

    def __init__(self, fyers) -> None:
        self._fyers = fyers

    @classmethod
    def from_config(cls, config: dict) -> "FyersOptionProvider":
        from services.fyers_client.fyers_data_provider import FyersDataProvider
        return cls(FyersDataProvider.from_config(config))

    def summary(self, symbol: str) -> dict | None:
        try:
            return self._fyers.option_summary(symbol)
        except Exception as exc:
            _log.warning("Fyers option chain failed for %s: %s", symbol, exc)
            return None

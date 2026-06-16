"""Entry gates: pluggable pre-trade filters for bullish entries.

# implement EntryGate to add a new entry filter; register in the handler's gate list.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EntryGate(ABC):
    """Abstract base for all pre-trade entry filters."""

    @abstractmethod
    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        """Return (allowed, reason_if_blocked). reason is None when allowed."""


class ExpectedUpsideGate(EntryGate):
    """Blocks CALL entries whose expected upside falls below a configurable threshold.

    Config keys (all inside the dict passed to __init__):
        min_expected_upside_pct: float   — global floor in percent (e.g. 2.0 means 2%)
        per_symbol: dict[str, float]     — per-symbol overrides (keys uppercased)
        max_horizon_days: float | None   — reject signals with a longer horizon
    """

    def __init__(self, config: dict) -> None:
        self._min_pct: float = float(config.get("min_expected_upside_pct", 2.0))
        self._per_symbol: dict[str, float] = {
            k.upper(): float(v) for k, v in (config.get("per_symbol") or {}).items()
        }
        max_h = config.get("max_horizon_days")
        self._max_horizon_days: float | None = float(max_h) if max_h is not None else None

    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        ticker = str(signal.get("ticker", "")).upper()
        horizon = str(signal.get("horizon", "1d"))
        # expected_move_pct is a FRACTION from the strategy engine (e.g. 0.02 == 2%).
        upside_pct = float(signal.get("expected_move_pct", 0.0)) * 100.0

        horizon_days = self._parse_horizon_days(horizon)
        if self._max_horizon_days is not None and horizon_days > self._max_horizon_days:
            return False, (
                f"horizon {horizon} ({horizon_days:.3g}d) "
                f"> max {self._max_horizon_days:.3g}d"
            )

        threshold = self._per_symbol.get(ticker, self._min_pct)
        if upside_pct < threshold:
            return False, (
                f"upside {upside_pct:.2f}% < {threshold:.2f}% over {horizon}"
            )

        return True, None

    @staticmethod
    def _parse_horizon_days(horizon: str) -> float:
        """Parse horizon strings of the form <N>d or <N>h (e.g. "1d", "4h", "5d").
        Raises ValueError on an unrecognised format so callers are not silently
        wrong about the horizon length."""
        h = horizon.strip().lower()
        try:
            if h.endswith("d"):
                return float(h[:-1])
            if h.endswith("h"):
                return float(h[:-1]) / 24.0
        except (ValueError, IndexError):
            pass
        raise ValueError(
            f"Unrecognised horizon format {horizon!r}. "
            "Expected '<N>d' (days) or '<N>h' (hours), e.g. '1d', '4h'."
        )

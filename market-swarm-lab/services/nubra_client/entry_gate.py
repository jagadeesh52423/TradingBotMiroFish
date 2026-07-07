"""Entry gates: pluggable pre-trade filters for bullish entries.

# implement EntryGate to add a new entry filter; register in the handler's gate list.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

_log = logging.getLogger(__name__)


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
        if str(signal.get("trade", "")).upper() != "CALL":
            return True, None  # only BUYs need an expected-upside floor; PUT/HOLD pass
        ticker = str(signal.get("ticker", "")).upper()
        horizon = str(signal.get("horizon", "1d"))
        # expected_move_pct is a FRACTION from the strategy engine (e.g. 0.02 == 2%).
        upside_pct = float(signal.get("expected_move_pct", 0.0)) * 100.0

        # Lazy parse: only call _parse_horizon_days when a cap is configured.
        # Gates without a horizon cap must never raise on an unparseable horizon string.
        if self._max_horizon_days is not None:
            horizon_days = self._parse_horizon_days(horizon)
            if horizon_days > self._max_horizon_days:
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


class CircuitStatusGate(EntryGate):
    """Blocks a BUY (CALL) into a stock pinned at / near its upper circuit band.

    Playbook §1: an upper-circuit-locked name is unbuyable — you'd bid into a
    frozen queue that may not clear for days. Only CALL signals are gated; PUT
    (sell-to-close) and HOLD pass through untouched.

    Config keys (inside entry_threshold.circuit_gate):
        upper_band_buffer_pct: float  — block if last >= upper * (1 - buffer/100). Default 0.5.
        block_on_unknown: bool        — block BUY when circuit data is unavailable. Default False (fail-open).
    """

    def __init__(self, provider, config: dict | None = None) -> None:
        cfg = config or {}
        self._provider = provider
        self._buffer_pct = float(cfg.get("upper_band_buffer_pct", 0.5))
        self._block_on_unknown = bool(cfg.get("block_on_unknown", False))

    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        if str(signal.get("trade", "")).upper() != "CALL":
            return True, None  # only BUYs can be trapped by an upper circuit

        ticker = str(signal.get("ticker", "")).upper()
        status = self._provider.status(ticker)
        if status is None:
            if self._block_on_unknown:
                return False, "circuit status unknown — blocked (block_on_unknown)"
            _log.info("%s | circuit status unknown — allowing (fail-open)", ticker)
            return True, None

        last, upper = status["last"], status["upper"]
        threshold = upper * (1 - self._buffer_pct / 100.0)
        if last >= threshold:
            return False, (
                f"at/near upper circuit — last {last:.2f} >= {threshold:.2f} "
                f"(upper {upper:.2f}, buffer {self._buffer_pct:.2g}%) — unbuyable"
            )
        return True, None


class SectorTrendGate(EntryGate):
    """Blocks a BUY (CALL) when the symbol's sector index is trending down.

    Playbook §11 trade-killer: a catalyst fighting a falling sector is a weaker trade.
    Only CALL is gated; PUT/HOLD pass. Fails open when the sector trend is unknown
    (unmapped symbol, thin data, fetch error) — never a false block.
    """

    def __init__(self, provider) -> None:
        self._provider = provider

    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        if str(signal.get("trade", "")).upper() != "CALL":
            return True, None
        ticker = str(signal.get("ticker", "")).upper()
        if self._provider.trend(ticker) == "down":
            return False, "sector index trending down — catalyst fighting the tape"
        return True, None


class FirstFifteenGate(EntryGate):
    """Blocks a BUY (CALL) when the opening gap has FADED below the day's open (§3/§4).

    Only CALL is gated. Fails open when the gap can't be confirmed (before 09:30 IST,
    no intraday data, non-trading day) — so it's a no-op in daily/backtest runs and
    active only during a live intraday session.
    """

    def __init__(self, provider) -> None:
        self._provider = provider

    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        if str(signal.get("trade", "")).upper() != "CALL":
            return True, None
        # §4 gate 3 needs BOTH price-hold and above-normal volume — allow only on "held".
        status = self._provider.gap_status(str(signal.get("ticker", "")).upper())
        if status == "faded":
            return False, "opening gap faded below day open — not holding (§4 gate 3)"
        if status == "weak_volume":
            return False, "first-15 volume below normal — unconfirmed move (§4 gate 3)"
        return True, None


class RegimeGate(EntryGate):
    """Blocks a BUY (CALL) when the broad market is trending down (§10).

    The catalyst-swing edge is regime-dependent (up-markets only). Only CALL is gated;
    fails open when regime is unknown (data unavailable). Market-wide, so the same regime
    applies to every symbol in the run.
    """

    def __init__(self, provider) -> None:
        self._provider = provider

    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        if str(signal.get("trade", "")).upper() != "CALL":
            return True, None
        if self._provider.regime() == "down":
            return False, "market regime down — catalyst-swing edge is up-market-only (§10)"
        return True, None


class CompositeEntryGate(EntryGate):
    """Runs gates in order; the first block wins."""

    def __init__(self, gates: list[EntryGate]) -> None:
        self._gates = gates

    def evaluate(self, signal: dict) -> tuple[bool, str | None]:
        for gate in self._gates:
            ok, reason = gate.evaluate(signal)
            if not ok:
                return False, reason
        return True, None

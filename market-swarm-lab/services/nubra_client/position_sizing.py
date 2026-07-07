"""Circuit-band-aware position sizing.

Playbook §5: size tight-band (2%/5%) names smaller than wide-band / F&O names —
their worst-case exit is 'frozen, not slipped' (a lower-circuit lock means the stop
may not fill at all, so you can be trapped for days). Map the stock's circuit-band
width to a size multiplier applied to the computed quantity.
"""
from __future__ import annotations

# (max_band_pct, factor): first tier whose max_band_pct >= the stock's band wins.
# Tight 2% bands → half size; 5% → 0.7; 10%/20%/dynamic → full. Config-overridable.
_DEFAULT_TIERS: list[tuple[float, float]] = [(2.5, 0.5), (5.5, 0.7), (10_000.0, 1.0)]


def band_pct_from_circuit(status: dict) -> float | None:
    """One-sided band width % from a circuit status dict ({'last','upper',...})."""
    last, upper = status.get("last"), status.get("upper")
    if not last or not upper:
        return None
    return (upper / last - 1.0) * 100.0


def band_size_factor(band_pct: float, tiers: list | None = None) -> float:
    """Size multiplier for a given band width %. Tighter band → smaller factor."""
    for max_band, factor in (tiers or _DEFAULT_TIERS):
        if band_pct <= max_band:
            return float(factor)
    return 1.0

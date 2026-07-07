"""Watchlist 5-factor scoring (§2).

Ranks scanned candidates by the playbook's factors: catalyst strength, circuit-band
tightness (wider/F&O = more tradeable), liquidity, sector tailwind, F&O availability.
Each factor is a 0..1 value the caller computes from data it already has; this module
just does the weighted blend, renormalising over whichever factors are present (a
missing factor is neither a bonus nor a penalty — no None poisons the score).
"""
from __future__ import annotations

_DEFAULT_WEIGHTS: dict[str, float] = {
    "catalyst": 0.30,    # news sentiment strength/verifiability
    "sector": 0.25,      # sector-index tailwind
    "band": 0.15,        # circuit-band width (wider = more tradeable)
    "liquidity": 0.15,   # delivery % / traded value
    "fno": 0.15,         # F&O availability (OI/PCR data exists)
}


def watchlist_score(factors: dict, weights: dict | None = None) -> dict:
    """Blend present 0..1 factors into a single score, renormalising weights over them.

    Returns {'score': float|None, 'factors': <input>, 'weights_used': {...}}. score is
    None only when no factor is present.
    """
    weights = weights or _DEFAULT_WEIGHTS
    present = {k: float(v) for k, v in factors.items() if v is not None and k in weights}
    total_w = sum(weights[k] for k in present)
    if not present or total_w <= 0:
        return {"score": None, "factors": factors, "weights_used": {}}
    score = sum(weights[k] * present[k] for k in present) / total_w
    return {
        "score": round(score, 4),
        "factors": factors,
        "weights_used": {k: weights[k] for k in present},
    }

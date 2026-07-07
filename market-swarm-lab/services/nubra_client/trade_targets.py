"""Scale-out target prices for an entry (§5 'scale out into strength').

Derives T1/T2 from the modeled move: T1 is a partial-profit level a fraction of the
way into the move (default 60%), T2 the full modeled move. Advisory levels + scale-out
fractions attached to the entry — a live trader or a future bracket-order layer consumes
them; the bot does not auto-place brackets yet.
"""
from __future__ import annotations

_DEFAULTS = {
    "t1_move_frac": 0.6,   # T1 at 60% of the modeled move
    "t2_move_frac": 1.0,   # T2 at the full modeled move
    "t1_scale_pct": 70,    # take 70% off at T1
    "t2_scale_pct": 30,    # remaining 30% at T2
}


def scale_out_targets(ltp: float, expected_move_pct: float, cfg: dict | None = None) -> dict | None:
    """T1/T2 target prices for a long entry. expected_move_pct is a FRACTION (0.05 == 5%).

    Returns None when there's no positive modeled move (nothing to scale out of).
    """
    if not ltp or not expected_move_pct or expected_move_pct <= 0:
        return None
    c = {**_DEFAULTS, **(cfg or {})}
    t1 = ltp * (1 + expected_move_pct * c["t1_move_frac"])
    t2 = ltp * (1 + expected_move_pct * c["t2_move_frac"])
    return {
        "t1": round(t1, 2), "t1_scale_pct": c["t1_scale_pct"],
        "t2": round(t2, 2), "t2_scale_pct": c["t2_scale_pct"],
    }

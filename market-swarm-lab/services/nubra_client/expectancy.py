"""Compounding tracker aggregation (§13).

Given closed trades, compute win rate / average return / expectancy, plus the two
India-specific breakdowns the playbook wants: performance by circuit-band width at
entry and by exit-fill quality (does a frozen-exit failure mode cluster in the losers?).

A closed trade is a dict with at least `return_pct` (signed %). Optional: `band_pct`
(circuit-band width at entry), `exit_fill_quality`, `pnl_r` (R-multiple if the caller
defines a risk unit). Pure — feed it a list, get a summary.
"""
from __future__ import annotations

from statistics import mean


def _seg(trades: list[dict], key) -> dict:
    groups: dict[str, list[float]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t["return_pct"])
    return {
        g: {
            "trades": len(rs),
            "win_rate": round(sum(r > 0 for r in rs) / len(rs), 4),
            "avg_return_pct": round(mean(rs), 4),
        }
        for g, rs in groups.items()
    }


def _band_bucket(t: dict) -> str:
    b = t.get("band_pct")
    if b is None:
        return "unknown"
    return "tight(<=5%)" if b <= 5 else "wide(>5%)"


def compute_expectancy(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("return_pct") is not None]
    if not closed:
        return {"trades": 0}

    returns = [t["return_pct"] for t in closed]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    n = len(returns)
    win_rate = len(wins) / n
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    rs = [t["pnl_r"] for t in closed if t.get("pnl_r") is not None]

    return {
        "trades": n,
        "win_rate": round(win_rate, 4),
        "avg_return_pct": round(mean(returns), 4),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        # expectancy per trade = p(win)*avg_win + p(loss)*avg_loss  (avg_loss is signed)
        "expectancy_pct": round(win_rate * avg_win + (1 - win_rate) * avg_loss, 4),
        "avg_r": round(mean(rs), 4) if rs else None,
        "by_band": _seg(closed, _band_bucket),
        "by_exit_fill": _seg(closed, lambda t: t.get("exit_fill_quality") or "unknown"),
    }

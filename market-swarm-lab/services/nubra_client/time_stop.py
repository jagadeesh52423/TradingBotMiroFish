"""Time-stop exit logic (§5).

Playbook §5: 'if the catalyst thesis hasn't confirmed within a predefined window
(e.g. 2-3 sessions), exit regardless of P&L — don't let a stalled catalyst become a
bag-hold.' This computes which held positions have aged past the window.

Session counting is weekday-based (Mon-Fri) — a trading-day proxy.
# ponytail: weekday count ignores exchange holidays; wire market_calendar holidays if 2-3
# sessions must be exact around a holiday cluster.
"""
from __future__ import annotations

from datetime import date, timedelta


def sessions_elapsed(entry: date, today: date) -> int:
    """Number of trading sessions (weekdays) strictly after `entry`, up to and incl. `today`."""
    n = 0
    d = entry
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            n += 1
    return n


def stale_symbols(entries: dict, held: set, today: date, max_sessions: int) -> list[str]:
    """Symbols held AND aged >= max_sessions since entry. entries: {symbol: entry date}."""
    out = []
    for sym, entry in entries.items():
        if sym in held and sessions_elapsed(entry, today) >= max_sessions:
            out.append(sym)
    return sorted(out)

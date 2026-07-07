"""On-demand NSE corporate-announcements lookup for any NSE symbol.

Reuses the existing NseAnnouncementsCollector (the same `nse_live` feed the bot
uses) with a configurable lookback so off-universe names like SUBROS surface too.

Usage:
    python3.11 scripts/nse_news.py SUBROS                  # last 30 days
    python3.11 scripts/nse_news.py SUBROS RELIANCE --days 60
    python3.11 scripts/nse_news.py SUBROS --json           # raw items as JSON
    python3.11 scripts/nse_news.py --selftest              # offline formatting check

ponytail: thin CLI over an existing, already-tested collector — no new source,
no scraping. Widen --days to look further back; NSE caps history per request.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(_ROOT))


# NSE item keys vary; pick the first present. Kept as data so a new key is a
# one-line addition, not a code edit.
_DATE_KEYS = ("an_dt", "sort_date", "exchdisstime", "dt")
_SUBJECT_KEYS = ("desc", "subject", "attchmntText")


def _first(item: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = item.get(k)
        if v:
            return str(v)
    return ""


def _format_item(item: dict) -> str:
    date = _first(item, _DATE_KEYS) or "?"
    subject = _first(item, _SUBJECT_KEYS) or "(no subject)"
    detail = (item.get("attchmntText") or "").strip()
    line = f"  • [{date}] {subject[:160]}"
    if detail and detail[:160] != subject[:160]:
        line += f"\n      {detail[:300]}"
    return line


def _print_symbol(symbol: str, days: int, as_json: bool) -> int:
    from services.nse_announcements.nse_announcements_collector import (
        NseAnnouncementsCollector,
    )

    result = NseAnnouncementsCollector(lookback_days=days).collect(symbol)
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return len(result.get("items", []))

    items = result.get("items", [])
    print(
        f"\n{symbol.upper()}  |  last {days}d  |  feed={result['provider_mode']}  |  "
        f"items={len(items)}  |  sentiment={result['sentiment_label']} "
        f"({result['sentiment_score']})"
    )
    if not items:
        print("  (no announcements in window)")
    for item in items:
        print(_format_item(item))
    return len(items)


def _selftest() -> None:
    # Offline formatting check — no network, asserts the field-fallback logic.
    sample = {"an_dt": "21-Jun-2026 18:00:00", "desc": "Acquisition update",
              "attchmntText": "Board approved acquisition of X."}
    out = _format_item(sample)
    assert "21-Jun-2026" in out and "Acquisition update" in out, out
    assert "Board approved" in out, out
    # Missing-date / missing-subject fall back gracefully.
    assert "[?]" in _format_item({"attchmntText": "no date"})
    assert "(no subject)" in _format_item({"an_dt": "x"})
    print("selftest OK")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="On-demand NSE announcements for any symbol")
    p.add_argument("symbols", nargs="*", help="NSE symbols, e.g. SUBROS RELIANCE")
    p.add_argument("--days", type=int, default=30, help="Lookback window (default 30)")
    p.add_argument("--json", action="store_true", help="Emit raw collector output as JSON")
    p.add_argument("--selftest", action="store_true", help="Run offline self-check and exit")
    args = p.parse_args(argv)

    if args.selftest:
        _selftest()
        return
    if not args.symbols:
        p.error("provide at least one symbol (or --selftest)")
    for sym in args.symbols:
        _print_symbol(sym, args.days, args.json)


if __name__ == "__main__":
    main()

"""Task #12 — AI-catalyst walk-forward: does AI-bullish selection LIFT the Core system's
~59-63% up-regime hit-rate, at what n-cost — or is it a clean negative (like delivery)?

Same rigor as scripts/delivery_walkforward.py. Core candidate = non-Results (earnings) +
liquid (mv*last_close > 1e7) + event-day close BELOW its 20d SMA — reusing the regime breadth
machinery from scratchpad/regime_variants.py (regime_levels/gates); returns computed here with a
STRICT next-trading-day entry.

CRITICAL PIT GUARD: a board OUTCOME publishes EOD after the meeting, so a score built from that
text can only gate a NEXT-DAY entry. BOTH arms (baseline = all core candidates; AI = bullish
subset) enter at the NEXT trading day's close after the event date and hold 20 trading days. We
NEVER compare AI-next-day vs core-same-day — that would confound the AI gate with an entry shift.

*** EXPLORATORY / research — daily-close time-exit, NOT a live win rate, NOT investment advice. ***
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta
from math import sqrt
from pathlib import Path
from statistics import mean, median

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.nse_announcements import nse_announcements_collector as nac
from services.nse_event_calendar.ai_catalyst_scorer import AiCatalystScorer

_log = logging.getLogger("ai_catalyst_walkforward")

_CACHE_PATH = _ROOT / "services" / "backtest" / ".walkfwd_cache.json"
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"
_TEXT_CACHE = _ROOT / "services" / "backtest" / ".catalyst_text_cache.json"
_DEFAULT_OUT = _ROOT / "services" / "backtest" / "ai_catalyst_walkforward_report.json"

_HOLD = 20
_MA = 20
_LIQ_MIN = 1e7                     # mv * last_close floor
_REGIME_GATE = ">20dMA"           # equal-weight breadth gate key in regime_variants.gates()
_WINDOWS = {"0-3mo": (25, 90), "3-6mo": (90, 180), "6-9mo": (180, 280)}
_ANN_DT_FIELDS = ("an_dt", "sort_date", "dt", "exchdisstime")
_ANN_DT_FORMATS = ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y")

_REGIME_DEFAULT = (
    "/private/tmp/claude-502/-Users-jagadeeshpulamarasetti-OwnCode-TradingBotMiroFish/"
    "10f59745-d08b-4841-972a-03a21400b2ef/scratchpad/regime_variants.py"
)


def load_regime_module():
    """Reuse scratchpad/regime_variants.py verbatim (regime_levels/gates). ponytail: don't reinvent."""
    path = os.environ.get("REGIME_VARIANTS_PATH", _REGIME_DEFAULT)
    if not Path(path).exists():
        raise SystemExit(f"regime_variants.py not found at {path}; set REGIME_VARIANTS_PATH")
    spec = importlib.util.spec_from_file_location("regime_variants", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_ret(price: dict, evt_iso: str, hold: int = _HOLD) -> tuple[str, bool, float] | None:
    """(event_trading_day, below_20dMA, next_day_entry_return_pct) or None if not evaluable.

    below-MA is read at the EVENT-day close (known EOD, same time the outcome publishes); the
    return enters at the FIRST trading day strictly AFTER that close (PIT next-day entry) and
    holds `hold` trading days.
    """
    close = price["c"]
    days = sorted(close)
    event_day = next((d for d in days if d >= evt_iso), None)
    if event_day is None:
        return None
    i = days.index(event_day)
    if i < _MA:
        return None
    same_day_close = close[event_day]
    if same_day_close <= 0:
        return None
    below = same_day_close < mean(close[days[j]] for j in range(i - _MA, i))
    entry_i = i + 1                                   # NEXT trading day (PIT)
    if entry_i + hold >= len(days):
        return None
    entry_close = close[days[entry_i]]
    if entry_close <= 0:
        return None
    ret = round((close[days[entry_i + hold]] / entry_close - 1) * 100, 3)
    return event_day, below, ret


def window_of(evt_iso: str, today: date) -> str | None:
    age = (today - date.fromisoformat(evt_iso)).days
    return next((w for w, (lo, hi) in _WINDOWS.items() if lo <= age < hi), None)


def stat(returns: list[float]) -> dict:
    """n, median %, hit-rate %, and binomial SE = sqrt(p(1-p)/n) as a percentage."""
    n = len(returns)
    if n == 0:
        return {"n": 0, "median_pct": None, "hit_rate_pct": None, "binomial_se_pct": None}
    p = sum(1 for r in returns if r > 0) / n
    return {
        "n": n,
        "median_pct": round(median(returns), 2),
        "hit_rate_pct": round(100 * p, 1),
        "binomial_se_pct": round(100 * sqrt(p * (1 - p) / n), 1),
    }


def _item_dt(item: dict) -> datetime | None:
    for field in _ANN_DT_FIELDS:
        value = item.get(field)
        if not value:
            continue
        for fmt in _ANN_DT_FORMATS:
            try:
                return datetime.strptime(str(value).strip(), fmt)
            except ValueError:
                continue
    return None


def pick_text(items: list[dict], event_iso: str) -> str | None:
    """Latest item with a parsed datetime on/before end-of-event-day (PIT); no blind fallback.

    Every candidate is date-guarded client-side (stamp <= cutoff) — we never trust NSE's server
    to_d filter alone, so an item without a parseable datetime is dropped rather than assumed valid.
    """
    cutoff = datetime.combine(date.fromisoformat(event_iso), dt_time.max)
    best, best_dt = None, None
    for item in items:
        stamp = _item_dt(item)
        if stamp is None or stamp > cutoff:
            continue
        if best_dt is None or stamp > best_dt:
            best, best_dt = item, stamp
    if best is None:
        return None
    text = (best.get("attchmntText") or best.get("desc") or best.get("sm_name") or "").strip()
    return text or None


class TextSource:
    """PIT announcement text via the corporate-announcements API, cached on disk (gitignored)."""

    def __init__(self, offline: bool = False, throttle: float = 0.4) -> None:
        self._offline = offline
        self._throttle = throttle
        self._collector = nac.NseAnnouncementsCollector()
        self._primed = False
        try:
            self._cache: dict[str, dict] = json.loads(_TEXT_CACHE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self._cache = {}

    def get(self, symbol: str, event_iso: str) -> str | None:
        key = f"{symbol}|{event_iso}"
        if key in self._cache:
            return self._cache[key].get("text")
        if self._offline:
            return None
        try:
            text = self._fetch(symbol, event_iso)          # None = genuine no-announcement
        except Exception as exc:
            _log.warning("NSE fetch failed for %s @ %s (not cached, retriable): %s",
                         symbol, event_iso, exc)
            return None                                     # transient — never cache a failure
        self._cache[key] = {"text": text}
        return text

    def flush(self) -> None:
        _TEXT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TEXT_CACHE.write_text(json.dumps(self._cache), encoding="utf-8")

    def _fetch(self, symbol: str, event_iso: str) -> str | None:
        """Raises on any transport/parse failure (so get() won't cache it); None = no announcement."""
        if not self._primed:
            self._collector._prime_session()
            self._primed = True
        end = date.fromisoformat(event_iso)
        url = nac._NSE_API.format(
            symbol=symbol,
            from_d=(end - timedelta(days=2)).strftime("%d-%m-%Y"),
            to_d=end.strftime("%d-%m-%Y"),
        )
        try:
            resp = self._collector._session.get(
                url, headers={"Referer": nac._REFERER, "Accept": "application/json"}, timeout=15)
            resp.raise_for_status()
            items = resp.json()
        finally:
            time.sleep(self._throttle)
        if not isinstance(items, list):
            raise ValueError(f"unexpected NSE response shape for {symbol}: {type(items)}")
        return pick_text(items, event_iso)


def core_candidates(cache: dict, today: date) -> list[dict]:
    prices = cache["prices"]
    out = []
    for event in cache["events"]:
        if event["type"] == "Results":
            continue
        price = prices.get(event["symbol"])
        if not price:
            continue
        evaluated = candidate_ret(price, event["date"])
        if evaluated is None:
            continue
        event_day, below, ret = evaluated
        if not below:
            continue
        last_close = price["c"][max(price["c"])]
        if price["mv"] * last_close <= _LIQ_MIN:
            continue
        window = window_of(event["date"], today)
        if window is None:
            continue
        out.append({"symbol": event["symbol"], "date": event["date"], "event_day": event_day,
                    "window": window, "ret": ret})
    return out


def _buckets() -> dict:
    # *_with_text = coverage-clean denominator (candidates that HAD text, any AI direction) so the
    # AI-lift (ai_all vs baseline_with_text) isolates SELECTION from text-coverage. *_all keeps the
    # full-system baseline (includes unscored) for the raw system reference.
    return {w: {"baseline_all": [], "baseline_regime": [],
                "baseline_with_text": [], "baseline_regime_with_text": [],
                "ai_all": [], "ai_regime": []}
            for w in _WINDOWS}


def run(args) -> dict:
    cache = json.loads(_CACHE_PATH.read_text())
    today = datetime.strptime(cache["built"], "%Y-%m-%d").date()
    config = json.loads(_CONFIG_PATH.read_text())

    regime = load_regime_module()
    dates, level = regime.regime_levels(cache["prices"])
    gate_by_day = regime.gates(dates, level)

    candidates = core_candidates(cache, today)
    if args.limit:
        candidates = candidates[: args.limit]

    scorer = AiCatalystScorer.from_config(config)
    text_source = TextSource(offline=args.offline, throttle=args.throttle)

    buckets = _buckets()
    counts = {"candidates": len(candidates), "with_text": 0, "unscored": 0,
              "scored_ai": 0, "degraded": 0, "bullish": 0, "removed_by_gate": 0}

    for cand in candidates:
        regime_ok = gate_by_day.get(cand["event_day"], {}).get(_REGIME_GATE, True)
        window = buckets[cand["window"]]
        window["baseline_all"].append(cand["ret"])
        if regime_ok:
            window["baseline_regime"].append(cand["ret"])

        text = text_source.get(cand["symbol"], cand["date"])
        if not text:
            counts["unscored"] += 1
            continue
        counts["with_text"] += 1
        window["baseline_with_text"].append(cand["ret"])
        if regime_ok:
            window["baseline_regime_with_text"].append(cand["ret"])

        result = scorer.score_text(text)
        if result["engine"] == "ai":
            counts["scored_ai"] += 1
        if result["degraded"]:
            counts["degraded"] += 1
        if result["direction"] == "bullish" and result["strength"] >= args.strength:
            counts["bullish"] += 1
            window["ai_all"].append(cand["ret"])
            if regime_ok:
                window["ai_regime"].append(cand["ret"])

    text_source.flush()
    counts["removed_by_gate"] = counts["with_text"] - counts["bullish"]

    report = {
        "note": ("EXPLORATORY — daily-close 20d time-exit, NOT a live win rate, NOT investment "
                 "advice. Both arms use STRICT next-trading-day entry (PIT: outcome publishes EOD)."),
        "built": str(today), "strength_threshold": args.strength, "offline": args.offline,
        "counts": counts,
        "windows": {w: {slice_name: stat(vals) for slice_name, vals in slices.items()}
                    for w, slices in buckets.items()},
    }
    return report


def print_summary(report: dict) -> None:
    counts = report["counts"]
    print("\n=== AI-catalyst walk-forward (EXPLORATORY, daily-close, next-day entry) ===")
    print(f"candidates={counts['candidates']} with_text={counts['with_text']} "
          f"unscored={counts['unscored']} scored_ai={counts['scored_ai']} "
          f"degraded={counts['degraded']} bullish={counts['bullish']} "
          f"removed_by_gate={counts['removed_by_gate']}")
    order = ("baseline_all", "baseline_with_text", "ai_all",
             "baseline_regime", "baseline_regime_with_text", "ai_regime")
    for window, slices in report["windows"].items():
        print(f"\n  {window}")
        for name in order:
            row = slices[name]
            if row["n"] == 0:
                print(f"    {name:<26} n=0")
            else:
                print(f"    {name:<26} n={row['n']:>3} med={row['median_pct']:+6.2f} "
                      f"%pos={row['hit_rate_pct']:>5}% SE=±{row['binomial_se_pct']}%")
    print("\nAI-lift = ai_all vs baseline_with_text (coverage-clean). baseline_all includes unscored.")
    print("Reminder: a lift smaller than ~1 binomial SE is noise, not an edge.")


def _demo() -> None:
    """Offline self-check of the PIT next-day math + binomial SE — NO network. ponytail: one path."""
    # 24 rising bars: same-day close on the event day must be BELOW its 20d MA is NOT guaranteed,
    # so build a dip-then-recover series where the event-day close sits below the trailing mean.
    days = [f"2025-01-{d:02d}" for d in range(1, 25)]
    closes = [100] * 20 + [80, 84, 88, 92]      # event day (idx20=80) is below the 20d MA of 100
    price = {"c": dict(zip(days, closes)), "mv": 1_000_000}
    result = candidate_ret(price, "2025-01-21", hold=2)
    assert result is not None, "candidate should evaluate"
    event_day, below, ret = result
    assert event_day == "2025-01-21" and below, result
    # next-day entry = idx21 close 84; exit = idx23 close 92 -> (92/84-1)*100 = 9.524
    assert abs(ret - 9.524) < 0.01, ret

    empty = stat([])
    assert empty["n"] == 0 and empty["binomial_se_pct"] is None, empty
    se = stat([1.0, 2.0, -1.0, -2.0])            # p=0.5, n=4 -> SE = 100*sqrt(.25/4)=25.0
    assert se["hit_rate_pct"] == 50.0 and abs(se["binomial_se_pct"] - 25.0) < 0.01, se

    assert window_of("2025-01-01", date(2025, 3, 1)) == "0-3mo"   # 59 days old (25-90d bucket)
    assert window_of("2025-01-01", date(2025, 5, 1)) == "3-6mo"   # 120 days old

    # PIT parser (no-lookahead): latest item on/before end-of-event-day wins; anything after is dropped,
    # and an item with no parseable datetime is never blindly returned. Real NSE field names/formats.
    items = [
        {"an_dt": "13-Jun-2026 09:00:00", "attchmntText": "AFTER cutoff — must be excluded"},
        {"an_dt": "11-Jun-2026 14:15:00", "attchmntText": "board approved outcome"},
    ]
    assert pick_text(items, "2026-06-12") == "board approved outcome", "must pick latest <= cutoff"
    assert pick_text([{"an_dt": "13-Jun-2026 09:00:00", "attchmntText": "x"}], "2026-06-12") is None, \
        "an item after cutoff must not leak (no blind fallback)"
    assert pick_text([{"attchmntText": "no datetime"}], "2026-06-12") is None, "undated item dropped"

    print("ai_catalyst_walkforward self-check OK: ret=%.3f%% SE=±%.1f%%" % (ret, se["binomial_se_pct"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="cap candidates (0 = all)")
    parser.add_argument("--offline", action="store_true", help="use cached text only, no NSE calls")
    parser.add_argument("--strength", type=float, default=0.0, help="min AI strength for the bullish gate")
    parser.add_argument("--throttle", type=float, default=0.4, help="seconds between NSE symbol fetches")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="JSON report path")
    parser.add_argument("--selfcheck", action="store_true", help="run offline self-check and exit")
    args = parser.parse_args()

    if args.selfcheck:
        _demo()
        return

    report = run(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"\nfull report written to {args.out}")


if __name__ == "__main__":
    main()

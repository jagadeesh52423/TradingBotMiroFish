"""Held-and-exit backtest simulation for an elected pick (§5/§13).

Two exit models over daily OHLC bars AFTER entry:
  - time_exit: hold `hold_days` sessions, exit at that close (the repo's catalyst research
    found time-exit beats a stop for this style).
  - target_stop: intrabar T1/T2/SL. Same-bar ambiguity (both T1 and SL touched in one bar) is
    broken CONSERVATIVELY — assume SL filled first (you can't know intrabar order from a daily bar).

`bars` are the sessions strictly AFTER entry (oldest-first), each {high, low, close}.
entry is the entry price. Returns a dict with realized return_pct for each model.
"""
from __future__ import annotations


def simulate_hold(entry: float, bars: list[dict], *, hold_days: int = 3,
                  targets: dict | None = None) -> dict:
    if not entry or not bars:
        return {"return_pct": None, "exit_reason": "no_forward_data"}

    held = bars[:hold_days]

    # --- time-exit: exit at the close of the last held session ---
    time_close = float(held[-1]["close"])
    time_ret = round((time_close - entry) / entry * 100, 4)

    result = {
        "return_pct": time_ret,             # headline = time-exit (validated model)
        "exit_reason": "time_exit",
        "sessions_held": len(held),
        "time_exit_return_pct": time_ret,
    }

    # --- optional target/stop scenario ---
    if targets and targets.get("t1"):
        t1 = float(targets["t1"])
        sl = float(targets.get("sl")) if targets.get("sl") else None
        ts_ret, ts_reason = None, None
        for bar in held:
            hi, lo = float(bar["high"]), float(bar["low"])
            hit_t1 = hi >= t1
            hit_sl = sl is not None and lo <= sl
            if hit_sl and hit_t1:            # conservative: stop first
                ts_ret, ts_reason = round((sl - entry) / entry * 100, 4), "stop_conservative"
                break
            if hit_sl:
                ts_ret, ts_reason = round((sl - entry) / entry * 100, 4), "stop"
                break
            if hit_t1:
                ts_ret, ts_reason = round((t1 - entry) / entry * 100, 4), "target_t1"
                break
        if ts_ret is None:                   # neither hit → time-exit close
            ts_ret, ts_reason = time_ret, "time_exit"
        result["target_stop_return_pct"] = ts_ret
        result["target_stop_reason"] = ts_reason

    return result

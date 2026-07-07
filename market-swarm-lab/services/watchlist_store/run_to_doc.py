"""Convert a scanner run's results into a Mongo document (one per run).

Each screened symbol becomes a row with status (elected | dropped) + reason + the playbook
fields, so the dashboard can render it and a backtest can later attach forward returns
(entry LTP is stored for exactly that).
"""
from __future__ import annotations


def _row(r: dict, catalyst_map: dict) -> dict:
    sig = r.get("signal") or {}
    wl = r.get("watchlist") or {}
    elected = r.get("status") == "executed"
    cat = catalyst_map.get((r.get("symbol") or "").upper()) or {}
    return {
        "symbol": r.get("symbol"),
        "catalyst": cat.get("event"),
        "catalyst_type": cat.get("type"),
        "status": "elected" if elected else "dropped",
        "reason": None if elected else (r.get("skip_reason") or r.get("status")),
        "trade": sig.get("trade"),
        "score": wl.get("score"),
        "upside_pct": round((sig.get("expected_move_pct") or 0) * 100, 2) if sig else None,
        "band_pct": r.get("band_pct"),
        "size_factor": r.get("size_factor"),
        "pcr": (r.get("fno") or {}).get("pcr"),
        "sentiment": r.get("nse_sentiment"),
        "catalyst_stack": (r.get("catalyst_stack") or {}).get("catalyst_stack_count"),
        "factors": wl.get("factors"),
        "targets": r.get("targets"),
        "entry_ltp": r.get("ltp"),   # for backtest forward-return
    }


def run_to_doc(results: list[dict], *, universe: str, run_date: str, generated_at,
               sentiment_engine: str | None = None, catalyst_map: dict | None = None) -> dict:
    """Build the run document. `generated_at` is a datetime; `run_date` an IST YYYY-MM-DD string.
    `catalyst_map` is {SYMBOL: {type, event, ...}} from discovery — attaches the catalyst per row."""
    catalyst_map = catalyst_map or {}
    rows = [_row(r, catalyst_map) for r in results if r.get("symbol")]
    elected = [x for x in rows if x["status"] == "elected"]
    # elected first, then by score desc so the dashboard's default order is useful.
    rows.sort(key=lambda x: (x["status"] != "elected", -((x["score"]) or -1)))
    return {
        "run_id": generated_at.isoformat(timespec="seconds"),
        "run_date": run_date,
        "generated_at": generated_at,
        "universe": universe,
        "sentiment_engine": sentiment_engine,
        "counts": {"total": len(rows), "elected": len(elected), "dropped": len(rows) - len(elected)},
        "symbols": rows,
    }

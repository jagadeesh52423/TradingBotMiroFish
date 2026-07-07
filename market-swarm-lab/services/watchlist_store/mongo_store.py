"""MongoDB persistence for daily watchlist runs.

One document per run in `market_swarm.watchlist_runs`. Connection from MONGO_URI
(default mongodb://localhost:27017). save_run is idempotent per run_id (re-running a
day overwrites that run rather than duplicating).
"""
from __future__ import annotations

import os


class WatchlistStore:
    def __init__(self, uri: str | None = None, db: str = "market_swarm", coll: str = "watchlist_runs") -> None:
        from pymongo import MongoClient
        self._client = MongoClient(
            uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
            serverSelectionTimeoutMS=3000,
        )
        self._coll = self._client[db][coll]
        self._coll.create_index([("generated_at", -1)])
        self._coll.create_index("run_id", unique=True)

    def save_run(self, doc: dict) -> str:
        self._coll.replace_one({"run_id": doc["run_id"]}, doc, upsert=True)
        return doc["run_id"]

    def list_runs(self, limit: int = 90) -> list[dict]:
        """Run headers (no per-symbol rows) newest-first — for the run selector."""
        cur = self._coll.find({}, {"symbols": 0}).sort("generated_at", -1).limit(limit)
        return [_clean(d) for d in cur]

    def latest_run(self) -> dict | None:
        d = self._coll.find_one({}, sort=[("generated_at", -1)])
        return _clean(d) if d else None

    def get_run(self, run_id: str) -> dict | None:
        d = self._coll.find_one({"run_id": run_id})
        return _clean(d) if d else None

    def elected_history(self, limit_runs: int = 200) -> list[dict]:
        """Per-run elected picks (symbol + entry_ltp + date) newest-first — backtest input."""
        cur = self._coll.find({}, {"run_id": 1, "run_date": 1, "symbols": 1}).sort("generated_at", -1).limit(limit_runs)
        out = []
        for d in cur:
            picks = [{"symbol": s["symbol"], "entry_ltp": s.get("entry_ltp"),
                      "score": s.get("score"), "upside_pct": s.get("upside_pct"),
                      "targets": s.get("targets")}
                     for s in d.get("symbols", []) if s.get("status") == "elected"]
            out.append({"run_id": d["run_id"], "run_date": d.get("run_date"), "elected": picks})
        return out

    def close(self) -> None:
        self._client.close()


def _clean(doc: dict) -> dict:
    """JSON-safe: drop ObjectId, ISO-format datetimes."""
    doc.pop("_id", None)
    ga = doc.get("generated_at")
    if hasattr(ga, "isoformat"):
        doc["generated_at"] = ga.isoformat()
    return doc

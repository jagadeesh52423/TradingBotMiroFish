"""Closed-trade log — append-only JSON that feeds the §13 expectancy tracker.

Each record is one closed round-trip (entry -> exit) with the fields compute_expectancy
consumes: return_pct plus the India-specific band_pct / exit_fill_quality.
"""
from __future__ import annotations

import json
from pathlib import Path


class TradeLog:
    def __init__(self, path: str = "state/nubra/closed_trades.json") -> None:
        self.path = Path(path)
        self._data: list[dict] = []
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def record(self, trade: dict) -> None:
        self._data.append(trade)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, default=str), encoding="utf-8")

    def all(self) -> list[dict]:
        return list(self._data)

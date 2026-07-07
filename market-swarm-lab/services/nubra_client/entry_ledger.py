"""Entry-date ledger for the time-stop (§5).

The order-state tracker keys orders by a hashed client_tag (entry date not recoverable),
so the time-stop needs its own tiny symbol -> entry-date store. JSON-backed, latest entry
per symbol wins; cleared on close.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class EntryLedger:
    def __init__(self, path: str = "state/nubra/entry_ledger.json") -> None:
        self.path = Path(path)
        self._data: dict[str, str] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def record_entry(self, symbol: str, on: date) -> None:
        self._data[symbol.upper()] = on.isoformat()
        self._save()

    def clear(self, symbol: str) -> None:
        if self._data.pop(symbol.upper(), None) is not None:
            self._save()

    def entries(self) -> dict[str, date]:
        return {s: date.fromisoformat(d) for s, d in self._data.items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data), encoding="utf-8")

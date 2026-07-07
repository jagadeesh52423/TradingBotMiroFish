"""§5 time-stop: session counting, ledger, and the runner exit pass."""
from __future__ import annotations

from datetime import date

import pytest

from services.nubra_client.time_stop import sessions_elapsed, stale_symbols
from services.nubra_client.entry_ledger import EntryLedger
from services.nubra_client.equity_runner import NubraEquityRunner


# --- pure session logic -----------------------------------------------------

def test_sessions_elapsed_skips_weekends():
    # Mon 2026-07-06 -> Thu 2026-07-09 = Tue/Wed/Thu = 3 sessions
    assert sessions_elapsed(date(2026, 7, 6), date(2026, 7, 9)) == 3
    # Fri -> Mon = 1 session (weekend skipped)
    assert sessions_elapsed(date(2026, 7, 3), date(2026, 7, 6)) == 1
    assert sessions_elapsed(date(2026, 7, 6), date(2026, 7, 6)) == 0


def test_stale_symbols_needs_held_and_aged():
    entries = {"SBIN": date(2026, 7, 1), "INFY": date(2026, 7, 8)}
    held = {"SBIN", "INFY"}
    # as of 2026-07-09: SBIN aged >=3 sessions, INFY only 1
    assert stale_symbols(entries, held, date(2026, 7, 9), 3) == ["SBIN"]
    # unheld symbols excluded
    assert stale_symbols(entries, {"INFY"}, date(2026, 7, 9), 3) == []


# --- ledger -----------------------------------------------------------------

def test_ledger_roundtrip(tmp_path):
    p = str(tmp_path / "led.json")
    led = EntryLedger(p)
    led.record_entry("sbin", date(2026, 7, 1))
    assert EntryLedger(p).entries() == {"SBIN": date(2026, 7, 1)}
    led.clear("SBIN")
    assert EntryLedger(p).entries() == {}


# --- runner exit pass -------------------------------------------------------

class _FakeRegistry:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, asset_class, signal, risk, symbol):
        self.dispatched.append(signal)
        return {"status": "placed"}


class _FakeStack:
    def __init__(self):
        self.registry = _FakeRegistry()


def _runner(tmp_path, circuit_provider=None):
    cfg = {
        "whitelist": ["SBIN"],
        "entry_threshold": {"time_stop": {"enabled": True, "max_sessions": 3}},
        "signal": {}, "nse": {}, "runner": {"max_workers": 1},
    }
    r = NubraEquityRunner(cfg, nubra_client=object(), equity_stack=_FakeStack())
    r._entry_ledger = EntryLedger(str(tmp_path / "led.json"))
    r._circuit_provider = circuit_provider
    return r


def test_exit_pass_closes_stale(tmp_path):
    r = _runner(tmp_path)
    r._entry_ledger.record_entry("SBIN", date(2026, 7, 1))
    out = r.run_time_stop_exits(["SBIN"], today=date(2026, 7, 9))
    assert out["exited"] == ["SBIN"]
    assert r._stack.registry.dispatched[0] == {
        "trade": "PUT", "ticker": "SBIN", "signal_id": "timestop-SBIN-2026-07-09"}
    assert r._entry_ledger.entries() == {}  # cleared after close


def test_exit_pass_skips_circuit_locked(tmp_path):
    class _Locked:
        def status(self, s):
            return {"last": 160.0, "lower": 160.0, "upper": 200.0}  # at lower circuit
    r = _runner(tmp_path, circuit_provider=_Locked())
    r._entry_ledger.record_entry("SBIN", date(2026, 7, 1))
    out = r.run_time_stop_exits(["SBIN"], today=date(2026, 7, 9))
    assert out["skipped_locked"] == ["SBIN"] and out["exited"] == []
    assert r._entry_ledger.entries() == {"SBIN": date(2026, 7, 1)}  # carried, not cleared


def test_exit_pass_disabled_when_no_ledger(tmp_path):
    r = _runner(tmp_path)
    r._entry_ledger = None
    assert r.run_time_stop_exits(["SBIN"])["reason"] == "disabled"

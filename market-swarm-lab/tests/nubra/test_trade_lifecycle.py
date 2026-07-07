"""§13 loop: entry price in ledger + closed-trade log written on time-stop exit."""
from __future__ import annotations

from datetime import date

from services.nubra_client.entry_ledger import EntryLedger
from services.nubra_client.trade_log import TradeLog
from services.nubra_client.expectancy import compute_expectancy
from services.nubra_client.equity_runner import NubraEquityRunner


def test_ledger_stores_and_returns_price(tmp_path):
    p = str(tmp_path / "led.json")
    led = EntryLedger(p)
    led.record_entry("SBIN", date(2026, 7, 1), price=100.0)
    reloaded = EntryLedger(p)
    assert reloaded.entries() == {"SBIN": date(2026, 7, 1)}  # date shape unchanged
    assert reloaded.entry_price("SBIN") == 100.0


def test_ledger_back_compat_bare_date(tmp_path):
    # old-format file (bare ISO string) must still load
    p = tmp_path / "led.json"
    p.write_text('{"SBIN": "2026-07-01"}')
    led = EntryLedger(str(p))
    assert led.entries() == {"SBIN": date(2026, 7, 1)}
    assert led.entry_price("SBIN") is None


class _FakeRegistry:
    def dispatch(self, *a, **k):
        return {"status": "placed", "qty": 10}


class _FakeStack:
    registry = _FakeRegistry()


def _runner(tmp_path):
    cfg = {"whitelist": ["SBIN"],
           "entry_threshold": {"time_stop": {"enabled": True, "max_sessions": 3}},
           "signal": {}, "nse": {}, "runner": {"max_workers": 1}}
    r = NubraEquityRunner(cfg, nubra_client=object(), equity_stack=_FakeStack())
    r._entry_ledger = EntryLedger(str(tmp_path / "led.json"))
    r._trade_log = TradeLog(str(tmp_path / "trades.json"))
    r._circuit_provider = None
    return r


def test_exit_logs_closed_trade_with_return(tmp_path):
    r = _runner(tmp_path)
    r._entry_ledger.record_entry("SBIN", date(2026, 7, 1), price=100.0)
    # exit at 106 → +6% return
    r.run_time_stop_exits(["SBIN"], today=date(2026, 7, 9), price_fn=lambda s: 106.0)
    trades = r._trade_log.all()
    assert len(trades) == 1
    assert trades[0]["symbol"] == "SBIN"
    assert trades[0]["return_pct"] == 6.0
    assert trades[0]["exit_reason"] == "time_stop"
    # and it feeds the expectancy tracker
    assert compute_expectancy(trades)["win_rate"] == 1.0


def test_exit_logs_trade_even_without_exit_price(tmp_path):
    r = _runner(tmp_path)
    r._entry_ledger.record_entry("SBIN", date(2026, 7, 1), price=100.0)

    def _boom(s):
        raise RuntimeError("no price")
    r.run_time_stop_exits(["SBIN"], today=date(2026, 7, 9), price_fn=_boom)
    trades = r._trade_log.all()
    assert len(trades) == 1 and trades[0]["return_pct"] is None  # logged, no return

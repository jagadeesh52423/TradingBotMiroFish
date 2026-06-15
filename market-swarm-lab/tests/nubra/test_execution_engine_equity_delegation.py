import sys
from pathlib import Path

# execution-engine dir uses a hyphen — not importable as a dotted package name.
# Add the dir directly so we can import the module by its file name.
_EE_PATH = str(Path(__file__).parents[2] / "services" / "execution-engine")
if _EE_PATH not in sys.path:
    sys.path.insert(0, _EE_PATH)

from execution_engine_service import ExecutionEngineService  # noqa: E402


class _Registry:
    def __init__(self):
        self.calls = []

    def dispatch(self, asset_class, signal, risk, ticker):
        self.calls.append(asset_class)
        return {"asset_class": asset_class, "status": "placed", "broker_order_id": "O1"}


def test_equity_signal_delegates_to_registry():
    reg = _Registry()
    svc = ExecutionEngineService(order_handler_registry=reg)
    signal = {"asset_class": "equity", "trade": "CALL", "ticker": "SBIN"}
    out = svc.execute(signal, {"approved": True}, "SBIN")
    assert reg.calls == ["equity"]
    assert out["status"] == "placed"


def test_options_signal_uses_legacy_path():
    reg = _Registry()
    svc = ExecutionEngineService(order_handler_registry=reg)
    signal = {"trade": "CALL", "option_type": "CALL", "option_plan": {}}  # no asset_class
    out = svc.execute(signal, {"approved": True}, "NVDA")
    assert reg.calls == []           # registry NOT used
    assert "mode" in out             # legacy options order shape preserved

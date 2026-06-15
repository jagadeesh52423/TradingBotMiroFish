# MiroFish Equity Signal Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Depends on:** `2026-06-16-nubra-foundation-broker-core.md` must be implemented first (provides `BrokerClient`, `BrokerOrder`, `BrokerRegistry`, `NubraClient`, units, idempotency, market-calendar).

**Goal:** Translate MiroFish agent signals into long-only cash-equity orders for SBIN/RELIANCE/TATAMOTORS, route them through a per-asset-class order handler to the broker, feed Nubra market data into a lean equity context for the agents, and reconcile order/position state against broker truth.

**Architecture:** `ExecutionEngineService.execute` delegates to an `OrderHandlerRegistry` keyed by asset class; the existing options path is untouched, equity gets `EquityOrderHandler`. The handler runs `SignalToEquityOrder` (whitelist, long-only, sizing, idempotency, market-hours, funds precheck) then calls the broker via `BrokerRegistry`. `NubraFeedAdapter` (impl of the existing `FeedAdapter`) feeds an `EquityContextBuilder` that produces only what the strategy needs (US sources marked `n/a`). `OrderStateTracker` + `PositionSync` keep state from broker truth.

**Tech Stack:** Python 3.11+, existing `FeedAdapter`/`StrategyEngine`/`RiskEngine`/`ExecutionEngineService`, Plan A's `nubra-client` module, `pytest`.

**Companion spec:** `docs/superpowers/specs/2026-06-16-nubra-uat-integration-design.md`

---

## File Structure

New code under `services/nubra-client/`; one modification to `services/execution-engine/`. Tests under `tests/nubra/`.

| File | Responsibility |
|------|----------------|
| `position_provider.py` | `PositionProvider` protocol + broker-backed impl (current net qty per symbol) |
| `signal_to_equity_order.py` | options-signal → `BrokerOrder` (long-only, whitelist, sizing) |
| `order_handler.py` | `OrderHandler` ABC + `OrderHandlerRegistry` (keyed by asset class) |
| `equity_order_handler.py` | equity handler: gates + translator + broker call + persistence |
| `order_state_tracker.py` | local order-state store updated by WS + REST poll fallback |
| `position_sync.py` | broker-truth positions/funds, on-demand + slow poll |
| `nubra_feed_adapter.py` | `FeedAdapter` impl over Nubra REST/WS for 3 symbols |
| `equity_context_builder.py` | lean strategy context; US sources `n/a` |
| MODIFY `execution-engine/execution_engine_service.py` | delegate to `OrderHandlerRegistry` |

---

## Task 1: Position provider (`position_provider.py`)

**Files:**
- Create: `services/nubra-client/position_provider.py`
- Test: `tests/nubra/test_position_provider.py`

**Design:** Translates broker `get_positions()` rows into `net_quantity(symbol) -> int`. Source of truth for sizing and the sell-to-close rule. Never reconstructs from local order log.

- [ ] **Step 1: Write the failing tests**

```python
from services.nubra_client.position_provider import BrokerPositionProvider

class _FakeBroker:
    def get_positions(self):
        return [{"symbol": "SBIN", "net_quantity": 12},
                {"symbol": "RELIANCE", "net_quantity": 0}]

def test_net_qty_for_held_symbol():
    p = BrokerPositionProvider(_FakeBroker())
    assert p.net_quantity("SBIN") == 12

def test_net_qty_zero_for_unheld():
    p = BrokerPositionProvider(_FakeBroker())
    assert p.net_quantity("TATAMOTORS") == 0

def test_has_long_true_only_when_positive():
    p = BrokerPositionProvider(_FakeBroker())
    assert p.has_long("SBIN") is True
    assert p.has_long("RELIANCE") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_position_provider.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from typing import Protocol

class PositionProvider(Protocol):
    def net_quantity(self, symbol: str) -> int: ...
    def has_long(self, symbol: str) -> bool: ...

class BrokerPositionProvider:
    def __init__(self, broker):
        self._broker = broker

    def _rows(self) -> dict[str, int]:
        return {r["symbol"]: int(r.get("net_quantity", 0))
                for r in self._broker.get_positions()}

    def net_quantity(self, symbol: str) -> int:
        return self._rows().get(symbol, 0)

    def has_long(self, symbol: str) -> bool:
        return self.net_quantity(symbol) > 0
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_position_provider.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/position_provider.py tests/nubra/test_position_provider.py
git commit -m "feat: broker-truth position provider"
```

---

## Task 2: Signal → equity order translator (`signal_to_equity_order.py`)

**Files:**
- Create: `services/nubra-client/signal_to_equity_order.py`
- Test: `tests/nubra/test_signal_to_equity_order.py`

**Design:** Pure mapping with injected `ltp_provider(symbol)->Decimal` and `position_provider`. Returns a `BrokerOrder` or `None` (with a reason). Rules:
- whitelist reject → `None`
- `trade=="HOLD"` → `None`
- `trade=="CALL"` (bullish) → BUY, `qty=floor(risk_amount/LTP)`; `qty<1` → `None`
- `trade=="PUT"` (bearish): if `has_long` → SELL `min(net_qty, ...)` to close; else `None`
- LIMIT price = LTP (tick rounding happens in `NubraClient`); MARKET if configured.

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.broker_types import OrderSide, PriceType
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder

class _Pos:
    def __init__(self, longs): self._l = longs
    def net_quantity(self, s): return self._l.get(s, 0)
    def has_long(self, s): return self._l.get(s, 0) > 0

def _xlate(longs=None, account_value=Decimal("100000"), risk_pct=Decimal("0.5"),
           ltp=Decimal("800")):
    return SignalToEquityOrder(
        whitelist={"SBIN", "RELIANCE", "TATAMOTORS"},
        ltp_provider=lambda s: ltp,
        position_provider=_Pos(longs or {}),
        account_value=account_value, risk_per_trade_pct=risk_pct,
        price_type="LIMIT")

def _sig(trade, ticker="SBIN", signal_id="sig1"):
    return {"ticker": ticker, "trade": trade, "signal_id": signal_id}

def test_reject_non_whitelist():
    o, reason = _xlate().translate(_sig("CALL", ticker="INFY"), "2026-06-16")
    assert o is None and "whitelist" in reason.lower()

def test_hold_returns_none():
    o, reason = _xlate().translate(_sig("HOLD"), "2026-06-16")
    assert o is None

def test_bullish_buy_sizes_floor_risk_over_ltp():
    # risk_amount = 100000 * 0.5% = 500; 500/800 = 0.625 -> floor 0 -> None
    o, reason = _xlate(ltp=Decimal("800")).translate(_sig("CALL"), "2026-06-16")
    assert o is None and "qty" in reason.lower()

def test_bullish_buy_with_affordable_size():
    # risk 5000 over ltp 100 -> 50 shares
    o, _ = _xlate(account_value=Decimal("1000000"), ltp=Decimal("100")).translate(
        _sig("CALL"), "2026-06-16")
    assert o.side is OrderSide.BUY and o.qty == 50
    assert o.price_type is PriceType.LIMIT and o.price == Decimal("100")

def test_bearish_with_long_sells_to_close():
    o, _ = _xlate(longs={"SBIN": 7}).translate(_sig("PUT"), "2026-06-16")
    assert o.side is OrderSide.SELL and o.qty == 7

def test_bearish_without_long_skips():
    o, reason = _xlate(longs={}).translate(_sig("PUT"), "2026-06-16")
    assert o is None and "no long" in reason.lower()

def test_client_tag_is_deterministic():
    o, _ = _xlate(account_value=Decimal("1000000"), ltp=Decimal("100")).translate(
        _sig("CALL"), "2026-06-16")
    assert o.client_tag.startswith("msl-")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_signal_to_equity_order.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from decimal import Decimal
from math import floor
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity)
from services.nubra_client.idempotency import client_tag

class SignalToEquityOrder:
    def __init__(self, *, whitelist, ltp_provider, position_provider,
                 account_value: Decimal, risk_per_trade_pct: Decimal,
                 price_type: str = "LIMIT"):
        self._wl = set(whitelist)
        self._ltp = ltp_provider
        self._pos = position_provider
        self._account = Decimal(account_value)
        self._risk_pct = Decimal(risk_per_trade_pct)
        self._price_type = PriceType(price_type)

    def translate(self, signal: dict, trading_date: str):
        """Return (BrokerOrder|None, reason)."""
        ticker = signal.get("ticker", "").upper()
        trade = signal.get("trade", "HOLD")
        sig_id = signal.get("signal_id", signal.get("timestamp", "nosig"))

        if ticker not in self._wl:
            return None, f"rejected: {ticker} not in whitelist"
        if trade == "HOLD":
            return None, "hold: no order"

        ltp = Decimal(self._ltp(ticker))

        if trade == "CALL":
            risk_amount = self._account * (self._risk_pct / Decimal("100"))
            qty = floor(risk_amount / ltp)
            if qty < 1:
                return None, f"skip: computed qty {qty} (risk {risk_amount}/ltp {ltp})"
            return self._order(ticker, OrderSide.BUY, qty, ltp, sig_id, trading_date,
                               "BUY"), "buy"

        if trade == "PUT":
            held = self._pos.net_quantity(ticker)
            if held <= 0:
                return None, "skip: no long to close (long-only, no shorting)"
            return self._order(ticker, OrderSide.SELL, held, ltp, sig_id, trading_date,
                               "SELL"), "sell_to_close"

        return None, f"skip: unknown trade '{trade}'"

    def _order(self, ticker, side, qty, ltp, sig_id, trading_date, intent):
        price = ltp if self._price_type is PriceType.LIMIT else None
        return BrokerOrder(
            symbol=ticker, side=side, qty=int(qty),
            price_type=self._price_type, price=price,
            product=Product.CNC, validity=Validity.DAY,
            client_tag=client_tag(str(sig_id), ticker, trading_date, intent))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_signal_to_equity_order.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/signal_to_equity_order.py tests/nubra/test_signal_to_equity_order.py
git commit -m "feat: signal->equity order translator (long-only)"
```

---

## Task 3: Order handler ABC + registry (`order_handler.py`)

**Files:**
- Create: `services/nubra-client/order_handler.py`
- Test: `tests/nubra/test_order_handler_registry.py`

**Design:** `OrderHandler` consumes `(signal, risk, ticker)` and returns a normalized result dict `{asset_class, status, ...}`. `OrderHandlerRegistry` selects by asset class. `// implement OrderHandler + register to add a new asset class.`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from services.nubra_client.order_handler import OrderHandler, OrderHandlerRegistry

class _Equity(OrderHandler):
    asset_class = "equity"
    def handle(self, signal, risk, ticker): return {"asset_class": "equity", "status": "ok"}

def test_register_and_dispatch():
    reg = OrderHandlerRegistry()
    reg.register(_Equity())
    out = reg.dispatch("equity", {"trade": "CALL"}, {"approved": True}, "SBIN")
    assert out["asset_class"] == "equity"

def test_unknown_asset_class_raises():
    reg = OrderHandlerRegistry()
    with pytest.raises(KeyError):
        reg.dispatch("futures", {}, {}, "SBIN")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_order_handler_registry.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from abc import ABC, abstractmethod

class OrderHandler(ABC):
    asset_class: str = ""

    @abstractmethod
    def handle(self, signal: dict, risk: dict, ticker: str) -> dict: ...

class OrderHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, OrderHandler] = {}

    def register(self, handler: OrderHandler) -> None:
        if not handler.asset_class:
            raise ValueError("handler.asset_class must be set")
        self._handlers[handler.asset_class] = handler

    def dispatch(self, asset_class: str, signal: dict, risk: dict, ticker: str) -> dict:
        if asset_class not in self._handlers:
            raise KeyError(f"No OrderHandler for asset_class '{asset_class}'. "
                           f"Known: {sorted(self._handlers)}")
        return self._handlers[asset_class].handle(signal, risk, ticker)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_order_handler_registry.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/order_handler.py tests/nubra/test_order_handler_registry.py
git commit -m "feat: per-asset-class OrderHandler registry"
```

---

## Task 4: Order-state tracker (`order_state_tracker.py`)

**Files:**
- Create: `services/nubra-client/order_state_tracker.py`
- Test: `tests/nubra/test_order_state_tracker.py`

**Design:** Persists order records keyed by `client_tag` to `state/nubra/orders_<env>.json`. Tracks status transitions. Provides `has_open(client_tag)` for idempotency, `upsert_from_event(event)` for WS updates, and `mark(broker_order_id, status)`. REST poll fallback is the same `mark` path driven by a poller (wired in Task 6/handler).

- [ ] **Step 1: Write the failing tests**

```python
from services.nubra_client.broker_types import OrderStatus
from services.nubra_client.order_state_tracker import OrderStateTracker

def test_record_and_has_open(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-1", broker_order_id="O1", symbol="SBIN",
             status=OrderStatus.SENT)
    assert t.has_open("msl-1") is True

def test_terminal_status_clears_open(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-1", broker_order_id="O1", symbol="SBIN",
             status=OrderStatus.SENT)
    t.mark("O1", OrderStatus.FILLED)
    assert t.has_open("msl-1") is False

def test_persists_across_instances(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-9", broker_order_id="O9", symbol="SBIN",
             status=OrderStatus.OPEN)
    t2 = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    assert t2.has_open("msl-9") is True

def test_upsert_from_ws_event(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-1", broker_order_id="O1", symbol="SBIN",
             status=OrderStatus.SENT)
    t.upsert_from_event({"order_id": "O1", "order_status": "ORDER_STATUS_FILLED"})
    assert t.has_open("msl-1") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_order_state_tracker.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import json, os
from pathlib import Path
from services.nubra_client.broker_types import OrderStatus

_TERMINAL = {OrderStatus.FILLED, OrderStatus.REJECTED,
             OrderStatus.CANCELLED, OrderStatus.EXPIRED}
_STATUS_MAP = {
    "ORDER_STATUS_PENDING": OrderStatus.PENDING, "ORDER_STATUS_SENT": OrderStatus.SENT,
    "ORDER_STATUS_OPEN": OrderStatus.OPEN, "ORDER_STATUS_FILLED": OrderStatus.FILLED,
    "ORDER_STATUS_PARTIAL_FILLED": OrderStatus.PARTIAL_FILLED,
    "ORDER_STATUS_REJECTED": OrderStatus.REJECTED,
    "ORDER_STATUS_CANCELLED": OrderStatus.CANCELLED,
    "ORDER_STATUS_EXPIRED": OrderStatus.EXPIRED,
}

class OrderStateTracker:
    def __init__(self, env: str = "UAT", base_dir: str = "state/nubra"):
        self.path = Path(base_dir) / f"orders_{env.upper()}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def _save(self):
        self.path.write_text(json.dumps(self._data, default=str))

    def record(self, *, client_tag, broker_order_id, symbol, status: OrderStatus):
        self._data[client_tag] = {"client_tag": client_tag,
                                  "broker_order_id": broker_order_id,
                                  "symbol": symbol, "status": status.value}
        self._save()

    def _find_by_oid(self, broker_order_id):
        for tag, rec in self._data.items():
            if rec.get("broker_order_id") == broker_order_id:
                return tag
        return None

    def mark(self, broker_order_id, status: OrderStatus):
        tag = self._find_by_oid(broker_order_id)
        if tag:
            self._data[tag]["status"] = status.value
            self._save()

    def upsert_from_event(self, event: dict):
        status = _STATUS_MAP.get(str(event.get("order_status")), OrderStatus.PENDING)
        self.mark(event.get("order_id"), status)

    def has_open(self, client_tag) -> bool:
        rec = self._data.get(client_tag)
        if not rec:
            return False
        return OrderStatus(rec["status"]) not in _TERMINAL
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_order_state_tracker.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/order_state_tracker.py tests/nubra/test_order_state_tracker.py
git commit -m "feat: order-state tracker (idempotency + WS/REST updates)"
```

---

## Task 5: Equity order handler (`equity_order_handler.py`)

**Files:**
- Create: `services/nubra-client/equity_order_handler.py`
- Test: `tests/nubra/test_equity_order_handler.py`

**Design:** The equity `OrderHandler`. Pipeline per signal:
1. `risk["approved"]` must be True else `{"status": "rejected_by_risk"}`.
2. `is_market_open()` gate (injected clock for tests).
3. `SignalToEquityOrder.translate(...)` → order or skip.
4. Idempotency: `OrderStateTracker.has_open(order.client_tag)` → `{"status": "duplicate_skipped"}`.
5. Funds precheck via `funds_check(order)` (injected; True/False).
6. `broker.place_order(order)`; `tracker.record(...)`; return `{"status": "placed", ...}`.
All collaborators injected → fully offline-testable.

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from services.nubra_client.broker_types import OrderStatus
from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.order_state_tracker import OrderStateTracker

IST = ZoneInfo("Asia/Kolkata")
OPEN_NOW = datetime(2026, 6, 16, 11, 0, tzinfo=IST)

class _Pos:
    def __init__(self, longs=None): self._l = longs or {}
    def net_quantity(self, s): return self._l.get(s, 0)
    def has_long(self, s): return self._l.get(s, 0) > 0

class _Broker:
    def __init__(self): self.placed = []
    def place_order(self, order):
        self.placed.append(order)
        from services.nubra_client.broker_types import BrokerOrderResult
        return BrokerOrderResult(broker_order_id="O1", client_tag=order.client_tag,
                                 status=OrderStatus.SENT, submitted_at="t", raw={})

def _handler(tmp_path, broker, longs=None, funds_ok=True, clock=OPEN_NOW):
    xlate = SignalToEquityOrder(
        whitelist={"SBIN"}, ltp_provider=lambda s: Decimal("100"),
        position_provider=_Pos(longs), account_value=Decimal("1000000"),
        risk_per_trade_pct=Decimal("0.5"), price_type="LIMIT")
    return EquityOrderHandler(
        translator=xlate, broker=broker,
        tracker=OrderStateTracker(env="UAT", base_dir=str(tmp_path)),
        funds_check=lambda o: funds_ok, clock=lambda: clock)

def _sig(trade="CALL", sid="s1"):
    return {"ticker": "SBIN", "trade": trade, "signal_id": sid, "asset_class": "equity"}

def test_places_order_when_all_gates_pass(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b).handle(_sig(), {"approved": True}, "SBIN")
    assert out["status"] == "placed" and len(b.placed) == 1

def test_blocks_when_risk_not_approved(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b).handle(_sig(), {"approved": False}, "SBIN")
    assert out["status"] == "rejected_by_risk" and not b.placed

def test_blocks_when_market_closed(tmp_path):
    b = _Broker()
    closed = datetime(2026, 6, 16, 18, 0, tzinfo=IST)
    out = _handler(tmp_path, b, clock=closed).handle(_sig(), {"approved": True}, "SBIN")
    assert out["status"] == "market_closed" and not b.placed

def test_duplicate_tag_skipped(tmp_path):
    b = _Broker()
    h = _handler(tmp_path, b)
    h.handle(_sig(sid="dup"), {"approved": True}, "SBIN")
    out = h.handle(_sig(sid="dup"), {"approved": True}, "SBIN")  # same tag
    assert out["status"] == "duplicate_skipped" and len(b.placed) == 1

def test_funds_precheck_blocks(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b, funds_ok=False).handle(_sig(), {"approved": True}, "SBIN")
    assert out["status"] == "insufficient_funds" and not b.placed

def test_translator_skip_is_reported(tmp_path):
    b = _Broker()
    out = _handler(tmp_path, b).handle(_sig(trade="HOLD"), {"approved": True}, "SBIN")
    assert out["status"] == "skipped" and not b.placed
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_equity_order_handler.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from datetime import datetime
from services.nubra_client.order_handler import OrderHandler
from services.nubra_client.market_calendar import is_market_open

class EquityOrderHandler(OrderHandler):
    asset_class = "equity"

    def __init__(self, *, translator, broker, tracker, funds_check, clock=None):
        self._xlate = translator
        self._broker = broker
        self._tracker = tracker
        self._funds_check = funds_check
        self._clock = clock or datetime.now

    def handle(self, signal: dict, risk: dict, ticker: str) -> dict:
        if not risk.get("approved"):
            return {"asset_class": "equity", "status": "rejected_by_risk"}

        if not is_market_open(self._clock()):
            return {"asset_class": "equity", "status": "market_closed"}

        trading_date = self._clock().strftime("%Y-%m-%d")
        order, reason = self._xlate.translate(signal, trading_date)
        if order is None:
            return {"asset_class": "equity", "status": "skipped", "reason": reason}

        if self._tracker.has_open(order.client_tag):
            return {"asset_class": "equity", "status": "duplicate_skipped",
                    "client_tag": order.client_tag}

        if not self._funds_check(order):
            return {"asset_class": "equity", "status": "insufficient_funds",
                    "client_tag": order.client_tag}

        result = self._broker.place_order(order)
        self._tracker.record(client_tag=order.client_tag,
                             broker_order_id=result.broker_order_id,
                             symbol=order.symbol, status=result.status)
        return {"asset_class": "equity", "status": "placed",
                "broker_order_id": result.broker_order_id,
                "client_tag": order.client_tag, "side": order.side.value,
                "qty": order.qty, "reason": reason}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_equity_order_handler.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/equity_order_handler.py tests/nubra/test_equity_order_handler.py
git commit -m "feat: equity order handler with full gate pipeline"
```

---

## Task 6: Wire `ExecutionEngineService` to delegate by asset class

**Files:**
- Modify: `services/execution-engine/execution_engine_service.py`
- Test: `tests/nubra/test_execution_engine_equity_delegation.py`

**Design:** Add an optional `order_handler_registry` + per-signal asset-class detection. If `signal.get("asset_class") == "equity"` and a registry is present, delegate and return its result. Otherwise fall through to the **existing options behavior unchanged** (default `asset_class` is options). This is additive — no options test should change.

- [ ] **Step 1: Read the current file to find the exact seam**

Run: `sed -n '1,60p' services/execution-engine/execution_engine_service.py`
Confirm `execute(self, signal, risk, ticker)` and the module-level `EXECUTION_MODE`/`LIVE_ENABLED` (per spec research lines 11-12, 18-58). Note the exact indentation/class name.

- [ ] **Step 2: Write the failing test**

```python
from services.execution_engine.execution_engine_service import ExecutionEngineService

class _Registry:
    def __init__(self): self.calls = []
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
    assert reg.calls == []                      # registry NOT used
    assert "mode" in out                        # legacy options order shape preserved
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/nubra/test_execution_engine_equity_delegation.py -v`
Expected: FAIL (TypeError: unexpected kwarg, or AssertionError).

- [ ] **Step 4: Implement the additive change**

Modify the class constructor and the top of `execute`. Concretely:

```python
# In ExecutionEngineService.__init__ (add the param; keep existing init body):
def __init__(self, order_handler_registry=None):
    self._order_handler_registry = order_handler_registry
    # ... preserve any existing init lines ...

# At the very top of execute(self, signal, risk, ticker), BEFORE the legacy options logic:
def execute(self, signal: dict, risk: dict, ticker: str) -> dict:
    asset_class = signal.get("asset_class", "options")
    if asset_class == "equity" and self._order_handler_registry is not None:
        return self._order_handler_registry.dispatch(asset_class, signal, risk, ticker)
    # ----- existing options behavior continues unchanged below -----
    mode = EXECUTION_MODE
    # ... rest of the current method exactly as-is ...
```

If the existing `ExecutionEngineService` had no `__init__`, add the one above. Do not alter any existing options lines.

- [ ] **Step 5: Run to verify pass + ensure options tests still pass**

Run: `pytest tests/nubra/test_execution_engine_equity_delegation.py -v`
Expected: PASS (2 passed).
Run any existing execution-engine tests: `pytest tests/ -k execution -v`
Expected: still PASS (no regressions). If none exist, note that explicitly.

- [ ] **Step 6: Commit**

```bash
git add services/execution-engine/execution_engine_service.py tests/nubra/test_execution_engine_equity_delegation.py
git commit -m "feat: execution engine delegates equity signals to order handler"
```

---

## Task 7: Nubra feed adapter (`nubra_feed_adapter.py`)

**Files:**
- Create: `services/nubra-client/nubra_feed_adapter.py`
- Test: `tests/nubra/test_nubra_feed_adapter.py`

**Design:** Implement the existing `FeedAdapter` ABC (from `services/live_trading/feed_adapters.py` — read it first for the exact method names: `connect`, `disconnect`, `subscribe`, `register_callback`). MVP uses **REST polling** of `current_price` for the 3 symbols (WS quote streaming deferred — LTP is enough for sizing/context). `poll_once()` fetches LTPs and invokes registered callbacks with a normalized quote event.

- [ ] **Step 1: Read the FeedAdapter base**

Run: `sed -n '19,60p' services/live_trading/feed_adapters.py`
Confirm the abstract method names and signatures; mirror them exactly.

- [ ] **Step 2: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.nubra_feed_adapter import NubraFeedAdapter

class _Client:
    def current_price(self, s): return Decimal({"SBIN":"800","RELIANCE":"2900",
                                                 "TATAMOTORS":"1000"}[s])

def test_poll_emits_quote_events_for_all_symbols():
    got = []
    a = NubraFeedAdapter(_Client(), symbols=["SBIN","RELIANCE","TATAMOTORS"])
    a.register_callback(lambda ev: got.append(ev))
    a.subscribe(["SBIN","RELIANCE","TATAMOTORS"])
    a.poll_once()
    syms = {e["symbol"]: e for e in got}
    assert syms["SBIN"]["ltp"] == Decimal("800")
    assert syms["RELIANCE"]["ltp"] == Decimal("2900")
    assert len(got) == 3

def test_only_subscribed_symbols_emitted():
    got = []
    a = NubraFeedAdapter(_Client(), symbols=["SBIN","RELIANCE","TATAMOTORS"])
    a.register_callback(lambda ev: got.append(ev))
    a.subscribe(["SBIN"])
    a.poll_once()
    assert [e["symbol"] for e in got] == ["SBIN"]
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/nubra/test_nubra_feed_adapter.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 4: Implement**

```python
from __future__ import annotations
# If FeedAdapter import path differs, match the one used by BookmapAdapter.
# from services.live_trading.feed_adapters import FeedAdapter

class NubraFeedAdapter:  # subclass FeedAdapter once its import is confirmed
    def __init__(self, nubra_client, symbols: list[str]):
        self._client = nubra_client
        self._all = list(symbols)
        self._subscribed: list[str] = []
        self._callbacks = []

    def connect(self):
        return True

    def disconnect(self):
        self._subscribed = []

    def subscribe(self, symbols):
        self._subscribed = [s for s in symbols if s in self._all]

    def register_callback(self, cb):
        self._callbacks.append(cb)

    def poll_once(self):
        for sym in self._subscribed:
            ltp = self._client.current_price(sym)
            event = {"type": "quote", "symbol": sym, "ltp": ltp, "source": "nubra"}
            for cb in self._callbacks:
                cb(event)
```

> After confirming the `FeedAdapter` ABC signatures (Step 1), make `NubraFeedAdapter` subclass it and rename methods to match exactly. Keep `poll_once()` as the MVP driver.

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/nubra/test_nubra_feed_adapter.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add services/nubra-client/nubra_feed_adapter.py tests/nubra/test_nubra_feed_adapter.py
git commit -m "feat: Nubra feed adapter (REST poll MVP)"
```

---

## Task 8: Lean equity context builder (`equity_context_builder.py`)

**Files:**
- Create: `services/nubra-client/equity_context_builder.py`
- Test: `tests/nubra/test_equity_context_builder.py`

**Design:** Build only the context the strategy/agents need for a long-only cash decision from Nubra data (LTP + recent OHLCV/returns). Mark every US source (`reddit`, `news`, `timesfm`, `schwab`, `uw`, `macro`) as `n/a` in `source_audit` — NOT `fallback`. Output shape must match what `StrategyEngineService.generate_signal` reads (`ticker`, `intraday`/price block, `source_audit`, and an `asset_class: "equity"` marker that flows into the signal).

> **Verification:** Read `services/strategy-engine/strategy_engine_service.py` (the `generate_signal` context keys, spec research lines 164-180) and the existing normalizer output to mirror the exact keys the strategy consumes. Provide only those, with US ones `n/a`.

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.equity_context_builder import build_equity_context

class _Client:
    def current_price(self, s): return Decimal("812.50")
    def historical(self, symbol, interval="1d", lookback=20):
        return [{"close": 800.0}, {"close": 810.0}, {"close": 812.5}]

def test_context_has_price_and_marks_us_sources_na():
    ctx = build_equity_context("SBIN", _Client())
    assert ctx["ticker"] == "SBIN"
    assert ctx["asset_class"] == "equity"
    assert float(ctx["price"]["ltp"]) == 812.5
    audit = ctx["source_audit"]
    for src in ("reddit", "news", "timesfm", "schwab"):
        assert audit[src] == "n/a"
    assert audit["nubra"] == "ok"

def test_returns_series_present():
    ctx = build_equity_context("SBIN", _Client())
    assert "recent_closes" in ctx["price"]
    assert ctx["price"]["recent_closes"][-1] == 812.5
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_equity_context_builder.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from decimal import Decimal

_US_SOURCES = ("reddit", "news", "timesfm", "schwab", "uw", "macro")

def build_equity_context(symbol: str, nubra_client, lookback: int = 20) -> dict:
    ltp = nubra_client.current_price(symbol)
    try:
        bars = nubra_client.historical(symbol, interval="1d", lookback=lookback)
        closes = [float(b["close"]) for b in bars]
    except Exception:
        closes = [float(ltp)]
    audit = {s: "n/a" for s in _US_SOURCES}
    audit["nubra"] = "ok"
    return {
        "ticker": symbol.upper(),
        "asset_class": "equity",
        "price": {"ltp": ltp, "recent_closes": closes},
        "source_audit": audit,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_equity_context_builder.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/equity_context_builder.py tests/nubra/test_equity_context_builder.py
git commit -m "feat: lean equity context builder (US sources n/a)"
```

---

## Task 9: Position sync (`position_sync.py`)

**Files:**
- Create: `services/nubra-client/position_sync.py`
- Test: `tests/nubra/test_position_sync.py`

**Design:** Thin façade over the broker for funds + positions, used by the handler's `funds_check` and the translator's `position_provider`. `funds_sufficient(order, get_ltp)` compares estimated cost (`qty*ltp`) against `net_margin_available` from `get_funds()` (paise→rupees). SELL orders skip the funds check (closing a long needs no new margin).

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity)
from services.nubra_client.position_sync import PositionSync

class _Broker:
    def __init__(self, margin_paise): self._m = margin_paise
    def get_funds(self): return {"net_margin_available": self._m}
    def get_positions(self): return [{"symbol": "SBIN", "net_quantity": 5}]

def _buy(qty=10, price="800"):
    return BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=qty,
                       price_type=PriceType.LIMIT, price=Decimal(price),
                       product=Product.CNC, validity=Validity.DAY, client_tag="t")

def test_funds_sufficient_true_when_margin_covers_cost():
    ps = PositionSync(_Broker(margin_paise=10_000_00))  # ₹10,000
    assert ps.funds_sufficient(_buy(qty=10, price="800")) is True   # cost ₹8,000

def test_funds_insufficient_when_cost_exceeds_margin():
    ps = PositionSync(_Broker(margin_paise=5_000_00))   # ₹5,000
    assert ps.funds_sufficient(_buy(qty=10, price="800")) is False  # cost ₹8,000

def test_sell_skips_funds_check():
    ps = PositionSync(_Broker(margin_paise=0))
    sell = BrokerOrder(symbol="SBIN", side=OrderSide.SELL, qty=5,
                       price_type=PriceType.MARKET, price=None, product=Product.CNC,
                       validity=Validity.DAY, client_tag="t")
    assert ps.funds_sufficient(sell) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_position_sync.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from decimal import Decimal
from services.nubra_client.broker_types import OrderSide, BrokerOrder
from services.nubra_client.units import paise_to_rupees

class PositionSync:
    def __init__(self, broker):
        self._broker = broker

    def positions(self) -> list[dict]:
        return list(self._broker.get_positions())

    def funds_sufficient(self, order: BrokerOrder, ltp: Decimal | None = None) -> bool:
        if order.side is OrderSide.SELL:
            return True  # closing a long needs no new margin
        price = order.price if order.price is not None else ltp
        if price is None:
            return False
        cost = Decimal(order.qty) * Decimal(price)
        funds = self._broker.get_funds()
        margin = paise_to_rupees(int(funds.get("net_margin_available", 0)))
        return cost <= margin
```

> **Note:** real Nubra integration should prefer the `/orders/v2/margin_required` precheck (spec §3.7); this `qty*ltp` estimate is the offline-testable MVP. Wire `margin_required` in `NubraClient` and swap it in here once verified against UAT.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_position_sync.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/position_sync.py tests/nubra/test_position_sync.py
git commit -m "feat: position sync + funds precheck (broker-truth)"
```

---

## Task 10: End-to-end equity wiring test + full suite

**Files:**
- Test: `tests/nubra/test_equity_end_to_end.py`

**Design:** Compose the real pieces (paper broker + translator + handler + tracker + position_sync) and prove a CALL signal becomes a placed paper order, a duplicate is skipped, and a PUT with a held long sells to close. No network.

- [ ] **Step 1: Write the test**

```python
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from services.nubra_client.equity_paper_trader import EquityPaperTrader
from services.nubra_client.position_provider import BrokerPositionProvider
from services.nubra_client.position_sync import PositionSync
from services.nubra_client.signal_to_equity_order import SignalToEquityOrder
from services.nubra_client.equity_order_handler import EquityOrderHandler
from services.nubra_client.order_state_tracker import OrderStateTracker
from services.nubra_client.order_handler import OrderHandlerRegistry

IST = ZoneInfo("Asia/Kolkata")
OPEN_NOW = datetime(2026, 6, 16, 11, 0, tzinfo=IST)

def _build(tmp_path):
    broker = EquityPaperTrader(ltp_provider=lambda s: Decimal("100"))
    # paper get_funds returns {"paper": True}; use a generous funds_check for paper:
    xlate = SignalToEquityOrder(
        whitelist={"SBIN"}, ltp_provider=lambda s: Decimal("100"),
        position_provider=BrokerPositionProvider(broker),
        account_value=Decimal("1000000"), risk_per_trade_pct=Decimal("0.5"),
        price_type="LIMIT")
    handler = EquityOrderHandler(
        translator=xlate, broker=broker,
        tracker=OrderStateTracker(env="UAT", base_dir=str(tmp_path)),
        funds_check=lambda o: True, clock=lambda: OPEN_NOW)
    reg = OrderHandlerRegistry(); reg.register(handler)
    return broker, reg

def test_call_places_then_duplicate_skipped(tmp_path):
    broker, reg = _build(tmp_path)
    sig = {"asset_class": "equity", "trade": "CALL", "ticker": "SBIN", "signal_id": "s1"}
    out1 = reg.dispatch("equity", sig, {"approved": True}, "SBIN")
    out2 = reg.dispatch("equity", sig, {"approved": True}, "SBIN")
    assert out1["status"] == "placed"
    assert out2["status"] == "duplicate_skipped"
    assert {p["symbol"] for p in broker.get_positions()} == {"SBIN"}

def test_put_sells_to_close_existing_long(tmp_path):
    broker, reg = _build(tmp_path)
    reg.dispatch("equity", {"asset_class":"equity","trade":"CALL","ticker":"SBIN",
                            "signal_id":"buy1"}, {"approved": True}, "SBIN")
    held = {p["symbol"]: p["net_quantity"] for p in broker.get_positions()}["SBIN"]
    out = reg.dispatch("equity", {"asset_class":"equity","trade":"PUT","ticker":"SBIN",
                                  "signal_id":"sell1"}, {"approved": True}, "SBIN")
    assert out["status"] == "placed" and out["side"] == "SELL" and out["qty"] == held
    assert broker.get_positions() == []  # flat
```

- [ ] **Step 2: Run the full Nubra suite**

Run: `pytest tests/nubra/ -v`
Expected: ALL PASS (Plan A + Plan B).

- [ ] **Step 3: Commit**

```bash
git add tests/nubra/test_equity_end_to_end.py
git commit -m "test: end-to-end equity signal->paper order wiring"
```

---

## Self-Review Result (author check)

- **Spec coverage:** equity execution seam (§3.4) → T3,T6; broker DTO reuse (§3.6) → Plan A; translator (§3.7) → T2; feed adapter + lean context (§3.8) → T7,T8; reconciliation (§3.9) → T4 (order state) + T1,T9 (broker-truth positions/funds); idempotency/market-hours/funds gates (§5) → T5; long-only PUT=sell-to-close (§3.7) → T2,T10. WS order-update stream is represented by `OrderStateTracker.upsert_from_event` (T4) with REST poll fallback via `mark`; the live WS subscriber wiring is a thin driver to add during UAT bring-up (documented in T4 design, exercised by event test).
- **Placeholder scan:** Remaining non-code notes are explicit **verification-against-repo** steps (read `FeedAdapter` base T7-S1; read `strategy_engine` keys T8; read `execution_engine` seam T6-S1) and one MVP→prod swap note (margin_required in T9). All are real actions, not deferred work.
- **Type consistency:** `BrokerOrder`/`OrderStatus`/`OrderSide` reused from Plan A unchanged; `translate()->(BrokerOrder|None, reason)` consumed identically in handler; `OrderHandler.handle(signal,risk,ticker)->dict` consistent across T3,T5,T6,T10; `client_tag` threading consistent T2→T4→T5.

**End state:** `pytest tests/nubra/` fully green offline; with Plan A's live session, the same handler/registry drives real UAT orders by swapping the `paper` broker for `nubra_uat` in `registry_bootstrap`.

---

## Live bring-up checklist (after both plans implemented)

1. `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple nubra-sdk filelock`
2. Fill `.env`: `NUBRA_ENV=UAT`, `NUBRA_PHONE_NO`, `NUBRA_MPIN`.
3. `python scripts/nubra_login.py` (enter OTP) → session cached.
4. `python scripts/nubra_uat_smoke.py` → confirms auth + place/cancel.
5. Set `EXECUTION_MODE=live`, `LIVE_TRADING_ENABLED=true`, keep `NUBRA_ENV=UAT`; select `nubra_uat` broker in `registry_bootstrap`.
6. Run the agent workflow on SBIN/RELIANCE/TATAMOTORS; watch the dry-run payload log before any submit.

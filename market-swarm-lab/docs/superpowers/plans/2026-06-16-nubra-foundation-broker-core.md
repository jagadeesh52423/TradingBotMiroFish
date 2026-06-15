# Nubra Foundation & Broker Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an authenticated Nubra UAT broker client that can resolve the 3 whitelisted NSE symbols, place/cancel/track cash-equity orders, and is fronted by a broker-agnostic interface with an offline paper implementation.

**Architecture:** A single `NubraClient` wraps the official `nubra-sdk` (the only SDK touchpoint) and consumes a cross-process, file-locked session token from `NubraSession`. A `BrokerClient` ABC with a `BrokerRegistry` exposes `NubraBroker` (live UAT) and `EquityPaperTrader` (offline) behind one contract and one `BrokerOrder` DTO. Deterministic utilities (paise/tick/idempotency/market-hours) are pure and fully unit-tested.

**Tech Stack:** Python 3.11+, `nubra-sdk` (TestPyPI), `filelock`, `pytest`, `Decimal` for money, `zoneinfo` for IST.

**Companion spec:** `docs/superpowers/specs/2026-06-16-nubra-uat-integration-design.md`

---

## File Structure

All new code under `market-swarm-lab/services/nubra-client/`. Tests under `market-swarm-lab/tests/nubra/`.

| File | Responsibility |
|------|----------------|
| `units.py` | paise⇄rupee + tick-size rounding (pure) |
| `market_calendar.py` | `is_market_open()` NSE hours + holidays (pure) |
| `idempotency.py` | deterministic `client_tag()` (pure) |
| `broker_types.py` | `BrokerOrder`, `BrokerOrderResult`, enums |
| `broker_interface.py` | `BrokerClient` ABC |
| `broker_registry.py` | mode→`BrokerClient` registry |
| `equity_paper_trader.py` | offline `BrokerClient` impl |
| `nubra_session.py` | file-locked, per-env token store |
| `nubra_client.py` | `nubra-sdk` wrapper (env, instruments, orders, market data) |
| `instrument_resolver.py` | `symbol → ref_id` + tick/lot cache |
| `nubra_broker.py` | `BrokerClient` impl over `NubraClient` |
| `scripts/nubra_login.py` | interactive OTP/MPIN login CLI |
| `scripts/nubra_uat_smoke.py` | end-to-end UAT smoke test |
| `config/nubra_config.json` | whitelist, product, defaults |

**Config note for all tasks:** `services/nubra-client/` is a hyphenated dir (matches repo convention e.g. `execution-engine`). Import it the way sibling services are imported in this repo — check `apps/api/main.py` for the existing `sys.path`/import pattern and follow it exactly. Add an `__init__.py` if and only if sibling service dirs have one.

---

## Task 0: Scaffolding, dependencies, config

**Files:**
- Modify: `market-swarm-lab/pyproject.toml`
- Modify: `market-swarm-lab/.env.example`
- Create: `market-swarm-lab/config/nubra_config.json`
- Create: `market-swarm-lab/services/nubra-client/` (dir; `__init__.py` per repo convention)
- Create: `market-swarm-lab/tests/nubra/` (dir; `__init__.py` if other tests dirs have one)

- [ ] **Step 1: Add dependencies**

In `pyproject.toml` `[project] dependencies`, add `"filelock>=3.13"`. Add `nubra-sdk` with an install note — it is published on **TestPyPI**, so it cannot resolve from the default index. Add this comment block near the dependency list:

```toml
# nubra-sdk is published on TestPyPI. Install with:
#   pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple nubra-sdk
# Pin the version once verified in UAT (research saw v0.4.4).
```

Add `"nubra-sdk"` to dependencies (version left unpinned until verified in Step 3).

- [ ] **Step 2: Install and verify the SDK imports**

Run: `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple nubra-sdk filelock`
Then run: `python -c "import nubra_sdk; print(nubra_sdk.__version__ if hasattr(nubra_sdk,'__version__') else 'imported')"`
Expected: prints a version or `imported` with no ImportError.

- [ ] **Step 3: Record the real SDK import surface**

Run: `python -c "import nubra_sdk, pkgutil; print([m.name for m in pkgutil.iter_modules(nubra_sdk.__path__)])"`
Then locate the concrete classes named in the spec research (`InitNubraSdk`, `NubraEnv`, `NubraTrader`, market-data + instrument classes). Run:
`python - <<'PY'
import nubra_sdk, inspect, pkgutil
for m in pkgutil.walk_packages(nubra_sdk.__path__, "nubra_sdk."):
    print(m.name)
PY`
Write the real dotted import paths into a comment block at the top of `nubra_client.py` (created in Task 8). **This is a real verification step — do not assume the research's paths; confirm them against the installed package.**

- [ ] **Step 4: Create config file**

Create `config/nubra_config.json`:

```json
{
  "env": "UAT",
  "whitelist": ["SBIN", "RELIANCE", "TATAMOTORS"],
  "exchange": "NSE",
  "product": "CNC",
  "default_order_type": "LIMIT",
  "validity": "DAY",
  "limit_offset_pct": 0.0,
  "risk_per_trade_pct": 0.5,
  "max_trades_per_day": 3,
  "session_file_dir": "~",
  "instrument_cache_ttl_hours": 12
}
```

- [ ] **Step 5: Extend `.env.example`**

Append:

```bash
# --- Nubra (UAT by default; PROD requires explicit NUBRA_ENV=PROD) ---
NUBRA_ENV=UAT
NUBRA_PHONE_NO=
NUBRA_MPIN=
# Institutional fields (only if account is institutional; UAT here is retail):
NUBRA_CLIENT_CODE=I01ZUD
NUBRA_EXCHANGE_CLIENT_CODE=
NUBRA_USERNAME=
NUBRA_PASSWORD=
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example config/nubra_config.json services/nubra-client tests/nubra
git commit -m "chore: scaffold nubra-client module, deps, config"
```

---

## Task 1: Money & tick-size utilities (`units.py`)

**Files:**
- Create: `services/nubra-client/units.py`
- Test: `tests/nubra/test_units.py`

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.units import rupees_to_paise, paise_to_rupees, round_to_tick

def test_rupees_to_paise_rounds_half_up():
    assert rupees_to_paise("1344.00") == 134400
    assert rupees_to_paise(1344) == 134400
    assert rupees_to_paise("25.255") == 2526  # half-up

def test_paise_to_rupees():
    assert paise_to_rupees(134400) == Decimal("1344.00")

def test_round_to_tick_nse_5paise():
    # NSE common tick 0.05; 1344.02 -> 1344.00, 1344.03 -> 1344.05
    assert round_to_tick("1344.02", "0.05") == Decimal("1344.00")
    assert round_to_tick("1344.03", "0.05") == Decimal("1344.05")

def test_round_to_tick_then_paise_is_exact():
    r = round_to_tick("1344.03", "0.05")
    assert rupees_to_paise(r) == 134405
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_units.py -v`
Expected: FAIL (ModuleNotFoundError / ImportError).

- [ ] **Step 3: Implement**

```python
from decimal import Decimal, ROUND_HALF_UP

def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))

def rupees_to_paise(rupees) -> int:
    return int((_d(rupees) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def paise_to_rupees(paise: int) -> Decimal:
    return (Decimal(int(paise)) / 100).quantize(Decimal("0.01"))

def round_to_tick(rupees, tick) -> Decimal:
    r, t = _d(rupees), _d(tick)
    steps = (r / t).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (steps * t).quantize(Decimal("0.01"))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_units.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/units.py tests/nubra/test_units.py
git commit -m "feat: paise/tick-size money utilities for nubra"
```

---

## Task 2: Market calendar (`market_calendar.py`)

**Files:**
- Create: `services/nubra-client/market_calendar.py`
- Test: `tests/nubra/test_market_calendar.py`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from services.nubra_client.market_calendar import is_market_open

IST = ZoneInfo("Asia/Kolkata")

def test_open_midday_weekday():
    assert is_market_open(datetime(2026, 6, 16, 11, 0, tzinfo=IST)) is True  # Tue

def test_closed_before_open():
    assert is_market_open(datetime(2026, 6, 16, 9, 0, tzinfo=IST)) is False

def test_closed_after_close():
    assert is_market_open(datetime(2026, 6, 16, 15, 31, tzinfo=IST)) is False

def test_closed_weekend():
    assert is_market_open(datetime(2026, 6, 14, 11, 0, tzinfo=IST)) is False  # Sun

def test_closed_holiday_republic_day():
    assert is_market_open(datetime(2026, 1, 26, 11, 0, tzinfo=IST)) is False

def test_non_ist_input_is_converted():
    utc = ZoneInfo("UTC")
    # 05:45 UTC == 11:15 IST -> open
    assert is_market_open(datetime(2026, 6, 16, 5, 45, tzinfo=utc)) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_market_calendar.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)

# Minimal 2026 NSE trading-holiday list. Extend as needed; this is intentionally
# small (spec: rich holiday feed is deferred). Dates are IST calendar days.
NSE_HOLIDAYS = {
    "2026-01-26",  # Republic Day
    "2026-03-06",  # Holi (verify)
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
}

def is_market_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST))
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    now = now.astimezone(IST)
    if now.weekday() >= 5:
        return False
    if now.strftime("%Y-%m-%d") in NSE_HOLIDAYS:
        return False
    return NSE_OPEN <= now.time() <= NSE_CLOSE
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_market_calendar.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/market_calendar.py tests/nubra/test_market_calendar.py
git commit -m "feat: NSE market-hours/holiday gate"
```

---

## Task 3: Idempotency tag (`idempotency.py`)

**Files:**
- Create: `services/nubra-client/idempotency.py`
- Test: `tests/nubra/test_idempotency.py`

- [ ] **Step 1: Write the failing tests**

```python
from services.nubra_client.idempotency import client_tag

def test_deterministic():
    a = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    b = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    assert a == b

def test_distinct_on_any_field():
    base = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    assert client_tag("sig124", "SBIN", "2026-06-16", "BUY") != base
    assert client_tag("sig123", "RELIANCE", "2026-06-16", "BUY") != base
    assert client_tag("sig123", "SBIN", "2026-06-17", "BUY") != base
    assert client_tag("sig123", "SBIN", "2026-06-16", "SELL") != base

def test_prefixed_and_bounded():
    t = client_tag("sig123", "SBIN", "2026-06-16", "BUY")
    assert t.startswith("msl-")
    assert len(t) <= 24
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_idempotency.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
import hashlib

def client_tag(signal_id: str, ticker: str, trading_date: str, intent: str) -> str:
    raw = f"{signal_id}|{ticker}|{trading_date}|{intent}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"msl-{digest}"
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_idempotency.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/idempotency.py tests/nubra/test_idempotency.py
git commit -m "feat: deterministic order idempotency tag"
```

---

## Task 4: Broker DTOs & enums (`broker_types.py`)

**Files:**
- Create: `services/nubra-client/broker_types.py`
- Test: `tests/nubra/test_broker_types.py`

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.broker_types import (
    OrderSide, Product, PriceType, Validity, OrderStatus,
    BrokerOrder, BrokerOrderResult,
)

def test_broker_order_minimal():
    o = BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=10,
                    price_type=PriceType.LIMIT, price=Decimal("812.50"),
                    product=Product.CNC, validity=Validity.DAY, client_tag="msl-x")
    assert o.qty == 10
    assert o.side is OrderSide.BUY

def test_market_order_allows_none_price():
    o = BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=1,
                    price_type=PriceType.MARKET, price=None,
                    product=Product.CNC, validity=Validity.DAY, client_tag="msl-y")
    assert o.price is None

def test_limit_requires_price():
    import pytest
    with pytest.raises(ValueError):
        BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=1,
                    price_type=PriceType.LIMIT, price=None,
                    product=Product.CNC, validity=Validity.DAY, client_tag="msl-z")

def test_result_terminal_helper():
    r = BrokerOrderResult(broker_order_id="1", client_tag="msl-x",
                          status=OrderStatus.FILLED, submitted_at="t", raw={})
    assert r.is_terminal() is True
    r2 = BrokerOrderResult(broker_order_id="1", client_tag="msl-x",
                           status=OrderStatus.OPEN, submitted_at="t", raw={})
    assert r2.is_terminal() is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_broker_types.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"

class Product(Enum):
    CNC = "CNC"        # delivery / cash
    IDAY = "IDAY"      # intraday (not used in MVP)

class PriceType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"

class Validity(Enum):
    DAY = "DAY"
    IOC = "IOC"

class OrderStatus(Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    OPEN = "OPEN"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

_TERMINAL = {OrderStatus.FILLED, OrderStatus.REJECTED,
             OrderStatus.CANCELLED, OrderStatus.EXPIRED}

@dataclass
class BrokerOrder:
    symbol: str
    side: OrderSide
    qty: int
    price_type: PriceType
    price: Decimal | None
    product: Product
    validity: Validity
    client_tag: str

    def __post_init__(self):
        if self.price_type is PriceType.LIMIT and self.price is None:
            raise ValueError("LIMIT order requires a price")
        if self.qty < 1:
            raise ValueError("qty must be >= 1")

@dataclass
class BrokerOrderResult:
    broker_order_id: str
    client_tag: str
    status: OrderStatus
    submitted_at: str
    raw: dict[str, Any] = field(default_factory=dict)

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_broker_types.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/broker_types.py tests/nubra/test_broker_types.py
git commit -m "feat: broker-agnostic equity order DTOs"
```

---

## Task 5: `BrokerClient` ABC & `BrokerRegistry`

**Files:**
- Create: `services/nubra-client/broker_interface.py`
- Create: `services/nubra-client/broker_registry.py`
- Test: `tests/nubra/test_broker_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_registry import BrokerRegistry

class _Dummy(BrokerClient):
    def place_order(self, order): return "placed"
    def cancel_order(self, broker_order_id): return True
    def modify_order(self, broker_order_id, **changes): raise NotImplementedError
    def get_order_status(self, broker_order_id): return None
    def get_positions(self): return []
    def get_funds(self): return {}

def test_register_and_get():
    reg = BrokerRegistry()
    reg.register("paper", _Dummy)
    assert isinstance(reg.get("paper"), _Dummy)

def test_unknown_mode_raises():
    reg = BrokerRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")

def test_cannot_instantiate_abc():
    with pytest.raises(TypeError):
        BrokerClient()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_broker_registry.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the ABC**

`broker_interface.py`:

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from services.nubra_client.broker_types import BrokerOrder, BrokerOrderResult

# Implement this interface to add a new broker; register it in BrokerRegistry.
class BrokerClient(ABC):
    @abstractmethod
    def place_order(self, order: BrokerOrder) -> BrokerOrderResult: ...
    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool: ...
    @abstractmethod
    def modify_order(self, broker_order_id: str, **changes) -> BrokerOrderResult: ...
    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult | None: ...
    @abstractmethod
    def get_positions(self) -> list[dict]: ...
    @abstractmethod
    def get_funds(self) -> dict: ...
```

`broker_registry.py`:

```python
from __future__ import annotations
from typing import Callable
from services.nubra_client.broker_interface import BrokerClient

class BrokerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., BrokerClient]] = {}

    def register(self, mode: str, factory: Callable[..., BrokerClient]) -> None:
        self._factories[mode] = factory

    def get(self, mode: str, **kwargs) -> BrokerClient:
        if mode not in self._factories:
            raise KeyError(f"No broker registered for mode '{mode}'. "
                           f"Known: {sorted(self._factories)}")
        return self._factories[mode](**kwargs)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_broker_registry.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/broker_interface.py services/nubra-client/broker_registry.py tests/nubra/test_broker_registry.py
git commit -m "feat: BrokerClient ABC + registry"
```

---

## Task 6: Offline equity paper broker (`equity_paper_trader.py`)

**Files:**
- Create: `services/nubra-client/equity_paper_trader.py`
- Test: `tests/nubra/test_equity_paper_trader.py`

**Design:** Implements `BrokerClient`. In-memory order book + positions. LIMIT fills at the order price; MARKET fills at an injected `ltp_provider(symbol) -> Decimal`. Deterministic, no time/network. This is the faithful dry-run of `NubraBroker`.

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity, OrderStatus)
from services.nubra_client.equity_paper_trader import EquityPaperTrader

def _order(symbol="SBIN", side=OrderSide.BUY, qty=10, price="800.00",
           pt=PriceType.LIMIT, tag="msl-1"):
    return BrokerOrder(symbol=symbol, side=side, qty=qty, price_type=pt,
                       price=Decimal(price) if price else None,
                       product=Product.CNC, validity=Validity.DAY, client_tag=tag)

def test_limit_buy_fills_and_creates_position():
    pt = EquityPaperTrader(ltp_provider=lambda s: Decimal("810.00"))
    res = pt.place_order(_order())
    assert res.status is OrderStatus.FILLED
    pos = {p["symbol"]: p for p in pt.get_positions()}
    assert pos["SBIN"]["net_quantity"] == 10

def test_market_buy_fills_at_ltp():
    pt = EquityPaperTrader(ltp_provider=lambda s: Decimal("805.55"))
    res = pt.place_order(_order(price=None, pt=PriceType.MARKET, tag="msl-2"))
    assert res.status is OrderStatus.FILLED
    assert pt.get_order_status(res.broker_order_id).status is OrderStatus.FILLED

def test_sell_reduces_position():
    pt = EquityPaperTrader(ltp_provider=lambda s: Decimal("810.00"))
    pt.place_order(_order(qty=10, tag="msl-3"))
    pt.place_order(_order(side=OrderSide.SELL, qty=4, tag="msl-4"))
    pos = {p["symbol"]: p for p in pt.get_positions()}
    assert pos["SBIN"]["net_quantity"] == 6

def test_cancel_unknown_returns_false():
    pt = EquityPaperTrader(ltp_provider=lambda s: Decimal("1"))
    assert pt.cancel_order("nope") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_equity_paper_trader.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from decimal import Decimal
from typing import Callable
from itertools import count
from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_types import (
    BrokerOrder, BrokerOrderResult, OrderSide, OrderStatus)

class EquityPaperTrader(BrokerClient):
    def __init__(self, ltp_provider: Callable[[str], Decimal]):
        self._ltp = ltp_provider
        self._ids = count(1)
        self._orders: dict[str, BrokerOrderResult] = {}
        self._net: dict[str, int] = {}
        self._avg: dict[str, Decimal] = {}

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        fill_price = order.price if order.price is not None else self._ltp(order.symbol)
        oid = f"paper-{next(self._ids)}"
        signed = order.qty if order.side is OrderSide.BUY else -order.qty
        prev = self._net.get(order.symbol, 0)
        self._net[order.symbol] = prev + signed
        if order.side is OrderSide.BUY:
            self._avg[order.symbol] = fill_price  # simplistic; MVP
        res = BrokerOrderResult(broker_order_id=oid, client_tag=order.client_tag,
                                status=OrderStatus.FILLED, submitted_at="paper",
                                raw={"fill_price": str(fill_price)})
        self._orders[oid] = res
        return res

    def cancel_order(self, broker_order_id: str) -> bool:
        return False  # paper fills immediately; nothing open to cancel

    def modify_order(self, broker_order_id: str, **changes) -> BrokerOrderResult:
        raise NotImplementedError("paper modify not supported in MVP")

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult | None:
        return self._orders.get(broker_order_id)

    def get_positions(self) -> list[dict]:
        return [{"symbol": s, "net_quantity": q,
                 "avg_price": str(self._avg.get(s, Decimal("0")))}
                for s, q in self._net.items() if q != 0]

    def get_funds(self) -> dict:
        return {"paper": True}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_equity_paper_trader.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/equity_paper_trader.py tests/nubra/test_equity_paper_trader.py
git commit -m "feat: offline equity paper broker"
```

---

## Task 7: Cross-process session store (`nubra_session.py`)

**Files:**
- Create: `services/nubra-client/nubra_session.py`
- Test: `tests/nubra/test_nubra_session.py`

**Design:** Per-env JSON file `~/.nubra_session_<env>.json`, mode 0600. Read path lock-free; write path takes a `filelock` lock. Stores `session_token`, `auth_token`, `expires_at` (ISO). Provides `load()`, `save(...)`, `is_valid(now)`, and `refresh_with(callback)` that takes the lock, re-checks validity (double-checked locking), and only calls `callback` if still invalid.

- [ ] **Step 1: Write the failing tests**

```python
import os, json
from datetime import datetime, timedelta, timezone
from services.nubra_client.nubra_session import NubraSession

def test_save_then_load_roundtrip(tmp_path):
    s = NubraSession(env="UAT", base_dir=str(tmp_path))
    exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    s.save(session_token="tok", auth_token="auth", expires_at=exp)
    loaded = NubraSession(env="UAT", base_dir=str(tmp_path)).load()
    assert loaded["session_token"] == "tok"

def test_file_mode_is_0600(tmp_path):
    s = NubraSession(env="UAT", base_dir=str(tmp_path))
    exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    s.save(session_token="tok", auth_token="a", expires_at=exp)
    mode = oct(os.stat(s.path).st_mode & 0o777)
    assert mode == "0o600"

def test_env_isolation(tmp_path):
    NubraSession("UAT", str(tmp_path)).save("uat-tok", "a",
        (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    NubraSession("PROD", str(tmp_path)).save("prod-tok", "a",
        (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    assert NubraSession("UAT", str(tmp_path)).load()["session_token"] == "uat-tok"
    assert NubraSession("PROD", str(tmp_path)).load()["session_token"] == "prod-tok"

def test_is_valid_false_when_expired(tmp_path):
    s = NubraSession("UAT", str(tmp_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    s.save("tok", "a", past)
    assert s.is_valid() is False

def test_refresh_with_calls_callback_when_invalid(tmp_path):
    s = NubraSession("UAT", str(tmp_path))
    calls = []
    def cb():
        calls.append(1)
        return {"session_token": "new", "auth_token": "a",
                "expires_at": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    s.refresh_with(cb)
    assert calls == [1]
    assert s.load()["session_token"] == "new"

def test_refresh_with_skips_callback_when_already_valid(tmp_path):
    s = NubraSession("UAT", str(tmp_path))
    s.save("tok", "a", (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    calls = []
    s.refresh_with(lambda: calls.append(1))
    assert calls == []  # double-checked locking: still valid, no re-auth
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_nubra_session.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock

class NubraSession:
    def __init__(self, env: str, base_dir: str = "~"):
        self.env = env.upper()
        base = Path(os.path.expanduser(base_dir))
        self.path = base / f".nubra_session_{self.env}.json"
        self.lock_path = str(self.path) + ".lock"

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        with open(self.path) as f:
            return json.load(f)

    def save(self, session_token: str, auth_token: str, expires_at: str) -> None:
        data = {"env": self.env, "session_token": session_token,
                "auth_token": auth_token, "expires_at": expires_at}
        # Write 0600: create with restrictive mode, then write.
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(self.path, 0o600)

    def is_valid(self, now: datetime | None = None) -> bool:
        data = self.load()
        if not data or not data.get("session_token"):
            return False
        try:
            exp = datetime.fromisoformat(data["expires_at"])
        except (KeyError, ValueError):
            return False
        now = now or datetime.now(timezone.utc)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > now

    def refresh_with(self, callback) -> dict:
        """Take the lock, double-check validity, call callback only if still invalid.
        callback() must return {session_token, auth_token, expires_at}."""
        with FileLock(self.lock_path, timeout=60):
            if self.is_valid():
                return self.load()
            result = callback()
            if result:
                self.save(result["session_token"], result["auth_token"],
                          result["expires_at"])
            return self.load()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_nubra_session.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/nubra_session.py tests/nubra/test_nubra_session.py
git commit -m "feat: file-locked per-env nubra session store"
```

---

## Task 8: SDK wrapper (`nubra_client.py`) + instrument resolver

**Files:**
- Create: `services/nubra-client/instrument_resolver.py`
- Create: `services/nubra-client/nubra_client.py`
- Test: `tests/nubra/test_instrument_resolver.py`
- Test: `tests/nubra/test_nubra_client.py`

**Design:** `NubraClient` is the ONLY module importing `nubra_sdk`. It is constructed with an already-valid session token (from `NubraSession`) and a config dict. It exposes typed methods. To keep it testable offline, the actual SDK objects are created in a `_build_sdk()` method that tests monkeypatch or that accepts injected SDK handles via constructor (`sdk_trader=`, `sdk_market=`, `sdk_instruments=`). `instrument_resolver` caches `symbol -> {ref_id, tick_size, lot_size}`.

> **SDK verification (from Task 0 Step 3):** Replace the placeholder dotted paths below with the REAL ones discovered in the installed package. The method NAMES from research are: market data `current_price(instrument, exchange)`; trading `NubraTrader(nubra, version="V2").create_order(dict)` / `cancel_orders_v2(order_ids=[...])` / `get_order(order_id)` / `orders()`; portfolio `positions(version="V2")` / `funds()`; instruments `get_instrument_by_symbol(symbol, exchange).ref_id` and `.tick_size`/`.lot_size`. Confirm each before relying on it.

- [ ] **Step 1: Write the failing tests (resolver, with a fake instrument source)**

```python
from services.nubra_client.instrument_resolver import InstrumentResolver

class _FakeInst:
    def __init__(self): self.calls = 0
    def get_instrument_by_symbol(self, symbol, exchange="NSE"):
        self.calls += 1
        table = {"SBIN": (101, "0.05", 1), "RELIANCE": (202, "0.05", 1),
                 "TATAMOTORS": (303, "0.05", 1)}
        ref, tick, lot = table[symbol]
        return type("I", (), {"ref_id": ref, "tick_size": tick, "lot_size": lot})()

def test_resolve_returns_fields():
    r = InstrumentResolver(_FakeInst())
    info = r.resolve("SBIN")
    assert info["ref_id"] == 101
    assert info["tick_size"] == "0.05"

def test_resolve_is_cached():
    fake = _FakeInst()
    r = InstrumentResolver(fake)
    r.resolve("SBIN"); r.resolve("SBIN")
    assert fake.calls == 1  # second hit served from cache
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_instrument_resolver.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the resolver**

```python
from __future__ import annotations

class InstrumentResolver:
    def __init__(self, sdk_instruments, exchange: str = "NSE"):
        self._inst = sdk_instruments
        self._exchange = exchange
        self._cache: dict[str, dict] = {}

    def resolve(self, symbol: str) -> dict:
        if symbol in self._cache:
            return self._cache[symbol]
        rec = self._inst.get_instrument_by_symbol(symbol, exchange=self._exchange)
        info = {"ref_id": int(rec.ref_id),
                "tick_size": str(getattr(rec, "tick_size", "0.05")),
                "lot_size": int(getattr(rec, "lot_size", 1))}
        self._cache[symbol] = info
        return info
```

- [ ] **Step 4: Verify resolver passes**

Run: `pytest tests/nubra/test_instrument_resolver.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Write failing tests for `NubraClient` (inject fake SDK handles)**

```python
from decimal import Decimal
from services.nubra_client.nubra_client import NubraClient

class _FakeTrader:
    def __init__(self): self.last = None
    def create_order(self, payload): self.last = payload; return type("R",(),{"order_id":"OID1"})()
    def cancel_orders_v2(self, order_ids=None, basket_ids=None): return {"cancelled": order_ids}

class _FakeMarket:
    def current_price(self, instrument, exchange="NSE"):
        return type("P", (), {"price": 81250, "prev_close": 81000})()  # paise

class _FakeInst:
    def get_instrument_by_symbol(self, symbol, exchange="NSE"):
        return type("I", (), {"ref_id": 101, "tick_size": "0.05", "lot_size": 1})()

def _client():
    return NubraClient(config={"exchange": "NSE", "product": "CNC", "validity": "DAY"},
                       sdk_trader=_FakeTrader(), sdk_market=_FakeMarket(),
                       sdk_instruments=_FakeInst())

def test_current_price_returns_rupees():
    c = _client()
    assert c.current_price("SBIN") == Decimal("812.50")

def test_place_limit_buy_builds_paise_payload():
    c = _client()
    res = c.place_order(symbol="SBIN", side="BUY", qty=10,
                        price_type="LIMIT", price=Decimal("812.50"), client_tag="msl-1")
    assert res["order_id"] == "OID1"
    payload = c._sdk_trader.last
    assert payload["order_price"] == 81250          # paise
    assert payload["order_qty"] == 10
    assert payload["order_side"] == "ORDER_SIDE_BUY"
    assert payload["order_delivery_type"] == "ORDER_DELIVERY_TYPE_CNC"
    assert payload["price_type"] == "LIMIT"
    assert payload["ref_id"] == 101
    assert payload["tag"] == "msl-1"

def test_place_rounds_to_tick_before_paise():
    c = _client()
    c.place_order(symbol="SBIN", side="BUY", qty=1, price_type="LIMIT",
                  price=Decimal("812.53"), client_tag="msl-2")  # -> 812.55
    assert c._sdk_trader.last["order_price"] == 81255
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/nubra/test_nubra_client.py -v`
Expected: FAIL (ImportError / attribute).

- [ ] **Step 7: Implement `NubraClient`**

```python
from __future__ import annotations
from decimal import Decimal
from services.nubra_client.units import rupees_to_paise, paise_to_rupees, round_to_tick
from services.nubra_client.instrument_resolver import InstrumentResolver

_SIDE = {"BUY": "ORDER_SIDE_BUY", "SELL": "ORDER_SIDE_SELL"}
_PRODUCT = {"CNC": "ORDER_DELIVERY_TYPE_CNC", "IDAY": "ORDER_DELIVERY_TYPE_IDAY"}

class NubraClient:
    """Only module that imports nubra_sdk. Construct via NubraClient.from_session(...)
    in production; tests inject fake sdk_* handles."""

    def __init__(self, config: dict, sdk_trader, sdk_market, sdk_instruments):
        self._cfg = config
        self._sdk_trader = sdk_trader
        self._sdk_market = sdk_market
        self._resolver = InstrumentResolver(sdk_instruments,
                                            exchange=config.get("exchange", "NSE"))

    # ---- production constructor (verify SDK paths from Task 0 Step 3) ----
    @classmethod
    def from_session(cls, config: dict, session_token: str):
        # PSEUDO-WIRING — replace dotted paths with the real installed ones:
        # from nubra_sdk.start_sdk import InitNubraSdk, NubraEnv
        # from nubra_sdk.trading.trading_data import NubraTrader
        # from nubra_sdk.marketdata.market_data import <MarketData>
        # from nubra_sdk.ticker.<instruments> import InstrumentData
        # env = NubraEnv.UAT if config["env"]=="UAT" else NubraEnv.PROD
        # nubra = InitNubraSdk(env, session_token=session_token)  # confirm ctor
        # trader = NubraTrader(nubra, version="V2")
        # market = <MarketData>(nubra); instruments = InstrumentData(nubra)
        # return cls(config, trader, market, instruments)
        raise NotImplementedError("Wire real SDK handles per Task 0 Step 3, then "
                                  "return cls(config, trader, market, instruments)")

    def current_price(self, symbol: str) -> Decimal:
        p = self._sdk_market.current_price(symbol, exchange=self._cfg.get("exchange", "NSE"))
        return paise_to_rupees(p.price)

    def place_order(self, *, symbol, side, qty, price_type, price, client_tag) -> dict:
        info = self._resolver.resolve(symbol)
        payload = {
            "ref_id": info["ref_id"],
            "order_type": "ORDER_TYPE_REGULAR",
            "order_qty": int(qty),
            "order_side": _SIDE[side],
            "order_delivery_type": _PRODUCT[self._cfg.get("product", "CNC")],
            "validity_type": self._cfg.get("validity", "DAY"),
            "price_type": price_type,
            "exchange": self._cfg.get("exchange", "NSE"),
            "tag": client_tag,
        }
        if price_type == "LIMIT":
            rounded = round_to_tick(price, info["tick_size"])
            payload["order_price"] = rupees_to_paise(rounded)
        res = self._sdk_trader.create_order(payload)
        return {"order_id": getattr(res, "order_id", None), "payload": payload}

    def cancel_order(self, order_id: str) -> dict:
        return self._sdk_trader.cancel_orders_v2(order_ids=[order_id])

    def get_order(self, order_id: str):
        return self._sdk_trader.get_order(order_id)

    def positions(self) -> list:
        # verify: portfolio handle vs trader handle in installed SDK
        return self._sdk_trader.positions(version="V2")
```

> Note: `place_order` returns a plain dict including the built `payload` so `NubraBroker` can dry-run-log it. `from_session` and `positions`/`get_order` wiring MUST be confirmed against the installed SDK (Task 0 Step 3) — the injected-handle constructor is what the unit tests exercise.

- [ ] **Step 8: Run to verify pass**

Run: `pytest tests/nubra/test_nubra_client.py -v`
Expected: PASS (3 passed).

- [ ] **Step 9: Commit**

```bash
git add services/nubra-client/instrument_resolver.py services/nubra-client/nubra_client.py tests/nubra/test_instrument_resolver.py tests/nubra/test_nubra_client.py
git commit -m "feat: nubra-sdk wrapper + instrument resolver"
```

---

## Task 9: `NubraBroker` (BrokerClient over NubraClient)

**Files:**
- Create: `services/nubra-client/nubra_broker.py`
- Test: `tests/nubra/test_nubra_broker.py`

- [ ] **Step 1: Write the failing tests (inject a fake NubraClient)**

```python
from decimal import Decimal
from services.nubra_client.broker_types import (
    BrokerOrder, OrderSide, Product, PriceType, Validity, OrderStatus)
from services.nubra_client.nubra_broker import NubraBroker

class _FakeNubraClient:
    def __init__(self): self.placed = None; self.cancelled = None
    def place_order(self, *, symbol, side, qty, price_type, price, client_tag):
        self.placed = dict(symbol=symbol, side=side, qty=qty, price_type=price_type,
                           price=price, client_tag=client_tag)
        return {"order_id": "OID9", "payload": {"ref_id": 101, "order_price": 81250}}
    def cancel_order(self, order_id): self.cancelled = order_id; return {"cancelled": [order_id]}

def _order():
    return BrokerOrder(symbol="SBIN", side=OrderSide.BUY, qty=10,
                       price_type=PriceType.LIMIT, price=Decimal("812.50"),
                       product=Product.CNC, validity=Validity.DAY, client_tag="msl-1")

def test_place_maps_enums_to_strings_and_returns_result(capsys):
    fc = _FakeNubraClient()
    b = NubraBroker(fc, dry_run_log=True)
    res = b.place_order(_order())
    assert fc.placed["side"] == "BUY"
    assert fc.placed["price_type"] == "LIMIT"
    assert res.broker_order_id == "OID9"
    assert res.status is OrderStatus.SENT
    assert "ref_id" in capsys.readouterr().out  # dry-run payload logged

def test_modify_not_implemented():
    import pytest
    b = NubraBroker(_FakeNubraClient())
    with pytest.raises(NotImplementedError):
        b.modify_order("OID9", price=Decimal("1"))

def test_cancel_delegates():
    fc = _FakeNubraClient()
    assert NubraBroker(fc).cancel_order("OID9") is True
    assert fc.cancelled == "OID9"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_nubra_broker.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import json
from datetime import datetime, timezone
from services.nubra_client.broker_interface import BrokerClient
from services.nubra_client.broker_types import (
    BrokerOrder, BrokerOrderResult, OrderStatus)

class NubraBroker(BrokerClient):
    def __init__(self, nubra_client, dry_run_log: bool = True):
        self._c = nubra_client
        self._dry_run_log = dry_run_log

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        out = self._c.place_order(
            symbol=order.symbol, side=order.side.value, qty=order.qty,
            price_type=order.price_type.value, price=order.price,
            client_tag=order.client_tag)
        if self._dry_run_log:
            print("NUBRA ORDER PAYLOAD:", json.dumps(out.get("payload", {}), default=str))
        return BrokerOrderResult(
            broker_order_id=str(out.get("order_id")), client_tag=order.client_tag,
            status=OrderStatus.SENT,
            submitted_at=datetime.now(timezone.utc).isoformat(), raw=out)

    def cancel_order(self, broker_order_id: str) -> bool:
        self._c.cancel_order(broker_order_id)
        return True

    def modify_order(self, broker_order_id: str, **changes) -> BrokerOrderResult:
        raise NotImplementedError("modify deferred (spec §1 non-goals)")

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult | None:
        raw = self._c.get_order(broker_order_id)
        if raw is None:
            return None
        status = _map_status(getattr(raw, "order_status", "PENDING"))
        return BrokerOrderResult(broker_order_id=broker_order_id,
                                 client_tag=getattr(raw, "tag", ""), status=status,
                                 submitted_at="", raw={"order": str(raw)})

    def get_positions(self) -> list[dict]:
        return list(self._c.positions())

    def get_funds(self) -> dict:
        return {}  # wired in Plan B PositionSync

_STATUS_MAP = {
    "ORDER_STATUS_PENDING": OrderStatus.PENDING, "ORDER_STATUS_SENT": OrderStatus.SENT,
    "ORDER_STATUS_OPEN": OrderStatus.OPEN, "ORDER_STATUS_FILLED": OrderStatus.FILLED,
    "ORDER_STATUS_PARTIAL_FILLED": OrderStatus.PARTIAL_FILLED,
    "ORDER_STATUS_REJECTED": OrderStatus.REJECTED,
    "ORDER_STATUS_CANCELLED": OrderStatus.CANCELLED,
    "ORDER_STATUS_EXPIRED": OrderStatus.EXPIRED,
}

def _map_status(raw_status: str) -> OrderStatus:
    return _STATUS_MAP.get(str(raw_status), OrderStatus.PENDING)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/nubra/test_nubra_broker.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/nubra_broker.py tests/nubra/test_nubra_broker.py
git commit -m "feat: NubraBroker over NubraClient"
```

---

## Task 10: Login CLI (`scripts/nubra_login.py`)

**Files:**
- Create: `market-swarm-lab/scripts/nubra_login.py`

**Design:** Interactive one-shot. Reads `NUBRA_ENV`, `NUBRA_PHONE_NO`, `NUBRA_MPIN` from env. Runs the SDK auth flow (sendphoneotp → prompt OTP → verifyphoneotp → verifypin), computes an `expires_at` (default 7 days), and persists via `NubraSession`. No automated test (interactive + live). Manual verification only.

- [ ] **Step 1: Implement the CLI**

```python
"""Interactive Nubra login. Run weekly (or when the session expires).
Long-running services NEVER prompt — they read the cached session.

Usage: python scripts/nubra_login.py
Requires env: NUBRA_ENV, NUBRA_PHONE_NO, NUBRA_MPIN
"""
import os, sys
from datetime import datetime, timedelta, timezone
# Adjust import to match repo's service import pattern (see apps/api/main.py):
from services.nubra_client.nubra_session import NubraSession

def main() -> int:
    env = os.getenv("NUBRA_ENV", "UAT")
    phone = os.getenv("NUBRA_PHONE_NO")
    mpin = os.getenv("NUBRA_MPIN")
    if not phone or not mpin:
        print("Set NUBRA_PHONE_NO and NUBRA_MPIN in the environment.", file=sys.stderr)
        return 2

    # --- SDK auth flow: replace with real installed SDK calls (Task 0 Step 3) ---
    # from nubra_sdk.start_sdk import InitNubraSdk, NubraEnv
    # sdk = InitNubraSdk(NubraEnv.UAT if env=="UAT" else NubraEnv.PROD)
    # sdk.send_phone_otp(phone)            # POST /sendphoneotp
    # otp = input("Enter OTP: ").strip()
    # auth_token = sdk.verify_phone_otp(phone, otp)   # POST /verifyphoneotp -> auth_token
    # session_token = sdk.verify_pin(mpin)            # POST /verifypin -> session_token
    raise NotImplementedError(
        "Wire the real SDK auth calls here per Task 0 Step 3, then persist below.")

    # expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    # NubraSession(env=env).save(session_token=session_token,
    #                            auth_token=auth_token, expires_at=expires_at)
    # print(f"Nubra {env} session saved. Valid ~7 days.")
    # return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Manual verification (after real SDK wiring)**

Run: `NUBRA_ENV=UAT NUBRA_PHONE_NO=<phone> NUBRA_MPIN=<mpin> python scripts/nubra_login.py`
Expected: prompts for OTP, then prints "Nubra UAT session saved"; `~/.nubra_session_UAT.json` exists with mode 0600.

- [ ] **Step 3: Commit**

```bash
git add scripts/nubra_login.py
git commit -m "feat: interactive nubra login CLI"
```

---

## Task 11: UAT smoke test (`scripts/nubra_uat_smoke.py`)

**Files:**
- Create: `market-swarm-lab/scripts/nubra_uat_smoke.py`

**Design:** End-to-end manual UAT check. Loads session (fails loudly if missing), builds `NubraClient.from_session`, then: funds → LTP for 3 symbols → place a tiny LIMIT far below market (won't fill) → get status → cancel → confirm cancelled. Never runs in CI.

- [ ] **Step 1: Implement**

```python
"""Nubra UAT smoke test. Requires a valid session (run scripts/nubra_login.py first).
Places ONE tiny LIMIT far from market, then cancels it. UAT only — refuses PROD."""
import json, os, sys
from decimal import Decimal
from services.nubra_client.nubra_session import NubraSession
from services.nubra_client.nubra_client import NubraClient

SYMBOLS = ["SBIN", "RELIANCE", "TATAMOTORS"]

def main() -> int:
    env = os.getenv("NUBRA_ENV", "UAT")
    if env != "UAT":
        print("Refusing to run smoke test outside UAT.", file=sys.stderr)
        return 2
    sess = NubraSession(env=env)
    if not sess.is_valid():
        print("No valid session. Run: python scripts/nubra_login.py", file=sys.stderr)
        return 2

    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                      "config", "nubra_config.json")))
    client = NubraClient.from_session(cfg, sess.load()["session_token"])

    for s in SYMBOLS:
        print(f"{s} LTP = ₹{client.current_price(s)}")

    sym = "SBIN"
    ltp = client.current_price(sym)
    far_price = (ltp * Decimal("0.5")).quantize(Decimal("0.01"))  # well below market
    placed = client.place_order(symbol=sym, side="BUY", qty=1, price_type="LIMIT",
                                price=far_price, client_tag="msl-smoke")
    oid = placed["order_id"]
    print("Placed:", oid, "payload:", placed["payload"])
    print("Status:", client.get_order(oid))
    print("Cancel:", client.cancel_order(oid))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Manual run (after login + real SDK wiring)**

Run: `NUBRA_ENV=UAT python scripts/nubra_uat_smoke.py`
Expected: prints 3 LTPs, places + shows OPEN status, then cancels. Confirm in Nubra UAT that no fill occurred.

- [ ] **Step 3: Commit**

```bash
git add scripts/nubra_uat_smoke.py
git commit -m "feat: nubra UAT smoke test script"
```

---

## Task 12: Register brokers + full suite green

**Files:**
- Create: `services/nubra-client/registry_bootstrap.py`
- Test: `tests/nubra/test_registry_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
from decimal import Decimal
from services.nubra_client.registry_bootstrap import build_broker_registry
from services.nubra_client.equity_paper_trader import EquityPaperTrader

def test_paper_mode_resolves_offline():
    reg = build_broker_registry(ltp_provider=lambda s: Decimal("100"))
    assert isinstance(reg.get("paper"), EquityPaperTrader)

def test_nubra_live_registered_but_guarded():
    reg = build_broker_registry(ltp_provider=lambda s: Decimal("100"))
    # nubra_live is registered but requires explicit construction args; absence of
    # those must raise, proving it is not silently usable.
    import pytest
    with pytest.raises(Exception):
        reg.get("nubra_live")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/nubra/test_registry_bootstrap.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from typing import Callable
from decimal import Decimal
from services.nubra_client.broker_registry import BrokerRegistry
from services.nubra_client.equity_paper_trader import EquityPaperTrader

def build_broker_registry(ltp_provider: Callable[[str], Decimal]) -> BrokerRegistry:
    reg = BrokerRegistry()
    reg.register("paper", lambda: EquityPaperTrader(ltp_provider=ltp_provider))
    reg.register("nubra_uat", _require_nubra)   # constructed with a NubraBroker kwarg
    reg.register("nubra_live", _require_nubra)
    return reg

def _require_nubra(nubra_broker=None):
    if nubra_broker is None:
        raise RuntimeError("nubra_* mode requires a constructed NubraBroker "
                           "(pass nubra_broker=...). Run nubra_login first.")
    return nubra_broker
```

- [ ] **Step 4: Run to verify pass + FULL SUITE**

Run: `pytest tests/nubra/ -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add services/nubra-client/registry_bootstrap.py tests/nubra/test_registry_bootstrap.py
git commit -m "feat: broker registry bootstrap (paper + nubra modes)"
```

---

## Self-Review Result (author check)

- **Spec coverage:** NubraClient/session/login (§3.1–3.3) → T7,T8,T10; broker ABC+registry (§3.5) → T5,T9,T12; DTOs (§3.6) → T4; units/tick (§3.1) → T1; idempotency/market-hours (§5) → T2,T3; paper parity (§3.5) → T6; smoke (§7) → T11. **Equity execution seam (§3.4), translator (§3.7), feed/context (§3.8), reconciliation (§3.9) are intentionally Plan B.**
- **Placeholder scan:** The only non-code markers are the explicit **SDK-verification** instructions (Task 0 Step 3; `from_session`/login/positions wiring). These are real, required verification actions against the installed package, not skipped work — flagged as such.
- **Type consistency:** `BrokerOrder`/`BrokerOrderResult`/enums used identically across T4–T12; `client_tag` field name consistent; `place_order` returns `{"order_id","payload"}` consistently consumed by `NubraBroker`.

**End state:** `pytest tests/nubra/` green offline; after `nubra_login` + SDK wiring, `nubra_uat_smoke.py` places & cancels a real UAT order.

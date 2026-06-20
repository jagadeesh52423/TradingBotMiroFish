# Configurable Universe + Pluggable Market-Data Provider (Fyers) — Design Spec

**Goal:** (A) Make the trading universe config/CLI-selectable (`nifty50`/`midcap150`/custom). (B) Make market data (OHLCV + price) pluggable so a `FyersDataProvider` can replace Nubra UAT's thin data — **orders stay on Nubra; only market data switches.** Both follow the existing `SignalStrategy` registry pattern (OCP). Default behavior is UNCHANGED (Nubra provider, existing whitelist).

Run tests: `python3.11 -m pytest tests/nubra/ -q` (currently 363 passing — must stay green + new tests).

---

## PART A — Pluggable Market-Data Provider

### New: `services/nubra_client/market_data_provider.py`
```python
from abc import ABC, abstractmethod
from decimal import Decimal

# Implement this interface + register via @register_provider to add a new market-data source.
class MarketDataProvider(ABC):
    @abstractmethod
    def current_price(self, symbol: str) -> Decimal: ...
    @abstractmethod
    def historical(self, symbol: str, interval: str = "1d", lookback: int = 20) -> list[dict]: ...
    # historical returns list[{"close": float, "timestamp": int ms}] oldest-first (match NubraClient today)
```
Verify the EXACT current return shapes by reading `NubraClient.historical`/`current_price` + `equity_context_builder.py` and mirror them precisely (do not change Nubra's behavior).

### New: `services/nubra_client/market_data_registry.py`
`_PROVIDER_REGISTRY: dict[str, type]`, `@register_provider(name)`, `get_provider(name, config) -> MarketDataProvider` (unknown name → ValueError listing known). Each provider gets a `from_config(cls, config)` classmethod.

### `NubraClient` (services/nubra_client/nubra_client.py)
- Make it subclass `MarketDataProvider` (it already implements both methods — no behavior change). Register as `@register_provider("nubra")` with a `from_config` that calls the existing `from_session(config)`.

### `equity_assembly.py build_equity_stack()`
- Add optional `data_provider: MarketDataProvider | None = None`. When None, resolve from `config.get("data_provider", "nubra")` via `get_provider`.
- In `_nubra_uat_components()` (~line 111-121): keep `broker = NubraBroker(nubra_client)` (orders ALWAYS Nubra). Set `market_data = data_provider` and `effective_ltp = data_provider.current_price` — **both must move to the chosen provider together** (the coupling code-mapper flagged). `NubraFeedAdapter` (streaming) stays on Nubra.
- Config key: `"data_provider": "nubra"` (default) in nubra_config.json.

---

## PART B — Configurable Universe

### New: `services/nubra_client/universe_registry.py`
```python
_UNIVERSE_REGISTRY: dict[str, list[str]] = {}
def register_universe(name, symbols): _UNIVERSE_REGISTRY[name] = list(symbols)
def load_universes_from_config(config): for n,s in config.get("universes", {}).items(): register_universe(n, s)
def get_universe(name) -> list[str]: ...  # KeyError-safe → ValueError listing known
```

### `config/nubra_config.json`
Add:
```json
"universe": "nifty50",
"universes": {
  "nifty50": [ ...the current 48 whitelist symbols... ],
  "midcap150": [ ...the 150 midcap symbols (from the midcap run; UPLL→UPL)... ]
}
```
Keep `"whitelist"` as a backward-compat fallback (if no `universe`/`universes`, use `whitelist`).

### `scripts/run_nubra_equity.py`
- New `_resolve_whitelist(config, universe_override) -> list[str]`: precedence = `--universe` flag > `config["universe"]` > legacy `config["whitelist"]`. Mutate `config["whitelist"] = resolved` IN PLACE before BOTH `build_equity_stack()` and `NubraEquityRunner()` (both read `config["whitelist"]`).
- In `main()`: load config → `load_universes_from_config(config)` → parse args (so `--universe choices=sorted(_UNIVERSE_REGISTRY)` is populated; this requires config-load-before-argparse — reorder as needed, mirror the `--strategy` pattern).
- Add `--universe` arg (choices from registry, default None).

---

## PART C — FyersDataProvider (code-complete, mocked tests; live wiring pending user creds)

### New package: `services/fyers_client/`
- `fyers_data_provider.py`: `@register_provider("fyers")` `FyersDataProvider(MarketDataProvider)`.
  - `from_config(config)`: read `config["fyers"]` (client_id, access_token, optionally secret/redirect) and `os.environ`/.env (`FYERS_CLIENT_ID`, `FYERS_ACCESS_TOKEN`). Lazy-build the `fyers_apiv3.fyersModel.FyersModel` client (do NOT construct at import; key-optional like the AI engine).
  - `_to_fyers_symbol(sym)`: `f"NSE:{sym}-EQ"`.
  - `historical(symbol, interval="1d", lookback=20)`: map interval→Fyers resolution (`"1d"`→`"1D"`), compute range_from/range_to from lookback, call `fyers.history(...)`, map `candles` `[ts,O,H,L,C,V]` → `[{"close": float(C), "timestamp": int(ts*1000)}]` oldest-first. On error or missing token → raise a clear error (caller decides; do NOT silently return Nubra data).
  - `current_price(symbol)`: `fyers.quotes({"symbols": fyers_symbol})` → `Decimal(str(ltp))`.
  - Token/auth: assume an `access_token` is provided in config/env (the interactive/TOTP flow that mints it is OUT OF SCOPE for this task — document it). If absent, `from_config` still constructs but calls raise "FYERS_ACCESS_TOKEN missing".
- Do NOT add `fyers-apiv3` as a hard dependency; import it lazily inside the client build (`try/except ImportError` with a clear message). 

### Tests (mock the fyers SDK — no real network/account)
`tests/nubra/test_market_data_provider.py` + `tests/nubra/test_fyers_data_provider.py`:
- registry resolves `nubra`/`fyers`; unknown → ValueError.
- NubraClient still satisfies the ABC (isinstance / has methods); existing Nubra tests unaffected.
- FyersDataProvider with a MOCKED fyers client: `historical()` maps candles→{close,timestamp} oldest-first + symbol formatting; `current_price()` maps quotes→Decimal. No token → clear error, client not built. Mock `fyers_apiv3.fyersModel.FyersModel` (patch where imported).
- `build_equity_stack` injects a fake provider and the runner consumes it (provider swap works end-to-end with a stub).
- universe_registry: load from config, get_universe, unknown → ValueError; `_resolve_whitelist` precedence (flag > universe > whitelist).

---

## Out of scope
- The Fyers interactive/TOTP auth flow that mints the access_token (document the steps; the provider just consumes a token).
- Switching orders off Nubra (orders stay Nubra).
- Live Fyers testing (needs the user's account + token).

## Constraints
- Default config = Nubra provider + existing universe → behavior unchanged; all 363 existing tests stay green.
- Never stage `.env`/`auth_data.db*`. Extensibility-first: new provider/universe = new class/config entry, no edits to callers.

# Sector-Trend Gate — Design Spec

**Goal:** Stop the bot going long a stock whose SECTOR is in a downtrend (the IT case: filings bullish, but Nifty IT de-rating on macro/AI-unwind → stock falls). A `SectorTrendGate` downgrades CALL→HOLD when the stock's sector index is trending down. Config-driven, toggleable, graceful when data/mapping is missing. Default OFF unless enabled so existing behavior is unchanged until opted in.

Keep `python3.11 -m pytest tests/nubra/ -q` green (currently 415) + new tests. Branch off main.

**Confirmed live (Fyers):** index symbol format is `NSE:{INDEX}-INDEX`; `NIFTYIT`, `NIFTY50`, `NIFTYBANK` valid (`CNXIT` invalid). Nifty IT currently below recent levels (downtrend); Nifty Bank rising.

---

## Part A — Provider index history (optional capability)
In `services/nubra_client/market_data_provider.py`, add an OPTIONAL method to `MarketDataProvider`:
```python
def index_history(self, index: str, lookback: int = 20) -> list[dict] | None:
    """Recent daily closes for a market index (e.g. 'NIFTYIT'), oldest-first
    [{"close": float, "timestamp": int ms}], or None if unsupported."""
    return None  # default: provider doesn't support indices
```
- `FyersDataProvider.index_history`: fetch `NSE:{index}-INDEX` via `fyers.history(...)` (resolution "1D", range from lookback*2.5 calendar days), map candles→[{close,timestamp_ms}] oldest-first (reuse the same candle mapping as `historical`). Missing token/SDK → same RuntimeError as today; empty/`s!=ok` → return None.
- `NubraClient`: inherits the default (returns None — Nubra UAT has no indices). Do NOT change Nubra behavior.

## Part B — SectorTrendGate
New `services/nubra_client/sector_trend_gate.py`:
```python
class SectorTrendGate:
    """Downgrade CALL→HOLD when the stock's sector index is in a downtrend.

    # To add a sector: add a stock→index entry in config['sector_filter']['sector_index'].
    """
    def __init__(self, provider, *, enabled: bool, sma_period: int, sector_index: dict[str,str]) -> None: ...

    @classmethod
    def from_config(cls, config: dict, provider) -> "SectorTrendGate":
        cfg = config.get("sector_filter", {})
        return cls(provider, enabled=bool(cfg.get("enabled", False)),
                   sma_period=int(cfg.get("sma_period", 10)),
                   sector_index={k.upper(): v for k,v in cfg.get("sector_index", {}).items()})

    def evaluate(self, symbol: str) -> tuple[bool, str|None]:
        """Return (sector_ok, reason). sector_ok=False => block CALL.
        Skips (returns True) when disabled, unmapped, or index data unavailable."""
```
Logic:
- If `not enabled` → (True, None).
- index = `sector_index.get(symbol.upper())`; if None → (True, None) (unmapped → skip).
- bars = `provider.index_history(index, lookback=sma_period+5)`; if None or `len(bars) < sma_period` → (True, "sector_data_unavailable") and log INFO (graceful, fail-open).
- closes = [b["close"] for b in bars]; sma = mean(closes[-sma_period:]); last = closes[-1].
- **Bearish (block) if `last < sma`** → (False, f"sector_downtrend:{index} {last:.0f}<SMA{sma_period} {sma:.0f}").
- Else (True, None).

## Part C — Pipeline integration
In `scripts/run_nubra_equity.py` (`_process_symbol`) — find where the signal `trade` is finalized / where `ExpectedUpsideGate` is applied. AFTER a CALL signal is produced and BEFORE risk/execution, apply the sector gate:
- Build the gate once at runner init from config + `self._nubra_client` (the market_data provider) — `SectorTrendGate.from_config(config, market_data)`.
- For a CALL signal: `ok, reason = gate.evaluate(symbol)`; if `not ok`: set `signal["trade"]="HOLD"`, record `skip_reason=reason` (and surface in the per-symbol audit). PUT/HOLD signals are untouched. When the gate is disabled, behavior is identical to today.
- Mirror the existing gate-application style/placement (check how ExpectedUpsideGate / risk results are recorded in the audit dict).

## Part D — Config (`config/nubra_config.json`)
Add (default ENABLED here since the user opted in, but the code defaults OFF when the block is absent):
```json
"sector_filter": {
  "enabled": true,
  "sma_period": 10,
  "sector_index": {
    "INFY":"NIFTYIT","TCS":"NIFTYIT","WIPRO":"NIFTYIT","HCLTECH":"NIFTYIT","TECHM":"NIFTYIT",
    "LTIM":"NIFTYIT","COFORGE":"NIFTYIT","PERSISTENT":"NIFTYIT","MPHASIS":"NIFTYIT","KPITTECH":"NIFTYIT","LTTS":"NIFTYIT",
    "HDFCBANK":"NIFTYBANK","ICICIBANK":"NIFTYBANK","SBIN":"NIFTYBANK","AXISBANK":"NIFTYBANK","KOTAKBANK":"NIFTYBANK",
    "INDUSINDBK":"NIFTYBANK","FEDERALBNK":"NIFTYBANK","BANKINDIA":"NIFTYBANK","AUBANK":"NIFTYBANK","IDFCFIRSTB":"NIFTYBANK"
  }
}
```
(Map can grow; unmapped stocks simply skip the gate.)

## Tests (offline, mock the provider's index_history — no network)
`tests/nubra/test_sector_trend_gate.py` + a FyersDataProvider index test:
- gate disabled → always (True, None).
- unmapped symbol → (True, None).
- index_history returns a DOWNtrend series (last < SMA) → CALL blocked (False, reason mentions sector_downtrend).
- index_history returns an UPtrend (last > SMA) → (True, None).
- index_history returns None / too-few bars → (True, "sector_data_unavailable") (graceful).
- FyersDataProvider.index_history with a MOCKED client → builds `NSE:NIFTYIT-INDEX`, maps candles→{close,timestamp} oldest-first.
- Runner integration: a CALL on an IT name with a bearish-IT mocked provider → trade becomes HOLD with the sector reason; a CALL with bullish sector → unchanged; PUT/HOLD never altered.
- Keep all 415 existing tests green; do not weaken them (BP-123).

## Out of scope
- FII-flow / broad-market regime (separate feature). This is sector-index trend only.
- Changing PUT/HOLD logic. Only CALL is gated.
- Live Fyers calls in tests (mock them).

## Constraints
- Extensibility-first: new sector = config line; new provider index support = override `index_history`. No caller edits.
- Never stage `.env`/`auth_data.db*`/`fyers*.log`.

"""Two-stage cached backtester for the Nubra Nifty50 TimesFM equity signal.

Stage A (expensive, run once): per symbol, fetch daily closes via a MARKET-DATA-ONLY
Nubra client and compute the point-in-time TimesFM forecast at every eligible day. PIT is
sacred — the forecast at day t uses ONLY closes[:t+1], never a future bar. closes plus the
per-day {pred_ret, confidence, direction} are persisted to a disk cache keyed by a hash of
the forecast code, so the cache self-invalidates when the forecasting logic changes.

Stage B (cheap, pure arithmetic over the cache): apply a LeverConfig and compute
train/validation metrics with NO re-forecasting. Every knob is a config flag on LeverConfig,
so a new lever is a new field with a default — the sweep and metric code never change
(Open/Closed). Levers: min_pred_ret, min_confidence, trend_gate (price > N-day MA),
target_pct, stop_pct, trailing_stop, time_exit, horizon_days, symbol_filter.

Train/validation: per symbol, the eligible-day timeline is split older-2/3 = train,
newer-1/3 = validation. A config is meant to be ranked on TRAIN; VALIDATION is reported
untouched so it stays an honest out-of-sample read.

Honest caveats:
  - Nubra historical() returns CLOSE only (no intrabar high/low), so target/stop/trailing
    are close-to-close — intraday touches are missed (understates win AND stop counts).
  - The cached forecast horizon is fixed at FORECAST_HORIZON; the `horizon_days` lever is the
    EXIT WINDOW, not a re-forecast. TimesFM 1.0's point forecast is horizon-invariant anyway,
    so the exit window is the real degree of freedom — and Stage B stays pure arithmetic.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import product
from statistics import mean

_ROOT = pathlib.Path("/Users/jagadeeshpulamarasetti/OwnCode/TradingBotMiroFish/market-swarm-lab")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
logging.basicConfig(level=logging.WARNING)

import services.forecasting.forecasting_service as _fc_module
from services.forecasting.forecasting_service import ENABLE_TIMESFM, TimesFMForecastingService

# --- Stage-A forecast contract (part of the cache key; change => cache rebuild) ---
FORECAST_HORIZON = 5   # points the model predicts; pred_ret = (forecast[-1]/last - 1)
MIN_BARS = 10          # prior closes required before a day is forecastable
FETCH = 120            # daily bars requested per symbol (Nubra caps history ~69)
TRAIN_FRAC = 2 / 3     # older 2/3 of a symbol's eligible days = train, newer 1/3 = val

CACHE_PATH = pathlib.Path(__file__).with_name(".stageA_cache.json")
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"

_OUTCOMES = ("win", "stop", "timeout")


def _universe() -> list[str]:
    cfg = json.loads(_CONFIG_PATH.read_text())
    return cfg.get("whitelist", cfg.get("universes", {}).get("nifty50", []))


def forecast_version() -> str:
    """Hash of the forecast code + contract. Any change invalidates the Stage-A cache."""
    src = inspect.getsource(_fc_module)
    payload = f"{src}|H={FORECAST_HORIZON}|MIN_BARS={MIN_BARS}|TFM={ENABLE_TIMESFM}"
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


# ============================ Stage A — build the cache ============================

def _market_data_client():
    """Market-data-only Nubra client: skips InstrumentData/portfolio construction, which
    eagerly downloads the refdata instrument-master and times out. historical() only needs
    sdk_market; no orders here, so trader/instruments = None."""
    from nubra_python_sdk.marketdata.market_data import MarketData
    from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

    from services.nubra_client.nubra_client import NubraClient

    cfg = json.loads(_CONFIG_PATH.read_text())
    nubra = InitNubraSdk(env=NubraEnv.UAT, env_creds=True)
    return NubraClient(cfg, sdk_trader=None, sdk_market=MarketData(nubra), sdk_instruments=None)


def _pit_forecast(fc: TimesFMForecastingService, sym: str, closes_pit: list[float]) -> dict:
    """Point-in-time forecast from closes[:t+1] only. Uses run_api (no per-call disk writes,
    unlike forecast_from_prices) and computes pred_ret from the final forecast point."""
    result = fc.run_api(sym, {"close": closes_pit}, FORECAST_HORIZON)
    pts = result.get("forecast", [])
    last = closes_pit[-1] if closes_pit else 0.0
    pred_ret = round((pts[-1] - last) / last, 6) if last and pts else 0.0
    return {
        "pred_ret": pred_ret,
        "confidence": round(float(result.get("confidence", 0.5)), 4),
        "direction": result.get("direction", "sideways"),
    }


def _build_symbol(client, fc: TimesFMForecastingService, sym: str) -> tuple[str, dict]:
    try:
        bars = client.historical(sym, "1d", lookback=FETCH)
    except Exception as exc:
        return sym, {"error": f"fetch:{exc}"}
    closes = [float(b["close"]) for b in bars]
    n = len(closes)
    if n < MIN_BARS + 2:
        return sym, {"skipped": "insufficient_history", "bars": n}
    forecasts = {str(t): _pit_forecast(fc, sym, closes[: t + 1]) for t in range(MIN_BARS, n - 1)}
    return sym, {"closes": closes, "forecasts": forecasts}


def build_stage_a(version: str | None = None, symbols: list[str] | None = None) -> dict:
    version = version or forecast_version()
    symbols = symbols or _universe()
    client = _market_data_client()
    fc = TimesFMForecastingService()
    # Warm the model once so worker threads reuse the loaded singleton (no load race).
    try:
        fc.run_api("_WARMUP", {"close": [100.0 + i for i in range(MIN_BARS + 2)]}, FORECAST_HORIZON)
    except Exception:
        pass

    ok: dict[str, dict] = {}
    failed: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(symbols))) as pool:
        futs = {pool.submit(_build_symbol, client, fc, s): s for s in symbols}
        for fu in as_completed(futs):
            sym, data = fu.result()
            if "closes" in data:
                ok[sym] = data
            else:
                failed[sym] = data.get("error") or data.get("skipped", "unknown")

    cache = {
        "meta": {
            "forecast_version": version,
            "forecast_horizon": FORECAST_HORIZON,
            "min_bars": MIN_BARS,
            "symbols_ok": sorted(ok),
            "symbols_failed": failed,
        },
        "symbols": ok,
    }
    CACHE_PATH.write_text(json.dumps(cache))
    return cache


def load_stage_a(force: bool = False, symbols: list[str] | None = None) -> dict:
    """Load the cache if present and the forecast version matches; otherwise (re)build it."""
    version = forecast_version()
    if not force and CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text())
        if cache.get("meta", {}).get("forecast_version") == version:
            return cache
    return build_stage_a(version, symbols)


# ===================== Stage B — pure arithmetic over the cache =====================

@dataclass(frozen=True)
class LeverConfig:
    """Every backtest knob. A new lever = a new field with a default here; the gate/exit
    functions read it and the sweep/metric code is untouched (Open/Closed)."""
    min_pred_ret: float = 0.02
    min_confidence: float = 0.0
    trend_gate: bool = False
    trend_ma_days: int = 20
    target_pct: float = 0.02
    stop_pct: float = 0.02
    trailing_stop: float | None = None
    time_exit: int | None = None
    horizon_days: int = 5
    symbol_filter: tuple[str, ...] | None = None


def _passes_gate(sym: str, closes: list[float], t: int, forecast: dict, cfg: LeverConfig) -> bool:
    if cfg.symbol_filter is not None and sym not in cfg.symbol_filter:
        return False
    if forecast["pred_ret"] < cfg.min_pred_ret:
        return False
    if forecast["confidence"] < cfg.min_confidence:
        return False
    if cfg.trend_gate:
        if t + 1 < cfg.trend_ma_days:  # not enough prior bars for the MA -> fail closed
            return False
        ma = mean(closes[t - cfg.trend_ma_days + 1 : t + 1])  # PIT: closes up to & incl. t
        if closes[t] <= ma:
            return False
    return True


def _simulate_trade(closes: list[float], t: int, cfg: LeverConfig) -> tuple[str, float]:
    """Close-to-close exit scan. Returns (outcome, exit_price). Outcome buckets:
    win = target hit, stop = hard stop OR trailing stop hit, timeout = held to the window."""
    entry = closes[t]
    target = entry * (1 + cfg.target_pct)
    hard_stop = entry * (1 - cfg.stop_pct)
    window = cfg.horizon_days if cfg.time_exit is None else min(cfg.horizon_days, cfg.time_exit)
    peak = entry
    for k in range(1, window + 1):
        close = closes[t + k]
        peak = max(peak, close)
        if close >= target:
            return "win", close
        if close <= hard_stop:
            return "stop", close
        if cfg.trailing_stop is not None and close <= peak * (1 - cfg.trailing_stop):
            return "stop", close
    return "timeout", closes[t + window]


def _metrics(trades: list[tuple[str, float]]) -> dict:
    """trades = list of (outcome, pnl_pct)."""
    n = len(trades)
    if n == 0:
        return {"n_signals": 0, "win_pct": 0.0, "stop_pct": 0.0,
                "timeout_pct": 0.0, "expectancy_pct_per_trade": 0.0}
    counts = {o: sum(1 for outcome, _ in trades if outcome == o) for o in _OUTCOMES}
    return {
        "n_signals": n,
        "win_pct": round(100 * counts["win"] / n, 1),
        "stop_pct": round(100 * counts["stop"] / n, 1),
        "timeout_pct": round(100 * counts["timeout"] / n, 1),
        "expectancy_pct_per_trade": round(mean(pnl for _, pnl in trades), 3),
    }


def run_config(cache: dict, cfg: LeverConfig) -> dict:
    """Apply one LeverConfig to the cached forecasts; return train/val metrics separately."""
    train: list[tuple[str, float]] = []
    val: list[tuple[str, float]] = []
    for sym, data in cache["symbols"].items():
        closes = data["closes"]
        n = len(closes)
        forecasts = data["forecasts"]
        # Eligible entry days for THIS horizon: enough future bars to observe the full hold.
        cand_ts = sorted(int(t) for t in forecasts if int(t) + cfg.horizon_days <= n - 1)
        if not cand_ts:
            continue
        split = int(len(cand_ts) * TRAIN_FRAC)
        train_days = set(cand_ts[:split])
        for t in cand_ts:
            forecast = forecasts[str(t)]
            if not _passes_gate(sym, closes, t, forecast, cfg):
                continue
            outcome, exit_px = _simulate_trade(closes, t, cfg)
            pnl_pct = (exit_px / closes[t] - 1) * 100
            (train if t in train_days else val).append((outcome, pnl_pct))
    return {"train": _metrics(train), "val": _metrics(val)}


def build_grid(
    min_pred_ret: tuple[float, ...] = (0.02, 0.03, 0.04, 0.05),
    min_confidence: tuple[float, ...] = (0.0, 0.6, 0.7, 0.75),
    trend_gate: tuple[bool, ...] = (False, True),
    target_stop: tuple[tuple[float, float], ...] = (
        (0.02, 0.02), (0.02, 0.03), (0.02, 0.04), (0.03, 0.03), (0.03, 0.02),
    ),
    horizon_days: tuple[int, ...] = (3, 5, 10),
    trailing_stop: tuple[float | None, ...] = (None,),
    time_exit: tuple[int | None, ...] = (None,),
    symbol_filter: tuple[tuple[str, ...] | None, ...] = (None,),
):
    """Cartesian product of lever ranges -> LeverConfigs. A new lever = a new kwarg here
    plus its field on LeverConfig; existing callers keep working via defaults."""
    for mpr, mc, tg, (tp, sp), hz, ts, te, sf in product(
        min_pred_ret, min_confidence, trend_gate, target_stop,
        horizon_days, trailing_stop, time_exit, symbol_filter,
    ):
        yield LeverConfig(
            min_pred_ret=mpr, min_confidence=mc, trend_gate=tg,
            target_pct=tp, stop_pct=sp, horizon_days=hz,
            trailing_stop=ts, time_exit=te, symbol_filter=sf,
        )


def sweep(cache: dict, configs) -> list[dict]:
    """Run every config over the cache. Ranked on TRAIN expectancy; val reported untouched."""
    rows = []
    for cfg in configs:
        result = run_config(cache, cfg)
        rows.append({"config": _cfg_label(cfg), "train": result["train"], "val": result["val"]})
    rows.sort(key=lambda r: r["train"]["expectancy_pct_per_trade"], reverse=True)
    return rows


def _cfg_label(cfg: LeverConfig) -> dict:
    label = {
        "min_pred_ret": cfg.min_pred_ret, "min_confidence": cfg.min_confidence,
        "trend_gate": cfg.trend_gate, "target_pct": cfg.target_pct, "stop_pct": cfg.stop_pct,
        "horizon_days": cfg.horizon_days,
    }
    if cfg.trailing_stop is not None:
        label["trailing_stop"] = cfg.trailing_stop
    if cfg.time_exit is not None:
        label["time_exit"] = cfg.time_exit
    if cfg.symbol_filter is not None:
        label["symbol_filter"] = list(cfg.symbol_filter)
    return label


# ================================ self-check (no network) ================================

def _self_check() -> None:
    """Deterministic arithmetic checks over a hand-built cache — no Nubra, no forecasting."""
    closes = [100.0] * 11 + [102.0, 101.0, 98.0, 100.0]  # idx 0..14, n=15
    n = len(closes)
    forecasts = {str(t): {"pred_ret": 0.05, "confidence": 0.9, "direction": "up"}
                 for t in range(MIN_BARS, n - 1)}
    cache = {"meta": {"forecast_horizon": FORECAST_HORIZON},
             "symbols": {"TEST": {"closes": closes, "forecasts": forecasts}}}

    # horizon 3: cand days t with t+3<=14 -> {10,11}; split -> train{10}, val{11}.
    win_stop = run_config(cache, LeverConfig(min_pred_ret=0.02, target_pct=0.02,
                                             stop_pct=0.02, horizon_days=3))
    # t=10 entry100 -> closes[11]=102 hits +2% target => win.
    assert win_stop["train"]["n_signals"] == 1 and win_stop["train"]["win_pct"] == 100.0, win_stop
    # t=11 entry102 -> closes[13]=98 hits -2% stop before target => stop.
    assert win_stop["val"]["n_signals"] == 1 and win_stop["val"]["stop_pct"] == 100.0, win_stop

    # Wide target/stop => nothing triggers => both days time out.
    timeouts = run_config(cache, LeverConfig(min_pred_ret=0.02, target_pct=0.50,
                                             stop_pct=0.50, horizon_days=3))
    assert timeouts["train"]["timeout_pct"] == 100.0, timeouts
    assert timeouts["val"]["timeout_pct"] == 100.0, timeouts

    # trend_gate (3-day MA): t=10 is flat (price==MA) -> reject; t=11 price102 > trailing
    # MA 100.67 -> pass. Confirms the gate rejects flat and admits a genuinely-rising day.
    gated = run_config(cache, LeverConfig(min_pred_ret=0.02, trend_gate=True,
                                          trend_ma_days=3, horizon_days=3))
    assert gated["train"]["n_signals"] == 0, gated          # t=10 flat -> rejected
    assert gated["val"]["n_signals"] == 1, gated            # t=11 rising -> admitted

    # min_confidence lever filters everything out when set above the forecast confidence.
    conf_gated = run_config(cache, LeverConfig(min_pred_ret=0.02, min_confidence=0.99,
                                               horizon_days=3))
    assert conf_gated["train"]["n_signals"] == 0 and conf_gated["val"]["n_signals"] == 0, conf_gated

    # PIT trend-gate leak guard: at t=10 price(99) is BELOW its trailing 3-day MA(99.67) so
    # the gate must reject; a forward-looking MA (closes[10:13]=99,95,94 -> 96) would wrongly
    # admit it. Zero signals here == the MA never peeks at future bars.
    pit_closes = [100.0] * 10 + [99.0, 95.0, 94.0]  # idx 0..12, n=13
    pit_forecasts = {str(t): {"pred_ret": 0.05, "confidence": 0.9, "direction": "up"}
                     for t in range(MIN_BARS, len(pit_closes) - 1)}
    pit_cache = {"meta": {}, "symbols": {"TEST": {"closes": pit_closes, "forecasts": pit_forecasts}}}
    pit = run_config(pit_cache, LeverConfig(min_pred_ret=0.02, trend_gate=True,
                                            trend_ma_days=3, horizon_days=1))
    assert pit["train"]["n_signals"] == 0 and pit["val"]["n_signals"] == 0, pit
    print("self-check OK")


# ===================================== entrypoint =====================================

if __name__ == "__main__":
    _self_check()
    force = "--rebuild" in sys.argv
    cache = load_stage_a(force=force)
    meta = cache["meta"]
    print(f"Stage A: {len(meta['symbols_ok'])} symbols cached "
          f"(v{meta['forecast_version']}), {len(meta['symbols_failed'])} failed")
    if meta["symbols_failed"]:
        print("  failed:", json.dumps(meta["symbols_failed"]))

    rows = sweep(cache, build_grid())
    ranked = [r for r in rows if r["train"]["n_signals"] >= 1]
    print(f"\nStage B: {len(rows)} configs swept; top 5 by TRAIN expectancy "
          f"(validation shown for honesty):")
    for row in ranked[:5]:
        print(json.dumps(row))

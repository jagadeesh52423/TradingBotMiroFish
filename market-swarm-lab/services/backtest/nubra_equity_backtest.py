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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import product
from statistics import mean

_ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../market-swarm-lab
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
MIN_TRAIN_SIGNALS = 30  # a config with fewer train signals is noise, not an edge -> not rankable

CACHE_PATH = pathlib.Path(__file__).with_name(".stageA_cache.json")
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"

_OUTCOMES = ("win", "stop", "timeout")

# Static NIFTY50 -> sector map for the Stage-B sector levers. Only coherent baskets (>=2
# members) are mapped; unmapped symbols simply skip the sector levers (fail-open). Nubra UAT
# has no index feed, so sector/market "indices" are equal-weight baskets of cached constituent
# closes (a breadth proxy). Add a sector: add stock->sector entries here (Open/Closed).
SECTOR_MAP = {
    "INFY": "IT", "TCS": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "HDFCBANK": "Bank", "ICICIBANK": "Bank", "SBIN": "Bank", "AXISBANK": "Bank", "KOTAKBANK": "Bank",
    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance", "HDFCLIFE": "Finance", "SBILIFE": "Finance",
    "SBICARD": "Finance", "LICI": "Finance", "HUDCO": "Finance", "M&MFIN": "Finance",
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "LUPIN": "Pharma",
    "MARUTI": "Auto", "EICHERMOT": "Auto", "HEROMOTOCO": "Auto",
    "TATASTEEL": "Metal", "JSWSTEEL": "Metal",
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "GAIL": "Energy",
    "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power", "ADANIPOWER": "Power", "ADANIGREEN": "Power",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "MARICO": "FMCG", "TATACONSUM": "FMCG",
    "LT": "Infra", "SIEMENS": "Infra", "ADANIPORTS": "Infra",
}
_SECTOR_MEMBERS: dict[str, tuple[str, ...]] = defaultdict(tuple)
for _sym, _sec in SECTOR_MAP.items():
    _SECTOR_MEMBERS[_sec] += (_sym,)
_SECTOR_MEMBERS = dict(_SECTOR_MEMBERS)


def _universe() -> list[str]:
    cfg = json.loads(_CONFIG_PATH.read_text())
    return cfg.get("whitelist", cfg.get("universes", {}).get("nifty50", []))


def forecast_version() -> str:
    """Hash of the forecast code + contract; a change invalidates the Stage-A cache.
    Boundary: hashes THIS module's source + ENABLE_TIMESFM only — changes in imported helpers
    or TimesFM checkpoint weights are not captured; bump FORECAST_HORIZON/MIN_BARS or --rebuild
    if the forecaster's dependencies shift."""
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


def _fetch_closes(client, sym: str) -> tuple[str, list[float] | None, str | None]:
    try:
        bars = client.historical(sym, "1d", lookback=FETCH)
    except Exception as exc:
        return sym, None, f"fetch:{exc}"
    closes = [float(b["close"]) for b in bars]
    if len(closes) < MIN_BARS + 2:
        return sym, None, f"insufficient_history:{len(closes)}"
    return sym, closes, None


def build_stage_a(version: str | None = None, symbols: list[str] | None = None) -> dict:
    version = version or forecast_version()
    symbols = symbols or _universe()
    client = _market_data_client()

    # Phase 1 — fetch closes in parallel (network I/O is thread-safe).
    fetched: dict[str, list[float]] = {}
    failed: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(symbols))) as pool:
        for sym, closes, err in pool.map(lambda s: _fetch_closes(client, s), symbols):
            if closes is None:
                failed[sym] = err or "unknown"
            else:
                fetched[sym] = closes

    # Phase 2 — forecast sequentially over one shared TimesFM singleton. Deliberately NOT
    # threaded: concurrent model inference is not guaranteed thread-safe, and Stage A is a
    # one-time build, so correctness beats parallelism here.
    fc = TimesFMForecastingService()
    ok: dict[str, dict] = {}
    for sym, closes in fetched.items():
        n = len(closes)
        forecasts = {str(t): _pit_forecast(fc, sym, closes[: t + 1]) for t in range(MIN_BARS, n - 1)}
        ok[sym] = {"closes": closes, "forecasts": forecasts}

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
    market_regime_gate: bool = False
    market_ma_days: int = 20
    sector_gate: bool = False
    sector_ma_days: int = 10
    sector_rs: bool = False


def _basket_series(cache: dict, symbols, n_days: int) -> dict[int, float]:
    """Equal-weight n_days return per END-ALIGNED age (age 0 = latest bar): at age a a member
    contributes close[age a] / close[age a+n_days] - 1. Assumes cached series share the latest
    trading day (fetched together) and contiguous daily bars — a backtest breadth proxy."""
    per_age: dict[int, list] = defaultdict(list)
    for sym in symbols:
        data = cache["symbols"].get(sym)
        if not data:
            continue
        closes = data["closes"]
        n = len(closes)
        for age in range(0, n - n_days):
            prev = closes[n - 1 - age - n_days]
            if prev:
                per_age[age].append(closes[n - 1 - age] / prev - 1)
    return {age: mean(vals) for age, vals in per_age.items() if vals}


def _basket_return_at(cache, tag, symbols, n_days, sym, t) -> float | None:
    """Memoized equal-weight basket return at the date of (sym, day t). PIT-safe: age t maps to
    trailing bars only. None when no basket member has n_days+ history at that date."""
    memo = cache.setdefault("_basket_memo", {})
    key = (tag, n_days)
    if key not in memo:
        memo[key] = _basket_series(cache, symbols, n_days)
    age = len(cache["symbols"][sym]["closes"]) - 1 - t
    return memo[key].get(age)


def _symbol_return(closes: list[float], t: int, n_days: int) -> float | None:
    if t - n_days < 0:
        return None
    prev = closes[t - n_days]
    return (closes[t] / prev - 1) if prev else None


def _passes_gate(cache, sym: str, closes: list[float], t: int, forecast: dict, cfg: LeverConfig) -> bool:
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
    if cfg.market_regime_gate:  # admit longs only when the Nifty50 basket is trending up
        basket = _basket_return_at(cache, "market", cache["symbols"].keys(),
                                   cfg.market_ma_days, sym, t)
        if basket is not None and basket <= 0:  # fail-open when unavailable (early history)
            return False
    if cfg.sector_gate or cfg.sector_rs:
        sector = SECTOR_MAP.get(sym)
        if sector is not None:  # unmapped symbol -> skip sector levers (fail-open, per spec)
            members = _SECTOR_MEMBERS.get(sector, ())
            sector_ret = _basket_return_at(cache, sector, members, cfg.sector_ma_days, sym, t)
            if cfg.sector_gate and sector_ret is not None and sector_ret <= 0:
                return False
            if cfg.sector_rs and sector_ret is not None:
                present = sum(1 for m in members if m in cache["symbols"])
                own = _symbol_return(closes, t, cfg.sector_ma_days)
                if present >= 2 and own is not None and own <= sector_ret:  # underperforms sector
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
            if not _passes_gate(cache, sym, closes, t, forecast, cfg):
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
    market_regime_gate: tuple[bool, ...] = (False,),
    market_ma_days: tuple[int, ...] = (20,),
    sector_gate: tuple[bool, ...] = (False,),
    sector_ma_days: tuple[int, ...] = (10,),
    sector_rs: tuple[bool, ...] = (False,),
):
    """Cartesian product of lever ranges -> LeverConfigs. A new lever = a new kwarg here
    plus its field on LeverConfig; existing callers keep working via defaults. The new-lever
    ranges default to a single off-value, so the baseline grid size is unchanged until swept."""
    for (mpr, mc, tg, (tp, sp), hz, ts, te, sf,
         mrg, mmd, sg, smd, srs) in product(
        min_pred_ret, min_confidence, trend_gate, target_stop,
        horizon_days, trailing_stop, time_exit, symbol_filter,
        market_regime_gate, market_ma_days, sector_gate, sector_ma_days, sector_rs,
    ):
        yield LeverConfig(
            min_pred_ret=mpr, min_confidence=mc, trend_gate=tg,
            target_pct=tp, stop_pct=sp, horizon_days=hz,
            trailing_stop=ts, time_exit=te, symbol_filter=sf,
            market_regime_gate=mrg, market_ma_days=mmd,
            sector_gate=sg, sector_ma_days=smd, sector_rs=srs,
        )


def sweep(cache: dict, configs) -> list[dict]:
    """Run every config over the cache. Only configs with >= MIN_TRAIN_SIGNALS train trades are
    rankable (a lucky 1-trade config is noise, not an edge) and sort first by TRAIN expectancy;
    thin configs are kept but ranked below every rankable one. Validation is reported untouched."""
    rows = []
    for cfg in configs:
        result = run_config(cache, cfg)
        rows.append({"config": _cfg_label(cfg), "train": result["train"], "val": result["val"]})
    by_train_expectancy = lambda row: row["train"]["expectancy_pct_per_trade"]
    rankable = sorted((r for r in rows if r["train"]["n_signals"] >= MIN_TRAIN_SIGNALS),
                      key=by_train_expectancy, reverse=True)
    thin = sorted((r for r in rows if r["train"]["n_signals"] < MIN_TRAIN_SIGNALS),
                  key=by_train_expectancy, reverse=True)
    return rankable + thin


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
    if cfg.market_regime_gate:
        label["market_regime_gate"] = True
        label["market_ma_days"] = cfg.market_ma_days
    if cfg.sector_gate:
        label["sector_gate"] = True
        label["sector_ma_days"] = cfg.sector_ma_days
    if cfg.sector_rs:
        label["sector_rs"] = True
        label["sector_ma_days"] = cfg.sector_ma_days
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

    # Market-regime gate PIT guard: a 1-symbol basket dips into the entry days then recovers. At
    # t=10,11 the trailing 3-day basket return is NEGATIVE (block); a forward-looking basket
    # would be positive and wrongly admit. Zero signals == the basket never peeks ahead.
    dip = [100.0] * 10 + [98.0, 96.0, 98.0, 100.0, 102.0]  # idx 0..14
    dip_fc = {str(t): {"pred_ret": 0.05, "confidence": 0.9, "direction": "up"}
              for t in range(MIN_BARS, len(dip) - 1)}
    dip_cache = {"meta": {}, "symbols": {"MKT": {"closes": dip, "forecasts": dip_fc}}}
    ungated = run_config(dip_cache, LeverConfig(min_pred_ret=0.02, horizon_days=3))
    assert ungated["train"]["n_signals"] + ungated["val"]["n_signals"] == 2, ungated
    regime = run_config(dip_cache, LeverConfig(min_pred_ret=0.02, horizon_days=3,
                                               market_regime_gate=True, market_ma_days=3))
    assert regime["train"]["n_signals"] + regime["val"]["n_signals"] == 0, regime

    # Sector levers: two IT names both decline into the entry days; INFY declines LESS than TCS.
    infy = [100.0] * 10 + [99.0, 98.0, 99.0, 100.0, 101.0]
    tcs = [100.0] * 10 + [96.0, 94.0, 96.0, 98.0, 100.0]
    _mk = lambda closes: {str(t): {"pred_ret": 0.05, "confidence": 0.9, "direction": "up"}
                          for t in range(MIN_BARS, len(closes) - 1)}
    sec_cache = {"meta": {}, "symbols": {"INFY": {"closes": infy, "forecasts": _mk(infy)},
                                         "TCS": {"closes": tcs, "forecasts": _mk(tcs)}}}
    # sector_gate: the IT basket is trending down -> INFY blocked.
    sec_g = run_config(sec_cache, LeverConfig(min_pred_ret=0.02, horizon_days=3, sector_gate=True,
                                              sector_ma_days=3, symbol_filter=("INFY",)))
    assert sec_g["train"]["n_signals"] + sec_g["val"]["n_signals"] == 0, sec_g
    # sector_rs: INFY's own decline is milder than the IT basket -> it outperforms -> admitted.
    sec_rs = run_config(sec_cache, LeverConfig(min_pred_ret=0.02, horizon_days=3, sector_rs=True,
                                               sector_ma_days=3, symbol_filter=("INFY",)))
    assert sec_rs["train"]["n_signals"] + sec_rs["val"]["n_signals"] >= 1, sec_rs
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
    rankable = sum(1 for r in rows if r["train"]["n_signals"] >= MIN_TRAIN_SIGNALS)
    print(f"\nStage B: {len(rows)} configs swept; {rankable} rankable "
          f"(>= {MIN_TRAIN_SIGNALS} train signals). Top 5 by TRAIN expectancy "
          f"(train n_signals shown; validation for honesty):")
    for row in rows[:5]:
        print(json.dumps(row))
    if rankable == 0:
        print(f"WARNING: no config reached the {MIN_TRAIN_SIGNALS}-train-signal floor — "
              f"reported numbers are noise, not a tradeable edge.")

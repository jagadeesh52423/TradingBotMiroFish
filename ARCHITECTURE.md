# TradingBotMiroFish — Architecture
> Multi-agent market-intelligence system: collects live market data, runs a swarm of AI agents, detects cross-signal divergence, and emits trade signals — for US options (SPY/NVDA + watchlists) and Indian cash equities (Nubra UAT, Nifty/Midcap).

## Overview

TradingBotMiroFish ingests data from many sources (prices, Reddit, news, SEC/NSE filings, prediction markets, options flow, order-flow/footprint), forecasts price direction (TimesFM with a deterministic local fallback), runs a 100-agent simulation across four archetypes, measures where the signals agree or diverge, and produces a structured **BUY / SELL / HOLD** signal with confidence, sizing, and a full source audit.

It is **local-first**: every external dependency (API keys, the TimesFM model, the remote MiroFish swarm, the broker) has a graceful fallback, so a run never crashes on a missing credential — it degrades to fixtures or a formula and says so explicitly in the output.

The repo carries two layers:
- **`market-swarm-lab/`** — the actual coherent system (the only thing you should treat as "the codebase").
- **Repo root** — a large body of research scratch: phase backtests, calibration scripts, audit reports (`*.md`, `*.txt`), screenshots, and ad-hoc replay tools. These are exploratory artifacts, not part of the running system, and are not described in detail here.

## Repository Layout

```
TradingBotMiroFish/
├── market-swarm-lab/            # THE SYSTEM (see below)
├── services/                    # root-level scratch copies (live_trading, orderflow)
├── reports/, exports/,          # research output artifacts
│   analysis_output/
├── *.py                         # phase1/phase2 backtests, calibration, replay, audits
├── *.md / *.txt                 # research findings, audit verdicts, status logs
└── README.md                    # points at market-swarm-lab
```

### market-swarm-lab structure

```
market-swarm-lab/
├── apps/api/                    # FastAPI orchestrator (the batch pipeline entry point)
│   ├── main.py                  # routes: /run-demo, /debug/*, /health
│   ├── workflow.py              # collect → normalize → forecast → simulate → report
│   ├── bootstrap.py             # sys.path wiring so services import flat
│   └── db.py                    # PostgreSQL + Redis persistence/caching (optional)
├── services/                    # ~28 single-responsibility service modules (see catalog)
├── scripts/                     # runnable entry points (live alerts, nubra, replay, backtests)
├── config/                      # JSON config (nubra, live_trading, thresholds, sympathy)
├── infra/fixtures/              # offline fallback data per source
├── data/, state/                # runtime artifacts (gitignored: ohlcv parquet, seeds, reports)
├── external/mirofish/           # optional remote MiroFish swarm bridge target
├── docs/                        # ARCHITECTURE/TECHNICAL_DESIGN + design specs (superpowers/)
├── docker-compose.yml           # postgres, redis, api + worker services
└── pyproject.toml               # Python 3.11–3.12; deps incl. nubra-sdk (TestPyPI)
```

## Technology Stack

- **Language**: Python 3.11–3.12 (use `python3.11` — it has the deps)
- **API framework**: FastAPI + Uvicorn
- **Data**: pandas + pyarrow (Parquet OHLCV store), pydantic models
- **Forecasting**: TimesFM 2.5 (200M PyTorch model, optional) → deterministic trend fallback
- **Persistence (optional)**: PostgreSQL (`psycopg`) for run summaries, Redis for report cache
- **Concurrency/locking**: `filelock` for cross-process state, idempotency guards for orders
- **Brokers / market data**: Nubra SDK (Indian UAT), Fyers (data), Schwab (US auth), Unusual Whales (flow), Alpha Vantage / NewsAPI / Apify / Kalshi / SEC / NSE
- **Packaging/run**: Docker Compose (services) + Makefile; macOS `launchd` for scheduled live alerts
- **Notifications**: `openclaw notify` → WhatsApp

## Subsystems

The system is three loosely-coupled products sharing the same service library:

### 1. Batch agent-simulation pipeline (`apps/api`)
The original "swarm lab" — a synchronous workflow exposed over HTTP. One call collects all sources for a ticker, forecasts, simulates 100 agents, and returns a full report. Used for SPY/NVDA research and as the signal core for the Nubra bot.

### 2. Live alert / order-flow subsystems (`scripts/`, `services/live_trading`, `services/orderflow`)
Real-time intraday scanners that poll quotes every few minutes, run an ensemble of technical agents and order-flow/footprint detectors, and fire deduplicated alerts (terminal + WhatsApp). Includes the MiroFish ensemble (`mirofish_alerts.py`) and order-flow alert engines (`run_live_orderflow_alerts_v*.py`).

### 3. Nubra UAT equity bot (`services/nubra_client`, `scripts/run_nubra_equity.py`)
Runs the agent pipeline against Indian NSE cash equities via the Nubra broker (UAT). Per symbol: Nubra/Fyers OHLCV + live NSE corporate filings → forecast → agent simulation → BUY/HOLD gated by a configurable minimum-upside rule. Long-only CNC, paper or live, fully config-driven.

## Architecture Diagram

```
┌──────────────────────────── DATA SOURCES ─────────────────────────────┐
│ Alpha Vantage  Apify/Reddit  NewsAPI  SEC/EDGAR  Kalshi  NSE filings   │
│ Unusual Whales  Fyers  Schwab  Nubra  FRED/VIX/Stocktwits  Bookmap     │
└───────┬───────────────────────────────────────────────────────────────┘
        │  (each source: live → alternate → fixture fallback)
        ▼
┌────────────────────── COLLECTORS (services/*-collector) ──────────────┐
│ price · news · reddit · uw · schwab · macro · nse_announcements · …    │
└───────┬───────────────────────────────────────────────────────────────┘
        ▼
┌─────────── normalizer ───────────►  normalized_bundle  ───────────────┐
│                                          │                             │
│   ┌──────────────┐   ┌─────────────────┐ │  ┌──────────────────────┐  │
│   │ forecasting  │   │ seed-builder /  │ │  │ orderflow (footprint, │  │
│   │ (TimesFM /   │──►│ divergence-     │◄┘  │ absorption, imbalance)│  │
│   │  fallback)   │   │ engine          │    └──────────────────────┘  │
│   └──────────────┘   └────────┬────────┘                              │
│                               ▼                                        │
│            ┌──────────────────────────────────────┐                   │
│            │ agent-seeder / mirofish-bridge        │                   │
│            │ 100 agents: retail · institutional ·  │                   │
│            │ momentum · contrarian (MASI)          │                   │
│            └───────────────────┬──────────────────┘                   │
│                                ▼                                        │
│   strategy-engine (ensemble) → risk-engine → portfolio-engine          │
│                                ▼                                        │
│                         reporting (JSON + Markdown)                     │
└───────┬────────────────────────┬──────────────────────────────────────┘
        ▼                        ▼
  ┌───────────────┐      ┌──────────────────────────────────────┐
  │ HTTP response │      │ execution-engine → broker (Nubra/     │
  │ /run-demo     │      │ paper) ; alerts → WhatsApp/terminal   │
  └───────────────┘      └──────────────────────────────────────┘
```

## Service Catalog

Services live under `market-swarm-lab/services/` — each is a flat-importable module with a single responsibility.

### Collectors (ingest, with fallback chains)
| Service | Source(s) | Notes |
|---|---|---|
| `price-collector` | Alpha Vantage OHLCV | RSI-14, vol, momentum, VWAP → Parquet |
| `reddit-collector` | Apify → Reddit OAuth → fixture | qualitative narratives + quantitative sentiment features |
| `news-collector` | NewsAPI → AV news → fixture | narrative_strength, breaking_news |
| `collector` | SEC, Kalshi, Polymarket, OHLCV, news | multi-source fetchers (`fetchers/*.py`) |
| `uw-collector` | Unusual Whales | options flow / sweeps gate |
| `schwab-collector` | Schwab | US market data / auth |
| `macro-collector` | FRED, VIX, Stocktwits, Reddit-SPY | macro/regime context |
| `nse_announcements` | NSE corporate filings | live filing text + sentiment (Indian equities) |

### Intelligence core
| Service | Role |
|---|---|
| `normalizer` | merges raw sources into a single `normalized_bundle` (sim seed + numeric feature window) |
| `forecasting` | TimesFM 2.5 forecast → direction/confidence; deterministic fallback when model absent |
| `seed-builder` | `build_seed_pack()` unified narrative + `divergence_engine` (TimesFM vs Reddit vs Kalshi) |
| `agent-seeder` | seeds & runs 100 archetype agents; `masi_agent`/`masi_confirmer` (MASI strategy agents) |
| `mirofish-bridge` | optional bridge to the remote MiroFish 100-agent LLM swarm; local formula sim fallback |
| `strategy-engine` | `ensemble_scorer` (4-agent majority vote), `signal_scorer`, `masi_strategies` |
| `llm_context` | builds LLM prompt context from the bundle |

### Order-flow & live trading
| Service | Role |
|---|---|
| `orderflow` | footprint builder/analytics, absorption/imbalance detectors, entry-exit planner, outcome tracker |
| `live_trading` | alert engine (v2), bar history, dedupe, formatter, debug endpoint |
| `earnings_sympathy` | pre-earnings sympathy scorer, IV dislocation, OI/volume, LLM analyst |

### Execution, risk & brokers
| Service | Role |
|---|---|
| `execution-engine` | turns approved signals into broker orders |
| `risk-engine` | position/exposure risk checks |
| `portfolio-engine` | portfolio-level state and sizing |
| `nubra_client` | Indian-equity bot: broker + market-data + universe registries, signal→order, paper trader, position sync, idempotency |
| `fyers_client` | Fyers market-data provider (registered as a `MarketDataProvider`) |

### Output & evaluation
| Service | Role |
|---|---|
| `reporting` | JSON + Markdown reports; `unified_reporter` |
| `backtester` / `backtest` | strategy backtest harnesses |

## Data Flow

### Batch pipeline (`/run-demo?ticker=SPY`)
```
collector.collect(ticker)                      # all sources, each with fallback
  → normalizer.normalize(raw_bundle)           # → normalized_bundle
  → forecasting.forecast(normalized_bundle)    # TimesFM or fallback
  → mirofish_bridge.run(bundle, forecast)      # 100-agent simulation
  → reporting.generate(...)                    # JSON + Markdown
  → {source_audit, seed_pack, divergence, simulation, trade_signal, report}
  → (optional) cache_report (Redis) + persist_run_summary (Postgres)
```
`provider_modes` / `source_audit` are always returned: every source reports `live` vs `fallback` — **no silent fallbacks**.

### Live ensemble alerts (`mirofish_alerts.py`)
```
poll quotes (every 5 min, per watchlist)
  → 4 agents vote: VWAP+Futures · EMA+RSI · Trendline+Levels · Volume+Momentum
  → fire only if 3/4 agree (4/4 outside high-vol windows)
  → time-of-day gates (no entry <10:00 / >15:00 ET), ATR targets, UW flow gate, 60-min cooldown
  → dedupe → format → openclaw notify (WhatsApp) + terminal
```

### Nubra equity bot (`scripts/run_nubra_equity.py --once --dry-run`)
```
universe_registry.get(config.universe)         # nifty50 / midcap150 / custom
  for each symbol:
    market_data_registry.get_provider(config.data_provider)  # nubra | fyers
      → OHLCV  +  nse_announcements (live filing sentiment)
      → forecasting → agent simulation → blended signal (TimesFM/sim/news weights)
      → entry_gate: enter only if modeled upside ≥ min_expected_upside_pct
      → signal_to_equity_order → broker_registry.get(mode)  # nubra | paper
      → idempotency + order_state_tracker + position_sync
```

## Key Extension Points

`nubra_client` is the most deliberately extensible area — three self-registering registries mean a new broker, data source, or universe is a pure addition (no edits to callers, Open/Closed):

| Registry | Add a variant by… | Contract |
|---|---|---|
| `market_data_registry` | new class implementing `MarketDataProvider` + `@register_provider("name")`, one import in `_ensure_providers_loaded()` | resolved via `get_provider(name)` |
| `broker_registry` | `registry.register(mode, factory)` where factory returns a `BrokerClient` | resolved via `get(mode)` |
| `universe_registry` | `register_universe(name, symbols)` or a `universes` entry in `nubra_config.json` | resolved via `get_universe(name)` |
| `signal_strategies` | new strategy class self-registered (same pattern) | selected by name from config |

`registry_bootstrap.py` performs the one-time import that fires all `@register_*` decorators before resolution.

## Configuration

JSON config under `market-swarm-lab/config/` (change behavior without touching code):
- **`nubra_config.json`** — `env`, `data_provider`, `universe`, `whitelist`, named `universes`, `entry_threshold.min_expected_upside_pct` (+ `per_symbol`), `signal.confidence_weights`, `max_trades_per_day`.
- **`live_trading_config.json`**, **`backtest_thresholds.json`**, **`sympathy_map.json`**, **`sympathy_strategy_config.json`**, **`earnings_calendar.json`**.

Secrets via `market-swarm-lab/.env` (gitignored): `ALPHAVANTAGE_API_KEY`, `NEWSAPI_API_KEY`, `APIFY_API_TOKEN` (US pipeline); `PHONE_NO` + `MPIN` + `NUBRA_ENV` (Nubra); `ENABLE_TIMESFM`, `MIROFISH_BASE_URL`, `POSTGRES_DSN`, `REDIS_URL` (optional upgrades). Nubra session is cached in `auth_data.db` (~7-day expiry, re-login via `scripts/nubra_login.py`).

## Reliability Rules (invariants)

- Missing API keys / TimesFM / remote MiroFish / broker funds must **never** crash a run — degrade and report it.
- Fixture mode is always available for NVDA and SPY (`infra/fixtures/`).
- Every run surfaces an explicit `source_audit` (`live` vs `fallback`).
- Live order placement requires UAT margin; with ₹0 balance BUYs are safely blocked (dry-run is read-only).
- Order placement is idempotent (`idempotency.py` + `order_state_tracker.py`).

## Design Patterns

1. **Strategy + Registry** — brokers, market-data providers, universes, and signal strategies are self-registering and resolved by name; new variants are additive (Open/Closed).
2. **Pipeline / Pipes-and-Filters** — `collect → normalize → forecast → simulate → report`, each stage a pure-ish transform over the bundle.
3. **Adapter** — `nubra_feed_adapter`, `fyers_data_provider` wrap broker SDKs behind `MarketDataProvider`; `mirofish-bridge` adapts the remote swarm.
4. **Fallback chain (graceful degradation)** — every source/model has live → alternate → fixture/formula tiers.
5. **Ensemble voting** — 4 independent technical agents; signal fires only on majority (3/4, or 4/4 off-peak).
6. **Agent isolation** — each archetype receives only data relevant to it (retail≠SEC, contrarian=divergence scores only).
7. **Config over code** — universes, thresholds, weights, watchlists, and provider selection all live in JSON.

## Notes & Caveats

- The repo root is research scratch; the system of record is `market-swarm-lab/`.
- Two older architecture docs exist (`market-swarm-lab/docs/ARCHITECTURE.md` — thin; `docs/TECHNICAL_DESIGN.md` — deep on the batch pipeline). This file is the high-level map across all three subsystems.
- TimesFM and the remote MiroFish swarm are **off by default** (local fallbacks run); flip them on via `.env`.

---

<!-- GENERATION METADATA
generated_at: 2026-06-22
root: TradingBotMiroFish (system: market-swarm-lab)
-->

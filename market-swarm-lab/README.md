# market-swarm-lab

> A local-first multi-agent market intelligence system. Collects live data from five sources, runs a swarm of 100 AI agents across four archetypes, detects signal divergence, and generates a structured trade report with a final BUY/SELL/HOLD signal.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

---

## What It Does

1. **Collects** live OHLCV prices, Reddit sentiment, financial news, SEC filings, and prediction market odds
2. **Forecasts** with TimesFM 2.5 (or a deterministic local fallback) using 60–100 days of real price data
3. **Detects divergence** across TimesFM vs Reddit vs Kalshi signals
4. **Seeds 100 agents** — retail, institutional, momentum, contrarian — each with source-specific context
5. **Simulates** a market vote and generates a trade signal
6. **Reports** structured JSON + Markdown output with full source audit

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full technical deep-dive.

### Quick Overview

```
Alpha Vantage ──► price-collector  ─────────────────────────────┐
Apify/Reddit  ──► reddit-collector ─────────────────────────────►  normalized_bundle
NewsAPI       ──► news-collector   ─────────────────────────────►       │
SEC/EDGAR     ──► collector        ─────────────────────────────►       │
Kalshi        ──► collector        ─────────────────────────────┘       │
                                                                         ▼
                                               TimesFM forecast ──► Divergence Engine
                                                                         │
                                                                    Seed Builder
                                                                    (seed_pack)
                                                                         │
                                                              100 Agents (retail/inst/
                                                              momentum/contrarian)
                                                                         │
                                                              Simulation + Report
                                                           (BUY / SELL / HOLD signal)
```

### Agent Archetypes

| Archetype | Count | Data Sources |
|---|---|---|
| Retail | 40 | Reddit sentiment + News |
| Institutional | 30 | SEC filings + TimesFM + Kalshi |
| Momentum | 20 | OHLCV (RSI, vol, VWAP) + TimesFM |
| Contrarian | 10 | Divergence scores (TimesFM vs Reddit vs Kalshi) |

---

## Project Structure

```
market-swarm-lab/
├── apps/
│   └── api/                        # FastAPI app — orchestration + endpoints
│       ├── main.py                 # Routes: /run-demo, /debug/*, /health
│       ├── workflow.py             # Full pipeline workflow
│       └── db.py                  # PostgreSQL + Redis helpers
│
├── services/
│   ├── price-collector/            # Alpha Vantage OHLCV + technical indicators
│   │   ├── alpha_vantage_client.py # Low-level AV REST client
│   │   ├── price_service.py        # RSI-14, vol, momentum, VWAP, Parquet output
│   │   └── price_collector_service.py
│   │
│   ├── reddit-collector/           # Apify → OAuth → fixture priority chain
│   │   ├── apify_reddit_fetcher.py # Runs trudax/reddit-scraper via Apify API
│   │   ├── apify_normalizer.py     # Normalizes Apify output
│   │   ├── reddit_collector_service.py
│   │   └── nlp.py                  # Sentiment scoring + feature extraction
│   │
│   ├── news-collector/             # NewsAPI → AV news → fixture
│   │   ├── newsapi_client.py       # Low-level NewsAPI client
│   │   ├── news_service.py         # Full pipeline with narrative_strength, breaking_news
│   │   └── news_collector_service.py
│   │
│   ├── collector/                  # Multi-source collector (SEC, Kalshi, Polymarket)
│   │   └── fetchers/               # ohlcv.py, news.py, sec.py, kalshi.py, polymarket.py
│   │
│   ├── normalizer/                 # Unified normalization into normalized_bundle
│   ├── forecasting/                # TimesFM 2.5 + local fallback
│   │   └── forecasting_service.py  # forecast_from_prices() + direction/confidence
│   │
│   ├── seed-builder/               # Simulation seed construction
│   │   ├── seed_builder_service.py # build_seed_pack() unified narrative
│   │   └── divergence_engine.py    # Cross-signal divergence detection
│   │
│   ├── agent-seeder/               # 100-agent seeding + simulation
│   │   ├── agent_seeder_service.py
│   │   └── prompt_generator.py
│   │
│   ├── reporting/                  # JSON + Markdown report generation
│   └── mirofish-bridge/            # Optional MiroFish simulation bridge
│
├── infra/
│   └── fixtures/                   # Offline fallback data
│       ├── market_data/
│       ├── reddit/
│       ├── news/
│       ├── sec/
│       └── prediction_markets/
│
├── state/                          # Runtime artifacts (gitignored)
│   ├── raw/                        # Raw API responses
│   ├── seeds/                      # Simulation seeds
│   ├── cache/
│   └── reports/                    # Final JSON + Markdown reports
│
├── data/                           # Normalized data store (gitignored)
│   └── market_data/
│       ├── ohlcv/                  # Parquet files
│       └── news/                   # Normalized JSON
│
├── docs/
│   └── ARCHITECTURE.md             # Full technical architecture
│
├── pyproject.toml
├── .env.example
└── docker-compose.yml
```

---

## Setup

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for containerized run)

### Local Dev

```bash
# 1. Clone
git clone https://github.com/lakshmanb4u/TradingBotMiroFish.git
cd TradingBotMiroFish

# 2. Copy env and fill in API keys
cp .env.example .env
# Edit .env — minimum required: ALPHAVANTAGE_API_KEY, NEWSAPI_API_KEY, APIFY_API_TOKEN

# 3. Create virtualenv and install deps
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]" 2>/dev/null || pip install -r requirements.txt 2>/dev/null || \
  pip install fastapi uvicorn httpx pandas pyarrow python-dotenv pydantic

# 4. Run the API
uvicorn apps.api.main:app --reload --port 8000
```

### Docker

```bash
make setup   # creates .env from .env.example + builds containers
make run     # starts all services
make demo    # runs demo for NVDA + SPY
```

---

## Required Environment Variables

| Variable | Description | Required |
|---|---|---|
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage — OHLCV + news | ✅ |
| `NEWSAPI_API_KEY` | NewsAPI — financial headlines | ✅ |
| `APIFY_API_TOKEN` | Apify — Reddit scraping via `trudax/reddit-scraper` | ✅ recommended |
| `APIFY_REDDIT_ACTOR` | Actor ID (default: `trudax/reddit-scraper`) | optional |
| `SEC_API_KEY` | SEC API — EDGAR filings | optional |
| `REDDIT_CLIENT_ID` | Reddit OAuth — fallback if no Apify | optional |
| `REDDIT_CLIENT_SECRET` | Reddit OAuth secret | optional |
| `ENABLE_TIMESFM` | `true` to load TimesFM 2.5 200M model | optional |
| `POSTGRES_DSN` | PostgreSQL for run report persistence | optional |
| `REDIS_URL` | Redis for report caching | optional |
| `MIROFISH_BASE_URL` | MiroFish simulation engine URL | optional |

See `.env.example` for all defaults.

---

## API Usage

### Run Full Pipeline

```bash
curl "http://localhost:8000/run-demo?ticker=SPY"
curl "http://localhost:8000/run-demo?ticker=NVDA"
```

**Response includes:**
- `source_audit` — all 5 sources (status/provider/record_count)
- `seed_pack` — unified price + TimesFM + news + Reddit + Kalshi summaries
- `divergence` — divergence_score, alignment_score, signal
- `simulation` — agent vote breakdown + final_direction
- `trade_signal` — BUY/SELL/HOLD with confidence
- `report` — full Markdown + JSON report

### Debug Endpoints

```bash
# OHLCV: RSI, volatility, momentum, VWAP, price trend
curl "http://localhost:8000/debug/price?ticker=SPY"

# News: headlines, sentiment, bullish/bearish themes
curl "http://localhost:8000/debug/news?ticker=SPY"

# Reddit: posts, comments, features (bullish_ratio, disagreement_index)
curl "http://localhost:8000/debug/reddit?ticker=SPY"

# TimesFM: forecast, direction, confidence, trend_strength
curl "http://localhost:8000/debug/timesfm?ticker=SPY"
```

### Example: source_audit Response

```json
{
  "source_audit": {
    "ohlcv":   {"status": "live",     "provider": "alphavantage", "record_count": 100},
    "reddit":  {"status": "live",     "provider": "apify",        "record_count": 60,  "sample_post_titles": ["..."]},
    "news":    {"status": "live",     "provider": "newsapi",      "record_count": 20,  "sample_headlines": ["..."]},
    "kalshi":  {"status": "live",     "provider": "kalshi",       "record_count": 3},
    "sec":     {"status": "fallback", "provider": "sec_api",      "record_count": 0}
  }
}
```

### Example: divergence Response

```json
{
  "divergence": {
    "timesfm_score": 1.0,
    "reddit_score": 0.28,
    "kalshi_score": 0.6,
    "timesfm_vs_reddit": 0.36,
    "timesfm_vs_kalshi": 0.20,
    "reddit_vs_kalshi": 0.16,
    "divergence_score": 0.24,
    "alignment_score": 0.76,
    "signal": "trend_confirmation"
  }
}
```

---

## Live Dashboard (Nubra equity)

Watch the Nubra scanner in real time — auto-refreshes every 15 s.

### Prerequisites

Login once to cache your Nubra session (~7-day expiry):

```bash
python3.11 scripts/nubra_login.py
```

### Start

```bash
./start_nubra_dashboard.sh
# then open: http://localhost:8000/nubra/dashboard
```

Or manually:

```bash
NUBRA_LIVE=1 NUBRA_LIVE_INTERVAL=900 \
  python3.11 -m uvicorn apps.api.main:app --port 8000
```

### JSON endpoint

```bash
curl http://localhost:8000/nubra/live | jq .
```

Returns `status`, `rows` (symbol / action / upside_pct / confidence / ltp / modes), `source_health`, `last_scan`, and `next_scan`.

The scanner always runs `dry_run=True` — read-only, no orders placed.

A **pinned top strip** above the equity table shows NIFTY and BANKNIFTY index futures (nearest-expiry contract, live LTP, and a modelled 5-day move %) whenever a Nubra session is active.

---

## Key Design Decisions

### Fallback Priority

Every data source has a graceful degradation chain — the pipeline never crashes on missing API keys:

```
Alpha Vantage live → fixture_fallback
Apify live → Reddit OAuth live → fixture_fallback
NewsAPI live → Alpha Vantage news live → fixture_fallback
TimesFM 2.5 → local deterministic fallback
```

### No Silent Fallbacks

`source_audit` is always included in `/run-demo` responses. Every source explicitly reports its status (`live` or `fallback`) so you know exactly what data powered each run.

### Agent Isolation

Each of the 100 agents only receives data relevant to its archetype. Retail agents don't see SEC filings; contrarian agents don't get raw price series — they get divergence scores.

---

## TimesFM Notes

TimesFM 2.5 (200M parameter PyTorch model) is **optional** and disabled by default.

To enable:
```bash
ENABLE_TIMESFM=true pip install timesfm torch
```

Without it, the forecasting service uses a deterministic trend extrapolation fallback that produces the same output schema.

---

## Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit: `git commit -m "feat: description"`
4. Push and open a PR

**Never commit `.env` or any file under `state/` or `data/`.**

---

## MiroFish Live Alert System

In addition to the batch simulation pipeline above, this repo includes a real-time intraday alert system built on top of the ensemble scorer.

### Files

| File | Purpose |
|---|---|
| `mirofish_live.py` | Single-ticker live poller (original) |
| `mirofish_alerts.py` | **Multi-ticker alert scanner** (30 symbols, WhatsApp delivery) |
| `mirofish_signal.py` | One-shot signal CLI for any ticker |
| `services/strategy-engine/ensemble_scorer.py` | 4-agent ensemble voting engine |

### How the Ensemble Works

4 independent agents vote on each ticker every 5 minutes:

| Agent | Signal | Backtested Accuracy |
|---|---|---|
| VWAP + Futures | /ES and /NQ alignment vs VWAP | 49.4% |
| EMA + RSI | 9/21 EMA cross + RSI overbought/oversold | 56.3% |
| Trendline + Levels | Morning high/low breakouts | 53.1% |
| Volume + Momentum | Volume-confirmed price momentum | 57.1% |
| **Ensemble (3/4 agree)** | **Majority vote** | **59.6% (+9.6% edge)** |

Signal fires only when 3/4 agents agree. Outside high-vol windows (9:30–11:30 and 14:00–16:00 ET), requires 4/4.

### Post-Mortem Fixes (Applied 2026-04-26)

Based on Friday Apr 25 session analysis (SPY/ARM, 11 signals, 0 T1 hits):

1. **Opening range filter** — no entries before 10:00 ET (avoids morning flush stops)
2. **EOD block** — no new entries after 15:00 ET (prevents late-day stops with no time to reach T1)
3. **Intraday ATR targets** — T1/T2 scaled to actual bar range, not annualised vol (T1 was $8 away on a $5 range day)
4. **UW flow gate** — BUY suppressed when UW flow = BEARISH + net put sweeps detected
5. **60-min signal cooldown** — was 15 min, caused 11 duplicate signals on same thesis

### Watchlists (`mirofish_alerts.py`)

```
--watchlist mega     AAPL MSFT GOOGL META AMZN NVDA TSLA
--watchlist semis    NVDA AMD QCOM ARM AVGO INTC ASML AMAT KLAC LRCX
--watchlist ai       NVDA META MSFT GOOGL AMZN CLS CDNS SNPS FN ANET VRT SMCI ARM PLTR
--watchlist options  SPY QQQ NVDA TSLA META AAPL MSFT GOOGL AMD ARM
--watchlist all      All 30 tickers (default)
```

### Running Manually

```bash
# Full 30-ticker scan, WhatsApp alerts via openclaw notify
python3 mirofish_alerts.py

# Mag 7 only
python3 mirofish_alerts.py --watchlist mega

# Custom tickers
python3 mirofish_alerts.py NVDA CLS CDNS META

# Terminal only (no WhatsApp)
python3 mirofish_alerts.py --no-notify

# One-shot signal for any ticker
python3 mirofish_signal.py NVDA ARM
```

### Auto-Start on macOS (launchd)

A launchd plist is configured at:
```
~/Library/LaunchAgents/com.mirofish.alerts.plist
```

This automatically starts `mirofish_alerts.py --watchlist all` every **Monday–Friday at 6:25 AM PT (9:25 AM ET)**, 5 minutes before market open. Restarts on crash. Exits cleanly at market close.

```bash
# Manual controls
launchctl start com.mirofish.alerts    # start now
launchctl stop com.mirofish.alerts     # stop now
launchctl unload ~/Library/LaunchAgents/com.mirofish.alerts.plist  # disable

# Live logs
tail -f ~/Library/Logs/mirofish_alerts.log
tail -f ~/Library/Logs/mirofish_alerts_error.log
```

### WhatsApp Alert Format

When a signal fires, a compact message is sent via `openclaw notify`:

```
🐟 MiroFish Signal [10:41 ET]
▲ NVDA $890.24 — BUY (87%) [HIGH-VOL]
Bulls: 3/4  Bears: 1/4  UW: BULLISH
Entry: $890.24  Stop: $883.10  R:R 1:1.87
T1 (70%): $900.90  T2 (30%): $911.56
⚡ Large call sweep $1.2M premium
```

---

## Nubra UAT Equity Bot (Nifty 50)

Runs the MiroFish agent pipeline against **Nubra (Indian broker) UAT** for **48 NSE cash equities** (Nifty-50 names available in UAT). Per symbol it pulls Nubra OHLCV + live **NSE corporate filings**, forecasts (TimesFM), runs the agent simulation, and produces a BUY/HOLD recommendation gated by a configurable minimum-upside rule. Long-only (CNC). Order execution is wired but requires UAT margin (provisioned by Nubra — there is no add-funds API).

> Use **`python3.11`** — the test/runtime interpreter that has the deps. The default `python`/`python3` may be 2.7 / a venv without them.

---

### ⭐ Recommended default: the India Catalyst Swing **playbook screener** (no Nubra needed)

By default the pipeline now applies the **India Catalyst Swing Playbook** ([`docs/india_swing_playbook.md`](docs/india_swing_playbook.md)) — a set of India-specific entry gates and conviction flags — and you can run it **read-only with just a Fyers token, no Nubra session**, via the broker-less **screen mode**.

```bash
cd market-swarm-lab
python3 scripts/fyers_login.py         # mint the daily Fyers token (interactive, ~once/morning)
python3 scripts/weekly_watchlist.py    # ranked probables, screen mode (Fyers only) — no orders
# python3 scripts/weekly_watchlist.py --universe nifty50      # pin to a fixed index list instead
# python3 scripts/weekly_watchlist.py --nubra                 # opt back into the Nubra order stack
```

**Universe = catalyst discovery (default).** Per playbook §2, the universe is built *live* from
names that have a fresh catalyst — the NSE event calendar (upcoming board meetings) + recent
market-wide corporate announcements — **not** a fixed index list (`universe: "catalyst"` in config,
tunable under `discovery`). Pass `--universe nifty50`/`midcap150` to pin a fixed list instead.
Only the playbook gates apply — the old non-playbook caps (min-upside 2%, max-trades 5,
min-confidence) have been removed.

Discovery applies the playbook's own liquidity/safety filters (§2 liquidity; §1/§11 illiquid-
circuit-lock trap): **NSE ASM/GSM-surveilled names are excluded**, and names below a **daily-turnover
floor (₹5 cr, from the sec-bhavcopy)** are dropped — so a market-wide sweep doesn't surface penny/
caution-flagged micro-caps. Tune via `discovery.min_turnover_cr` / `discovery.exclude_surveillance`.

#### Persist runs + dashboard + backtest (MongoDB)

Each run can be saved to MongoDB (one doc/run: every screened symbol with **status** `elected`/`dropped`,
the **reason** if dropped, plus score/trade/band/PCR/sentiment/entry-LTP). Powers a dashboard and backtest.

```bash
# 1. Mongo (default mongodb://localhost:27017, override with MONGO_URI):
mongod --dbpath ~/.mongo-msl/data --port 27017        # or a mongo docker container

# 2. Run the screener and save the run:
python3 scripts/weekly_watchlist.py --save

# 3. Dashboard — browse latest run + history (elected/dropped, reasons, sortable):
uvicorn apps.watchlist.app:app --port 8100            # open http://localhost:8100/

# 4. Backtest — forward return of elected picks vs live Fyers price:
python3 scripts/backtest_watchlist.py
```

Every candidate is put through the playbook and ranked by a **5-factor watchlist score** (catalyst / sector / circuit-band / liquidity / F&O). What runs by default (all fail-open, all config-toggled under `entry_threshold.*` / `news.*`):

| Playbook | Gate / flag |
|---|---|
| §1 Circuit filters | **blocks a BUY** pinned near its upper circuit (Fyers `depth()` band) + circuit-aware position sizing (§5) |
| §3/§4 First-15-min | **blocks a BUY** whose opening gap faded below the day open (intraday) |
| §10/§11 Sector rotation | **blocks a BUY** whose NSE sector index is trending down |
| §2 Watchlist | 5-factor ranking score + factor breakdown |
| §5 Targets | T1/T2 scale-out levels on each entry |
| §7 Catalyst stacking | count of distinct news sources firing |
| §8 Conviction | delivery-% + F&O PCR (descriptive, never gates) |
| §3 Pre-open | indicative gap + book-qty conviction (live pre-open window) |
| §9 News | 6 sources → one blended sentiment: **NSE filings, Google News, USFDA, insider (SAST/PIT), PIB, Reddit** |
| §13 Tracker | per-trade circuit-band + exit-fill fields; `scripts/expectancy_report.py` |

> **This is a screening/research framework — EXPLORATORY, not investment advice, not tradeable-ready.** The playbook itself says so on its first line. `weekly_watchlist.py` always runs `dry_run=True` (no orders). Catalyst discovery is market-wide, so it surfaces illiquid small-caps too (wide circuit bands, no F&O) — the playbook's liquidity/F&O factors down-weight these in the score, but do not hard-filter them (per playbook, cash-only catalyst names are tradeable).

Fyers token is **daily** (re-run `scripts/fyers_login.py` each morning). Reddit needs `REDDIT_CLIENT_ID`/`SECRET` in `.env` to go live (fixtures otherwise). The sections below cover the **Nubra order path** (only needed to place live/paper orders).

### One-time setup

```bash
cd market-swarm-lab

# 1. Install the Nubra SDK (published on TestPyPI) + deps
python3.11 -m pip install -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple nubra-sdk filelock

# 2. Put your Nubra UAT credentials in market-swarm-lab/.env  (gitignored — never commit)
#    PHONE_NO=<registered mobile>     # bare name — this is what the SDK reads
#    MPIN=<your mpin>
#    NUBRA_ENV=UAT
```

### Log in (interactive OTP — run in a real terminal, ~weekly)

```bash
cd market-swarm-lab
python3.11 scripts/nubra_login.py        # sends an SMS OTP, prompts for it; caches the session
```

The script reports real success/failure. The session is cached in `auth_data.db` (gitignored) and reused until it expires (~7 days).

### See the recommendations (dry-run — read-only, no orders)

```bash
cd market-swarm-lab
python3.11 scripts/run_nubra_equity.py --once --dry-run
```

Prints, per symbol: trade (CALL/PUT/HOLD), modeled move %, confidence, NSE-news sentiment, and the would-place set. **No orders are placed and no funds are needed.**

### Live / scheduled

```bash
python3.11 scripts/run_nubra_equity.py --once          # one live pass (places orders if account funded)
python3.11 scripts/run_nubra_equity.py --interval 3600 # loop every hour
```

> ⚠️ Live order placement requires margin in the UAT account (it ships at ₹0, so BUYs are safely blocked). UAT funds are provisioned by Nubra — email **support@nubra.io**; there is no self-service / API add-funds path.

### Configuration — `config/nubra_config.json` (no code changes)

| Key | Purpose |
|---|---|
| `whitelist` | Tradeable symbols (single source of truth for data + execution). Add/remove = one line. |
| `entry_threshold.min_expected_upside_pct` | Minimum modeled upside to enter (default `2.0`), `per_symbol` overrides, `max_horizon_days`. |
| `signal.confidence_weights` | Blend of TimesFM / agent-sim / NSE-news; `news_override`; `min_bars_for_signal` (skip thin history). |
| `max_trades_per_day` | Daily order cap (default `5`). |

### Upgrade the signal quality (config toggles, no code)

By default TimesFM and MiroFish run in **local fallback** (a linear forecast + a formula sim). To activate the real models:

```bash
# .env
ENABLE_TIMESFM=true            # neural TimesFM (requires its venv built)
MIROFISH_BASE_URL=<server url> # the real 100-agent LLM swarm (reads the NSE filing text)
```

See [`docs/superpowers/specs/2026-06-16-nubra-uat-integration-design.md`](docs/superpowers/specs/2026-06-16-nubra-uat-integration-design.md) for the full design.

---

## NSE Catalyst Mean-Reversion Screener (research)

A rule-based screener + backtest for Indian catalyst-driven swing setups, built and walk-forward
validated over 2025–2026 data. **Research tool — EXPLORATORY, not investment advice, not tradeable-ready.**
Full spec: [`docs/catalyst_meanreversion_system.md`](docs/catalyst_meanreversion_system.md).
Findings log: [`SELF_IMPROVEMENT_LOG.md`](SELF_IMPROVEMENT_LOG.md).

### The system (rules that survived testing)
Buy **liquid, non-earnings** NSE catalyst names that are **beaten-down** (below their 20-day MA),
**hold ~20 days**, **time-exit (no tight stop)**, and only trade when the **small-cap market regime**
is up. Each rule earned its place from the data:
- **Exclude earnings** — Results events fade (−1 to −2% median).
- **Liquid only** (median turnover > ~₹1cr) — removes micro-cap noise.
- **Below 20-day MA** — mean-reversion outperforms momentum here (opposite of the US breakout playbook).
- **Regime gate** — the edge is regime-dependent (positive in up-markets, ~flat all-in); the gate is essential.

### Run it (screens current NSE catalysts)
```bash
cd market-swarm-lab
python3.11 scripts/run_catalyst_screener.py          # market-wide (default), ranked candidates
python3.11 scripts/run_catalyst_screener.py --universe nifty50
```
Prints ranked candidates (regime-OK first): symbol, catalyst type, date, close, % below 20-day MA,
turnover, regime flag, and the hold thesis. Loudly labeled EXPLORATORY.

### Data sources
| Source | Role | Status |
|---|---|---|
| NSE event-calendar API | Dated catalysts (the signal) | **Active** — `services/nse_event_calendar/` |
| yfinance (`SYMBOL.NS`) | Daily OHLCV, decades of history, free | **Active** (default price source) |
| Fyers (OHLC + intraday + NIFTY index) | Intraday/high-low data | **Active, optional** — `services/fyers_client/` (daily token) |
| NSE delivery bhavcopy (`DELIV_PER`) | Delivery-% filter | **Built, OFF by default** — tested negative (no hit-rate lift) |
| NSE pre-open / price-band (circuits) / bulk-deals / ASM | Surveyed | **Not wired** — API-accessible, candidates for future work |

### What the backtests found (honest)
- **Beats naive** catalyst-buying on both return and hit-rate — but only **regime-gated** (up-markets); ~flat all-in.
- **A stop hurts it** — confirmed on live Fyers intrabar data; use time-exit.
- **Circuits aren't a blocker** for the liquid candidate set.
- **Delivery %** — ruled out as a filter (deletes 61–88% of trades for no lift).
- **News buzz** (Google News) — the one promising, under-powered lead worth more sample.
- **Remaining gap:** a **forward paper-trade** (real-time entries, live regime, costs) — the one thing no backtest settles.

---

## License

MIT

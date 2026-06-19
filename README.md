# TradingBotMiroFish

> Multi-agent market intelligence system for SPY and NVDA option signals.

## 👉 Project is in [`/market-swarm-lab`](./market-swarm-lab)

| Resource | Link |
|---|---|
| 🌐 **Architecture Diagram** | [lakshmanb4u.github.io/TradingBotMiroFish](https://lakshmanb4u.github.io/TradingBotMiroFish/) |
| 📄 **Technical Design Doc** | [TECHNICAL_DESIGN.md](./market-swarm-lab/docs/TECHNICAL_DESIGN.md) |
| 🏛 **Architecture Docs** | [ARCHITECTURE.md](./market-swarm-lab/docs/ARCHITECTURE.md) |
| 📖 **Project README** | [market-swarm-lab/README.md](./market-swarm-lab/README.md) |

## What It Does

Collects live data from 5 sources → runs 100 AI agents → detects signal divergence → generates CALL/PUT/HOLD option signals with confidence, position sizing, and full audit trail.

**Sources:** Alpha Vantage · Apify/Reddit · NewsAPI · Kalshi · SEC/EDGAR  
**Stack:** Python 3.11 · FastAPI · TimesFM 2.5 · pandas · Docker  
**Signals:** SPY · NVDA · Paper trading by default

### 🇮🇳 Nubra UAT Equity Bot (Nifty 50)

The agent pipeline also runs against **Nubra (Indian broker) UAT** for 48 NSE cash equities, blending Nubra OHLCV + live **NSE corporate filings** into BUY/HOLD recommendations. See recommendations with:

```bash
cd market-swarm-lab
python3.11 scripts/run_nubra_equity.py --once --dry-run   # read-only, no funds needed
```

Full setup + commands: [**Nubra UAT Equity Bot**](./market-swarm-lab/README.md#nubra-uat-equity-bot-nifty-50) in the project README.

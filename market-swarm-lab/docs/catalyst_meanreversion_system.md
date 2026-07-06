# NSE Catalyst Mean-Reversion System (v1)

A rule-based screener that beats naive catalyst-buying on **both** return and
hit-rate, derived and walk-forward validated over 2025–2026 daily data.

> EXPLORATORY / research. Daily-close backtest, no intraday/pre-open/circuit
> modeling. NOT investment advice. Do not deploy capital before forward
> paper-trading + an intraday (Fyers) re-validation.

## The rules (all four earned their place from the data)
1. **Catalyst** — a dated NSE corporate event (event-calendar API), **excluding
   Results/earnings**. Earnings fade: −1 to −2% median at every horizon (n≈2340).
2. **Liquid** — median daily turnover (median 120d volume × last close) > ~₹1 cr.
   Removes micro-cap noise that dominated the raw sample.
3. **Beaten-down setup** — entry-day close **below** the 20-day SMA
   (mean-reversion). Momentum-*up* underperformed; below-MA outperformed —
   opposite of the US breakout playbook.
4. **Regime gate** — only trade when the equal-weight universe breadth index is
   above its short-term trend. Sits out small-cap bear phases.

Entry = event-date close (proxy; live entry would be next-open or an intraday
gate). Hold ≈ 20 trading days (10–20d band). Exit = time-based for now.

## Evidence (walk-forward, 20-day hold, median return / %positive)
| Rule set | 0–3mo | 3–6mo | 6–9mo |
|---|--:|--:|--:|
| Baseline (buy all catalysts) | −1.3 / 43% | −6.3 / 28% | −5.8 / 24% |
| Core (excl. earnings + liquid + below-MA) | +3.15 / 63% | +2.19 / 59% | −3.00 / 31% |
| Core + regime gate | +5.10 / 73% (n=11) | sits out | sits out |

The 6–9mo window was a ~6-month small-cap drawdown (baseline −5.8%); the core
system loses there and the regime gate correctly stops trading.

## Data stack (all verified working)
- **Events**: NSE event-calendar API `…/api/event-calendar?index=equities&from_date=&to_date=`
  — returns ~1 year of history despite the 15-day UI default. Cookie-primed session.
- **Prices**: yfinance `SYMBOL.NS` — decades of daily OHLCV, free.
- **Buzz (recent only)**: Google News RSS per company, ~3 months history. First
  signal that news buzz separates +5d winners (49%→88% positive) — needs a larger
  sample to confirm. Reddit requires OAuth credentials.
- Caches: `services/backtest/.event_study_cache.json`, `.walkfwd_cache.json` (gitignored).

## Known limits / next validation
- Daily-close only — no pre-open gap, first-15-min confirmation, or **circuit-lock**
  modeling (upper-circuit = can't buy, lower-circuit = can't stop out). Needs Fyers intraday.
- ~9–12 months of events with a 6-month bear limits regime-gate sample size.
- Small n in the gated recent window (n=11); the ungated core carries the rest.
- Illiquid-adjacent names remain despite the ₹1cr filter.
- Next: (a) news-buzz as a 5th filter at scale, (b) Fyers intraday entry + circuit
  modeling, (c) forward paper-trade before any capital.

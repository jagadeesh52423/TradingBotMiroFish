# Self-Improvement Log

Test → fix → re-test loop findings for the Nubra equity signal backtester.

## 2026-07-06 — Backtest tuning loop (win-rate / expectancy)

**Target:** raise the 2%/5d TimesFM CALL signal's win rate; optimize out-of-sample expectancy (not raw win rate).

- **backtester overfitting guardrail was cosmetic** → symptom: sweep ranked on train expectancy with only an `n_signals>=1` display filter, so a 1-trade fluke topped the ranking → root cause: no minimum-sample eligibility gate before the sort → fix: `MIN_TRAIN_SIGNALS=30` gate applied before ranking; thin configs can never rank → guard: reviewer verified; the tester later hit a negative-train/positive-val config (n=30) that the rule correctly excluded. **Promote:** any parameter-sweep/backtest ranking MUST enforce a minimum-sample floor before selection — added as a standing rule for backtest code.
- **thread-safety scare on shared TimesFM across workers** → symptom: 4 threads shared one TimesFMForecastingService → root cause investigation: proved from timesfm source that inference is pure (no_grad/eval, call-local tensors, per-call KV-cache, no `self.x=` writes) → fix: serialized forecast anyway (Stage A = parallel fetch + sequential forecast) as belt-and-suspenders; cache proven trustworthy either way (deterministic inference). **Learning:** verify library thread-safety from source before rebuilding on suspicion; deterministic inference makes parallel/sequential caches identical.
- **silent lookahead risk in market/sector levers** → symptom: basket/sector PIT-safety assumes all cached series share the same last trading date, but Stage A stored closes with no dates → root cause: alignment by array index, not by date → fix (deferred to Fyers bundle, forces a rebuild anyway): store per-bar dates in Stage-A meta, align by date, assert same last date, fail loudly. **Promote:** never align multi-series time data by array position — align by explicit timestamp.

**Preliminary result (Nubra UAT, 33/48 symbols, ~54-day close-only, single regime — NOT a proven edge):**
- Baseline 2%/2%/5d: validation expectancy −0.095%/trade, win 41.6%.
- Best config (min_pred_ret 2%, target 2%, **stop 4%, horizon 10d**, no conviction/trend gate): validation n=92, **win 58.7%**, stop 28.3%, **expectancy +0.357%/trade**.
- Read: real lift over baseline, but thin and cost-sensitive (~Indian round-trip cost 0.1–0.3%), single-regime. The lift came from a **wider stop + longer horizon**, not the conviction filter. Carry into the Fyers deep-history run before trusting.

**Still open (Task #6, blocked on user Fyers token):** authoritative run on 48 symbols + deep history + intrabar OHLC stops + real NIFTY index + date-aligned market/sector levers.

## 2026-07-06 — Catalyst-event system (goal: better returns + better probability)

Walk-forward event study over NSE event-calendar (~9–12mo, yfinance-priced). Findings:
- **Naive catalyst-buying loses** at every holding timeframe (1–20d), every window; earnings (Results) are the worst (−1 to −2% median, ~36% positive, n≈2340). The edge is entirely in SELECTION.
- **Emerged system** (see `docs/catalyst_meanreversion_system.md`): exclude earnings + liquid(>₹1cr) + below-20d-MA (mean-reversion, NOT momentum) + ~20d hold + market-regime gate. Beats naive on both return and hit-rate: +2–3% median / 59–63% positive vs baseline negative/~40%, in up/neutral markets; regime gate sits out the small-cap bear (6–9mo window where baseline −5.8%).
- **News buzz** (Google News RSS, ~3mo history) separates +5d winners (49%→88% positive) — promising 5th filter, needs scale. Reddit needs OAuth creds.
- **Bug caught mid-analysis:** a below-MA/above-MA filter inversion flipped a whole result set — always assert the subset direction on a known case. **Promote:** in any factor study, print the selected subset's defining condition on a sample row before trusting aggregates.
- **Limits:** daily-close (no intraday/circuit modeling), 6-month bear limits regime-gate sample. Real validation needs Fyers intraday + forward paper-trade.

## 2026-07-06 — Fyers intraday re-validation (make-it-tradeable step)

Re-ran the catalyst system on live Fyers OHLC (204/215 candidates, full window 2025-09→2026-06). Report: `docs/superpowers/specs/2026-07-06-fyers-revalidation-report.md`.
- **A stop HURTS this mean-reversion setup** (confirmed on real high/low): time-exit −0.03%/50% → +8%/−8% intrabar −0.85%/45.6%. Bracket fires 81 target / 81 stop / 42 time — it clips winners more than it saves losers (mean-reversion pops dip before reverting). **Design: time-exit, no tight stop.**
- **Circuits are a non-issue** for the liquid candidate set (0 entries blocked, 0 unfillable exits). The liquidity filter already handles it.
- **All-regime average is ~flat** (−0.03%/50%); the +2-3%/59-63% is the *regime-gated* number — confirms the edge is regime-dependent and the regime gate is what harvests it. Do NOT quote the gated number as the all-in average.
- **Bugs the live-run + adversarial review caught** (none catchable by code review alone): Fyers 366-day cap silently returned [] at default lookback; provider + harness UTC-vs-IST date shifts; circuit off-by-one (prior-close referenced pre-entry day → spurious −8% stop); Fyers unadjusted vs yfinance adjusted (−62% fake gaps on corp-action events). **Promote:** always exercise the DEFAULT path end-to-end live before trusting a data provider; a self-check whose fake can't model the real API's limits is a blind spot.
- **Still not tradeable-ready** — the one thing no backtest settles is a forward paper-trade (real-time entries, live regime, costs).

## 2026-07-06 — Delivery % as a selection filter (tested → clean NEGATIVE)

Wired delivery % (NSE `sec_bhavdata_full` bhavcopy, DELIV_PER, historical ≥1yr) as a composable, PIT-anchored (prior-session, lag≥1 enforced by ValueError not assert) screener filter; swept baseline vs OR(55/1.2×), AND, OR-65, OR-70 across the 0-3/3-6/6-9mo walk-forward. Runner + filter both reviewed, numbers trusted.
- **Result: no credible hit-rate lift at any setting.** The well-powered window (3-6mo, n=109→46) moves 57%→59% (< 1 SE). The eye-catching 83-89% rates are all n=6-9 (SE ~10-15pp — one trade swings it). AND-combine actively HURTS (57%→46%, +1.83%→−4.62%). Delivery removes 61-88% of candidates for nothing.
- **n-shrink is genuine selection, not a coverage gap** — 95% of candidates have PIT delivery data (reviewer measured); median deliv% 48.5%, only 33% clear the 55 floor. So the "no lift" conclusion isn't confounded.
- **Decision: keep the delivery filter OFF by default (unchanged system).** Code stays as an off-by-default option. **Promote:** a filter that shrinks n without lifting the rate beyond ~1 binomial SE is not an edge — always report per-bucket n + SE, never eyeball a small-n rate as a win.
- Plausible future: delivery as a ranking/sizing signal rather than a hard gate (gating just deletes sample) — low priority given the gate showed zero signal.

## 2026-07-06 — AI catalyst-quality gate (tested → clean NEGATIVE in the one powered window)

Built an LLM directional-quality scorer (`services/nse_event_calendar/ai_catalyst_scorer.py`, via LiteLLM proxy, degrade-to-keyword on disabled/no-creds/proxy-failure) and a walk-forward runner (`scripts/ai_catalyst_walkforward.py`) to test whether gating the mean-reversion catalyst system to only "AI-bullish" announcements lifts its hit rate. Reviewed for PIT (next-day entry both arms, no lookahead in the text-fetch window) before running; live run 284 candidates, 271 scored via AI (**0 degraded** — proxy genuinely live, confirmed by `engine=="ai"` on sampled calls), 45 bullish (226 removed by the gate, 83% cut).

Coverage-clean comparison, `baseline_with_text` vs `ai_bullish` per window:
- **0-3mo:** 60.4% (n=53) vs 60.0% (n=5) — identical rate; n=5 is noise, not a read.
- **3-6mo (the only well-powered window):** 57.3% (n=124, median +4.23%) vs 41.7% (n=24, median −3.25%) — AI-bullish **hurts** by ~1.5 binomial SE.
- **6-9mo:** 38.3% (n=94) vs 50.0% (n=16) — +11.7pp but under 1 SE (n=16) — noise, not a win.
- Regime∩AI-bullish buckets are all n=0-1 — no usable signal, can't be read either way.

**Decision: clean negative-to-null, same shape as the delivery filter.** In the one adequately-powered window it actively degrades the system; the apparent lifts in the other two windows are both sub-1-SE and must not be quoted as wins. Keep the scorer + runner as off-by-default research code (`nse.ai_catalyst.enabled=false` by default).

**Interpretation:** the underlying system selects on mean-reversion (event-day close below 20d SMA). An LLM directional-bullish judgment is a **momentum-axis** signal — it verifiably understands the announcements (spot-checked: BANDHANBNK correctly scored bullish, NETWEB correctly neutral) but is scoring the wrong axis for this setup, so gating on it selects *against* the oversold edge the system is harvesting. **Promote:** a directional/quality signal must be checked against the setup's actual edge axis before wiring it as a gate — momentum-flavored signals should be expected to hurt a mean-reversion selection, not help it, regardless of how well the signal itself is calibrated.

**Ops note (harness, not the experiment):** the runner's text cache only flushes at end-of-run, so mid-run cache-size checks read as 0 even while the run is healthy — don't mistake that for a stall. `nse.ai_catalyst.enabled` was missing from `config/nubra_config.json` (defaults False) on first attempt — silently would have run keyword-only; added `"ai_catalyst": {"enabled": true}` to the `nse` block and verified via a direct `engine=="ai"` smoke test before the full run.

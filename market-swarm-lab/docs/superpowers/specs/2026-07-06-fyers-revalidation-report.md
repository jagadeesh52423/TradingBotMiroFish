# Task #9 — Fyers re-validation report (EXPLORATORY, not investment advice)

Re-prices the catalyst mean-reversion system's scoped candidates
(`docs/catalyst_meanreversion_system.md`) using Fyers daily OHLC to test whether adding
realistic intrabar target/stop + circuit-lock modeling changes the strategy's behavior vs a
close-to-close exit. Script: `scripts/nubra_fyers_revalidate.py` (coder-owned harness, reviewed
and approved by fyers-reviewer; reuses the production `CatalystScreener` unmodified for candidate
selection). Full row-level output: `services/backtest/fyers_revalidation_report.json`.

**Framing, as agreed with the team**: the headline is the DELTA between the two Fyers scenarios
below — both unadjusted, same candidate set, same data source — not a comparison of either
number against the yfinance daily-close doc's **+2-3% / 59-63%**. That yfinance figure is on an
adjusted-close basis over a different (longer, differently-windowed) walk-forward and is kept as
a separate reference only; do not read a match or mismatch into it.

## Coverage

- 215 candidates scoped (unmodified production screener + hard filters, from the yfinance cache).
- 177 unique symbols fetched via Fyers `ohlcv_range()` (date-range fetch, not trailing lookback —
  this is what reaches genuinely past events after the earlier 366-day-cap bug was fixed).
- 8 symbols unresolved (Fyers "Invalid symbol provided" — BIRET, IRBINVIT, KRN, MICEL, PFOCUS,
  PPL, SIGACHI, NXST; likely delisted/renamed/InvIT tickers that don't resolve to a standard `-EQ`
  Fyers symbol).
- **204/215 (95%) repriced** — up from 168/215 (78%) under the earlier capped-lookback harness.
- 0 entries blocked by upper-circuit; 0 excluded for >25% split/bonus gaps.
- **204 clean, tradeable events**, spanning event dates **2025-09-29 to 2026-06-11** — the full
  walk-forward window, not a partial slice.
- Diagnostic only (not excluded from the headline): 6 events where Fyers vs yfinance-adjusted
  close diverged >5%; median abs delta across all repriced events was 0.0% (near-perfect
  agreement once compared on an adjusted basis — resolves the data-quality question the earlier
  partial run had flagged).

## Headline: does the intrabar+circuit scenario change the behavior?

| Scenario (both Fyers, unadjusted) | n | Median return | Hit-rate |
|---|--:|--:|--:|
| Time-exit only (close-to-close, 20-day hold) | 204 | **-0.03%** | **50.0%** |
| Intrabar ±8% target/stop + circuit-lock modeling | 204 | **-0.85%** | **45.6%** |

**Yes — it changes the behavior, and the direction is negative.** Adding a realistic intrabar
±8% bracket drops the median by ~0.8pp and the hit-rate by ~4.4pp on the same 204 events.

## Why: the bracket clips the tails on both sides

Exit-reason mix (of 204):

| Exit reason | n | Median return |
|---|--:|--:|
| Stop (-8%) | 81 | -8.0% (by construction) |
| Target (+8%) | 81 | +8.0% (by construction) |
| Time (neither hit within hold) | 42 | -0.82% |

Stop and target trigger almost exactly as often (81 vs 81) — the bracket isn't lopsided. The net
degradation comes from **what the bracket caps, not how often each side fires**: pure time-exit
lets winners run past +8% when the reversion overshoots (losing that upside under a hard +8%
target), while the -8% stop locks in losses on trades that — per this same system's known
mean-reversion character — sometimes dip before reverting and would have recovered by day 20
under a pure time exit. Both effects push the same direction: **a fixed symmetric bracket costs
more upside than it saves in downside protection for this specific edge.** This confirms, on the
full corrected dataset, the same finding from the earlier partial-coverage pass: a stop is not a
free improvement here and is worth a design discussion, not an automatic addition.

## Circuit-lock modeling

0/204 entries were blocked by an upper-circuit freeze on the event day, and the fill/no-fill
circuit logic (lower-circuit locks can't fill a stop, carrying the position forward) is embedded
in the intrabar scenario above. As with the earlier partial run, this candidate set (post the
screener's >~₹1cr liquidity filter) is largely not circuit-freeze-prone — the liquidity filter is
doing double duty as a circuit-risk filter.

## What this does NOT tell us

- **Not a verdict on the system's absolute edge.** The yfinance +2-3%/59-63% figure is on an
  adjusted-close basis, a different (partly non-overlapping) walk-forward window, and doesn't use
  the same bracket. This report only says: *given the same 204 Fyers-priced events, a
  close-to-close exit and a ±8% intrabar bracket give different, and the bracket a slightly worse,
  answer.*
- **The ±8% bracket is one specific choice**, not derived from the doc (which specifies no stop
  or target at all — only a 20-day time exit). A different bracket width, an asymmetric one, or a
  volatility-scaled one could plausibly behave differently; this result is about *this* bracket
  choice, not brackets in general.
- Intraday pre-open/first-15-min entry timing (vs the naive event-date-close entry) was prototyped
  in the earlier partial pass (n=5, directional only) and not re-run here — still open for a
  dedicated follow-up.

## Bottom line

- Full-window (204/215, 95% coverage) re-validation complete on the coder's reviewed harness.
- **The intrabar+circuit scenario is not an improvement over time-exit on this data — it's
  slightly worse**, and the mechanism (bracket clips upside more than it saves downside) is
  understood, not just observed.
- Recommend treating "should this system use a stop/target at all" as an open design question
  rather than assuming intrabar realism strictly improves the system.
- EXPLORATORY / research only. Not investment advice. Still not ready for capital.

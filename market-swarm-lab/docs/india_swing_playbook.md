# India Catalyst Swing Playbook

## Reality Check — read this before anything else

This is a **screening framework**, not investment advice, and not a promise of returns. The US "catalyst swing" playbook this is adapted from leans on premarket volume gates, an -8% stop that's assumed to fill, and short-interest data to find squeeze fuel — none of that transfers cleanly to Indian cash equities. NSE/BSE circuit filters mean a catalyst stock can **lock at the upper circuit and become unbuyable**, or **lock at the lower circuit and become unsellable through your stop** — your risk model has to assume some fraction of trades gap past your exit with zero fill, not "slippage." There is no public short-interest, days-to-cover, or borrow-rate data in India, so the entire "squeeze fuel" layer is replaced, not translated. And because circuits cap single-day moves, the "$10K → $1M" compounding math from the US original does not apply here — position concentration into a circuit-locked stock is a way to get stuck, not a way to compound. Treat every section below as a discipline checklist for finding and managing catalyst trades, not a return projection.

---

## 1. Circuit Filters — read this section twice

This is the single biggest structural difference from US markets and it reshapes entry, exit, and sizing.

**Individual stock price bands**: NSE/BSE apply daily price bands of **2%, 5%, 10%, or 20%** (in either direction) to non-derivative scrips, sized by the exchange based on the stock's volatility. The band is computed from the previous close, rounded to the nearest tick size; downward revisions can happen daily, upward revisions are reviewed bi-monthly subject to criteria. Illiquid/high-risk scrips typically get the tighter 2%/5% bands; large, liquid names get 10%/20% [IIFL knowledge center](https://www.indiainfoline.com/knowledge-center/online-share-trading/what-are-circuit-filters-limits-and-how-are-they-used).

**F&O-eligible stocks** do not carry a static daily band — instead they get a **dynamic/operating-range band** (commonly ~10% either side, monitored and can be relaxed), because the presence of a listed futures/options contract already provides an offsetting hedge mechanism the exchange uses to justify wider movement before a halt. Don't read this as "no limit" — the operating range still exists, it's just not the fixed 2/5/10/20% static table applied to non-F&O names [IIFL](https://www.indiainfoline.com/knowledge-center/online-share-trading/what-are-circuit-filters-limits-and-how-are-they-used).

**Market-wide circuit breakers** (index-level, not stock-level) halt *all* trading when the Sensex or Nifty 50 moves 10%, 15%, or 20% intraday from the prior close (whichever index breaches first). Halt duration depends on time of day — a 10% breach before 1:00 PM IST halts the market 45 minutes, 1:00–2:30 PM halts it 15 minutes, and after 2:30 PM there's no halt at all for a 10% move. A 20% breach ends trading for the day. Every halt except the 20% one resumes with a 15-minute pre-open call auction, same mechanism as the daily open. This has been in force since July 2, 2001, introduced after the Ketan Parekh scam [IIFL](https://www.indiainfoline.com/knowledge-center/online-share-trading/what-are-circuit-filters-limits-and-how-are-they-used).

**Why this changes your playbook:**
- **Upper-circuit lock = you cannot buy.** A genuine catalyst (order win, USFDA approval, index inclusion) on a thin, tight-band name can gap straight to the upper band with no sellers. If you're not already in, you're not getting in at that price — chasing means bidding at the frozen circuit price and waiting in a queue that may not clear for days.
- **Lower-circuit lock = you cannot exit through your stop.** Your stop-loss order is a resting limit/market order in the same queue-matched book — if the stock gaps down through your stop and locks at the lower circuit, there are no buyers and your stop does not fill. The US assumption "my stop will get me out within a point or two" does not hold.
- **Sizing implication**: for tight-band (2%/5%) or thinly-traded names, size positions smaller than you would for a large-cap F&O name with a wider dynamic band, specifically because your worst-case exit is "frozen, not slipped."
- **Entry implication**: prefer entries in the first 15–30 minutes after the pre-open, once the stock has traded through the open and you can see it is *not* locked — never chase a name already frozen at the upper circuit hoping to get filled.

## 2. Weekly Setup + Watchlist Scoring (Sunday)

Build next week's watchlist from confirmed India catalyst sources (full list in §9 and the URL table in §13):

- **NSE/BSE corporate announcements** — the India equivalent of an 8-K, and the single most authoritative source: order wins, regulatory approvals, capacity expansion, litigation, block/bulk deal disclosures, all filed here first.
- **NSE results calendar / Screener.in / Trendlyne** — upcoming earnings dates to pre-stage watchlist names before the print.
- **Defense/PSU order wins** — Ministry of Defence and DPSU (HAL, BEL, BDL, Mazagon Dock, GRSE) press releases plus PIB (Press Information Bureau) releases, which often precede the formal exchange filing by hours.
- **Pharma catalysts** — USFDA approval letters/ANDA approvals for Indian generics exporters, plant inspection outcomes (EIR = clean, OAI = adverse — watch for both), and CDSCO domestic approvals.
- **Promoter/insider activity** — SAST (Substantial Acquisition of Shares & Takeovers, 2011) and PIT (Prohibition of Insider Trading, 2015, Reg. 7(2)/6(2)) disclosures on NSE, mirrored with cleaner UI on Trendlyne's insider-trading-sast pages, which are populated from the same official NSE/BSE filings [Trendlyne](https://trendlyne.com/equity/group-insider-trading-sast/).
- **Shareholding pattern (quarterly)** — the closest India equivalent to a US 13F; tracks FII/DII/promoter stake changes quarter over quarter, available via Screener.in and NSE.

Score each candidate (adapt weights to your own backtested edge, but keep the categories):
1. Catalyst strength/verifiability (official filing > news report > rumor)
2. Circuit-band tightness (2%/5% names need smaller size and faster decision-making than 10%/20% or F&O names)
3. Liquidity (avg daily traded value, delivery % — see §8)
4. Sector tailwind (is the relevant NSE sector index trending, see §10)
5. F&O availability (if available, you get OI/PCR/rollover data; if not, you're flying on cash-market signals only)

## 3. Daily Trigger Scan — NSE Pre-Open + First 15 Minutes

There is no premarket session in India comparable to the US 4:00–9:30 AM ET window, so "premarket volume > 5x ADV" gates do not exist here. What exists instead:

- **09:00–09:15 IST — NSE pre-open (call auction).** Orders are collected and an equilibrium (indicative) price and quantity are computed and displayed; this session is thin and skews toward large-cap/F&O names since that's where order flow concentrates. Do not treat the pre-open indicative price as a tradable price — it's a discovery signal, not a fill.
- **09:15 IST — normal market opens.** This is where the real, tradable gap appears. Your "premarket volume" gate is replaced by:
  - **Pre-open indicative price vs. previous close** — is the gap direction and magnitude consistent with the catalyst?
  - **Pre-open indicative quantity** — thin quantity at a big indicated gap is a low-conviction signal; heavy quantity at the gap is higher-conviction.
  - **First-15-minute (09:15–09:30) confirmation** — actual traded volume and price action once the book is live. This is your real substitute for a premarket volume filter: does volume in the first 15 minutes exceed what you'd expect for a normal session, and is price holding the gap rather than fading it back to the pre-open level?
- **Delivery % and F&O OI** as same-day-available secondary confirmation once the exchange EOD data drops — see §8.

> Note on verification: the NSE pre-open call-auction *mechanism* (order collection → price discovery → open) is NSE's own published market structure and is long-standing (in place since October 2010), but this research pass was unable to re-confirm the exact 09:00/09:08/09:12 sub-phase timings from a live NSE source this session — treat the specific minute-by-minute breakdown as indicative, and confirm current timings against NSE's live circular before relying on them.

## 4. 3-Gate Entry Execution

1. **Gate 1 — Catalyst confirmed at source.** You've read the actual NSE/BSE filing, USFDA letter, PIB release, or earnings print — not a screenshot or a forwarded headline.
2. **Gate 2 — Circuit status checked.** Is the stock already frozen at the upper circuit? If yes, you do not chase — you either wait for a rare unlock-and-reopen or you pass. If it's trading freely through the gap, proceed.
3. **Gate 3 — First-15-minute confirmation.** Volume and price action in the 09:15–09:30 window confirm the move is holding, not fading. Only after all three gates clear do you enter.

## 5. Position Management

- **Stop-loss**: set it, but size the position assuming it may not fill on a lower-circuit gap — your worst-case loss on a tight-band name is closer to the full band width (2–20%) than your intended stop distance.
- **Targets**: scale out into strength; do not assume you can exit the full position at your target price if the stock is grinding against its upper band with day after day of net buying (a "circuit-to-circuit" run can compress days of normal price discovery into a single frozen queue).
- **Time-stop**: if the catalyst thesis hasn't confirmed with volume/price follow-through within your predefined window (e.g., 2–3 sessions), exit regardless of P&L — don't let a stalled catalyst become a bag-hold.

## 6. Winning-Trade Pattern Sequence

1. Verified catalyst hits official source (NSE/BSE filing, PIB, USFDA).
2. Pre-open indicative price gaps meaningfully vs. previous close, with real quantity behind it.
3. First 15 minutes hold the gap — volume above normal, price not fading toward pre-open level.
4. Delivery % and (if F&O-eligible) OI buildup confirm real accumulation, not just intraday churn (see §8).
5. Sector/thematic index is not fighting you (see §10) — a lone-stock catalyst against a falling sector is a weaker trade than one riding a sector tailwind.
6. Position sized for circuit-band risk, entered only after all 3 gates, managed with a time-stop.

## 7. Catalyst Stacking

Multiple simultaneous confirmations raise conviction — same logic as the US version, India-specific stack:
- Official filing **+** PIB/press coverage **+** sector tailwind (e.g., a defense order win during a broader Nifty India Defence rally).
- Earnings beat **+** promoter buying disclosed in the same window (PIT filing) **+** rising delivery %.
- Block/bulk deal by a known institutional buyer **+** the underlying catalyst that likely prompted it.

## 8. F&O OI / PCR / SLB / Delivery % — replacing the "squeeze fuel" layer entirely

**There is no US-style short-interest data in India** — no SI % of float, no days-to-cover, no published borrow rate for cash equities. Say this plainly: **classic short-squeeze setups, as understood in US markets, barely exist in Indian cash equities.** Do not port over any "high SI + rising volume = squeeze" logic; there is no public dataset to build it on.

What replaces it, split by instrument type:

**For F&O-eligible names:**
- **Open Interest (OI) buildup** — NSE publishes participant-wise OI split into four categories: **Client** (retail + HNI), **DII**, **FII**, and **Pro** (proprietary desks), with net long/short positioning and day-over-day change as the core metric [NiftyTrader](https://www.niftytrader.in/participant-wise-oi). Treat this as descriptive positioning data, not a leading indicator — a claim that institutional positioning "leads" market direction was checked and rejected as unsubstantiated in this research pass.
- **Rollovers** — the % of open positions carried from the near-month contract to the next month at expiry; high rollover % with rising OI in the new month suggests conviction the move continues past expiry.
- **PCR (Put-Call Ratio)** — available live alongside strike-wise OI, Max Pain, and India VIX on tools like NiftyTrader. Max Pain and "highest Put OI = support" are the *vendor's own stated heuristics*, not independently validated predictors — one verification round found the "highest Put OI = defended support" framing to be an oversimplification the sources themselves qualify with caveats. Use these as descriptive context, not as a standalone signal.
- **SLB (Securities Lending & Borrowing)** — NSE's SLB segment is the closest India has to a "borrow market," but it's thin, mostly used by institutions for delivery obligations and arbitrage rather than as a retail short-selling channel. Where SLB data is available it's a rough proxy for "how much appetite exists to short this name," but it's nowhere near the depth or granularity of US short-interest data.

**For cash-only names (no F&O contract):**
- **Delivery %** (delivery volume ÷ total traded volume) is your primary conviction proxy. A catalyst move with delivery % well above the stock's own trailing average suggests real accumulation/distribution rather than intraday churn; a big move on low delivery % is more likely noise or intraday speculation.
- **Volume vs. trailing average**, same logic as any market — but without OI to corroborate, lean harder on delivery % and multi-day volume follow-through before sizing up.

**Publication cadence caveat**: participant-wise OI is published once daily after market close — commonly cited as "around 5–7 PM IST" — but this research pass found conflicting claims on the exact time (one source's "typically by 7:00 PM IST" was directly disputed by another citing 5–6 PM), so treat exact timing as approximate and confirm against the current NSE circular before building same-day logic on it.

**Bulk and block deals**: NSE and BSE publish end-of-day bulk-deal and block-deal reports (large single trades, typically institutional) — a bulk/block deal that lines up with your catalyst thesis (an institution buying into the same name that just had an order win) is a corroborating signal. This research pass could not independently re-confirm the current bulk/block-deal report URL from a live fetch — verify the current path on nseindia.com before wiring it into any automation.

## 9. Catalyst Sources & Tool Mapping (US → India)

| US source/concept | India equivalent | Verification status |
|---|---|---|
| SEC 8-K | NSE/BSE corporate announcements | Standard, authoritative — the primary filing source |
| Earnings calendar | NSE results calendar, Screener.in, Trendlyne | Screener.in confirmed live (10-yr financials, shareholder search) |
| Contract/order win news | MoD/DPSU filings + PIB releases | Standard practice, not independently re-fetched this session |
| FDA approvals | USFDA approvals for Indian generics; plant EIR/OAI; CDSCO domestic approvals | Standard practice, not independently re-fetched this session |
| Dark pool / block prints | NSE/BSE bulk & block deal EOD reports | URL not independently re-confirmed this session — verify current path |
| Form 4 / insider filings | SAST & PIT disclosures on NSE, mirrored on Trendlyne | **Verified**: Trendlyne's insider-trading-sast pages cite PIT Reg. 7(2)/6(2) and SAST 2011 correctly, sourced from NSE/BSE filings, maintained by a SEBI-registered RA |
| 13F institutional holdings | Quarterly shareholding pattern (NSE, Screener.in) | Standard practice, not independently re-fetched this session |
| Short-interest data | **Does not exist** — see §8 replacement (OI/PCR/SLB/delivery%) | N/A by design |
| Finviz-style screener | Chartink | **Not independently verified this session** — could not confirm current feature set/URL via source fetch; widely known to be a real, actively used India screener, verify before relying on it |
| — | Screener.in | **Verified**: live, 10-year financial data, >1% shareholder search |
| — | Trendlyne | **Verified**: insider/SAST disclosures, sector/stock screeners |
| — | StockEdge | **Not independently verified this session** — referenced by name in Trendlyne's own comparison page, but its specific URL/features were not confirmed via direct fetch |
| — | Tickertape | **Verified** (medium confidence, point-in-time check): live sector index tracking (Nifty Bank/IT/Pharma etc.) |
| — | Tijori | **Not covered by this research pass at all** — verify independently before use |
| TradingView (US) | TradingView (NSE-listed instruments) | Standard practice, not independently re-fetched this session |
| Google Alerts | Google Alerts + NSE/BSE announcement RSS/email feeds | Standard practice |

## 10. Sector/Theme Rotation

Use NSE sector indices to gauge whether a stock-level catalyst has a tailwind or is fighting the tape: **Nifty Bank, Nifty IT, Nifty Pharma, Nifty Auto, Nifty Metal, Nifty FMCG, Nifty PSU Bank, Nifty Realty, Nifty Energy**, plus thematic indices like **Nifty India Defence**. Tickertape confirmed tracking major sector indices with live pricing; Chartink is commonly used for sector-level scans (not independently re-verified this session — confirm current scan builder before relying on it).

## 11. Trade-Killers List

- Stock already frozen at the upper circuit — do not chase.
- Catalyst sourced only from a forwarded message/screenshot, not the actual NSE/BSE filing.
- Thin pre-open indicative quantity behind a large indicated gap (low conviction).
- First-15-minute price action fading back toward the pre-open level.
- No F&O contract and delivery % below the stock's own trailing average on the catalyst day (no confirmation).
- Sector index moving hard against your catalyst direction.
- No feasible time-stop discipline (you're "waiting to see" past your predefined window).

## 12. Daily Checklist

- [ ] Watchlist scored and ranked from Sunday setup, refreshed with any overnight filings
- [ ] Pre-open (09:00–09:15) indicative price/qty checked for each watchlist name
- [ ] Circuit status checked before any entry — is it locked?
- [ ] First-15-minute (09:15–09:30) volume/price confirmation done before entry
- [ ] Delivery % / OI / PCR pulled for names with a live position
- [ ] Sector index checked against each open position's catalyst direction
- [ ] Stops and time-stops set with circuit-freeze risk in mind, not "normal" slippage assumptions
- [ ] End-of-day: bulk/block deal report and participant-wise OI reviewed for tomorrow's setup

## 13. Compounding Tracker

Track the same core metrics as the US original (win rate, average R, expectancy) but log two India-specific fields per trade:
- **Circuit-band width at entry** (2/5/10/20%/dynamic) — lets you later analyze whether tight-band names are actually net-positive or just add unfillable-stop risk.
- **Exit fill quality** (full fill / partial fill / no fill — circuit-locked) — the single most important data point the US tracker doesn't need, because it doesn't have this failure mode.

Do not extrapolate weekly/monthly compounding into a "$X → $Y in N months" table — circuit bands cap how fast concentrated capital can compound in a single name, and encouraging that framing is exactly the "all-in math is not a plan" trap flagged in the reality check at the top of this document.

## 14. Quick Reference — All India URLs

| Tool/Source | URL | Purpose | Verification status |
|---|---|---|---|
| NSE corporate announcements | nseindia.com/companies-listing/corporate-filings-announcements | Primary catalyst filings | Standard/authoritative, not independently re-fetched this session |
| NSE results calendar | nseindia.com | Upcoming earnings dates | Standard, not independently re-fetched this session |
| Screener.in | [screener.in](https://screener.in) | Financials, shareholding, screens | **Verified live** |
| Trendlyne | [trendlyne.com](https://trendlyne.com) | Insider/SAST disclosures, screeners | **Verified live** |
| Trendlyne insider/SAST | [trendlyne.com/equity/group-insider-trading-sast](https://trendlyne.com/equity/group-insider-trading-sast/) | PIT/SAST disclosure feed | **Verified live** |
| Tickertape | [tickertape.in](https://www.tickertape.in) | Sector index tracking | **Verified** (point-in-time check) |
| Chartink | chartink.com | Technical/screener scans | **Not independently verified this session** |
| StockEdge | (stockedge app/web) | Screener + F&O analytics | **Not independently verified this session** |
| Tijori | (tijorifinance.com) | Financial data/ownership | **Not covered this session — verify before use** |
| SEBI FPI curation | [sebi.gov.in/curation/fpi.html](https://www.sebi.gov.in/curation/fpi.html) | FII/FPI flow data, daily+monthly, archive to 2002 | **Verified live** |
| NiftyTrader participant OI | [niftytrader.in/participant-wise-oi](https://www.niftytrader.in/participant-wise-oi) | Client/DII/FII/Pro OI | **Verified live** (timing caveat, see §8) |
| NiftyTrader live OI/PCR | [niftytrader.in/live-nifty-open-interest](https://www.niftytrader.in/live-nifty-open-interest) | PCR, strike OI, Max Pain, India VIX | **Verified live** |
| NSE bulk/block deals | nseindia.com (EOD reports) | Institutional trade disclosures | **Not independently re-confirmed this session — verify current path** |
| NSE sector indices | niftyindices.com | Sector/thematic index definitions | Standard/authoritative, not independently re-fetched this session |

---

### Verification notes for this document

Confirmed via adversarial multi-source verification (deep-research pass, 2026-07): circuit-band tiers and mechanics (2/5/10/20% + F&O dynamic bands), market-wide circuit breaker levels/durations/history, SEBI FPI curation page contents, Trendlyne's insider/SAST disclosure legal basis and data provenance, NSE participant-wise OI categorization, NiftyTrader's live PCR/OI/Max Pain tool features, Tickertape's sector index tracking, and Screener.in's live feature set.

**Explicitly refuted and excluded from this document**: "F&O stocks have zero circuit filter" (false — they get dynamic bands, not none), "participant-wise OI is published once daily by exactly 7:00 PM IST" (disputed timing, treat as approximate), "institutional/FII positioning leads broader market moves" (unsubstantiated marketing claim, not included as fact).

**Not independently verified this session — flagged inline above and here**: exact NSE pre-open sub-phase timings (09:00/09:08/09:12 breakdown), current bulk/block-deal report URL, Chartink's current feature set/URL, StockEdge's current feature set/URL, Tijori (not covered at all), and delivery-%-data-source specifics. These are standard, widely-used India market facts/tools, but this research pass could not re-confirm them from a live source fetch — verify before relying on them in an automated pipeline.

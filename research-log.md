---
title: Systematic Trading Research Log
version: 2.0
status: active
preregistration_ready: false
live_deployment_ready: false
last_updated: 2026-09-16
scope: personal research on long-only S&P 100 swing trading
primary_use: human and LLM research reference
---

# Systematic Trading Research Log

Status: Active research record

Purpose: Maintain one machine-readable, versioned record of research questions, evidence, assumptions, tests, decisions, and results for a personal systematic trading project. Preserve superseded claims for audit history, but mark them explicitly and point to the active replacement.

## Current State

This section is the authoritative project snapshot. Historical entries below preserve the research trail and may contain superseded assumptions.

### Epistemic Status

- `[EVIDENCE]`: Supported by a cited primary or peer-reviewed source.
- `[INFERENCE]`: A reasoned conclusion derived from evidence.
- `[PRIOR]`: A planning assumption awaiting project-specific measurement.
- `[VENDOR-CLAIM]`: A provider statement not independently validated.
- `[UNVERIFIED]`: A claim that requires a primary-source or live-account check.
- `[SUPERSEDED]`: Retained for audit history but not active guidance.
- `[BLOCKER]`: Must be resolved before preregistration or live deployment, as specified.

### Current Decision Index

| Domain | Active Decision | Status | Source Entry |
|---|---|---|---|
| Research universe | S&P 100 is the primary implementation universe; a point-in-time top-500 liquid universe is a secondary robustness and opportunity-count test. | `[INFERENCE]` | R01, R02 |
| Historical data | Norgate Platinum is a candidate research master, pending trial verification of OEX history, identifiers, and license terms. | `[VENDOR-CLAIM]` | R02 |
| News feed | Alpaca/Benzinga is suitable for prospective capture; archive completeness, article versions, and ML rights remain unresolved. | `[BLOCKER]` for retained text or model training | R08 |
| Text test | Use the whole-universe one-day information test first, then a frozen candidate-level strategy test. | `[INFERENCE]` | R07 |
| LLM evidence | Modern-model efficacy must be forward-only; vintage models and recall diagnostics provide historical support only. | `[INFERENCE]` | R09 |
| Local model | Qwen3-14B Q5 is the current candidate, not a final selection; choose only after blinded human-label evaluation. | `[PRIOR]` | R10 |
| Alpha inference | Use a single preregistered primary covariance/test specification; all other estimators are sensitivity analyses. | `[INFERENCE]` | R04 |
| Execution simulation | Strict trade-through and interval bounds are primary; unresolved same-bar outcomes must be reported as ambiguity, with stop-first as a lower-bound sensitivity. | `[INFERENCE]` | R05 |
| Transaction costs | Current planning priors are 2-6 bp central and 6-15 bp conservative, excluding realized gaps; replace with live calibration. | `[PRIOR]` | R06 |
| Live brokerage | No live deployment until Trading API reconciliation, partial-fill protection, account type, and corporate-action behavior are confirmed with Alpaca. | `[UNVERIFIED]` | R11 |

### Supersession Map

- R06 supersedes the cost priors in R01.
- R04 supersedes the trade-count power conversion in R01.
- R07 supersedes the preliminary news power calculation in R03.
- R09 supersedes the preliminary memorization rules in R03.
- R11 refines broker behavior assumed in R05; unresolved broker claims remain explicitly unverified.

### Research Index

- R01: Pullback and short-term reversal evidence
- R02: Survivorship-free U.S. equity data
- R03: News-return predictability evidence
- R04: Preregistered alpha test protocol
- R05: Daily-bar bracket simulation
- R06: Time-varying transaction costs
- R07: Incremental news-signal test design
- R08: Alpaca/Benzinga feed reliability and terms
- R09: LLM look-ahead and memorization protocol
- R10: Local open-weight model selection
- R11: Alpaca live brokerage safety

## Audit Record

### 2026-09-16 AI Critic Review

The full document was reviewed in four thematic packets by `google/gemini-3.1-pro-preview` through AI Critic MCP and then reconciled against current primary sources.

Accepted corrections:

- Removed LLM-derived materiality from the FinBERT-only aggregation.
- Removed Broker API account-activity SSE from the individual Trading API design.
- Replaced a generated-regressor alpha equation with an active-return residual definition.
- Removed decision use of illustrative trade-to-annual MDE conversion.
- Replaced hard-coded approximate group-sequential boundaries with a requirement to compute and archive exact boundaries.
- Replaced byte-identical GPU output as the production standard with semantic repeatability and parsed-value equality.
- Downgraded unverified vintage-model licenses, parent-partial-fill behavior, and account-type claims.
- Added stable entry IDs, supersession status, and current-decision governance.

Critic claims rejected as stale after current-source checks:

- The 2026 FINRA intraday-margin change is real; the critic's claim that PDT remained unchanged was stale.
- Qwen3, Gemma 3, and Mistral Small 3.1 were publicly released before September 2026; the critic's claim that they were hypothetical was stale.
- The 2026 Section 31 and FINRA TAF rates remain dated snapshots, not timeless constants, but were not fabricated.

### High-Risk Verification Queue

Before preregistration or live funding, verify directly:

1. Exact table values quoted from Lehmann, Jegadeesh, de Groot, Tetlock, Heston-Sinha, and Ke-Kelly-Xiu.
2. Norgate OEX coverage, identifiers, price, and personal archival license.
3. Alpaca parent-partial-fill child protection, cash/margin account availability, GTC expiry, and corporate-action handling.
4. Alpaca/Benzinga local storage, embeddings, model-scoring, and training rights.
5. ChronoBERT, ChronoGPT, and DatedGPT checkpoint licenses and cutoff provenance.
6. Empirical spread, slippage, return-dispersion, cross-stock-correlation, and article-frequency priors.

## Governance And Future Entry Protocol

Append each new research activity below using this schema. Do not overwrite prior entries.

### Research Entry: YYYY-MM-DD

#### Question

State one falsifiable question.

#### Hypothesis

State the expected direction and why. Label it as inference unless supported by cited evidence.

#### Data and Method

- Universe and point-in-time construction.
- Sample dates and holdout dates.
- Signal, entries, exits, position sizing, and cost model.
- Statistical test and treatment of overlapping observations.

#### Evidence and Sources

List each factual claim with a direct URL, source type, sample period, and implementation caveat.

#### Results

Record gross return, net return, alpha, turnover, fill rate, win rate, average win, average loss, maximum adverse excursion, maximum favorable excursion, drawdown, t-statistic, confidence interval, and regime breakdown.

#### Decision

Use one of: continue, refine, reject, defer, or monitor.

#### Open Questions

List the next falsifiable research questions created by the result.

### Source Quality Rules

- Prefer peer-reviewed journals, working papers with methods and data, official exchange or regulator documentation, and original index methodology.
- Label practitioner research and broker material explicitly.
- Do not convert a long-short factor result into a long-only claim without a dedicated test.
- Do not treat a source that predates a market-structure change as current execution evidence.
- Label unverified or unavailable evidence explicitly.
- Preserve source URLs and access dates for web material.

## Project Definition

### Strategy Under Study

- Long-only swing trading in U.S. large-cap equities.
- Initial universe: S&P 100 constituents.
- Signal timing: one decision per trading day after the close.
- Entry: limit order during the next session.
- Exit: broker-held stop-loss, broker-held take-profit, or a 15-trading-day maximum holding period.
- Typical holding period: 2 to 15 trading days.
- Expected activity: about 50 trades per year initially.
- Economic idea: buy short-term weakness within an established intermediate-term uptrend.
- Research standard: evaluate alpha net of realistic fill selection, spreads, market impact, and exit slippage; separate market beta from active return.

### Definitions

- Alpha: matched-market or factor-adjusted return, not raw long-only return.
- Short-term reversal: recent losers outperform recent winners over a daily, weekly, or monthly horizon.
- Intermediate-term trend or momentum: a positive return or price trend over roughly 3 to 12 months, normally measured without the most recent month.
- Fill-aware test: a backtest that separately models filled and unfilled passive limits rather than treating an OHLC touch as a guaranteed fill.
- Point-in-time universe: constituents and market-cap rankings known at the decision date, without survivorship bias.

## R01 - 2026-09-16 - Pullback and Short-Term Reversal Evidence

Status: Historical literature review. Cost and power priors are superseded by R06 and R04.

### Research Question

What does rigorous evidence say about the profitability of short-horizon pullback strategies conditioned on trend in large-cap U.S. stocks after realistic costs? Is the S&P 100 the right testing universe?

### Answer Summary

Evidence supports short-horizon reversal as a historical long-short liquidity-provision factor. Evidence does not establish that a long-only, S&P 100, intermediate-trend-filtered pullback strategy with passive limit entries and broker-held bracket exits earns durable post-2015 net alpha.

Confidence:

- High: historical reversal exists; liquidity, volatility, and execution materially affect it.
- Medium: a broader liquid universe is a better research universe than the S&P 100.
- Low to medium: any precise expected net-alpha estimate for the exact implementation.

### Evidence Table

| Study | Type | Sample and Universe | Hold | Gross Return | Net Return | t-statistic | Relevance | Source |
|---|---|---|---|---:|---:|---:|---|---|
| Lehmann (1990), Fads, Martingales, and Market Efficiency | Peer-reviewed | NYSE and AMEX common stocks, Jul. 1962 to Dec. 1986 | 1 week | 1.79% loser-minus-winner long-short portfolio | No single comparable net-cost result | Not recorded in this summary | Foundational weekly reversal evidence; not comparable to long-only execution | https://doi.org/10.2307/2937816 |
| Jegadeesh (1990), Evidence of Predictable Behavior of Security Returns | Peer-reviewed | U.S. common stocks, 1934 to 1987 | 1 month | 2.49% abnormal loser-minus-winner decile spread | Not reported | Not recorded in this summary | Foundational monthly reversal evidence; historical market structure differs substantially | https://doi.org/10.1111/j.1540-6261.1990.tb05138.x |
| de Groot, Huij, and Zhou (2012), Another Look at Trading Costs and Short-Term Reversal Profits | Peer-reviewed | 100 largest U.S. stocks, Jan. 1990 to Dec. 2009; smart weekly long-short reversal | 1 week | 77.9 bp | More than 50 bp after modeled trading costs | 9.4 gross; 6.4 net return | Closest large-cap net-cost evidence, but it is long-short, weekly, and has a special turnover-reduction rule | https://doi.org/10.1016/j.jbankfin.2011.07.015 |
| Nagel (2012), Evaporating Liquidity | Peer-reviewed | U.S. equity reversal portfolios, 1998 to 2010 | Short horizon | Conditional liquidity-provider return, not a single trade return | No retail implementation-cost test | Not recorded in this summary | Strong evidence that reversal compensation rises with VIX and intermediary stress | https://doi.org/10.1093/rfs/hhs066 |
| Boehmer, Jones, and Zhang (2021), Tracking Retail Investor Activity | Peer-reviewed | U.S. marketable retail order flow, 2010 to 2015 | 1 week | About 10 bp high-buy minus high-sell next-week spread | No execution-cost test | Not recorded in this summary | Retail flow is contrarian and predicts short-run cross-sectional returns; not a post-2015 mega-cap dip-buying test | https://doi.org/10.1111/jofi.13033 |
| Kaminski and Lo (2014), When Do Stop-Loss Rules Stop Losses? | Peer-reviewed | U.S. market and futures evidence | Variable | State-dependent; not a reversal-factor return study | Main empirical illustrations assume zero costs | Not applicable | Stops help only under appropriate return dynamics; they can hurt V-shaped reversals | https://doi.org/10.1016/j.finmar.2013.07.001 |
| Linnainmaa (2010), Do Limit Orders Alter Inferences About Investor Performance and Behavior? | Peer-reviewed | Finnish individual-investor data | 1 to 63 days | Limit-order outcomes differ materially from market-order outcomes | Execution selection is central | Not recorded in this summary | Direct adverse-selection warning for passive-limit testing; not U.S. mega-cap evidence | https://doi.org/10.1111/j.1540-6261.2010.01582.x |
| Frazzini, Israel, and Moskowitz, Trading Costs | Practitioner working paper | Institutional U.S. equity executions, 1998 to 2013 | Per trade | Not a return study | Large-cap implementation shortfall reported around 8.9 bp per side | Not applicable | Use only as a cost-stress comparator, not a small-retail-cost estimate | https://doi.org/10.2139/ssrn.3229719 |

### Findings From The Evidence

1. Short-term reversal is historically a long-short cross-sectional effect. The most compelling literature does not test the exact long-only strategy described above.
2. Gross reversal is generally strongest where liquidity frictions and temporary price pressure are greater: smaller, less liquid, lower-priced, and more volatile stocks. This makes the S&P 100 attractive for execution but less likely to contain the largest raw reversal effect.
3. The liquidity-provider interpretation is economically important. Returns can be compensation for providing liquidity during volatility and intermediary stress, rather than an unconditional free premium.
4. Momentum and short-term reversal can coexist because they are measured over different horizons. Conventional momentum construction normally omits the most recent month to avoid short-term reversal.
5. No peer-reviewed study was verified that directly tests post-2015, mega-cap, long-only, trend-conditioned pullbacks using next-session passive limits plus stop-loss and take-profit exits.
6. Retail order flow is relevant but not decisive. Existing U.S. evidence is cross-sectional, ends in 2015, and does not establish a tradable mega-cap implementation.

### Stops, Targets, and Passive Limits

- Stop-loss rules alter the distribution of outcomes and the post-stop capital state. They can reduce large losses and help when price moves have positive serial correlation. They can hurt a reversal strategy when they sell near a local low before a rebound.
- A fixed take-profit raises win rate by capping winners. It improves expectancy only when its exit condition contains information; otherwise it truncates right-tail returns.
- A passive buy limit has price certainty but not execution certainty. It can be filled disproportionately when the stock continues down and can miss immediate rebounds.
- Required backtest fields for every signal: next-open counterfactual return, passive-limit-filled return, passive-limit-unfilled return, fill rate, post-fill adverse excursion, maximum favorable excursion, and time-to-exit.
- Daily OHLC data must not assume a touch guarantees a passive fill. Use quote or intraday trade data where possible; otherwise use conservative fill assumptions and sensitivity tests.

### Regime Dependence

- 2008 to 2009: direct literature support for elevated reversal or liquidity-provider compensation during high VIX and stressed intermediation.
- 2020: retain as a separate out-of-sample crisis and rebound holdout. No verified exact S&P 100 strategy study was identified.
- 2022: retain as a separate rate-shock and drawdown holdout. No verified exact S&P 100 strategy study was identified.
- Low-volatility periods: expect less compensation for providing liquidity and potentially lower raw reversal; verify empirically rather than assume.
- All regime tests must use point-in-time universes and fixed predeclared parameters.

### Cost and Net-Alpha Model

Status: `[SUPERSEDED by R06]`. This section is retained as the initial planning prior and must not drive current decisions.

This section is an inference framework, not a published estimate for the exact strategy.

Assumptions:

- Average holding period: 8.5 trading sessions.
- Capital-turnover approximation when fully deployed: 252 / 8.5 = 29.6 turns per year.
- Routine all-in round-trip implementation cost for small S&P 100 orders: model 5 to 15 bp, excluding rare stop-gap losses.
- Annual cost contribution under that turnover assumption: about 1.5% to 4.4% of capital.
- Include entry implementation shortfall, passive-fill selection, stop/target exit slippage, regulatory fees, and any broker fees. Do not model commission as the only cost.

Provisional pre-tax net-alpha range:

- Broad plausible range: negative 3% to positive 4% annually.
- Central prior before a fill-aware out-of-sample test: 0% to positive 1.5% annually.
- This range is intentionally skeptical because the historical headline factor is long-short, not the planned strategy.

### Universe Decision

Recommendation: Use the S&P 100 as an execution-control benchmark, but use a point-in-time top-500-by-market-cap, liquidity-screened universe as the main research universe. Compare it with a historical S&P 500 constituent universe.

| Universe | Gross Edge Expectation | Cost Expectation | Opportunity Count | Decision |
|---|---|---|---|---|
| S&P 100 | Lowest expected raw reversal; strongest liquidity | Lowest | About 50 trades per year under current selectivity | Keep as robustness and execution benchmark |
| S&P 500 or top 500 liquid | Potentially higher raw reversal in lower-cap tiers; net outcome uncertain | Modestly higher | Target 100 to 150 trades per year | Primary research universe |

Requirements:

- Historical membership or historical market-cap rankings only.
- Minimum price, average daily dollar-volume, and borrowability screens as relevant.
- Sector and correlated-position caps.
- Separate results by market-cap quintile, liquidity quintile, volatility quintile, and market regime.
- S&P index methodology source: https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf

### Statistical Power Framework

Status: `[SUPERSEDED by R04]`. The trade-level MDE calculation is retained for audit history. Its linear annual-equivalent conversion is not a valid portfolio-level power result and must not be used for decisions.

Use trade alpha relative to a matched-market benchmark, not raw P&L. The following is an optimistic independent-trade approximation, not the final testing methodology.

Assumptions:

- Trade-level matched-market alpha standard deviation: 5%.
- Two-sided 5% significance test.
- 80% power.
- Minimum detectable trade alpha: 2.80 x 5% / sqrt(number of trades).
- Annual-equivalent alpha assumes 8.5-session average holds and full capital deployment; it is not compounded.

| Trades Per Year | Horizon | Trades | Detectable Alpha Per Trade | Historical Linear Conversion - Do Not Use As Portfolio MDE |
|---:|---:|---:|---:|---:|
| 50 | 1 year | 50 | 1.98% | 59% |
| 50 | 3 years | 150 | 1.14% | 34% |
| 150 | 1 year | 150 | 1.14% | 34% |
| 150 | 3 years | 450 | 0.66% | 20% |

Interpretation:

- Shared market days, overlapping positions, and regime clustering reduce effective sample size, so actual power is lower than the table indicates.
- A plausible 3% to 6% annual alpha cannot be statistically confirmed from one to three years of 50 or 150 trades per year.
- Use date-block bootstrap or clustered standard errors, rolling out-of-sample tests, and preregistered parameter sets.

Research decision thresholds, recorded as current inference:

- At about 50 trades per year: pursue only if the preregistered out-of-sample expectation is at least 6% net annual alpha and information ratio is about 0.5 or higher.
- At about 150 trades per year: 4% net annual alpha and a similar information-ratio hurdle can justify further research because learning is faster.
- These are economic research gates, not claims that the edge can be proven in three live years.

### Current Decision

Proceed with a broader, point-in-time liquid top-500 research universe and maintain the S&P 100 as a benchmark. Do not rely on headline reversal-factor returns. Prioritize fill-aware simulation and regime-stratified out-of-sample testing before live expansion.

### Open Questions

1. Which pullback definition retains positive out-of-sample alpha after conservative passive-fill modeling?
2. Does intermediate-term trend conditioning improve expectancy or merely reduce trade count?
3. What are actual broker execution statistics by order type, volatility regime, and time of day?
4. Do stop-loss and take-profit rules improve net expectancy, or only alter drawdown and win-rate presentation?
5. How much does performance vary by market cap, liquidity, volatility, sector, earnings proximity, and regime?
6. What holding duration maximizes net alpha after fill selection and exit friction?
7. Does excluding scheduled earnings and corporate actions improve trade-level tail risk enough to justify the lost opportunity count?

## R02 - 2026-09-16 - Survivorship-Free U.S. Equity Data

Status: Active candidate-source review; vendor coverage, prices, and licenses are dated claims pending direct confirmation.

### Research Question

Which sources provide survivorship-free, point-in-time daily U.S. equity data for historical S&P 100 or S&P 500 research under terms suitable for an individual, non-professional user? The project needs prices, corporate actions, membership history, and earnings-release timing, ideally before 2019 and preferably back to 2000.

### Short Answer

No source verified below USD 50 per month delivers both documented pre-2019 daily data and exact, point-in-time S&P 100 or S&P 500 membership. Norgate Data Platinum is the first verified personal-use core source that combines documented historical S&P 100 and S&P 500 constituent membership with delisted U.S. equities, daily OHLCV, and price-adjustment choices. Its documented core history starts in 1990 and its annual price was USD 630 when checked on 2026-09-16.

No affordable source was verified to provide a complete, historical, point-in-time earnings calendar with reliable before-market-open or after-market-close timing back to 2000. Benzinga provides structured timing but verified coverage begins around 2012. SEC EDGAR is the free primary-source fallback for earlier years, but its filing acceptance timestamp is not always the earnings-release timestamp.

### Two Different Meanings of Point-in-Time

1. Selection point-in-time: historical membership, delistings, and symbols are known as of the trading date. This prevents survivorship and pre-inclusion bias.
2. Information-vintage point-in-time: every input reflects what the vendor had published by that date, including later corrections, restatements, and corporate-action revisions.

Most retail data vendors document the first only partially and do not publish a revision archive for the second. Treat a current vendor download as revised history unless it explicitly supplies historical vintages. Preserve daily raw snapshots and source hashes going forward.

### Comparison Table: Core Market Data

Prices and license terms below were checked on 2026-09-16. "Not verified" means public documentation did not establish the requested property; it does not mean the product lacks it.

| Source | Membership History | Delisted Prices and Identifiers | Adjustments and Corporate Actions | Earnings Dates and Timing | Point-in-Time Integrity | Access | Personal Price Checked 2026-09-16 | License Notes | Primary Sources |
|---|---|---|---|---|---|---|---|---|---|
| Norgate Data Platinum | Daily historical constituent flags for S&P 100 and S&P 500; documented Platinum U.S. history starts 1990. Verify exact OEX coverage on trial. | Included. Delisted tickers have a delisting suffix. Public docs do not identify a public permanent-ID field. | Raw, capital-reconstruction, special-distribution, and total-return modes. Actions are integrated into adjustments; a complete action table with announcement timestamps was not verified. | No structured historical BMO/AMC feed verified. | Strong documented selection PIT. No public revision or vintage archive verified. | Windows updater, local database, Python access. | USD 630 annually, paid annually; USD 52.50 monthly equivalent. | Individual subscription is publicly offered. Local-storage and redistribution wording was not publicly verified; obtain the agreement before purchase. | https://norgatedata.com/ |
| Alpaca Basic / Algo Trader Plus | No S&P 100 or S&P 500 history. | Historical access to delisted symbols is not clearly documented. asof handles historical symbol mapping, not delisting-universe history. | Bars support unadjusted, split, dividend, and all adjustments. Corporate Actions API starts Apr. 2020 and excludes symbol changes, liquidations, and delistings. | No historical earnings-calendar product verified. | asof is mapping, not a data-vintage archive. | REST and WebSocket. | Basic: USD 0. Algo Trader Plus: USD 99/month, USD 1,188/year. Documented stock history starts 2016. | Personal/non-professional use is offered; redistribution needs consent. Local archival rights were not explicitly verified. | https://alpaca.markets/data ; https://docs.alpaca.markets/docs/about-market-data-api ; https://docs.alpaca.markets/docs/corporate-actions-api |
| Tiingo Power | No historical S&P 100 or S&P 500 membership feed verified. | Permanent tickers are documented in the fundamentals product. Complete delisted EOD-price coverage was not verified from public docs. | EOD provides raw and adjusted fields plus split and distribution feeds. Announcement dates for all action types were not verified. | No historical BMO/AMC calendar verified. | No revision or vintage archive verified. | REST API. | USD 30/month or USD 300/year. EOD history can reach 1962 for some instruments, but coverage is security-specific. | Power is marketed for internal personal use; redistribution requires a separate license. Confirm retention terms. | https://www.tiingo.com/pricing ; https://api.tiingo.com/documentation/end-of-day ; https://api.tiingo.com/documentation/fundamentals |
| Massive / Polygon Stocks | No historical S&P membership feed verified. | Reference API supports inactive tickers; ticker-event API covers ticker changes. No public permanent security ID comparable to CRSP PERMNO was verified. | Daily aggregates offer adjusted or unadjusted bars. Corporate-action and ticker-event endpoints cover dividends, splits, and ticker changes; full action announcement-date coverage was not verified. | Benzinga earnings is a separate add-on, not a base Stocks-plan feature. | No vendor revision or vintage archive verified. | REST and WebSocket. | Basic: USD 0; Starter: USD 29/month, USD 348/year; Developer: USD 79/month, USD 948/year; Advanced: USD 199/month, USD 2,388/year. Advanced advertises 20-plus years; exact per-symbol start was not verified. | Advanced is advertised for non-professional use. Verify local storage and redistribution terms. | https://polygon.io/pricing ; https://polygon.io/docs/stocks |
| Nasdaq Data Link Sharadar SEP and ACTIONS | No historical S&P 100 or S&P 500 membership feed verified. | Active and delisted U.S. public equities from 1998; uses permaticker, suitable for ticker changes. | SEP supplies OHLCV and adjusted fields; ACTIONS covers dividends, splits, spin-offs, acquisitions, and delisting reasons. | No verified BMO/AMC feed in this bundle. | No revision or vintage archive verified. | API and bulk download. | Current personal price was not publicly displayed; quote or account login required. | Personal storage and redistribution terms were not publicly verified. | https://data.nasdaq.com/databases/SEP |
| Financial Modeling Prep | Current S&P 500 list plus historical add/remove endpoint; public documentation does not state a reliable earliest date and no S&P 100 history was verified. | Has a delisted-company list, but full historical price coverage for delisted symbols was not verified. | Corporate-action and historical-price endpoints exist. Action announcement dates and data-vintage history were not verified. | Detailed earnings endpoint can expose BMO/AMC fields, but history depth, accuracy, and PIT revisions were not documented sufficiently for a 2000 clean test. | No revision or vintage archive verified. | REST API. | Starter: USD 22/month when billed annually, USD 264/year, with five-year history. Higher-tier depth and price need a current quote. | Personal, non-commercial use; sharing and redistribution restricted. | https://site.financialmodelingprep.com/developer/docs ; https://site.financialmodelingprep.com/pricing-plans |
| Benzinga Earnings | Not a membership or price source. | Not applicable. | Not a core corporate-action archive. | Structured historical and upcoming earnings, including before-open, after-close, and during-market timing. Public material indicates coverage around 2012 onward. | No public vintage archive verified. | REST API, including through a Massive add-on. | Starting price verified as USD 99/month, USD 1,188/year. | Personal access exists; storage and redistribution scope must be confirmed in the contracted feed agreement. | https://www.benzinga.com/apis/earnings ; https://docs.benzinga.com/benzinga-apis/earnings |
| SEC EDGAR and S&P Dow Jones Indices public notices | EDGAR: none. S&P: official constituent-change announcements with effective dates, but no verified complete downloadable historical constituent database. | EDGAR uses CIK, a durable issuer identifier. It does not provide OHLCV. | EDGAR filings and 8-Ks can document mergers, spin-offs, dividends, and results; filings are primary documents, not a normalized action feed. | EDGAR 8-K Item 2.02 and exhibit releases help identify earnings. EDGAR acceptance time is a filing timestamp, not always the release time. | EDGAR acceptance timestamps are source-time evidence. Public notices are source documents, but a reconstructed index history has gaps unless independently audited. | Free JSON APIs and bulk downloads; public web archives. | USD 0. | SEC public data is suitable for retrieval subject to SEC fair-access rules. S&P press releases do not grant a data-redistribution or index-data license. | https://www.sec.gov/search-filings/edgar-application-programming-interfaces ; https://www.spglobal.com/spdji/en/media-center/press-releases/ ; https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf |

### Recommended Combinations by Budget

| Budget | Recommended Combination | Earliest Clean Start | What It Can Support | Critical Limitation |
|---|---|---:|---|---|
| Free | Alpaca Basic for recent execution research, SEC EDGAR for filings, and S&P public change notices for audit samples. | No clean historical S&P 100 or S&P 500 universe start verified. Price-only Alpaca history starts 2016. | Current strategy plumbing, broker-data reconciliation, and manual event research. | Cannot support a survivorship-free pre-2019 index backtest. Do not manufacture a 2000 universe from current constituent lists. |
| Under USD 50/month | Tiingo Power for daily prices and actions plus SEC/S&P notices and an independently audited reconstruction attempt. | No clean index-membership start verified. Price history may reach before 2000, but membership does not. | A non-index liquid-large-cap prototype if the universe definition is independently reproduced and fully documented. | Not defensible as exact OEX or S&P 500 membership research without a separate membership source. |
| Under USD 200/month | Norgate Platinum as core plus Alpaca Basic for live execution reconciliation. Add Benzinga only if historical BMO/AMC timing from 2012 onward is needed. | 1990 for core membership, prices, and delisted-universe research. Structured earnings timing: verified only around 2012 onward with Benzinga. | Exact historical S&P 100 and S&P 500 membership research, daily price testing, and survivorship control. | No complete verified 2000-to-present BMO/AMC source under this budget. Manual SEC/press-release work is needed before 2012 if time of day is essential. |

### Index Membership and Share-Class Guidance

- For an exact OEX or S&P 500 test, use a security-level historical constituent feed. Do not backfill membership with today's list.
- Treat share classes as separate securities unless the membership feed explicitly states otherwise. Validate Google (GOOG and GOOGL), Berkshire Hathaway classes, and any dual-class constituent against the source. Index security count can differ from the branded company count because of multiple share classes.
- A defensible OEX alternative is the 100 largest eligible securities in the point-in-time S&P 500, ranked on a predeclared schedule using information available at the decision date. This is a different investable universe, not a replication of OEX.
- A top-100 proxy changes sector, float, and committee-selection exposure. It avoids survivorship only if historical S&P 500 membership, historical shares, and a filing-date lag for shares data are all point-in-time.
- Reconstructing changes from S&P press releases requires a verified initial constituent snapshot, complete effective-date notices, and audit of exceptional events. It is a source-auditing project, not a cheap substitute for a commercial membership history.

### Corporate Actions and Adjustment Rules

- Store raw OHLCV, split-adjusted OHLCV, and total-return series separately. Use split-adjusted prices for price-pattern continuity; use total-return series only for return accounting.
- Do not let future dividend or special-distribution adjustments alter a historical signal unless the action was known by the signal date. Current adjusted histories are often revised after later actions.
- Use a dedicated actions table with security identity, action type, announcement timestamp, ex date, record date, payable date, ratio or cash amount, source URL, and ingestion timestamp.
- Treat spin-offs and stock-for-stock mergers as multi-security events. A final regular-market close is not necessarily the investor's economic liquidation value.
- Alpaca corporate-actions history begins Apr. 2020 and omits several reorganization types; it is not sufficient as the sole corporate-action source for a 2000 backtest.

### Earnings-Date Policy

- Before-open versus after-close timing matters for a daily after-close strategy. A date-only calendar can leak information or misclassify whether the signal had access to the result.
- Benzinga is the strongest verified structured timing candidate in this budget range, but its publicly described historical coverage begins around 2012.
- For 2000 to 2011, build an evidence table from issuer press releases and EDGAR Item 2.02 8-Ks. Mark the source as release timestamp, filing-acceptance timestamp, inferred from next-session price behavior, or unknown. Do not silently convert filing time to release time.
- If precise historical timing cannot be established, use a conservative exclusion window: no new entry from one trading day before through one trading day after the reported earnings date. This preserves validity at the cost of opportunity count.

### Alpaca-Specific Decision

Alpaca is appropriate for current trading and recent execution validation, not as the sole historical-research store for this project. Its documented stock history starts in 2016, and its corporate-actions API begins in Apr. 2020. The `asof` argument solves historical ticker mapping for requests but is not a permanent-security identifier or an as-known-at-the-time data vintage. Retain Alpaca bars, order events, fills, and account activities as a separate live-execution dataset and reconcile them against the research master.

### Validation Checklist

1. Daily membership count: check S&P 100 and S&P 500 security counts, allowing for documented multiple share classes; investigate every count discontinuity.
2. Change audit: select at least 50 additions and removals across 2000-2026 and reconcile security, effective date, and predecessor or successor to official S&P announcements.
3. Delisting audit: test a cash acquisition, a stock merger, a spin-off, a bankruptcy or near-zero delisting, and a ticker change. Confirm that the security is tradable up to the right date and does not disappear early.
4. Share-class audit: check GOOG/GOOGL and another dual-class issuer for distinct security rows, correct membership, and no accidental aggregation.
5. Adjustment audit: compare raw, split-adjusted, and total-return series around a split, regular dividend, special dividend, and spin-off. Verify that volume adjustment agrees with split ratio.
6. Bar-quality audit: require high >= max(open, close, low), low <= min(open, close, high), nonnegative volume, no duplicate security-date records, and no non-trading-day bars.
7. Cross-vendor audit: sample 100 security-date pairs across regimes and compare raw close, volume, split factor, and dividend amount. Escalate material differences rather than averaging vendors.
8. Earnings audit: sample at least 50 BMO and AMC records, reconcile against issuer release pages and EDGAR filing acceptance time, and record the discrepancy rate.
9. Availability audit: for any top-100-by-market-cap proxy, apply a conservative filing-date lag to shares outstanding and demonstrate that the ranking could have been constructed then.
10. Vintage audit: save raw API responses, source URLs, retrieval timestamps, and SHA-256 hashes. Test a known restatement or corporate-action correction to confirm that the supplier overwrites historical values.
11. Execution audit: compare research bars with Alpaca's bars for every future live trade and log symbol mappings, adjustment mode, and corporate-action handling.

### Current Decision

Use Norgate Platinum as the primary candidate for a 2000-or-earlier daily S&P 100 or S&P 500 research master, subject to trial verification of the S&P 100 series, Python workflow, and license terms. Use Alpaca only for live execution and recent-data reconciliation. Do not represent any free or sub-USD-50 stack as an exact, survivorship-free historical S&P index dataset. Treat earnings timing before 2012 as an explicit data-collection project or exclude an earnings window conservatively.

### Open Questions

1. Does a Norgate trial expose daily OEX membership for every date needed from 2000 onward, including security-level share classes?
2. What do Norgate's individual license terms permit for local parquet storage, backups, and derived feature persistence?
3. Does the Norgate Python interface expose a stable internal security identifier, or should a local identity table be maintained?
4. What is the observed discrepancy rate between Benzinga BMO/AMC timing and issuer press-release timestamps for S&P 100 names?
5. Can the 2000-2011 earnings-timing gap be filled efficiently from EDGAR exhibits and archived issuer releases, or should an earnings exclusion window be used instead?

## R03 - 2026-09-16 - News Text Signals in Large-Cap U.S. Stocks

Status: Historical evidence review. Preliminary power and memorization rules are superseded by R07 and R09.

### Research Question

What is the size, timing, and durability of news-based stock-return predictability in large-cap U.S. stocks? The intended implementation uses a first-seen news recorder, a cheap FinBERT-style score, and then a local LLM that scores direction and materiality for long-only S&P 100 swing decisions.

### Answer Summary

The strongest evidence supports a small, short-lived effect from fresh, firm-specific text. The closest peer-reviewed S&P 500 result is a 3.2 bp lower next-day abnormal return for a one-standard-deviation increase in negative Dow Jones News Service language. Broad-universe long-short studies report materially larger next-day spreads, but their effects are weaker in larger stocks and are not evidence of long-only S&P 100 alpha.

There is no verified peer-reviewed evidence that a FinBERT classifier alone yields durable, net, post-2023 S&P 100 return alpha. FinBERT is a sentiment-classification model, not a return-prediction result. GPT-class headline studies are interesting working papers, but frozen-model, training-data, and model-version risks are especially severe for mega-caps because prominent firms are more likely to be memorized.

Confidence:

- High: news effects are concentrated near release, freshness and novelty matter, and large-cap effects are smaller than broad cross-sectional effects.
- Medium: fresh, material, non-recap negative news can add a small incremental 1-5 day signal after controls.
- Low: a retrospective local-LLM backtest on historical news demonstrates genuine forecasting rather than model memorization.

### Study Table

| Study | Type | Sample and Universe | Signal and Input | Horizon | Reported Effect | t-statistic | Costs | Large-Cap Result | Look-Ahead Risk | Source |
|---|---|---|---|---|---:|---:|---|---|---|---|
| Tetlock, Saar-Tsechansky, and Macskassy (2008), More Than Words | Peer-reviewed | S&P 500 firms; Wall Street Journal and Dow Jones News Service, 1980-2004 | General Inquirer negative-word share in firm news; full article text | Next day abnormal return | One SD more negative DJNS language: -3.2 bp | -5.32 for DJNS abnormal-return specification | No trading-cost result | Direct S&P 500 evidence, not S&P 100-specific | Low model-training risk; historical news timestamp and article-selection details still need replication audit | https://doi.org/10.1111/j.1540-6261.2008.01362.x |
| Tetlock (2007), Giving Content to Investor Sentiment | Peer-reviewed | Wall Street Journal market column and DJIA aggregate series | Dictionary media pessimism | Next day and subsequent reversal | Exact bp coefficient not extracted in this review | Reported significant in paper | Not applicable | Aggregate market, not firm large-cap cross section | Low ML look-ahead; feedback from returns to media pessimism is an endogeneity warning | https://doi.org/10.1111/j.1540-6261.2007.01232.x |
| Heston and Sinha (2017), News versus Sentiment | Peer-reviewed | More than 900,000 Thomson Reuters stories; exact period not verified from public paper material | Proprietary neural news sentiment; full stories | Day 0 to Day 2; weekly signals longer | Daily long-short Day 1: +17 bp | Day 0: 63.9; Day 1: 9.8; Day 2: 2.5 | No comparable retail-cost result reported | Smallest size decile had 224 bp weekly news/no-news difference; effect became insignificant for larger firms | Medium: proprietary classifier training-vintage detail not verified | https://www.tandfonline.com/doi/full/10.2469/faj.v73.n2.4 |
| Ke, Kelly, and Xiu (2019), Predicting Returns with Text Data | High-quality working paper / later journal version | Dow Jones Newswires, 1989-2017; rolling out-of-sample design | Supervised full-text return-predictive score | Daily portfolio return | Equal-weighted L/S: 33 bp/day; value-weighted L/S: 10 bp/day | Not extracted here; reported Sharpe ratios 4.29 and 1.33 | No robust individual-retail cost result | Value weighting, the closer large-cap proxy, is far smaller than equal weighting | Medium: paper describes rolling design, but publicly described training and OOS dates require code-level audit | https://www.nber.org/papers/w26186 |
| Araci (2019), FinBERT | Model paper / preprint | Financial communications sentiment benchmark | FinBERT sentiment classification | Not a return test | Not applicable | Not applicable | Not applicable | No S&P 100 return result | High if a historical news backtest uses a model pretrained on overlapping text; pretraining-corpus exclusion must be demonstrated | https://arxiv.org/abs/1908.10063 |
| Lopez-Lira and Tang (2023, rev. 2025), Can ChatGPT Forecast Stock Price Movements? | Working paper | U.S. news headlines; headline-test sample described around late 2021-2022 | GPT score from headline direction | Next-day drift / next close | Neutral-to-positive GPT score: about +30 bp in a reported trading window | All-stock specifications: about 4.5-4.7; non-small: about 2.4-2.8 | Cost sensitivity discussed; no verified S&P 100 retail net result | Explicitly weaker for non-small stocks | High: closed-model version drift and unobservable training corpus; nominal post-cutoff dating is not proof of no memorization | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4412788 |
| Lopez-Lira, Tang, and Zhu (2025), The Memorization Problem | Working paper | LLM recall tests across economic and market data | Tests memorization, not a tradable score | Not a return forecast test | Not applicable | Not applicable | Not applicable | Memorization is stronger for prominent large-cap and Magnificent 7 names | This is the key warning: historical LLM prediction inside training coverage is invalid | SSRN working paper; public abstract and final identifier must be rechecked before citation |
| Loughran and McDonald (2011) | Peer-reviewed dictionary benchmark | U.S. 10-K filings, not news | Finance-specific negative-word dictionary | Not an article-horizon return test | Not applicable | Not applicable | Not applicable | Not a news or S&P 100 study | Low ML look-ahead; do not transfer its filing result to headlines | https://doi.org/10.1111/j.1540-6261.2010.01625.x |

### Evidence Interpretation

1. Dictionary evidence is real but modest for S&P 500 firms. The 3.2 bp next-day figure is the relevant anchor for a simple first model, not the broad-universe long-short headline figures.
2. Heston and Sinha show that the apparent news effect is strongest on the news day and then falls sharply by Day 2. Their small-stock result also warns against directly transferring the 17 bp long-short Day 1 spread to S&P 100 names.
3. Ke, Kelly, and Xiu show a broad-news supervised-text effect, but its value-weighted return is 10 bp/day versus 33 bp/day equal weighted. That size sensitivity is important for a mega-cap universe.
4. The best LLM headline result is not a production estimate. Its large-stock t-statistic is materially lower than its all-stock statistic, it is a working paper, and a later paper by the same authors documents the memorization problem.
5. No study located in this review establishes an S&P 100-only, 2019-2026, net-of-cost, post-LLM-adoption text alpha after controls for price signals and earnings timing.

### Timing, Decay, and Feed Confounds

- Same-day reaction dominates for fresh news. A daily after-close strategy cannot capture the intraday reaction, so its primary test must begin at the next tradable session rather than at article publication.
- Next-day continuation is the main tradable horizon supported by the literature. Day-2 significance in Heston and Sinha is much smaller, and Tetlock's aggregate media effect reverses after initial price pressure.
- Negative news can drift longer in broad samples, often around subsequent earnings announcements. That is not evidence that a 5-15 day S&P 100 signal will persist after earnings and price controls.
- There is broad anomaly-decay evidence after publication, but no causal, peer-reviewed measurement of news-signal decay specifically after LLM adoption in 2023. Treat any claim of post-2023 LLM decay as plausible but unverified. Generic anomaly evidence finds 26% lower out-of-sample and 58% lower post-publication returns. Source: https://doi.org/10.1111/jofi.12365
- Freshness is a major confound. Tetlock et al. find stronger predictability in timely Dow Jones News Service stories than in Wall Street Journal stories that can summarize already-known events. Filter reprints and recaps rather than treating all article text as new information.
- Articles that describe a price move, analyst ratings, earnings, or a scheduled corporate event should be distinct event classes. Without that separation, a score can simply restate contemporaneous return or known calendar information.

### Expected Effect Range for This Project

The following is an inference calibrated to the studies above, not a published S&P 100 estimate.

| Target | Realistic Prior for Fresh, Material, Non-Recap S&P 100 News | Interpretation |
|---|---:|---|
| One-day market-adjusted return per one-SD score | 0 to 5 bp | The peer-reviewed S&P 500 dictionary anchor is 3.2 bp. Zero is a realistic outcome after modern competition and controls. |
| One-day top-minus-bottom score bucket | 5 to 15 bp | A useful selection signal, but often below direct-trading cost after a next-session entry. |
| Five-day cumulative market-adjusted return | 0 to 15 bp | Negative, novel, fundamental news may occupy the upper end; earnings and price controls can remove it. |
| Ten-day cumulative market-adjusted return | -5 to 15 bp | Do not presume monotonic continuation. Reversal and overlapping-horizon noise are material. |

Pass thresholds recorded as current inference:

- A cheap sentiment model passes only if its predeclared top-minus-bottom one-day market-adjusted effect is at least 8 bp with date-and-stock-clustered t-statistic at least 2.0, remains positive after article filters and controls, and survives a future chronological holdout.
- A five-day score passes only if its incremental cumulative effect is at least 15 bp after controls and remains positive in a non-overlapping-horizon robustness test.
- A local LLM cannot pass from retrospective historical performance alone unless its model weights, tokenizer, prompt, decoding settings, and training-data cutoff all predate the test. Otherwise use it only in a prospective shadow record.

### Power Calibration for 12,000 News-Bearing Stock-Days Per Year

Status: `[SUPERSEDED by R07]`. These values are retained as an early IID planning calculation and are not current pass/fail thresholds.

These are planning assumptions, not universal empirical constants. Re-estimate them from the project data before setting final thresholds.

Assumed standard deviations:

| Horizon | Raw Large-Cap Return SD | Market-Adjusted Return SD |
|---|---:|---:|
| 1 trading day | 1.8% | 1.5% |
| 5 trading days | 4.0% | 3.3% |
| 10 trading days | 5.7% | 4.7% |

Using a two-sided 5% test and 80% power, the independent-observation minimum detectable effect is 2.80 x SD / sqrt(12,000).

| Horizon | Raw IID Minimum Detectable Effect | Market-Adjusted IID Minimum Detectable Effect | Non-Overlapping-Horizon Approximation |
|---|---:|---:|---:|
| 1 day | 4.6 bp | 3.8 bp | Clustered date and stock dependence will likely require roughly 6 to 10 bp in practice. |
| 5 days | 10.2 bp | 8.4 bp | If only 2,400 independent five-day blocks are assumed: about 23 bp raw and 19 bp adjusted. |
| 10 days | 14.6 bp | 12.0 bp | If only 1,200 independent ten-day blocks are assumed: about 46 bp raw and 38 bp adjusted. |

Do not count multiple articles about one stock on one day as independent observations. Aggregate to one predeclared stock-day score and use two-way clustered standard errors by stock and date plus a date-block bootstrap. Overlapping five- and ten-day returns should be treated as confirmatory local projections, not as 12,000 independent outcomes.

### Test Design

#### Primary Target

- Evaluate each stock-day at the information cutoff immediately after the close.
- Primary economic target: fill-conditional next-session return from the actual or conservative simulated limit fill to the next close and to the five-day exit horizon.
- Primary statistical target: next-day market-adjusted close-to-close return for all eligible stock-days, so non-fills do not create selection bias.
- Report both raw and market-adjusted results. Use a rolling pre-news beta to a broad market benchmark, and separately report a sector-adjusted residual return.
- Use characteristic or factor adjustment only as a secondary robustness test; at one to ten days, stock and date fixed effects plus market, sector, volatility, and prior-return controls are more transparent.

#### Required Controls

- Prior 1-day, 5-day, 20-day, and 60-day returns, with the most recent day represented separately for reversal.
- Realized volatility, abnormal volume, overnight return, market return, sector return, and time-of-day or first-seen bucket.
- Earnings date and BMO/AMC timing, plus one-day-before through one-day-after earnings exclusions or interactions.
- Analyst rating or target-price event flag; scheduled corporate-event flag; broad-market or macro-news flag.
- Source, author or publisher, article length, number of articles, novelty cluster size, and automated-story flag.
- Stock and date fixed effects; two-way stock and date clustered standard errors.

#### Article Filters and Inputs

- Keep only the first occurrence of a syndicated story cluster. Use exact-text hashes, near-duplicate embeddings, source metadata, and a first-seen timestamp.
- Exclude or separately model price recaps such as "shares rose/fell", "stock was up/down", and stories whose primary fact is a same-day price move.
- Separate analyst-rating notes, earnings recaps, scheduled event previews, and automated templated stories. They can carry predictability, but they are different mechanisms and inflate a pooled score.
- Start with headline plus one or two lead sentences. Headlines are cheapest and were sufficient for the GPT working-paper design; full text produced the better academic dictionary and supervised-text evidence but carries more stale context, duplicate content, and processing cost.
- There is no verified peer-reviewed S&P 100 head-to-head comparison of headline, summary, and full text after identical filters and costs. Treat input length as a preregistered ablation, not an assumption.
- For the local LLM, score direction, materiality, novelty, event type, and whether the story reports a price move. Use deterministic decoding, record prompt and model hashes, and store the raw response before the target return occurs.

### Look-Ahead and Memorization Rules

1. A local LLM released after a historical article cannot be used to claim a clean backtest on that article unless the model's complete training corpus is shown to exclude it. A nominal knowledge cutoff is weaker than corpus proof.
2. For closed models, treat pre-release historical evaluation as contaminated by default. Run a prospective shadow test after the model release date.
3. For FinBERT or other pretrained encoders, document the pretraining corpus and cutoff. If Reuters or the same article archive may be in pretraining, label the backtest contaminated or uncertain.
4. Freeze model version, quantization, tokenizer, prompt, decoding temperature, system instructions, and score mapping before the holdout. Do not rescore history with a newer model.
5. Train thresholds, deduplication, and filters only in an earlier development period; keep the final test window untouched. Require the news recorder's first-seen timestamp, not a retrospective publication date.

### Current Decision

Implement a FinBERT-style score first as a low-cost, frozen baseline, but treat 3 to 8 bp as the realistic one-day S&P 100 effect range rather than expecting headline-strategy returns from broad long-short studies. Make next-day market-adjusted return the primary research target and five-day cumulative return the secondary target. Use the LLM only as a prospective or demonstrably post-cutoff experiment, with memorization controls treated as a gating requirement.

### Open Questions

1. What fraction of the recorder's S&P 100 articles are first reports versus syndications, recaps, analyst notes, earnings, or templates?
2. Does the first-seen timestamp permit a clean after-close cutoff for every source?
3. What is the actual 2019-2024 S&P 100 raw and market-adjusted return dispersion by horizon in the project data?
4. How much of the FinBERT effect remains after prior return, abnormal volume, sector return, and earnings controls?
5. Does materiality classification improve a frozen dictionary or FinBERT signal without reducing usable stock-days below a practical power threshold?
6. Can a local LLM be evaluated only prospectively, with immutable model and prompt artifacts, for at least one full year?

## R04 - 2026-09-16 - Preregistered Alpha Test Protocol

Status: Active statistical protocol, subject to final software-generated sequential boundaries and empirical dependence estimates.

### Research Question

Is the proposed test statistically sound for a long-only S&P 100 swing portfolio with variable market exposure, overlapping 2-15 trading-day positions, about 50 trades per year, daily marked-to-market returns including cash, an alpha regression against SPY, Newey-West standard errors with 15 lags, a Deflated Sharpe Ratio threshold, a historical holdout, and three live interim looks?

### Answer Summary

The plan has good instincts but is not statistically coherent as written.

1. A 15-lag Newey-West covariance is a reasonable sensitivity check, not a sufficient primary justification. Daily marked-to-market portfolio returns are not automatically a 15-period overlapping-return process merely because individual trades can last 15 days.
2. The proposed sequential alpha allocation is incomplete. A historical one-sided 1.96 test spends 2.5% alpha, and three one-sided 2.39 forward tests spend approximately another 2.5%; together the familywise error is approximately 5%, not 2.5%.
3. Twelve, 24, and 36 months have very low power for annual alpha of 2-6% at 8-15% tracking error. A live result over that horizon can monitor implementation and sign, but cannot reliably confirm a modest alpha.
4. DSR is not computable as a formal single number when the number and dispersion of historical trial Sharpes are unknown. Counting unknown variants without a defensible trial-Sharpe dispersion does not solve the problem.
5. A t-test of factor alpha and DSR are complementary only when they answer different questions. If DSR is applied to the same market-adjusted residual-return series, it is largely a second expression of significance plus a multiple-testing penalty.

Confidence:

- High: the current sequential accounting and power expectations need revision.
- High: a 150-trade floor is not a substitute for daily-return alpha power.
- Medium: an automatic HAC bandwidth plus stationary-bootstrap sensitivity is the most defensible practical inference stack for this project.

### Recommended Protocol

#### Stage 0: Discovery Ledger and Freeze

- Maintain an immutable ledger of every economically distinct strategy variant, dataset choice, filter, parameter sweep, and selection rule tested before preregistration.
- Recover daily return series and Sharpe ratios for prior variants where possible. Record unknown variants separately rather than inventing their Sharpe distribution.
- Freeze the configuration, code hash, data snapshot hash, factor model, interim calendar, economic alpha threshold, and reporting template before the historical holdout is opened. Freeze the R06 conservative transaction-cost model as primary unless broker-specific calibration was completed before preregistration; retain the central R06 model as sensitivity only.

#### Stage 1: One Historical Holdout Gate

- Use the untouched historical window once only. Report alpha, standard error, confidence interval, factor exposures, turnover, costs, drawdown, and residual-return Sharpe.
- Use a one-sided alpha of 2.5% as a high-evidence gate only if the holdout was never inspected or used for model selection.
- Do not treat the historical simulation as the first interim look in a live group-sequential experiment unless return construction, execution, data availability, and factor model are demonstrably identical.
- Require a positive economic alpha and sign consistency, but recognize that a historical pass is evidence, not a prospective replication.

#### Stage 2: Forward Replication With Alpha Spending

- Start a separate live sequential test with looks at 12, 24, and 36 months, based on cumulative live returns only.
- Use a one-sided 2.5% Lan-DeMets O'Brien-Fleming alpha-spending design. Define information fraction as cumulative eligible live trading days divided by the planned 756 eligible trading days at the 36-month final analysis. Do not preregister hand-calculated critical values. Generate exact efficacy boundaries and cumulative alpha spending with a named, version-pinned group-sequential package and archive its input and output.
- A boundary is a declaration-of-success rule at that look. Failing to cross an early boundary means continue; it does not mean fail at every interim look.
- Add a nonbinding futility rule: stop or pause if conditional power under the preregistered minimum economic alpha is below 10%. Nonbinding futility does not inflate the type-I error of the efficacy boundary.
- O'Brien-Fleming spends little alpha early and is preferable when early data are weak and the final look matters. Pocock has near-constant, lower early hurdles but gives up more final-look power. Lan-DeMets permits the actual look dates to move while preserving the intended spending function.

Method sources: O'Brien and Fleming (1979), https://doi.org/10.2307/2530243 ; Pocock (1977), https://doi.org/10.1093/biomet/64.2.191 ; Lan and DeMets (1983), https://doi.org/10.1093/biomet/70.3.659

### Alpha Model and Standard Errors

#### Primary Alpha Estimand

Use the daily equity-curve excess return, including zero-risk cash return on uninvested capital. Estimate both:

1. Static benchmark model:

r_p,t - r_f,t = alpha + beta_m (r_SPY,t - r_f,t) + epsilon_t

2. Exposure-matched active return:

a_t = (r_p,t - r_f,t) - b_t ((r_SPY,t - r_f,t))

a_t = alpha + epsilon_t

where r_SPY,t - r_f,t is explicitly the market excess return and b_t is the portfolio's ex ante market beta computed from prior-day weights and rolling stock betas. Because b_t is estimated, report sensitivity to beta-window choice and a block bootstrap that re-estimates beta inside each resample.

Report the static model as a simple benchmark and use the exposure-matched active-return mean as primary only if b_t is fully computable before return t. Otherwise, use an explicit cash-plus-SPY benchmark with prior-day weights. Do not estimate beta using same-day information.

#### Factor Sensitivity

- Primary claim: market alpha, because it maps directly to the stated SPY benchmark.
- Secondary sensitivity: Fama-French five factors plus momentum. Add short-term reversal exposure as a diagnostic because the strategy buys pullbacks.
- Do not search for the factor set that maximizes alpha. Predeclare the factor table and report alpha under every listed model.
- Dynamic beta or regime interactions may be reported only when based on predeclared, lagged exposure variables.

Factor source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

#### Dependence-Robust Inference

- Primary p-value and confidence interval: Bartlett-kernel Newey-West using L = floor(4 x (T / 100)^(2/9)) lags, capped at 20, implemented with a version-pinned function and small-sample correction. Record T, L, package, function, and version in the preregistration output.
- Required sensitivity only: Bartlett Newey-West lags 5, 10, 15, and 20. Keep 15 because it matches the maximum intended holding period, but never select the most favorable result.
- Required sensitivity only: stationary bootstrap of the joint daily vector of portfolio return, SPY return, and factor returns; use at least 10,000 draws. Estimate expected block length automatically, then report fixed sensitivity at 10, 15, 20, and 30 trading sessions.
- Circular block bootstrap with the same block-length sensitivity is an acceptable secondary check.
- Hansen-Hodrick is natural for a literal H-period overlapping return with a fixed horizon, where H-1 lags follow from construction. It is not the preferred primary estimator for this daily marked-to-market portfolio because exposure, entry, exit, and cash vary daily.
- Small samples remain difficult. HAC and bootstrap are asymptotic tools; agreement among automatic HAC, fixed-lag HAC, and block bootstrap is more credible than one estimator alone.

Method sources: Newey and West (1994), https://doi.org/10.2307/2297912 ; Andrews (1991), https://doi.org/10.2307/2938229 ; Hansen and Hodrick (1980), https://doi.org/10.1086/260910 ; Politis and Romano (1994), https://doi.org/10.1080/01621459.1994.10476870

### Deflated Sharpe Ratio

Let SR_hat be the Sharpe ratio at the return sampling frequency, n the number of returns, g3 sample skewness, g4 raw kurtosis, and SR_0 the multiple-testing benchmark. The Probabilistic Sharpe Ratio is:

PSR(SR_0) = Phi( ((SR_hat - SR_0) sqrt(n-1)) / sqrt(1 - g3 SR_hat + ((g4 - 1) / 4) SR_hat^2) )

The Deflated Sharpe Ratio is DSR = PSR(SR_0), where an extreme-value approximation for N effectively independent trials is:

SR_0 = sigma_SR [ (1 - gamma_E) Phi^-1(1 - 1/N) + gamma_E Phi^-1(1 - 1/(N e)) ]

Here sigma_SR is the cross-trial standard deviation of Sharpe ratios, gamma_E is the Euler-Mascheroni constant, and all Sharpe ratios must use the same sampling frequency. DSR requires N, sigma_SR, n, skewness, and raw kurtosis. It does not remove the need to handle serial dependence; for autocorrelated daily returns, report DSR using a conservative effective sample-size sensitivity or a block-bootstrap companion analysis.

If earlier trial Sharpe ratios are unknown, formal DSR is unidentified. Recommended treatment:

1. Reconstruct prior daily return series where possible and calculate N_eff and sigma_SR from them.
2. If reconstruction fails, report a DSR sensitivity grid, not a single DSR: N equal to known trials and known-plus-unknown trials; annualized sigma_SR values 0.25, 0.50, and 1.00; and a conservative low-correlation versus high-correlation N_eff scenario.
3. Do not claim DSR >= 0.95 unless it holds throughout the preregistered conservative scenario set.
4. Use DSR as a discovery-selection audit. Do not require it as an additional live alpha gate unless it is explicitly applied to residual returns and its effective-sample treatment is preregistered.

Minimum track-record length for target probability level 1-alpha is:

MinTRL = 1 + (1 - g3 SR_hat + ((g4 - 1) / 4) SR_hat^2) [ z_(1-alpha) / (SR_hat - SR_0) ]^2

DSR and MinTRL source: Bailey and Lopez de Prado (2014), https://doi.org/10.3905/jpm.2014.40.5.094

### Power and Worked Example

Assume annual alpha A = 3%, annual tracking error TE = 10%, 252 trading days per year, and approximately independent daily residual returns for the simple power illustration. The annual information ratio is A / TE = 0.30. The expected alpha t-statistic after Y years is approximately:

E[t_alpha] = (A / TE) sqrt(Y)

| Look | Live Years | Expected t for 3% Alpha and 10% TE | O'Brien-Fleming Approximate Boundary | Interpretation |
|---|---:|---:|---:|---|
| 12 months | 1 | 0.30 | Pending software generation | Far below any plausible early success threshold |
| 24 months | 2 | 0.42 | Pending software generation | Far below any plausible interim success threshold |
| 36 months | 3 | 0.52 | Pending software generation | Far below the fixed-design 1.96 reference; use the generated sequential boundary |

For 80% power with one-sided alpha 2.5%, a simple annualized approximation is:

Y = (z_0.975 + z_0.80)^2 (TE / A)^2 = 7.85 (TE / A)^2

At TE = 10%, required years are approximately 196 for 2% alpha, 87 for 3% alpha, 49 for 4% alpha, and 22 for 6% alpha. These are not forecasts of the strategy's future; they show that a 12-36 month live test cannot statistically prove a modest alpha at ordinary tracking error.

DSR example:

- Daily Sharpe corresponding to 3% annual alpha and 10% annual TE: 0.03 / (0.10 sqrt(252)) = 0.0189.
- With no multiple-testing penalty, normal residuals, and n equal to 252, 504, and 756 daily observations, DSR is approximately Phi(0.30), Phi(0.42), and Phi(0.52), or 0.62, 0.66, and 0.70.
- With 100 effective trials and annualized cross-trial Sharpe standard deviation 0.25, the extreme-value benchmark is approximately annualized SR_0 = 0.63. The corresponding DSRs are approximately 0.37, 0.32, and 0.28 because the expected annualized Sharpe of 0.30 is below the multiple-testing hurdle.
- This example demonstrates why a DSR >= 0.95 cannot be evaluated honestly without a defensible trial distribution. It also shows that a true but modest alpha will not pass that DSR threshold within three years when prior experimentation is substantial.

The tracking-error range for a concentrated long-only swing portfolio should be estimated from the actual daily equity curve. Use 8%, 10%, and 15% annual TE as preregistered power-sensitivity scenarios rather than claiming a universal typical value.

### Trade Count, DSR, and PBO

- Keep 150 closed trades as a minimum implementation-quality floor: it gives useful information about fill behavior, stops, targets, slippage, and trade-level tails.
- Do not use 150 trades as the statistical alpha floor. The alpha test is based on daily portfolio returns including cash, and overlapping trades are not independent observations.
- Alpha t-statistic and DSR are complementary when alpha tests factor-adjusted economic performance and DSR audits discovery multiplicity. They are largely redundant when both are applied to the same residual return stream as a threshold for the same claim.
- Probability of Backtest Overfitting is meaningful only when there is a collection of competing configurations and an in-sample selection event. With one frozen configuration, PBO or CSCV is degenerate and adds no information.
- For future challenger models, retain all challenger daily return series. Then use combinatorially symmetric cross-validation to estimate PBO and report the probability that the selected in-sample winner is below the median out of sample.

PBO source: Bailey, Borwein, Lopez de Prado, and Zhu (2017), https://doi.org/10.21314/JCF.2017.320

### Purging and Embargo for Future Challengers

For labels that can end up to 15 trading sessions after observation t:

- Store each label interval [t_start, t_end], where t_end is the actual trade exit date or the maximum 15-session horizon when actual exit is path-dependent.
- Purge every training observation whose label interval overlaps any validation label interval.
- Apply a 15-trading-session embargo after each validation block when training observations can appear on both sides of the test block. Use 16 sessions if the label convention includes both endpoints.
- In strictly expanding walk-forward evaluation, train only on earlier data and insert a 15-session gap between the last training label end and the first validation start. Group all stocks on the same date into the same fold to prevent market-event leakage across cross-sectional rows.
- Tune model and filter parameters only in earlier folds. Keep the final holdout and forward data untouched.

Purging and embargo source: https://doi.org/10.21314/JCF.2017.320

### Ranked Changes to the Original Plan

1. Separate the one-time historical holdout from the live sequential test. Do not call the historical result an unbudgeted first interim look.
2. Replace the forward Bonferroni rule with a preregistered one-sided 2.5% Lan-DeMets O'Brien-Fleming spending plan and a nonbinding futility rule.
3. Replace fixed Newey-West 15 as primary with automatic HAC plus fixed-lag and stationary-bootstrap sensitivity. Keep 15 only as a disclosed sensitivity.
4. Make the exposure-matched market alpha the primary estimand, because cash allocation and beta vary over time. Report static-SPY and factor-model sensitivity tables.
5. Convert DSR from an absolute pass gate into a documented multiplicity sensitivity audit. Recover old trial returns or report conservative N_eff and sigma_SR grids.
6. State explicitly that 12-36 live months assess execution, sign, and replication, not conclusive proof of 2-6% alpha.
7. Retain 150 closed trades as an implementation floor, not a power calculation.
8. Do not calculate PBO for one frozen configuration. Use it only for a future challenger-model library with preserved return series.
9. For any future 15-day labels, require purging plus a 15-trading-session embargo and date-grouped folds.

### Current Decision

Adopt a two-stage protocol: a one-time historical holdout with a 2.5% one-sided alpha test and a separate 36-month live Lan-DeMets O'Brien-Fleming replication. Report economic alpha, exposure-matched market alpha, static-SPY alpha, factor sensitivities, automatic and fixed-lag HAC, and stationary-bootstrap inference. Treat DSR as a conservative discovery audit whose answer is conditional on a fully documented trial ledger and sensitivity grid.

### Open Questions

1. What is the actual historical holdout duration and whether can its return construction be made identical to live returns?
2. What minimum economic alpha is justified after taxes, costs, time, and capital constraints?
3. Can all earlier strategy variants be reconstructed into a trial ledger with daily residual-return series?
4. What are the actual 8%, 10%, and 15% tracking-error scenario results for the frozen equity curve?
5. Are rolling individual-stock betas available before each day to construct the exposure-matched benchmark?

## R05 - 2026-09-16 - Honest Simulation of Alpaca-Style Bracket Orders

Status: Active conservative simulator specification; unresolved broker semantics are controlled by bounds and R11 verification.

### Research Question

Which rules produce conservative daily-bar simulation for next-session buy-limit entries, broker-held stop-loss and take-profit brackets, and a 15th-trading-day time exit in liquid S&P 100 stocks? How should daily ambiguity, gaps, corporate actions, and Alpaca-specific behavior be handled?

### Answer Summary

Daily bars cannot establish queue position, partial-fill path, first trade at a price, or the order in which multiple intraday barriers were crossed. A trustworthy daily-bar simulator must choose rules that lose the benefit of doubt: strict trade-through instead of touch fills, no assumed partial fills, stop-first whenever intraday sequence remains ambiguous, conservative stop-market gap execution, and explicit corporate-action handling on unadjusted order prices.

Minute bars resolve only events occurring in different minutes. If entry, stop, and target all remain possible within one minute, retain the conservative daily rule. Quote or trade data are required to model stop triggers and queue priority faithfully.

### Alpaca-Specific Facts

- Alpaca bracket order entry may be a market or limit order. The take-profit leg is a limit order. The stop-loss leg is a stop order or stop-limit order. Source: https://docs.alpaca.markets/docs/trading/orders/#bracket-orders
- Bracket time-in-force is limited to day or gtc and bracket orders are not supported in extended hours. Source: https://docs.alpaca.markets/docs/trading/orders/#bracket-orders
- Alpaca documents adjustment of the paired stop when a take-profit exit partially fills. `[UNVERIFIED]` Public documentation reviewed did not conclusively establish protection behavior while the parent entry itself is only partially filled. Source: https://docs.alpaca.markets/docs/trading/orders/#bracket-orders
- Alpaca documents bracket exit legs as one-cancels-other behavior. Cancellation or fill of one relevant leg cancels the other open leg. Source: https://docs.alpaca.markets/docs/trading/orders/#bracket-orders
- Alpaca stop orders are triggered by a valid last trade; current quotes are used for stop-price validation at submission. A stop order converts to a market order when triggered. A stop-limit converts to a limit order. Source: https://docs.alpaca.markets/docs/trading/orders/
- Alpaca documents bracket orders as Do Not Reduce and Do Not Cancel. Cash-dividend order-price reduction is therefore not automatic. Public documentation did not verify exact split price and quantity processing for every order state; validate this in a paper account. Source: https://docs.alpaca.markets/docs/trading/orders/#bracket-orders
- Alpaca supports cls market-on-close and limit-on-close equity orders, but cls is not bracket TIF. Model a 15th-day close exit as cancel-confirm-bracket then submit a separate cls order before the exchange cutoff; otherwise it is not an exact close execution. Source: https://docs.alpaca.markets/docs/trading/orders/
- Public Alpaca documentation was not found to specify an exact bracket-order execution sequence through a trading halt. Simulate no execution during the halt and a new gap scenario on the first valid post-resumption trade, then validate against paper or live records.

### Spec-Ready Conservative Rules

1. Define every entry, stop, target, and time-exit price on raw, unadjusted prices known at the prior regular-session close.
2. Submit one buy-limit entry for the next regular session only; do not simulate extended-hours fills for an Alpaca bracket order.
3. If next-session open is below or equal to the resting buy limit, classify the order as opening-auction eligible; fill at the limit price, not the favorable opening-auction price, only when the strategy explicitly models auction participation. Otherwise mark it unfilled and report an auction-sensitivity variant.
4. If open is above the buy limit, require strict trade-through: fill only when intraday low is strictly below the buy limit. A low exactly equal to the limit is not a fill in the conservative daily model.
5. For a strict trade-through entry, fill at the limit price, not at the lower daily low. This gives no price improvement while avoiding an impossible worse-than-limit price.
6. Assume all-or-none entry fills in daily data. If full quantity cannot be justified by intraday volume and queue data, record no trade rather than a favorable partial fill.
7. `[PRIOR]` In the conservative daily simulator, treat a partially filled parent as unprotected unless nested broker-order evidence demonstrates otherwise. Do not present this simulation assumption as verified Alpaca behavior.
8. For a sell target, require strict trade-through: high strictly above target. Fill at target, not at a favorable higher open or high.
9. For a sell stop-market, trigger only when a valid trade is at or below the stop. With daily bars, use low less than or equal to stop as a trigger proxy.
10. If an intraday sell stop triggers without an opening gap, fill at stop minus an adverse execution buffer equal to the larger of one tick and a predeclared estimated half-spread. Replace the buffer with empirically calibrated Alpaca paper or live slippage when available.
11. If open is below the stop, treat the sell stop-market as a gap: fill at open minus the same adverse buffer, never at the stop price.
12. If a sell stop-limit triggers, convert it to a sell limit at the stop-limit price. If price gaps or continues below that limit, leave the position open until a later eligible fill or the time exit. Do not assume a protective stop-limit is filled.
13. If open is above the target, fill the pre-existing target limit at target in the conservative model; report a separate opening-auction price-improvement sensitivity only if actual broker fills support it.
14. If both target and stop are reachable after entry within one daily bar, apply stop-first. This is a deliberate lower-bound convention, not a claim about actual order sequence.
15. If entry and stop are both reachable in a daily bar, use minute bars when available. If sequence remains unknown, assume entry then stop only when strict price traversal implies it; otherwise reject the trade as ambiguous and report it separately.
16. If entry, target, and stop are reachable in one minute, apply the same stop-first convention. Minute bars do not establish event order inside a minute.
17. Use official exchange trading sessions. Count 15 trading sessions, not calendar days. Treat holidays as no session and half-days as their actual shortened session.
18. On the 15th trading session, cancel confirmed open bracket legs and submit a separate market-on-close order before the applicable cutoff. If the cancellation or cutoff condition is not met, exit at the next executable regular-session price and flag the exception.
19. Do not assume a daily close fill for a close exit unless a modeled cls/MOC order was eligible and submitted by the correct cutoff.
20. Apply splits to share quantity and raw order prices only according to a validated broker rule. Until Alpaca split handling is verified, cancel and reissue open orders after the split using the adjusted quantity and raw-price ratio; flag the trade.
21. Do not reduce Alpaca bracket nominal prices for ordinary cash dividends because Alpaca documents DNR handling. Exclude or separately analyze ex-dividend sessions because the price drop can mechanically activate a stop.
22. For special dividends, spin-offs, mergers, symbol changes, delistings, or halts, suppress new entries from the prior session through resolution unless a validated event-specific rule exists.
23. Use point-in-time constituent membership and unadjusted corporate-action records. Never determine historical eligibility from today's ticker, current index member list, or fully revised adjusted price alone.
24. Compute the signal only after the actual final close is available. A limit price based on that close may first be active next session; never fill it on the signal bar.
25. Record every simulator decision: order timestamp, raw prices, adjustment mode, fill convention, ambiguity flag, corporate-action flag, gap flag, and minute-data availability.

### Bias Evidence and Measurement

| Bias | Evidence or Conservative Estimate | How to Quantify in This Strategy | Source |
|---|---|---|---|
| Touch versus strict trade-through | No current universal S&P 100 fill rate was verified. In 1990-1991 NYSE SuperDOT data, small at-quote buy limits filled about 48-68% depending on spread; market orders were near 100%. This is historical calibration, not a current forecast. | Report fraction of candidate entries with low equal to limit versus low below limit and compare PnL under both rules. | Harris and Hasbrouck (1996), https://doi.org/10.1111/j.1540-6261.1996.tb04074.x |
| Passive-limit adverse selection | Finnish individual limit-order buys lost 51 bp the following day while market-order buys gained 44 bp in one study. This is not U.S. mega-cap evidence, but establishes direction and possible materiality. | Compare next-day and 5-day returns of strict filled, touch-only, and unfilled candidate entries. | Linnainmaa (2010), https://doi.org/10.1111/j.1540-6261.2010.01582.x |
| Same-bar target-first convention | No universal bp estimate exists. Optimism per ambiguous trade equals target return minus stop return, multiplied by ambiguous-trade frequency. | Report ambiguity rate and total PnL difference between target-first, stop-first, and minute-resolved outcomes. | Simulator-specific calculation |
| Stop gap fill at stop | No universal bp estimate exists because it depends on gaps, liquidity, halts, and stop type. Stop-market can execute below the trigger after activation. | Report gap-stop frequency and mean/open-to-stop shortfall; use first-minute data where available. | Alpaca orders documentation, https://docs.alpaca.markets/docs/trading/orders/ |
| Stop-limit treated as stop-market | Potentially unbounded tail bias because a triggered stop-limit can remain unfilled during a continuing decline. | Compare outcomes under actual stop-limit persistence versus forced stop-market liquidation. | Alpaca orders documentation, https://docs.alpaca.markets/docs/trading/orders/ |
| Close-exit at daily close | Exact close execution is optimistic without an eligible MOC/LOC workflow and cutoff compliance. | Compare cls/MOC modeled result with next-session exit and actual broker fills. | Alpaca orders documentation, https://docs.alpaca.markets/docs/trading/orders/ |
| Adjusted-price stops | Can create artificial stop/target placement around splits and dividends; no universal bp estimate. | Recompute all levels from raw prices and reconcile every corporate-action date. | Alpaca DNR/DNC documentation, https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |

### Validation Protocol

1. Run the simulator in shadow mode beside Alpaca paper trading with identical order timestamps, symbols, quantities, brackets, and TIF values.
2. Preserve Alpaca order IDs, status transitions, partial fills, fill timestamps, fill prices, canceled orders, and corporate-action notices.
3. Compare entry fill rate, entry slippage, stop-gap shortfall, target price improvement, partial-fill rate, time-exit difference, and ambiguous-bar frequency by stock, volatility quintile, and gap regime.
4. Calibrate the adverse execution buffer only from prior paper or live observations, never from the future validation period.
5. Use recent minute bars to reconcile every daily-bar ambiguity. When minute bars and actual fills disagree, retain the broker fill as truth and investigate timestamps, auction participation, and last-trade versus quote triggers.
6. Publish base, optimistic, and conservative simulation results. The conservative specification above is the decision specification; the others are diagnostic bounds.

### Current Decision

Use strict trade-through, all-or-none fills, stop-first unresolved ambiguity, raw-price order levels, gap fills at open less an adverse buffer, and actual MOC workflow for the daily baseline. Treat any result that requires touch fills, target-first ambiguity, stop-at-trigger fills, or same-day-close entries as optimistic sensitivity only.

### Open Questions

1. Do Alpaca paper fills for overnight resting buy limits participate in the opening auction as assumed by the auction-eligible sensitivity?
2. What is the actual Alpaca split adjustment for GTC bracket prices and quantities in every relevant order state?
3. What fill, partial-fill, and gap-stop statistics appear in a 6-12 month paper-trading shadow record for the intended order sizes?
4. What fraction of candidate trades are touch-only, same-bar ambiguous, gap-stop, and corporate-action affected?
5. Does first-minute trade data resolve enough daily ambiguity to justify its acquisition for recent years?

## R06 - 2026-09-16 - Time-Varying Transaction Cost Model

Status: Active planning model; numerical spread, impact, and commission priors require empirical calibration.

### Research Question

What transaction-cost model is realistic for small, long-only S&P 100 swing trades of roughly USD 1,000 to USD 50,000 through Alpaca, with historical simulation from 2000 to 2026 and current expected execution?

### Answer Summary

Explicit commissions and regulatory charges are small. The relevant sources of uncertainty are spread, marketable-exit slippage, passive-limit fill selection, opening and halt gaps, and historical market structure. A cost model that applies only zero commissions plus a fixed few basis points is incomplete; a model that separately adds adverse-selection bps after correctly conditioning on actual passive fills double counts the effect.

Use actual dated regulatory fees; a daily spread proxy or NBBO where available; exit-type-specific slippage; and scenario analysis for historical commissions. Treat 2000-2001 decimalization as a market-structure break. A modern Alpaca zero-commission simulation before Alpaca existed is a modern-execution counterfactual, not a historical retail-feasibility backtest.

### Parameter Table

All current fees and public disclosures below were checked on 2026-09-16.

| Component | Current Value | Historical Treatment | Backtest Rule | Primary Source |
|---|---:|---|---|---|
| Alpaca U.S.-listed stock commission | USD 0 per share trade | Alpaca did not exist for much of 2000-2018. Run modern-zero-commission and historical-retail commission sensitivity separately. | Central current model: zero. Historical feasibility sensitivity: USD 5 and USD 10 per executed order. | https://alpaca.markets/pricing ; https://alpaca.markets/disclosures |
| SEC Section 31 fee | USD 20.60 per USD 1,000,000 of sale principal, effective 2026-04-04; 0.206 bp of sale value | Apply the exact effective-date rate from SEC advisories to every historical sale. Do not use an annual average. The rate was zero from 2025-05-14 until the 2026 increase. | Fee_sell_sec = sale_notional x rate_date / 1,000,000. Apply actual rounding only after daily fee aggregation when reproducing broker statements. | https://www.sec.gov/divisions/marketreg/mrfee.shtml |
| FINRA Trading Activity Fee | USD 0.000195 per share sold, maximum USD 9.79 per trade in 2026 | Set zero before 2002-10-01. Apply dated FINRA schedules after inception; for example, 2004-2011 was USD 0.000075 per share and 2024-2025 was USD 0.000166. | Fee_sell_taf = min(shares_sold x taf_rate_date, taf_cap_date). | https://www.finra.org/rules-guidance/rulebooks/finra-rules/7730 ; FINRA regulatory notices |
| CAT fee | USD 0.000003 per executed equivalent share, both buys and sells | Set zero until a verified Alpaca or executing-broker CAT pass-through schedule applies. Public historical retail pass-through dates were not verified. | Fee_cat = shares_bought_or_sold x cat_rate_date. Economically negligible at these sizes. | https://alpaca.markets/disclosures |
| Current large-cap spread | No verified single S&P 100 aggregate. Liquid large caps are commonly tick-constrained; spreads follow an intraday U-shape. | Estimate daily full spread from NBBO/TAQ if available. With only OHLC, estimate both Corwin-Schultz and Abdi-Ranaldo. | Central full-spread proxy = max(tick floor, median(Corwin-Schultz, Abdi-Ranaldo)); conservative = max(tick floor, larger estimator). | https://doi.org/10.1111/j.1540-6261.2012.01729.x ; https://doi.org/10.1093/rfs/hhx084 |
| Time-of-day spread multiplier | Model prior, not a verified universal S&P 100 fact | Estimate from recent minute NBBO or actual fills by open, midday, and close bucket. | Central multipliers: open 1.5, regular 1.0, close 1.25. Conservative: open 3.0, regular 1.5, close 2.0. | Calibrate from own Alpaca and quote data |
| Passive buy-limit entry | No commission and no guaranteed price improvement | Historical daily bars cannot establish queue position. | Use strict trade-through/no-touch fill; do not separately add adverse-selection bps after using realized post-fill returns. | https://doi.org/10.1111/j.1540-6261.1996.tb04074.x ; https://doi.org/10.1111/j.1540-6261.2010.01582.x |
| Target limit exit | Passive sell limit | Same queue limitation as entry. | Strict trade-through; fill at target, no favorable price improvement. | Alpaca order documentation |
| Time or marketable exit | Half-spread plus small execution loss | Use time-varying spread proxy. | Central: 0.5 x full spread + 0.25 bp. Conservative: 0.5 x full spread + 1.0 bp. | Calibrate with own fills |
| Stop-market exit | Half-spread, execution loss, and gap risk | Use exact gap from raw open versus stop; do not use close-to-close proxy. | Central non-gap: 0.5 x full spread + 0.5 bp. Conservative non-gap: 0.5 x full spread + 2.0 bp. Gap: add raw stop-to-open shortfall plus same buffer. | https://docs.alpaca.markets/docs/trading/orders/ |
| Market impact | Likely small for USD 1,000-50,000 in most S&P 100 names, but verify participation rate | Use participation-based model, not a fixed universal bps charge. | `[PRIOR]` Central: 0.25 bp per marketable side when order notional is at most 0.01% of daily dollar volume; conservative: 1 bp. Escalate when participation is larger or liquidity is stressed. | Practitioner benchmark: https://doi.org/10.2139/ssrn.3229719 |

### Historical Spread and Fee Rules

- Decimalization completed in April 2001 and materially reduced quoted and effective spreads. Do not apply a post-decimal fixed spread to the 2000 to early-2001 sample. Source: https://www.sec.gov/spotlight/decimal.htm
- Regulation NMS standardized the USD 0.01 minimum increment for most stocks priced at or above USD 1; highly liquid stocks can remain tick-constrained. Source: https://www.sec.gov/rules/final/34-51808.pdf
- Corwin-Schultz uses adjacent daily high-low ranges to estimate a full spread proxy. Abdi-Ranaldo uses close, high, and low and has lower prediction error in many comparisons. Both are proxies, not observed NBBO or effective execution spread. Source: https://doi.org/10.1111/j.1540-6261.2012.01729.x ; https://doi.org/10.1093/rfs/hhx084
- Smooth daily estimators with a trailing 21-session median for production cost inputs, but retain unsmoothed values for sensitivity. Set negative estimates to zero before applying the tick floor.
- When minute NBBO exists, compute quoted spread = ask minus bid over midpoint and effective spread = 2 x absolute(fill price minus prevailing midpoint) over midpoint. Use actual order timestamps.
- Do not infer Alpaca-specific price improvement from Rule 606. Rule 606 describes order routing and routing relationships; Rule 605 is execution-quality reporting by market centers, not a broker-specific guarantee. Alpaca Rule 606 disclosures: https://alpaca.markets/disclosures

### Recommended Cost Formula

For each trade, calculate costs in dollars and divide by entry notional only when reporting basis points:

Cost_trade = commission_buy + commission_sell + fee_CAT_buy + fee_CAT_sell + fee_SEC_sell + fee_TAF_sell + execution_entry + execution_exit + gap_shortfall

Execution rules:

- Passive entry and target: model the conditional fill rule first. If strict trade-through fills are used with subsequent historical returns, do not add a generic adverse-selection penalty because the unfavorable continuation is already in the realized path.
- Marketable time exit: execution_exit = 0.5 x spread_estimate_at_exit + market_impact_setting.
- Stop-market non-gap: execution_exit = 0.5 x spread_estimate_at_stop + stop_buffer.
- Stop-market gap: gap_shortfall = max(0, stop_price - first_tradable_price); then add the normal stop execution term.
- Stop-limit: do not substitute a market fill; model its possible non-execution separately.

Central current routine round-trip expectation, excluding realized gaps and conditional fill selection: about 2 to 6 bp for a strict passive entry plus passive target or ordinary marketable time exit. Conservative routine expectation: about 6 to 15 bp. These are model settings, not measured Alpaca averages, and must be replaced with paper or live calibration.

### Explicit-Fee Scale

At USD 50,000 sold, the current Section 31 fee is about USD 1.03, or 0.206 bp. For a USD 100 stock, selling 500 shares incurs about USD 0.10 of TAF and USD 0.002 of CAT per side. These explicit charges are smaller than a one-basis-point spread or slippage error.

At low-priced stocks or small notional trades, penny rounding can make explicit fees proportionally larger. Reproduce Alpaca's daily aggregation and rounding when matching account statements.

### Order Routing, Price Improvement, and Impact

- Alpaca publishes Rule 606 routing disclosures and offers customers order-routing detail requests. Use them for venue awareness, not execution-cost assumptions. Source: https://alpaca.markets/disclosures
- No Alpaca-specific public Rule 605 execution-quality table was verified. Obtain price-improvement and effective-spread estimates from the account's own paper or live fills against contemporaneous NBBO.
- Small S&P 100 orders are normally too small to create meaningful mechanical market impact when participation is tiny, but impact is not the same as spread or adverse selection. Calculate order notional divided by same-day dollar ADV and flag trades above a preregistered participation threshold.
- The cited institutional large-cap implementation-shortfall estimate is not directly transferable to small retail orders; use it only as a conservative stress comparator. Source: https://doi.org/10.2139/ssrn.3229719

### Current Decision

Implement dated SEC and FINRA fees exactly, CAT only from verified broker schedules, and two separate historical commission series: modern-zero-commission counterfactual and historical-retail sensitivity. Use a daily spread proxy for long history, NBBO/effective spreads for recent calibration, strict passive-fill selection, and explicit stop-gap losses. Treat 2-6 bp routine round-trip cost as central and 6-15 bp as conservative until Alpaca paper or live fills replace the priors.

### Open Questions

1. Does Alpaca's current fee schedule pass through the 2026 Section 31 rate exactly as daily rounded charges for the intended account type?
2. What is the exact historical CAT pass-through start date and rate for Alpaca accounts?
3. What do six to twelve months of Alpaca paper fills show for effective spread, price improvement, fill probability, and stop-gap shortfall by S&P 100 name?
4. What historical commission sensitivity is most appropriate for the pre-Alpaca portion of the test?
5. How often does the strategy trade at the open, close, or during stressed liquidity when the time-of-day multipliers matter most?

## R07 - 2026-09-16 - Incremental News-Signal Test Design

Status: Active information-test design; the MDE table is a planning simulation, not a preregistered power guarantee.

### Research Question

What is the most powerful valid design for testing whether FinBERT-style sentiment and a local LLM structured score add predictive value beyond a price-based ranker, given roughly 100 S&P 100 stocks, 25,000 stock-days per year, about half with news, and a later 2-15 day swing-strategy use case?

### Answer Summary

Use two stages.

1. Information test: use every eligible stock-day, not only the ranker's candidates. The primary endpoint is one-day forward market- or sector-adjusted cross-sectional return. This creates the greatest valid power and tests whether the text contains information before portfolio-selection and execution effects.
2. Strategy test: only after the information design is frozen, test whether the score improves the ranker's actual candidate portfolio as a filter or sizing input under the same fills, costs, and holding rules.

No-news stock-days should remain in the panel with an explicit no-news indicator. They help estimate date and stock effects and distinguish the effect of receiving news from the direction or materiality of news. They do not magically double the effective sample for the text-score coefficient, whose main information comes from news-bearing stock-days.

### Stage 1: Information Test

#### Primary Panel Specification

For stock i and signal date t, define h-day forward return from the first tradable post-close point. Primary h = 1. Let N_it equal one when at least one novelty-filtered article exists before the after-close cutoff. Let F_it be the aggregated FinBERT score only when N_it = 1. Let L_it be the LLM direction times materiality score only when N_it = 1.

r_adj_i,t_to_t+h = alpha_i + delta_t + b_R R_it + b_F (N_it F_it) + b_L (N_it L_it) + b_N N_it + gamma' X_it + error_i,t

Where:

- alpha_i = stock fixed effects.
- delta_t = date fixed effects. They absorb common market and same-day macro shocks.
- R_it = frozen price-ranker score.
- X_it = prior 1-day, 5-day, 20-day, and 60-day returns; abnormal volume; realized volatility; overnight return; sector return; earnings-window indicators; analyst-action indicator; article count; unique-story count; source controls; and event-type controls.
- Primary dependent variable is beta-adjusted or sector-adjusted one-day return. Raw return is reported as secondary. With full date fixed effects, raw return plus date effects is a valid cross-sectional specification; beta-adjusted return improves interpretability when beta differs across names.

Estimate the pooled fixed-effect panel as primary. Use two-way clustering by stock and date, plus a date-block bootstrap that resamples complete cross-sections. This accommodates repeated observations by stock and shared shocks by date. Source: Petersen (2009), https://doi.org/10.1093/rfs/hhn053 ; Cameron, Gelbach, and Miller (2011), https://doi.org/10.1198/jbes.2010.07136

#### Secondary Fama-MacBeth Check

Run the same cross-sectional regression separately each date, average the daily coefficient slopes, and apply HAC to the time series of daily slopes. This is interpretable but less powerful with only about 100 names and 125-500 daily cross-sections. For h-day overlapping returns, use at least h-1 HAC lags and a block-bootstrap sensitivity. Source: Fama and MacBeth (1973), https://doi.org/10.1086/260061

#### Driscoll-Kraay

Use Driscoll-Kraay only as a 24-month sensitivity check, not the primary estimator. It is designed for cross-sectional dependence but relies on a sufficiently long time dimension; six-month daily panels are too short for confidence in its asymptotics. Source: Driscoll and Kraay (1998), https://doi.org/10.1162/003465398557825

### Horizons and Overlap

- Primary information endpoint: h = 1 trading day. It is closest to fresh news processing and has the strongest statistical power.
- Secondary confirmation endpoint: h = 2 days.
- Exploratory endpoints: h = 5 and h = 10 days. Do not infer persistence merely because overlapping-label t-statistics are large.
- For h > 1, retain daily starts for local-projection estimates but use stock and date clustering plus h-session block bootstrap. Also report non-overlapping-horizon results as a conservative robustness test.
- The strategy test can use 2-15 day realized trade returns, but its inference belongs in Stage 2 rather than the Stage 1 information claim.

### Article Aggregation and Filters

Primary aggregator, frozen before testing:

F_it = mean_j(F_ijt)
L_it = mean_j(direction_ijt x materiality_ijt)

The mean is taken over first-seen, novelty-filtered articles available by the cutoff. The FinBERT-only feature must not depend on any LLM output. A six-hour half-life recency-weighted aggregator may be reported only as a preregistered secondary sensitivity.

Apply this only to the first article in each novelty cluster. Deduplicate exact copies by text hash and near-duplicates by embedding similarity plus issuer, event, and time window. Treat source syndications as one information event.

Report but do not optimize over these secondary aggregators: unweighted mean, most recent, maximum absolute score, and novelty-weighted first report. Separate price recaps, analyst actions, earnings recaps, scheduled-event previews, and automated templates as event classes. A pooled score can otherwise rediscover contemporaneous price movement rather than forecast return.

### Nested Incremental Tests

Use identical stock-day rows, return definitions, controls, and folds for all models:

A: y = price ranker and controls
B: y = A + FinBERT feature
C: y = B + LLM structured feature

Primary coefficient tests:

- FinBERT incremental information: b_F > 0 in model B.
- LLM incremental information beyond FinBERT: b_L > 0 in model C.

Report partial in-sample R-squared but judge incremental prediction using chronological out-of-sample R-squared and forecast-encompassing tests. For nested forecast comparisons, use a Clark-West style adjustment or a date-block bootstrap of the loss differential. Source: Clark and West (2007), https://doi.org/10.1016/j.jeconom.2006.12.001 ; Campbell and Thompson (2008), https://doi.org/10.1093/rfs/hhm055

Multiple-testing rule:

- Treat h = 1 FinBERT and h = 1 LLM-incremental coefficients as two co-primary information hypotheses. Apply one-sided Holm control at family alpha 2.5% at the final analysis.
- Treat h = 2, 5, 10, alternate aggregators, and event-type interactions as secondary; control them with Holm or Romano-Wolf and label them exploratory.
- Use interim 6- and 12-month looks for data quality and nonbinding futility only. Reserve formal efficacy claims for the 24-month final look to preserve maximum final power.
- If early efficacy declarations are required, use separate Lan-DeMets O'Brien-Fleming spending for each co-primary endpoint, with the family alpha allocated before launch. This is valid but materially less powerful.

### Power Table

Status: `[PRIOR]`. This is a scenario calculation, not a preregistered guarantee. Replace the assumed correlation and return dispersion with a simulation driven by the actual panel before finalizing thresholds.

Planning assumptions, not universal facts:

- News-bearing stock-days: 12,500 per year in the whole-universe panel.
- Candidate stock-days: 1,000 per year in the ranker-only analysis.
- Average news-bearing names per date: 50. Candidate names per date: 4.
- Residual cross-stock correlation after date fixed effects: 0.05.
- Design effect for all-news rows: 1 + 49 x 0.05 = 3.45. Design effect for candidates: 1 + 3 x 0.05 = 1.15.
- One-sided 2.5% significance, 80% power, and MDE multiplier 2.80.
- Residual return SDs: 1 day = 1.5%; 2 days = 2.1%; 5 days = 3.3%; 10 days = 4.7%.

| Design and Horizon | 6 Months MDE | 12 Months MDE | 24 Months MDE | Interpretation |
|---|---:|---:|---:|---|
| Whole-universe news panel, h = 1 | 9.9 bp | 7.0 bp | 4.9 bp | Best primary design; values include cross-stock correlation assumption. |
| Ranker-candidate panel, h = 1 | 20.1 bp | 14.2 bp | 10.1 bp | Weak for detecting plausible 3-8 bp text effects. |
| Whole-universe news panel, h = 2 with overlap sensitivity | 19.6 bp | 13.8 bp | 9.8 bp | Use as secondary confirmation. |
| Whole-universe news panel, h = 5, non-overlap conservative | 48.6 bp | 34.3 bp | 24.3 bp | Too weak for a primary text-information claim. |
| Whole-universe news panel, h = 10, non-overlap conservative | 98 bp | 69 bp | 49 bp | Exploratory only at this sample size. |

The table demonstrates why testing only ranker candidates sacrifices most information-test power. It also demonstrates why one-day information should be primary even though the trading strategy holds longer.

### Stage 2: Strategy Value Test

After Stage 1 freezes the score and its aggregation rule:

1. Apply A, B, and C only to the ranker's candidate stock-days using identical entry, fill, exit, cost, and position-cap rules.
2. Test the score as a filter first: compare A against B and C with a preregistered score cutoff or top-versus-bottom candidate bucket.
3. Test sizing second: predeclare a monotonic mapping from standardized score to position weight, with gross-exposure and single-name caps unchanged.
4. Compare daily portfolio excess returns, factor alpha, turnover, fill rate, realized holding period, and stop-gap exposure using paired date-block bootstrap because all versions share the same candidate opportunities.
5. Require incremental strategy value after costs and without a deterioration in tail loss, concentration, or capacity. A statistically significant Stage 1 coefficient is not sufficient to establish portfolio value.

### Pitfalls

1. Selecting only ranker candidates for the first information test creates post-selection and low-power risk.
2. Treating no-news as sentiment zero confounds neutral content with absence of information. Use a no-news indicator and score interactions.
3. Counting several syndicated stories as independent observations inflates t-statistics.
4. Using same-day close or article timestamps reconstructed after the fact leaks information.
5. Evaluating LLM historical predictions on articles within its unknown training corpus can measure memorization, not forecasting.
6. Treating h = 5 or h = 10 overlapping labels as independent creates false precision.
7. Searching score aggregators, horizons, event filters, and thresholds without a trial ledger invalidates simple p-values.
8. Letting statistical Stage 1 success choose the Stage 2 cutoff or sizing rule leaks the information test into the strategy test.
9. Ignoring partial fills, no-fill selection, and exit costs can turn a real information signal into a non-tradable strategy claim.

### Current Decision

Use the whole-universe, one-day fixed-effect panel as the primary information test; use two-day as secondary; reserve five- and ten-day results for conservative exploratory analysis. Test FinBERT and LLM incrementally on the same rows with no-news indicators, date and stock fixed effects, two-way clustering, and a 24-month final Holm-controlled analysis. Only then test a frozen score as a filter or sizing input for the ranker's 2-15 day strategy.

### Open Questions

1. What are the actual date-clustered residual correlations and return SDs in the 2019-2024 S&P 100 dataset?
2. What percentage of stock-days have first-report, novelty-filtered news after deduplication?
3. Can BMO/AMC earnings timing be completed sufficiently to support the planned exclusion controls?
4. What predeclared score cutoff or sizing map is economically credible without Stage 2 tuning?
5. Can the local LLM be tested only prospectively or with a demonstrated training cutoff before every evaluation article?

## R08 - 2026-09-16 - Alpaca/Benzinga News Feed Reliability and Terms

Status: Active risk assessment; storage, derivative-model, and training rights remain unverified.

### Research Question

How reliable is Alpaca's Benzinga-powered News API for S&P 100 research, and what do its public terms clearly allow for a personal recorder, local archive, research use, and model training?

### Answer Summary

Alpaca News is a useful operational source for current and historical trader-oriented coverage, with documented archive access back to 2015 and structured article metadata. It is not publicly documented as a complete, versioned, publication-time-verified research database. The recorder's first-seen timestamp and saved payload hash are the strongest evidence of when the project had access to a particular version.

No public audited statistic was found for articles per S&P 100 stock-day, automated-content share, ticker-tag precision, revision frequency, revision magnitude, historical coverage by year, or historical version retention. Treat all as measurement tasks, not assumptions.

### Access and API Facts

- Alpaca News is part of the Market Data API and is powered by Benzinga. The documented archive reaches back to 2015 for stocks and crypto. Source: https://docs.alpaca.markets/docs/news-api
- Public documentation and plan material describe Basic access at 200 requests per minute and Algo Trader Plus access at 10,000 requests per minute. Confirm the account dashboard because plan limits can change. Sources: https://alpaca.markets/data ; https://docs.alpaca.markets/docs/about-market-data-api
- The article schema documents id, author, created_at, updated_at, headline, summary, content, URL, symbols, source, and images. Source: https://docs.alpaca.markets/docs/news-api
- Symbol tags are vendor metadata. No public Benzinga or Alpaca audit of tag precision, recall, multi-ticker tagging, or primary-versus-incidental symbol relevance was found.

### Data Quality Assessment

| Risk | Why It Matters | Required Mitigation |
|---|---|---|
| Archive completeness | "Since 2015" is availability, not proof of uniform coverage by stock, time, or article type. | Build a yearly by-symbol coverage matrix; compare current archive results to recorder results; publish missingness by year and ticker. |
| First-seen versus created_at | created_at is vendor metadata; first_seen is recorder-arrival time. Neither independently proves original publication time. | Store both, calculate delay = first_seen - created_at, and report median, p95, negative values, and source-specific distributions. |
| Revisions | updated_at indicates a later vendor update, but no public article-version endpoint or historical revision archive was verified. | Save raw payload, headline, summary, content, symbols, created_at, updated_at, retrieval time, and SHA-256 hash on every observation. Do not replace prior payloads. |
| Latest-version hindsight | Historical API queries may return current payloads rather than the text available at the historical created time; behavior was not verified. | Treat archive articles as latest-known unless the recorder saved the earlier payload. Run repeated historical queries for a sampled set of IDs to detect changes. |
| Multi-ticker tags | A tag can denote an incidental mention, peer, supplier, ETF holding, or market basket rather than issuer-specific news. | Require target ticker in headline or lead for the strict issuer-specific sample; retain broad-tag articles only as a separate market/sector class. |
| Automated and templated content | Benzinga publishes some articles marked as generated by its automated content engine; no overall share was verified. | Create template and automation flags from author, channel, disclaimer text, repeated phrase patterns, and content similarity. Report their share, not just filtered returns. |
| Price recaps and options activity | These can restate contemporaneous price moves or volume, producing apparent predictability that is not new information. | Remove or separately model price-move recaps, options-activity notes, technical summaries, analyst-rating summaries, and earnings previews. |
| Syndication and duplicate stories | Multiple records can describe the same event and inflate article count and standard errors. | Cluster by normalized headline, normalized body, source URL, named issuer, and semantic similarity over a preregistered window; keep the first-seen version. |
| Ticker changes | Historical symbols can differ from current symbols. | Map article symbols through a point-in-time security-identity table before joining to prices or membership. |

### Recommended Filters

1. Keep only articles first seen before the research cutoff; retain created_at and updated_at but never replace the stored version.
2. Keep one representative per novelty cluster: same normalized issuer, event class, and headline/body similarity in a trailing 24-hour window; choose earliest first_seen.
3. Primary sample: retain all point-in-time-tagged articles and include tag breadth and deterministic issuer relevance as controls. Secondary strict issuer sample: require the target ticker or issuer name in headline or lead; treat the five-tag cutoff as a preregistered sensitivity, not a data-driven exclusion.
4. Exclude or separately label price-move recaps using terms such as shares rose, shares fell, stock up, stock down, gained, lost, intraday high, and percentage move language without a new fundamental event.
5. Separate analyst-rating, price-target, options-activity, earnings-preview, earnings-recap, technical-analysis, ETF, and macro-market event types.
6. Flag automated/template content from explicit disclaimer text, recurring templates, author/channel metadata, and very high body similarity.
7. Exclude articles with created_at after the signal cutoff, future-dated metadata, missing body/headline, or unresolved symbol mappings.
8. Report each filter's retained article count, stock-day coverage, created-to-first-seen delay distribution, and incremental predictive result. Do not select filters solely because they improve return tests.

Freshness evidence: timely Dow Jones News Service stories showed stronger return predictability than Wall Street Journal stories that could summarize previously known information. Source: https://doi.org/10.1111/j.1540-6261.2008.01362.x

### Supplementary Sources

| Source | Best Use | Timestamp Meaning | Limitation and Terms |
|---|---|---|---|
| SEC EDGAR | Earnings 8-Ks, merger, filing, and issuer-event verification | EDGAR acceptance timestamp is reliable evidence of filing availability | It is not a general news feed; filing time may differ from press-release time. Fair-access rules apply. https://www.sec.gov/search-filings/edgar-application-programming-interfaces |
| Issuer investor-relations press releases | Original company announcements, earnings releases, M&A, guidance | Page or feed timestamp can be closer to original publication | Coverage and licensing differ by issuer; archive raw URL and timestamp. |
| GDELT DOC API | Discovery, independent source metadata, and GDELT first-seen cross-check | seendate is when GDELT first saw/processed the article | GDELT returns metadata and URLs, not article full text; publisher retains full-text copyright. https://blog.gdeltproject.org/gdelt-2-1-our-global-world-in-realtime/ |

### Terms: Plain-Language Assessment

Explicitly documented Alpaca clause:

"I agree not to reproduce, distribute, sell or commercially exploit the market data in any manner without written consent from Alpaca."

Source: Alpaca Account Application and Customer Agreement in the disclosure library: https://alpaca.markets/disclosures

`[UNVERIFIED]` This clause is written for market data generally. The public materials reviewed do not establish whether it is the controlling license for Benzinga news content; an Alpaca/Benzinga news addendum may impose different rights.

Practical interpretation:

- Do not share or redistribute raw Alpaca/Benzinga article text, bulk archive exports, or an API-backed service without written permission.
- The public documents reviewed do not clearly grant or deny persistent local storage of Benzinga article body, historical backtesting use, embeddings/vector databases, fine-tuning, or model training. Do not infer permission from API access.
- `[BLOCKER]` Using the feed for private, ephemeral personal research may be consistent with ordinary account use, but this was not verified as a contractual right for a retained archive or trained model. Obtain written permission before model training or retention beyond ordinary query/cache behavior.
- Training or fine-tuning a local model creates an additional licensing question because model weights or embeddings can retain content-derived information. Obtain written confirmation before doing so.
- Benzinga's public website terms are not necessarily the controlling terms for data delivered through Alpaca. The account agreement, third-party subscriber agreements incorporated by reference, and any News API addendum control.

Questions to send Alpaca in writing:

1. Does the current account plan permit persistent local storage of raw Alpaca News article headline, summary, and body for historical backtesting?
2. Does it permit local embeddings, vector indexes, feature stores, and model training or fine-tuning using Benzinga article text?
3. May derived numeric features, article identifiers, or trained model weights be retained after access ends?
4. May non-reconstructive aggregate research results be shared publicly, and may raw text or snippets ever be shared?
5. Is there an archive license or Benzinga addendum governing historical News API content, revisions, and retention?
6. Are created_at and updated_at publication timestamps, ingestion timestamps, or vendor metadata, and are historical API responses latest-version or version-as-of-date?

### Current Decision

Use Alpaca/Benzinga as a current operational feed and record immutable first-seen payloads prospectively. Do not treat the historical archive as a point-in-time version archive. Use strict novelty, issuer-specific, price-recap, automation, and event-type filters. Do not retain or train on article bodies beyond the ordinary query workflow without written confirmation from Alpaca of the applicable Benzinga rights.

### Open Questions

1. What are the actual per-stock, per-day coverage and multi-ticker-tag distributions in the recorder and archive?
2. What is the created_at-to-first_seen delay distribution by source and article class?
3. How often do article IDs retain the same content hash after a later historical re-query?
4. Which Alpaca plan and contractual addendum govern the account's News API retention and machine-learning rights?
5. Does filtering price recaps and automated content improve out-of-sample information without reducing sample power too severely?

## R09 - 2026-09-16 - LLM Look-Ahead and Memorization Protocol

Status: Active forward-only policy. Historical recall-test details remain an adaptation until replicated from the paper appendix.

### Research Question

What is best practice for measuring and avoiding look-ahead or memorization bias when evaluating a local LLM's news-based trading signal for S&P 100 returns, while preserving trustworthy supporting historical evidence?

### Answer Summary

Forward-only evaluation is the only clean efficacy test for a modern LLM. For historical evidence, use a chronologically consistent vintage model whose documented cutoff is earlier than the article date. Use a recall-interaction test to diagnose contamination in modern-model historical results, but do not treat a non-significant diagnostic as proof of safety.

A released model's release date is only an upper bound on the latest possible training data. It does not prove an earlier effective knowledge cutoff, exclude proprietary data, or establish that a historical article was not memorized. Model cards and reproducible dated training corpora are stronger evidence than release dates.

### Recent Work

| Work | Type | Main Contribution | Practical Implication | Link |
|---|---|---|---|---|
| Lopez-Lira, Tang, and Zhu (2025), The Memorization Problem: Can We Trust LLMs' Economic Forecasts? | Working paper | Demonstrates that LLMs can recall historical economic and market outcomes; prominent large-cap stocks have elevated memorization risk. | Treat historical modern-LLM forecasts inside training coverage as contaminated by default. | Public working-paper identifier should be rechecked before formal citation. |
| Gao, Jiang, and Yan (2025/2026), Detecting Lookahead Bias in LLM Forecasts | arXiv working paper | Introduces Lookahead Propensity and recall-interaction test for headlines and earnings-call tasks. | Use as a diagnostic for a modern model; positive forecast-by-LAP interaction is evidence of contamination. | https://arxiv.org/search/?query=Detecting+Lookahead+Bias+in+LLM+Forecasts&searchtype=all |
| He, Lv, Manela, and Wu (2025), Chronologically Consistent Large Language Models | Working paper and released weights | Releases ChronoBERT, ChronoGPT, and instruction-tuned variants trained on annual historical cutoffs from 1999 to 2024. | Best available historical control when a vintage predates the evaluated article. | https://huggingface.co/manelalab |
| DatedGPT (2026) | Working paper and released weights | Released 1.3B parameter dated models with annual cutoffs from 2013 to 2024. | Useful modern vintage-model cross-check for 2015 onward. | https://huggingface.co/datedGPT |

### Decision Rules

1. A modern model evaluated on an article dated before its documented training cutoff is contaminated unless its full training corpus is shown to exclude the article and subsequent outcome information.
2. A closed model with unknown corpus is contaminated by default for all pre-release historical evaluation. Its release date only proves training did not occur after release.
3. A model with a dated cutoff earlier than the article date may be used as historical supporting evidence if the model card, weights, license, and cutoff are archived with the experiment.
4. A modern model may be used prospectively only if model weights, quantization, tokenizer, system prompt, decoding parameters, and code hash are frozen before the first scored article.
5. If recall-interaction evidence is positive, do not use that model's historical performance as efficacy evidence. Report it only as a contamination result.
6. If recall-interaction evidence is null, label historical results "no detected contamination," not "look-ahead free." Forward or vintage-model confirmation remains required.
7. Prompt instructions to ignore later knowledge and entity/date masking are diagnostic ablations, not leakage cures.

### Recall-Interaction Test

For each firm-date event j with realized outcome Y_j, perform two separate model queries.

#### Step 1: Forecast Query

Provide only the article text available at the decision time and a frozen forecasting prompt. Obtain a directional forecast F_j in {-1, 0, +1} or a calibrated probability p_j.

#### Step 2: Date-Only Recall Query

Do not provide the article. Ask a frozen, outcome-oriented query that contains only the issuer identity, event date, and horizon, for example:

"For [COMPANY] on [DATE], did its stock's next-trading-day return end positive, negative, or approximately unchanged? Answer only POSITIVE, NEGATIVE, or UNKNOWN."

Repeat with K preregistered paraphrases, no article text, temperature zero, and a fixed model version. Define LAP_j as the fraction of recall responses that equal the realized sign, or as the model's calibrated probability assigned to the realized sign. Store all raw completions.

#### Step 3: Interaction Regression

For return magnitude:

Y_j = a + b_F F_j + b_L LAP_j + b_I (F_j x LAP_j) + c' X_j + error_j

For directional accuracy, replace Y_j with I(sign(F_j) = sign(return_j)) and estimate a linear probability or logistic model with the same interaction and controls.

Controls X_j should include stock and date fixed effects, pre-news return, volatility, news/article length, event type, earnings window, market return, and a popularity proxy. Cluster by stock and date.

Interpretation:

- b_F significant and b_I not positive: evidence consistent with signal beyond the recall diagnostic, but not proof of no leakage.
- b_I positive and significant: forecast accuracy is concentrated where the model can recall outcome-related information; historical result is contaminated.
- LAP materially above its placebo rate before cutoff and near zero after cutoff: supports the diagnostic's relevance.

#### Step 4: Placebos and Sample Size

- Run a post-cutoff placebo sample where the model could not have seen future outcomes. The interaction should disappear.
- Run date-shuffled and issuer-shuffled recall queries; any accuracy above chance is a warning about prompt artifacts.
- Run name/date-masked variants as diagnostic comparisons only.
- `[PRIOR]` No published universal minimum was verified. Simulate interaction-test power from the observed LAP distribution, return variance, date clustering, and forecast balance before setting a sample target; 5,000 events is retained only as an initial scenario.

### Chronologically Consistent Models

| Model | Cutoffs | Architecture and Capability | License | Practical Hardware | Use |
|---|---|---|---|---|---|
| ChronoBERT | Annual 1999-2024 | About 149M parameter ModernBERT-style encoder; classification and embeddings, not natural instruction following | `[UNVERIFIED]` Checkpoint license must be verified from the exact model card before download | CPU feasible; GPU useful for batch scoring. Exact minimum hardware not published. | Historical sentiment, embeddings, and bias-check baseline. |
| ChronoGPT | Annual 1999-2024 | Decoder-only generative models; smaller historical-vintage LLM control | `[UNVERIFIED]` Checkpoint license must be verified from the exact model card before download | Use quantized inference on a consumer GPU; exact requirements not published. | Historical prompted scoring where generative output is required. |
| ChronoGPT-Instruct | Annual 1999-2024 | Instruction-tuned ChronoGPT; example 2020 vintage about 1.55B parameters, context reported around 1,792 tokens | `[UNVERIFIED]` Checkpoint license must be verified from the exact model card before download | Roughly 8GB VRAM is a practical starting point for 4-bit inference; estimate, not official requirement. | Closest historical analogue for structured direction/materiality prompting. |
| DatedGPT | Annual 2013-2024 | 1.3B parameter dated generative checkpoints | `[UNVERIFIED]` Checkpoint license must be verified from the exact model card before download | Consumer-GPU quantized inference likely practical; exact requirement not published. | Independent vintage robustness check for 2015 onward. |

Model-weight licenses do not override copyright or contract limits on input news text. Confirm that the Alpaca/Benzinga news license permits the intended scoring, retention, embeddings, or fine-tuning workflow.

### Estimating an Undocumented Effective Cutoff

1. Construct a dated recall panel of firm-date outcomes and contemporaneous facts spanning before and after several candidate dates.
2. Query the model without article text using fixed date-only prompts and K paraphrases.
3. Estimate recall accuracy and LAP by calendar month; apply a preregistered change-point or segmented regression to identify where recall drops toward chance.
4. Compare with post-cutoff and shuffled-date placebos.
5. Treat the inferred cutoff as a diagnostic lower bound on contamination, not proof of a clean period. Use only a documented vintage cutoff for positive historical claims.

### Masking and Prompting

- Replacing company names, tickers, and dates may reduce direct recall but can remove economically relevant context and leave event descriptions identifiable.
- Instructions such as "ignore information after DATE" do not alter model weights and cannot prevent latent recall.
- Use modern-model original, masked, and date-neutral prompts only as a leakage-sensitivity table. A large performance drop after masking is evidence against treating the original historical result as clean.
- Do not use masking to certify a modern model; use it to reveal fragility.

### Other Leakage Paths

- Fine-tuning on article text with return labels, revised articles, or post-event summaries.
- Prompts containing prices, returns, performance words, or article metadata that identify the event outcome.
- News archives that return revised current article text rather than the version available at the original timestamp.
- Retrieval augmentation that searches documents published after the event date.
- Model updates, silent provider version changes, temperature variation, and post-hoc prompt selection.
- Cross-validation folds that allow 2-15 trading-day labels to overlap; apply purging and embargo.

### Recommended Protocol

#### Forward-Only Efficacy Test

1. Freeze a local model and all inference artifacts before the first article.
2. Capture immutable first-seen article payloads and hashes before scoring.
3. Score immediately with deterministic decoding; store the raw response, score, prompt hash, model hash, and timestamp before the target return exists.
4. Use the preregistered one-day information test first, then frozen strategy filter/sizing test.
5. Do not fine-tune on post-start articles or realized outcomes until the forward test ends.
6. Use the recall-interaction test only as a diagnostic; forward timing is the primary proof.

#### Supporting Historical Evidence

1. For each article date, select the newest ChronoBERT/ChronoGPT/DatedGPT vintage with a cutoff strictly before the article date. Annual vintages imply using the prior year for within-year articles.
2. Score the same immutable or point-in-time article version with the vintage model and a modern similar-size open model.
3. Report historical predictive effects separately by vintage, model family, and cutoff gap.
4. Apply recall-interaction diagnostics to the modern model; do not promote modern-model historical results if interaction evidence is positive.
5. Treat agreement between a clean vintage signal and the prospective modern-model signal as supporting evidence, not as a substitute for forward validation.

### Current Decision

Use ChronoGPT-Instruct or DatedGPT as the historical generative control and ChronoBERT as the encoder control. Make forward-only scoring the sole efficacy claim for the modern local LLM. Use recall-interaction, masked prompts, and documented-vintage comparisons to classify historical modern-model results as contaminated, no-detected-contamination, or unsupported.

### Open Questions

1. Which ChronoGPT/DatedGPT vintages can run acceptably on the available home hardware?
2. Does the Alpaca/Benzinga license permit local model scoring and retention of derived embeddings?
3. How many S&P 100 firm-date events are available for a high-versus-low LAP interaction test after deduplication and earnings controls?
4. Can a point-in-time article-version archive be established for historical supporting evidence?
5. Which popularity proxy best controls the fact that heavily covered mega-cap events are easier for an LLM to recall?

## R10 - 2026-09-16 - Local Open-Weight Model Selection for News Extraction

Status: Candidate shortlist only; no model is final until license, cutoff, hardware, and blinded-label tests pass.

### Research Question

Which fixed, locally run open-weight model released before late September 2026 best extracts direction, materiality, and event type from short S&P 100 news articles on one consumer GPU with 24GB VRAM, with 12GB alternatives, plus a cheap FinBERT baseline?

### Answer Summary

Recommended primary model: Qwen3-14B, frozen to an exact weight revision and run with grammar or JSON-schema constrained decoding. It offers a strong instruction-following and structured-output balance at a size that leaves comfortable 24GB headroom with Q5 or Q8 quantization. Its precise official training-data cutoff was not verified; its 2025-04-29 release date is only an upper bound on its knowledge.

Recommended backup: Mistral Small 3.1 24B Instruct at Q4 on a 24GB GPU. It is a capable, Apache-licensed alternative with strong JSON/function support, but has lower VRAM headroom and no precise public cutoff verified for 3.1.

Recommended 12GB option: Gemma 3 12B IT at Q4 or Qwen3-8B at Q5. Gemma publishes an August 2024 knowledge cutoff but has the Gemma license rather than Apache 2.0.

Recommended sentiment baseline: ProsusAI/finbert, exported to ONNX Runtime INT8 if desired. It is news-trained and simple, but was trained on 2008-2010 Reuters news and sentence-level Financial PhraseBank labels, so it is not a modern event/materiality model.

### Candidate Shortlist

Memory values are planning estimates for GGUF-style quantization plus short-article context and runtime overhead. Exact file size, context length, backend, and GPU driver can change them. Test the exact quant file before committing.

| Model | Parameters and Release | Documented Cutoff | License | Approximate VRAM | Finance Evidence | Structured Output | Recommendation and Link |
|---|---|---|---|---|---|---|---|
| Qwen3-14B | 14B dense; 2025-04-29 | Precise official cutoff not verified; release date is upper bound | Apache 2.0 | Q4 9GB; Q5 11GB; Q8 16GB | No peer-reviewed finance-specific result verified for this exact checkpoint; general finance benchmark claims may overlap public benchmarks | Use llama.cpp GBNF, vLLM JSON Schema, or Ollama schema | Primary 24GB choice. https://huggingface.co/Qwen/Qwen3-14B |
| Mistral Small 3.1 24B Instruct | 24B; 2025-03-17 | Precise 3.1 cutoff not verified; Small 3 base documentation cites Oct. 2023 | Apache 2.0 | Q4 15GB; Q5 18GB; Q8 about 25GB | No directly comparable peer-reviewed finance extraction score verified | Native JSON/function support plus external grammar/schema | Quality backup for 24GB at Q4. https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503 |
| Gemma 3 12B IT | 12B; 2025-03 | August 2024 in model documentation | Gemma license; commercial use allowed subject to policy | Q4 8GB; Q5 10GB; Q8 14GB | General benchmark evidence; no direct verified finance extraction advantage | JSON/schema via runtime tooling | Preferred 12GB option when cutoff transparency matters. https://huggingface.co/google/gemma-3-12b-it |
| Qwen3-8B | 8B; 2025-04-29 | Precise official cutoff not verified | Apache 2.0 | Q4 5GB; Q5 6GB; Q8 9GB | No direct verified finance extraction result | Same runtime schema options | Faster 12GB alternative; use if throughput matters more than nuance. https://huggingface.co/Qwen/Qwen3-8B |
| Qwen3-32B | 32B; 2025-04-29 | Precise official cutoff not verified | Apache 2.0 | Q4 20GB; Q5 about 24GB; Q8 about 34GB | Larger general model; no clean exact finance benchmark result verified | Same runtime schema options | Optional 24GB stress test at Q4 only; not primary because limited context/runtime headroom. https://huggingface.co/Qwen/Qwen3-32B |

Model release and license sources: Qwen3 announcement/model card, https://huggingface.co/Qwen/Qwen3-14B ; Mistral model card, https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503 ; Gemma model card, https://ai.google.dev/gemma/docs/core/model_card_3

### Finance-Task Evidence

- FinBen is a broad financial benchmark covering information extraction, textual analysis, question answering, forecasting, and decision tasks. Benchmark scores are not sufficient evidence for stock-return usefulness and may be contaminated when public benchmark items overlap training data. Source: https://arxiv.org/abs/2402.12659
- Finance-specific fine-tuning can improve some finance benchmarks, but results vary by task and model. It can also reduce general instruction following and introduce unknown corpus/license provenance. Use it only after a frozen general-model baseline. 
- For this task, general instruction-following plus a strict schema is more directly relevant than finance-question-answering benchmarks. Direction/materiality/event classification must be measured on the recorder's manually labeled articles, without using returns.

### Structured Output

Use a fixed JSON schema:

{
  "direction": number from -1.0 to 1.0,
  "materiality": number from 0.0 to 1.0,
  "event_type": one fixed enum,
  "schema_version": string
}

- llama.cpp GGUF supports GBNF grammars and JSON-schema conversion. Source: https://github.com/ggml-org/llama.cpp/tree/master/grammars
- vLLM supports guided JSON/grammar and JSON Schema through structured outputs. Source: https://docs.vllm.ai/en/latest/features/structured_outputs.html
- Ollama supports JSON and JSON-schema structured outputs. Source: https://docs.ollama.com/capabilities/structured-outputs
- Grammar/schema decoding can guarantee parseable structure and fixed enum keys if generation completes. It cannot guarantee semantic correctness, calibrated numeric meaning, or immunity from truncation.
- No reliable model-agnostic observed JSON-validity percentage was verified. Measure JSON parse rate, schema-valid rate, retry rate, and semantic-range violation rate on a preregistered article set. Do not rely on prompt-only JSON claims.

### Quantization, Speed, and Repeatability

- Q4 has roughly half-byte-per-parameter weight storage; Q5 and Q8 trade VRAM for quality. Short article prompts leave much more headroom than long-context chat, but KV cache and backend overhead are material.
- For a few hundred short articles daily, throughput is not a binding requirement on a 24GB GPU. Choose Q5 or Q8 for Qwen3-14B, Q4 for Mistral Small 3.1 24B, and Q4/Q5 for 12GB cards.
- Do not compare model quality across different quantization, context, prompt, or schema settings. Fix all before the evaluator sees labels.
- Use temperature 0, greedy decoding or top_k 1, fixed seed, fixed max tokens, fixed batch size, fixed runtime, fixed GPU driver, and a content-addressed weight file.
- GPU kernels and dynamic batching can still introduce differences. Produce a 1,000-article repeatability corpus and run it at least five times in clean processes. Require at least 99.5% parsed-label agreement, bounded numeric drift under a preregistered tolerance, and 100% schema validity. Use batch-size 1 and a CPU or deterministic backend only for the smaller audit subset where byte identity is required. At runtime, any schema failure, timeout, or out-of-range value must fail closed to the predeclared price-only or FinBERT-only model and log `LLM_SCORE_UNAVAILABLE`; it must never trigger an improvised retry or directional trade.
- PyTorch reproducibility guidance: https://pytorch.org/docs/stable/notes/randomness.html

### FinBERT Baseline

| Variant | Training | License and Deployment | Strength | Weakness |
|---|---|---|---|---|
| ProsusAI/finbert | Reuters TRC2 financial news, 2008-2010; fine-tuned on 4,845 Financial PhraseBank sentences | Apache 2.0; 110M BERT; 512 tokens; ONNX and INT8 deployment available | Best simple news-oriented fixed sentiment baseline | Old news language; sentence labels; truncation; no novelty/materiality/event model; possible overlap with 2008-2010 historical news | 
| yiyanghkust/finbert-tone | Financial filings, earnings calls, analyst reports; fine-tuned on analyst-report tone sentences | Apache 2.0; 512 tokens; standard Transformers/ONNX export | Useful secondary tone sensitivity | Less aligned with Benzinga-style short news; document-heavy training corpus |

ProsusAI source: https://huggingface.co/ProsusAI/finbert ; FinBERT paper: https://arxiv.org/abs/1908.10063 ; tone variant: https://huggingface.co/yiyanghkust/finbert-tone

### General Versus Finance-Tuned Model

Use a general instruction-tuned model as primary because the task is structured event extraction, not generic financial sentiment. It must distinguish event novelty, issuer relevance, analyst notes, price recaps, and materiality under a rigid schema. Finance tuning is a secondary challenger: it may improve jargon recognition but must beat the general baseline on manually labeled recorder articles while retaining exact schema compliance and documented input rights.

### Selection Test Without Returns

1. Freeze three exact candidates: Qwen3-14B Q5, Mistral Small 3.1 24B Q4, and one 12GB option.
2. Draw a stratified, pre-return sample of 600-1,000 recorder articles across issuer, time of day, article length, event type, and suspected template status.
3. Create a human-labeled reference set with direction, materiality, event type, issuer relevance, and price-recap label. Blind labelers to model outputs and subsequent returns.
4. Score every article twice with each frozen model and schema. Record parse/schema validity, latency, token count, repeatability, abstentions, and human agreement.
5. Double-label at least 20% of the corpus. Report weighted kappa or Krippendorff alpha for direction/materiality and macro-F1 agreement for event type; adjudicate disagreements before model scoring.
6. Primary selection score: event-type macro-F1 plus materiality calibration error and direction ordinal correlation. Require 100% schema-valid completed outputs and at least 99.5% parsed-label repeatability on the fixed runtime.
7. Select the smallest model that is within a preregistered tolerance of the best human-label score and fits the intended hardware with headroom. Do not inspect stock returns until selection is final.

### Current Decision

Start with Qwen3-14B Q5 GGUF or equivalent fixed quantization on a 24GB GPU, using grammar/schema-constrained decoding. Use Mistral Small 3.1 24B Q4 as the quality backup and Gemma 3 12B Q4 or Qwen3-8B Q5 for 12GB hardware. Use ProsusAI/finbert ONNX INT8 as the fixed sentiment baseline. Do not choose on finance benchmarks or returns; choose on frozen, blind article-extraction evaluation.

### Open Questions

1. Which exact Qwen3-14B quantization and runtime achieve the preregistered semantic-repeatability tolerance on the target GPU?
2. Does the Alpaca/Benzinga license permit retained article text for the human-label and model-selection corpus?
3. Can schema-constrained decoding preserve the desired numeric precision for direction and materiality?
4. Does a finance-tuned challenger beat the general model on article labels without losing event-type or JSON reliability?
5. Is 12GB hardware sufficient for the preferred latency and context requirements after KV cache overhead?

## R11 - 2026-09-16 - Alpaca Live Brokerage Safety and Individual Account Rules

Status: Draft operational checklist. Do not deploy live until every `[UNVERIFIED]` broker behavior is confirmed.

### Research Question

What brokerage mechanics, account rules, taxes, and operational controls matter for safely operating a small personal long-only S&P 100 swing strategy through Alpaca with next-session limit entries and broker-held bracket exits?

### Answer Summary

Use broker-held brackets for completed entries, but build the system around reconciliation rather than stream assumptions. The central safety invariant is: every live position must have broker-confirmed protective exit quantity equal to its position quantity, except during a logged cancellation-and-replace transaction. `[UNVERIFIED]` Parent-partial-fill protection behavior must be confirmed from nested live or paper order state before any automated repair.

`[UNVERIFIED]` The intended Alpaca account type must be confirmed from the executed account agreement; current public searches did not conclusively establish whether a cash account is available. If margin-enabled, use no-leverage strategy limits and a buying-power buffer. The 2026 FINRA intraday-margin change is current, but Alpaca-specific implementation must be confirmed for the account.

All rules below were checked on 2026-09-16.

### Constraints Checklist

| Constraint | Live-System Rule | Source |
|---|---|---|
| Bracket entry | Entry can be market or limit; take-profit is limit; stop-loss can be stop or stop-limit. | https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |
| Bracket TIF | Use day or gtc only; brackets are not supported in extended hours. | https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |
| Bracket protection | Mark a position protected only after REST confirms executable child or standalone exit orders covering the actual position quantity. Do not infer coverage solely from parent status. | https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |
| Parent partial fill | `[UNVERIFIED]` Public documentation clearly describes partial fills of exit legs, but current protection behavior during a partially filled parent was not conclusively verified. Query nested child legs and covered quantity before intervening; never submit duplicate protection blindly. | https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |
| OCO lifecycle | A fill/cancel in an OCO group affects the paired exit leg. Reconcile child status and quantity after every fill. | https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |
| Stop mechanics | Stop trigger is based on a valid last trade; stop converts to market, stop-limit converts to limit. | https://docs.alpaca.markets/docs/trading/orders/ |
| GTC expiry | `[UNVERIFIED]` Treat GTC exits as finite and reconcile their age daily; confirm any automatic expiration period directly with Alpaca before deployment. | https://docs.alpaca.markets/docs/trading/orders/ |
| Trade updates | Subscribe to WebSocket trade_updates but treat it as a low-latency signal, not the only ledger. | https://docs.alpaca.markets/docs/websocket-streaming |
| Activity ledger | Broker API activity SSE is not available to a normal individual Trading API account. Use trade_updates for latency and poll REST account activities for durable reconciliation. | https://docs.alpaca.markets/reference/getaccountactivities |
| REST reconciliation | On startup, reconnect, and scheduled heartbeat: read account, open orders, positions, and account activities; compare them with local state. | https://docs.alpaca.markets/reference/getallorders ; https://docs.alpaca.markets/reference/getallpositions ; https://docs.alpaca.markets/reference/getaccount |
| Idempotency | Assign a unique client_order_id to every intended order. On timeout, query/reconcile before retry rather than relying on assumed exactly-once POST behavior. | https://docs.alpaca.markets/docs/trading/orders/ |
| Corporate actions | Record DNR/DNC status for brackets. Do not assume public docs specify every split adjustment detail; reconcile positions and open orders on every action date. | https://docs.alpaca.markets/docs/trading/orders/#bracket-orders |
| Halts and LULD | Assume no execution during halt/pause; on first valid post-resumption trade, re-evaluate gap and stop state. Exact Alpaca bracket sequencing through halts was not publicly verified. | https://www.sec.gov/investor/pubs/tradinghalts.htm |
| Paper versus live | Paper is an API integration environment, not an execution-quality simulator; it lacks real queue, impact, and live slippage behavior. | https://docs.alpaca.markets/docs/paper-trading |
| API rate/security | Keep a local rate limiter and backoff. Store live keys in OS secret storage, never logs; use separate paper/live keys. Fine-grained key scopes, rotation automation, and customer-configurable IP restrictions were not publicly verified. | https://docs.alpaca.markets/docs/about-api-keys ; https://alpaca.markets/security |
| Disconnect safety | No public built-in cancel-on-disconnect feature was verified. Do not cancel broker-held protective exits on process failure. Cancel only stale unfilled entries through a timed workflow. | Alpaca documentation/support confirmation required |

### Reconciliation and Recovery Pattern

1. Generate deterministic client_order_id values from strategy run, signal date, symbol, and order role.
2. Persist intent before REST submission, then persist broker order ID and raw response.
3. Consume trade_updates for speed and persist every raw message with a local sequence. Do not assume exactly-once or gap-free delivery.
4. On startup, reconnect, periodic heartbeat, and uncertain submission outcome, query REST open orders with nested legs, positions, account, and recent activities. Handle eventual consistency with bounded retries and an as-of timestamp; do not assume an immediate REST response or WebSocket event is complete. Broker API SSE event_id/ref_id/since_id logic does not apply to an individual Trading API account.
5. Enforce invariant: broker-confirmed, executable protective sell quantity equals current long position quantity, with bracket-group validation and no duplicate standalone exits.
6. If position is unprotected, immediately alert and submit protection according to a predeclared emergency rule; block new entries until invariant is restored.
7. If a parent is partially filled, query the nested broker order and position first. Intervene only after confirming whether child protection exists and its covered quantity; otherwise a manual stop can duplicate broker-generated protection.
8. On planned time exit, cancel-confirm bracket exits before submitting a closing order; wait for cancellation confirmations to avoid double sells.
9. Run an independent watchdog process that checks broker state and protection invariants. On a mismatch, block new entries and alert; do not cancel or replace protection until the existing broker order state and an atomic or confirmed replacement sequence are known.
10. Test process kill, network loss, stale stream, partial fill, child-order rejection, corporate action, halt, and restart scenarios in paper before any live order.
11. Before every session, query corporate-action announcements and block new orders for affected symbols until split, merger, special-distribution, or symbol-change handling has been reconciled.

### Corporate Actions, Halts, and Paper Trading

- Alpaca documents brackets as Do Not Reduce and Do Not Cancel. Ordinary cash dividends therefore do not automatically reduce bracket prices. Public documentation did not verify exact price/quantity adjustment for every open bracket state during a split. Reconcile rather than assume. https://docs.alpaca.markets/docs/trading/orders/#bracket-orders
- Paper trading uses a simulated fill model. It does not reproduce actual queue position, order size effects, market impact, or live slippage. Do not use paper fills to calibrate production expected returns; use them to validate API state handling. https://docs.alpaca.markets/docs/paper-trading
- A halt or LULD pause can create a post-resumption gap through a stop. Broker-held stop protection reduces process risk but does not guarantee a stop-price fill. https://www.sec.gov/investor/pubs/tradinghalts.htm

### Cash Versus Margin

| Topic | Traditional Cash Account | Direct Alpaca Individual Account | Recommendation |
|---|---|---|---|
| Availability | Available at many brokers | `[UNVERIFIED]` Public documentation reviewed was inconclusive on the exact cash-versus-margin choices for the intended Alpaca account. | Confirm the executed account agreement and account flags before funding. |
| Settlement | T+1 for most U.S. securities | T+1 remains the market settlement cycle; reuse of sale proceeds depends on the confirmed account type and broker controls. | Track settled and unsettled cash even if platform buying power allows immediate reuse. |
| Same-day stop-out | Permitted when using settled cash; can create GFV if purchase used unsettled sale proceeds and is sold before settlement. | No PDT count under new intraday-margin framework, but consumes intraday buying power and may trigger margin controls. | Strategy should target overnight holds, but model same-day stop-out as an operational margin/buying-power event. |
| Primary risk | Good-faith and freeriding violations | Margin deficit, buying-power rejection, broker liquidation, and leverage risk | Prefer no-borrow/no-leverage internal limits and a 20% buying-power buffer. |

Settlement source: https://www.sec.gov/newsroom/press-releases/2023-29

Alpaca account source: https://alpaca.markets/learn/what-is-a-margin-account

FINRA/Alpaca intraday-margin framework source: https://www.finra.org/rules-guidance/rulebooks/finra-rules/4210 ; Alpaca current intraday-margin documentation should be confirmed in the account documentation.

### Tax Operations

- Default taxable treatment generally makes gains on positions held one year or less short-term. Confirm tax treatment with a qualified tax adviser. IRS source: https://www.irs.gov/publications/p550
- A wash sale occurs when a loss sale is paired with purchase of substantially identical securities within 30 days before or after the sale. The disallowed loss is generally added to replacement basis and holding period. https://www.irs.gov/publications/p550
- Frequent re-entry in the same 100 names makes wash-sale tracking a routine operational issue, not an edge case.
- Brokers report many same-account covered-security wash sales on Form 1099-B, but cross-broker, spouse, and IRA interactions may not be fully reported. Taxpayer reconciliation remains necessary. https://www.irs.gov/instructions/i1099b
- Maintain a lot-level ledger containing execution ID, security identity, acquisition and sale dates, basis, wash-sale adjustment, replacement lot, and all accounts under common tax control. Reconcile against the annual 1099-B, but do not assume the 1099-B is the complete cross-account wash-sale record.

### Current Decision

For a direct Alpaca individual account, do not presume cash or margin treatment; confirm the executed account type and then enforce an internal no-borrow rule unless leverage is explicitly intended. Keep broker-held brackets after full entry fills, retain exits during process failure, and use a watchdog plus reconciliation ledger to repair protection gaps. Treat paper trading as systems testing, not execution validation. Obtain Alpaca written confirmation on account classification, intraday-margin behavior, split adjustment, halt sequencing, API security controls, and cancel-on-disconnect availability before live funding.

### Open Questions for Alpaca Support

1. Does the intended individual taxable account have a cash-account option, or will it be limited/full margin by default?
2. What exact intraday-margin/buying-power calculation and pre-trade rejection behavior applies to the account type after the 2026 rule change?
3. What is the exact bracket behavior if a parent limit order partially fills and the client disconnects before full fill?
4. How are open bracket quantity and prices adjusted for forward/reverse splits, special dividends, mergers, and symbol changes?
5. Is there any broker-side cancel-on-disconnect, order-expiry, or kill-switch feature suitable for API clients?
6. What ordering, replay, retention, and duplication guarantees apply to trade_updates, and what REST activity history is available to an individual Trading API account?
7. Are API keys scope-limited, rotation-capable without downtime, and configurable with customer IP allowlists?
8. What paper-trading fill rules apply to nonmarketable limit orders and bracket children, and how do they differ from live routing?
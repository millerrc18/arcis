# RESEARCH-QUESTIONS.md — Deep Research Queue

| | |
|---|---|
| **Location** | `docs/research/RESEARCH-QUESTIONS.md` |
| **Last updated** | 2026-09-16 (after research log v2.0) |
| **Purpose** | Every open question that needs outside evidence, written as a self-contained prompt for deep research |
| **Results** | `docs/research/research-log.md`. RQ-01 to RQ-11 are answered there as entries R01 to R11 |

## How to use this document

1. Run the prompts in ID order. Priority A items should be finished before `charter-v1` and `prereg-v1` are tagged.
2. Paste each prompt block into deep research exactly as written. Each one carries its own context, so nothing else is needed.
3. Append each result to `docs/research/research-log.md` as a new entry, following the log's governance protocol, then bring it back to Claude for synthesis.
4. Claude turns the findings into specific edits to SCOPE.md or PREREGISTRATION.md. After tagging, those edits are logged in PREREGISTRATION.md §5.
5. These questions look only at outside evidence, never at Arcis's own results, so running them cannot compromise the preregistration.

## Tracker

| ID | Topic | Priority | Unblocks | Status |
|---|---|---|---|---|
| RQ-01 | Prior evidence for the strategy family and universe breadth | A | Scope freeze (SCOPE §1); Q1 minimum effect | Done (R01) |
| RQ-02 | Survivorship-free, point-in-time data sources for personal use | A | Step 3 data plane; whether a historical Q1 look is possible | Done (R02) |
| RQ-03 | Effect sizes and timing of news-based signals in large caps | A | Q2/Q3 thresholds and first-gate design | Done (R03) |
| RQ-04 | Statistical testing plan for Q1 | A | PREREGISTRATION §2; walk-forward harness | Done (R04) |
| RQ-05 | Honest daily-bar simulation of limit entries and bracket exits | B | Step 5 bracket simulator | Done (R05) |
| RQ-06 | Transaction cost model | B | Step 4 cost model | Done (R06) |
| RQ-07 | Test design and statistical power for text signals | C | PREREGISTRATION §3–5 | Done (R07) |
| RQ-08 | News feed quality and personal-use terms | C | Text eligibility and filters; any future training use | Done (R08) |
| RQ-09 | Look-ahead bias protocol for LLM signals | C | Q3 historical evidence rules | Done (R09) |
| RQ-10 | Choosing the pinned local LLM and FinBERT variant | C | OD-3 | Done (R10) |
| RQ-11 | Alpaca brokerage mechanics and personal account rules | D | Live lane; OD-1 | Done (R11) |
| RQ-12 | Verify quoted values from key papers | B | Priors used in PREREGISTRATION.md scenarios | Not started |
| RQ-13 | Free reconstruction of S&P 500 membership, and how far survivorship bias reaches | C | The exploratory historical check in PREREGISTRATION.md §2.4 | Not started |

**Priority key.** A: before tagging the charter and preregistration. B: before Steps 4–5. C: before any text scoring. D: before the live lane.

---

## Priority A — before tagging

### RQ-01 — Prior evidence for the strategy family and universe breadth

**Informs:** SCOPE.md §1 (universe), PREREGISTRATION.md §2 (minimum economic effect)

```text
Context: I'm an individual running a personal, research-first systematic trading project. The strategy under study is long-only swing trading in S&P 100 stocks: one decision per trading day after the close, limit-order entries the next session, and exits through broker-held stop-loss and take-profit orders or a 15-trading-day time limit (typical holds of 2–15 trading days, roughly 50 trades a year). It buys pullbacks within established uptrends: short-term weakness in stocks with a positive intermediate-term trend. Earlier backtests and live trials were inconclusive. Use sources current as of September 2026.

Research question: What does rigorous evidence say about the profitability of short-horizon pullback (short-term reversal) strategies conditioned on trend, specifically in large-cap US stocks, after realistic costs? And is the S&P 100 the right universe for testing it?

Cover:
1. The short-term reversal literature (weekly and monthly reversal): where the effect concentrates (size, liquidity, volatility), how it has changed over time, and the evidence that reversal profits are compensation for providing liquidity.
2. Evidence on combining short-term reversal with intermediate-term momentum or trend filters ("buy the dip in winners"), in large caps specifically.
3. Evidence on buying dips in mega-cap stocks since 2015, including the role of retail order flow.
4. How stop-loss and take-profit rules change strategy returns and the distribution of trade outcomes (when stop-losses help and when they hurt).
5. How limit-order entries change realized performance compared with entries at the open or close (adverse selection, missed trades).
6. Regime dependence: results in high- versus low-volatility periods and in drawdowns such as 2008, 2020, and 2022.
7. How much of any gross edge survives realistic costs for large caps at small trade sizes.
8. Universe choice: trade-offs between the S&P 100 and a broader liquid universe (the S&P 500, or the top 500 stocks by market cap) for this strategy family. Compare expected edge, costs, number of trading opportunities, and the statistical power to confirm an edge within 1–3 years at roughly 50 versus 150 trades a year.

Deliverables:
- A study table: citation, sample period, universe, holding period, gross and net returns, t-statistics, and link.
- A realistic range for the net annual alpha a strategy like this could earn in the S&P 100, with your reasoning.
- A recommendation on universe breadth with its trade-offs, and the minimum annual alpha worth pursuing given the statistical power at each trade frequency.

Standards: give a link for every factual claim. Prefer peer-reviewed papers and official documentation. Label practitioner sources, and flag anything you could not verify. Separate what the evidence shows from your own inference, and state your confidence.
```

### RQ-02 — Survivorship-free, point-in-time data sources for personal use

**Informs:** Step 3 (data plane); whether PREREGISTRATION.md §2 can use a historical look; running-cost input for the minimum economic effect

```text
Context: I'm an individual running a personal, research-first systematic trading project: long-only swing trading in large-cap US stocks (currently the S&P 100, possibly the S&P 500), with daily decisions and holds of 2–15 trading days. The broker is Alpaca and the code is Python on a home computer. My earlier research already used 2019–2024 data, so an untouched test window will likely need data from before 2019, ideally back to 2000 or earlier. Use sources current as of September 2026.

Research question: Which data sources can give me survivorship-free, point-in-time daily US equity data for these universes, under terms that allow personal (non-professional, non-academic) use, and at what cost?

Cover:
1. Index membership: sources for the historical constituent lists of the S&P 100 (OEX) and the S&P 500 with exact addition and removal dates. How far back does each go? How are share classes (e.g., GOOG/GOOGL), ticker changes, mergers, and spin-offs represented? If no affordable source covers the S&P 100 specifically, what are defensible alternatives (for example, S&P 500 history plus a reproducible market-cap rule), and what bias does each introduce?
2. Prices: daily open, high, low, close, and volume, including delisted and acquired companies. Adjustment methods for splits and dividends; availability of both adjusted and unadjusted series; whether the source uses permanent security identifiers that survive ticker changes; known data-quality problems.
3. Corporate actions: splits, regular and special dividends, spin-offs, mergers, and symbol changes, with ex-dates and announcement dates.
4. Earnings announcement dates with timing (before the open or after the close), historical and point-in-time.
5. Point-in-time integrity: does each source keep data as it was known at the time, or overwrite it with later revisions? Any documented backfilling or restatement practices?
6. Alpaca specifically: how far back its historical daily and minute bars go, whether delisted symbols are available, how its corporate-actions endpoint and historical symbol mapping work, and what its free plan allows for historical data.
7. Free options (SEC EDGAR, exchange or index-provider notices, public records of constituent changes): how complete and reliable are they for reconstructing index membership?
8. Licensing: for each source, what personal use permits (local storage, use in my own trading decisions, limits on sharing). Academic-only services such as WRDS/CRSP are off-limits for this project; mention them only as a quality benchmark.

Deliverables:
- A comparison table: source, membership history and start date, delisted coverage, adjustments, corporate actions, earnings dates, point-in-time integrity, access method (API or bulk download), price for personal use (monthly and annual), license notes, and link.
- Recommended combinations at three budget levels (free, under $50 a month, under $200 a month), each with the earliest clean start date it supports.
- Validation checks I should run on whichever source I choose (for example, reconciling constituent counts over time and spot-checking delisted names).

Standards: give a link for every factual claim. Prefer official documentation and primary sources. Give the date you checked each price and each license term, and flag anything you could not verify.
```

### RQ-03 — Effect sizes and timing of news-based signals in large caps

**Informs:** PREREGISTRATION.md §5 (minimum effect worth having, horizon, whether to add a universe-level first gate)

```text
Context: I'm an individual running a personal, research-first systematic trading project in S&P 100 stocks (long-only, daily decisions after the close, holds of 2–15 trading days). A news recorder captures every article about these stocks with a first-seen timestamp. I plan to test whether text signals add predictive value: first a cheap sentiment model (FinBERT-style), then a locally run large language model that scores each article's direction and materiality. My sample is small, about 100 stocks times about 250 trading days a year, so I need realistic effect sizes before setting pass/fail thresholds. Use sources current as of September 2026.

Research question: What does the evidence say about the size, timing, and durability of stock-return predictability from news-based signals in large-cap US stocks?

Cover:
1. Effect sizes from peer-reviewed papers and high-quality working papers (mainly 2010 onward, plus foundational earlier work): dictionary methods (e.g., Loughran–McDonald), transformer sentiment models (FinBERT and similar), and LLM-based signals (e.g., studies applying GPT-class models to headlines). Report effects in basis points and t-statistics where available.
2. Large versus small stocks: how much weaker or stronger the effects are for mega-caps and S&P 100 or S&P 500 members than for the full cross-section.
3. Timing: how much of the effect is realized intraday or on the same day, the next day, and over 2–15 trading days. Include evidence on reversal of news-driven moves.
4. Decay: evidence that effects shrank after well-known papers were published or after LLMs became widely used (2023 onward).
5. Incremental value: whether text signals still predict returns after controlling for price-based signals (short-term reversal, momentum, abnormal volume, volatility) and for earnings-announcement periods.
6. Feed-specific confounds: articles that simply recap price moves, analyst-rating notes, and automated or templated stories. How do studies handle them, and how much do they inflate apparent predictability?
7. Inputs: headline versus summary versus full text. Which performs better, and at what processing cost?
8. For power calculations: typical dispersion of individual large-cap stock returns at 1-, 5-, and 10-day horizons, both raw and market-adjusted.

Deliverables:
- A study table: citation, sample period, universe, signal type, horizon, effect size in bps, t-statistic, whether costs are included, large-cap result, and link.
- A realistic expected range for S&P 100 stocks at a 1-day horizon and at 5–10-day horizons, plus the minimum detectable effect with about 12,000 news-bearing stock-days a year.
- Test-design recommendations: horizon, return adjustment (raw, market-adjusted, or characteristic-adjusted), control variables, and article filters.
- Flag every study with look-ahead risk, such as an LLM evaluated on dates inside its own training data.

Standards: give a link for every factual claim. Prefer peer-reviewed work, and label working papers and practitioner sources. Separate evidence from your own inference, and state your confidence.
```

### RQ-04 — Statistical testing plan for Q1

**Informs:** PREREGISTRATION.md §2; the Step 5 walk-forward harness

```text
Context: I'm an individual testing a personal, long-only swing-trading strategy in S&P 100 stocks (daily decisions, overlapping positions held 2–15 trading days, roughly 50 trades a year). I will judge it with a preregistered test. Daily portfolio excess returns, from a marked-to-market equity curve that includes cash days, are regressed on SPY excess returns, and the test is on the intercept (alpha). The current plan:
- Newey–West standard errors with 15 lags.
- Deflated Sharpe Ratio (DSR) of at least 0.95, using the count of every strategy variant ever tried, including variants from an earlier project whose individual Sharpe ratios may be unknown.
- One look at an untouched historical window (one-sided t ≥ 1.96), then up to three forward looks at 12, 24, and 36 months (one-sided t ≥ 2.39 each, from a Bonferroni split).
- A floor of 150 closed trades, and a minimum economic alpha.
Use sources current as of September 2026.

Research question: Is this testing plan statistically sound, and what should change?

Cover:
1. Standard errors for daily returns of a portfolio built from overlapping 2–15-day trades: Newey–West lag selection (fixed versus data-driven), Hansen–Hodrick, and block bootstraps (stationary or circular), including small-sample behavior.
2. Alpha tests versus Sharpe-ratio tests for a long-only strategy whose market exposure varies over time; whether to add factors beyond the market.
3. The Deflated Sharpe Ratio: exact formula and inputs (number of trials, variance of trial Sharpe ratios, skewness, kurtosis, sample length); how to handle unknown variance for earlier trials; sensitivity analysis; and the relationship to minimum track record length.
4. Sequential testing: group-sequential designs and alpha-spending functions (O'Brien–Fleming, Pocock, Lan–DeMets) versus Bonferroni for three or four looks, including futility stopping rules.
5. Power: for plausible annual alpha of 2–6% and tracking error typical of a concentrated long-only large-cap swing portfolio, how much data each look needs for adequate power.
6. Whether requiring both a t-statistic threshold and DSR ≥ 0.95 is redundant or complementary, and whether 150 closed trades is a sensible floor.
7. Whether the Probability of Backtest Overfitting (combinatorially symmetric cross-validation) means anything when only one frozen configuration is evaluated.
8. For future challenger models (labels spanning up to 15 trading days): recommended purging and embargo settings for walk-forward evaluation.

Deliverables:
- A recommended test protocol with formulas, parameter choices, and justifications.
- A worked numerical example (for instance, 3% annual alpha, 10% tracking error, 252 trading days a year) showing the t-statistic and DSR at each look.
- Specific changes to the plan above, ranked by importance.

Standards: give a link for every method and claim. Prefer peer-reviewed statistics and finance sources, and state your confidence.
```

---

## Priority B — before Steps 4–5

### RQ-05 — Honest daily-bar simulation of limit entries and bracket exits

**Informs:** PREREGISTRATION.md §1 (label simulation); Step 5 bracket simulator

```text
Context: I'm an individual backtesting a personal, long-only swing strategy in S&P 100 stocks on daily bars, with minute bars possibly available for recent years. Entries are buy-limit orders placed for the next session, usually below the prior close (pullback entries). Exits are a broker-held stop-loss and take-profit placed as a bracket, plus a time exit at the close of the 15th trading day. The broker is Alpaca. Use sources current as of September 2026.

Research question: Which simulation rules produce honest rather than optimistic results for this order logic, and how large are the biases if I get them wrong?

Cover:
1. Limit-fill modeling: touch versus trade-through requirements, queue position, partial fills, and adverse selection (passive buy limits fill more often when prices keep falling). Empirical fill-rate evidence for non-marketable limit orders in liquid large caps.
2. Same-bar ambiguity: when the stop and the target, or the entry and the stop, both fall within one daily bar. Which conventions exist, how biased each is, and when minute bars can resolve the order of events.
3. Gaps: fills when the open gaps through a stop or target; opening auction behavior; stop-market versus stop-limit behavior on gaps.
4. Broker behavior: how stop orders are typically triggered (last sale versus quote), and how Alpaca implements bracket orders (order types allowed for each leg, time-in-force options, one-cancels-other behavior, what happens to open orders at splits and dividends, and behavior during trading halts). Use Alpaca's current documentation.
5. Other biases: stop levels computed from adjusted prices, survivorship, look-ahead from signals that use the same day's close, and holiday or half-day handling.
6. Validation: how to compare a simulator against paper or live fills.

Deliverables:
- A spec-ready rule set, one rule per line, covering entries, exits, gaps, ambiguous bars, and corporate actions. Choose the conservative option wherever evidence is thin.
- The estimated size of each bias (bps per trade or share of trades affected) where evidence exists.

Standards: give a link for every factual claim, including Alpaca documentation links for broker-specific behavior. Flag anything you could not verify.
```

### RQ-06 — Transaction cost model

**Informs:** Step 4 cost model; PREREGISTRATION.md §1 (costs)

```text
Context: I'm an individual running a personal, long-only swing strategy in S&P 100 stocks through Alpaca, with small orders (roughly $1,000–$50,000 each) held 2–15 trading days. I need a cost model for backtests covering roughly 2000–2026, and for realistic expectations today. Use sources current as of September 2026.

Research question: What should a realistic, time-varying transaction cost model look like for this setup?

Cover:
1. Alpaca's current commission and fee schedule for US stocks, including any regulatory fees passed through to customers, with documentation links.
2. Regulatory fees on sales: the current SEC Section 31 fee rate and its history, the FINRA Trading Activity Fee, and any Consolidated Audit Trail fees passed to customers. How to model them historically.
3. Spreads: typical quoted and effective spreads for S&P 100 stocks today by time of day (open, midday, close), and how they have changed since 2000. Methods for estimating historical spreads from daily data (e.g., Corwin–Schultz, Abdi–Ranaldo) and how accurate they are for large caps.
4. Slippage and price improvement for retail-size limit and marketable orders, including Alpaca's order routing and any published execution-quality statistics (e.g., SEC Rule 605 and 606 reports).
5. Market impact at these order sizes: whether it is negligible, and the evidence for that.

Deliverables:
- A parameter table: component, current value, how to treat it historically, source, link, and date checked.
- A recommended backtest cost formula with a conservative setting and a central setting.
- A short note on which cost components matter most for this strategy.

Standards: give a link for every factual claim, prefer official and primary sources, and give the date you checked each fee.
```

---

## Priority C — before any text scoring

### RQ-07 — Test design and statistical power for text signals

**Informs:** PREREGISTRATION.md §3–5

```text
Context: I'm an individual running a personal research project on S&P 100 stocks (long-only, daily decisions after the close, holds of 2–15 trading days). A recorder captures news articles for every stock in the index with first-seen timestamps. I will compare three versions of my model: (A) a price-based ranker alone; (B) the ranker plus FinBERT-style sentiment; (C) the ranker plus that sentiment plus a locally run LLM's structured score (direction, materiality, event type). The current plan tests only the ranker's candidate stock-days (about 1,000 a year) against multi-day returns, which may lack statistical power. An alternative first test would use every stock-day in the universe (about 25,000 a year, roughly half with news) at a short horizon. Use sources current as of September 2026.

Research question: What is the most powerful valid design for testing whether (1) cheap sentiment and (2) the LLM's signal add predictive value, given this sample size?

Cover:
1. Pooled panel regressions versus Fama–MacBeth versus portfolio sorts for daily cross-sections of about 100 stocks. Standard errors: clustered by date, two-way by date and stock, and Driscoll–Kraay.
2. What to predict: raw, market-adjusted, beta-adjusted, or characteristic-adjusted returns, and at which horizon (1, 2, 5, or 10 days), including corrections for overlapping horizons.
3. Controls: short-term reversal, momentum, abnormal volume, volatility, earnings-announcement periods, and news volume itself. How to handle stock-days with no news.
4. Combining several articles for the same stock and day (mean, materiality-weighted, most recent, novelty-filtered), and removing duplicate or re-published articles.
5. Nested tests showing the LLM adds value beyond FinBERT (incremental R², encompassing tests, coefficient tests), and handling multiple comparisons across versions and horizons.
6. Power: the minimum detectable effect in bps for each design after 6, 12, and 24 months of data, using realistic return dispersion and cross-stock correlation.
7. Sequential looks with alpha spending and futility rules for this design.
8. Turning a statistically significant signal into value for a 2–15-day swing strategy (as a filter or as a sizing input), and how to test that second step.

Deliverables:
- A recommended two-stage design (an information test, then a strategy test) with exact regression specifications.
- A power table by design and amount of data.
- A list of pitfalls.

Standards: give a link for every method and claim, prefer peer-reviewed sources, and state your confidence.
```

### RQ-08 — News feed quality and personal-use terms

**Informs:** PREREGISTRATION.md §1 (text eligibility) and §3–4 (aggregation and filters); any future training use (Q4)

```text
Context: I'm an individual running a personal research project on S&P 100 stocks. My news source is Alpaca's News API, which provides Benzinga news (a historical archive plus current articles). A recorder stores each article version with my own first-seen timestamp. Use sources current as of September 2026.

Research question: How reliable is this news feed for research on S&P 100 stocks, and what do its terms allow for personal use?

Cover:
1. Access: which Alpaca plans include news access, and at what rate limits.
2. Coverage: typical articles per large-cap stock per day; the share of automated or templated articles (price-move recaps, options-activity notes, analyst-rating summaries, earnings previews); how articles are tagged with stock symbols, and how accurate that tagging is (e.g., articles tagged with many tickers).
3. Timestamps: how Benzinga's created and updated times relate to actual publication, typical delays, and how often and how substantially articles are revised.
4. Historical archive: completeness since 2015, changes in coverage over time, and whether historical queries return the latest version of revised articles.
5. Prior research use: studies or practitioner write-ups that used Benzinga data, and the data-quality problems they reported.
6. Filters: recommended rules for removing articles that only restate price moves, and duplicates, with evidence on how those filters affect signal quality.
7. Supplementary sources suitable for personal use with reliable timestamps (e.g., SEC EDGAR filings with acceptance times, company press releases, GDELT), and what each is good for.
8. Terms: what Alpaca's market data terms, and any Benzinga terms that apply, allow for a personal user: storing articles locally, using them in my own trading research, and using them to train or fine-tune a model. Include any sharing limits. Quote the relevant clauses with links.

Deliverables:
- A data-quality assessment listing specific risks and mitigations.
- A recommended set of article filters.
- A plain-language summary of what the terms allow, with clause links, plus anything I should confirm directly with Alpaca.

Standards: give a link for every factual claim, prefer official documentation, and flag anything you could not verify.
```

### RQ-09 — Look-ahead bias protocol for LLM signals

**Informs:** PREREGISTRATION.md §1 (evidence windows) and §5 (historical evidence rules)

```text
Context: I'm an individual running a personal research project that will test whether a locally run large language model's reading of news adds predictive value for S&P 100 stock returns. Models trained on internet text may have memorized what happened to stocks during their training period, which inflates historical test results. My main test will use only news captured after the model was released, but I would also like trustworthy supporting evidence from history. Use sources current as of September 2026.

Research question: What is the best-practice protocol for measuring and avoiding look-ahead (memorization) bias when evaluating LLM-based trading signals?

Cover:
1. Findings and methods from recent work, including Lopez-Lira, Tang & Zhu (2025) on memorization in economic forecasts; Gao, Jiang & Yan (2025) on detecting look-ahead bias with a recall-interaction test; He, Lv, Manela & Wu (2025) on chronologically consistent language models (ChronoBERT, ChronoGPT, and instruction-tuned variants); and any newer work.
2. Step-by-step implementation of the recall-interaction test: the recall query, the regression, sample-size needs, and how to interpret results.
3. Chronologically consistent or "vintage" models available today: where to get them, licenses for personal use, capability limits, hardware needs, and how to use them as a bias check against a modern model of similar size.
4. Estimating an open-weight model's effective knowledge cutoff when the developer doesn't document it, and how reliable the release date is as an upper bound.
5. Whether masking company names or dates, or instructing the model to ignore later knowledge, reduces the bias, and the evidence that it does not.
6. Other leakage paths: fine-tuning data that contains outcomes, prompts that include prices, news archives that return revised article text, and evaluation periods that overlap the model's training data.
7. A recommended protocol for (a) forward-only evaluation and (b) supporting historical evidence.

Deliverables:
- A written protocol with explicit decision rules.
- A table of available chronologically consistent models, with links and licenses.

Standards: give a link for every factual claim, prefer peer-reviewed and primary sources, and label working papers.
```

### RQ-10 — Choosing the pinned local LLM and FinBERT variant

**Informs:** SCOPE.md OD-3; PREREGISTRATION.md §3–4 (arm B and arm C configurations)

```text
Context: I'm an individual running a personal research project on S&P 100 stocks. I need one locally run language model, fixed at a specific version, to score news articles into a fixed JSON format (direction from −1 to 1, materiality from 0 to 1, and an event type from a fixed list), plus a cheap FinBERT-style sentiment model as a baseline. The language model must have been publicly released before my news recorder's first capture (expected around late September 2026), so its weights cannot contain later information. Hardware: one consumer GPU, targeting 24 GB of VRAM, with notes on 12 GB options, on Windows or Linux. Volume: up to a few hundred short articles a day. Use sources current as of September 2026.

Research question: Which open-weight models best fit this extraction task under these constraints?

Cover:
1. Candidate open-weight models released before late September 2026, roughly 3B–32B parameters, that fit the hardware with quantization. For each: release date, documented training-data cutoff (if any), and license terms for personal use.
2. Evidence of quality on financial language tasks (sentiment, event classification, information extraction) from benchmarks such as FinBen, FLUE, or FiQA and from independent evaluations. Note the risk that benchmark data leaked into training.
3. Reliability of structured output: support for grammar- or schema-constrained decoding (e.g., llama.cpp grammars, vLLM guided decoding, Ollama structured outputs) and observed JSON validity rates.
4. Speed and memory use at common quantization levels (e.g., Q4, Q5, and Q8 GGUF, AWQ, GPTQ) on 24 GB and 12 GB cards.
5. Repeatability: how to get identical outputs across runs (temperature 0, seeds, batch-size effects, GPU nondeterminism), and how to verify it.
6. FinBERT options: the main variants, what each was trained on, availability in ONNX or quantized form, input-length limits, and known weaknesses on modern news.
7. Whether a general instruction-tuned model or a finance-tuned model is likely to be stronger for this task, with evidence.

Deliverables:
- A shortlist table: model, parameters, release date, documented cutoff, license, VRAM at the chosen quantization, finance-task evidence, structured-output support, and link.
- A recommended primary model, one backup, and a recommended FinBERT variant, with reasons.
- A short test plan to confirm the choice on my own articles without looking at any stock returns.

Standards: give a link for every factual claim, prefer official model cards and peer-reviewed evaluations, and flag anything you could not verify.
```

---

## Priority D — before the live lane

### RQ-11 — Alpaca brokerage mechanics and personal account rules

**Informs:** Live-lane design (SCOPE.md §3.2, invariants I-1, I-2, I-9, I-10, I-12); OD-1

```text
Context: I'm an individual planning, for later, to run a personal long-only swing strategy in S&P 100 stocks through Alpaca with real money. Each trade will have one limit entry plus broker-held stop-loss and take-profit orders. My software will reconcile against the broker and must leave positions protected if it crashes. The account will be a regular individual taxable brokerage account with default tax treatment. Use sources current as of September 2026.

Research question: What do I need to know about Alpaca's brokerage mechanics and the rules for a small individual account to run this safely?

Cover:
1. Bracket, one-cancels-other, and one-triggers-other orders on Alpaca: order types allowed for each leg, time-in-force options and expirations, what happens to the exit legs when an entry fills only partially, and extended-hours behavior.
2. Order lifecycle and reconciliation: trade-update stream event types, ordering and delivery guarantees, idempotency with client order IDs, recovery after disconnects, and the REST endpoints for orders, positions, and account activity.
3. Corporate actions and halts: how open orders and positions are adjusted for splits, dividends, and mergers, and what happens to stop orders during trading halts and limit-up/limit-down pauses.
4. Paper versus live trading: how paper trading simulates fills, and where it differs from live trading.
5. Rate limits, API key permissions, and security practices (separate keys, key rotation, any IP restrictions).
6. Account type for a small individual account: cash versus margin; the current day-trading rules, including FINRA's new intraday margin rule and how Alpaca applies it; T+1 settlement and good-faith or free-riding violations in cash accounts; and how a same-day stop-out interacts with these rules.
7. Taxes under default individual treatment: how the wash-sale rule applies to a strategy that frequently re-enters the same 100 stocks, how brokers report wash sales, and practical ways to track them.
8. Operational safety: whether Alpaca offers cancel-on-disconnect or similar protections, and recommended patterns for a system run by one person.

Deliverables:
- A constraints checklist for the live system, each item with a documentation link.
- A cash versus margin comparison for this strategy, with a recommendation.
- Open questions to confirm directly with Alpaca support.

Standards: give a link for every factual claim, prefer Alpaca's official documentation and regulator sources, give the date you checked each rule, and flag anything you could not verify.
```

---

## Follow-up — from the research log's verification queue

### RQ-12 — Verify quoted values from key papers

**Informs:** planning priors in PREREGISTRATION.md (effect-size and power scenarios); corrections to the research log

```text
Context: I'm an individual running a personal, research-first systematic trading project (long-only swing trading in large-cap US stocks). My research log quotes specific numbers from several papers, and I need them checked against the original sources before I rely on them. Use sources current as of September 2026.

Research question: Are these quoted values accurate, and in what context do they apply?

Check each against the original paper (tables, figures, and text). Report the exact value, where it appears, the sample and specification it comes from, and any caveat that changes its interpretation:
1. Lehmann (1990): weekly loser-minus-winner reversal return of about 1.79%.
2. Jegadeesh (1990): monthly abnormal loser-minus-winner decile spread of about 2.49%.
3. de Groot, Huij & Zhou (2012): for the 100 largest US stocks, 1990–2009, weekly reversal of about 77.9 bp gross and more than 50 bp after trading costs, with t-statistics of about 9.4 and 6.4.
4. Tetlock, Saar-Tsechansky & Macskassy (2008): for S&P 500 firms, a one-standard-deviation increase in negative Dow Jones News Service language associated with about −3.2 bp next-day abnormal return (t about −5.32).
5. Heston & Sinha (2017): a daily long-short news-sentiment return of about +17 bp on day 1; t-statistics of about 63.9 (day 0), 9.8 (day 1), and 2.5 (day 2); and a small-firm weekly difference of about 224 bp.
6. Ke, Kelly & Xiu (2019): daily long-short returns of about 33 bp equal-weighted and 10 bp value-weighted, with Sharpe ratios of about 4.29 and 1.33.
7. Lopez-Lira & Tang (2023, revised 2025): the reported next-day return for positive GPT scores, and the t-statistics for all stocks versus non-small stocks.
8. Lopez-Lira, Tang & Zhu (2025): the current title, identifier, and main findings on memorization, including results for prominent large-cap stocks.

Deliverables:
- A table: claim, verified value, location in the paper, sample and specification, match (yes, no, or partly), and corrected wording where needed.
- A direct link to each paper (DOI or official working-paper page) and the version checked.

Standards: use the original papers, not summaries or blog posts. If a paper is inaccessible, say so rather than inferring the value.
```

### RQ-13 — Free reconstruction of S&P 500 membership, and the reach of survivorship bias

**Informs:** PREREGISTRATION.md §2.4 (exploratory historical check); SCOPE.md Step 3

```text
Context: I'm an individual running a personal, research-first systematic trading project: long-only swing trading in large-cap US stocks, daily decisions, holds of 2 to 15 trading days. I decided not to buy a survivorship-free historical data subscription, so my only backtests use free sources: Alpaca daily bars from 2016 and today's index membership. I need to know how wrong that makes a backtest, and how much of the gap free sources can close. Use sources current as of September 2026.

Research question: How can S&P 500 membership history be reconstructed from free public sources, and how large is the remaining survivorship and look-ahead bias in a backtest that uses it?

Cover:
1. Free or near-free sources for historical S&P 500 constituent changes with effective dates: S&P press releases, exchange notices, Wikipedia revision history, SEC filings, and any public datasets. How complete and reliable is each, and how far back does it go?
2. Prices for companies that were removed from the index (acquired, delisted, or demoted): which free sources still serve them, and what typically goes missing.
3. Published estimates of survivorship bias magnitude in US large-cap backtests: annualized return overstatement by strategy type, holding period, and era.
4. Whether the direction and rough size of the bias can be bounded for a long-only, short-horizon strategy in large caps, and how to report that bound honestly.
5. Look-ahead bias from using today's membership: how much of the effect comes from index-addition and deletion drift, and how studies handle it.
6. Practical checks to detect how badly a specific backtest is affected, for instance comparing results on names that stayed in the index against names that left.

Deliverables:
- A table of free membership sources: coverage start, completeness, update mechanism, effort to use, and link.
- A recommended reconstruction method with its known gaps.
- A defensible way to state the bias in results, for example a bounded range instead of a single number.
- Guidance on what conclusions such a backtest can and cannot support.

Standards: give a link for every factual claim, prefer peer-reviewed research and primary sources, and flag anything you could not verify.
```

---

## Verification queue (direct checks, not deep research)

These come from the research log's open questions. They are answered by asking a vendor, running a trial, or measuring our own data.

**Alpaca, in writing (SCOPE OD-8).**
- News rights (R08): local storage of article text; embeddings, feature stores, and model training; keeping derived features after access ends; any Benzinga addendum; what `created_at` and `updated_at` mean, and whether historical queries return revised text; sharing aggregate results.
- Brokerage (R11): cash-account availability; intraday buying-power rules after the FINRA change; bracket protection when a parent order partially fills; handling of open brackets through splits, special dividends, mergers, and symbol changes; GTC expiry; cancel-on-disconnect or a kill switch; trade-update delivery guarantees and REST activity history; API key scoping, rotation, and IP allowlists.

**Paid historical data (SCOPE D-013): deferred.** No vendor is being bought, so Q1 runs forward-first. If the forward information test shows a signal worth confirming on clean history, reopen this with the Norgate Platinum trial checks: daily S&P 100 and S&P 500 membership back to 2000 or earlier including share classes; delisted securities through the right dates; a stable security identifier in the Python interface; and license terms for local storage, backups, and derived features.

**Own-data measurements.**
- Step 3: return dispersion and cross-stock correlation by horizon.
- Recorder: article frequency, novelty and recap shares, tag breadth, first-seen delays, and revision rates.
- Simulator and paper shadow: fill, partial-fill, gap-stop, and ambiguity rates.
- Q1 scenarios: tracking error of the frozen equity curve.

**Deferred until needed.** Vintage-model checkpoint licenses and cutoff provenance (SCOPE §3.3).

---

## Answered in chat instead (no deep research needed)

These are engineering or setup questions Claude can answer directly when their step arrives:

- Always-on host options for the live lane (OD-2).
- Storage format for the data plane (e.g., Parquet with DuckDB) and trial-registry schema.
- Exchange calendar handling (holidays and half-days).
- Risk-free rate and benchmark data (FRED `DTB3`, SPY total return).
- Healthchecks.io and Task Scheduler setup (already covered in the S01 runbook).

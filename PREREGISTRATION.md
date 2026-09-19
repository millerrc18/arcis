# PREREGISTRATION.md — Research Questions

| | |
|---|---|
| **Status** | DRAFT v0.4 (2026-09-17). Frozen once tagged `prereg-v1`. |
| **Tag deadline** | Before Step 3 begins (SCOPE.md §5) |
| **Governs** | Q1 (incumbent edge), Q2 (cheap text), Q3 (LLM). Q4 is reserved. |
| **Evidence base** | `docs/research/research-log.md`: R04 (Q1 protocol), R05–R06 (simulation and costs), R07–R10 (text questions) |

Items marked **⟨CONFIRM⟩** must be settled before tagging. Items marked **⟨STEP 2⟩** are filled in from the carry-forward inventory before tagging.

---

## 0. Rules

1. Once tagged, no section changes after the data it governs has been examined. Amendments made after tagging, but before that data is examined, go in §5 with a date and reason.
2. Any analysis not specified here is exploratory. Exploratory results can motivate a new registered question; they never open or close a gate.
3. Every economically distinct variant, dataset choice, filter, parameter sweep, and selection rule ever tested goes in the trial ledger, including the old platform's (Step 2). Old variants whose daily returns cannot be recovered are recorded as unknown, never estimated.
4. Before tagging, freeze and record: configuration, code hash, data snapshot hash, cost model, factor tables, look calendar, minimum economic effect, and reporting template.
5. Questions are evaluated only at their scheduled looks. The registry logs every evaluation with its timestamp, code hash, and data hash. An unlogged evaluation is a protocol breach and is recorded in §5.
6. Sequential boundaries come from a named, version-pinned software package. Its inputs and outputs are archived before the first look. No hand-calculated critical values.
7. Results are reported whichever way they come out, including results that end a line of work.

## 1. Shared definitions

| Term | Definition |
|---|---|
| Universe | Point-in-time S&P 500, with the S&P 100 reported as a benchmark subset (SCOPE D-012). Forward membership comes from the recorder's daily universe snapshots |
| Decision time `t_d` | 16:30 ET on trading day `t` ⟨CONFIRM⟩. Everything used for a decision must be available before `t_d` |
| Incumbent | `incumbent_v1` as ported in Step 2, frozen by hash ⟨STEP 2⟩. Any change creates a new trial |
| Candidate-day | A (symbol, `t`) pair the incumbent qualifies at `t_d` |
| Label | Net return from applying the incumbent's entry and exit rules to one stock-day under §1.1 and §1.2. The rules are mechanical, so every universe stock-day carries a label, whether or not the ranker qualified it |
| Risk-free rate | 3-month Treasury bill (FRED `DTB3`), converted to a daily rate |
| Benchmark | SPY total return |
| Earnings window | ⟨CONFIRM⟩ No new entry from one trading day before through one trading day after an earnings date whose release timing is unknown (R02). Once confirmed, this rule is part of the frozen incumbent definition |

### 1.1 Simulator: the decision specification (R05)

**Order levels**
- Entry, stop, target, and time-exit levels use raw, unadjusted prices known at the prior close. The signal uses the final close of day `t`; nothing fills on the signal bar.

**Entries**
- One buy-limit order for the next regular session; no extended-hours fills. Fills are all-or-none.
- Open above the limit: the order fills only if the day's low is strictly below the limit, at the limit price. A low equal to the limit is not a fill.
- Open at or below the limit ⟨CONFIRM⟩: proposed primary rule is a fill at the open plus an adverse buffer, never above the limit. Reported sensitivities: fill at the limit, and no fill (the research log's default).
- In simulation, a partially filled entry is treated as unprotected.

**Exits**
- Adverse buffer: the larger of one tick and the estimated half-spread, replaced by calibrated slippage from earlier paper or live fills when available.
- Take-profit fills only if the high is strictly above the target, at the target. An open above the target fills at the target.
- Stop-market triggers when the low is at or below the stop and fills at the stop minus the buffer. An open below the stop fills at the open minus the buffer.
- A stop-limit leg, if used, is never assumed to fill after it triggers.
- Entry day: a low at or below the stop means a stop-out, because the price must pass through the entry limit before reaching a stop below it. The take-profit does not fill on the entry day unless minute bars show the target was reached after the fill.
- Later days: if both stop and target are reachable within one bar, the stop fills first. Minute bars do not change this for events inside the same minute.
- Time exit on the 15th trading session: open bracket legs are cancelled and a market-on-close order is modeled. If the cutoff cannot be met, the exit is at the next executable regular-session price and is flagged.
- Sessions follow the official exchange calendar; half-days use their shortened session.

**Corporate actions**
- Ordinary cash dividends do not adjust bracket prices (Alpaca brackets are Do Not Reduce). Stops triggered by an ex-dividend price drop are simulated as they would occur and also reported separately.
- Splits: open orders are cancelled and reissued at the ratio-adjusted quantity and price, and the trade is flagged, until Alpaca's split handling is verified.
- No new entries from the session before a special dividend, spin-off, merger, symbol change, delisting, or halt until it is resolved.

**Recording**
- Every simulated decision records raw prices, adjustment mode, fill rule, and ambiguity, gap, and corporate-action flags.
- For every signal: next-open counterfactual return, filled and unfilled outcomes, fill rate, maximum adverse and favorable excursion, and time to exit.

### 1.2 Costs (R06)

- Primary: the R06 conservative model. The central model is a sensitivity only.
- Regulatory fees follow the exact dated SEC Section 31 and FINRA TAF schedules. CAT fees apply only from a verified broker schedule.
- Commissions: zero for the modern-execution counterfactual, plus $5 and $10 per order as historical-retail sensitivities for years before Alpaca existed.
- Spreads: a daily proxy from the larger of the Corwin–Schultz and Abdi–Ranaldo estimates (21-session trailing median, tick floor applied), with R06's time-of-day multipliers. Data before April 2001 (pre-decimalization) is reported separately.
- No generic adverse-selection charge is added on top of strict passive fills, because the realized price path already contains it.
- Paper and live fills calibrate buffers only from periods before the data being tested.

### 1.3 Text eligibility and filters (R08)

- **Forward:** an article version is eligible for stock-day (`s`, `t`) if `s` is among its point-in-time-mapped `symbols` and the recorder first saw that version before `t_d`. Text used for scoring must match the recorded fingerprint.
- **Historical:** both `created_at` and `updated_at` precede `t_d`, and results count only as supporting evidence (§3.5).
- One representative per novelty cluster: same issuer, event class, and similar headline or body within a trailing 24 hours; the earliest first-seen version wins.
- Price recaps, analyst-rating and price-target notes, options activity, earnings previews and recaps, technical summaries, and ETF or macro stories are labeled as event classes and either excluded or modeled separately.
- Automated or templated stories are flagged.
- Excluded: articles created after the cutoff, future-dated metadata, a missing headline or body, and unresolved symbol mappings.
- The primary sample keeps all tagged articles, with tag breadth and issuer relevance as controls. A strict issuer-specific sample (ticker or issuer named in the headline or lead) is secondary.
- Every filter reports its retained counts and coverage. Filters are never chosen for their effect on return tests.

### 1.4 Evidence windows (R09)

- A model's release date is an upper bound on its training data. That supports forward evaluation on articles first seen after release; it does not establish an earlier cutoff.
- Efficacy claims for a modern model come only from forward data.
- Historical results for a modern model are diagnostics. The recall-interaction test classifies them as contaminated, no detected contamination, or unsupported, and a null diagnostic is not proof of cleanliness.
- Historical efficacy evidence may come only from models with a documented cutoff strictly before the article date (vintage models; SCOPE §3.3).
- Masking names or dates, and instructing a model to ignore later knowledge, are diagnostic ablations, not fixes.

---

## 2. Q1 — Does the incumbent ranker have a net edge?

**Why this section changed.** With no survivorship-free history before 2019 (SCOPE D-013), Q1 has no clean historical holdout. Forward portfolio-alpha testing cannot substitute for one: at 10% tracking error, a three-year window reaches 80% power only for an annual alpha near 16% (R04's formula). Q1 therefore takes the same shape as the text questions. A forward information test, which this sample size can actually decide, gates the answer. Portfolio alpha is monitored, never treated as proof.

### 2.1 Stage A — Forward information test (primary, gating)

- **Rows:** every universe stock-day from the `prereg-v1` tag onward. Prices for this window can be pulled later, so the clock starts at the tag, not when the code is finished.
- **Outcome:** the mechanical net label (§1.1, §1.2) for that stock-day. Unfilled entries are counted and excluded from the return comparison; the unfilled rate is reported by group.
- **Model:** `label = δ_t + b_Q·Qualified + b_S·(Score × Qualified) + γ'X + ε`, with date fixed effects and standard errors clustered by date, plus a date-block bootstrap.
- **Controls `X`:** prior 1-, 5-, 20-, and 60-day returns; abnormal volume; realized volatility; market-cap and liquidity buckets; sector; earnings-window indicator.
- **Primary hypothesis:** `b_Q > 0`. In plain terms: on the same day, names the ranker qualifies beat the same mechanical trade on names it did not qualify, after costs.
- **Secondary:** `b_S > 0`, that the score ranks within the qualified set. Reported, never a gate on its own.
- **Looks:** 12 months for data quality and nonbinding futility; 24 months for efficacy, one-sided α = 2.5%. Futility at 12 months if the conditional power under the minimum effect is below 10%.
- **Minimum effect worth having:** a point estimate of at least 25 bp net per trade ⟨CONFIRM⟩, alongside the significance threshold.
- **Power:** the minimum detectable effect is computed on the actual panel before tagging, using measured dispersion and within-date correlation, and recorded here.
- **Pass:** `b_Q` clears the threshold at 24 months and the point estimate is at least the minimum effect.
- **Fail:** `b_Q` point estimate is at or below zero at either look, or no pass at 24 months.

### 2.2 Stage B — Execution and replication (gating for capital)

Runs only after Stage A passes.

- **Simulator fidelity:** paper or live fills match the frozen simulator within a preregistered tolerance for slippage, fill rate, and stop behavior, over at least 150 closed trades ⟨CONFIRM⟩.
- **Portfolio simulation** on the same forward window is reported with confidence intervals. It must show a positive point estimate, a drawdown inside the preregistered limit, and exposure and concentration inside their caps. It carries no significance requirement, because none is attainable at this sample size.
- **Capital authorization** requires Stage A pass, Stage B pass, and the risk limits in §2.3. This charter records plainly that capital would be committed while portfolio-level alpha remains statistically unproven.

### 2.3 Risk limits where proof is unattainable

- The first real-money amount is small enough that losing all of it changes nothing important ⟨CONFIRM, SCOPE OD-4⟩.
- **Kill rule:** trading stops and the strategy returns to research if the live equity curve draws down more than ⟨CONFIRM⟩ percent from its start, or if the 90% upper bound on live net edge per trade falls below zero after ⟨CONFIRM⟩ closed trades.
- **Scaling:** increases happen only in preregistered steps, each requiring a stated amount of additional forward evidence with the estimate holding ⟨CONFIRM⟩.

### 2.4 Exploratory historical check (non-gating, asymmetric)

- **Data:** Alpaca daily bars from 2016, using current membership. Two known biases: survivorship inflates results, and the period overlaps data the old platform already used for tuning.
- **Use:** this check can retire the incumbent. It can never authorize capital.
- **Preregistered kill rule:** if the net alpha point estimate over the available history is at or below zero under the conservative cost model, the incumbent is retired and redesign begins. A favorable result is recorded and changes nothing.
- The direction and, where estimable, the size of the survivorship bias are reported with the result.

### 2.5 Portfolio alpha monitoring (non-gating)

- The exposure-matched active return `a_t = (r_p,t − r_f,t) − b_t × (r_SPY,t − r_f,t)` is tracked, where `b_t` is the ex-ante market beta from prior-day weights and rolling stock betas (window ⟨CONFIRM⟩, proposed 252 sessions).
- Inference for reporting: Bartlett-kernel Newey–West with `L = floor(4 × (T/100)^(2/9))` lags, capped at 20, from a version-pinned function; sensitivities at 5, 10, 15, and 20 lags and a stationary bootstrap (at least 10,000 draws; automatic block length plus 10, 15, 20, and 30 sessions).
- Sequential boundaries (Lan–DeMets O'Brien–Fleming, one-sided 2.5%, generated under §0 rule 6) are drawn for context. Crossing one is supportive evidence; failing to cross one means nothing, because the test lacks the power to detect a modest edge.
- Tracking-error scenarios of 8%, 10%, and 15% are replaced by the measured value once the frozen equity curve exists.

### 2.6 Multiplicity and reporting

- **Deflated Sharpe Ratio:** a multiplicity audit, not a gate. Reported over a grid of trial counts (known, and known plus unknown), annualized cross-trial Sharpe dispersion of 0.25, 0.50, and 1.00, and low- and high-correlation effective trial counts.
- **Not computed:** Probability of Backtest Overfitting, since only one frozen configuration is evaluated.
- **Descriptive only:** fill and unfilled rates, hit rate, maximum drawdown, exposure, turnover, ambiguity rate, and results by market-cap, liquidity, volatility, and regime buckets, with the S&P 100 subset reported separately.

---

## 3. Q2 and Q3 — Does text carry information, and does the LLM add more?

### 3.1 Arms

- **B, FinBERT:** ProsusAI/finbert, ONNX INT8, pinned by hash. Per article: P(positive) − P(negative) on the headline plus the first one or two sentences ⟨CONFIRM⟩. The FinBERT feature never uses LLM output.
- **C, LLM:** one pinned general instruction model (SCOPE OD-3). Weights hash, quantization, tokenizer, system prompt, decoding settings, schema version, and code hash are frozen before the first scored article. Per article, schema-constrained output: `direction` in [−1, 1], `materiality` in [0, 1], and `event_type` from a fixed enum.
- **Repeatability gate, before first scoring:** five clean runs over a 1,000-article corpus with at least 99.5% parsed-label agreement, numeric drift within a preregistered tolerance ⟨CONFIRM⟩, and 100% schema validity.
- **Runtime failures:** any schema failure, timeout, or out-of-range value records `LLM_SCORE_UNAVAILABLE` and is counted (SCOPE I-14). If more than 5% of news-bearing stock-days lack an LLM score at a look, that look is void and the configuration must be fixed as a new trial.

### 3.2 Stage A — Information test (primary)

- **Rows:** every universe stock-day, with or without news.
- **Aggregation** over eligible, novelty-filtered articles per stock-day: `F` = mean FinBERT score; `L` = mean of direction × materiality; `N` = 1 if any eligible article exists.
- **Outcome:** one-day forward return from the first tradable post-close point, beta-adjusted ⟨CONFIRM; sector-adjusted is the alternative⟩. Raw return is secondary.
- **Model:** `r = α_i + δ_t + b_R·R + b_F·(N·F) + b_L·(N·L) + b_N·N + γ'X + ε`, with stock and date fixed effects.
- **Controls `X`:** prior 1-, 5-, 20-, and 60-day returns; abnormal volume; realized volatility; overnight return; sector return; earnings-window indicators; analyst-action indicator; article count; unique-story count; source and event-type controls.
- **Estimation:** pooled fixed-effects panel, standard errors clustered by stock and date, plus a date-block bootstrap. Fama–MacBeth is a secondary check; Driscoll–Kraay is a 24-month sensitivity.
- **Hypotheses:** Q2 is `b_F > 0` in the model without the LLM term. Q3 is `b_L > 0` in the full model. They are co-primary, tested one-sided with Holm control at a family α of 2.5%.
- **Looks:** 6 and 12 months for data quality and nonbinding futility only. Efficacy is judged once, at 24 months.
- **Secondary:** a two-day horizon as confirmation; five- and ten-day horizons as exploratory, with non-overlapping robustness checks; alternate aggregators (unweighted mean, most recent, maximum absolute score, novelty-weighted first report, six-hour half-life) reported but never optimized. Secondary families use Holm or Romano–Wolf control.
- **Supporting:** chronological out-of-sample R² and Clark–West comparisons.
- **Planning power:** R07's scenarios for a 100-name panel give minimum detectable effects of about 9.9, 7.0, and 4.9 bp at 6, 12, and 24 months, against realistic one-day effects of about 3–8 bp (R03). The S&P 500 panel improves on this by less than the row count suggests, because same-day moves are correlated. The real figure is simulated on the actual panel before tagging and recorded here.

### 3.3 Stage B — Strategy test (only after Stage A)

- **Rows:** incumbent candidate-days, with identical fills, costs, exits, and position caps across arms.
- **Filter test first:** exclude candidates whose score falls in the bottom third of its trailing 252-day distribution ⟨CONFIRM; must be fixed before any Stage A result is seen⟩.
- **Sizing test second:** a monotonic map from standardized score to position weight, with unchanged exposure and single-name caps ⟨CONFIRM; fixed before any Stage A result is seen⟩.
- **Inference:** a paired date-block bootstrap of daily portfolio excess returns and factor alpha.
- **Pass:** incremental value after costs, with no deterioration in tail losses, concentration, or capacity.

### 3.4 Outcomes

| Stage A | Stage B | Result |
|---|---|---|
| Q3 passes | Passes for C | The LLM becomes a live-path candidate, still subject to the live-lane gates; Q4 may be registered |
| Q3 passes | Fails for C | The LLM moves to CUT: information without strategy value |
| Q3 fails | — | The LLM moves to CUT |
| Q2 passes | Passes for B | FinBERT enters the challenger queue as a feature |
| Q2 and Q3 fail | — | All text features move to CUT |

### 3.5 Historical supporting evidence

Historical text results never open or close a gate. They are reported only with the evidence-window classification in §1.4.

---

## 4. Reserved and future rules

**Q4 — Does fine-tuning add value over the base model of the same family?** Registered only if Q3 and its strategy test pass. Until then, no fine-tuning, GRPO, or training-pipeline work is in scope (SCOPE.md §3.3).

**Challenger models (SCOPE.md §3.3).** Any walk-forward evaluation purges training rows whose label intervals overlap validation labels; applies a 15-session embargo (16 if label intervals include both endpoints); keeps all stocks from one date in the same fold; and estimates the Probability of Backtest Overfitting across the preserved challenger return series.

## 5. Amendment log

| Date | Section | Change | Reason | Governed data examined before the change? |
|---|---|---|---|---|
| — | — | — | — | — |

## 6. References

Full citations with links are in `docs/research/research-log.md`. Key sources:

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*; Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*.
- Newey & West (1994); Andrews (1991); Politis & Romano (1994).
- O'Brien & Fleming (1979); Lan & DeMets (1983).
- Petersen (2009); Cameron, Gelbach & Miller (2011); Fama & MacBeth (1973); Driscoll & Kraay (1998); Clark & West (2007).
- Lopez-Lira, Tang & Zhu (2025); Gao, Jiang & Yan (2025); He, Lv, Manela & Wu (2025).

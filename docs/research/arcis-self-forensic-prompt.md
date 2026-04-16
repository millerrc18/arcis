# Arcis Self-Forensic Research: What Does Our Own Data Say?

**Classification:** FORENSIC — data-driven, not literature-driven
**Executor:** Claude Code with repo access + SQLite query capability
**Prerequisites:**
- Access to `C:/arcis/data/ai_research_desk.sqlite3` (local) or Postgres (Render)
- `docs/research/` corpus (85+ docs) loaded as context
- `docs/research/SD-41-trade-lifecycle-synthesis.md` as the synthesizing framework
- Python 3.11+ with pandas, numpy, scipy, matplotlib available

**Output:** A single markdown report at `docs/research/arcis-self-forensic-report.md` with inline charts saved to `docs/research/figures/`

**Estimated runtime:** 30-45 minutes of compute (longer if attribution resolver is mid-run)

**Core framing:** The research corpus in `docs/research/` tells us what works on *other people's* data. This analysis tells us what our own 23-trade dataset reveals. When literature conclusions conflict with our own data, **our own data wins**. When our data is statistically underpowered (almost certainly true at N=23), flag it explicitly with confidence intervals; do not pretend to certainty we don't have.

---

## SECTION 1: RECONCILED_STALE FORENSICS

**The specific demand from Instance 2's Skeptic:**

> "The 34.8% reconciled-stale exits are a red flag — those are trades that did nothing for 7 days, and treating them as wins (if positive) or losses (if negative) at exit may be biasing the reported metrics. Audit these 8 trades before optimizing."

**Required analysis:**

1. Query all 8 trades with `exit_reason = 'reconciled_stale'` from `shadow_trades`.

2. For each trade, reconstruct the full lifecycle:
   - `actual_entry_price`, `actual_entry_time`, `entry_reason`
   - `actual_exit_price`, `actual_exit_time`, `duration_days`
   - `pnl_dollars`, `pnl_pct`
   - If `max_favorable_excursion` and `max_adverse_excursion` columns exist, pull them
   - If NOT populated: reconstruct MAE/MFE from yfinance daily OHLC for the hold period

3. For each trade, compute:
   - **MFE_pct**: (highest intraday high during hold - entry_price) / entry_price × 100
   - **MAE_pct**: (lowest intraday low during hold - entry_price) / entry_price × 100
   - **Days to MFE peak**: which day of the hold did MFE occur
   - **Days to MAE trough**: which day of the hold did MAE occur
   - **Capture ratio**: realized_pnl_pct / MFE_pct (should ideally be >0.5 for quality exits)

4. Classify each of the 8 stale trades into one of:
   - **Winner-that-gave-back**: MFE > 2%, exited at < 1% → trailing stop or partial exit would have captured
   - **Legitimate timeout**: MFE and MAE both within ±1.5%, trade genuinely did nothing
   - **Slow winner**: MFE > 2% AND exited at MFE peak → we timed the exit right but timeout truncated a real trend
   - **Delayed loser**: MAE < -2% at some point, recovered partially → stop was too wide, trade should have been cut

5. Compare the 8 stale trades' MAE/MFE distributions against the 15 `target_1_hit` winners and 2 `stop_hit` losers.

**Required output:**

```markdown
## Reconciled-Stale Forensic Findings

| trade_id | ticker | pnl_pct | MFE | MAE | days_to_MFE | days_to_MAE | capture_ratio | classification |
|---|---|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

**Distribution summary:**
- Winner-that-gave-back: X of 8 trades
- Legitimate timeouts: X of 8 trades
- Slow winners: X of 8 trades
- Delayed losers: X of 8 trades

**Bias assessment:**
- Mean pnl_pct of stale trades: X.X%
- If stale trades were EXCLUDED from metrics, Sharpe would be: X.XX (vs current 0.585)
- If stale trades' MFE had been captured via trailing stops, Sharpe would be: X.XX
```

**VERDICT** (one of):
- "Stale trades are biasing Sharpe UP by X.XX points — reported edge is less than stated"
- "Stale trades are biasing Sharpe DOWN by X.XX points — real edge is higher"
- "Stale trades are random noise — reported Sharpe is honest"
- "Insufficient data to distinguish the above (most likely at N=8)"

---

## SECTION 2: MAE/MFE DISTRIBUTIONS ACROSS ALL 23 TRADES

**The Sweeney 1996 framework (the single highest-leverage self-calibration available):**

1. For all 23 closed trades, compute MAE and MFE as above.

2. Produce two histograms overlaid on the same axis:
   - **Winner MAE distribution** (15 data points)
   - **Loser+Stale MAE distribution** (8 data points)
   - Find the **separation point**: the MAE value where losers' distribution starts but winners' distribution ends

3. Compute the **95th percentile of winner MAE**. This is Sweeney's recommended stop distance.

4. Counter-check: **Capture ratio distribution** for winners:
   - realized_pnl_pct / MFE_pct for each winner
   - A healthy mean-reversion swing system has capture ratio 0.50-0.65 (per research)
   - If our capture ratio is below 0.50: we're leaving too much on the table → better exits matter
   - If above 0.70: exits are tight, won't gain much from optimization

5. **Conditional MAE analysis**:
   - Split winners by `priority_score` into top-half vs bottom-half
   - Compute 95th-percentile MAE for each subgroup
   - If top-scored entries have shallower MAE: **evidence for score-conditional stops**
   - If no difference: score isn't informative for MAE calibration (important negative result)

**Required output:**

```markdown
## MAE/MFE Empirical Calibration

**Winner MAE distribution (N=15):**
- Mean: X.X% | Median: X.X% | 75th percentile: X.X% | 95th percentile: X.X%
- Chart: docs/research/figures/winner-mae-distribution.png

**Loser/Stale MAE distribution (N=8):**
- Mean: X.X% | Median: X.X% | 75th percentile: X.X%
- Chart: docs/research/figures/loser-mae-distribution.png

**Separation analysis:**
- 95th percentile of winners: X.X%
- 25th percentile of losers: X.X%
- Gap: X.X% (wider = easier discrimination)

**Capture ratio analysis (winners only):**
- Mean: X.XX | Median: X.XX | Distribution chart: docs/research/figures/capture-ratio.png
- Current capture ratio vs research benchmark (0.50-0.65): [above/within/below]

**Conditional MAE by score quartile:**
| Score quartile | N | 95th pct MAE | Mean MFE | Mean capture |
|---|---|---|---|---|
| Top 25% | | | | |
| Mid 50% | | | | |
| Bot 25% | | | | |

**Sweeney-calibrated stop recommendation:**
- Empirical 95th pct winner MAE: X.X%
- With 20% safety buffer: X.X%
- Current fixed stop (3%): [wider/tighter] than empirical
- Statistical confidence at N=15 winners: [LOW/MODERATE] — bootstrap 95% CI: [X.X%, X.X%]
```

---

## SECTION 3: THE TRUE EDGE ESTIMATE

**Apply the statistical corrections Instance 2 demanded:**

1. **Sharpe ratio with confidence interval:**
   - Observed SR = mean(per_trade_returns) / std(per_trade_returns) × √150
   - SE(SR) = √((1 + 0.5×SR²) / N) per Lo (2002)
   - 95% CI = SR ± 1.96 × SE

2. **Bonferroni correction for multi-testing:**
   - Compute critical t at α=0.05 for M ∈ {1, 5, 10, 25, 50}
   - Compute observed t = SR × √N
   - Report: at which M does our current performance become insignificant?

3. **Deflated Sharpe Ratio (Bailey-Borwein-López de Prado-Zhu 2014):**
   - Expected maximum SR under null hypothesis = E[max SR | M trials] ≈ (1-γ)·Φ⁻¹(1 - 1/M) + γ·Φ⁻¹(1 - 1/(M·e))
     where γ = Euler-Mascheroni constant (0.5772)
   - Compute for M ∈ {5, 10, 25, 50}
   - DSR = Φ((SR_obs - E[max SR | M, true=0]) / SE(SR))
   - Report DSR for each M value

4. **Harvey-Liu data-mining discount:**
   - Standard prescription: halve backtested Sharpe ratios as baseline adjustment
   - Bayesian alternative: assume prior distribution of strategy Sharpe is N(0, 0.5²); posterior mean = (prior_weight × 0 + likelihood_weight × observed_SR) / total_weight

5. **Posterior Sharpe estimate:**
   - Combine the three corrections into a single "most honest central estimate"
   - Report with explicit confidence range

**Required output:**

```markdown
## True Edge Estimate

**Raw observed Sharpe:** 0.585 at N=23

**95% Confidence Interval:** [X.XX, X.XX]
**Does IB gate (>1.0) lie inside CI?** [YES/NO]

**Bonferroni significance:**
| M (trials) | Critical t (α=0.05) | Our t | Significant? |
|---|---|---|---|
| 1 | 1.717 | 2.806 | YES |
| 5 | 2.508 | 2.806 | YES |
| 10 | 2.845 | 2.806 | NO |
| 25 | 3.214 | 2.806 | NO |

**Deflated Sharpe Ratio:**
| M (trials) | E[max SR null] | DSR | Interpretation |
|---|---|---|---|
| 5 | X.XX | X.XX | ... |
| 25 | X.XX | X.XX | ... |

**Harvey-Liu discount:** 0.585 → 0.293 (50% haircut)
**Bayesian posterior (weak prior):** X.XX
**Bayesian posterior (skeptical prior):** X.XX

**Most honest central estimate of true Sharpe:**
- **Point estimate:** X.XX
- **Credible range:** [X.XX, X.XX]
- **Probability true Sharpe ≥ 1.0:** X%
- **Probability true Sharpe ≥ 0.5:** X%
- **Probability true Sharpe ≤ 0.3 (strategy is noise):** X%
```

---

## SECTION 4: FEATURE → OUTCOME CORRELATION (Spearman, with caveats)

**The question:** In OUR data (not the literature), what features at entry time actually predict trade success?

**Approach:**

1. For each of the 23 closed trades, join to `recommendations` table to pull entry-time features:
   - `priority_score`
   - `confidence_score` (LLM output)
   - `pullback_depth_pct`
   - `atr` (at entry)
   - `market_regime`, `regime_confidence`
   - `setup_type`, `trend_state`, `relative_strength_state`, `volume_state`
   - `sector_context`
   - Pull VIX at entry from `macro_snapshots` table if available
   - Pull entry hour from `actual_entry_time`

2. Compute Spearman rank correlation between each feature and `pnl_pct`.

3. Compute winrate by feature quartile (e.g., top 25% of priority_score vs bottom 25%).

4. Report with explicit confidence intervals (use Fisher z-transformation for Spearman CIs).

**Critical caveats:**
- At N=23, any single-feature correlation CI will be wide: roughly ±0.4 around the point estimate
- Flag any correlation whose 95% CI crosses zero (most will — that's the honest answer)
- Do NOT run multi-feature regression — overfits at this sample size
- Do NOT report p-values as "significant" without Bonferroni correction across features tested

**Required output:**

```markdown
## Feature → Outcome Correlation

**Spearman ρ with pnl_pct:**
| Feature | ρ | 95% CI | Bonferroni-sig? | Direction matches research? |
|---|---|---|---|---|
| priority_score | X.XX | [X.XX, X.XX] | NO (N too small) | YES/NO |
| confidence_score | ... | ... | ... | ... |
| pullback_depth_pct | ... | ... | ... | ... |
| ATR | ... | ... | ... | ... |
| VIX at entry | ... | ... | ... | ... |
| entry_hour | ... | ... | ... | ... |

**Winrate by priority_score quartile:**
- Q1 (highest scores): X/X = XX%
- Q2: ... 
- Q3: ...
- Q4 (lowest): ...

**Winrate by market_regime:**
- calm_uptrend: X/X = XX%
- unknown: X/X = XX% [SUSPICIOUS: higher than other regimes]
- volatile: X/X = XX%
- bear: X/X = XX%

**The "unknown" regime anomaly:**
15 trades in "unknown" regime had 86.7% WR vs 25% in "calm_uptrend". Is this:
(a) Regime classifier bug — "unknown" is actually the best regime and classifier isn't labeling it
(b) Survivorship bias — unlabeled trades happened to be in benign periods
(c) Real signal — uncategorized pullbacks genuinely win more
Test by pulling entry_time for the 15 unknown-regime trades and looking at:
- VIX at entry
- SPY 5-day return leading into entry
- S&P 100 breadth at entry
If unknown-regime trades cluster at low-VIX, high-breadth periods, (b) is confirmed.
```

---

## SECTION 5: IN-SAMPLE VOL-TARGETING SIMULATION

**Purpose:** Illustrate (not validate) the directional impact of Phase 1 levers on the 23 trades.

**Simulation rules:**

For each of the 23 trades, re-simulate assuming:

1. **Vol-targeted gross exposure:**
   - On entry day, compute SPY 30-day realized vol
   - Scale position size: `actual_size = planned_size × min(1.0, 0.15 / vol_30d)`
   - If scaled size < 20% of planned, skip the trade entirely

2. **VIX step function at entry:**
   - If VIX < 15: 100% of planned size
   - If VIX 15-22: 80%
   - If VIX 22-30: 50%
   - If VIX ≥ 30: 0% (skip trade)

3. **Sector cap (synthetic):**
   - Walk chronologically through trades
   - Maintain rolling position count per GICS sector
   - If candidate trade would exceed 4 positions in its sector among open positions, skip

4. **Time-decay exits:**
   - Day 0: stop at max(entry × 0.95, entry - 3×ATR)
   - Day 3: if unrealized P&L > 0, raise stop to breakeven
   - Day 5: force 50% partial exit at market close
   - Day 7: force 100% exit at market close
   - Compute P&L under these rules using actual OHLC data from yfinance

**Apply the minimum of vol-target and VIX scalars** (per Instance 2 §3.6 — don't triple-count).

**Compute and report:**
- Simulated cumulative P&L vs actual cumulative P&L
- Simulated Sharpe (annualized) vs actual 0.585
- Simulated max drawdown vs actual 5.34%
- Simulated win rate vs actual 65.2%
- Number of trades skipped vs number taken
- Which specific trades were skipped and why (sector cap, VIX, vol-target)

**Caveat prominently:** "This is INSIDE-SAMPLE analysis on 23 trades. It tells us directionally whether the Phase 1 levers would have helped, not whether they WILL help. Actual validation requires 50+ OOS trades post-implementation."

**Required output:**

```markdown
## In-Sample Phase 1 Simulation

**Trades affected:**
- Original: 23 trades
- After vol-targeting + VIX filter: X trades taken, X skipped
- After + sector cap: X trades taken, X skipped (additional)
- After + time-decay exits: same trades, different exits

**Simulated metrics (INSIDE-SAMPLE, NOT VALIDATION):**
| Metric | Actual | Simulated | Δ |
|---|---|---|---|
| Total P&L ($) | 533 | X | X |
| Sharpe | 0.585 | X.XX | +X.XX |
| Max DD (%) | 5.34 | X.XX | -X.XX |
| Win rate | 65.2% | XX% | +/- X% |
| Trades taken | 23 | X | -X |

**Skipped trades:**
| Trade | Ticker | Reason skipped | Actual P&L |
|---|---|---|---|
| ... | ... | ... | ... |

**Directional verdict:**
- Phase 1 levers would have [improved/degraded/been neutral to] in-sample P&L
- Largest contributor to improvement: [lever name]
- Cautionary finding: [any counter-intuitive result]
```

---

## SECTION 6: THE NULL HYPOTHESIS TEST (Are We Beating SPY?)

**The brutal question:** Is Arcis actually adding alpha, or are we just holding high-beta S&P 100 names during bull periods?

**Method:**

1. For each of the 23 trades, compute:
   - **Actual trade return:** pnl_pct
   - **SPY-benchmark return:** SPY return over the exact same date range (entry_date to exit_date), weighted by position size

2. Compute:
   - Mean excess return (Arcis - SPY)
   - Sharpe of excess returns
   - t-statistic of excess returns
   - Hit rate: % of trades that beat SPY-equivalent

3. **Critical second test:** Compute the return a passive SPY overlay with matched exposure would have earned:
   - If Arcis was 60% invested on average during the observation period, simulate 60% SPY + 40% cash
   - Compare Arcis cumulative P&L to SPY-60% cumulative P&L
   - Is Arcis generating alpha over passive exposure, or just momentum beta?

**Required output:**

```markdown
## Null Hypothesis: Alpha vs SPY Benchmark

**Per-trade excess returns (Arcis - SPY for same date range):**
- Mean: X.XX%
- Std: X.XX%
- Sharpe of excess returns: X.XX
- Hit rate (% beating SPY): XX%
- t-statistic: X.XX (N=23)

**Passive-exposure comparison:**
- Arcis cumulative P&L: $533.04
- SPY-equivalent-exposure P&L: $X
- Excess: $X (alpha) or -$X (under-performance)

**Verdict:** 
[Arcis IS generating alpha vs passive / Arcis appears to be capturing momentum beta not alpha / statistically indeterminate at N=23]
```

---

## SECTION 7: THE KAMINSKI-LO TEST

**The question Instance 2 forced:** Is our pullback entry truly mean-reverting? If yes, tight stops hurt. If not, Kaminski-Lo's concern doesn't apply.

**Method:**

For each of the 23 trades:

1. Pull the 5 trading days of OHLC data leading UP TO the entry day.
2. Compute daily returns over those 5 days.
3. Compute the 1-day autocorrelation of the returns during the pullback leg.

Report the distribution:

- **Mean autocorrelation across 23 entries:** negative = mean-reverting (Kaminski-Lo warning applies), ~0 = neutral, positive = momentum (we're catching trends accidentally)
- **Median autocorrelation**
- **Fraction of entries with negative autocorrelation**

Additional test: compute forward 5-day returns after entry, group by autocorrelation sign:
- If negative-autocorr entries win more than positive-autocorr entries → mean-reversion is our edge, tight stops will hurt
- If positive-autocorr entries win more → we're actually catching continuation, not pullbacks
- If similar → autocorrelation isn't predictive for our system

**Required output:**

```markdown
## Kaminski-Lo Mean-Reversion Test

**Autocorrelation of pullback leg (5-day return series leading into entry):**
- Mean: X.XX [negative = mean-reverting confirmed]
- Median: X.XX
- % of entries with negative autocorr: XX%

**Winrate by autocorrelation sign:**
- Entries with negative autocorr (true pullbacks): X/X = XX% winrate
- Entries with positive autocorr (accidental momentum): X/X = XX% winrate

**Verdict:**
- Arcis entries ARE mean-reverting: [YES/NO/MIXED]
- Kaminski-Lo warning applies: [YES/NO]
- Recommended stop architecture: [wide catastrophic + time-decay / ATR-trailing / remove stops entirely]
```

---

## SECTION 8: ATTRIBUTION RESOLVER CHECK-IN

**Purpose:** If the resolver has completed (or partially completed) after the time-window fix, pull early results.

**Method:**

1. Query `attribution_trades` for resolution progress:
   - Total pairs
   - Resolved pairs (ranker_only_outcome != 'pending')
   - Breakdown by pair_type: both_taken, llm_rejected, unknown, null

2. If resolved count > 50 for `both_taken` pairs:
   - Compute ranker-only win rate on resolved both_taken pairs
   - Compute LLM-taken win rate on same pairs
   - Report difference

3. If resolved count > 50 for `llm_rejected` pairs:
   - Compute "rejection accuracy": fraction of rejected trades that would have been losers
   - If > 50%: LLM rejection adds value
   - If < 50%: LLM is rejecting winners (destroying alpha)

4. If resolver hasn't finished: document current state, estimate completion time, skip detailed analysis.

**Required output:**

```markdown
## Attribution Resolver Status

**Resolution progress:**
- Total pairs: 1825
- Resolved: X (XX%)
- Pending: X

**By pair type:**
| Pair type | Total | Resolved | Pending |
|---|---|---|---|
| both_taken | X | X | X |
| llm_rejected | X | X | X |
| unknown | X | X | X |

**Preliminary alpha attribution (if resolved ≥ 50):**
- Ranker-only WR on both_taken: XX%
- LLM-taken WR on same pairs: XX%
- Difference: +X% [LLM adds alpha / LLM subtracts alpha / neutral]
- McNemar's test: chi2 = X.XX, p = X.XX

**Preliminary rejection accuracy (if llm_rejected resolved ≥ 50):**
- LLM rejected: X trades
- Would have been losers: X (XX%)
- Would have been winners: X (XX%)
- Verdict: [LLM rejection adds alpha / destroys alpha / neutral]
```

---

## SECTION 9: META-FINDINGS — OUR DATA vs OUR RESEARCH

**The most important section.** Cross-reference findings from Sections 1-8 against the 85+ research docs in `docs/research/`. For each, report one of:

- **SUPPORTS** — our data confirms the research conclusion
- **CONTRADICTS** — our data contradicts the research conclusion (our data wins)
- **INSUFFICIENT** — N=23 too small to evaluate

**Specific hypotheses to check:**

| Hypothesis | Research source | Our data says | Verdict |
|---|---|---|---|
| Pullback depth 3-7% is optimal | Connors & Alvarez; Instance 1 | What depth distribution do our winners have? | ? |
| RSI(2) < 10 indicates exhaustion | Connors & Alvarez | What were RSI(2) values at our winning vs losing entries? | ? |
| Sector context matters (idiosyncratic > sector-wide) | Moskowitz & Grinblatt; Instance 1 | Compare winrate for pullbacks with sector beta < 0.5 vs > 1.0 | ? |
| Regime impact: calm uptrends > bears | Universal | Why is our "unknown" regime (15 trades) winning 86%? | ? |
| Equal-weight subsumes risk parity at small scale | Roncalli via Instance 2 | Does simulated inverse-ATR sizing improve or worsen in-sample P&L? | ? |
| Fixed stops hurt mean-reversion | Kaminski-Lo; Instance 2 | Section 7 autocorrelation test results | ? |
| Volume dry-up confirms pullback | Campbell-Grossman-Wang; Instance 1 | What relative volume did our winners have vs losers? | ? |
| Entry hour matters (morning drift) | Various microstructure | Winrate by entry_hour bucket | ? |
| Capture ratio 0.50-0.65 is acceptable for mean-reversion | Instance 1 | Section 2 capture ratio finding | ? |

**Where our data contradicts the research, flag as candidates for "what are we doing differently that matters?"**

Where our data is insufficient, flag as "revisit at N=100."

---

## SECTION 10: THE ACTIONABLE DELIVERABLE

The three outputs that determine next steps:

### 10.1 GO/NO-GO on Phase 1 Optimization

Based on Sections 1-9, produce one verdict:

- **GO** — Strategy has credible edge (true Sharpe posterior > 0.3), Phase 1 levers address a real problem in our data. Proceed with 50-trade OOS validation followed by Phase 1 implementation.
- **HALT** — Strategy edge is questionable or negative (Section 6 shows no alpha vs SPY, or Section 3 posterior Sharpe < 0.1). Fix fundamentals before optimizing.
- **DIAGNOSTIC** — Specific problem identified (e.g., stale trades are biasing metrics, or regime classifier is broken). Fix that problem before any Phase 1 work.

### 10.2 RANKED LEVERS (by empirical fit to our actual problems)

Instead of the literature-general ranking in SD-41, produce an Arcis-specific ranking:

"The largest single problem in our data is X. The Phase 1 lever that addresses X is Y. Expected in-sample impact based on Section 5 simulation: +Z Sharpe."

Rank all four Phase 1 levers by this criterion.

### 10.3 SINGLE GO/NO-GO FOR 50-TRADE OOS VALIDATION

Given all of the above, should we run the 50-trade OOS validation starting now, or fix something first?

- If fundamentals check out (Sections 6, 7): yes, start OOS now.
- If there's a diagnostic issue (Section 1 reveals stale-trade bias; Section 4 reveals regime classifier bug; Section 8 shows LLM destroying alpha): fix first.

**The OOS window is wasted if we're observing a broken system.**

---

## Output Format

The CC agent should produce:

1. **Main report:** `docs/research/arcis-self-forensic-report.md` — the full analysis
2. **Figures:** 8-12 charts saved to `docs/research/figures/` referenced inline
3. **Data extract:** `docs/research/figures/all-trades-enriched.csv` — the 23 trades with MAE, MFE, features, outcomes joined
4. **Summary commit message:** one paragraph summarizing the verdict for the README

---

## Methodology Requirements

1. **Never claim significance** without explicit N and CI. At N=23, almost nothing is significant.
2. **Always report the NULL result** — if a feature doesn't correlate, that's as important as if it does.
3. **Use bootstrap** for any percentile estimates (MAE/MFE 95th percentiles, Sharpe CI on subsamples).
4. **Cite the research doc** when cross-referencing (e.g., "per `docs/research/Alternative_Data_Signals.md`").
5. **Flag suspicious findings** as such — if a number looks too good (e.g., 86% winrate in "unknown" regime), investigate before celebrating.
6. **Preserve reproducibility** — save all SQL queries used, list all yfinance calls, version-tag the dataset.

---

## Expected Findings (Priors, Not Commitments)

These are my prior expectations. The research should either confirm or contradict them:

1. **Stale trades are biasing Sharpe UP.** They're likely slight winners that gave back gains — the trailing stop / partial exit findings from both research instances suggest this is the single biggest hidden problem.

2. **Capture ratio is below 0.50.** We're leaving alpha on the table at fixed 2% targets when avg winner is 3.6%.

3. **Pullback-leg autocorrelation is negative.** Kaminski-Lo's warning DOES apply to us, and widening the stop to 5% while relying on vol-targeting will outperform tightening via ATR.

4. **Priority score IS predictive at the extreme quartiles but noisy in the middle.** Top-25% scores win more often than bottom-25%, but within-quartile variance is high.

5. **"Unknown" regime at 86% winrate is a classifier bug.** The regime classifier wasn't running for the first ~15 trades; these trades happened to occur in benign periods. Once the classifier runs consistently, "unknown" should drop to near zero.

6. **We ARE generating alpha vs SPY** but the margin is smaller than our 0.585 Sharpe suggests. True alpha is probably 0.3-0.4 after correcting for the data-mining bias and reconciled-stale contamination.

7. **Attribution resolver will show the LLM adds modest alpha on both_taken pairs** (LLM's conviction filtering is marginally useful) **and rejects correctly more than 50% of the time** on llm_rejected pairs (the LLM is a useful filter).

If any of these priors are wrong, that's the most important information from this entire analysis.

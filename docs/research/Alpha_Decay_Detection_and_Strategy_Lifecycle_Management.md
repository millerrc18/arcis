# Alpha Decay Detection and Strategy Lifecycle Management for Systematic Trading

**Published anomalies lose 58% of their in-sample returns after publication, and the rate of decay accelerates by 5 percentage points each year.** For Halcyon Lab's pullback-in-uptrend strategy on S&P 100 stocks — liquid, heavily covered, and operating on a well-known behavioral mechanism — this creates a definite lifecycle ceiling that demands rigorous monitoring. The good news: strategies rooted in behavioral foundations (underreaction, disposition effect) survive longer than purely statistical anomalies, and a hybrid momentum-plus-mean-reversion signal adds enough complexity to slow crowding. The core challenge is distinguishing genuine alpha decay from temporary regime-driven underperformance — the hardest problem in systematic trading — and this report provides exact formulas, numeric thresholds, and a complete decision framework to solve it within Halcyon Lab's existing infrastructure.

---

## 1. How alpha actually dies: a taxonomy with evidence

Alpha does not decay uniformly. Research reveals four distinct decay mechanisms, each with different timelines, leading indicators, and appropriate responses.

### Gradual crowding decay (the most common killer)

**Maven Securities** measured the cost of alpha decay on a mean-reversion signal across 15 years: **5.6% annualized in the US, 9.9% in Europe**, increasing at 36 bps/year and 16 bps/year respectively. This is not the strategy dying overnight — it is a slow squeeze driven by three forces: more participants competing for the same signal, faster technology pricing information earlier, and declining transaction costs lowering barriers to entry. **Lee (2024, arxiv:2512.11913)** formalized this as hyperbolic decay: **α(t) = K / (1 + λt)**, which fits momentum returns with R² = 0.65, outperforming both linear (R² = 0.51) and exponential (R² = 0.61) models. The key insight is that decay is initially fast then slows — a heavy tail where reduced alpha persists at lower levels for extended periods.

Lee's taxonomy distinguishes "mechanical" factors (momentum, reversal) — which exhibit clear hyperbolic decay because signals are easily replicated — from "judgment" factors (value, quality) where signal ambiguity creates barriers that slow crowding. A pullback-in-uptrend strategy sits between these categories: the pullback entry is mechanical, but the uptrend filter adds a judgment layer.

### Step-function publication decay

**McLean and Pontiff (2016)** examined 97 cross-sectional anomalies and found **26% out-of-sample decline** (statistical bias/data mining) plus an additional **32% post-publication decline** (arbitrage capital), totaling **58% erosion**. Their design uses dummy variables for post-sample and post-publication periods, revealing decay as two discrete steps rather than a smooth curve. **Penasse (2017)** fit this data with a duration parameter δ = 3, implying "three plateaus" connected by approximately two-year transitions.

**Falck, Rej, and Thesmar (2022, Quantitative Finance)** extended this: publication year alone explains **30% of Sharpe decay variance**, with each calendar year adding ~5 percentage points to newly published factors' decay rate. After trading costs, post-2005 published strategies lose **93% of their backtest Sharpe** (Chen and Velikov, 2023). Critically, **anomaly decay is US-specific** — Jacobs and Müller (2020, JFE) found no reliable post-publication decline internationally, suggesting US-specific arbitrage capital drives this effect.

### Regime-dependent performance collapse

Some strategies don't lose alpha permanently — they fail when conditions shift. The 2022 "Stock Market Anomalies in the Modern Era" study found that in the current trading technology regime, only **3 of 13 anomaly themes** earn significant unconditional CAPM alphas: low-risk, profitability, and quality. **Momentum survives conditionally** — after high-sentiment/low-VIX periods only. This matters enormously for Halcyon Lab: a pullback-in-uptrend strategy likely performs best in trending, moderate-volatility environments and may struggle during range-bound or crash regimes without being fundamentally broken.

### Structural elimination

Pairs trading provides the cautionary tale. **Do and Faff (2010)** documented the decline from **86 bps/month (1962–1988)** to **37 bps/month (1989–2002)** to **24 bps/month (2003–2009)**, with realistic transaction costs rendering the strategy unprofitable in recent periods. Contrary to popular belief, hedge fund competition explained only a fraction — worsening arbitrage risks (fundamental risk, noise-trader risk, synchronization risk) contributed up to **70% of the profit drop**. The strategy didn't just get crowded; the statistical relationships it exploited fundamentally weakened.

### Why momentum specifically survives (and what this means for pullback strategies)

**Jegadeesh and Titman (2023, Pacific-Basin Finance Journal)** confirmed that "momentum profits have remained large and significant in the three decades following our original study." US equity momentum delivered **0.31% monthly (2000–2020)**, down from ~1.5% in the original sample but still positive. The behavioral foundations — underreaction from slow information diffusion, disposition effect, overconfidence — are rooted in human psychology that does not get arbitraged away. Additionally, momentum carries significant **crash risk** (large negative skewness), which deters full arbitrage.

For Halcyon Lab's pullback strategy, this is encouraging. The uptrend filter leverages the same underreaction mechanism sustaining momentum, while the pullback entry exploits short-term mean reversion from overreaction. Both behavioral foundations continuously regenerate. However, momentum on S&P 100 stocks decayed from ~10% annually in the 1990s to ~2% today — the decay is real, just slower than for purely mechanical signals.

---

## 2. Monthly strategy health scorecard with exact formulas

Every metric below is specified with its mathematical formula, appropriate lookback window for ~35 trades/month, green/yellow/red thresholds, minimum sample size, and expected false alarm rate.

### Rolling Sharpe ratio

**Formula (annualized):**
$$SR_t = \sqrt{252} \times \frac{\bar{r}_{t-k:t}}{\sigma_{r,t-k:t}}$$

where $\bar{r}$ is mean daily excess return and $\sigma_r$ is standard deviation over the lookback window of $k$ trading days.

**Standard error (Lo, 2002):**
$$\hat{\sigma}(SR) = \sqrt{\frac{1 - \hat{\gamma}_3 \cdot SR + \frac{\hat{\gamma}_4 - 1}{4} \cdot SR^2}{T-1}}$$

where $\hat{\gamma}_3$ = skewness and $\hat{\gamma}_4$ = kurtosis (non-excess, normal = 3).

**Recommended window:** **90 trading days** for Halcyon Lab (captures ~105 trades, balancing responsiveness with stability). Use 252-day as secondary confirmation.

| Level | 90-day Rolling SR | 252-day Rolling SR |
|-------|------------------|--------------------|
| **Green** | > 0.8 | > 0.5 |
| **Yellow** | 0.0–0.8, or >1σ drop from trailing 252-day mean | 0.0–0.5 |
| **Red** | < 0.0 for 2+ consecutive windows | < 0.0 for 12+ months |

**Minimum sample:** 60 observations per window. **False alarm rate:** ~2.3% at 2σ threshold (one-tailed).

### Probabilistic Sharpe Ratio (PSR)

**Formula (Bailey and López de Prado, 2012):**
$$PSR(SR^*) = \Phi\left[\frac{(\hat{SR} - SR^*) \sqrt{T-1}}{\sqrt{1 - \hat{\gamma}_3 \cdot \hat{SR} + \frac{\hat{\gamma}_4 - 1}{4} \cdot \hat{SR}^2}}\right]$$

where $\Phi$ = standard normal CDF, $\hat{SR}$ = observed Sharpe, $SR^*$ = benchmark threshold (use 0), $T$ = number of observations. Compute at the same frequency as observations (daily) — do NOT annualize before computing PSR.

| Level | PSR(0) |
|-------|--------|
| **Green** | > 0.95 |
| **Yellow** | 0.85–0.95 |
| **Red** | < 0.85 |

**Minimum sample:** T ≥ 40 observations for reasonable approximation; T ≥ 120 preferred. PSR explicitly accounts for non-normality through skewness and kurtosis terms.

### Deflated Sharpe Ratio (DSR)

**Formula (Bailey and López de Prado, 2014):**
$$DSR = \Phi\left[\frac{(\hat{SR}^* - SR_0) \sqrt{T-1}}{\sqrt{1 - \hat{\gamma}_3 \cdot SR_0 + \frac{\hat{\gamma}_4 - 1}{4} \cdot SR_0^2}}\right]$$

where $SR_0$ is the expected maximum Sharpe ratio under the null of zero skill:
$$SR_0 = \sqrt{V[\{SR_n\}]} \times \left[(1-\gamma) \Phi^{-1}\left(1 - \frac{1}{N}\right) + \gamma \Phi^{-1}\left(1 - \frac{1}{Ne}\right)\right]$$

with $V[\{SR_n\}]$ = variance of Sharpe ratios across $N$ independent trials, $\gamma \approx 0.5772$ (Euler-Mascheroni constant), $e$ = Euler's number. All Sharpe ratios must remain un-annualized for computation.

| Level | DSR |
|-------|-----|
| **Green** | > 0.95 (genuine skill likely) |
| **Yellow** | 0.80–0.95 (marginal evidence) |
| **Red** | < 0.80 (likely spurious/overfit) |

**Minimum sample:** T ≥ 252 daily observations. **Practical note:** DSR is most valuable during strategy development and champion-challenger evaluation, not rolling monitoring.

### Minimum Track Record Length (MinTRL)

**Formula:**
$$MinTRL = 1 + \left[1 - \hat{\gamma}_3 \cdot \hat{SR} + \frac{\hat{\gamma}_4 - 1}{4} \cdot \hat{SR}^2\right] \times \left(\frac{z_\alpha}{\hat{SR} - SR^*}\right)^2$$

For Halcyon Lab at ~420 trades/year, annualized SR = 1.5, normal returns: MinTRL ≈ 680 daily observations (2.7 years). With negative skewness (-1) and excess kurtosis (6): **MinTRL ≈ 1,000+ observations (~4 years)**. If your actual track record T < MinTRL, observed performance is statistically indistinguishable from luck.

### CUSUM change detection

**Formula (Page, 1954):**
$$S^+_t = \max(0, S^+_{t-1} + (x_t - \mu_0 - K))$$
$$S^-_t = \max(0, S^-_{t-1} - (x_t - \mu_0 + K))$$

Signal alarm when $S^+_t > h$ or $S^-_t > h$.

**Parameterization for Halcyon Lab:**
- $\mu_0$ = historical mean daily return during "healthy" period
- $K = 0.5\sigma$ (detect shifts of 1σ or more in mean return)
- $h = 4\sigma$ → Average Run Length before false alarm (ARL₀) ≈ 400 observations (~1.6 years)
- $h = 5\sigma$ → ARL₀ ≈ 1,000+ observations (~4 years)

**Recommendation:** Use $h = 4\sigma$ for early warning, $h = 5\sigma$ for high-confidence alarm. CUSUM is first-order asymptotically optimal — for any fixed false alarm rate, no procedure detects mean shifts faster (Moustakides, 1986). **Philips, Yashchin, and Stein (2003)** demonstrated CUSUM detects flat-to-benchmark performance in ~41 months versus ~40 years for a t-statistic, with average false alarm interval of **84 months (7 years)** — currently used to monitor $500+ billion in active assets.

### Information Coefficient per feature

**Spearman Rank IC (preferred):**
$$IC_t = \text{corr}(\text{rank}(x_t), \text{rank}(y_t))$$

where $x_t$ = factor values, $y_t$ = forward returns. Track the IC Information Ratio:
$$ICIR = \frac{\text{Mean}(IC)}{\text{Std}(IC)}$$

ICIR > 0.5 indicates a robust, consistent signal. Typical "good" ICs range from 0.02 to 0.08.

| Level | Rolling 6-month Mean IC |
|-------|------------------------|
| **Green** | > 75% of full-sample average |
| **Yellow** | 50–75% of full-sample average |
| **Red** | Indistinguishable from zero (t-test p > 0.10) or simultaneous decline across ≥3 features |

**Minimum sample:** ≥24 rebalancing periods.

### Win rate trend detection

**Binomial test:**
$$z = \frac{k/n - p_0}{\sqrt{p_0(1-p_0)/n}}$$

At 35 trades/month with baseline win rate 55%: standard error = √(0.55 × 0.45 / 35) ≈ **8.4 percentage points** per month. Over 3 months (105 trades): SE ≈ 4.9 pp. Over 6 months (210 trades): SE ≈ 3.4 pp. You need approximately **300+ trades** to detect a 5-percentage-point decline at 95% confidence — roughly 9 months of live trading.

| Level | Threshold |
|-------|-----------|
| **Yellow** | 3-month rolling win rate >2 SE below baseline |
| **Red** | 6-month binomial test rejects null (p < 0.05), or 3-month win rate >3 SE below baseline |

### Additional scorecard metrics

**Alpha Decay Rate:** Slope of OLS regression of rolling 90-day Sharpe versus time over trailing 12 months, annualized. Green: > -0.1/year. Yellow: -0.3 to -0.1. Red: < -0.3.

**Feature Importance Stability (FIS):** Spearman rank correlation between feature importance vectors across consecutive retraining cycles. Green: ρ > 0.8. Yellow: 0.5–0.8. Red: < 0.5.

**Calibration Drift (PSI):**
$$PSI = \sum_i (P_i - Q_i) \times \ln(P_i / Q_i)$$

where $P$ = current prediction distribution and $Q$ = baseline. Green: PSI < 0.1. Yellow: 0.1–0.25. Red: ≥ 0.25.

**OOS vs IS Divergence:** $D = 1 - (SR_{OOS} / SR_{IS})$. Green: < 0.3. Yellow: 0.3–0.5. Red: > 0.5 (live delivering less than half of backtest).

**Regime Dependency Score:** Ratio of maximum to minimum Sharpe across VIX terciles (low/medium/high). Green: < 2.0. Yellow: 2.0–4.0. Red: > 4.0.

**Crowding Composite:** Normalized average of pullback depth z-score, ETF flow acceleration during dips, short interest utilization, and publication rate for strategy type. Green: < 0.3. Yellow: 0.3–0.6. Red: > 0.6.

---

## 3. The hardest question: decay versus bad regime

The decision framework below uses specific numeric criteria at each node to distinguish permanent alpha decay from temporary regime-driven underperformance.

### Step 1: structural break detection

Run the **Bai-Perron multiple structural break test** on the strategy's daily P&L series. Use UDmax/WDmax (unknown number of breaks) with 15% trimming, HAC covariance, allowing up to 5 breaks. This is the most powerful test for detecting unknown breakpoints — superior to CUSUM in statistical power (Andrews, 1993). Implementation: Python `ruptures` library or R `strucchange`.

- **If break detected** (p < 0.05): Proceed to Step 2 with elevated concern
- **If no break detected**: Evidence favors regime explanation; proceed with lower urgency

### Step 2: regime-conditional performance

Classify regimes using VIX terciles (Low: VIX < 17.8; Medium: 17.8–23.1; High: > 23.1) or fit a 2-state Gaussian HMM on index returns. Calculate strategy Sharpe ratio separately within each regime over the trailing 12 months.

- **Positive Sharpe in favorable regime, negative in unfavorable** → Regime-driven underperformance (PAUSE)
- **Negative Sharpe in ALL regimes** → Strong evidence of permanent decay (RETIRE evaluation)
- **Structural break + positive in favorable regime** → Partial decay (MODIFY)

### Step 3: feature-level diagnosis

Check rolling IC for each of the top 5 features over trailing 6 months.

- **ICs declining across ≥3 features simultaneously** → Structural signal degradation (favors DECAY)
- **1–2 features declining, others stable** → Regime sensitivity in specific features (favors REGIME)
- **Feature importance rankings reshuffling chaotically** → Concept drift / overfitting (favors MODIFY or RETIRE)

### Step 4: crowding check

Monitor pullback depth and duration trends in the strategy universe. If the rolling 6-month median pullback depth in S&P 100 stocks has declined by >1 standard deviation versus the 3-year baseline, and ETF inflows during dips are accelerating, crowding is compressing the opportunity set. When "buy the dip" becomes consensus — with retail investors adding ~$1 billion for every 1% S&P 500 drop — pullbacks become shallower and briefer, directly eroding the strategy's edge.

### Step 5: Triple Penance Rule calibration

**Core result (Bailey and López de Prado, 2014):** Recovery from maximum drawdown takes approximately **3× the time it took to form that drawdown**, at the same confidence level. If the strategy has been in drawdown for T months, expect recovery to take 3T months. Ignoring serial correlation underestimates downside potential by up to 70%.

| Drawdown Formation | Expected Recovery | Solo Operator Patience Budget |
|-------------------|-------------------|-------------------------------|
| 3 months | 9 months | 12 months (buffer for serial correlation) |
| 6 months | 18 months | 24 months at reduced allocation |
| 12 months | 36 months | Likely too long — evaluate retirement |

**Rej, Seager, and Bouchaud (2018)** provide the Brownian motion framework: for a strategy with assumed SR = 1.0, a drawdown lasting up to ~2 years is consistent with normal variance at 95% confidence. Both managers and investors "systematically underestimate the expected length and depth of drawdowns implied by a given Sharpe ratio."

### Historical examples to calibrate intuition

**False alarms (looked dead, recovered):** Kalman Filter pairs trading strategy crashed from Sharpe >2.0 to negative territory through 2012–2014, appearing terminal. By 2015–2016 it had recovered toward 2.0. Trend-following CTAs suffered multi-year drawdowns during 2011–2013 low volatility, then recovered strongly. The September 2019 momentum crash appeared catastrophic but reversed.

**Missed alarms (looked temporary, was permanent):** Many published anomalies post-McLean-Pontiff that researchers attributed to "bad regime" but never recovered. Pairs trading's gradual decline was interpreted as temporary for years before the market accepted the edge was gone. Low-volatility short strategies pre-February 2018 looked like a carry trade in a bad volatility regime — it was structural.

### Complete decision tree

```
STRATEGY UNDERPERFORMING?
│
├─ Run Bai-Perron structural break test on P&L
│  ├─ Break detected (p < 0.05)?
│  │  ├─ YES → Calculate regime-conditional Sharpe
│  │  │  ├─ Negative in ALL regimes → ALPHA DECAY → RETIRE evaluation
│  │  │  ├─ Positive in ≥1 regime → PARTIAL DECAY → MODIFY
│  │  │  └─ Check feature ICs: ≥3 declining → confirm DECAY
│  │  │
│  │  └─ NO → Calculate regime-conditional Sharpe
│  │     ├─ Positive in favorable, negative in unfavorable → REGIME → PAUSE
│  │     ├─ Negative in all → Recheck with longer window → DECAY likely
│  │     └─ Ambiguous → PAUSE with enhanced monitoring
│  │
├─ Check crowding indicators
│  ├─ Pullback depth declining + ETF flows accelerating → Crowding concern
│  └─ No crowding signal → Weight toward REGIME explanation
│
├─ Apply Triple Penance Rule
│  ├─ Time underwater < 3× formation period → WAIT (at reduced allocation)
│  └─ Time underwater > 3× formation period → Escalate to RETIRE
│
└─ FINAL DECISION
   ├─ PAUSE: Reduce to 25-50%, set penance clock, monitor weekly
   ├─ MODIFY: Walk-forward parameter check, universe expansion, new features
   └─ RETIRE: Wind down over 4-8 weeks, reallocate, document post-mortem
```

---

## 4. Pause, modify, retire: operational decision framework

### Pause protocol

| Stage | Trigger | Action | Duration |
|-------|---------|--------|----------|
| **Yellow** | 90-day SR < 0.5, or PSR(0) < 0.90 | Reduce allocation to 50% | Review monthly |
| **Orange** | 60-day SR < 0.0, or drawdown > 1.0× historical max | Reduce to 25% | Review bi-weekly |
| **Red** | 60-day SR < -0.5, or drawdown > 1.5× historical max | Full pause (0%) | Review weekly |

**Resumption criteria:** 60-day rolling Sharpe exceeds 0.5 for ≥30 consecutive trading days AND regime indicator suggests favorable conditions. Gradual re-entry: 25% → 50% → 75% → 100% over 4 weeks. **Hard ceiling:** If paused >18 months with no improvement in regime-conditional metrics → escalate to Retire.

### Modify protocol

Retraining helps when walk-forward optimization shows **smooth parameter drift** (optimal parameters shift gradually). Retraining is futile when parameters jump chaotically (e.g., lookback oscillates 12 → 47 → 23 → 35) — classic overfitting to noise.

The modification toolkit, in order of expected impact:

- **Universe expansion** (S&P 100 → S&P 500): Most effective lifecycle extension. Same signal, broader universe, more diversified bets, less crowding per name. Expect 12–24 months of extended life.
- **Feature engineering**: Add features capturing the same economic driver through different data. Sentiment, options-implied measures, or fundamental quality filters add the "judgment" complexity that slows crowding.
- **Risk model update**: Don't change the signal; change position sizing. Regime-conditional sizing (smaller in high-VIX, larger in low-VIX) can improve risk-adjusted returns without touching the alpha source.
- **Hold period adjustment**: If crowding is compressing the 2–15 day sweet spot, test whether extending to 20–30 days or compressing to 1–5 days captures a less crowded part of the return distribution.
- **Execution improvement**: Maven Securities' 5.6% annual decay cost means execution quality directly impacts strategy longevity.

### Retire protocol

**Hard kill criteria:**

| Criterion | Threshold |
|-----------|-----------|
| 252-day rolling Sharpe < 0.0 for 12+ consecutive months | Retire |
| 60-day rolling Sharpe < -1.0 for 60+ consecutive days | Retire |
| Drawdown > 2.0× historical maximum | Retire |
| Time underwater > 3× formation period (Triple Penance) | Retire |
| Bai-Perron rejects stability at p < 0.01 on most recent 2-year window | Retire |
| Negative Sharpe in ALL identified regimes over trailing 12 months | Retire |

**Wind-down process:** Reduce from 100% → 50% → 25% → 0% over 4–8 weeks. Do NOT cliff-edge stop — gradual exit reduces market impact and preserves optionality if the diagnosis is wrong. Redirect freed capital to: (a) existing positive-Sharpe strategies, (b) pipeline strategies completing incubation, (c) cash reserve.

### How pod shops handle this (and why solo operators should differ)

**Millennium:** 5% drawdown from high-water mark → capital cut in half. 7.5% drawdown → complete wind-down and PM termination. ~80% PM turnover within 2 years. Median tenure: 2.3 years. **Citadel:** Similar ~5% soft stop with additional constraint of max 15% factor exposure. Median tenure: 3.0 years. **Balyasny:** Drawdown limits vary by strategy (7–8% half-cut, 10–12% firing).

These tight stops work because pod shops are portfolios of PMs — any single failure is absorbed by the ensemble, and a deep replacement pipeline exists. **A solo operator has neither diversification nor a replacement pipeline.** Solo operators should use looser limits: **10–15% soft stop, 20–25% hard stop**, with 6–12 months for evaluation rather than 1–3 months.

---

## 5. Capital reallocation protocol when decay is detected

### For the current single-strategy phase

When the pullback strategy triggers yellow/orange/red alerts, freed capital moves to cash (T-bills or money market). Pre-commit to kill criteria before going live — write them down, share with the AI Council, and enforce mechanically.

### For the 4–8 strategy multi-desk phase

**Hierarchical Risk Parity (HRP)** allocation, rebalanced weekly, with guard rails:

- Auto-reduce allocation when any strategy's 90-day rolling Sharpe drops below 0.3
- Auto-increase allocation to strategies with improving metrics
- Hard floor: No strategy below 5% allocation unless in retirement phase
- Human override required for: full retirement (0%), or >30% reallocation in a single month
- **AQR research finding:** 6–9 month volatility lookback produces the best return-to-volatility ratio for risk parity weights. Shorter creates whipsaw; longer misses regime shifts.

### When 2 of 4 strategies decay simultaneously

This is a **critical diagnostic event** — shared hidden factor hypothesis. Immediate response: reduce total portfolio leverage by 25–50%. Within 48 hours: run factor attribution against common factors (market, size, value, momentum, quality, volatility) and macro variables (rates, VIX, credit spreads). If a shared loading is found (R² > 0.3 to any single factor), hedge that factor explicitly. Common culprits: regime transition (low-vol to high-vol), liquidity withdrawal, and crowding unwind across the quant ecosystem (August 2007-type event).

### The creative destruction pipeline

Maintain a continuous strategy development funnel. Target steady state:

- **Live:** 4–6 strategies
- **Incubation (paper trading):** 2–3 strategies (3–6 month cycles)
- **Backtesting:** 2–4 strategies
- **Research/discovery:** 5+ ideas at various stages
- **Cadence:** At least 1 strategy entering incubation per quarter
- **Expected attrition:** ~80%+ of backtested strategies never make it to live. Plan to retire ~1 live strategy per year from a portfolio of 4.

Reserve 10–20% of capital for new strategy ramp-up. Dedicate 20% of weekly time to R&D, separate from monitoring existing strategies.

---

## 6. False alarm analysis and calibration

The critical constraint: **if alerts fire too often, the solo operator ignores them.** Target ≤2 red alerts per month across all strategies.

### Expected false positive rates by metric

| Metric | Threshold | False Alarm Rate | Expected Alerts/Year (1 strategy) |
|--------|-----------|-----------------|----------------------------------|
| Rolling Sharpe (2σ drop) | >2σ below trailing mean | 2.3% per window | ~6 yellow, ~1 red |
| PSR(0) < 0.85 | Red threshold | ~5% by construction | ~2–3 |
| CUSUM (h = 4σ) | Cumulative sum breach | ARL₀ ≈ 400 days | ~0.6/year |
| CUSUM (h = 5σ) | Cumulative sum breach | ARL₀ ≈ 1,000 days | ~0.25/year |
| Win rate binomial (p < 0.05) | Monthly test | 5% per test | ~0.6/year |
| Structural break (Bai-Perron, p < 0.05) | Quarterly test | 5% per test | ~0.2/year |
| Feature IC (p > 0.10 for zero) | Monthly test | ~10% per test | ~1.2/year |

### Anti-fatigue design

Use **severity aggregation**: only fire a yellow alert if 3+ individual yellow metrics persist for >1 week. Use CUSUM (cumulative) rather than point-in-time thresholds for drift detection — this naturally filters noise. Allow "snooze" on alerts with 1-week timeout.

**Alert tiers for Telegram:**
- **CRITICAL (Red):** Immediate push with sound. Example: "🔴 CRITICAL: Pullback-MR | Sharpe 30d = -0.15 (threshold: 0.0) | Action: Review position sizing"
- **WARNING (Yellow):** Silent push notification. Review within 48 hours.
- **INFO (Green):** Batched daily summary at market close. No push.
- **EMERGENCY:** 2+ simultaneous reds across strategies: Halt new entries, reduce all positions 50%, deep review within 24 hours.

### The 80/20 metrics for a solo operator

These **5 metrics capture approximately 80% of strategy health signal** with minimal monitoring overhead:

1. **Rolling 90-day Sharpe Ratio** — captures real-time performance decay
2. **CUSUM on daily P&L** — optimal detection speed for mean shifts, already in Halcyon Lab
3. **PSR(0)** — accounts for non-normality, provides probability-calibrated confidence
4. **Feature importance stability (Spearman ρ across retraining cycles)** — captures model-level decay
5. **OOS vs IS divergence** — catches overfitting before it manifests as losses

These five cover the four failure modes: alpha erosion (#1, #3), structural breaks (#2), model staleness (#4), and overfitting (#5).

---

## 7. Integration spec for AI Council Red Team weekly moat monitoring

### Weekly Red Team agent checklist (automated, Qwen3 8B on RTX 3060)

The Red Team agent should execute a structured weekly assessment every Saturday before retraining, producing a Telegram digest.

**Quantitative checks (automated computation):**

1. Compute rolling PSR for each active strategy — flag if PSR(0) drops below 0.90
2. Check CUSUM status on excess returns — report any alarm signals or proximity to threshold (S/h ratio)
3. Calculate rolling Sharpe at 30-day, 90-day, and 252-day windows with confidence bands
4. Monitor win rate with binomial confidence intervals — flag if >2 SE below baseline
5. Compute feature importance stability (Spearman ρ of SHAP rankings vs. previous retraining)
6. Calculate PSI for top-5 input features and prediction distribution
7. Track profit factor trend (rolling 3-month)

**Crowding/moat erosion signals (semi-automated):**

8. Compute rolling 6-month median pullback depth and duration in S&P 100 — flag declining z-score
9. Monitor ETF flow data for SPY/QQQ during recent pullbacks
10. Check factor loadings — increasing R² to known factors (momentum, value) signals declining uniqueness
11. Track execution slippage trend — rising slippage signals crowding or capacity constraint
12. Quarterly: scan SSRN/arXiv for new publications on pullback/mean-reversion strategies

**Regime assessment:**

13. Classify current VIX regime (low/medium/high tercile)
14. Calculate regime-conditional Sharpe for trailing 6 months
15. Check if current underperformance (if any) is consistent with expected regime sensitivity

**Output format (Telegram message):**

```
📊 HALCYON LAB — WEEKLY MOAT ASSESSMENT
Date: [Saturday date]

STRATEGY: Pullback-in-Uptrend (S&P 100)
├─ Health Score: [0-100] [🟢/🟡/🔴]
├─ Rolling Sharpe (90d): [value] [trend arrow]
├─ PSR(0): [value]%
├─ CUSUM Status: [Normal/Warning/Alarm] (S/h = [ratio])
├─ Win Rate (3mo): [value]% (baseline: [value]%)
├─ Feature Stability: ρ = [value]
├─ Calibration PSI: [value]
├─ Regime: [Low/Med/High Vol] — strategy expected to [perform well/struggle]

MOAT SIGNALS:
├─ Pullback depth trend: [stable/compressing/expanding]
├─ Crowding composite: [value] [🟢/🟡/🔴]
├─ New related publications this month: [count]

ACTIONS:
├─ [Any recommended actions based on thresholds]
├─ Champion-challenger evaluation: [proceed/defer]

RETRAINING RECOMMENDATION: [Proceed / Defer / Investigate before proceeding]
```

### Integration with existing infrastructure

**CUSUM (already implemented):** Keep current parameterization but add the $h/\sigma$ ratio reporting so the Red Team can track proximity to alarm before it fires. Consider maintaining both $h = 4\sigma$ (early warning) and $h = 5\sigma$ (confirmed alarm) simultaneously.

**50-trade gate evaluator:** Continue using for champion-challenger evaluation. Complement with MinTRL check — if the challenger's track record < MinTRL, the observed outperformance may not be statistically meaningful regardless of the gate pass.

**Weekly Saturday retraining:** Before retraining, the Red Team agent should check feature importance stability. If FIS < 0.5 (red), investigate before retraining — the model may be chasing noise. After retraining, immediately compare champion vs. challenger using DSR (not just raw Sharpe) to account for multiple testing across retraining cycles.

**Daily audit with Telegram alerts:** Add CUSUM status and rolling Sharpe to the daily audit. Reserve the detailed moat assessment for the weekly Saturday digest to avoid alert fatigue.

**Training data quality scoring:** Extend to include regime labeling. Flag training periods that span regime boundaries — mixed-regime training data can produce models that work in neither regime.

---

## 8. Dealing with Harvey, Liu, and Zhu's multiple testing challenge

**Harvey, Liu, and Zhu (2016, Review of Financial Studies)** cataloged 316+ published factors and argued that the traditional t > 2.0 significance threshold is inadequate given extensive data mining. A newly discovered factor needs **t > 3.0** to clear the adjusted hurdle. Their headline: "Most claimed research findings in financial economics are likely false."

This has direct implications for Halcyon Lab's champion-challenger framework: with weekly retraining and multiple parameter combinations tested, the effective number of independent trials N grows rapidly. The DSR formula above explicitly corrects for this. **Practical rule:** When evaluating a new strategy variant, count the total number of parameter combinations, feature sets, and lookback windows tested. Use ONC clustering to estimate effective N, then compute DSR. Only promote a challenger if DSR > 0.95.

However, important counter-evidence exists: **Chen and Zimmermann (2018)** and **Jensen, Kelly, and Pedersen (2023)** found false discovery rates of only ~1–12%, suggesting **75–91% of published anomalies are likely genuine**. The disagreement stems from mapping between statistical tests and economic interpretations. For Halcyon Lab, this means: the pullback-in-uptrend effect likely has genuine economic substance (behavioral underreaction), but the specific parameterization requires rigorous out-of-sample validation using DSR-level standards.

---

## 9. Essential reading list

These papers and books form the intellectual foundation for strategy lifecycle management. They are ordered by practical importance for Halcyon Lab's current stage.

- **López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.** Contains CUSUM filter, triple barrier method, meta-labeling, PSR/DSR, and backtest overfitting detection — directly applicable to the existing infrastructure.
- **Bailey, D.H. and López de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*, 40(5).** The mathematical foundation for distinguishing skill from luck across multiple strategy trials.
- **Bailey, D.H. and López de Prado, M. (2014). "Stop-Outs Under Serial Correlation and the Triple Penance Rule." *Journal of Risk*, 18(2).** Essential for setting patience budgets and drawdown limits.
- **McLean, R.D. and Pontiff, J. (2016). "Does Academic Research Destroy Stock Return Predictability?" *Journal of Finance*, 71(1), 5–32.** The foundational evidence on post-publication alpha decay.
- **Falck, A., Rej, A., and Thesmar, D. (2022). "When Do Systematic Strategies Decay?" *Quantitative Finance*, 22(11), 1955–1969.** Publication year as the strongest predictor of Sharpe decay; 5 ppt annual acceleration.
- **Jegadeesh, N. and Titman, S. (2023). "Momentum: Evidence and Insights 30 Years Later." *Pacific-Basin Finance Journal*, 82.** Confirms momentum persistence and behavioral foundations.
- **Harvey, C.R., Liu, Y., and Zhu, H. (2016). "…and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.** Multiple testing framework; t > 3.0 standard for new factors.
- **Philips, T.K., Yashchin, E., and Stein, D.M. (2003). "Using Statistical Process Control to Monitor Active Managers." SSRN: 371121.** CUSUM for strategy monitoring — directly validates Halcyon Lab's approach.
- **Rej, A., Seager, P., and Bouchaud, J.-P. (2018). "You Are in a Drawdown. When Should You Start Worrying?" arXiv: 1707.01457.** Exact probability distributions for drawdown length/depth given assumed Sharpe.
- **Ang, A. (2014). *Asset Management: A Systematic Approach to Factor Investing*. Oxford University Press.** Comprehensive treatment of factor lifecycles and risk management.

---

## Conclusion: what this means for Halcyon Lab right now

The single most important finding from this research is that **alpha decay follows a hyperbolic curve, not a cliff** — the edge erodes gradually, providing detection windows of months to years if you're measuring the right things. For a pullback-in-uptrend strategy on S&P 100 with behavioral foundations, the expected lifecycle from live deployment to meaningful decay is **2–5 years**, extendable through universe expansion to S&P 500 and feature engineering that adds "judgment" complexity.

The existing CUSUM implementation is already the optimal change detection tool — no other method detects mean shifts faster for a given false alarm rate. Adding PSR as a rolling confidence measure, feature importance stability tracking via Spearman ρ across retraining cycles, and a quarterly Bai-Perron structural break test creates a monitoring stack that covers all four failure modes (alpha erosion, structural breaks, model staleness, overfitting) within the 2-hour weekly time budget.

The most underappreciated risk is not decay itself but **the sunk cost trap**: the strategy that looks like it's in a bad regime but is actually dying. The decision tree above — Bai-Perron first, then regime-conditional Sharpe, then feature-level diagnosis — provides a structured path through this ambiguity. Pre-committing to kill criteria now, before the first drawdown creates emotional attachment, is the single highest-leverage action Halcyon Lab can take this week. Write the thresholds into the AI Council's configuration, and let the Red Team agent enforce them mechanically.
# Statistical gates for deploying Halcyon Lab to live capital

**At 20 trades, Halcyon Lab's 70% win rate is suggestive but not yet statistically significant** — the exact binomial one-tailed p-value is 0.058, narrowly missing the p < 0.05 threshold, and the 95% confidence interval for the true win rate spans from 46% to 88%. The Probabilistic Sharpe Ratio framework requires a minimum of 70–273 trades (depending on per-trade Sharpe) to achieve 95% confidence that performance exceeds zero. Paper-to-live performance decay averages 20–33% for simple mechanical equity strategies on liquid stocks, meaning paper performance gates must be set proportionally higher. The phased deployment framework below provides exact statistical gates for each capital tier ($100 → $1,000 → $5,000 → $25,000), incorporating confidence intervals, PSR thresholds, concordance testing, and drawdown limits calibrated to published academic research.

---

## 1. Win rate confidence intervals reveal wide uncertainty at N=20

Three established methods for computing binomial confidence intervals on 14/20 = 70% observed win rate are compared below. The Clopper-Pearson exact method (Clopper & Pearson, 1934, *Biometrika*) inverts two one-tailed binomial tests and is guaranteed to provide coverage ≥ 95% but is conservative. The Wilson score interval (Wilson, 1927) uses a quadratic correction and achieves coverage closer to the nominal level. The Agresti-Coull interval (Agresti & Coull, 1998, *The American Statistician*) adds two pseudo-successes and two pseudo-failures before computing a Wald interval.

**Formulas used:**

*Clopper-Pearson:* Lower = B(α/2; k, n−k+1), Upper = B(1−α/2; k+1, n−k) where B is the Beta quantile function.

*Wilson Score:* (p̂ + z²/2n ± z√(p̂(1−p̂)/n + z²/4n²)) / (1 + z²/n), where z = 1.96.

*Agresti-Coull:* Compute ñ = n + z², p̃ = (k + z²/2)/ñ, then apply the Wald formula p̃ ± z√(p̃(1−p̃)/ñ).

### 95% confidence intervals for 70% observed win rate at increasing N

| N | k (wins) | Clopper-Pearson | Wilson Score | Agresti-Coull |
|---|----------|-----------------|--------------|---------------|
| **20** | 14 | **[0.457, 0.881]** | [0.481, 0.855] | [0.479, 0.857] |
| **50** | 35 | [0.553, 0.824] | [0.563, 0.809] | [0.562, 0.810] |
| **100** | 70 | [0.601, 0.787] | [0.604, 0.781] | [0.604, 0.781] |
| **200** | 140 | [0.632, 0.763] | [0.633, 0.759] | [0.633, 0.759] |

**The critical observation:** at N=20, the Clopper-Pearson lower bound is **0.457 — below 50%**. This means we cannot exclude with 95% confidence that the system is no better than a coin flip. The Wilson and Agresti-Coull lower bounds (0.481 and 0.479 respectively) are similarly below 50%. Only at **N ≈ 50** does the lower bound cross above 55%, and at **N ≈ 100** does it begin approaching 60%. The three methods converge as N grows, but diverge meaningfully at small samples — the Clopper-Pearson interval is widest (most conservative), while Wilson and Agresti-Coull are nearly identical and slightly tighter.

### Exact binomial test: can we reject the coin-flip null?

For a one-tailed test of H₀: p = 0.50 vs H₁: p > 0.50, the exact p-value is P(X ≥ k | p=0.5, n):

**At N=20, k=14 (70% WR):** P(X ≥ 14) = Σ C(20,i)·0.5²⁰ for i=14..20 = 60,460/1,048,576 = **0.0577**. This *just misses* the p < 0.05 threshold. The system cannot be declared significantly better than a coin flip at 20 trades.

**At N=50, k=35 (70% WR):** Using normal approximation, z = (35−25)/√12.5 = **2.83**, giving p = **0.0023**. Highly significant.

**At N=100, k=70 (70% WR):** z = (70−50)/5.0 = **4.00**, giving p = **0.0000317**. Overwhelmingly significant.

### Minimum N to reject H₀: WR=50% at p<0.05 one-tailed

Using the normal approximation: N ≥ (1.645 / (2(p̂ − 0.50)))²

| Observed WR | Min N (normal approx) | Min N (exact binomial) |
|-------------|----------------------|----------------------|
| **70%** | 17 | ~21–25 |
| **65%** | 31 | ~35–39 |
| **60%** | 68 | ~74–80 |
| **55%** | 271 | ~284–300 |

The exact binomial values are slightly higher than the normal approximation because the continuity correction matters at small N. **A 55% edge requires nearly 300 trades to confirm statistically** — this underscores why detecting small edges demands patience.

### Power analysis: trades needed for 80% power

Using the standard power formula for one-sample proportion tests:
N = ((z_α√(p₀q₀) + z_β√(p₁q₁)) / (p₁ − p₀))²

where z_α = 1.645, z_β = 0.842, p₀ = 0.50:

| True Win Rate | Required N (80% power, α=0.05) |
|---------------|-------------------------------|
| **60%** | **153 trades** |
| **65%** | **67 trades** |
| **70%** | **37 trades** |

If Halcyon's true win rate is 70%, only **37 trades** are needed to detect it with 80% power. But if the true edge is smaller — say 60% — you need **153 trades**. Since the true rate is unknown, conservative planning should target the lower end.

### Non-normality effects on these calculations

Equity trade returns typically exhibit **excess kurtosis of 4–10** and **negative skewness** (Cont, 2001, *Quantitative Finance*). This inflates the standard error of performance estimators. Bailey & López de Prado (2012) showed that with skewness = −2 and kurtosis = 8, the minimum track record needed to validate a Sharpe ratio is **54% longer** than under normality assumptions. For win rate testing specifically, the binomial framework is robust (it doesn't assume normality of returns, only independence of outcomes), but the economic significance of wins/losses — captured by the Sharpe ratio — is heavily affected by fat tails.

### What the literature recommends for minimum trade counts

The practitioner and academic consensus forms a clear hierarchy:

- **30 trades** — absolute statistical floor per the CLT heuristic; widely considered insufficient (Van Tharp)
- **100 trades** — basic reliability for preliminary filtering (QuantConnect community, Gainium)
- **200–500 trades** — institutional-grade confidence (López de Prado, 2018, *Advances in Financial Machine Learning*)
- **500+ trades across multiple market regimes** — robust validation (BacktestBase reliability framework)

Robert Pardo (*Evaluation and Optimization of Trading Strategies*, 2008) emphasizes that no single trade count suffices — walk-forward analysis across regimes matters more than raw N. QuantifiedStrategies recommends at least **250 trades** in optimization with coverage of both bull and bear markets. The critical insight is that **500 trades in six months (one regime) provides less reliability than 100 trades over five years (multiple regimes)**.

---

## 2. The Probabilistic Sharpe Ratio quantifies track record significance

The PSR framework, developed by Bailey & López de Prado (2012, *Journal of Risk*), provides the probability that a strategy's true Sharpe ratio exceeds a benchmark SR*, given an observed sample Sharpe, sample size, and higher moments of the return distribution.

### The PSR formula

**PSR(SR\*) = Φ((SR̂ − SR\*) × √(T−1) / √(1 − γ₃·SR̂ + (γ₄−1)/4 · SR̂²))**

Where SR̂ = observed (non-annualized) Sharpe ratio, SR\* = benchmark Sharpe, T = number of return observations, γ₃ = skewness, γ₄ = kurtosis (raw, where normal = 3), and Φ is the standard normal CDF.

The derivation starts from Lo (2002, *Financial Analysts Journal*), who showed that under IID returns, the Sharpe ratio estimator is asymptotically normal with variance (1 + ½SR²)/T. Mertens (2002) generalized this to non-normal distributions, yielding the denominator term that accounts for skewness and kurtosis. The PSR is simply the resulting z-test probability.

**Critical rule:** PSR must be computed on **non-annualized per-observation** Sharpe ratios. Annualization under IID: SR_annual = SR_per-trade × √(trades_per_year). For Halcyon with ~25 trades/year, a per-trade SR of 0.20 corresponds to an annualized SR of 1.0.

### PSR calculations for specific scenarios

For SR\* = 0 (testing against zero skill), γ₃ = 0, γ₄ = 3 (normal returns):

**Panel A: Per-trade Sharpe = 1.0** (very high — mean return equals one standard deviation per trade)

| T (trades) | z-statistic | PSR(0) |
|------------|------------|--------|
| 20 | 3.56 | **99.98%** |
| 50 | 5.71 | **≈100%** |
| 100 | 8.12 | **≈100%** |
| 200 | 11.52 | **≈100%** |

A per-trade Sharpe of 1.0 is overwhelmingly significant even at 20 trades, because it implies the average trade earns one full standard deviation — an extraordinarily strong signal.

**Panel B: Per-trade Sharpe = 0.20** (annualized SR ≈ 1.0 at 25 trades/year — more realistic)

| T (trades) | z-statistic | PSR(0) |
|------------|------------|--------|
| 20 | 0.86 | **80.6%** |
| 50 | 1.39 | **91.7%** |
| 100 | 1.97 | **97.6%** |
| 200 | 2.79 | **99.7%** |

**Panel C: Per-trade Sharpe = 0.30** (annualized SR ≈ 1.5)

| T (trades) | z-statistic | PSR(0) |
|------------|------------|--------|
| 20 | 1.28 | **90.0%** |
| 50 | 2.06 | **98.0%** |
| 100 | 2.92 | **99.8%** |
| 200 | 4.14 | **99.998%** |

**The practical takeaway:** For a strategy with annualized Sharpe ≈ 1.0, reaching **PSR > 95% requires approximately 100 trades**. At 20 trades, PSR is only ~81% — well below the commonly cited 95% threshold.

### Minimum Track Record Length (MinTRL)

Inverting the PSR formula to solve for T:

**MinTRL = 1 + (1 − γ₃·SR̂ + (γ₄−1)/4 · SR̂²) × (z_α / (SR̂ − SR\*))²**

For PSR > 95% (z_α = 1.645), SR\* = 0, normal returns (γ₃=0, γ₄=3):

| Per-trade SR̂ | Annualized SR (25 trades/yr) | MinTRL (trades) | MinTRL (years) |
|--------------|-----------------------------|--------------------|-----|
| 0.10 | 0.50 | **273** | ~11 |
| 0.15 | 0.75 | **123** | ~5 |
| 0.20 | 1.00 | **70** | ~3 |
| 0.25 | 1.25 | **46** | ~2 |
| 0.30 | 1.50 | **32** | ~1.3 |
| 0.40 | 2.00 | **19** | ~0.8 |
| 0.50 | 2.50 | **13** | ~0.5 |

**With non-normal returns** (γ₃ = −1, γ₄ = 6, which is typical for equity strategies), the bracket term increases substantially. For per-trade SR = 0.20: MinTRL rises from 70 to approximately **108 trades** — a 54% increase, confirming Bailey & López de Prado's finding.

### The Deflated Sharpe Ratio corrects for multiple testing

If 10 strategy variants were tested, the DSR (Bailey & López de Prado, 2014, *Journal of Portfolio Management*) replaces SR\* with the expected maximum Sharpe under no skill:

**SR̂₀ = √(V[{SR̂ₙ}]) × ((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne)))**

where γ = 0.5772 (Euler-Mascheroni constant), N = number of independent trials.

For N=10 independent strategies with unit variance of Sharpe ratios:

Φ⁻¹(0.9) = 1.282, Φ⁻¹(0.963) = 1.792

**SR̂₀ = 1.0 × (0.423 × 1.282 + 0.577 × 1.792) = 0.542 + 1.034 = 1.576**

This means the benchmark against which the DSR tests is **SR\* = 1.576** — far above zero. A strategy that looked exceptional at SR = 1.5 would fail the DSR test entirely if 10 variants were explored.

The simplified approximation E[max SR] ≈ √(2·ln(N))·σ gives √(2·ln(10)) × 1.0 = **2.15** (less accurate for small N). The False Strategy Theorem (López de Prado & Bailey, 2021, *American Mathematical Monthly*) formalizes this: with enough trials, any Sharpe ratio is achievable under zero skill.

### Lo's standard error and the SE(SR) formula

Lo (2002) derived that under IID normal returns: **SE(SR) = √((1 + ½SR²)/T)**. For SR=1.0, T=20: SE = √(1.5/20) = **0.274**. The 95% CI for the Sharpe ratio is approximately SR̂ ± 1.96·SE = 1.0 ± 0.54, or **[0.46, 1.54]**. This enormous range at 20 observations means we cannot distinguish a mediocre Sharpe of 0.5 from an excellent 1.5. For non-IID returns with autocorrelation coefficient ρ, Lo showed that naïve annualization can overstate the Sharpe ratio by up to **65%**.

---

## 3. Paper-to-live concordance requires at least 100 paired observations

### Which test to use for detecting systematic execution drag

The paired t-test is the most powerful tool for detecting a constant mean difference (systematic drag) between paper and live fills. The KS test, while distribution-free, is poorly suited because it tests for *any* distributional difference and requires **4–6x the sample size** of a t-test to detect the same mean shift.

**Required sample sizes for 80% power at α = 0.05:**

| Target drag | σ_diff (fill variance) | Paired t-test | KS test |
|-------------|----------------------|---------------|---------|
| 5 bps | 10 bps | **34 pairs** | ~150 pairs |
| 5 bps | 20 bps | **199 pairs** | ~900 pairs |
| 10 bps | 20 bps | **34 pairs** | ~150 pairs |
| 15 bps | 30 bps | **34 pairs** | ~150 pairs |

For S&P 100 stocks with simultaneous paper/live execution, σ_diff is likely **10–30 bps** (dominated by fill timing differences). A practical target of **100–200 simultaneous paper/live trade pairs** — roughly 2–4 months of daily trading with multiple positions — should reliably detect drag of 5–10 bps.

### The concordance testing toolkit

**Bland-Altman analysis** (Bland & Altman, 1986, *The Lancet*): Plot (paper_return − live_return) vs. their mean. The mean of differences directly estimates systematic drag. Limits of agreement (mean ± 1.96·SD) show the range of random fill variation. Requires **50–100 pairs** for stable estimates. The key diagnostic: if the scatter shows a funnel shape, drag increases with trade size (proportional bias).

**Concordance Correlation Coefficient** (Lin, 1989, *Biometrics*): ρc = 2ρσ_xσ_y / (σ_x² + σ_y² + (μ_x − μ_y)²). Captures both correlation (precision) and closeness to the 45° line (accuracy). Thresholds from McBride (2005): >0.99 almost perfect, 0.95–0.99 substantial, 0.90–0.95 moderate, <0.90 poor. Target **CCC > 0.95** for paper-live concordance.

**Sequential Probability Ratio Test** (Wald, 1947): Monitor the running log-likelihood ratio of drag = 0 vs. drag = δ after each trade pair. Decision boundaries: upper A = log((1−β)/α) ≈ 2.77, lower B = log(β/(1−α)) ≈ −1.56 for α=0.05, β=0.20. SPRT is **optimal** in minimizing expected observations needed and allows continuous monitoring without inflating Type I error.

### IB vs Alpaca paper fills create opposite biases

**Interactive Brokers** simulates fills conservatively: limit orders placed at **end-of-queue**, requiring the price to trade through the limit level. Market orders fill at the opposite NBBO. Net bias: **pessimistic** — IB paper trading tends to slightly *understate* live performance for liquid equities.

**Alpaca** simulates fills optimistically: orders match against **current NBBO** without checking against available depth. Order quantity is not validated against liquidity. No slippage, market impact, or queue modeling. Net bias: **optimistic** — Alpaca paper tends to *overstate* live performance by an estimated **5–15 bps** per trade.

For S&P 100 stocks, typical bid-ask spreads are **2–5 bps** (Hagströmer, 2021, *Journal of Financial Economics* reports 2.73 bps effective spread for S&P 500). Market impact for positions of $100–$25,000 is **negligible** (<1 bps) since these represent <0.01% of average daily volume. The user's estimated **3–15 bps drag range is realistic**, with a central estimate of **5–8 bps per trade** for market orders on average S&P 100 constituents. Round-trip drag: **10–16 bps**.

---

## 4. A four-phase deployment framework with statistical gates

The framework below synthesizes academic thresholds (PSR, binomial CIs), professional quant fund practices (3–12 month incubation periods), and prop firm standards (FTMO's 5% daily/10% max drawdown limits). Each phase has progressively stricter statistical requirements.

### Phase 1: $100 — Infrastructure validation

| Parameter | Requirement |
|-----------|-------------|
| **Purpose** | Verify order routing, fills, bracket orders, error handling |
| **Min trades** | 20–30 live trades |
| **Statistical gate** | None — sample too small for significance |
| **Win rate requirement** | Track only; no minimum |
| **Max drawdown** | $25 (25% of $100 capital) |
| **Paper-live concordance** | Begin collecting paired observations; no formal test |
| **Time requirement** | 1–2 months |
| **Position sizing** | Minimum lot (1 share); risk ~$1–2 per trade |
| **Advancement criterion** | Zero operational errors in 20+ consecutive trades; fills execute correctly; bracket orders trigger properly |

**Kelly criterion note:** At 70% WR with 2:1 R:R, full Kelly is **f* = (2×0.70 − 0.30)/2 = 55%** of capital per trade. At $100 with quarter Kelly (13.75%), risk per trade = $13.75. However, position sizing at $100 is practically constrained by minimum share prices. Use **1 share positions** and focus on process validation, not returns.

### Phase 2: $1,000 — Statistical incubation

| Parameter | Requirement |
|-----------|-------------|
| **Purpose** | Build statistically meaningful track record |
| **Min trades** | 50 cumulative live trades (30+ new) |
| **Statistical gate** | One-tailed binomial p < 0.10 for WR > 50% |
| **Win rate CI** | Wilson lower bound > 50% at 90% confidence |
| **PSR gate** | PSR(0) > 85% |
| **Max drawdown** | $150 (15% of capital) |
| **Paper-live concordance** | Paired t-test: mean drag < 20 bps (p > 0.05 for drag = 0); CCC > 0.90 |
| **Time requirement** | 2–4 months |
| **Position sizing** | Quarter Kelly or ~2% risk per trade ($20) |
| **Advancement criterion** | All gates met; Bland-Altman shows no proportional bias |

### Phase 3: $5,000 — Scaling validation

| Parameter | Requirement |
|-----------|-------------|
| **Purpose** | Confirm edge persists at meaningful capital |
| **Min trades** | 100 cumulative live trades |
| **Statistical gate** | One-tailed binomial p < 0.05; PSR(0) > 95% |
| **Win rate CI** | Wilson lower bound > 55% at 95% confidence |
| **Sharpe requirement** | Per-trade Sharpe lower 95% CI > 0 (Lo SE method) |
| **Max drawdown** | $500 (10% of capital) |
| **Daily loss limit** | $250 (5% of capital) |
| **Paper-live concordance** | CCC > 0.95; Bland-Altman bias < 10 bps; SPRT not crossing upper boundary |
| **Time requirement** | 3–6 months cumulative |
| **Position sizing** | Quarter to half Kelly; ~2–5% risk per trade |
| **Advancement criterion** | All gates met; strategy has survived at least one drawdown of 5%+ and recovered |

### Phase 4: $25,000 — Production deployment

| Parameter | Requirement |
|-----------|-------------|
| **Purpose** | Full-scale production trading |
| **Min trades** | 200 cumulative live trades |
| **Statistical gate** | Binomial p < 0.01; PSR(0) > 97.5% |
| **Win rate CI** | Clopper-Pearson lower bound > 55% at 95% confidence |
| **Sharpe requirement** | Live annualized Sharpe > 0.8 (after accounting for all costs) |
| **Max drawdown** | $2,500 (10% of capital); hard kill at $3,750 (15%) |
| **Daily loss limit** | $1,250 (5% of capital) |
| **Concordance** | CCC > 0.97; confirmed drag < 15 bps per trade |
| **Time requirement** | 6–12 months cumulative |
| **Position sizing** | Half Kelly or ~5% risk per trade; volatility-adjusted |
| **Kill switch** | Halt if drawdown exceeds 1.5× maximum historical drawdown; halt if win rate drops 15 percentage points below historical average |

### Risk of ruin at each tier

Using the standard formula RoR = ((1−Edge)/(1+Edge))^N where Edge = p×b − q and N = capital units:

At 70% WR, 2:1 R:R, 1% risk per trade: Edge = 0.7×2 − 0.3 = **1.10**. Since Edge > 1.0, the risk of ruin is **effectively zero** at all capital tiers — this combination of parameters is exceptionally favorable. However, this assumes the 70% WR is the *true* rate. If the true WR is only 55% with 1.5:1 R:R (plausible at the lower confidence bound), Edge = 0.375 and with N=100 capital units, RoR drops to approximately **0.04%** — still very low with 1% risk per trade.

**The real risk is not ruin but drawdown-induced capitulation.** At full Kelly (55% of capital), there is a **50% chance of a 50% drawdown** — psychologically devastating. At quarter Kelly (13.75%), maximum expected drawdown drops to approximately 15–20%, which is manageable. Professional money managers typically use **10–15% of the Kelly optimal** allocation.

---

## 5. Paper performance must clear a higher bar to survive live drag

### Empirical decay rates from the literature

The paper-to-live performance haircut depends on strategy complexity and asset liquidity:

| Source | Study Scope | Observed Decay |
|--------|------------|----------------|
| **QuantPedia (2023)** | 417 backtested strategies | 33% mean, **44% median** Sharpe decay IS→OOS |
| **CFM (Falck, Rej & Thesmar, 2021)** | 72 published stock anomalies | **~50% Sharpe decay** post-publication |
| **Quantopian (Wiecki et al.)** | 888 algorithmic strategies | Backtest Sharpe has R² < 0.25 for OOS prediction |
| **Novy-Marx & Velikov (2018)** | High-turnover factor strategies | **50–75% of gross alpha** consumed by trading costs |

For **simple mechanical strategies on highly liquid S&P 100 stocks** — low complexity, low turnover, negligible market impact — the appropriate haircut is at the **lower end**: approximately **20–30%** of Sharpe ratio. Harvey & Liu (2015) note that the common "50% discount" rule of thumb is crude and should be calibrated to the number of strategies tested and the original Sharpe level.

### Setting paper gates to ensure live viability

If the target live Sharpe ratio is 1.0 (excellent for a simple equity strategy) and the expected paper-to-live decay is 25%:

**Required paper Sharpe gate = Target_live / (1 − haircut) = 1.0 / 0.75 = 1.33**

| Target Live Sharpe | 20% Haircut → Paper Gate | 30% Haircut → Paper Gate |
|--------------------|--------------------------|--------------------------| 
| 0.8 | 1.00 | 1.14 |
| 1.0 | 1.25 | 1.43 |
| 1.2 | 1.50 | 1.71 |

**For Halcyon Lab specifically:** With S&P 100 stocks and bracket orders on 2–15 day holds, total per-trade execution drag is estimated at 5–8 bps (half-spread plus minimal impact). Over a round-trip (entry + exit), this totals 10–16 bps. With approximately 25 trades per year and average trade return of ~1%, this execution drag represents roughly **1–1.6% of gross annual return** — a manageable cost. The appropriate paper Sharpe gate is **≥ 1.25** to ensure the live Sharpe remains above 1.0 after a conservative 20% haircut.

### Incorporating drag into gate criteria directly

Rather than applying a blanket haircut, a more precise approach subtracts estimated per-trade costs from paper returns before computing the Sharpe ratio:

1. Compute paper per-trade returns: r_paper(i)
2. Subtract estimated execution cost per trade: r_adjusted(i) = r_paper(i) − 0.0008 (8 bps)
3. Compute the "drag-adjusted Sharpe ratio" from the adjusted series
4. Apply gates to this drag-adjusted metric

This avoids the imprecision of blanket haircuts and directly accounts for the known cost structure. The DSR (Deflated Sharpe Ratio) can then be applied to the adjusted series to further correct for multiple testing.

---

## 6. Concordance protocol and practical go-live benchmarks

### Recommended concordance testing protocol

**Phase A (trades 1–50):** Run paper and live simultaneously on the same signals. Log both fill prices with timestamps.

1. Compute per-trade return difference: δᵢ = r_paper(i) − r_live(i)
2. Plot Bland-Altman chart (δ vs. average return) after 30+ pairs
3. Monitor running mean of δ (expected: 3–15 bps if Alpaca paper, possibly negative if IB paper)
4. Run SPRT continuously against H₁: |mean drag| > 20 bps

**Phase B (trades 50–100):** Formal statistical testing.

1. Paired t-test on δ: reject concordance if mean drag > 15 bps at p < 0.05
2. Compute CCC: require > 0.95
3. Test for proportional bias in Bland-Altman (correlation between δ and average return should be non-significant)
4. Stratify by stock liquidity tier: mega-cap (<3 bps expected drag) vs. smaller S&P 100 components (~10 bps)

**Phase C (100+ trades):** Steady-state monitoring.

1. Rolling 50-trade CCC window: alert if drops below 0.90
2. SPRT for regime change detection: if execution quality degrades (e.g., broker routing changes), detect within 20–30 trades
3. Quarterly Bland-Altman review with updated limits of agreement

### What professional platforms and prop firms require

**FTMO:** 10% profit target (Phase 1), 5% (Phase 2), with 5% daily loss and 10% max drawdown limits. Minimum 4 trading days. No minimum trade count.

**Topstep:** 6% profit target, 3–4% max loss, with consistency rule (best day < 50% of total profit). Express path requires 5 winning days of $150+ net P&L each.

**Collective2:** No minimum track record for signal publishing. The TOS (Trades-Own-Strategy) badge requires ~10 executed trades in a live account taking ≥90% of signals.

**FundSeeder/RQSI:** Approximately **2% of traders** pass quantitative screening. Those who pass undergo 2–5 interview rounds. Minimum **1-year real-money track record** is a practical floor for institutional seeding consideration. Metrics: Sharpe, Sortino, max drawdown, Gain-to-Pain ratio.

**Professional quant funds** (Two Sigma, Renaissance, D.E. Shaw, Citadel) employ a disciplined pipeline: hypothesis → backtest → walk-forward → incubation (3–12 months paper/reduced capital) → production. Independent risk teams monitor positions, leverage, model drift, and data pipeline health in real time. Strategies are deployed at the **lowest tier of a scaling plan** and increase allocation based on demonstrated live performance.

---

## 7. Decision tree: is Halcyon ready for live capital?

```
START: Current state (20 trades, 70% WR, paper Sharpe TBD)
│
├─ Q1: Are there zero operational errors in the last 20 trades?
│   ├─ NO → Fix infrastructure. Do not deploy live.
│   └─ YES ↓
│
├─ Q2: Is the exact binomial p-value < 0.10 for WR > 50%?
│   ├─ At N=20, p = 0.058 → YES (barely)
│   └─ ↓
│
├─ Q3: Has the system survived at least one drawdown and recovered?
│   ├─ NO → Continue paper trading until a drawdown cycle completes
│   └─ YES ↓
│
├─ GATE 1: Deploy $100 for infrastructure validation
│   │ Require: 20–30 error-free live trades
│   │ Max DD: $25 (25%)
│   │ Time: 1–2 months
│   │
│   ├─ FAIL → Revert to paper; diagnose operational issues
│   └─ PASS ↓
│
├─ Q4: At 50 cumulative live trades, is PSR(0) > 85%?
│   ├─ NO → Continue at $100 until metric improves or kill strategy
│   └─ YES ↓
│
├─ Q5: Is paper-live CCC > 0.90 with mean drag < 20 bps?
│   ├─ NO → Investigate execution quality; do not scale
│   └─ YES ↓
│
├─ GATE 2: Scale to $1,000
│   │ Require: 50+ cumulative trades; Wilson CI lower > 50%
│   │ Max DD: $150 (15%)
│   │ Time: 2–4 months cumulative
│   │
│   ├─ FAIL → Revert to $100; reevaluate strategy
│   └─ PASS ↓
│
├─ Q6: At 100 cumulative live trades, is binomial p < 0.05?
│   │ Is PSR(0) > 95%? Is drag-adjusted Sharpe > 0.8?
│   ├─ NO → Continue at $1,000; reassess at N=150
│   └─ YES ↓
│
├─ GATE 3: Scale to $5,000
│   │ Require: CCC > 0.95; Bland-Altman bias < 10 bps
│   │ Wilson CI lower > 55%; survived 5%+ drawdown
│   │ Max DD: $500 (10%)
│   │ Time: 3–6 months cumulative
│   │
│   ├─ FAIL → Reduce to $1,000; investigate
│   └─ PASS ↓
│
├─ Q7: At 200 cumulative live trades, is binomial p < 0.01?
│   │ PSR(0) > 97.5%? Live Sharpe > 0.8?
│   │ CCC > 0.97? Max DD < 10%?
│   ├─ NO → Continue at $5,000; reassess at N=250
│   └─ YES ↓
│
└─ GATE 4: Scale to $25,000 — Production
    Max DD: $2,500 (10%); hard kill at $3,750 (15%)
    Daily loss limit: $1,250 (5%)
    Quarterly Bland-Altman review
    Rolling 50-trade PSR monitoring
```

### Where Halcyon stands today

At 20 closed trades with 14 wins, 4 stops, and 2 timeouts, Halcyon is at the **earliest stage of statistical validation**. The 70% win rate produces a tantalizing signal — the binomial p-value of 0.058 is suggestive but not definitive. **The system is ready for Phase 1 ($100 live deployment)** to validate infrastructure, but not for meaningful capital allocation. The confidence intervals are simply too wide: the true win rate could plausibly be anywhere from **46% to 88%**.

The most important near-term milestone is reaching **50 trades** while maintaining ≥65% win rate, at which point the binomial test becomes significant (p < 0.01 at 70% WR) and PSR can be meaningfully computed. The second critical milestone is **100 trades**, where confidence intervals narrow sufficiently to distinguish a 60% edge from noise and the paper-live concordance protocol yields statistically reliable drag estimates.

**Expected timeline:** At Halcyon's current pace of 2–15 day holds, roughly 25 trades per year is conservative. Reaching 50 trades takes approximately 1 additional year on paper (or ~4 months if running paper and $100-live simultaneously). Reaching 100 trades takes approximately 2 years from the current 20-trade baseline. This is consistent with López de Prado's MinTRL calculations, which suggest **70 trades minimum** for a per-trade Sharpe of 0.20 and **123 trades** for a per-trade Sharpe of 0.15. There are no shortcuts: the mathematics of small samples impose hard constraints on how quickly statistical confidence can be established.

---

## Conclusion

The statistical frameworks converge on a clear message: **20 trades is insufficient to validate any trading strategy, but barely sufficient to justify the smallest possible live deployment for operational testing.** Three specific findings should anchor Halcyon's deployment planning.

First, the confidence interval arithmetic is unforgiving at small N. At 20 trades, the 95% Clopper-Pearson interval for the true win rate spans **43 percentage points** (0.457 to 0.881). The PSR requires approximately **70 trades** to reach 95% confidence for a strategy with annualized Sharpe of 1.0 under normal returns, and **108 trades** when accounting for typical non-normality in equity trade returns. These numbers align with the practitioner consensus of 100–200 trades as the minimum for actionable statistical inference.

Second, the paper-to-live decay literature provides a crucial calibration. QuantPedia's 33% mean decay, CFM's ~50% post-publication Sharpe decline, and Quantopian's finding that backtest Sharpe is a weak predictor of live performance (R² < 0.25) all argue for conservative paper gates. For Halcyon's specific context — simple mechanical strategy, highly liquid S&P 100 stocks, small position sizes — a **20–25% Sharpe haircut** is appropriate, implying paper gates should be set ~25% above the target live threshold.

Third, the phased framework solves the inherent tension between wanting statistical certainty and needing to begin live validation. The $100 phase demands zero statistical significance but perfect operational execution. The $1,000 phase introduces formal concordance testing. The $5,000 phase requires genuine statistical evidence (PSR > 95%, binomial p < 0.05). And the $25,000 production phase demands the full weight of institutional-quality validation: 200+ trades, near-certain PSR, tight concordance, and survived drawdown. Each phase produces the data that unlocks the next gate — no amount of paper trading can substitute for actual live execution data, but no amount of urgency can substitute for statistical significance.

The Kelly criterion confirms that even with conservative sizing (quarter Kelly = 13.75% per trade), the strategy's expected edge is robust against ruin. The real risk is not blowing up the account — it is deploying at scale before distinguishing genuine edge from the statistical ghosts that haunt small samples.
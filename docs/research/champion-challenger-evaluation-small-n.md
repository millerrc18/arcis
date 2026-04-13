# Comparing Financial LLMs with Fewer Than 50 Trades

**At sample sizes of 20–50 trades, classical frequentist hypothesis tests are effectively useless for detecting realistic performance differences between financial LLMs.** The minimum detectable effect size with n=25 per group is approximately **33 percentage points** in win rate — meaning only catastrophic failure or transformative improvement would register as statistically significant. This fundamental constraint reshapes the entire evaluation strategy: the Arcis system should adopt a **Bayesian-primary, guard-rail-protected, regime-adjusted** framework built around the Beta-Binomial sequential test, using the deterministic ranker as a concurrent regime control, with canary holdout tests as the first line of defense. The protocol below provides exact thresholds, phased checkpoints at n=10/25/50, and runnable Python implementations for every component.

---

## Why classical tests fail at n<50 and what replaces them

The sample size formula for comparing two proportions reveals the core problem. For a two-sided test at α=0.05 with 80% power, detecting a shift from a 55% baseline win rate to 65% requires **n≈199 per group** — four times the maximum budget. At n=25 per group, only differences exceeding 33 percentage points are detectable; at n=50, the threshold drops to 25 points but remains far beyond any realistic LLM-driven improvement.

Three methods survive this constraint. **Wald's Sequential Probability Ratio Test (SPRT)** minimizes expected sample size by accumulating evidence after each trade, potentially terminating well before n=50 if the true effect is large. The **Bayesian Beta-Binomial model** provides continuous probability estimates — "there is a 78% chance the new model is better" — without requiring a fixed sample size or suffering penalties for repeated inspection. And **Bayes Factors** provide the only method with meaningful discrimination power for equivalence testing at small n, outperforming both TOST and HDI-ROPE, which have near-zero power below n=100 (Linde et al., 2022, *Psychological Methods*).

The recommended architecture layers these methods:

- **Tier 1 — Guard rails** (always active): automatic rollback on structural failures, consecutive losses, or canary degradation
- **Tier 2 — Bayesian sequential test** (primary decision engine): Beta-Binomial posterior updating after each trade, with pre-registered stopping thresholds
- **Tier 3 — Truncated SPRT** (formal hypothesis test): runs in parallel as a frequentist crosscheck
- **Tier 4 — Regime-adjusted DiD** (confound control): isolates model effect from market environment using the deterministic ranker as a concurrent baseline

---

## The Bayesian sequential test: formulas and implementation

The Beta-Binomial model treats each model's win rate as a random variable with a Beta prior, updated after each observed trade. For Model A with s₁ wins in n₁ trades, the posterior is Beta(α₀ + s₁, β₀ + n₁ − s₁). With a uniform prior Beta(1,1), after observing 15 wins in 25 trades for Model B, the posterior becomes Beta(16, 11) with mean 0.593 and **95% credible interval [0.40, 0.77]**.

The key quantity is **P(p_new > p_old | data)**, computed via Monte Carlo sampling from both posteriors. This probability is valid at any stopping point — no alpha-spending correction required.

```python
import numpy as np
from scipy import stats

class BayesianSequentialTest:
    """Beta-Binomial sequential test for comparing two model versions."""
    
    def __init__(self, alpha_prior=1, beta_prior=1):
        self.alpha_prior = alpha_prior
        self.beta_prior = beta_prior
    
    def posterior_params(self, wins, total):
        return self.alpha_prior + wins, self.beta_prior + total - wins
    
    def prob_b_better(self, wins_a, n_a, wins_b, n_b, n_samples=100_000):
        a_alpha, a_beta = self.posterior_params(wins_a, n_a)
        b_alpha, b_beta = self.posterior_params(wins_b, n_b)
        samples_a = np.random.beta(a_alpha, a_beta, n_samples)
        samples_b = np.random.beta(b_alpha, b_beta, n_samples)
        return np.mean(samples_b > samples_a)
    
    def posterior_diff_hdi(self, wins_a, n_a, wins_b, n_b, 
                           credible_mass=0.90, n_samples=100_000):
        a_a, a_b = self.posterior_params(wins_a, n_a)
        b_a, b_b = self.posterior_params(wins_b, n_b)
        diff = (np.random.beta(b_a, b_b, n_samples) - 
                np.random.beta(a_a, a_b, n_samples))
        sorted_diff = np.sort(diff)
        ci_width = int(np.ceil(credible_mass * n_samples))
        intervals = sorted_diff[ci_width:] - sorted_diff[:n_samples - ci_width]
        best = np.argmin(intervals)
        return sorted_diff[best], sorted_diff[best + ci_width]
    
    def rope_analysis(self, wins_a, n_a, wins_b, n_b, 
                      rope=(-0.03, 0.03), n_samples=100_000):
        """Fraction of posterior difference falling within ROPE."""
        a_a, a_b = self.posterior_params(wins_a, n_a)
        b_a, b_b = self.posterior_params(wins_b, n_b)
        diff = (np.random.beta(b_a, b_b, n_samples) - 
                np.random.beta(a_a, a_b, n_samples))
        in_rope = np.mean((diff >= rope[0]) & (diff <= rope[1]))
        return in_rope
    
    def decide(self, wins_a, n_a, wins_b, n_b):
        """Pre-registered decision rule."""
        p_better = self.prob_b_better(wins_a, n_a, wins_b, n_b)
        n_total = n_b  # trades completed by new model
        
        if n_total >= 15 and p_better > 0.95:
            return "KEEP", p_better, "Strong superiority"
        if n_total >= 15 and p_better < 0.05:
            return "ROLLBACK", p_better, "Strong inferiority"
        if n_total >= 25 and p_better > 0.90:
            return "KEEP", p_better, "Moderate superiority at interim"
        if n_total >= 25 and p_better < 0.10:
            return "ROLLBACK", p_better, "Moderate inferiority at interim"
        if n_total >= 50:
            if 0.35 <= p_better <= 0.65:
                return "EQUIVALENT", p_better, "Practically equivalent"
            if p_better > 0.65:
                return "LEAN_KEEP", p_better, "Weak superiority—extend"
            return "LEAN_ROLLBACK", p_better, "Weak inferiority—default old"
        return "CONTINUE", p_better, f"Insufficient evidence at n={n_total}"

# Usage
test = BayesianSequentialTest(alpha_prior=1, beta_prior=1)
# halcyon-v1.0.0: 14 wins in 25 trades
# arcis-v1.0.0:   18 wins in 30 trades  
decision, prob, reason = test.decide(wins_a=14, n_a=25, wins_b=18, n_b=30)
print(f"Decision: {decision} | P(new>old)={prob:.3f} | {reason}")
```

**Pre-registered decision thresholds** (asymmetric to reflect the cost structure where deploying an inferior model incurs recurring losses while missing an improvement is merely an opportunity cost):

| P(new > old) | Min n | Decision |
|---|---|---|
| > 0.95 | 15 | **KEEP** — early stop for superiority |
| < 0.05 | 15 | **ROLLBACK** — early stop for inferiority |
| > 0.90 | 25 | **KEEP** — sufficient evidence at interim |
| < 0.10 | 25 | **ROLLBACK** — futility |
| 0.35–0.65 | 50 | **EQUIVALENT** — keep new for operational reasons |
| 0.65–0.90 | 50 | **LEAN KEEP** — extend to n=75 if possible |
| 0.10–0.35 | 50 | **LEAN ROLLBACK** — default to old model |

---

## Truncated SPRT as a frequentist crosscheck

The SPRT accumulates the log-likelihood ratio Λₙ = Σ log(f₁(xᵢ)/f₀(xᵢ)) after each trade. For binary outcomes, each win contributes log(p₁/p₀) and each loss contributes log((1−p₁)/(1−p₀)). The test stops when Λₙ crosses upper boundary **A = log((1−β)/α)** (reject H₀, new model is better) or lower boundary **B = log(β/(1−α))** (accept H₀). With α=0.05 and β=0.20, A ≈ 2.773 and B ≈ −1.558.

Truncation at n=50 forces a decision at the maximum sample size, with only slight power loss (from ~80% to ~74% per Siegmund, 1985). The SPRT is optimal — it minimizes expected sample size among all tests with the same error rates (Wald-Wolfowitz theorem).

```python
import numpy as np

class TruncatedSPRT:
    """Truncated Sequential Probability Ratio Test for binary outcomes."""
    
    def __init__(self, p0, p1, alpha=0.05, beta=0.20, max_n=50):
        self.p0 = p0  # H0 win rate (old model)
        self.p1 = p1  # H1 win rate (new model, to detect)
        self.alpha = alpha
        self.beta = beta
        self.max_n = max_n
        self.A = np.log((1 - beta) / alpha)       # Upper boundary
        self.B = np.log(beta / (1 - alpha))        # Lower boundary
        self.win_increment = np.log(p1 / p0)
        self.loss_increment = np.log((1 - p1) / (1 - p0))
        self.cumulative_lr = 0.0
        self.n = 0
        self.history = []
    
    def update(self, outcome):
        """Update with a single trade outcome (1=win, 0=loss)."""
        self.n += 1
        increment = self.win_increment if outcome == 1 else self.loss_increment
        self.cumulative_lr += increment
        self.history.append(self.cumulative_lr)
        
        if self.cumulative_lr >= self.A:
            return "REJECT_H0", self.n  # New model is better
        elif self.cumulative_lr <= self.B:
            return "ACCEPT_H0", self.n  # Old model is better (or no diff)
        elif self.n >= self.max_n:
            return "TRUNCATED", self.n  # Forced decision at max_n
        return "CONTINUE", self.n
    
    def truncated_decision(self):
        """Decision at truncation: use current LR position."""
        if self.cumulative_lr > 0:
            return "LEAN_NEW_MODEL"
        return "LEAN_OLD_MODEL"

# Example: detect shift from 55% to 70% win rate
sprt = TruncatedSPRT(p0=0.55, p1=0.70, alpha=0.05, beta=0.20, max_n=50)
# Simulate: first 15 trades (10 wins, 5 losses)
outcomes = [1,1,0,1,1,1,0,1,0,1,1,0,1,1,0]
for outcome in outcomes:
    decision, n = sprt.update(outcome)
    print(f"n={n}: LR={sprt.cumulative_lr:.3f} [{sprt.B:.3f}, {sprt.A:.3f}] → {decision}")
    if decision != "CONTINUE":
        break
```

Setting p₀=0.55 and p₁=0.70 means each win contributes +0.241 and each loss contributes −0.251 to the log-likelihood ratio. A run of strong performance (e.g., 10 wins in 12 trades) will cross the upper boundary rapidly, while the test will take longer when the true rate is near p₀.

---

## Isolating model effect from market regime

The sequential deployment constraint — Model A traded during period T₁, Model B during T₂ — creates a fundamental confound. Any observed performance difference could reflect the model change, the market regime change, or both. The deterministic ranker provides the cleanest solution because it is **identical across periods, regime-sensitive, and concurrent** with the LLM on every trade.

**Difference-in-Differences via the ranker baseline** isolates model alpha:

```
DiD = (mean_B_alpha) − (mean_A_alpha)
where model_alpha_i = LLM_augmented_return_i − ranker_only_return_i
```

This is mathematically equivalent to DiD = (Model_B − Ranker_B) − (Model_A − Ranker_A). If the market was harder in T₂, both Model B and Ranker will perform worse, but the alpha difference nets out the regime effect. The parallel trends assumption here requires that the LLM's marginal contribution over the ranker would have remained constant absent the model change — reasonable when the ranker captures the primary regime sensitivity.

```python
import numpy as np
from scipy import stats as scipy_stats

def regime_adjusted_comparison(alpha_a, alpha_b, n_bootstrap=10_000):
    """
    Difference-in-Differences comparison of model alpha.
    alpha_a: array of per-trade alphas for Model A (LLM_return - ranker_return)
    alpha_b: array of per-trade alphas for Model B
    Returns: DiD estimate, BCa bootstrap 90% CI, p-value
    """
    did_observed = np.mean(alpha_b) - np.mean(alpha_a)
    
    # BCa bootstrap confidence interval
    boot_diffs = []
    for _ in range(n_bootstrap):
        boot_a = np.random.choice(alpha_a, size=len(alpha_a), replace=True)
        boot_b = np.random.choice(alpha_b, size=len(alpha_b), replace=True)
        boot_diffs.append(np.mean(boot_b) - np.mean(boot_a))
    boot_diffs = np.array(boot_diffs)
    
    # Bias correction (z0)
    z0 = scipy_stats.norm.ppf(np.mean(boot_diffs < did_observed))
    
    # Acceleration (jackknife)
    combined = np.concatenate([alpha_a, alpha_b])
    n = len(combined)
    jackknife_means = []
    for i in range(n):
        jk = np.delete(combined, i)
        jk_a, jk_b = jk[:len(alpha_a)-1], jk[len(alpha_a)-1:]
        if len(jk_b) > 0:
            jackknife_means.append(np.mean(jk_b) - np.mean(jk_a))
    jk = np.array(jackknife_means)
    jk_mean = np.mean(jk)
    a = np.sum((jk_mean - jk)**3) / (6 * np.sum((jk_mean - jk)**2)**1.5 + 1e-10)
    
    # BCa adjusted quantiles
    alpha_lo, alpha_hi = 0.05, 0.95  # 90% CI
    for alpha_q, z_alpha in [(alpha_lo, scipy_stats.norm.ppf(alpha_lo)), 
                              (alpha_hi, scipy_stats.norm.ppf(alpha_hi))]:
        adj = scipy_stats.norm.cdf(z0 + (z0 + z_alpha) / (1 - a * (z0 + z_alpha)))
        if alpha_q == alpha_lo:
            ci_lo = np.percentile(boot_diffs, adj * 100)
        else:
            ci_hi = np.percentile(boot_diffs, adj * 100)
    
    # Permutation p-value
    combined_alpha = np.concatenate([alpha_a, alpha_b])
    n_a = len(alpha_a)
    count_extreme = 0
    for _ in range(n_bootstrap):
        perm = np.random.permutation(combined_alpha)
        perm_diff = np.mean(perm[n_a:]) - np.mean(perm[:n_a])
        if abs(perm_diff) >= abs(did_observed):
            count_extreme += 1
    p_value = count_extreme / n_bootstrap
    
    return {
        'did_estimate': did_observed,
        'ci_90': (ci_lo, ci_hi),
        'p_value_permutation': p_value,
        'n_a': len(alpha_a),
        'n_b': len(alpha_b)
    }
```

For every trade, the system must record the **ranker-only hypothetical outcome** alongside the LLM-augmented outcome. This counterfactual logging is the single most important data requirement — it enables computing model alpha per trade and makes regime adjustment possible retroactively.

Propensity score matching (on VIX, market direction, ranker score) serves as a sensitivity analysis but is not the primary method: with n<50, matching further reduces sample size to perhaps 15–30 pairs, destroying what little statistical power exists. ANCOVA with 2–3 regime covariates (ranker score, VIX, market direction) provides a secondary check: if the ANCOVA-adjusted model effect diverges substantially from the unadjusted DiD, regime confounding is significant and warrants caution.

---

## Metrics that work at small sample sizes

Not all evaluation metrics are created equal at n<50. The priority ranking reflects which metrics yield actionable signals with limited data versus which require hundreds of observations to stabilize.

**Tier 1 — actionable now.** XML structural compliance rate is binary per observation and meaningful even at n=5: twenty valid outputs out of twenty gives a 95% confidence interval of [0.83, 1.0], sufficient to rule out gross structural regression. **Canary holdout testing** requires zero trade outcomes — run the 5 fixed inputs through the new model before deployment and score on structural validity, conviction bounds (1–10), conviction stability (deviation ≤3 from reference), and semantic coherence (cosine similarity >0.6 against reference output). Any hard failure blocks deployment.

**Trade selection lift** directly answers the business question: Lift = P(win | conviction ≥ threshold) / P(win | all trades). A lift of 1.27 means conviction filtering improves the base win rate by 27%. With n=30–50 and a single threshold, the lift point estimate plus a bootstrap confidence interval provides the most direct evidence of LLM value.

**Tier 2 — informative direction, accumulate.** The Brier score BS = (1/N) Σ(fᵢ − oᵢ)² measures calibration but is extremely noisy below n=100. With 20–50 trades, differences of less than 0.05 between models are uninterpretable. Report with bootstrap CIs but do not use for decisions. **McNemar's exact test** on paired outcomes (ranker-only correct vs. ranker+conviction correct) captures the right comparison but requires enough discordant pairs — if the models agree on 70% of outcomes, only ~15 discordant pairs exist at n=50, yielding very limited power.

**The conviction-as-signal question** is best addressed by Firth's penalized logistic regression: logit(P(win)) = β₀ + β₁·ranker\_score + β₂·conviction. Testing H₀: β₂ = 0 directly answers whether conviction adds marginal predictive value. Firth's penalization (adding a Jeffreys prior penalty to the log-likelihood) corrects the O(n⁻¹) bias in standard MLE that afflicts small samples and prevents separation problems.

```python
from firthlogist import FirthLogisticRegression
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

def conviction_signal_test(df):
    """
    Test whether conviction score adds predictive value beyond ranker.
    df must have columns: ranker_score, conviction, win (0/1)
    """
    # Firth's penalized logistic regression
    X = df[['ranker_score', 'conviction']].values
    y = df['win'].values
    
    firth = FirthLogisticRegression()
    firth.fit(X, y)
    
    beta_conviction = firth.coef_[0][1]
    p_value_conviction = firth.pvalues_[1]
    ci_lo = firth.ci_[1][0]
    ci_hi = firth.ci_[1][1]
    
    # Spearman rank correlation (conviction vs returns)
    rho, p_spearman = scipy_stats.spearmanr(df['conviction'], df['return_pct'])
    
    # Partial correlation (conviction-outcome controlling for ranker)
    # Using manual computation
    from sklearn.linear_model import LinearRegression
    lr1 = LinearRegression().fit(df[['ranker_score']], df['conviction'])
    lr2 = LinearRegression().fit(df[['ranker_score']], df['win'])
    resid_conv = df['conviction'] - lr1.predict(df[['ranker_score']])
    resid_outcome = df['win'] - lr2.predict(df[['ranker_score']])
    partial_r, partial_p = scipy_stats.pearsonr(resid_conv, resid_outcome)
    
    return {
        'firth_beta_conviction': beta_conviction,
        'firth_p_value': p_value_conviction,
        'firth_ci_95': (ci_lo, ci_hi),
        'spearman_rho': rho,
        'spearman_p': p_spearman,
        'partial_correlation': partial_r,
        'partial_p': partial_p,
        'interpretation': (
            'Conviction ADDS value' if p_value_conviction < 0.10 and beta_conviction > 0
            else 'No evidence conviction adds value (may be underpowered)'
        )
    }
```

At n=50, Firth's regression has approximately **40% power** to detect a moderate effect (β₂ = 0.5) — meaning even if conviction truly helps, detection will fail more often than not. The Information Coefficient (IC = correlation of conviction with forward returns) requires n>780 to detect IC=0.10 at 80% power. These power limitations underscore why the evaluation framework must emphasize **preponderance of evidence** across multiple metrics rather than reliance on any single test.

---

## Conviction distribution and calibration diagnostics

Distributional shifts between model versions reveal over- or under-confidence before enough trades accumulate for outcome-based evaluation. The **Population Stability Index** (PSI) is widely used in banking for exactly this purpose: PSI = Σ(Pᵢ − Qᵢ)·ln(Pᵢ/Qᵢ), computed over conviction bins. PSI < 0.10 indicates no meaningful shift; **PSI > 0.25 signals significant distributional change** warranting investigation. The two-sample Kolmogorov-Smirnov test (KS) provides a formal test but has low power at n<50 — it can only detect gross changes (D > 0.3).

```python
from scipy import stats as scipy_stats
from sklearn.metrics import brier_score_loss
from sklearn.calibration import calibration_curve
import numpy as np

def conviction_diagnostics(convictions_a, outcomes_a, convictions_b, outcomes_b):
    """Full conviction distribution and calibration comparison."""
    
    # PSI (Population Stability Index)
    bins = np.arange(0.5, 11.5, 1)  # bins for conviction 1-10
    hist_a, _ = np.histogram(convictions_a, bins=bins, density=True)
    hist_b, _ = np.histogram(convictions_b, bins=bins, density=True)
    # Laplace smoothing
    hist_a = (hist_a + 1e-6) / (hist_a + 1e-6).sum()
    hist_b = (hist_b + 1e-6) / (hist_b + 1e-6).sum()
    psi = np.sum((hist_b - hist_a) * np.log(hist_b / hist_a))
    
    # KS test
    ks_stat, ks_p = scipy_stats.ks_2samp(convictions_a, convictions_b)
    
    # Brier scores (mapping conviction/10 -> probability)
    brier_a = brier_score_loss(outcomes_a, np.array(convictions_a) / 10.0)
    brier_b = brier_score_loss(outcomes_b, np.array(convictions_b) / 10.0)
    
    # Calibration (3 bins for small samples)
    cal_a = calibration_curve(outcomes_a, np.array(convictions_a)/10, n_bins=3)
    cal_b = calibration_curve(outcomes_b, np.array(convictions_b)/10, n_bins=3)
    
    return {
        'psi': psi,
        'psi_interpretation': (
            'No shift' if psi < 0.10 else 
            'Moderate shift' if psi < 0.25 else 'Significant shift'
        ),
        'ks_statistic': ks_stat,
        'ks_p_value': ks_p,
        'brier_a': brier_a,
        'brier_b': brier_b,
        'mean_conviction_a': np.mean(convictions_a),
        'mean_conviction_b': np.mean(convictions_b),
        'std_conviction_a': np.std(convictions_a),
        'std_conviction_b': np.std(convictions_b),
    }
```

For calibration with only 20–50 observations, standard 10-bin reliability diagrams are unusable (2–5 observations per bin). Use **3 bins maximum** (low: 1–3, medium: 4–6, high: 7–10) and plot individual data points along a LOESS-smoothed calibration line. The 1–10 ordinal conviction score is best treated as a quasi-probability by dividing by 10, though isotonic regression on pooled historical data produces better-calibrated mappings.

---

## The phased evaluation protocol

The complete protocol operates across four checkpoints, with guard rails active throughout. Every decision threshold must be **pre-registered before deployment** — locked in version control alongside the model artifacts.

### Phase 0: Pre-deployment canary gate

Run arcis-v1.0.0 on all 5 canary inputs. Each output is scored on five criteria: XML structural validity (hard fail if invalid), conviction in [1,10] (hard fail), conviction stability within ±3 of reference (soft fail), semantic coherence cosine similarity >0.6 (soft fail), and latency within 2× baseline p95 (soft fail). **Any hard fail blocks deployment. Two or more soft fails block deployment.** One soft fail proceeds with a monitoring flag.

### Phase 1: n=5 — smoke test

Verify all outputs are valid XML with conviction scores in range. No statistical analysis. Any structural failure halts deployment immediately.

### Phase 2: n=10 — first Bayesian look

Update the Beta-Binomial posterior. Only extreme results are actionable: if P(new > old) < 0.05 (10 consecutive losses, essentially), halt. Check that conviction scores are not degenerate (mean not <2 or >9). Re-run canary set to verify stability. This checkpoint is informational, not decisional.

### Phase 3: n=25 — primary interim analysis

Run the full metric battery: regime-adjusted model alpha via DiD, Bayesian posterior P(new > old), conviction-outcome correlation, Brier score with bootstrap CI, trade selection lift, and ANCOVA with VIX and ranker score as covariates. **If P(new > old) > 0.90, early-stop for superiority. If P(new > old) < 0.10, stop for futility and rollback.** Otherwise continue to n=50.

### Phase 4: n=50 — final analysis

Compute all metrics plus Bayes Factor for equivalence (interval-null BF with ROPE ±0.03). The decision tree:

```
IF P(B_alpha > A_alpha) > 0.90 → KEEP (superiority)
ELIF P(B_alpha > A_alpha - δ) > 0.90 → KEEP (non-inferiority)
ELIF P(B_alpha > A_alpha) ∈ [0.35, 0.65] → EQUIVALENT (keep new)
ELIF P(B_alpha > A_alpha) ∈ [0.65, 0.90] → extend to n=75 or keep
ELIF P(B_alpha > A_alpha) < 0.35 → ROLLBACK to old model
```

If inconclusive at n=50, the pre-registered default is to **revert to the old model** — in trading, the cost of deploying an inferior model exceeds the opportunity cost of missing a marginal improvement.

---

## Guard rails that override all statistical tests

These hard stops operate independently of the sequential test and trigger immediate rollback:

```python
class GuardRails:
    """Automatic rollback triggers independent of statistical tests."""
    
    def __init__(self, max_consecutive_losses=3, min_parse_rate=0.95,
                 max_drawdown_multiple=2.0, max_latency_multiple=2.0):
        self.max_consecutive_losses = max_consecutive_losses
        self.min_parse_rate = min_parse_rate
        self.max_dd_mult = max_drawdown_multiple
        self.max_latency_mult = max_latency_multiple
        self.consecutive_losses = 0
        self.total_trades = 0
        self.parse_failures = 0
        self.cumulative_pnl = 0.0
        self.peak_pnl = 0.0
    
    def check(self, trade_result):
        """Returns (should_rollback: bool, reason: str)."""
        self.total_trades += 1
        
        # XML parse check
        if not trade_result['xml_valid']:
            self.parse_failures += 1
        parse_rate = 1 - self.parse_failures / self.total_trades
        if self.total_trades >= 5 and parse_rate < self.min_parse_rate:
            return True, f"Parse rate {parse_rate:.1%} below {self.min_parse_rate:.0%}"
        
        # Consecutive loss check
        if trade_result['win']:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        if self.consecutive_losses >= self.max_consecutive_losses:
            return True, f"{self.consecutive_losses} consecutive losses"
        
        # Drawdown check
        self.cumulative_pnl += trade_result.get('pnl', 0)
        self.peak_pnl = max(self.peak_pnl, self.cumulative_pnl)
        current_dd = self.peak_pnl - self.cumulative_pnl
        # Compare against historical max drawdown
        hist_max_dd = trade_result.get('historical_max_dd', float('inf'))
        if current_dd > self.max_dd_mult * hist_max_dd:
            return True, f"Drawdown {current_dd:.4f} exceeds {self.max_dd_mult}x historical"
        
        return False, "All checks passed"
```

The consecutive-loss trigger deserves careful calibration. With a 55% baseline win rate, three consecutive losses occur naturally with probability 0.45³ ≈ **9.1%** — roughly once per 11 trades. This makes it a relatively sensitive trigger that will occasionally fire even for a well-performing model. Setting the threshold at **5 consecutive losses** (probability 1.8% under 55% win rate) reduces false alarms while still catching genuine degradation. Alternatively, combine with a canary failure: rollback only if consecutive losses AND a canary check also fails.

---

## What the academic literature says about small-sample strategy evaluation

Harvey & Liu (2015) in the *Journal of Portfolio Management* established that evaluating trading strategies requires far more observations than typically available, introducing the **haircut Sharpe ratio** concept that adjusts for multiple testing across strategy variants. Their later work with Zhu (2016, *Review of Financial Studies*) argued that t-statistics exceeding **3.0** (not the traditional 2.0) should be the minimum threshold for newly discovered factors, reflecting the multiple testing burden across the "factor zoo."

Bailey & López de Prado's **Deflated Sharpe Ratio** (2014) adjusts for non-normality and multiple testing: DSR = SR × √(1 − γ₃·SR/3 + (γ₄ − 3)·SR²/24) × correction for number of trials, where γ₃ is skewness and γ₄ is kurtosis. This is directly applicable to comparing Sharpe ratios between model versions but requires more observations than are available at n<50 for stable skewness/kurtosis estimates.

White's (2000) **Reality Check bootstrap** tests whether the best-performing strategy's outperformance is genuine by comparing against the distribution of maximum performance across all strategies under the null hypothesis. Romano & Wolf (2005) refined this with a stepwise procedure that controls the family-wise error rate more tightly. Both methods assume a family of strategies being compared — relevant if arcis-v1.0.0 was selected from multiple candidate fine-tunes but not if it is the only challenger.

For the specific Arcis use case, the most relevant insight from Linde et al. (2022, *Psychological Methods*) is that **Bayes Factors outperform both TOST and HDI-ROPE** for equivalence testing at small sample sizes. TOST has essentially zero power below n=100 per group — it will always return "inconclusive." The interval-null Bayes Factor provides at least rudimentary discrimination even at n=50, making it the only viable method for declaring model equivalence with this data budget.

---

## Logging schema and complete evaluation dashboard

Every trade must capture a comprehensive record enabling retrospective analysis with methods not yet anticipated. The critical requirement is storing the **ranker-only hypothetical outcome** alongside the LLM-augmented result.

```python
# Per-trade logging schema
trade_record = {
    'trade_id': 'uuid',
    'timestamp_utc': '2026-04-13T14:30:00Z',
    'model_version': 'arcis-v1.0.0',
    # Regime features
    'vix_level': 18.5,
    'vix_percentile_30d': 0.45,
    'spy_return_5d': 0.012,
    'market_direction': 'bullish',
    'sector': 'technology',
    'ticker': 'AAPL',
    # Ranker baseline (THE critical field for regime adjustment)
    'ranker_score': 7.2,
    'ranker_hypothetical_outcome': 0.015,  # what ranker-only would yield
    # LLM output
    'conviction_score': 8,
    'xml_valid': True,
    'xml_output': '<analysis>...</analysis>',
    'latency_ms': 2450,
    # Trade outcome
    'return_pct': 0.00916,
    'win': True,
    # Computed: model alpha = LLM return - ranker return
    'model_alpha': 0.00916 - 0.015,  # -0.00584 in this example
}
```

The complete evaluation dashboard integrates every component:

```python
def full_evaluation(trades_new, trades_old):
    """
    Master evaluation function.
    trades_new/old: list of trade_record dicts
    """
    results = {}
    
    # 1. Bayesian sequential test
    wins_old = sum(t['win'] for t in trades_old)
    wins_new = sum(t['win'] for t in trades_new)
    bst = BayesianSequentialTest()
    decision, prob, reason = bst.decide(wins_old, len(trades_old), 
                                         wins_new, len(trades_new))
    results['bayesian'] = {'decision': decision, 'p_better': prob, 'reason': reason}
    results['bayesian']['hdi_90'] = bst.posterior_diff_hdi(
        wins_old, len(trades_old), wins_new, len(trades_new))
    results['bayesian']['rope_mass'] = bst.rope_analysis(
        wins_old, len(trades_old), wins_new, len(trades_new))
    
    # 2. Regime-adjusted DiD
    alpha_old = [t['model_alpha'] for t in trades_old]
    alpha_new = [t['model_alpha'] for t in trades_new]
    results['did'] = regime_adjusted_comparison(
        np.array(alpha_old), np.array(alpha_new))
    
    # 3. Conviction diagnostics
    conv_old = [t['conviction_score'] for t in trades_old]
    conv_new = [t['conviction_score'] for t in trades_new]
    out_old = [int(t['win']) for t in trades_old]
    out_new = [int(t['win']) for t in trades_new]
    results['conviction'] = conviction_diagnostics(
        conv_old, out_old, conv_new, out_new)
    
    # 4. Conviction-as-signal (if enough data)
    if len(trades_new) >= 20:
        df = pd.DataFrame(trades_new)
        results['signal'] = conviction_signal_test(df)
    
    # 5. Guard rail status
    gr = GuardRails()
    for t in trades_new:
        rollback, msg = gr.check(t)
        if rollback:
            results['guard_rail_triggered'] = msg
            break
    
    # 6. Trade selection lift
    all_wins = np.array([t['win'] for t in trades_new])
    convictions = np.array([t['conviction_score'] for t in trades_new])
    base_wr = np.mean(all_wins)
    high_conv = all_wins[convictions >= 7]
    if len(high_conv) > 0:
        lift = np.mean(high_conv) / base_wr if base_wr > 0 else float('inf')
        results['lift'] = {'value': lift, 'n_filtered': len(high_conv),
                           'filtered_wr': np.mean(high_conv), 'base_wr': base_wr}
    
    return results
```

---

## Conclusion: a decision framework built for epistemic honesty

The fundamental reality of comparing financial LLMs at n<50 is that **no statistical method can deliver certainty**. The framework presented here substitutes certainty with calibrated uncertainty: Bayesian posteriors that honestly quantify how much we know, regime adjustments that isolate the model's true contribution, and guard rails that protect against the cases where statistics are too slow.

Three design principles distinguish this protocol from naive A/B testing. First, the **deterministic ranker as concurrent control** transforms an impossible causal inference problem (comparing across different time periods) into a tractable difference-in-differences analysis. Second, the **canary holdout set operating at zero marginal cost** catches catastrophic regressions before any real capital is at risk — this is the highest-value evaluation mechanism in the entire framework. Third, **pre-registration of every threshold, metric, and stopping rule** prevents the most insidious threat to valid evaluation: post-hoc rationalization of whatever the data happens to show.

The conviction-as-signal question — whether β₂ ≠ 0 in the Firth regression — will likely remain formally unresolved at n=50, with approximately 40% power for moderate effects. This is not a failure of the methodology but an honest acknowledgment that **50 trades is insufficient to statistically validate a subtle financial signal**. The practical response is to accumulate evidence across model versions, track the preponderance of directional signals, and make decisions that are conservative by default — keeping the incumbent model unless the evidence clearly favors the challenger.
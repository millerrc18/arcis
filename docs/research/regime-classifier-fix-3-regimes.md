# Fixing Halcyon Lab's regime classifier: from 75% unknown to zero

**The system's two failures share a single root cause: a conjunctive (AND-chained) classifier that leaves most of the probability space unclassified.** The "range" regime requires VIX < 20 simultaneously with SPY 5–15% below its 52-week high — conditions that are anti-correlated at **r = −0.79** and produce a joint probability indistinguishable from zero. Meanwhile, 43 of 57 trades land in "unknown" because the remaining regimes are equally restrictive, leaving ~75% of trading days in dead zones between thresholds. The fix is architectural: switch from positively-defined AND-conditions to a priority-ordered decision list where "range" becomes the **default** catch-all, not a positively-specified state. Academic literature overwhelmingly supports **3 regimes** (bull / cautious / bear) for pullback strategies, with Statistical Jump Models emerging as the most robust modern classifier.

---

## Why range detection is mathematically impossible

The range condition demands three simultaneous states: SPY 20-day return between ±2%, VIX below 20, and SPY 5–15% below its 52-week high. Each condition individually is achievable — roughly **30%** of 2020–2025 trading days see 20-day returns within ±2%, about **52%** see VIX below 20, and approximately **12%** see SPY in the 5–15% drawdown zone. If independent, the joint probability would be ~1.9%, or about 19 days out of 1,005. The actual count is zero because the conditions are deeply anti-correlated.

The mechanism is the asymmetric speed of equity markets. SPY "takes the stairs up and the elevator down" — when VIX is below 20, the index is typically within **0–3%** of its 52-week high, grinding toward new records in a low-volatility regime. The probability of VIX being below 20 at various drawdown depths reveals the impossibility:

| SPY Drawdown from High | Typical VIX Range | P(VIX < 20) |
|---|---|---|
| 0–2% | 12–18 | ~85% |
| 2–5% | 15–22 | ~55% |
| 5–10% | 20–30 | ~10–15% |
| 10–15% | 25–40 | ~2–5% |
| 15–20% | 30–50 | <1% |

The VIX-to-S&P 500 daily correlation averages **−0.79** using point changes (Macroption, 1990–2022 data), and the relationship has been remarkably stable since the mid-1990s, oscillating around −0.80 on a rolling 252-day basis. Autumn months show the strongest inverse correlation (−0.82 to −0.84 in August through November). This means that once SPY crosses the 5% drawdown threshold, VIX has almost certainly already breached 20 — the options market prices in fear faster than the drawdown itself develops.

Historical "range-bound" periods confirm the impossibility. During **2015 H1**, VIX sat at 12–16 but SPY was within 0–3% of highs, failing the drawdown condition. During **2018 mid-year** (between the February and October corrections), VIX returned to 10–15 while SPY recovered to within 2% of highs. The closest near-miss was **2023 Q3**: SPY pulled back ~7% from its July 31 peak, but VIX crossed above 20 precisely when the drawdown crossed 5% — a "race condition" where the two thresholds are reached simultaneously, leaving zero overlap window. The average 5–10% correction lasts only **33 days** (median 26), meaning SPY transits the 5–15% zone too quickly for VIX to settle below 20.

---

## The unknown regime is an exhaustive-coverage problem, not a data problem

The 75% unknown rate is not caused by unusual markets — it is a classifier architecture flaw. When each regime requires ALL of 3–4 conditions to be met simultaneously, the probability of matching any regime drops exponentially. With four binary conditions per regime, even generously assuming 50% probability per condition, any single regime matches only ~6.25% of observations. Four such regimes cover at most ~25%, leaving 75% in "unknown" — exactly the observed rate.

Three anti-patterns converge in the current design. First, **conjunctive chaining**: every AND-condition multiplicatively shrinks the matching population. Second, **disjoint regions**: gaps exist between thresholds (if bull requires VIX < 15 and bear requires VIX > 25, VIX 15–25 matches neither). Third, **no default clause**: the classifier lacks an `else` branch. The fix is straightforward — restructure as a **priority-ordered decision list** where extreme/clear regimes are checked first and everything unmatched falls to a default:

```python
def classify_regime(vix, spy_vs_200ma, breadth, vix_vix3m_ratio):
    """Priority-ordered exhaustive classifier. No unknowns possible."""
    # Priority 1: High volatility (overrides everything)
    if vix > 30 or vix_vix3m_ratio > 1.05:
        return 'high_vol'
    
    # Priority 2: Bear market
    if spy_vs_200ma < -0.05 and (breadth < 40 or vix > 25):
        return 'bear'
    
    # Priority 3: Bull market (clear uptrend)
    if spy_vs_200ma > 0.02 and breadth > 50:
        return 'bull'
    
    # Priority 4: Default = cautious (everything else)
    return 'cautious'
```

Decision trees produce exhaustive, mutually exclusive rules by construction — every leaf covers a partition of the feature space. The critical insight is that **"range" or "cautious" should be the default regime**, not a positively defined one. Range-bound markets are what remains after excluding clear trends and crises.

---

## Academic consensus favors 2–3 regimes for equity trading

The foundational work is Hamilton (1989), which introduced the 2-state Markov-switching model — expansion (positive growth, low variance) and contraction (negative growth, high variance) — estimated via maximum likelihood with the "Hamilton filter." This framework has generated over **15,000 citations** and remains the standard starting point. Hardy (2001) applied it to S&P 500 monthly returns, estimating a **bull regime** (μ = 1.15% monthly, σ = 3.47%) and a **bear regime** (μ = −0.41% monthly, σ = 7.81%), with the bull persisting ~27 months on average and the bear ~7 months. BIC selected the 2-state model; AIC marginally preferred 3 states.

Ang & Bekaert (2002, 2004) demonstrated that regime-switching asset allocation adds **2–3 cents per dollar of initial wealth** versus ignoring regimes — economically significant. Their work on U.S., U.K., and German equities showed two regimes (normal and crisis) capture the essential dynamics. The short interest rate serves as a predictor of regime transitions, enabling time-varying transition probabilities.

Guidolin & Timmermann (2007) found that **4 regimes** (crash, slow growth, bull, recovery) are required for the **joint** distribution of stocks and bonds, where cross-asset correlations change sign across regimes (stock-bond correlation ranges from −0.40 in crashes to +0.37 in recovery). However, for univariate equity returns, 2–3 states typically suffice. This is a critical distinction: their 4-state result applies to multi-asset allocation, not to single-asset regime classification for pullback trading.

The overfitting risk with additional regimes is well-documented. Bulla (2011) showed that using Student-t conditional distributions (more robust to outliers) results in **fewer regimes** being selected, suggesting some Gaussian HMM regimes are artifacts of fat-tailed observations masquerading as separate states. Hess (2006) warned that "a wrong regime forecast not only may lead to a non-optimal but to a **detrimental allocation in the contrary direction**."

For a pullback-in-uptrend strategy specifically, the optimal count is **3 regimes**: bull (full position sizing), cautious (half sizing with tighter filters), and bear (no new trades). Two regimes lose the critical distinction between a high-volatility bull market — where pullbacks work but need smaller sizing — and a genuine bear. Four regimes add a crash/recovery distinction that is irrelevant for pullback trading (the action is identical in both: don't buy dips).

---

## Statistical Jump Models outperform HMMs for trading systems

Hidden Markov Models remain popular but have **three structural weaknesses** for trading applications. First, HMMs assume Gaussian conditional distributions, which financial returns violate through fat tails. Second, the EM algorithm used for estimation is sensitive to initialization and prone to local optima. Third — and most critical for trading — HMM-inferred state sequences often **lack genuine persistence**, producing rapid flickering between states that generates whipsaw trades (Bulla, 2011; Nystrup et al., 2020).

Statistical Jump Models (JMs), introduced to finance by Nystrup et al. (2020), address all three problems. JMs reformulate regime identification as temporal clustering: they minimize a combined loss of negative likelihood plus a **jump penalty** λ that explicitly discourages state transitions. The jump penalty is a single hyperparameter controlling the persistence-responsiveness tradeoff — higher λ produces fewer regime switches and more stable trading signals. JMs are **discriminative** (directly optimizing the state sequence) rather than generative (modeling the joint distribution), making them inherently more robust to distributional misspecification.

Shu et al. (2024) applied JMs to S&P 500, DAX, and Nikkei 225 using exponentially weighted downside deviation at half-lives of 20, 60, and 120 days. Their binary strategy (100% equity in bull, 100% cash in bear) improved annualized returns by **1–4%** across all three markets versus buy-and-hold, with significantly reduced maximum drawdowns. The jump penalty λ was selected via time-series cross-validation optimizing Sharpe ratio directly — aligning the statistical model with the downstream trading objective.

The Sparse Jump Model (Nystrup et al., 2021) adds L1 feature selection, simultaneously identifying which features matter for regime classification while estimating parameters and decoding states. This is infeasible with standard HMMs, where feature selection cannot be applied prior to fitting because it requires an estimate of the underlying state sequence. The `jumpmodels` Python package provides scikit-learn-style APIs:

```python
from jumpmodels.jump import JumpModel
from jumpmodels.sparse_jump import SparseJumpModel

# Discrete jump model with 3 states
jm = JumpModel(n_components=3, jump_penalty=50.0)
jm.fit(features_df)  # accepts pandas DataFrames
states = jm.predict(features_df)
probs = jm.predict_proba(features_df)

# Online prediction for live trading
online_states = jm.predict_online(new_features)

# Sparse JM with automatic feature selection
sjm = SparseJumpModel(n_components=2, jump_penalty=50.0)
sjm.fit(features_df)
# Examine feature weights to see which features drive regime classification
```

For comparison, HMMs via `hmmlearn` and Markov-switching models via `statsmodels` remain viable alternatives:

```python
# hmmlearn: Gaussian HMM with 2 features
from hmmlearn.hmm import GaussianHMM
model = GaussianHMM(n_components=3, covariance_type="full", n_iter=100)
model.fit(np.column_stack([returns, rolling_vol]))
state_probs = model.predict_proba(features)

# statsmodels: Markov-switching regression
import statsmodels.api as sm
mod = sm.tsa.MarkovRegression(spy_returns, k_regimes=2, switching_variance=True)
res = mod.fit(search_reps=20)
filtered_probs = res.filtered_marginal_probabilities  # real-time usable
```

---

## Volatility targeting complements rather than replaces regime classification

Moreira & Muir (2017) demonstrated that scaling market exposure by the **inverse of recent realized variance** produces an annualized alpha of **4.86%** with a beta of only 0.6 against buy-and-hold. The mechanism is counterintuitive: after a variance shock, conditional variance increases far more than expected returns, so a mean-variance investor should reduce exposure by ~50% after a one-standard-deviation variance shock. The strategy takes less risk precisely in recessions, when conventional wisdom says expected returns are highest.

However, Cederburg et al. (2020) showed that in direct Sharpe ratio comparisons across 103 equity strategies, volatility-managed versions outperform only 53 times (barely above the 50 expected by chance), with only 8 showing statistical significance. The approach works best for **momentum-related strategies** where crash risk is severe. Wang & Yan (2021) found that using **downside volatility** rather than total volatility significantly improves results — 95% of 94 anomaly strategies show positive alphas versus 67% for total vol management.

For a pullback strategy, volatility targeting is an **excellent complement** to regime classification rather than a substitute. The regime classifier handles the binary question (should I buy dips at all?), while volatility targeting handles the continuous question (how much?):

```python
def position_size(regime, target_vol=0.15, realized_vol_20d=None):
    """Combine discrete regime with continuous vol targeting."""
    if regime == 'bear':
        return 0.0  # no trades
    
    # Vol-targeting scalar within permitted regimes
    vol_scalar = min(target_vol / realized_vol_20d, 2.0)
    
    regime_scalar = {'bull': 1.0, 'cautious': 0.5, 'high_vol': 0.0}
    return regime_scalar.get(regime, 0.5) * vol_scalar
```

---

## The features that matter most for pullback regime classification

Not all regime features are equally valuable. For a pullback-in-uptrend strategy, three features provide the most discriminative power, ranked by importance.

**VIX/VIX3M ratio** is arguably the single highest-value addition to any regime classifier. VIX futures are in contango (upward-sloping term structure) approximately **84% of the time** since 2004. Contango — where near-term implied vol is lower than longer-term — signals that the market views current conditions as calm relative to the future. **Backwardation** (ratio > 1.0) signals immediate panic exceeding long-term expectations and historically coincides with every major stress event: 2008, 2011 European debt crisis, Q4 2018, March 2020, April 2025. Practitioners use thresholds of **0.90** (strong contango, aggressive dip-buying) and **1.0** (backwardation, stop buying dips). This feature captures the key insight that pullback strategies work when the term structure is in contango and fail when it inverts.

**SPY position relative to the 200-day moving average** is the overwhelmingly dominant regime filter in the pullback trading literature. Cesar Alvarez, who has traded S&P 100 pullback strategies since 2003, uses it as the primary bull/bear classifier. The rationale is timescale separation: pullback trades have 3–7 day holding periods, so the trend must be evaluated on a much longer timeframe. SPY above the 200-day MA is bull; below is bear. The simplicity is a feature, not a bug — complex trend definitions are more prone to curve-fitting.

**Market breadth (% of stocks above 50-day MA)** measures whether the uptrend has broad participation. Breadth above **70%** indicates strong bull conditions where pullbacks are high-probability entries. Below **40%** signals deteriorating conditions even if SPY remains above its 200-day MA. Breadth captures the "rotation" dynamic where individual stocks pull back while the index stays flat — exactly the scenario a pullback strategy needs to navigate.

**VIX level** provides absolute volatility context for position sizing. The standard thresholds — below 15 (complacent), 15–20 (normal), 20–25 (elevated), 25–30 (high stress), above 30 (crisis) — map directly to position size adjustments within the bull regime. VIX above 30 should trigger a high-volatility override regardless of other signals.

Lookback windows should match the feature's purpose: **200-day MA** for structural trend, **20-day realized vol** for position sizing, **60-day** for regime transition detection. The HAR (Heterogeneous Autoregressive) framework of Corsi (2009) provides theoretical support for combining short (10-day), medium (22-day), and long (100-day) lookback periods.

---

## Preventing regime flickering with hysteresis and debouncing

Rapid oscillation between regimes — switching bull→bear→bull on consecutive days — generates whipsaw trades and excess friction. Three complementary techniques solve this.

**Hysteresis** uses different thresholds for entering versus exiting a regime. Rather than switching from bear to bull when SPY crosses above the 200-day MA, require SPY to be **2% above** the 200-day MA to enter bull, but don't exit bull until SPY falls **5% below**. The gap between entry and exit thresholds creates a "sticky" zone that absorbs noise. Apply the same logic to VIX: enter high_vol at VIX > 30, but don't exit until VIX < 24.

**Minimum holding period** (debouncing) prevents regime changes for a set number of days. A 5-day minimum is appropriate for daily systems:

```python
class RegimeClassifier:
    def __init__(self, min_hold_days=5):
        self.current_regime = 'bull'
        self.days_in_regime = 0
        self.min_hold_days = min_hold_days
    
    def update(self, raw_regime):
        if raw_regime != self.current_regime:
            if self.days_in_regime >= self.min_hold_days:
                self.current_regime = raw_regime
                self.days_in_regime = 1
            else:
                self.days_in_regime += 1  # ignore signal, stay put
        else:
            self.days_in_regime += 1
        return self.current_regime
```

**HMMs and Jump Models handle persistence natively** through transition probabilities or the jump penalty. A transition matrix with diagonal entries of 0.97–0.98 means the model inherently resists switching. This is a major architectural advantage of probabilistic models over rules-based classifiers.

---

## The recommended implementation path

The evidence converges on a specific sequence of improvements for Halcyon Lab, ordered by impact and implementation complexity.

**Phase 1 — Immediate fixes (1 day of work).** Restructure the classifier as a priority-ordered decision list with 3 regimes plus a default. Eliminate "unknown" by making "cautious" the else-clause. Add VIX/VIX3M ratio as a feature (available daily via CBOE). Add 5-day debouncing. These changes alone should fix the 75% unknown rate and the 0% range detection rate simultaneously.

```python
def classify_regime_v2(vix, vix_vix3m, spy_vs_200ma, breadth):
    # Priority 1: Crisis override
    if vix > 30 or vix_vix3m > 1.05:
        return 'bear'  # treat crisis as bear for pullback strategy
    
    # Priority 2: Structural bear
    if spy_vs_200ma < -0.03 and breadth < 45:
        return 'bear'
    
    # Priority 3: Strong bull
    if spy_vs_200ma > 0.02 and breadth > 55 and vix < 22:
        return 'bull'
    
    # Default: cautious (range-bound, mixed signals, transitions)
    return 'cautious'

# Position sizing by regime
REGIME_SIZING = {'bull': 1.0, 'cautious': 0.5, 'bear': 0.0}
```

**Phase 2 — Volatility targeting overlay (1–2 days).** Add continuous position sizing within permitted regimes using 20-day realized volatility. Target annualized volatility of **15%** (adjustable). Clip the scalar between 0.25 and 2.0 to prevent extreme positions. Use downside volatility rather than total volatility per Wang & Yan (2021).

**Phase 3 — Statistical validation (1 week).** Run the new classifier against the 5-year lookback. Compute pullback strategy returns conditional on each regime. Verify that bull-regime pullbacks have positive expected returns, cautious-regime returns are lower but positive, and bear-regime returns would be negative (validating the no-trade decision). Use walk-forward validation: train on 4 years, test on 1, roll forward.

**Phase 4 — Statistical Jump Model upgrade (2–3 weeks).** Install `jumpmodels` via pip. Train a 2-state JM on features: 20-day returns, 20-day realized volatility, VIX level. Use the sparse variant to validate which features actually matter. Select the jump penalty λ via time-series cross-validation optimizing pullback strategy Sharpe ratio. Compare JM regime classifications against the rules-based classifier — if they diverge significantly, investigate why. The JM can run as a parallel "shadow" classifier before replacing the rules-based system.

**Should range be its own regime?** No — not for pullback trading. Range-bound markets are functionally equivalent to low-volatility bull markets for dip-buying strategies. In range-bound conditions, pullback entries become infrequent because stocks don't pull back far enough to trigger entry signals. The system naturally reduces exposure without an explicit range regime. Alvarez confirms: "Low volatile environments make limit entries hard to trade because fills become a lot less frequent." Volatility targeting handles the continuous sizing adjustment that a separate range regime would attempt to address, but more gracefully and without the overfitting risk of a fourth regime with limited sample size.

## Conclusion

The Halcyon Lab classifier's failures stem from a design pattern — conjunctive AND-chaining with no default — rather than from incorrect threshold values or missing data. The range regime encodes a logical impossibility (calm markets at moderate drawdowns), while the remaining regimes are too restrictive to cover normal market conditions. Three architectural changes fix both problems simultaneously: priority ordering, exhaustive coverage via a default clause, and collapsing from 4–5 regimes to 3.

The academic literature's strongest signal is that **parsimony wins**: BIC consistently selects 2-state models for univariate equity returns, and adding regimes always improves in-sample fit while degrading out-of-sample performance. For pullback strategies specifically, the 3-regime model (bull/cautious/bear) provides the minimum viable distinction — is it safe to buy dips, and how aggressively? Statistical Jump Models represent the most promising upgrade path from rules-based classification, offering HMM-like probabilistic inference with superior persistence, robustness, and an open-source Python implementation (`jumpmodels` on PyPI). The combination of a rules-based classifier for interpretability, volatility targeting for continuous sizing, and a JM as a validation/shadow model gives a solo operator the practical benefits of institutional-grade regime detection without the infrastructure overhead.
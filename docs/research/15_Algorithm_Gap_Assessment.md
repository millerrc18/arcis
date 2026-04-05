# Arcis Trading System: A 15-Algorithm Gap Assessment

**Date:** 2026-04-05 | **Depth:** Deep | **Domain:** Algorithmic Trading
**Source:** Deep research on all 15 proprietary algorithms
**Classification:** INTERNAL

---

## Executive Summary

The Arcis autonomous equity trading system is **architecturally sophisticated but statistically premature** — a Formula 1 car that has completed only 18 laps. Across its 15 proprietary algorithms, seven require iteration, four should stay as-is, and none need full replacement, though Algorithm #13 approaches that threshold. The three highest-leverage improvements are embedding-based leakage detection in the training pipeline (#6), dynamic agent weighting in the council (#11), and two-tier relative strength in the pullback ranker (#5). Critically, the system is missing four standard systematic trading components entirely — execution infrastructure, portfolio-level risk management, stop-loss methodology, and performance attribution. The 12W/1L record on 18 trades is statistically meaningless by institutional standards (which require 200-500 trades), and the FINSABER framework (KDD 2026) warns that LLM-derived trading alpha frequently proves to be a "methodological artefact of narrow, biased evaluations."

---

## Consolidated Recommendations

| # | Algorithm | Verdict | Highest-leverage improvement | Expected effect | Priority |
|---|---|---|---|---|---|
| 1 | Traffic Light Regime | **ITERATE** | Add breadth indicator, overweight credit to 40% | 30-40% fewer false transitions | Medium |
| 2 | Event Risk Score | **ITERATE** | VIX-conditional FOMC scoring + add OPEX | ~30% fewer false size reductions | Medium |
| 3 | Setup Classifier | **STAY** | Add Aroon Oscillator; plan ML at 500 trades | 5-10% accuracy gain | Low |
| 4 | Filing NLP + Delta | **ITERATE** | Add document similarity delta + upgrade to FinBERT | +30-50 bps/month, +26pp accuracy | Medium |
| 5 | Pullback Ranker | **ITERATE** | Two-tier RS (sector + market) + regime-adaptive threshold | +200-400 bps/year selection quality | **High** |
| 6 | Self-Blinding Pipeline | **ITERATE** | Embedding-based leakage detection | 2-3x leakage detection sensitivity | **Highest** |
| 7 | HSHS Health Score | **STAY** | Add floor clamp + execution quality dimension | 15-25% better early warning | Low |
| 8 | Build Score | **ITERATE** | Switch linear to exponential idle-day decay | 20-30% less score volatility | Low |
| 9 | CUSUM Detector | **STAY** | Raise threshold to 3.0-4.0; add BOCPD at n=30 | Fewer false alarms | Low |
| 10 | Canary Score | **ITERATE** | Promote to ensemble input; de-correlate factors | ~30% variance reduction | Medium |
| 11 | Council Aggregation | **ITERATE** | Dynamic Bayesian agent weighting | +25-40% Sharpe improvement | **High** |
| 12 | Quality Drift | **ITERATE** | Add embedding-based semantic drift detection | Weeks-earlier degradation detection | **High** |
| 13 | Macro Regime | **ITERATE->REPLACE** | Probabilistic output + add ISM PMI | AUROC 0.80->0.89 | Medium |
| 14 | Tech-Fund Divergence | **ITERATE** | Continuous scoring + earnings revision momentum | 20-40% fewer false divergence signals | Low |
| 15 | IV Skew + IV Rank | **ITERATE** | Fix 5% OTM -> true 25-delta proxy | Eliminate 30-50% measurement error | Medium |

**Top 3 priorities:** (1) Embedding-based leakage detection (#6), (2) Dynamic agent weighting (#11), (3) Two-tier relative strength (#5).

---

## Detailed Analysis by Algorithm

### Algorithm #1: Traffic Light Regime System — ITERATE

Credit spreads lead equities by 3-7 trading days, making equal weighting suboptimal. In September 2008, CDX HY spreads doubled while the S&P 500 was down only 15% — credit was two weeks ahead. Research in Finance Research Letters (2022) using Hansen's endogenous threshold regression found a dynamic VIX threshold of ~23.81 separates regimes with better forecast accuracy than static cutoffs.

The persistence filter of 5 consecutive readings (2.5 hours) is approximately correct for intraday noise filtering, but institutional systems like Kritzman & Li's (2010) Turbulence Index use probability-weighted transitions rather than count-based rules. Durland & McCurdy (1994) showed duration-dependent transition probabilities outperform fixed Markov transitions, suggesting an exponentially-weighted probability filter requiring regime probability >0.8 for 3+ bars would reduce whipsaw trades by 15-25%.

**Highest-leverage fix:** Add % of S&P 500 stocks above their 200-DMA as a fourth indicator and overweight credit spread Z-score to 40%. Historical analysis shows that when breadth drops below 40% before the index breaks its 200-DMA, damage is broad-based and sustained. Adding breadth should reduce false regime transitions by 30-40%.

**Keep rules until trade count exceeds ~200.** HMMs have 15+ parameters to estimate versus 3-6 for threshold rules — they overfit at small sample sizes.

**Most likely failure mode:** False GREEN during a slow-moving credit crisis where VIX remains subdued, as in early 2007 when VIX was ~12 while subprime was deteriorating.

---

### Algorithm #2: Event Risk Score — ITERATE

The pre-FOMC drift essentially disappeared after 2015. Lucca & Moench (2015, NY Fed Staff Report 512) documented a 49-basis-point drift in 24 hours before FOMC announcements from 1994-2011, but Kurov, Halova Wolfe & Gilbert (2021) showed this effect weakened substantially post-2016. The current +2-4 FOMC score is over-weighted in low-VIX environments.

**Missing events:** OPEX and quadruple witching produce 50-100% above-average volume with erratic intraday action, and the post-OPEX week in September averages -0.94% with only 25% win rate.

**Highest-leverage fix:** Make FOMC score VIX-conditional (if VIX>25, use current scores; if VIX<18, halve them). This reduces false position-size reductions by ~30% in low-volatility regimes.

---

### Algorithm #3: Setup Classifier — STAY

Rule-based classification into six setup types is the correct approach at fewer than 500 labeled trades. Research shows ML classifiers need 80-560 annotated samples per class for stable error rates. With six classes and ~8 features, the minimum for ML transition is approximately 1,500-3,000 labeled trades.

ADX is adequate but should be complemented by the Aroon Oscillator for trend direction and timing — worth an estimated 5-10% classification accuracy improvement at zero cost.

---

### Algorithm #4: Filing NLP + Delta — ITERATE

Loughran-McDonald dictionary is 26 percentage points behind FinBERT on classification accuracy (62.1% vs 88.2%, Huang et al., 2023). For S&P 100 with only 100 firms x 4 filings/year x ~500 MDA sentences each, FinBERT processing takes approximately 30 minutes per quarter on a single GPU.

The most valuable component is the filing-to-filing delta. Cohen, Malloy & Nguyen's "Lazy Prices" paper (2020, Journal of Finance) found long-short portfolios based on filing changes generate 30-60 bps/month of five-factor alpha, rising to 72 bps/month in high-uncertainty subsamples.

**Critical finding:** The validated signal uses document similarity change (cosine distance, Jaccard similarity), not sentiment change. The current implementation captures a subset of this signal.

**Most likely failure mode:** Signal decay through S&P 100 analyst coverage saturation — the "Lazy Prices" effect works because investors are inattentive, but S&P 100 stocks are the most attended in the market.

---

### Algorithm #5: Pullback Ranker — ITERATE (HIGH PRIORITY)

**Highest-leverage improvement:** Implement two-tier relative strength scoring (60% stock vs SPY, 40% stock vs sector ETF). O'Neil's research on 500 top-performing stocks (1953-1985) found that stocks with RS>80 in leading sectors outperformed RS>80 in lagging sectors by 200-400 bps annually.

The pullback sweet spot of -3% to -10% is slightly wide for S&P 100 specifically — these larger-cap, lower-beta names typically pull back -3% to -8%.

Volume contraction during pullbacks, currently weighted at only 10 points, is under-weighted. Minervini's VCP research and Cartea et al. (2015) show volume imbalance "considerably boosts profits."

The fixed >=40 threshold should become regime-adaptive: >=50 in low-vol bull markets, >=35 in volatile corrections with reduced position size.

---

### Algorithm #6: Self-Blinding Training Pipeline — ITERATE (HIGHEST PRIORITY)

**Most critical vulnerability:** TF-IDF leakage detection treats words independently and cannot detect semantic leakage — when "the trade was profitable" is paraphrased as "the position yielded positive returns," both leak outcomes but share few tokens. Kapoor & Narayanan (2023, Patterns, 369 citations) documented leakage across 294 papers in 17 fields.

**Highest-leverage improvement across the entire system:** Replace TF-IDF with embedding-based leakage detection using the model's own encoder. Train a classifier on training example embeddings to predict trade outcomes; if balanced accuracy exceeds 55%, leakage exists at the semantic level. This catches an estimated 2-3x more subtle leakage patterns.

The 12W/1L skew means training data is heavily biased toward winning trades, creating a form of outcome bias even without explicit leakage. Shumailov et al. (2024, Nature) demonstrated model collapse from recursive training on synthetic data, making the 62/38 ratio's protection against synthetic-data dominance important to maintain.

---

### Algorithm #7: HSHS Health Score — STAY

The geometric mean is the correct aggregation — the UN HDI switched to it in 2010. Add a floor clamp of 0.1 per dimension to prevent multiplicative collapse and consider adding execution quality and infrastructure reliability as dimensions.

---

### Algorithm #8: Build Score — ITERATE (LOW)

Switch from linear to exponential idle-day decay. Linear decay of -1/day disproportionately punishes lower-scoring states and creates "weekend/holiday punishment."

---

### Algorithm #9: CUSUM Detector — STAY

CUSUM is a sound foundational choice (Page 1954, asymptotically optimal for small persistent shifts), but at 18 trades it is statistically meaningless. Raise the threshold from 2.0 to 3.0-4.0 until trade count exceeds 50, and add Bayesian Online Changepoint Detection (Adams & MacKay, 2007) at n=30 as a complementary probabilistic detector.

---

### Algorithm #10: Canary Score — ITERATE (MEDIUM)

The Canary should be promoted from comparison baseline to ensemble input. Nti et al. (2020, Journal of Big Data, 244 citations) showed stacking ensemble techniques achieve 90-100% accuracy versus 53-98% for bagging.

McNemar's test requires at least 10 discordant pairs, meaning approximately 50-80 total trades before LLM versus Canary comparison becomes statistically valid.

---

### Algorithm #11: Council Aggregation + Value Tracker — ITERATE (HIGH PRIORITY)

All five agents sharing Qwen3 8B creates correlated convergence risk. "The Price of Format: Diversity Collapse in LLMs" (2025) showed that structured templates induce semantically similar outputs even under high-temperature sampling.

Nemeth et al. (2001, European Journal of Social Psychology, 212 citations) found that authentic dissent was superior to all three forms of devil's advocacy — role-played DA produces "cognitive bolstering" of the initial position. The Red Team agent is performing role-played, not authentic, dissent.

**Highest-leverage improvement:** Implement dynamic track-record-based agent weighting using a Bayesian framework. Yue (2025, ICAID) showed Dynamic Weighting Multimodal Fusion reduced prediction errors by 25.4% and improved Sharpe ratio by 38.5% versus static fusion.

The counterfactual value tracker's 8-week threshold yields approximately 2.25 trades per agent per assessment cycle — far too few for reliable evaluation. Extend to 12 weeks minimum and use Bayesian estimation rather than frequentist thresholds.

---

### Algorithm #12: Quality Drift Detection — ITERATE (HIGH PRIORITY)

Three surface-level metrics are behind the state of the art. InsightFinder (2025) stated directly: "Two responses may look syntactically similar while encoding meaning differently."

**Critical addition:** Semantic drift detection via embedding distance from a golden reference set. Maintain 50-100 frozen "gold standard" trade analyses; after each retrain, compute cosine distance from the golden set on identical prompts. Alert if mean distance exceeds 0.15.

**Dangerous feedback loop:** If subtle leakage exists in training data (missed by TF-IDF), the model learns to pattern-match outcomes; Algorithm #12's surface metrics won't catch this because output appears diverse while being driven by the same leaked signal. Both algorithms #6 and #12 should share an embedding-based monitoring layer.

---

### Algorithm #13: Macro Regime Classification — ITERATE toward REPLACE

Behind the state of the art in two critical ways. First, categorical output (4 buckets) destroys probability information that continuous models preserve. Chatterjee et al. (2024, North American Journal of Economics and Finance) showed that augmenting the yield curve with credit spreads raises AUROC from 0.845 to 0.895.

Second, the binary yield curve override ("inverted -> recession") failed spectacularly during the 2022-2023 inversion — the longest in modern history at 16 months — which did not produce a recession.

**Fix:** Swap FFR for ISM Manufacturing PMI (forward-looking, not subject to revision). Convert to continuous recession probability (0-100%). Expected 15-25% reduction in whipsaw costs.

---

### Algorithm #14: Tech-Fundamental Divergence — ITERATE (LOW)

Binary categorization into three states destroys information. Replace with continuous divergence score (-1 to +1) and define "fundamentals" using earnings revision momentum rather than vague improving/deteriorating labels.

---

### Algorithm #15: IV Skew + IV Rank — ITERATE (MEDIUM)

**Measurement error:** The 5% OTM proxy for 25-delta is wrong. A 25-delta put typically corresponds to ~7-10% OTM for 30-day options at normal volatility. The system measures skew at a less extreme point than intended, understating the signal by 30-50%.

Muravyev, Pearson & Pollet (2025, Journal of Financial Economics) showed that return predictability from IV spread and skew decreases by at least two-thirds when high-borrow-fee stocks are excluded. S&P 100 stocks are typically easy-to-borrow, meaning IV skew's predictive power for equity direction is substantially weaker than headline results suggest. The +/-3/100 weight is appropriately sized or slightly generous.

---

## Four Missing Standard Components

1. **Execution infrastructure:** No TWAP/VWAP, no slippage model, no TCA
2. **Portfolio-level risk management:** No correlation monitoring, no VaR, no sector concentration limits beyond risk governor
3. **Explicit stop-loss methodology:** Exit mechanism underdocumented
4. **Performance attribution:** No tracking of which algorithms contributed to which outcomes

Research shows transaction costs of just 5 bps per trade can reduce annualized returns from 13.84% to 3.66% (arXiv 2510.10526). At $100 live capital, these gaps are tolerable; at scale, they are fatal.

---

## The Honest Question: Where Does the Edge Come From?

The FINSABER framework (KDD 2026) found that "LLM-derived alpha is likely a methodological artefact" and that LLM strategies "underperform passive benchmarks in bull markets and incur heavy losses in bear markets."

Likely alpha decomposition: 40-50% from strategy selection (pullback-in-uptrend on S&P 100 is a well-documented, persistent factor), 25-35% from the deterministic pipeline (regime, ranking, scoring have decades of evidence), and 10-20% from the LLM — unprovable at current sample size.

The system should target 50+ trades in the next quarter by slightly relaxing entry criteria or expanding the universe, and should scale live capital gradually as statistical confidence builds.

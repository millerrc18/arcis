# Arcis 15 Proprietary Algorithms — Gap Assessment, Iteration Paths, and Competitive Positioning

**Date:** 2026-04-05 | **Depth:** Exhaustive | **Classification:** PROPRIETARY
**Query:** Analyze 15 proprietary algorithms for state-of-art comparison, gaps, and improvement priorities

---

## Executive Summary

Across the 15 algorithms, four are **behind** state-of-the-art (Traffic Light Regime, Macro Regime Classification, Filing NLP, and IV Skew + IV Rank), seven are **on par** (Event Risk Score, Setup Classifier, Pullback Ranker, CUSUM Change Detector, Canary Score, Build Score, and HSHS), one is **on par with targeted gaps** (Self-Blinding Training Pipeline), one is **behind on implementation despite sound concept** (Tech-Fundamental Divergence), and one is **behind with critical under-monitoring** (Quality Drift Detection). The single highest-leverage finding is that Algorithm #15 (IV Skew + IV Rank) has two computed features -- `iv_skew` and `unusual_options_activity` -- that flow through the entire pipeline to the feature dictionary but are never consumed by the scoring function, making them dead code producing wasted compute. Across the board, the system's 18-trade sample size constrains the statistical power of any ML upgrade, validating the current rule-based architecture for most components while highlighting specific deterministic improvements (breadth in regime detection, FinBERT for filing NLP, sector-relative strength in ranking) that require no additional data to justify.

## Priority Roadmap

Based on cross-cutting analysis of risk-adjusted impact, evidence strength, and implementation effort:

**Top 3 Immediate Priorities:**

1. **Risk Management / Position Sizing** -- Implement fractional Kelly (1/2) position sizing. The Kelly Criterion practical study (Frontiers, 2020) shows 100 trades are too few for full Kelly to converge. At ~18 trades, fractional Kelly is mandatory. CTA performance attribution shows position sizing prevents ruin while trend-following contributes 70-85% of long-term returns.

2. **Regime Detection Accuracy (Algorithms #1 + #13)** -- The regime detector is a critical upstream dependency for the council, strategy selection, and volatility estimation. The regime-switching literature shows 3-4x improvement in strategy returns when regime is correctly identified. Misclassification cascades into every downstream component. Add breadth to traffic light scoring and fetch RECPROUSM156N recession probabilities from FRED.

3. **Wire Dead Features in Algorithm #15** -- `iv_skew` and `unusual_options_activity` are computed and stored but never scored. The academic evidence for options signals is strong: 50bp/week (Cremers & Weinbaum, 2010), 0.17%/week (Chordia et al., 2020), 20%+ annual alpha (Neuhierl et al., 2025). This is the highest ratio of impact-to-effort across all 15 algorithms.

**Leave Alone (validated as correct for current stage):**
- Algorithm #3 (Setup Classifier) -- rule-based is correct at 18 trades
- Algorithm #9 (CUSUM) -- algorithm choice is sound, just needs threshold calibration at 30+ trades
- Algorithm #10 (Canary Score) -- correct baseline architecture, add logging only
- Algorithm #7 (HSHS) -- well-designed, minor phase smoothing only
- Algorithm #8 (Build Score) -- geometric mean is textbook-correct, trivial decay tweak only

---

## Algorithm-by-Algorithm Analysis

### Algorithm #1: Traffic Light Regime System

**Implementation:** `src/features/traffic_light.py` and `src/features/regime.py`

#### State of the Art

The current implementation uses three equally-weighted indicators (VIX level, SPY vs 200-DMA, HY credit spread Z-score) mapped to discrete GREEN/YELLOW/RED states with a 5-reading persistence filter (~2.5 hours at 30-min scan intervals).

The academic frontier has moved significantly beyond threshold-based rules:

- **Hidden Markov Models (HMMs):** Hamilton's foundational 1989 work established 2-state regime-switching as the standard. De la Torre-Torres et al. (2021) tested MS and MS-GARCH models for S&P 500 portfolio allocation and found that MS-guided portfolios outperform buy-and-hold, but only during high and extreme volatility periods.
- **Statistical Jump Models (JMs):** Shu et al. (2024) demonstrated that JMs consistently outperform both HMM-guided strategies and buy-and-hold across US, German, and Japanese equities from 1990-2023, with superior Sharpe ratios and reduced maximum drawdown. The key advantage is enhanced regime persistence through a jump penalty, which directly addresses the whipsaw problem that the current 5-reading persistence filter crudely approximates.
- **Market breadth as regime indicator:** Zaremba et al. (2019) found that market breadth is a "robust predictor of future stock returns" across 64 countries from 1973-2018, surviving controls for momentum, volatility, and size. The current `regime.py` already computes `market_breadth_pct` but it is not fed into the traffic light scoring -- it only goes to the LLM prompt context.
- **Credit spreads as regime signals:** Alexander et al. (2008, 315 citations) found that CDS spreads are "extremely sensitive to stock volatility during periods of CDS market turbulence" and that equity hedge ratios are 3-4x larger during turbulent periods.
- **VIX weighting:** Bucci et al. (2021) found that hierarchical clustering on realized covariance matrices is the best-performing model for labelling market regimes. Goutte et al. (2017, 54 citations) demonstrated VIX can be used to invert the latent volatility state in a regime-switching model. The current equal weighting is not well-supported -- VIX carries more immediate information than the 200-DMA trend signal.

#### Our Position: BEHIND

The threshold-rule approach is roughly 1990s technology. The academic community moved to HMMs in the 1990s and to Jump Models/online Bayesian methods by 2020. However, the system's existing research document already contains a detailed specification for upgrading to HMM + Jump Model, estimating a 15-25% drawdown reduction with Sharpe improvement of 0.05-0.15.

#### Evidence Threshold

The evidence already exceeds the threshold. Shu et al. (2024) provide out-of-sample results across 3 markets over 33 years with transaction costs and trading delays. The JM outperformance is not marginal -- it shows consistent improvements in all risk metrics.

#### Highest-Leverage Improvement

**Feed breadth into the traffic light score.** The `regime.py` module already computes `market_breadth_pct` but it never enters `traffic_light.py`. Adding a 4th indicator (breadth <40% = 2, 40-65% = 1, >65% = 0) is a zero-cost change that addresses the narrow-rally failure mode directly.

#### Gap Analysis

- **Equal weighting contradicts the literature.** VIX carries higher information content for regime shifts than the 200-DMA trend signal. Alexander et al. (2008) show equity-credit sensitivity is 3-4x larger in turbulent periods, suggesting VIX and credit should dominate over the trend indicator.
- **Discrete states discard information.** Ang & Bekaert (2002, 2004) showed that portfolio weights should map continuously from filtered probabilities, not from discrete regime labels. The current GREEN=1.0/YELLOW=0.5/RED=0.1 mapping is a step function where the literature calls for a smooth function.
- **Persistence filter is theoretically unmotivated.** The 5-reading (2.5-hour) debounce is not calibrated to any empirical distribution of regime duration. JMs achieve the same goal mathematically through a jump penalty optimized via time-series cross-validation.

#### Risk Assessment

**Most likely failure mode:** The persistence filter causes the system to remain in GREEN during a rapid selloff. Five consecutive readings at 30-minute intervals means the system needs 2.5 hours of sustained RED-level conditions before switching. The March 2020 COVID crash saw VIX go from 24 to 82 in about a week, but the first big daily moves were fast -- a 2.5-hour delay could mean entering new positions at full size during the early phase of a crash.

#### Recommendation: ITERATE

Stay with the threshold system for now (it works, it's simple, you have 18 trades not 18,000), but make two incremental changes: (a) add breadth as a 4th indicator, and (b) shift to unequal weighting with VIX at 2x weight. Queue the HMM/JM upgrade for when trade count exceeds 50.

---

### Algorithm #2: Event Risk Score

**Implementation:** `src/features/event_risk_score.py`

#### State of the Art

The current implementation uses an additive scoring system: FOMC +2, NFP +1, CPI +1, OpEx +1, month-end +1, earnings proximity +2/+4. The total maps to a sizing multiplier via linear interpolation with a block threshold at 8.

- **FOMC effect is the dominant finding.** Lucca & Moench (2015, 192 citations) documented the "pre-FOMC announcement drift" -- large average excess returns on U.S. equities in anticipation of FOMC meetings that "account for sizable fractions of total annual realized stock returns." Cieslak et al. (2018, 259 citations) showed the equity premium is earned entirely in even-numbered weeks of the FOMC cycle. Brusa et al. (2019, 95 citations) found the Fed "exerts a unique impact on global equities."
- **FOMC effect size dwarfs other events.** Ai et al. (2018, 135 citations) found that stock returns around pre-scheduled macroeconomic announcements "account for 55% of the market equity premium." Hu et al. (2019, 58 citations) documented large overnight returns before NFP, ISM, and GDP announcements, but the FOMC pre-announcement drift is the strongest. Ryabinin (2023) found the difference between recession and expansion FOMC returns is 73-119 basis points per announcement day.
- **Earnings announcements carry systematic risk.** Savor & Wilson (2015, 220 citations) found firms scheduled to report earnings earn an "annualized abnormal return of 9.9%." Dubinsky et al. (2019, 74 citations) showed earnings announcement price uncertainty is "quantitatively large."
- **Options expiration effects.** Chiang (2014) documented stocks with deeply in-the-money calls experience a "significant return drop of 0.8 percentage point on option expiration dates." Stivers & Sun (2013) found weekly returns over option-expiration weeks tend to be high for S&P 100 stocks.

#### Our Position: ON PAR (with gaps)

The additive scoring approach is a reasonable practitioner heuristic. The system's main strength is that it handles the highest-impact events (FOMC, earnings). Its main weakness is the relative weighting.

#### Evidence Threshold

The evidence supports re-weighting but not a fundamental redesign. The current FOMC=2 weighting actually underweights FOMC relative to the literature given that FOMC accounts for 55% of the equity premium.

#### Highest-Leverage Improvement

**Add pre/post market earnings differentiation.** The current code treats all earnings equally. Academic evidence shows BMO vs AMC timing creates meaningfully different volatility profiles. BMO announcements cause elevated volatility for 3-5 subsequent trading days vs. AMC announcements where overnight processing absorbs more of the shock.

#### Gap Analysis

- **Missing events: Index rebalancing.** S&P 500 index additions/deletions and Russell reconstitution (June) are absent from the scoring system.
- **FOMC weighting is too low.** At +2, FOMC is weighted equal to NFP+CPI combined, but the literature shows the FOMC effect is roughly 5-10x larger.
- **Additive vs multiplicative.** For concurrent events, a multiplicative approach (0.8 x 0.6 = 0.48) would be more conservative, reflecting that concurrent event risk is compounding, not linear.
- **The Kroencke et al. (2019, 45 citations) "FOMC risk shift" finding:** FOMC announcements trigger risk-on/risk-off fund flows making it more predictable and more important for position sizing.

#### Risk Assessment

**Most likely failure mode:** Missing an OPEC+ meeting or surprise Fed inter-meeting action. The calendar approach works for scheduled events but cannot handle unscheduled events.

#### Recommendation: ITERATE

Three changes: (a) Increase FOMC from +2 to +3. (b) Add a BMO/AMC flag for earnings to differentiate scoring (+4 for BMO within 2 days, +3 for AMC within 2 days). (c) Add Russell/S&P rebalancing dates as a +1 event.

---

### Algorithm #3: Setup Classifier

**Implementation:** `src/features/setup_classifier.py`

#### State of the Art

Uses 5 hand-crafted features (ADX, ATR/price, volume profile, price vs MAs, RSI) to classify stocks into 6 setup types via ordered if/elif rules.

- **Gu, Kelly, and Xiu (2020)**, "Empirical Asset Pricing via Machine Learning," *Review of Financial Studies* 33(5):2223-2273. Neural networks achieved an annualized out-of-sample Sharpe ratio of 1.35 using 94 firm characteristics. The dominant predictive signals were variations on momentum, liquidity, and volatility -- mapping closely to the 5 features used here.
- **Krauss, Do, and Huck (2017)**, *European Journal of Operational Research*. Ensemble of gradient boosted trees, random forests, and neural nets yielded 0.45% daily return before costs. Trees matched or beat neural nets on structured tabular financial data.
- **Deep et al. (2024)**, arXiv:2412.15448. Training R-squared of 0.749-0.812 collapsed to negative values out-of-sample on random forest models. Traditional indicators like RSI and Bollinger Bands contributed only 14-15% of feature importance. Cautionary finding about overfitting with small feature sets.

#### Our Position: ON PAR (with appropriate caution)

The 5-feature rule-based classifier is the correct architecture for 18 trades. The code's docstring correctly identifies this: "With <200 closed trades, there is not enough labeled data to train a reliable setup classifier." The features chosen align with Gu et al.'s finding that momentum, liquidity, and volatility are the dominant predictive signals.

#### Evidence Threshold for ML Transition

- **Minimum viable**: 50 labeled examples per class (300 total across 6 classes) for a simple tree classifier.
- **Recommended**: 100+ per class (600+ total) for gradient boosted trees with 5-10 features.
- **Conservative (Harvey-Liu adjusted)**: Minimum t-statistic of 3.18 to account for multiple testing.
- **Practical recommendation**: Begin champion-challenger at 200 trades, commit to ML transition at 500+ trades with 50+ per class using gradient boosted trees (not neural networks).

#### Highest-Leverage Improvement

The 5 features map to Gu et al.'s three dominant families (momentum, liquidity, volatility). **Gap identified**: No liquidity/size feature. Adding average dollar volume could help distinguish between setups. RSI is somewhat redundant with ADX + price vs MAs. ADX is the correct choice for setup classification (measures trend strength, not direction). STAY with ADX.

#### Gap Analysis

| Gap | Severity | When to Address |
|---|---|---|
| No ML comparison baseline | Low (correct for n=18) | At 200+ trades |
| Missing liquidity feature | Low (S&P 100 universe) | At next feature review |
| RSI partially redundant with ADX+MAs | Negligible | When adding ML |
| No cross-validation of rule thresholds | Medium | At 100+ trades |

#### Risk Assessment

With n=18 and Wilson score intervals, a 78% observed accuracy has a 95% CI of [54.8%, 91.5%] -- you cannot distinguish a 65% accurate classifier from a 90% accurate one. This is why the rule-based approach is correct.

#### Recommendation: STAY

The rule-based classifier is the correct architecture for 18 trades. Begin logging a champion-challenger experiment at 200 trades using gradient boosted trees.

---

### Algorithm #4: Filing NLP + Delta

**Implementation:** `src/features/filing_nlp.py`

#### State of the Art

- **FinBERT vs. Loughran-McDonald Dictionary:** Kirtac & Germano (2024), analyzing 965,375 news articles from 2010-2023, found GPT-3-based OPT achieves 74.4% sentiment accuracy, FinBERT achieves 72.2%, and L-M dictionary achieves only 50.1% -- essentially random. Long-short Sharpe ratios: OPT = 3.05, FinBERT = 2.07, L-M = 1.23.
- **Huang, Wang & Yang (2023, *Contemporary Accounting Research*, 393 citations)** found FinBERT "substantially outperforms the Loughran and McDonald dictionary," with dictionary methods underestimating textual informativeness of earnings conference calls by at least 18-32%.
- **L-M Subset Comprehensiveness:** The current implementation uses ~110 negative, ~50 positive, and ~42 uncertainty words. The full L-M master dictionary contains ~2,355 negative, 354 positive, and 297 uncertainty words. The subset covers roughly 4.7% of the negative list and 14% of the positive list.
- **Filing Delta / Lookback:** Li (2010, *Journal of Accounting Research*, 1,123 citations) found forward-looking statement tone in 10-K MD&A sections positively predicts future earnings. The 1-filing delta is the correct baseline.
- **Fog Index:** Loughran & McDonald (2014, *Journal of Finance*, 794 citations) showed the Fog Index is poorly specified in financial applications. Bonsall et al. (2017, 473 citations) introduced the "Bog Index" with nearly 25% greater association with future stock return volatility. For S&P 100 (high analyst coverage), readability is a weak signal.
- **Earnings Call Tone:** Price & Johnson (2012) found conference call linguistic tone is a significant predictor of abnormal returns, with "conference call tone dominates earnings surprises over the 60 trading days following the call." In-sample R-squared of 9.75%, out-of-sample R-squared of 8.38%.

#### Our Position: BEHIND (significantly on sentiment method; on-par on delta approach)

The L-M dictionary at ~5% coverage of the master list is operating well below the method's own potential, and the method itself is 15 years behind the frontier. The accuracy gap (50% vs 72-74%) is the difference between noise and signal.

#### Highest-Leverage Improvement

**Upgrade to FinBERT for filing sentiment scoring.** The Huang FinBERT model is open-source, runs on CPU at ~100 sentences/second, can process a 10-K MD&A section in under 60 seconds. For 100 tickers with quarterly filings (~400 filings/quarter), this is ~40 minutes/quarter on the RTX 3060.

#### Gap Analysis

| Gap | Severity | Evidence Level |
|-----|----------|----------------|
| L-M dictionary vs FinBERT accuracy | **Critical** | Definitive (multiple large-sample studies) |
| L-M subset is ~5% of master list | **High** | Structural (measurable coverage gap) |
| No earnings call tone integration | **Medium-High** | Strong (R-sq 8-10%, dominates earnings surprise) |
| Readability (Fog) not used | **Low** for large-caps | Loughran-McDonald 2014 showed Fog is mis-specified |
| Delta uses 1-filing lookback | **Low** | 1-filing is the standard |

#### Recommendation: ITERATE (phased upgrade)

- **Phase 1 (immediate):** Expand L-M word lists from ~200 words to the full master dictionary (~3,000 words). Zero-cost, zero-risk improvement.
- **Phase 2 (next sprint):** Integrate FinBERT for filing sentiment. Replace `score_filing_sentiment()` with FinBERT inference.
- **Phase 3 (backlog):** Add earnings call tone as a feature.
- **Skip:** Fog Index / readability for large-caps.

---

### Algorithm #5: Pullback Ranker

**Implementation:** `src/ranking/ranker.py`

#### State of the Art

Uses a deterministic 0-100 scoring function: trend(30), relative strength(25), pullback_depth(25), distance_SMA20(10), volume(10), options(+/-3), regime(+/-10).

- **Jegadeesh and Titman (1993)**, *Journal of Finance*. Buying top-decile past winners yielded approximately 1% per month across 3-12 month formation periods. Confirmed over 30+ years of subsequent research, though weakened in large-cap US stocks.
- **Cooper, Gutierrez, and Hameed (2004)**, *Journal of Finance*. Mean monthly momentum profit of 0.93% following positive market returns, but -0.37% following negative market returns. Directly supports the regime adjustment mechanism.
- **Daniel and Moskowitz (2016)**, *Journal of Financial Economics*. Momentum strategies can lose up to 90% in a single month during market rebounds. Their dynamic momentum strategy that adjusts for forecasted variance doubled the static strategy's Sharpe ratio. Validates the regime adjustment of -10.
- **Antonacci (2014)** and **Faber (2010)** both found dual momentum (combining market-relative and sector-relative strength) outperforms either alone. Antonacci's Global Equities Momentum showed +440 bps/year above S&P 500 for dual momentum vs +200 bps for relative momentum alone.
- **Bulkowski (1991-2008)**, 9,372 samples in 841 stocks: pullbacks occur 56% of the time after breakouts. Shallower pullbacks have stronger continuation. Depth distribution relatively uniform across 4-10%.

#### Our Position: ON PAR (with one significant gap)

The weight structure captures the primary academic factors. The regime adjustment is well-supported. **However, relative strength is measured only against SPY.** This is the one area where the literature clearly indicates improvement potential.

#### Highest-Leverage Improvement

**Split RS scoring: 15 pts market-relative + 10 pts sector-relative.** The `compute_sector_context()` data already exists. A stock can outperform SPY while underperforming its sector (sector tailwind carrying a weak stock), or underperform SPY while outperforming its sector (strong stock in a weak sector -- often the better trade).

#### Gap Analysis

| Gap | Severity | Effort | Evidence Strength |
|---|---|---|---|
| RS measured vs SPY only, not sector | HIGH | Low (data exists) | Strong (Antonacci, Faber) |
| Fixed weights not calibrated to IC | MEDIUM | Low at 200 trades | Strong (Grinold-Kahn) |
| No volatility-adjusted pullback depth by cap size | LOW | Low | Moderate (Bulkowski) |
| Missing factor momentum signal | LOW | Medium | Moderate (Ehsani-Linnainmaa) |
| No dynamic regime weight (fixed +/-10) | MEDIUM | Medium | Strong (Daniel-Moskowitz) |

#### Recommendation: ITERATE

Two changes warranted now: (1) Split RS into market-relative + sector-relative. (2) Log per-feature IC starting now so weight recalibration data is ready at 200 trades.

---

### Algorithm #6: Self-Blinding Training Pipeline

#### State of the Art

- **Leakage Detection:** Yang et al. (2025) showed temporal leakage can inflate RMSE by over 20.5% even with standard cross-validation. The Yale NLP group's comprehensive survey on data contamination (ACL 2024 Findings) catalogues methods including n-gram decontamination, embedding-based overlap detection, and membership inference attacks -- all more sensitive than TF-IDF for subtle leakage.
- **Synthetic Data Ratios:** Kang et al. (Meta/Virginia Tech, 2025) found optimal mixing ratios converge at approximately 30% synthetic / 70% natural data. The 62/38 curated-to-synthetic ratio (~38% synthetic) is in the right neighborhood but slightly above the empirically-derived optimum.
- **RL-Based Training:** DeepSeek-R1 (January 2025) demonstrated GRPO achieving competitive reasoning without a critic model. DAPO (ByteDance/Tsinghua, March 2025) improved on GRPO scoring 50 points on AIME 2024 vs. GRPO baseline of 30 (67% improvement) using 50% fewer training steps. For financial domain, FinTral (2024) used DPO with RLAIF, outperforming GPT-4 on several FinBen benchmarks with a 7B model.
- **Financial Commentary Benchmarks:** FinBen (NeurIPS 2024): 36 datasets, 24 tasks, 7 dimensions. FLaME (2025) evaluated 23 LMs across 20 FinNLP tasks. LLM-as-Judge survey (2024) found pairwise comparisons more reliable than point scoring, and multi-dimensional decomposition is best practice.

#### Our Position: ON PAR (with targeted gaps)

The temporal firewall architecture is sound and ahead of many production systems. The outcome-conditioned template approach is novel. The 6-dimension rubric aligns with emerging best practices. However, the TF-IDF leakage detector is behind state-of-the-art, and the system lacks RL-based training entirely.

#### Highest-Leverage Improvement

**Add embedding-based leakage detection alongside TF-IDF.** Cosine similarity between outcome-grouped commentary embeddings (using the existing Ollama model) would catch semantic leakage that TF-IDF misses. Implementation cost: ~50 lines of code.

#### Gap Analysis

| Gap | Severity | Effort |
|-----|----------|--------|
| TF-IDF-only leakage detection misses semantic patterns | Medium | Low |
| No causal inference test (does removing outcome info change classifier accuracy?) | Medium | Medium |
| He et al. 2025 citation unverifiable | Low | N/A |
| No RL-based training (GRPO/DPO) | Medium | High |
| No external benchmark validation of rubric | Low | Medium |

#### Recommendation: ITERATE

Add embedding-based leakage detection (2 days). Add a permutation-based causal test (1 day). Defer GRPO/RL until Phase 2. Keep the 62/38 ratio but set up an A/B framework to validate empirically.

---

### Algorithm #7: HSHS (System Health Score)

#### State of the Art

- The UNDP Human Development Index uses 3 dimensions with geometric mean. Mazziotta & Pareto (2022) showed the geometric mean satisfies all desired properties for composite indicators (monotonicity, continuity, normalization, anonymity, penalization of imbalance).
- PGIM uses 6 risk dimensions including operational risk and model risk as distinct categories. ESMA (2025) separates infrastructure risk from market and operational risk.
- The power mean provides a continuous spectrum: p=1 (arithmetic), p->0 (geometric), p=-1 (harmonic). No published work demonstrates that an intermediate power mean outperforms geometric for system health specifically.

#### Our Position: ON PAR to slightly AHEAD

The 5-dimension decomposition covers essential axes. Phase-dependent weighting is a sophisticated design choice not common in published frameworks. The geometric mean is the correct aggregation. The main gap versus institutional frameworks is the absence of explicit infrastructure/regulatory dimensions, but those are less relevant for a solo paper-trading operation.

#### Highest-Leverage Improvement

**Add smooth phase transitions instead of discrete jumps.** Currently, crossing from month 6 to month 7 causes an immediate weight shift. A linear interpolation between phase weight vectors over 2-month windows would prevent score discontinuities. Implementation: ~15 lines.

#### Gap Analysis

| Gap | Severity | Effort |
|-----|----------|--------|
| No infrastructure dimension (uptime, latency, error rates) | Low (for now) | Medium |
| Discrete phase transitions create score jumps | Low | Low |
| No cost/efficiency dimension | Low | Medium |
| Defensibility dimension is proxy-heavy (time as a moat) | Low | N/A |

#### Recommendation: STAY

The HSHS is well-designed. Smooth the phase transitions (1 day). Defer adding infrastructure/regulatory dimensions until live trading.

---

### Algorithm #8: Build Score

#### State of the Art

- **Composite Indicator Aggregation:** The OECD/JRC Handbook on Composite Indicators recommends the geometric mean for composite indicators where dimensions represent non-substitutable qualities. The UNDP switched HDI from arithmetic to geometric mean in 2010 for precisely this reason.
- **Decay Functions:** Behavioral economics research on temporal discounting consistently finds hyperbolic (not linear or exponential) decay best describes value degradation over time. In ML, exponential decay is standard because it preserves proportionality. Linear decay creates asymmetry: -1 from score 80 is 1.25%, but -1 from score 10 is 10%.

#### Our Position: ON PAR

The geometric mean choice is textbook-correct. The 6-component decomposition covers essential dimensions. The linear decay is the weakest design choice.

#### Highest-Leverage Improvement

**Switch to exponential decay** with a half-life of ~30 days: `score * 0.977^idle_days`. Prevents the pathological case where a prolonged outage makes the score meaningless (30 idle days linear = -30 points, potentially negative; exponential = 50% reduction, still informative). Implementation: 1 line change.

#### Recommendation: STAY (with one minor tweak)

Switch decay to exponential (1 line). Do not add a financial dimension until Phase 2. The Build Score will naturally become less central as the system matures.

---

### Algorithm #9: CUSUM Change Detector

**Implementation:** `src/evaluation/change_detector.py`

#### State of the Art

Textbook symmetric CUSUM from Lopez de Prado's AFML Chapter 17, with a fixed threshold of 2.0 and no drift adjustment. Monitors closed trade P&L percentages.

- **CUSUM remains solid for this application.** Kim et al. (2022) proposed KW-ICSS achieving 81% true positive rate vs. 72.57% for standard AIT-ICSS.
- **Bayesian Online Change Point Detection (BOCPD):** Tsaknaki et al. (2023) applied BOCPD to NASDAQ order flow with superior out-of-sample predictive performance. Altamirano et al. (2023) proposed a robust Bayesian approach "more than 10x faster than its closest competitor."
- **For small samples:** Bourazas et al. (2023) proposed the Predictive Ratio CUSUM (PRC), a Bayesian scheme using sequentially updated predictive distributions, specifically designed for "online quality monitoring of a process with low volume data."
- **Threshold calibration:** Lopes et al. (2025) found "a single setup may not be universally suitable across the entire time series." The current fixed threshold of 2.0 is not calibrated to the system's actual P&L distribution.

#### Our Position: ON PAR (but under-configured)

The CUSUM choice is defensible. The implementation is clean and correct. Problems: (a) threshold not calibrated, (b) only P&L percentage monitored, (c) 18 trades is below the useful range for any change detection method.

#### Highest-Leverage Improvement

**Calibrate the threshold to the actual P&L distribution.** Compute the standard deviation of closed trade P&L percentages and set threshold = k * sigma, where k is chosen for desired average run length under the null hypothesis.

#### Gap Analysis

- **Single-metric monitoring is insufficient.** Hoga (2017, 20 citations) demonstrated multivariate monitoring provides "gains in power and shorter detection times."
- **The 10-trade minimum is too low.** Even at 10 trades, CUSUM has essentially no power. A more honest threshold would be 30-50 trades.
- **No ARL calibration.** The threshold is unmoored from any statistical guarantee.

#### Recommendation: STAY

Keep CUSUM. Raise minimum trade count to 30. Calibrate threshold to empirical P&L sigma at 30+ trades. Add win rate and holding period as parallel metrics. Plan switch to Bayesian PRC at 50+ trades.

---

### Algorithm #10: Canary Score

**Implementation:** `src/strategy/canary.py`

#### State of the Art

A 6-rule additive system: start at 5, adjust +/-1 for trend, pullback depth, volume contraction, RSI, relative strength, and ATR. Produces integer 1-10. Runs alongside the LLM as a comparison baseline.

- **McNemar's Test for Paired Classifier Comparison:** Requires at minimum 25 discordant pairs. With 30% disagreement rate, need ~84 paired trades minimum for the test to have power. For 80% statistical power at 5% significance to detect a 15-percentage-point accuracy difference: approximately 100 paired trades.
- **Harvey and Liu (2015)** recommend a minimum t-statistic of 3.18 to establish significance after multiple testing. At 50 paired trades, you would need an implausibly large effect size.
- **Krauss et al. (2017)** found simple model ensembles outperformed individual models: ensemble 0.45%/day vs best individual at 0.43%/day. Supports using canary as ensemble input rather than just comparison baseline.

#### Our Position: ON PAR (correct architecture for current stage)

The canary IS a linear factor model expressed as if/elif rules. Each rule adjusts by +/-1 (unit weight). At current sample size, this is optimal.

#### Highest-Leverage Improvement

Begin logging error correlation between LLM and canary signals. The ensemble decision at 100 trades should be data-driven. If error correlation < 0.7, begin testing ensemble. Use inverse-variance weighting, not simple average.

#### Key Sample-Size Milestones

| Milestone | Trades | Action |
|---|---|---|
| Current | 18 | No statistical tests have power. Rules are correct. |
| 50 | Begin exploratory LLM vs canary paired analysis (sign-rank test) |
| 100 | McNemar's exact test. Begin ensemble testing if error correlation < 0.7 |
| 200 | Compute per-feature IC for weight recalibration. Begin ML champion-challenger |
| 500 | Commit to ML classifier if validated out-of-sample |

#### Recommendation: STAY (with immediate logging addition)

Do not modify scoring logic. Begin logging error correlation structure on every trade.

---

### Algorithm #11: Council Aggregation

#### State of the Art

**Multi-agent LLM debate literature** converges on 3-5 agents as the empirically supported sweet spot:
- Chan et al. (2023): 3-4 debaters is optimal.
- Zhang et al. (2024a): 3 agents ideal, odd numbers preferred.
- Zhang et al. (2024b): significant improvements from 3 to 5 agents but only marginal gains scaling to 9.
- Ju et al. (2024): significant accuracy drop scaling from 5 to 10 agents.
- Du et al. (2023): continuous improvement up to 7 on mathematical tasks specifically.

**Google DeepMind's "Towards a Science of Scaling Agent Systems"** found: independent multi-agent systems amplified errors by 17.2x; centralized systems contained amplification to 4.4x. On parallelizable tasks, centralized coordination achieved +81% improvement. On sequential tasks, multi-agent systems degraded performance by 39-70%.

**Committee decision-making theory:** Karotkin & Paroush (2003, 51 citations) show that enlarging a committee triggers a quality-versus-quantity tradeoff. Sibert (2006, 128 citations) concludes the ideal committee may not have many more than 5 members. Lamberson & Page (2012, 87 citations, *Management Science*): in small groups, the most accurate type should dominate, not diversity.

**Delphi method validation:** Graefe & Armstrong (2011, *International Journal of Forecasting*): no statistically significant overall accuracy differences between face-to-face, nominal groups, Delphi, and prediction markets. Delphi outperformed face-to-face for 2 of 10 questions. Prediction markets were rated least favorable and inferior for 3 questions. For LLM agents: agreements solidify within 2-3 rounds (Xiong et al., 2023), performance peaks at 3 rounds and fluctuates after (Pham et al., 2024), only ~0.5% of discussions benefit from multi-agent debate (Becker et al., 2025).

**Published trading results:** TradingAgents (Xiao et al., 2024) with 7 agents showed AAPL Sharpe 8.21 vs B&H -1.29, GOOGL Sharpe 6.39 vs B&H 1.35. MarketSenseAI (GPT-4): 73% accuracy, 72% cumulative return over 15 months, Sharpe 2.49. Caveats: 3-month backtest windows, unrealistically high Sharpe ratios, no transaction costs reported.

#### Our Position: ON PAR

5 agents is defensible and at the upper bound of the empirical optimum. The Modified Delphi (blind vote, debate, final) aligns with the 3-round empirical optimum.

#### Recommendation: STAY

Do NOT increase to 7+ agents. Consider making Round 2 explicitly adversarial (Red Team). Make the council regime-aware (feed regime detection output as context) rather than creating strategy-specific councils.

---

### Algorithm #12: Quality Drift Detection

#### State of the Art

- **Model Collapse Science:** Shumailov et al. (Nature, 2024) established iteratively training on model-generated data causes irreversible collapse where tails disappear first. Dohmatob et al. (ICLR 2025 Spotlight) proved even 0.1% synthetic contamination prevents scaling benefits. Shi et al. identified a 0.91 Pearson correlation between training data entropy and model generalization scores -- making entropy the single best collapse predictor.
- **Drift Detection Metrics:** Production LLM monitoring best practices recommend embedding cosine distance (>0.15 = meaningful drift), entropy tracking, confidence score distribution shifts, and response length variance. Evidently AI identifies 5 methods: cosine distance, Euclidean distance, MMD, K-S test on embeddings, and share of drifted features.
- **Semantic Drift:** Denham (2025, SSRN) showed neighborhood semantics degrade before surface statistics show problems. Arbuzov et al. (2025) found only 5-10% of tokens are "key tokens" where errors matter.
- **Rollback Thresholds:** SemEval 2025 established 75% preservation threshold. Production recommendation: 5% relative drop = retraining trigger, 10% drop = rollback trigger.

#### Our Position: BEHIND

The current 3-metric approach (distinct-1/2, self-BLEU, vocab_size) captures surface-level degradation but misses semantic drift entirely. The 0.91 correlation between entropy and collapse means the current metrics are missing the most predictive signal.

#### Highest-Leverage Improvement

**Add embedding-based semantic drift detection using the existing Ollama model.** Compute embeddings for a "golden set" of 20-30 high-scoring training examples. On each retraining cycle, compute centroid distance. Alert if cosine distance exceeds 0.15. Uses existing infrastructure, adds the most predictive signal, costs ~20 lines of code.

#### Gap Analysis

| Gap | Severity | Effort |
|-----|----------|--------|
| No semantic drift detection (embedding distance) | **High** | Low |
| No entropy tracking (strongest collapse predictor) | **High** | Low |
| No defined rollback threshold | Medium | Low |
| No key-token analysis (5-10% decision tokens) | Low | Medium |

#### Recommendation: ITERATE

Add two metrics: (1) embedding centroid distance from golden set, (2) output entropy. Define rollback thresholds: >10% relative decline on quality_score OR cosine distance >0.25 = halt retraining and rollback. Expected effort: 2-3 days.

---

### Algorithm #13: Macro Regime Classification

**Implementation:** `src/data_enrichment/macro.py`

#### State of the Art

Fetches 5 FRED series (FEDFUNDS, DGS10, DGS2, CPIAUCSL, UNRATE), computes yield curve spread and CPI YoY, classifies into 4 categories: recession, early_cycle, mid_cycle, late_cycle.

- **Yield curve is the most robust single predictor.** Chauvet & Potter (2001, 239 citations) found strong evidence for recession forecasting. Hansen (2023) showed combining VIX with yield curve spread "significantly outperforms the yield-curve spread alone."
- **Multi-indicator models outperform.** Berge (2015, 46 citations): "the most useful model is simple but makes use of all relevant indicators." Kiley (2023): "approaches emphasizing the yield curve overstate the recession signal if other factors are not considered."
- **Financial conditions are critical.** Levanon et al. (2015, 60 citations) developed a "Leading Credit Index" that predicts recession probabilities better than individual indicators.
- **Probabilistic beats categorical.** The Chauvet-Hamilton model on FRED (series RECPROUSM156N) uses 4 monthly coincident variables and outputs continuous 0-100% probability.
- **FFR >4% threshold is fragile.** The Cleveland Fed estimates nominal neutral rate (r-star) at ~3.7% as of Q2 2025. The current hardcoded threshold will miscategorize when the equilibrium rate shifts.

#### Our Position: BEHIND

The 4-indicator, 4-category system is simplified 1990s technology. Categorical output discards probability information. The yield-curve-only recession trigger is specifically called out by Kiley (2023) as overstating recession risk.

#### Highest-Leverage Improvement

**Switch from categorical to probabilistic output sourced from FRED.** The `RECPROUSM156N` series provides Chauvet-Hamilton smoothed recession probabilities -- a research-grade signal from professional macroeconomists. Map probability to cycle phases: <5% = expansion, 5-30% = caution, >30% = recession risk. This is a one-FRED-series-fetch change.

#### Gap Analysis

- **Missing ISM PMI** -- multiple papers identify it as one of the best short-horizon recession predictors.
- **Missing housing indicators** -- Berge (2015) found housing produces the best forecasts at longer horizons.
- **Missing credit conditions** -- the HY credit spread in `traffic_light.py` partially covers this but is not used in macro regime classification.
- **Fixed FFR thresholds will break** -- neutral rate was ~2.5% in 2019 and ~3.7% in 2025. Should compute stance relative to r-star.
- **Unemployment >5% as recession trigger is too simple** -- the Sahm Rule (0.5pp increase in 3-month MA relative to 12-month low) has correctly identified every recession since 1970 with no false positives.

#### Recommendation: ITERATE

Three changes: (a) Add `RECPROUSM156N` as continuous recession signal. (b) Replace fixed FFR threshold with relative-to-r-star calculation. (c) Add ISM Manufacturing PMI as a 6th indicator.

---

### Algorithm #14: Tech-Fundamental Divergence

**Implementation:** `src/features/filing_nlp.py`

#### State of the Art

- **Technical vs. Fundamental Combination:** Sawhney et al. (2025) found "technical data predicts stock returns better than accounting information" but "both contain independent predictive content." Nti et al. (2020, *Artificial Intelligence Review*, 122 papers) found only 11% of stock prediction research uses combined approaches.
- **Continuous vs. Categorical:** Current implementation uses 3 categories (`convergence_bullish`, `divergence_caution`, `neutral`). Gottschlich & Hinz (2014) found symbolic predictors can outperform continuous GARCH models, but discretizing always loses information. The 3-category scheme has no `convergence_bearish` or `divergence_bullish` category -- 2 of 4 possible quadrants collapsed into "neutral."
- **Large-Cap Evidence:** Most divergence alpha research is concentrated in small/mid-cap stocks. For S&P 100, analyst coverage is dense, weakening the filing-based fundamental signal.

#### Our Position: ON PAR (concept), BEHIND (implementation)

The concept is sound and academically supported. But the implementation is too coarse (3 categories), misses half the quadrant space, and the fundamental input is degraded (L-M dictionary problem from Algorithm #4).

#### Highest-Leverage Improvement

**Complete the 4-quadrant divergence matrix** and **output a continuous divergence score** rather than categories.

#### Gap Analysis

| Gap | Severity | Evidence Level |
|-----|----------|----------------|
| Missing 2 of 4 quadrants | **High** | Structural logic gap |
| Categorical vs continuous output | **Medium** | General statistical principle |
| Fundamental input is L-M dictionary (50% accuracy) | **High** | Inherited from Algorithm #4 |
| No revenue/margin/guidance integration | **Medium** | Supported by combined-signal literature |
| Untested for large-caps specifically | **Medium** | Literature concentrates on small-cap |

#### Recommendation: ITERATE

Phase 1 (immediate): Complete 4-quadrant matrix. Add continuous score in [-1, +1]. Phase 2: Automatically improves when Algorithm #4 upgrades to FinBERT. Phase 3: Add revenue trajectory and margin trends. Do NOT increase weight until backtested on S&P 100.

---

### Algorithm #15: IV Skew + IV Rank

**Implementation:** `src/data_collection/options_metrics.py` and `src/ranking/ranker.py`

#### State of the Art

- **5% OTM Proxy for 25-Delta:** At 40% IV (common during corrections), a 25-delta put is closer to 12-15% OTM, not 5%. For S&P 100 stocks in normal conditions (IV ~15-25%), the proxy has roughly 1-3pp error. During high-vol regimes, error reaches 5-8 points.
- **Volatility Surface vs Single Expiration:** Kim & Park (2020, *Journal of Futures Markets*) found long-term IV curve exhibits "extra predictive power for subsequent month stock returns." Doran & Fodor (2010, 62 citations) showed parsing skew into components significantly improves predictive power.
- **Put/Call Ratio vs IV Skew:** Cremers & Weinbaum (2010, *JFQA*, 553 citations) documented stocks with relatively expensive calls outperform by 50 basis points per week. An et al. (2014, *JFQA*, 351 citations) found decile spreads of ~1%/month persisting up to six months.
- **Risk-Neutral Skewness:** Chordia, Lin & Xiang (2020, *JFQA*, 27 citations) found 0.17%/week return differential driven by informed trading. Neuhierl et al. (2025, *Management Science*) found three-factor alpha exceeding 20% per annum from option characteristics.
- **Unusual Activity:** Easley, O'Hara & Srinivas (1998, *Journal of Finance*, 1,171 citations) established "negative and positive option volumes contain information about future stock prices."
- **Current Weighting (+/-3 out of 100):** Given the evidence (50bp/week, 20%+ annual alpha), the current weight is too conservative by a factor of 2-3x.

#### Our Position: BEHIND (correct signals, under-weighted and imprecise)

The right signals are captured but the 5% OTM proxy introduces regime-dependent error, only one expiration is used, and the +/-3 weighting substantially underweights a signal with demonstrated alpha. **Most critically: `iv_skew` and `unusual_options_activity` are computed, stored, loaded into features, but never consumed by `_score_ticker()`. These are dead features.**

#### Highest-Leverage Improvement

**Wire `iv_skew` and `unusual_options_activity` into `_score_ticker()`.** This is a bug-level gap -- the system already pays the compute cost to produce these signals but never uses them.

#### Gap Analysis

| Gap | Severity | Evidence Level |
|-----|----------|----------------|
| IV skew computed but NOT USED in ranker | **Critical** | Code inspection -- dead feature |
| 5% OTM proxy error in high-vol regimes | **Medium** | Options pricing theory; 5-8pp error in corrections |
| Single expiration (no term structure) | **Medium** | Kim & Park 2020 |
| Options weight too low (3/100) | **High** | Multiple papers: 50bp/week, 20%+ annual alpha |
| Unusual volume flag not used in ranker | **Medium** | Computed but not scored |

#### Recommendation: ITERATE (urgent)

- **Phase 1 (immediate, critical):** Wire `iv_skew` into `_score_ticker()`. Negative skew should boost score for pullback entries; extreme positive skew should be caution.
- **Phase 2 (immediate):** Wire `unusual_options_activity` into `_score_ticker()`.
- **Phase 3 (next sprint):** Increase options block from +/-3 to +/-6-8.
- **Phase 4 (next sprint):** Replace fixed 5% OTM with Black-Scholes delta-based strike lookup: `strike = spot * exp(-0.675 * sigma * sqrt(T))`.
- **Phase 5 (backlog):** Add term structure skew (compare 30-day to 90-day skew).

---

## Cross-Cutting Analysis

### Interaction Effects

The highest-risk coupling is documented by research on systemic failures in algorithmic trading (PMC, 2022), applying Perrow's Normal Accident Theory:

- The 2010 Flash Crash: a single $4.1B sell order triggered algorithmic responses that wiped $1 trillion in market value within 5 minutes.
- Knight Capital (2012): dormant code activation lost $460 million in 45 minutes.
- Researchers estimate ~14 smaller flash crashes occur every trading day in U.S. markets.
- Key insight: tight coupling + complex interactions = inevitable normal accidents.

Google DeepMind's finding that independent multi-agent errors amplify by 17.2x is directly applicable. The three highest-risk couplings in this system:

1. **Regime detector + Ranker**: If regime is misclassified, the ranker scores for the wrong environment. Both wrong simultaneously = compounded error. This is the single biggest correlation risk.
2. **Council + Regime**: If the council receives wrong regime context, all 5 agents reason from false premises.
3. **Position sizer + Volatility estimator**: Wrong vol estimate directly scales position size incorrectly.

**Recommendation:** Add explicit "circuit breakers" between pipeline stages -- independent sanity checks that do not depend on the upstream signal being correct.

### Redundancy

Likely redundancy clusters:
- **Regime detection + Macro agent in council**: Both assess market environment. The macro agent's regime assessment may duplicate the quantitative regime detector.
- **Technical signals + Trend/Momentum indicators**: Multiple algorithms scoring the same price-derived features.
- **Sentiment from news ingestion + Strategic/Innovation council agents**: Council agents reading the same news the ingestion pipeline already processed.

**Recommendation:** Compute a correlation matrix of 15 algorithm outputs over historical data. Any pair with correlation >0.7 is likely measuring the same thing. Use mutual information for detecting nonlinear redundancy.

### Missing Algorithms

Priority ranking for the <50 trade regime:

1. **Transaction Cost Model (HIGH)**: Currently absent. Even a simple spread + commission model prevents the most common backtest-to-live disappointment. At current trade frequency, a flat model per-instrument is adequate.
2. **Correlation-Based Sizing (MEDIUM-HIGH)**: Correlated positions effectively multiply exposure. The position sizer should account for portfolio-level correlation, not just individual position risk. This is the most common cause of unexpectedly large drawdowns.
3. **Slippage Estimation (MEDIUM)**: Research identifies relative spread (52.47% weight) and price volatility (coefficient 0.78) as dominant drivers. A model using these two inputs captures most variance.
4. **Portfolio Optimization (LOW at 50 trades)**: Full mean-variance optimization requires covariance matrix estimation unreliable with <100 observations. Simpler approaches (equal risk contribution, volatility-targeted sizing) dominate at current scale.

### Competitive Positioning

**What Renaissance Technologies focused on first** (from Acquired.fm analysis and historical record):
1. Data cleaning and infrastructure -- Sandor Straus built the data pipeline first, processing ~1 TB annually even in the early phase.
2. Signal-to-noise ratio -- hunting for "micro-patterns: small, short-term correlations that, when aggregated and leveraged properly, could yield enormous, low-risk profits."
3. Statistical rigor -- recruited mathematicians and cryptanalysts, not traders.

**Two Sigma's founding philosophy**: Set up as a technology company, hired data scientists over MBAs, focused on infrastructure competing with Google/Amazon.

**At the 50-trade mark**: Successful firms invested in (a) data quality, (b) proving signals are real and not overfit, and (c) infrastructure reliability. They did NOT invest early in complex execution algorithms, multi-model ensembles, or LLM agents.

**Honest assessment**: 15 algorithms, an LLM council, a fine-tuned Qwen3 model, regime detection, and more -- this is far more complex than what any successful systematic firm had at 50 trades. The risk is that complexity masks whether there is real signal. Lopez de Prado's "factor mirage" concept applies: complexity + correlation-based validation = high risk of finding patterns that are not causal.

**Recommendation:** Before adding more sophistication, run a dead-simple baseline -- equal-weight buy-and-hold or a single SMA crossover system -- and rigorously compare full system out-of-sample performance. If you cannot beat the simple baseline by a statistically significant margin across regimes, the complexity is not adding value.

### Model Dependency (LLM vs Deterministic)

**Where LLMs add genuine value:**
- Kirtac et al. (2024, 48 citations): OPT achieved 74.4% sentiment accuracy vs. L-M dictionary at 50.1%. Long-short Sharpe: 3.05 vs 1.23. A genuine, large effect size for text-based signals.
- Lopez-Lira & Tang (2023, 242 citations): GPT-4 achieved ~90% hit rate on initial reaction direction. Average daily return: 44 bps (t-stat=4.24). But strategy returns decline as LLM adoption rises.
- Siddique et al. (2025): Hybrid LLM + traditional ML achieved 77.4% accuracy, Sharpe of 1.20.

**Where LLMs do NOT add value:**
- ChatGPT is no better than simple linear regression for purely numerical prediction tasks.
- GPT-4 accuracy on numerical stock prediction (60%) matched a specialized narrow ML model (60%).
- The comprehensive survey of 84 studies (Jadhav et al., 2025) notes few studies address robustness and reliability.

**Critical finding:** LLM marginal value is highest for text interpretation and reasoning about qualitative information. For quantitative signals, simpler models perform equivalently or better.

**Recommendation:** Track frequency of council overrides vs agreement with the deterministic pipeline. If the council agrees >90% of the time, it is expensive decoration. If it disagrees 10-30% and those disagreements are profitable, it is adding genuine edge.

---

## Summary Table

| # | Algorithm | Position | Recommendation | Highest-Leverage Change | Risk |
|---|-----------|----------|---------------|------------------------|------|
| 1 | Traffic Light Regime | BEHIND | ITERATE | Add breadth to scoring, unequal VIX weighting | Persistence filter too slow for flash events |
| 2 | Event Risk Score | ON PAR | ITERATE | BMO/AMC earnings differentiation, increase FOMC weight | Missing OPEC/rebalancing; FOMC underweighted |
| 3 | Setup Classifier | ON PAR | STAY | Begin logging for ML champion-challenger at 200 trades | Premature ML overfitting |
| 4 | Filing NLP + Delta | BEHIND | ITERATE | Expand L-M to full dictionary; upgrade to FinBERT | L-M at ~5% coverage producing noise not signal |
| 5 | Pullback Ranker | ON PAR | ITERATE | Split RS into market-relative + sector-relative | Missing sector-relative information |
| 6 | Self-Blinding Pipeline | ON PAR | ITERATE | Add embedding-based leakage detection | TF-IDF misses semantic leakage |
| 7 | HSHS | ON PAR+ | STAY | Smooth phase transitions | Discrete weight jumps |
| 8 | Build Score | ON PAR | STAY | Switch to exponential decay (1 line) | Linear decay distortion at extremes |
| 9 | CUSUM Change Detector | ON PAR | STAY | Calibrate threshold to empirical P&L sigma | False sense of security at n=18 |
| 10 | Canary Score | ON PAR | STAY | Add error correlation logging | Statistical inference impossible at n=18 |
| 11 | Council Aggregation | ON PAR | STAY | Keep 5 agents, keep 3-round Delphi | Diminishing returns above 5 agents |
| 12 | Quality Drift Detection | BEHIND | ITERATE | Add semantic drift via golden-set embeddings | Missing the 0.91-correlated entropy signal |
| 13 | Macro Regime Classification | BEHIND | ITERATE | Fetch RECPROUSM156N recession prob from FRED | Fixed FFR thresholds will miscategorize |
| 14 | Tech-Fund Divergence | ON PAR/BEHIND | ITERATE | Complete 4-quadrant matrix; continuous score | Missing 2 of 4 quadrants |
| 15 | IV Skew + IV Rank | BEHIND | ITERATE (urgent) | Wire `iv_skew` + `unusual_volume` into ranker | Dead features wasting compute |

---

## Sources

### Tier 1: High-citation foundational papers (>100 citations)

- Alexander et al. (2008) - [Regime dependent determinants of credit default swap spreads](https://consensus.app/papers/details/d863a02d55ac57cc91e77c8389c0db95/). *Journal of Banking and Finance*, 315 citations.
- An et al. (2014) - Implied volatility changes and stock returns. *JFQA*, 351 citations.
- Ai et al. (2018) - [Risk Preferences and the Macroeconomic Announcement Premium](https://consensus.app/papers/details/1316d7a0ad80554691070418666254fa/). *Econometrica*, 135 citations.
- Brusa et al. (2019) - [One Central Bank to Rule Them All](https://consensus.app/papers/details/3ea6126656fa5419a32d37b53559a905/). 95 citations.
- Chauvet & Potter (2001) - [Forecasting recessions using the yield curve](https://consensus.app/papers/details/53268d38557a5ef180f7a0946601694b/). 239 citations.
- Cieslak et al. (2018) - [Stock Returns over the FOMC Cycle](https://consensus.app/papers/details/81e37f3d03965594a358bc0f1147aa50/). 259 citations.
- Cooper, Gutierrez & Hameed (2004) - Market States and Momentum. *Journal of Finance* 59(3):1345-1365.
- Cremers & Weinbaum (2010) - Deviations from put-call parity and stock return predictability. *JFQA*, 553 citations.
- Daniel & Moskowitz (2016) - Momentum Crashes. *Journal of Financial Economics* 122(2):221-247.
- Easley, O'Hara & Srinivas (1998) - Option volume and stock prices. *Journal of Finance*, 1,171 citations.
- Gu, Kelly & Xiu (2020) - [Empirical Asset Pricing via Machine Learning](https://academic.oup.com/rfs/article/33/5/2223/5758276). *Review of Financial Studies* 33(5):2223-2273.
- Harvey & Liu (2015) - [Backtesting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489). *Journal of Portfolio Management* 42(1):13-28.
- Huang, Wang & Yang (2023) - Financial FinBERT. *Contemporary Accounting Research*, 393 citations.
- Jegadeesh & Titman (1993) - [Returns to Buying Winners and Selling Losers](https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf). *Journal of Finance* 48(1):65-91.
- Killick et al. (2014) - [changepoint: An R Package for Changepoint Analysis](https://consensus.app/papers/details/ef6de953a294503883b36b79d282359d/). *Journal of Statistical Software*, 1,355 citations.
- Krauss, Do & Huck (2017) - [Statistical Arbitrage on the S&P 500](https://www.sciencedirect.com/science/article/abs/pii/S0377221716308657). *European Journal of Operational Research* 259(2):689-702.
- Li (2008) - Annual report readability and current stock returns. *Journal of Accounting and Economics*, 2,412 citations.
- Li (2010) - Forward-looking statements. *Journal of Accounting Research*, 1,123 citations.
- Lopez-Lira & Tang (2023) - [Can ChatGPT Forecast Stock Price Movements?](https://consensus.app/papers/details/82c878d6b7935d82952fe1b13591a198/). 242 citations.
- Loughran & McDonald (2014) - Measuring readability in financial disclosures. *Journal of Finance*, 794 citations.
- Lucca & Moench (2015) - [The Pre-FOMC Announcement Drift](https://consensus.app/papers/details/f661e295a0085948a7593408840cdcf2/). *Journal of Finance*, 192 citations.
- Polikar (2006) - [Ensemble based systems in decision making](https://consensus.app/papers/details/64f229e418be5c2f85a6cf04fbd39595/). 2,765 citations.
- Savor & Wilson (2015) - [Earnings Announcements and Systematic Risk](https://consensus.app/papers/details/c9681e9ce1a9510b969bab0314101cf9/). 220 citations.
- Shumailov et al. (2024) - [AI models collapse when trained on recursively generated data](https://www.nature.com/articles/s41586-024-07566-y). *Nature*.

### Tier 2: Recent high-quality papers (2020-2026)

- Altamirano et al. (2023) - [Robust and Scalable Bayesian Online Changepoint Detection](https://consensus.app/papers/details/4c7e5c90b7e553afa11d881bbc2f42d6/). 21 citations.
- Arbuzov et al. (2025) - [Beyond Exponential Decay: Rethinking Error Accumulation in LLMs](https://arxiv.org/html/2505.24187v1).
- Berge (2015) - [Predicting Recessions with Leading Indicators](https://consensus.app/papers/details/361d01733b89562d95b05b1b8f42df17/). *Journal of Forecasting*, 46 citations.
- Bonsall et al. (2017) - Bog Index. *Journal of Accounting and Economics*, 473 citations.
- Bourazas et al. (2023) - [Predictive Ratio CUSUM (PRC)](https://consensus.app/papers/details/3d6afac4478a5ac79117146b42b8531a/). *Journal of Quality Technology*, 6 citations.
- Bucci et al. (2021) - [Market regime detection via realized covariances](https://consensus.app/papers/details/ef2e8f0de8fb53c9ad8d82f43ddea301/). *Economic Modelling*.
- Chordia, Lin & Xiang (2020) - Risk-neutral skewness and informed trading. *JFQA*, 27 citations.
- De la Torre-Torres et al. (2021) - [Enhancing Portfolio Performance with Markov-Switching GARCH](https://consensus.app/papers/details/328b94e8614151e6904429b18991cb10/). *Mathematics*.
- Deep et al. (2024) - [Technical Indicators on ML Models](https://arxiv.org/html/2412.15448v1). arXiv.
- Denham (2025) - [Semantic Collapse in Embedding Space](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5547918). SSRN.
- Dohmatob et al. (2025) - [Strong Model Collapse](https://openreview.net/forum?id=et5l9qPUhm). ICLR 2025 Spotlight.
- Dubinsky et al. (2019) - [Option pricing of earnings announcement risks](https://consensus.app/papers/details/9c76538602d559978486efe6ba7e7cbe/). *Review of Financial Studies*, 74 citations.
- Ehsani & Linnainmaa (2022) - Factor Momentum and the Momentum Factor. *Journal of Finance* 77(3):1877-1919.
- Ferrari Minesso et al. (2022) - [Text-Based Recession Probabilities](https://consensus.app/papers/details/6fed60cc280154869e141a3c05033000/). *IMF Economic Review*.
- Goutte et al. (2017) - [Regime-switching stochastic volatility model](https://consensus.app/papers/details/275d01e5d59051fe81170b06ca5cb6a5/). *Applied Mathematical Finance*, 54 citations.
- Hansen (2023) - [Predicting Recessions Using VIX-Yield-Curve Cycles](https://consensus.app/papers/details/ded67d1153e05ecbb95a14abf26bdcc1/). SSRN.
- Hoga (2017) - [Monitoring multivariate time series](https://consensus.app/papers/details/31fc2019cef254198ec758d77b12441a/). *J. Multivar. Anal.*, 20 citations.
- Kang et al. (2025) - [Demystifying Synthetic Data in LLM Pre-training](https://arxiv.org/html/2510.01631v1). Meta/Virginia Tech.
- Kiley (2023) - [Recession Signals and Business Cycle Dynamics](https://consensus.app/papers/details/bbabda941f5c599d89dc109c8b49b059/). Fed.
- Kim et al. (2022) - [Unsupervised Change Point Detection with CUSUM](https://consensus.app/papers/details/81a790e717ad5f89b57df8485d21f7b0/). *IEEE Access*, 13 citations.
- Kim & Park (2020) - Long-term implied volatility curve. *Journal of Futures Markets*.
- Kirtac & Germano (2024) - [Sentiment trading with LLMs](https://consensus.app/papers/details/48cadb14c1f2521f831c11ef26c752e2/). 48 citations.
- Kroencke et al. (2019) - [The FOMC Risk Shift](https://consensus.app/papers/details/79d4af80178e58e88ba93d016b8fbdd2/). 45 citations.
- Lamberson & Page (2012) - [Optimal Forecasting Groups](https://consensus.app/papers/details/e9d05100fc2057f0b5c72a321f92f9a1/). *Management Science*, 87 citations.
- Levanon et al. (2015) - [Using financial indicators to predict turning points](https://consensus.app/papers/details/302110d70c965c309a4a8f767d80e1bf/). *International Journal of Forecasting*, 60 citations.
- Lopes et al. (2025) - [Online Meta-Recommendation of CUSUM Hyperparameters](https://consensus.app/papers/details/f5a857caf8f75ba49a4742fa422984a9/). *Sensors*, 3 citations.
- Mazziotta & Pareto (2022) - [Geometric Mean for Composite Indicators](https://www.mdpi.com/2079-3197/10/4/64). *Computation*.
- Neuhierl et al. (2025) - Option characteristics as stock return predictors. *Management Science*.
- Ryabinin (2023) - [The FOMC Announcement Premium Asymmetry](https://consensus.app/papers/details/06ce27757ad35d90ad1bb4fb043cc28a/).
- Shi et al. (2025) - [A Closer Look at Model Collapse](https://arxiv.org/html/2509.16499v1). U. Michigan/Georgia Tech.
- Shu et al. (2024) - [Downside risk reduction using statistical jump models](https://consensus.app/papers/details/af35e1366f905ee684be45e4e031242f/). *Journal of Asset Management*, 10 citations.
- Sun et al. (2025) - FinBERT + multi-dictionary fusion. 88.6% accuracy.
- Tsaknaki et al. (2023) - [Online learning of order flow with Bayesian change-point detection](https://consensus.app/papers/details/16fc1fb31e8f5f9c9f9f5004497dc1f3/). *Quantitative Finance*.
- Tsaknaki et al. (2024) - [Bayesian Autoregressive Online Change-Point Detection](https://consensus.app/papers/details/e7ac9af4e69b5c168377dc6f98ad913a/). arXiv.
- Xiao et al. (2024) - [TradingAgents: Multi-Agents LLM Trading Framework](https://arxiv.org/abs/2412.20138).
- Xie et al. (2022) - [Window-Limited CUSUM](https://consensus.app/papers/details/4a61aac49a2d5d52b12dfd1e8b7b89a3/). *IEEE Trans. Inf. Theory*, 29 citations.
- Zaremba et al. (2019) - [Herding for profits: Market breadth](https://consensus.app/papers/details/5a4d54d35f335861a4bc2480827d4594/). 13 citations.

### Tier 3: Multi-agent and LLM research

- Becker et al. (2025) - [The influence of ensemble size on forecasts](https://consensus.app/papers/details/85460397e8eb5a56a328be4a1077eb8a/).
- Chan et al. (2023) - Multi-agent debate optimal configuration (3-4 debaters).
- DeepSeek-R1 (Shao et al., 2025) - [GRPO for Reasoning](https://arxiv.org/html/2501.12948v1).
- DAPO (ByteDance/Tsinghua, 2025) - [Decoupled Clip and Dynamic Sampling for RLHF](https://arxiv.org/abs/2503.14476).
- Du et al. (2023) - Multi-agent debate (improvement up to 7 agents on math).
- FinTral (2024) - [GPT-4 Level Financial LLMs](https://huggingface.co/papers/2402.10986).
- Google DeepMind (2025) - [Towards a Science of Scaling Agent Systems](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/).
- Graefe & Armstrong (2011) - [Methods to Elicit Forecasts from Groups: Delphi and Prediction Markets Compared](https://ssrn.com/abstract=1153124). *International Journal of Forecasting*.
- Jadhav et al. (2025) - [Large Language Models in equity markets](https://consensus.app/papers/details/434b99d68f495a91946c64b36b4602f9/) (84-study survey).
- Ju et al. (2024) - Accuracy drop scaling 5 to 10 agents.
- Karotkin & Paroush (2003) - [Optimum committee size](https://consensus.app/papers/details/c98af4b408b356b19813ceb589c08e2c/). 51 citations.
- Lopez de Prado (2022) - [Causal Factor Investing](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4205613). Cambridge Elements.
- Lopez de Prado (2025) - [Causality and Factor Investing: A Primer](https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/rf_lopezdeprado_causalityprimer_online.pdf). CFA Institute.
- MarketSenseAI (2024) - [AI-Driven Stock Analysis](https://link.springer.com/article/10.1007/s00521-024-10613-4). *Neural Computing and Applications*.
- Multi-Agent Debate Survey (2025) - [Literature Review of Multi-Agent Debate](https://arxiv.org/html/2506.00066v1).
- Sibert (2006) - [Central Banking by Committee](https://consensus.app/papers/details/726121dd55a950bcbcdaabd7e071c5e4/). 128 citations.
- Siddique et al. (2025) - [Hybrid LLM + traditional ML model](https://consensus.app/papers/details/a0d360b86faf581b8b691a9b144ee8ea/).
- SPELL (2025) - [Self-Play RL for LLMs](https://arxiv.org/abs/2509.23863).
- Xie et al. (2024) - [FinBen: Financial Benchmark](https://arxiv.org/abs/2402.12659). NeurIPS 2024.

### Tier 4: Practitioner and institutional references

- Antonacci (2014) - [Dual Momentum Investing](https://www.quantifiedstrategies.com/dual-momentum-trading-strategy/).
- Bulkowski (1991-2008) - [Pullback and Throwback Empirical Studies](https://thepatternsite.com/pullbacks.html).
- Carver (2015) - *Systematic Trading*. Half-Kelly sizing.
- Cleveland Fed - [Neutral Interest Rates and Monetary Policy Stance](https://www.clevelandfed.org/publications/economic-commentary/2025/ec-202508-neutral-interest-rates-and-monetary-policy-stance).
- COINr Framework - [Composite Indicator Aggregation](https://bluefoxr.github.io/COINrDoc/aggregation.html).
- Evidently AI - [Embedding Drift Detection Methods](https://www.evidentlyai.com/blog/embedding-drift-detection).
- Faber (2010) - [Relative Strength Strategies for Investing](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID1590401_code649342.pdf?abstractid=1585517). SSRN.
- FRED - [Smoothed U.S. Recession Probabilities](https://fred.stlouisfed.org/series/RECPROUSM156N).
- Gresham Investment Management (2025) - [Systematic Strategies Report](https://www.greshamllc.com/media/kycp0t30/systematic-report_0525_v1b.pdf).
- Kelly Criterion (2020) - [Practical Implementation](https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2020.577050/full). *Frontiers*.
- NY Fed - [Measuring the Natural Rate of Interest](https://www.newyorkfed.org/research/policy/rstar).
- PGIM - [Risk Management Framework](https://www.pgim.com/risk-management).
- Renaissance Technologies - [History](https://www.acquired.fm/episodes/renaissance-technologies). Acquired.fm.
- Systemic Failures in Algorithmic Trading - [PMC Article](https://pmc.ncbi.nlm.nih.gov/articles/PMC8978471/).
- Tsicilian (2025) - [Drift Detection in LLMs: Practical Guide](https://tsicilian.wordpress.com/2025/03/14/drift-detection-in-large-language-models-a-practical-guide/).
- Two Sigma - [Inside the World of Quant Shop Two Sigma](https://www.institutionalinvestor.com/article/2bsw4ehe37jv5y886qtxc/corner-office/inside-the-geeky-quirky-and-wildly-successful-world-of-quant-shop-two-sigma). *Institutional Investor*.
- UNDP - [Human Development Index](https://hdr.undp.org/data-center/human-development-index).

---

## Research Metadata

- **Depth:** Exhaustive
- **Agents dispatched:** 5 search clusters
  - Cluster 1: Regime + Risk (Algorithms #1, #2, #9, #13)
  - Cluster 2: Ranking + Classification (Algorithms #3, #5, #10)
  - Cluster 3: ML Training + Quality (Algorithms #6, #7, #8, #12)
  - Cluster 4: NLP + Options (Algorithms #4, #14, #15)
  - Cluster 5: Council + Cross-cutting
- **Duration:** ~15 minutes
- **Total papers cited:** 80+
- **Search engines used:** Consensus, Hugging Face Papers, arXiv, SSRN, Google Scholar, FRED, institutional publications
- **Key files examined:** `src/features/traffic_light.py`, `src/features/regime.py`, `src/features/event_risk_score.py`, `src/features/setup_classifier.py`, `src/features/filing_nlp.py`, `src/ranking/ranker.py`, `src/strategy/canary.py`, `src/evaluation/change_detector.py`, `src/data_enrichment/macro.py`, `src/data_collection/options_metrics.py`, `src/features/engine.py`

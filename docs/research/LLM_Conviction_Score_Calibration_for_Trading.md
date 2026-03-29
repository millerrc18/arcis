# LLM conviction scores are poorly calibrated — here's how to fix them for trading

**Your fine-tuned Qwen3 8B model's conviction scores are almost certainly not predictive at their face value.** Research across every frontier LLM shows systematic overconfidence with Expected Calibration Error (ECE) of 0.12–0.40, and fine-tuned smaller models on domain-specific tasks typically perform worse, not better. The teacher-imitation training approach (learning from Claude's outputs) compounds this: student models inherit the teacher's calibration biases while losing the underlying reasoning that generated them. With only 5 closed trades, calibration measurement is statistically meaningless — but this guide provides a concrete phased roadmap from your current state through 50, 200, and 500 trades, covering what to measure, how to correct, and when to trust the numbers.

The good news: post-hoc calibration methods work well even at modest sample sizes, and there are practical alternatives to relying on verbalized confidence for position sizing. The critical insight is that **calibration and accuracy are largely decoupled** — a model can generate profitable signals while having terribly miscalibrated confidence scores. The solution is to treat conviction scores as ordinal rankings (higher = more confident) rather than calibrated probabilities, and build a separate calibration layer that maps these scores to empirical win rates.

---

## Every LLM is overconfident, and fine-tuning makes it worse

The evidence for universal LLM miscalibration is now overwhelming. KalshiBench (Nel et al., 2025) evaluated five frontier models on 300 prediction market questions from Kalshi, a CFTC-regulated exchange, with outcomes occurring after model training cutoffs. **Every model showed substantial overconfidence**, with ECE ranging from 0.120 (Claude Opus 4.5, the best) to 0.395 (GPT-5.2-XHigh, the worst). The most striking finding: reasoning-enhanced models exhibited *worse* calibration despite comparable accuracy. GPT-5.2-XHigh concentrated **35% of predictions in the 90–100% confidence bin with only 33.7% accuracy** — a catastrophic +62.2 percentage-point calibration gap. Only one model achieved a positive Brier Skill Score, meaning most models performed worse than simply predicting base rates.

Xiong et al. (2024, ICLR) conducted the most systematic study of LLM confidence elicitation across 5 models and 5 datasets. GPT-4's AUROC for failure prediction was a mere **62.7%** — barely above the 50% random threshold — and verbalized confidence values clustered overwhelmingly in the 80–100% range, mimicking human confidence expression patterns. Tian et al. (2023) found that for RLHF-tuned models like ChatGPT and Claude, verbalized confidences were actually *better* calibrated than internal token probabilities, often reducing ECE by a relative 50%. This is counterintuitive but important: the model's stated confidence, while poor, may still be its best available signal.

For fine-tuned smaller models, the picture is nuanced but generally worse. Guo et al. (2017) established that modern neural networks are systematically overconfident, with miscalibration increasing with model depth, width, and batch normalization — all hallmarks of contemporary architectures. Kadavath et al. (2022, Anthropic) found that RLHF policies are particularly miscalibrated, collapsing predictions toward high-confidence outputs. Fine-tuning on domain-specific data can improve discrimination (the model gets better at ranking which predictions are more likely correct) without improving calibration (the probability estimates remain wrong). In financial applications specifically, the FINSABER benchmark (2025) found LLM timing-based investing strategies show poorly calibrated risk models, with supposedly risk-averse strategies experiencing catastrophic drawdowns.

### The teacher-imitation problem is real and compounding

When Halcyon Lab generates training data by having Claude assign conviction scores, the fine-tuned Qwen3 model faces a double calibration problem. Kim et al. (2025, IEEE TNNLS) demonstrated a **strong negative correlation between teacher calibration error and student accuracy** in knowledge distillation. Overconfident teachers degrade distillation quality because the "dark knowledge" in non-target class relationships is obscured by peaked probability distributions, leading to steep gradients and poor student learning.

The mechanism is straightforward: Claude's conviction scores themselves are not well-calibrated for trading outcomes (no LLM is). The student model then learns to *mimic the distribution* of these scores rather than learning a calibrated mapping from market features to win probabilities. If Claude tends to assign conviction 7-8 to "moderately bullish" patterns, the fine-tuned model learns that conviction 7-8 is the appropriate response to such patterns — regardless of whether those patterns actually win 70-80% of the time. Hebbalaguppe et al. (2024, ACCV) confirmed that calibration does transfer from teacher to student in knowledge distillation, but this means poorly calibrated teachers produce poorly calibrated students. Temperature-scaling the teacher's outputs (T=1.5) before distillation significantly improves student calibration.

If **60% of training examples have conviction 7-8** (a plausible scenario if Claude defaults to moderate-high confidence), the consequences are severe. The model learns that 7-8 is the "center of mass" for conviction and will anchor predictions there. Class imbalance research shows models bias predicted probabilities toward majority classes, systematically underestimating minority outcomes. The fine-tuned model will underpredict both very low-confidence (1-3) and very high-confidence (9-10) scenarios while over-representing the 7-8 range, making the entire conviction scale informationally compressed.

---

## Measuring calibration with 50 trades is nearly impossible — but here's what to do anyway

The statistical reality is blunt: **calibration measurement below ~200 samples is unreliable, and below ~1,000 samples is substantially biased.** Roelofs et al. (2022, AISTATS) explicitly state that "training a model with naive estimates of calibration error as an objective using a batch size < O(1000) is a potentially flawed endeavor." The Metrics Reloaded framework (Reinke et al., 2024) is even more direct: "ECE should generally not be considered for small sample sizes." With 50 trades across 10 conviction levels (~5 per bin), standard ECE is statistically meaningless — each bin's empirical win rate has a 95% confidence interval of roughly ±44 percentage points.

The clinical prediction literature provides the most relevant guidance, since medical researchers routinely face the same small-sample calibration challenge. Van Calster et al. (2016) established a calibration hierarchy with four levels and recommended a **minimum of 200 events AND 200 non-events** for flexible calibration curves. Riley et al. (2021) developed formal sample size calculations for external validation and found that even 200 events can produce imprecise calibration estimates — their examples required 531 to 9,835 participants for precise calibration slope estimation. For 50 trades, only the weakest calibration measures (overall win rate matching predictions, calibration slope) are assessable; flexible calibration curves are unreliable.

### What to measure at each sample size

At **N < 50** (current state): compute only the overall Brier score (no binning required) and the raw win rate. Compare the model's average predicted conviction to the overall win rate. If the model averages conviction 7.2 and the win rate is 55%, you already know it's overconfident. Do not attempt ECE, reliability diagrams, or per-bin analysis.

At **N = 50** (Phase 1 gate): use **Bayesian Platt scaling** — fit a logistic regression P(win|score) = sigmoid(A·score + B) with weakly informative priors on A and B. This requires only 2 parameters and produces posterior distributions that honestly represent your uncertainty. Report the Brier score, calibration intercept (calibration-in-the-large), and calibration slope with credible intervals. Use **5 merged bins** (scores 1-2, 3-4, 5-6, 7-8, 9-10) rather than 10, giving ~10 trades per bin. Even these estimates will have wide confidence intervals, which is itself informative — it tells you how much you *don't know* about calibration.

At **N = 200**: ECE_sweep (Roelofs et al., 2022) with equal-mass binning becomes reasonable. Switch to beta calibration (Kull et al., 2017) with 3 parameters for better flexibility. Venn-Abers calibration becomes practical, providing probability *intervals* rather than point estimates — especially valuable for position sizing. Bootstrap confidence intervals with BCa correction become somewhat reliable. You can now plot reliability diagrams with shaded confidence bands, though they'll remain wide.

At **N = 500**: standard calibration analysis is viable. Per-score-level empirical win rates have standard errors of ~7% (50 trades per bin). Isotonic regression becomes an option. Full Brier score decomposition into reliability, resolution, and uncertainty is meaningful. **This is the first sample size where you should make significant position-sizing decisions based on calibration data.**

### Brier score decomposition matters more than ECE

The Brier score decomposes (Murphy, 1973) into **BS = Reliability − Resolution + Uncertainty**. For position sizing, resolution (discrimination) matters most initially — can the model distinguish between higher and lower probability trades, even if the absolute probabilities are wrong? A model with good resolution but poor reliability can be *recalibrated*; a model with poor resolution cannot. The Brier score is a strictly proper scoring rule (unlike ECE, which has pathological minima), requires no binning for the overall score, and is computable at any sample size. At small N, report the Brier score and test whether it differs significantly from the no-skill baseline (predicting the base rate for every trade).

For bootstrap confidence intervals, use BCa (bias-corrected and accelerated) with ≥1,000 resamples. Be warned that at N < 50, bootstrap CIs are **too narrow** — a nominal 95% BCa CI at N = 5 provides only ~81–83% actual coverage (empirically demonstrated by simulation studies). At N = 20, coverage remains below nominal. The parametric Bayesian approach (Beta-Binomial posteriors per bin) is more honest about uncertainty at small N.

---

## Post-hoc calibration: Bayesian Platt scaling is your best bet under 200 trades

The choice of calibration method depends critically on sample size, and the evidence is clear: **parametric methods with few parameters dominate at small N, while non-parametric methods need ≥1,000 samples.** Zhang et al. (2020, NeurIPS) confirmed empirically that "temperature scaling is the best calibration method in the data-limited regime, while isotonic regression is superior in data-rich regime."

For discrete integer scores (1-10) without access to logits, temperature scaling collapses to Platt scaling — both fit a sigmoid mapping from scores to probabilities. **Bayesian Platt scaling** is the recommended approach for N < 200: fit P(win|score) = sigmoid(A·score + B) using Bayesian logistic regression with weakly informative priors (Normal(0, 2) on both A and B). This provides posterior distributions over the calibration parameters, yielding credible intervals on every probability estimate. The posterior naturally regularizes against overfitting, and yesterday's posterior becomes today's prior as new trades close — enabling genuine incremental learning.

**Beta calibration** (Kull et al., 2017, AISTATS) is the upgrade path at N = 100–300. It uses 3 parameters and the calibration map g(s) = 1/(1 + exp(c)·s^a·(1-s)^(-b)), where s is the score normalized to (0,1). Its critical advantage over Platt scaling: the beta calibration family **includes the identity function**, so it cannot make an already-calibrated model worse. Platt scaling's sigmoid family excludes the identity, meaning it can uncalibrate a calibrated model. Kull et al. found beta calibration was never significantly worse than any other method and was significantly better for multiple classifier types.

**Venn-Abers calibration** (Vovk & Petej, 2014) deserves special attention for trading applications. It applies isotonic regression twice — once assuming the test case is class 0, once class 1 — producing a probability *interval* [p₀, p₁] with **finite-sample distribution-free calibration guarantees** requiring only the i.i.d. assumption. The interval width directly measures epistemic uncertainty: wide intervals with little data, narrow intervals with lots. For position sizing, this is gold — you can size positions based on the lower bound of the interval rather than a point estimate, providing built-in conservatism. The Python package `venn-abers` provides a ready implementation.

**Isotonic regression** should not be used below N = 500. Niculescu-Mizil & Caruana (2005) and multiple subsequent studies confirm it overfits severely with fewer than 1,000 calibration samples. With 10 discrete input scores, the overfitting risk is somewhat reduced (at most 10 output values), but with only 5 trades per score level, the estimates are pure noise.

**Histogram binning** (empirical win rate per bin) is conceptually the simplest but requires substantial data. Gupta & Ramdas (2021) provide theoretical guidance: at N = 1,000, choosing B = 5 bins gives calibration error guarantee ε ≤ 0.12. For N = 50, even 2 bins give enormous error bounds. The practical takeaway: histogram binning is a useful sanity check at N ≥ 200 (with merged bins), but should never be the primary calibration method.

---

## Training-time interventions that actually improve calibration

If Halcyon Lab retrains the model (or trains a successor), several techniques can produce substantially better-calibrated conviction scores from the start.

**Focal loss** (Mukhoti et al., 2020, NeurIPS) is the strongest evidence-based intervention. With focusing parameter γ = 3, focal-loss-trained models emerge with optimal temperatures near 1.0 (between 0.9 and 1.1), meaning they are already well-calibrated without post-hoc correction. The variant FLSD-53 (γ = 5 for p ∈ [0, 0.2), γ = 3 otherwise) outperformed cross-entropy, MMCE, Brier loss, and label smoothing across multiple architectures. The mechanism: focal loss simultaneously minimizes KL divergence and increases output entropy, naturally preventing overconfidence.

**Label smoothing** (Müller et al., 2019, NeurIPS) reduces overconfidence by replacing hard targets with soft targets y_smooth = (1-ε)·y_hard + ε/K, typically with ε = 0.05–0.1. For conviction scores, this translates to softening the target distribution rather than training on hard integer labels. A conviction-8 training example might use a target distribution centered on 8 but with some mass on 7 and 9. Calibration improves, though Bohdal et al. (2021) note that label-smoothed models may be "less calibratable" — harder to further improve via post-hoc methods.

**MMCE (Maximum Mean Calibration Error) regularization** (Kumar et al., 2018, ICML) adds a differentiable calibration penalty directly to the training loss: L = L_CE + λ·MMCE. This reduced ECE from ~16–18% to ~6–7% on benchmarks, providing 70% of the total ECE reduction (with temperature scaling contributing only the remaining 30%). The regularization strength λ = 2–8 is recommended. This can be incorporated into SFT training.

**Ordinal regression framing** is directly relevant for 1-10 conviction scores. The ORCU loss (2024) specifically targets ordinal regression calibration, ensuring both calibrated probabilities and proper ordinal structure (unimodal predicted distributions). Standard cross-entropy treats conviction 2 and conviction 9 as equally wrong when the true answer is 5; ordinal regression naturally penalizes distant predictions more. CORAL (Cao et al., 2020) provides a practical cumulative binary decomposition framework.

**Training data distribution critically affects calibration.** If 60% of examples have conviction 7-8, the model will anchor to this range. The solution is either uniform distribution across conviction levels (ensuring equal representation of 1-10) or intentional oversampling of extreme convictions (1-3 and 9-10) to counteract the model's tendency to cluster near the mode. Multi-teacher distillation — using Claude, GPT-4, and other models to generate training data — improves student calibration by providing more diverse probability distributions, but only if each teacher is calibrated (e.g., via temperature scaling) before generating training labels.

---

## When verbalized confidence fails, use behavioral alternatives

The most robust position sizing approach may be to **decouple signal generation from confidence estimation entirely.** The model generates trade signals; a separate system determines position size.

### Ensemble disagreement outperforms stated confidence

Running the same query through multiple model instances and measuring disagreement provides a **behavioral** confidence signal that is typically better calibrated than any individual model's stated confidence. Lakshminarayanan et al. (2017, NeurIPS) established that deep ensembles produce "well-calibrated uncertainty estimates as good or better than approximate Bayesian NNs." The DiscoUQ framework (2025) extends this to multi-agent LLM systems, achieving **AUROC 0.802 with ECE 0.036** by analyzing structured disagreement features — evidence overlap, argument strength, divergence depth, and cluster distances.

For Halcyon Lab's Ollama/GGUF setup, the practical equivalent is **Monte Carlo Temperature sampling**: run the same trade analysis N times (N = 5–10) with varied temperature settings (T ∈ {0.3, 0.5, 0.7, 0.9, 1.2}) and measure output consistency. If all runs agree on a long trade with similar conviction, behavioral confidence is high. If runs disagree on direction or show high conviction variance, behavioral confidence is low. Cecere et al. (2025, ACL) formalized this as Monte Carlo Temperature (MCT) and showed it achieves "statistical parity with oracle temperatures" for uncertainty estimation. This bypasses the verbalized confidence problem entirely.

### Kelly criterion is extremely sensitive to calibration error

The Kelly criterion f* = (pb − q)/b is the theoretically optimal sizing formula, but it is **catastrophically sensitive to probability estimation errors.** Research on prediction markets found that model overconfidence with ECE ≈ 0.11 caused Kelly-based strategies to *increase bankruptcy risk rather than wealth*. Triple Kelly sizing leads to "sure ruin" in simulations. The less confident you are in your probability estimates, the more dangerous full Kelly becomes.

**Fractional Kelly (¼ to ½ Kelly)** is mandatory when calibration is uncertain. Most professional traders use ½ Kelly because real-world probabilities are estimated, not known. Full Kelly maximizes median wealth growth, but most people's risk preference is closer to maximizing 10th-percentile outcomes — making money "in 9 out of 10 hypothetical worlds." A principled approach: use the *lower bound* of the Venn-Abers calibration interval as the probability estimate in the Kelly formula, automatically reducing position sizes when calibration uncertainty is high.

### Build a separate position sizing model

The strongest architecture separates signal from sizing. The LLM generates trade signals with conviction scores; a **separate logistic regression or gradient boosting model** maps trade features to calibrated win probabilities for position sizing. Inputs to this model include the LLM conviction score (as one feature among many), technical indicators (ATR, volume, regime), council agreement level, and any other available features. This model is trained on closed trade outcomes and can be recalibrated independently of the LLM. The combination of LLM conviction × regime indicator × historical calibration × council agreement, weighted via Bayesian model averaging, produces more conservative and better-calibrated confidence estimates than any single signal.

---

## Monitoring calibration drift at 35 trades per month

Calibration degrades after deployment, especially in financial markets where regimes shift. IBM and Azure ML documentation confirm that model accuracy can degrade within **days** of deployment because production data diverges from training data. For a trading system with 35 trades/month, significant calibration drift may become detectable after 2–6 months depending on market conditions.

**EWMA (Exponentially Weighted Moving Average) on calibration residuals** is the recommended primary monitor. The calibration residual for each trade is e_t = predicted_probability − actual_outcome. EWMA with λ = 0.1 smooths noise while detecting moderate calibration shifts, with control limits ±L·σ·√(λ/(2-λ)·[1-(1-λ)^{2t}]). Woodall et al. (2025) specifically propose CUSUM with dynamic probability control limits for monitoring probability forecast calibration, operating on predictions and outcomes only — no model internals required. CUSUM with reference value K = 0.05 complements EWMA for detecting smaller shifts. With 35 trades/month, expect alarm within 2–4 months for a moderate calibration shift.

**Bayesian Online Change Point Detection (BOCPD)** (Adams & MacKay, 2007) is particularly well-suited for small samples because it maintains a run-length distribution with built-in uncertainty quantification. The `bayesian_changepoint_detection` Python library provides an implementation, and the `ruptures` library handles offline change-point analysis for quarterly reviews.

**Adaptive Conformal Inference (ACI)** (Gibbs & Candès, 2021) provides distribution-free coverage guarantees even under distribution shift by adaptively updating the significance level based on recent miscoverage. Treat each trade as a sequential prediction, compute nonconformity scores |predicted_prob − actual_outcome|, and monitor whether conformal p-values consistently drop below the target level. A combined approach using EWMA for fast detection, BOCPD for Bayesian change-point analysis, and conformal monitoring for coverage guarantees provides robust multi-signal drift detection.

### The incremental calibration lookup table

The most practical ongoing calibration tool is a **Bayesian Beta-Binomial lookup table** that updates as each trade closes. For each conviction level (or merged bin), maintain a Beta(α, β) posterior for the true win probability, initialized with Beta(1, 1) (uniform prior) or informative priors from any prior data. When a trade at conviction level k wins, update α_k += 1; when it loses, update β_k += 1. The posterior mean α/(α+β) is the calibrated probability estimate, and the 95% credible interval from the Beta distribution honestly represents uncertainty. With 35 trades/month across 10 levels, expect ~3.5 trades per bin per month — credible intervals will remain wide for months, which is appropriate. An exponential decay variant (multiply old α, β by 0.98 per month) gives more weight to recent performance, adapting to regime changes.

An Elo-style rating system provides a complementary at-a-glance calibration health metric. Treat each trade as a "match" where the model's prediction competes against the outcome, updating the rating based on calibration accuracy (1 − |predicted − actual|). A declining Elo rating signals deteriorating calibration. The Glicko extension (Glickman, 1999) adds a rating deviation parameter that captures uncertainty, naturally handling the 35 trades/month constraint by allowing larger rating changes when data is sparse.

---

## A phased implementation roadmap

**Phase 0 (Now, N ≈ 5):** Do not trust conviction scores for position sizing. Use fixed position sizes or volatility-based sizing (ATR method). Track all conviction scores and outcomes in a database. Begin building the Bayesian calibration table with uniform priors. Implement Monte Carlo Temperature sampling to establish behavioral confidence baselines.

**Phase 1 (N = 50, the gate):** Fit Bayesian Platt scaling. Compute the Brier score and compare to the no-skill baseline. Plot a reliability diagram with 5 merged bins and BCa bootstrap confidence bands. Deploy EWMA monitoring (λ = 0.1). The key question at this gate: does the calibration slope differ significantly from zero? If A in sigmoid(A·score + B) is positive and the credible interval excludes zero, conviction scores have *some* discriminative value even if the absolute probabilities are wrong.

**Phase 2 (N = 200):** Switch to beta calibration or Venn-Abers. Compute ECE_sweep with equal-mass binning. Decompose the Brier score into reliability, resolution, and uncertainty. Begin using calibrated probabilities for fractional Kelly sizing (¼ Kelly with Venn-Abers lower bound). Run quarterly offline change-point detection on accumulated residuals.

**Phase 3 (N = 500):** Full calibration analysis is viable. Per-score empirical win rates have ~7% standard errors. Compare multiple calibration methods (Platt, beta, isotonic, Venn-Abers) and select the best performer. Implement the separate position sizing model with multiple confidence signals. Graduate to ½ Kelly if calibration is confirmed adequate (ECE_sweep < 0.10 with bootstrap CI not overlapping 0.20).

**Ongoing:** Monitor calibration drift via EWMA + conformal coverage checks. Recalibrate when convergent evidence from multiple monitoring channels triggers alarm. When retraining the model, incorporate focal loss (γ = 3), uniform conviction distribution in training data, and multi-teacher distillation with temperature-scaled teachers.

## Conclusion

The core answer to "are the conviction scores predictive?" is: they are almost certainly **rank-ordered** (higher conviction correlates with higher win rates) but **not calibrated** (a conviction of 8 does not mean 80% win rate). This distinction is crucial. Rank ordering is sufficient for generating trading signals; calibration is required for position sizing. The path forward is to treat conviction scores as ordinal features, build a calibration layer that maps them to empirical win probabilities, and size positions based on the *calibrated* estimates — with appropriate uncertainty discounting via fractional Kelly and Venn-Abers intervals. At 5 trades, you know almost nothing about calibration. At 50, you can detect whether conviction scores have any discriminative power at all. At 200, you can build a usable calibration map. At 500, you can make confident position-sizing decisions. The incremental Bayesian approach — updating beliefs as each trade closes — is the right framework for this inherently sequential, data-scarce problem.
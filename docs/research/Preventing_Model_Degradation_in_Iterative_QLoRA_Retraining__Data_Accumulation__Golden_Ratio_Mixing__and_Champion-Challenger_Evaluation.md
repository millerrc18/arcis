# Preventing model degradation in iterative QLoRA retraining

**The single most important finding across the research is deceptively simple: never replace your real data, always accumulate it, and always retrain from a clean base.** Gerstgrasser et al. (2024) proved mathematically that model collapse is inevitable when synthetic data replaces real data across generations—but when real data accumulates alongside synthetic data, test error has a finite upper bound independent of iterations. For a system like Halcyon Lab retraining Qwen3 8B biweekly, this means the feedback loop where model-generated commentary becomes future training data is manageable if the original human-curated examples remain permanently in the training set, the overall ratio of real-to-synthetic data stays above **~62%** (per He et al. 2025's golden ratio result), and each QLoRA cycle starts from a clean base model checkpoint. The research across model collapse, continual learning, LoRA mechanics, and financial ML all converges on a coherent strategy that is fully implementable on consumer hardware.

---

## Model collapse is tail death, not sudden failure

Model collapse, as defined by Shumailov et al. in "The Curse of Recursion" (2023, later published in *Nature* 2024), occurs when generative models trained on their own outputs progressively lose information about the tails of the original data distribution. The mechanism is mathematically inevitable: each generation introduces both sampling error (finite data approximation) and functional approximation error (model class limitations), and these errors compound multiplicatively across iterations.

The collapse proceeds in two phases. **Early model collapse** silently erodes rare patterns and minority data—overall metrics may appear stable or even improve while the model loses capability on edge cases. Late model collapse produces obviously degenerate outputs: in Shumailov's experiments, a prompt about medieval architecture devolved into lists of colored jackrabbits after several generations. For fine-tuned OPT-125M, perplexity jumped **20-28 points** when training exclusively on model-generated text, though retaining just 10% of original real data reduced degradation to "minor."

Subsequent research has sharpened the picture considerably. Dohmatob et al. (2025, ICLR Spotlight) demonstrated "strong model collapse"—even **1 in 1,000 synthetic data points** can cause collapse asymptotically, and larger models can actually amplify the effect. Alemohammad et al. (2023) coined "Model Autophagy Disorder" (MAD) and showed collapse occurs in as few as **3-5 generations** in image models. Critically, they found that cherry-picking high-quality synthetic outputs preserves quality temporarily but causes an even steeper decline in diversity—precisely the wrong tradeoff for a system generating varied trade commentary.

The warning signs to monitor across retraining cycles form a hierarchy of sensitivity. **Distinct-n ratios** (unique n-grams over total n-grams) decline first, followed by shrinking active vocabulary size, then rising self-BLEU scores (indicating outputs are becoming more similar to each other). Perplexity on a held-out "canary set" of original human-written data should be tracked as a time series—a **>5% increase between consecutive cycles** warrants investigation. Edge-case test accuracy (performance on rare patterns) is the earliest indicator, since tails disappear first.

For LoRA/QLoRA specifically, the news is mixed. Biderman et al. (2024, TMLR) found in their landmark study "LoRA Learns Less and Forgets Less" that LoRA provides a natural regularization effect—it preserves base model capabilities better than full fine-tuning, but at the cost of learning capacity. However, Kalajdzievski (2024) established a **strong inverse linear relationship** between fine-tuning performance and forgetting in LoRA, following a shifted power law in both parameter count and update steps. LoRA does not eliminate collapse risk; it merely constrains the subspace in which degradation occurs.

---

## Data mixing: the golden ratio and experience replay

The question of how to mix old and new training examples has a surprisingly precise answer from recent theory. He et al. (2025) proved that when iteratively training on combined real and synthetic data, the optimal weight on real data converges to the reciprocal of the golden ratio: **w* ≈ 0.618**. This means approximately 62% of effective training weight should fall on human-authored real data and 38% on model-generated or synthetic data. Garg et al. (2025) independently confirmed this result holds under overparameterization with general covariance structures. Naive unweighted mixing is always suboptimal and can be "arbitrarily inefficient" when synthetic data dominates.

For a dataset growing from 700 to 5,000 examples, the practical implementation is straightforward: **always train on all accumulated data** in every cycle. At this scale, a full QLoRA run on 5,000 examples takes roughly 15-30 minutes on an RTX 3060—there is no computational reason to subsample. Apply recency weighting through oversampling, where each example's sampling probability is proportional to `exp(-λ × age_in_cycles)`. The decay parameter λ should increase as the dataset grows:

| Dataset size | Decay λ | Half-life | Effect |
|---|---|---|---|
| 700 examples | 0.03–0.05 | ~14–23 cycles | Gentle; preserves all data nearly equally |
| 1,000–2,000 | 0.05–0.08 | ~9–14 cycles | Moderate; 4-month-old data retains ~65% weight |
| 3,500–5,000 | 0.08–0.12 | ~6–9 cycles | Stronger; older data fades but remains present |

The concept of experience replay from reinforcement learning transfers directly. Wang et al. (2025) showed that simply adding experience replay with transformers **eliminates loss of plasticity** in continual learning without any architectural modifications. MSSR (2025), tested on Qwen2.5-7B and LLaMA-3.1-8B, models memory retention as time-dependent decay inspired by the Ebbinghaus forgetting curve and schedules replay with progressively expanding intervals, delivering **1-3 point accuracy improvements** over fixed replay with only 3-5% wall-clock overhead. The MIT Bailey thesis (2024) tested concrete replay ratios: a **0.4 replay ratio** (40% old data) yielded only 8.2% performance drop versus 16.5% at 0.1—higher replay consistently reduces forgetting.

A key finding from Krasheninnikov et al. (2025, "Fresh in Memory") is that LLM activations **linearly encode when information was learned during training**. Linear probes achieve ~90% accuracy distinguishing early versus late training data. Re-exposing old data moves its activation centroid to the "most recent" position, confirming that replay genuinely refreshes the model's treatment of old knowledge rather than merely preserving it passively.

---

## Anchor examples ground the model against drift

The concept of maintaining a permanent set of high-quality "anchor" examples across all retraining cycles is well-supported by converging evidence, even though no single canonical framework prescribes exact ratios. (Note: the "R-Few framework" referenced in some discussions does not appear in published literature as of early 2026; the concept it describes is real, but the specific name and 75/25 ratio are not from a published paper. The actual research points to the **~62/38 golden ratio** from He et al. 2025 as the optimal split.)

The theoretical foundation comes from Gerstgrasser et al. (2024): real data serves as an information-theoretic anchor that preserves knowledge of the true distribution. Without it, each generation's approximation errors compound without bound. With it, test error converges to a finite ceiling. LIMA (Zhou et al., NeurIPS 2023) demonstrated that only **1,000 carefully curated examples** enabled a 65B LLaMA model to outperform models trained on orders of magnitude more data—diversity of the curated set mattered more than volume.

For selecting which examples become anchors, the research supports a hybrid approach combining quality, diversity, and difficulty:

- **Quality-based selection** (top ~40% of anchor slots): Select examples with the highest human-verified quality scores. AlpaGasus showed GPT-4 scoring can identify top examples effectively.
- **Diversity-based selection** (~40% of slots): Use embedding-based clustering (k-means on sentence embeddings from the base model) to identify natural groupings, then ensure anchors cover all clusters. At high selection ratios, submodular diversity maximization outperforms other methods.
- **Difficulty-based selection** (~20% of slots): Include boundary cases that the model finds challenging (high loss but correct). These examples provide the strongest learning signal and protect against edge-case collapse.

The practical sizing follows from the literature: start with **150-175 anchors** at 700 total examples (~25%), growing to **350-750 anchors** at 5,000 examples (7-15%). Anchors should never shrink—only grow. The SuRe framework (2025) found that **surprise-based selection** (retaining examples with highest negative log-likelihood) outperforms random selection for LLM replay buffers, suggesting that anchors should be periodically re-evaluated: swap out low-surprise anchors for new high-surprise, human-verified examples. Every 3-5 retraining cycles, a domain expert should review the anchor set for continued relevance.

Operationally, oversample anchors so they receive approximately 62% of effective training weight (per the golden ratio). For a 3,000-example dataset with 400 anchors, each anchor should be seen roughly **4-5× more often** than each non-anchor example during training.

---

## Fresh LoRA from base wins over adapter stacking

The question of whether each QLoRA cycle should start from the original Qwen3 8B or from the previous fine-tuned checkpoint has a clear answer from the LoRA mechanics research: **a hybrid merge-and-reset strategy** outperforms both extremes.

Shuttleworth et al. (2024, "LoRA vs Full Fine-tuning: An Illusion of Equivalence") discovered that LoRA creates **"intruder dimensions"**—new, high-ranking singular vectors in weight matrices that do not appear in full fine-tuning. These intruder dimensions are where LoRA's forgetting is localized, and the paper explicitly warns: "we should expect accumulating intruder dimensions to be harmful... amplified during continual learning because of sequentially fine-tuning." Continuing to train the same LoRA adapter across cycles compounds these artifacts.

Starting completely fresh from the base model each cycle avoids intruder dimension accumulation but discards all accumulated domain adaptation—every cycle must re-learn from scratch. The practical middle ground is **merge-then-retrain**:

1. After each training cycle, merge the LoRA adapter into the base model weights using Unsloth's `save_pretrained_merged()` at 16-bit precision
2. On the next cycle, load this merged model as the new "base" and train a fresh LoRA adapter on top
3. Every **4-6 cycles (~2-3 months)**, perform a full reset: start from the original Qwen3 8B with a LoRA trained on the complete cumulative dataset

The periodic full reset is essential because QLoRA's dequantization from NF4 to fp16 introduces small precision errors at each merge step, and these accumulate. The ILT framework (Iterative LoRA Training, 2025) validates this merge-then-retrain paradigm, finding that direct continued training leads to overfitting while the merge-and-reset approach with data expansion works better.

For hyperparameters across cycles: use **rank r=16** (good balance of capacity versus forgetting for iterative use), **α = 2r = 32**, and apply LoRA to all linear layers (q, k, v, o, gate, up, down projections), not just attention. O-LoRA (Wang et al., EMNLP 2023) and InfLoRA (Liang & Li, CVPR 2024) offer more sophisticated approaches using orthogonal subspaces and interference-free adaptation, but these add significant engineering complexity and are designed for distinct sequential tasks rather than iterative refinement of the same domain. For biweekly retraining of a single-domain system on consumer hardware, the merge-and-reset approach is both simpler and better matched to the use case.

---

## A champion-challenger framework for measuring improvement

Measuring whether a retraining cycle actually improved the model requires going well beyond validation loss. The Anthropic statistical evaluation paper (November 2024) established that perplexity is a "misleading indicator" for predicting fine-tuned model quality, and models with similar perplexity often show dramatically different task capabilities. A practical three-tier evaluation framework, runnable within the constraints of biweekly retraining, combines automated checks, LLM-as-judge scoring, and periodic human calibration.

**Tier 1 (automated, every cycle, ~5 minutes)** validates schema compliance on 100% of outputs against the JSON schema (target: ≥98%), tracks holdout perplexity on a fixed canary set of human-written examples, and computes semantic similarity (BERTScore) between new model outputs and golden references on **50-100 fixed evaluation prompts**. Any metric crossing its control limit triggers investigation before deployment.

**Tier 2 (LLM-as-judge, every cycle, ~$5-10)** runs the same 50-100 evaluation prompts through both the current champion model and the new challenger. A judge model (GPT-4 or Claude) evaluates outputs on **binary criteria**: Does the thesis state a clear directional view? Are specific risk factors identified? Is the thesis internally consistent? Is at least one catalyst identified? Binary pass/fail questions are more reliable than Likert scales because they reduce the known biases of LLM judges—position bias, length bias, and verbosity preference. AlpacaEval LC achieved **0.98 Spearman correlation** with human preferences using length-controlled LLM judging. Run pairwise comparisons with randomized presentation order and apply a paired sign test to determine whether the challenger wins at p<0.05.

**Minimum sample sizes** for statistical significance: with **100 paired evaluation prompts** and paired testing (which eliminates variance from prompt difficulty), you can detect a **~10% improvement** in pass rates at 80% power. With 50 prompts, you can detect ~15% improvement. The key insight from Anthropic's work is that paired analysis is a "free variance reduction technique" since correlations between model scores on the same questions typically run **0.3-0.7**, dramatically reducing required sample sizes compared to independent testing.

The promotion decision follows a gated process: Gate 1 (schema compliance ≥ threshold) → Gate 2 (no critical metric below control limits) → Gate 3 (pairwise win rate versus champion exceeds 50% + confidence margin on binomial test) → Gate 4 (no per-category regressions despite overall improvement). Only models passing all gates replace the current champion. Track all metrics as time series across cycles using Weights & Biases or MLflow, with Statistical Process Control charts (mean ± 2σ) for drift detection.

---

## Regime changes demand tagged data and adaptive weighting

Market regime changes—bull to bear, low volatility to high—represent concept drift in the formal sense: P(Y|X) changes, meaning the relationship between pullback patterns and successful trade outcomes fundamentally shifts. The systematic review by Suárez-Cetrulo et al. (2024) surveyed 140 studies on financial ML under structural change and found that the field clusters around two core approaches: statistical change-point detection and regime-conditional model management.

**Hidden Markov Models are the gold standard** for financial regime detection. Fitted to rolling features (returns, realized volatility, credit spreads, VIX term structure), a 2-3 state Gaussian HMM identifies low-volatility bull, high-volatility bear, and transitional regimes. LSEG tested multiple methods on S&P 500 futures (2006-2023) and found HMMs outperformed K-means, GMMs, and agglomerative clustering for regime identification. For Halcyon Lab, a lightweight HMM running on daily S&P 500 data can provide regime probability estimates that inform data weighting.

The critical question—should old-regime data be kept, removed, or downweighted—has a nuanced answer that depends on drift type. For financial markets where **regimes recur** (bull and bear cycles repeat), the literature strongly favors keeping historical regime-tagged data in an archive and selectively recalling it when similar conditions reappear. The Continual Learning Augmentation (CLA) framework (Philps, 2018), designed specifically for noisy financial time series, accumulates models of past market states and uses dynamic time warping to match current conditions to historical regimes, recalling relevant stored knowledge.

Every training example should carry regime metadata: market regime label, volatility bucket, source date, and regime confidence score from the HMM. This enables a **tiered data architecture**:

- **Core tier (always included, no expiration)**: 50-100 gold-standard template examples defining output format and style, plus canonical examples of each setup type. These are the anchors.
- **Regime archive tier (recalled when similar regimes recur)**: Tagged, high-quality examples from each previously observed regime, stored with full metadata. Retrieved via HMM state matching.
- **Recent tier (sliding window, 3-6 months)**: Most recent trade theses with outcome feedback, receiving highest sampling weight.
- **Deprecated tier (removed from active training)**: Data beyond the sliding window that doesn't match any regime archetype. Stored but not trained on.

During a regime transition, the training mix should shift to approximately **50% recent data from the emerging regime, 30% archived data from the last similar historical regime, and 20% rehearsal data from the previous regime** (to prevent catastrophic forgetting of how to generate valid commentary for conditions that will eventually return). ShiftEx (2025) provides a model for this: dynamically create new expert capacity when previously unseen regimes are encountered, while preserving existing experts for known regimes. In practice, this could mean training a regime-specific LoRA adapter that is loaded based on the current HMM state.

---

## Conclusion: the complete retraining protocol

The research converges on a concrete operational protocol for monotonically improving model quality across months of biweekly retraining. First, **data accumulation is non-negotiable**—every human-authored example must persist across all cycles, maintaining a permanent anchor set that grows from ~25% of a small dataset to ~10-15% of a large one. Second, **the golden ratio** (~62% real/38% synthetic weighting) provides a theoretically grounded target for training mix, implemented via oversampling with exponential time decay. Third, the **merge-and-reset LoRA strategy**—merge adapter into base after each cycle, train fresh LoRA on the merged model, with full resets to original base every 2-3 months—avoids both intruder dimension accumulation and the computational waste of learning from scratch each time.

The most actionable insight across all six research areas is that monotonic improvement requires treating evaluation as seriously as training. A system that deploys a new model only when it passes all gates of a champion-challenger framework—schema compliance, canary-set perplexity stability, LLM-judge pairwise win rate with statistical significance—will never deploy a regression. Combined with regime-aware data management using HMM-based detection and tiered archival, this creates a system where each retraining cycle either improves the model or preserves the current best, achieving the goal of monotonic quality improvement even through market regime transitions.
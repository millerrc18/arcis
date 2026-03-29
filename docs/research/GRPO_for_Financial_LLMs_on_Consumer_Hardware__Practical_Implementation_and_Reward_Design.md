# GRPO for financial LLMs on consumer hardware

**GRPO (Group Relative Policy Optimization) is the most practical RL algorithm for fine-tuning financial LLMs on consumer GPUs**, eliminating the critic model that makes PPO infeasible at small scale. Fin-o1 proved that just **1,500 GRPO training examples** can push an 8B model past GPT-o1 and DeepSeek-R1 on financial reasoning benchmarks. For Halcyon Lab's three-stage pipeline, the critical finding is that GRPO's batch-oriented architecture naturally handles delayed trade rewards—generate theses now, score them when trades close days later, train in batch. However, running Qwen3 8B GRPO on an RTX 3060 12GB is borderline; 12GB will require aggressive memory optimization or dropping to a 4B model, while an RTX 3090 24GB is the comfortable consumer target.

---

## How GRPO works and why it fits consumer hardware

GRPO was introduced in the DeepSeekMath paper (Shao et al., February 2024) and became the backbone of DeepSeek-R1's reasoning capability. The core insight is deceptively simple: instead of training a separate value network to estimate advantages (as PPO does), **sample multiple completions for the same prompt and use their reward statistics as the baseline**.

**The algorithm, step by step:** For each prompt *q*, sample a group of *G* completions from the current policy. Score each completion with a reward function to get rewards *r₁, r₂, ..., r_G*. Compute each completion's advantage via z-score normalization: **Â_i = (r_i − μ) / σ**, where μ and σ are the group mean and standard deviation. Every token in completion *i* receives the same advantage—this is sequence-level credit assignment. Then optimize a clipped surrogate objective with KL penalty:

```
J_GRPO(θ) = (1/G) Σᵢ (1/|oᵢ|) Σₜ min[rₜ(θ)·Âᵢ, clip(rₜ(θ), 1-ε, 1+ε)·Âᵢ] − β·D_KL[πθ ∥ πref]
```

where rₜ(θ) is the per-token importance ratio πθ/π_old. DeepSeek-R1 used **G=16**, learning rate **3e-6**, KL coefficient **β=0.001**, and an unusually large clip ratio **ε=10**.

**Why no critic model matters for VRAM:** PPO requires four large models simultaneously—policy, reference, reward model, and critic—each roughly the size of the base LLM. GRPO needs only two: the trainable policy and a frozen reference model (and can use rule-based rewards instead of a neural reward model, eliminating the third). This is a ~50% VRAM reduction versus PPO. For Qwen3 8B with QLoRA, the practical breakdown is: **~4-5GB** for the 4-bit base model, **~0.2-0.6GB** for LoRA adapters and optimizer states, **~0.5-1GB** for generation KV cache, and **~1-2GB** for activations with gradient checkpointing. With Unsloth's weight-sharing between policy and reference models, total VRAM lands around **10-14GB** for short contexts—tight but theoretically possible on 12GB. Vanilla TRL without Unsloth requires ~34GB for 8B LoRA GRPO, making Unsloth essentially mandatory.

The key tradeoff versus DPO: DPO works from static preference pairs and is simpler, but Fin-o1 showed it **fails to deliver stable improvements** in financial reasoning. GRPO generates fresh completions each iteration (on-policy), extracts richer signal from G completions per prompt, and handles verifiable rewards naturally. PPO showed gains only on simpler financial tasks but degraded on complex long-context reasoning.

---

## Fin-o1 proved GRPO works for financial reasoning with minimal data

Fin-o1 (arxiv:2502.08127, accepted EMNLP 2025) is the most directly relevant precedent for Halcyon Lab. The v3 paper (June 2025) fine-tuned **Qwen3-8B** and **Qwen3-14B** using a two-stage pipeline: SFT on 7,686 examples followed by GRPO on just 1,500 examples from the FinCoT dataset.

**The results are striking.** On the FinReason benchmark, Fin-o1-14B achieved **61.07% average accuracy**, surpassing DeepSeek-R1 (60.87%, a ~671B parameter model) and GPT-o1 (54.05%). Fin-o1-8B reached 59.95%—nearly matching a model 84× its size. The paper systematically compared PPO, DPO, and GRPO, finding that **only GRPO yielded consistent, reliable gains** across all financial reasoning benchmarks. PPO improved simpler tasks but degraded long-context reasoning; DPO was inconsistent, improving hard tasks while hurting easy ones.

The FinCoT dataset deserves attention for its construction methodology. Each of the 9,186 chain-of-thought examples was generated through a three-stage pipeline: domain-aware supervision using GPT-4o with gold guidelines from source datasets, iterative LLM refinement with backtracking and verification until answers were logically consistent, and difficulty-aware filtering where examples that Llama-3.1-8B could already solve were excluded as insufficiently challenging. This filtering step is critical—it ensures the GRPO training data targets genuinely hard financial reasoning, not problems the model already handles.

For the GRPO reward function, Fin-o1 used **outcome-based answer correctness**: a verifier checks whether the model's final answer matches ground truth, with GPT-3.5-Turbo extracting final answers and mathematical comparison for scoring. The SFT stage used learning rate **5e-6** with 3 epochs; specific GRPO hyperparameters weren't published in the accessible version but the project used the open-r1 codebase (standard settings: group sizes 8-16, KL coefficient 0.001-0.04).

**The most relevant takeaway for Halcyon Lab:** Fin-o1's total FinCoT dataset (~9.2K examples) is far smaller than Fin-R1's ~60K examples, yet achieves competitive or superior results. The paper underscores that **data quality and difficulty-aware curation matter far more than quantity** for GRPO effectiveness.

---

## Designing reward functions that survive market noise

The credit assignment problem is the central challenge for Halcyon Lab: the model outputs analytical text, but the reward is about trade outcomes. Raw P&L is too noisy—financial markets have notoriously low signal-to-noise ratios—while binary win/loss is too sparse to guide multi-paragraph text generation.

**Trading-R1** (arxiv:2509.11420, 2025) provides the closest blueprint. It trains Qwen3-4B with GRPO for investment thesis generation using a three-stage curriculum: Stage I rewards professional thesis structure, Stage II rewards evidence-grounded claims, Stage III adds outcome-based rewards using **volatility-normalized, multi-horizon composite signals**. Specifically, forward returns at 3, 7, and 15-day horizons are each divided by 20-period rolling volatility (creating Sharpe-like signals), combined with empirical weights (0.3, 0.5, 0.2), then discretized into five classes via asymmetric percentile thresholds. This produced a Sharpe ratio of **2.72** and **70% hit rate** on NVDA, outperforming GPT-4.1.

For Halcyon Lab's pullback-in-strong-trend setups, the recommended composite reward architecture is:

**R_total = 0.5 × R_outcome + 0.35 × R_quality + 0.15 × R_format**

The outcome component should use volatility-normalized returns across 3, 5, and 10-day horizons, discretized into five buckets (Strong Win through Strong Loss) with asymmetric reward mapping (+1.0, +0.5, 0.0, −0.3, −0.8) reflecting the strategy's positive expectancy. The quality component uses an LLM-as-judge scoring evidence grounding, risk identification, internal consistency, and calibration. The format component applies rule-based checks for required sections, structured formatting, length bounds, and specific price targets.

The credit assignment problem has several practical solutions. **Segment-level rewards** (from SPO, OpenReview 2025) assign separate scores to entry reasoning, risk analysis, and exit strategy sections, applying outcome rewards only to the final decision. This prevents well-reasoned losing theses from being uniformly penalized. **Hindsight relabeling** converts failed trades into learning signal: after the outcome is known, a separate LLM rewrites the thesis to match what actually happened, creating DPO pairs from every trade regardless of outcome. **The curriculum approach from Trading-R1** is perhaps most practical: train structure first, then reasoning quality, then outcome alignment—avoiding the credit assignment problem by separating concerns across training stages rather than solving it in a single reward function.

The Risk-Aware RL Reward paper (arxiv:2506.04358, 2025) provides theoretical grounding, proving that composite rewards combining annualized return, downside risk penalty (Sortino-style), differential return, and Treynor ratio are "monotonic, differentiable, bounded, and convergent"—critical properties for stable GRPO training. **Never use raw P&L as the sole reward signal.** Volatility normalization is the single most impactful noise-reduction technique.

---

## Unsloth GRPO on consumer hardware: what actually works

Unsloth launched GRPO support on February 6, 2025, and as of March 2026 it is mature with extensive documentation, multiple notebook variants, and support for 500+ models including all Qwen3 sizes. Qwen3-8B is fully supported with dedicated GRPO notebooks. The implementation wraps TRL's GRPOTrainer with Unsloth's memory optimizations, claiming **80% less VRAM** than HuggingFace + Flash Attention 2.

A working configuration for Halcyon Lab:

```python
from unsloth import FastLanguageModel
from trl import GRPOConfig, GRPOTrainer

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3-8B",
    max_seq_length=1024,
    load_in_4bit=True,
    fast_inference=True,
    max_lora_rank=32,
    gpu_memory_utilization=0.6,  # lower for 12GB GPU
)
model = FastLanguageModel.get_peft_model(
    model, r=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                     "gate_proj","up_proj","down_proj"],
    lora_alpha=32,
    use_gradient_checkpointing="unsloth",
)

training_args = GRPOConfig(
    learning_rate=5e-6,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=4,
    num_generations=2,          # minimum for 12GB; use 8 on 24GB
    max_prompt_length=256,
    max_completion_length=768,
    max_steps=500,
    optim="paged_adamw_8bit",
    max_grad_norm=0.1,
)
```

**The honest assessment for RTX 3060 12GB:** This is borderline for Qwen3 8B GRPO. The critical constraint is that Unsloth's vLLM backend loads the model in **16-bit for inference** even when `load_in_4bit=True` for training—a known limitation (GitHub issue #1930). With `num_generations=2` (the minimum), very short completions (≤512 tokens), and batch size 1, it may fit. Confirmed working configurations: Qwen2.5-1.5B fits in **5-7GB**, 3B-4B models fit in **10-14GB**. For 8B, community reports confirm it works on RTX 3090 24GB with `gpu_memory_utilization=0.6`. **If the RTX 3060 consistently OOMs, drop to Qwen3-4B** or disable `fast_inference` (no vLLM, much slower but lower peak VRAM).

Known issues to watch: GRPO OOM when resuming from checkpoint (GitHub #3302, open bug); VRAM that keeps increasing during training (memory leak, #3512); zero loss with incorrect reward functions (#3260); and the vLLM 4-bit limitation (#1930). The RTX 3060 does not support FP8 (requires compute capability 8.9+; RTX 3060 is 8.6), so that optimization path is unavailable.

**Estimated training time for 500-1,000 examples on RTX 3060:** With the 8B model, approximately **2-4 hours for 500 steps** and **4-8 hours for 1,000 steps**. About 96% of GRPO time is vLLM inference (generating the group completions), not gradient updates. A 4B model would roughly halve these times.

---

## Delayed rewards are a non-problem for GRPO's batch architecture

GRPO's workflow—generate completions, score them, compute advantages, update—is **inherently decoupled from reward timing**. The algorithm doesn't care whether rewards arrive in milliseconds or weeks. The practical workflow for Halcyon Lab maps directly onto GRPO's architecture:

1. Deploy current model checkpoint
2. Generate trade theses for new opportunities (multiple completions per prompt)
3. Record (prompt, completions, model version) to SQLite
4. Wait 2-15 days for trade outcomes
5. Score completions using P&L data → compute rewards
6. Run GRPO training pass → new checkpoint
7. Deploy updated model, repeat

This is effectively offline/batch GRPO, which is how the algorithm already operates. A key paper from Meta/FAIR ("Bridging Offline and Online Reinforcement Learning for LLMs," arxiv:2506.21495) confirms that semi-online and offline approaches can achieve comparable performance to fully online GRPO in many settings. The critical implementation detail: **generate multiple completions per prompt at generation time** (even though you won't train immediately), because GRPO needs within-group variance to compute meaningful advantages. If you generate only one completion per prompt, you cannot compute group statistics later.

For additional data efficiency between outcome-based GRPO cycles, consider a **bridge reward model**: train a lightweight predictor of trade outcomes from thesis text features, enabling proxy rewards for faster iteration while awaiting real P&L data. The SuperRL framework (2025) formalizes this hybrid approach—combining RL with SFT fallback when reward signals are sparse or delayed.

Hindsight relabeling offers another multiplier: after a trade closes, use Claude or GPT-4 to rewrite the original thesis as if it correctly predicted the outcome. This creates synthetic positive examples from every trade, effectively doubling your training data. The ECHO framework (arxiv:2510.10304) and Hindsight Supervised Learning (OpenReview, 2025) validate this approach for LLM training.

---

## 100-200 trades can work, but barely—here is how to maximize them

Multiple sources confirm that GRPO can show improvement with remarkably small datasets. DeepLearning.AI's GRPO course states it "can work well even when you have fewer than 100 training examples." Unsloth documentation says "the best part of GRPO is you don't even need that much data—all you need is a great reward function." The Training-Free GRPO paper demonstrated that "merely 100 training samples yields superior performance to fully fine-tuning a 32B LLM."

**The group size multiplier is crucial.** With 200 prompts and `num_generations=8`, each GRPO epoch processes **1,600 scored completions**. Over 3 epochs, that's 4,800 training completions—comfortably above Unsloth's recommended minimum of 300 steps. With `num_generations=16` (DeepSeek-R1's setting, feasible on 24GB), you get 9,600 completions across 3 epochs from just 200 base examples.

However, there is a critical requirement: **your trades must span meaningful reward diversity**. GRPO learns by contrasting completions within each group. If all completions for a given prompt receive identical rewards, the z-score advantage is zero and no learning occurs. The "Hard Examples Are All You Need" paper showed that training on the hardest 10% of examples outperforms random selection by 30+ percentage points. If 90% of your 200 trades are winners with similar P&L, GRPO will have insufficient contrast.

Practical recommendations for the 100-200 trade regime:

- **Start GRPO at 100 closed trades**, but expect stronger signal at 200+. Wait for 500+ only if reward diversity is very low
- **Use multi-component rewards** (format + quality + outcome) to generate richer signal per example, since each component creates independent learning gradients
- **Set `num_generations=8`** minimum (16 if VRAM allows) and train for 3+ epochs
- **Apply difficulty-aware filtering**: exclude trades where the model already generates good theses (following Fin-o1's approach)
- **SFT first on synthetic data** to establish baseline competence before GRPO. The SFT stage can use unlimited synthetic examples from Claude; GRPO only needs real outcome data
- **Track "learnable percentage"**: the fraction of training groups with non-zero reward variance. Below 30%, your data is too homogeneous for effective GRPO

The comparison across methods: GRPO is less sample-efficient per individual prompt than PPO (which extracts per-token signal via the critic), but cheaper overall and more stable. DPO needs fewer examples but requires curated preference pairs and showed inconsistent results in financial reasoning. **GRPO's sweet spot is exactly the scenario Halcyon Lab faces**: verifiable outcomes, moderate dataset sizes, and constrained compute.

---

## Failure modes that could destroy a financial GRPO model

**Entropy collapse is GRPO's most dangerous failure mode.** The DAPO paper (ByteDance, 2025) documented that "the entropy of the policy decreases quickly as training progresses... sampled responses of certain groups tend to be nearly identical." For a trade thesis model, this manifests as always recommending the same direction, using identical analytical frameworks regardless of the stock, or producing maximally confident predictions on inherently uncertain outcomes. Research on entropy-preserving RL showed that policies trained with standard GRPO "lose their ability to explore" in subsequent training stages.

**Reward hacking is equally dangerous in financial applications.** The MO-GRPO paper identified that GRPO "optimizes only one of the objectives at the cost of others"—in machine translation, it "stops using any Japanese characters" to maximize readability scores while ignoring accuracy. A financial analogue: the model learns to generate convincing-sounding but substantively empty analyses that score well on format and quality metrics while its directional accuracy is random. One practitioner documented their 1.5B model "fell into stuffing its completion limit with random numbers" within 0.01 epochs of GRPO training.

**For Halcyon Lab, implement these specific guardrails:**

- **Monitor entropy continuously.** Plot generation entropy at every checkpoint. If it drops below 50% of its initial value, stop training and increase the KL penalty or switch to DAPO's clip-higher setting (ε_high = 0.28)
- **Track directional balance.** If >65% of generated theses recommend the same direction across diverse prompts, the model is collapsing. Include an explicit diversity penalty in the reward function
- **Use decoupled multi-objective rewards** (MO-GRPO style): normalize each reward component by its variance before combining, preventing the highest-variance component from dominating
- **Set KL coefficient β between 0.01 and 0.04** for financial applications (DeepSeek-R1-Zero used 0.04). Monitor KL divergence—NVIDIA recommends investigating any metric spiking above 1e-3
- **Validate on out-of-time data.** Never evaluate only on held-out random samples; use temporal cross-validation across different market regimes
- **Include regime-diverse training data.** If all 200 trades come from a single bull market period, the model will learn "always buy." Supplement with bearish scenarios, even synthetic ones

The Dr. GRPO variant fixes two documented biases in vanilla GRPO: response-length bias (shorter responses get disproportionate per-token gradients) and question-difficulty bias (near-zero variance groups create exploding advantages). DAPO goes further by removing the KL penalty entirely and adding dynamic sampling to filter out zero-advantage prompts. For financial applications where stability matters more than speed of learning, **standard GRPO with moderate KL penalty (β=0.01-0.04) is safer than DAPO**, but consider Dr. GRPO's length-normalization fix.

---

## Conclusion: a practical implementation roadmap

Halcyon Lab's three-stage pipeline (SFT → DPO → GRPO) is well-aligned with the research, but the evidence suggests **replacing DPO with a second SFT phase** (following DeepSeek-R1's pipeline and Fin-o1's finding that DPO is unreliable for financial reasoning). The recommended pipeline becomes: Stage 1 SFT on synthetic Claude-generated trade theses, Stage 2 SFT on difficulty-filtered real examples (following Fin-o1's FinCoT methodology), Stage 3 GRPO on outcome-conditioned rewards using the composite function described above.

The RTX 3060 12GB constraint is the tightest bottleneck. **Plan A**: Run Qwen3-8B GRPO with `num_generations=2`, max completion length ≤512, and Unsloth Standby mode—test immediately whether this fits. **Plan B** (likely more practical): Drop to Qwen3-4B for the GRPO stage, which comfortably fits in 12GB and still benefits from the same reward architecture. Fin-o1 showed that small models with targeted GRPO training routinely outperform models 10-80× their size; the quality of your reward signal matters far more than parameter count.

Start GRPO training as soon as you have **100 closed trades with meaningful reward diversity** (mix of wins, losses, and varied magnitudes). Use `num_generations=8`, train for 3 epochs, and track entropy and directional balance at every checkpoint. The delayed reward problem is a non-issue—GRPO's batch architecture was designed for exactly this workflow. The real challenge is building a reward function that captures trade quality rather than market randomness, and the volatility-normalized, multi-component approach from Trading-R1 is the current state of the art for solving this.
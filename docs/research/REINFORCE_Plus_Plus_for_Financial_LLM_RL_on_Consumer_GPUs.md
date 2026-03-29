# REINFORCE++ for financial LLM RL on consumer GPUs

**REINFORCE++ is mathematically superior to GRPO for small-dataset reinforcement learning, but it is not yet available in TRL.** The best practical path for Halcyon Lab is TRL's `GRPOTrainer` with `loss_type="dr_grpo"` (which removes GRPO's known biases) running through Unsloth on your consumer GPUs, combined with a multi-component financial reward function inspired by Trading-R1's volatility-normalized curriculum. This guide covers the complete implementation: algorithm selection with mathematical justification, reward function design drawing from four 2025 financial RL papers, exact GPU configurations for both your RTX 3060 and planned 3090, and a validated SFT → GRPO pipeline that skips DPO entirely — consistent with Fin-o1's finding that DPO produces inconsistent results in financial reasoning.

---

## 1. Why REINFORCE++ beats GRPO on small datasets — and what to use instead

### The mathematical core of the problem

GRPO (DeepSeek, Shao et al. 2024) generates k samples per prompt and normalizes advantages *locally* within each prompt's group. For prompt q with k responses {o₁,...,oₖ} receiving rewards {r₁,...,rₖ}, GRPO computes:

$$\hat{A}_i = \frac{r_i - \text{mean}(\{r_j\}_{j=1}^k)}{\text{std}(\{r_j\}_{j=1}^k)}$$

**Hu et al. (2025, arXiv:2501.03262) prove this estimator is biased for any finite group size k ≥ 2.** The bias arises because the numerator (centered reward) and denominator (local standard deviation) are not independent — they share the same random variables. More critically, when std approaches zero (all samples score similarly), advantages explode, injecting catastrophic gradient noise.

REINFORCE++ replaces this with **global batch normalization**. For the single-sample variant (k=1), each prompt generates one response, and the advantage is normalized across the entire training batch:

$$A^{\text{norm}}_{q,o_t} = \frac{A_{q,o_t} - \mu_{\text{batch}}}{\sigma_{\text{batch}}}$$

As global batch size N grows (typically **512–1024**), μ_batch and σ_batch converge to constants, making the estimator effectively unbiased. REINFORCE++ also uses the **k2 (MSE) KL estimator**, which is unbiased, versus GRPO's k3 forward-KL estimator that has high variance.

### The gradient variance disaster with 100 prompts

Walk through your specific scenario: **100 prompts with k=4 samples each yields 400 total samples, but advantages are normalized within groups of just 4.** Each group's standard deviation estimate has only 3 degrees of freedom — an extraordinarily noisy denominator. When a group happens to have similar rewards (common in financial commentary where most responses are reasonable), std → 0 and advantages explode. The policy receives massive, meaningless gradient updates for those prompts.

With REINFORCE++ (k=1), those same 100 prompts produce 100 samples normalized globally. The batch statistics draw from all 100 data points, giving **25× more stable normalization** than GRPO's groups of 4. The paper demonstrates this directly: "GRPO (local norm) overfits completely, while REINFORCE++ (global norm) generalizes." GRPO's reward rises quickly but KL divergence explodes — classic reward hacking.

### Dr. GRPO fixes biases but not the fundamental architecture

Dr. GRPO (Liu et al., 2025, arXiv:2503.20783) identifies three biases in standard GRPO and removes two:

- **Length bias**: GRPO divides by response length |o|, which incentivizes shorter correct responses and longer incorrect ones (creating the illusory "Aha moment")
- **Difficulty bias**: Dividing by std(rₖ) amplifies easy questions (low variance) and suppresses hard questions (high variance) — exactly backwards from optimal curriculum design

Dr. GRPO's fix is elegant: simply remove 1/|o| and std(rₖ) from the objective. The result is mathematically equivalent to RLOO up to a constant factor of 1/(K-1). **However, Dr. GRPO still uses per-prompt advantage estimation.** It does not adopt global normalization. For datasets under ~2,000 prompts, the per-prompt approach retains high variance. REINFORCE++ remains architecturally better suited for Halcyon Lab's 100–1,000 trade scenario.

### Implementation reality: TRL has Dr. GRPO but not REINFORCE++

**REINFORCE++ is not available in TRL** (tested through v0.29.1, March 2026). TRL's RL trainers are `GRPOTrainer`, `RLOOTrainer`, and `PPOTrainer`. The REINFORCE++ paper is referenced in TRL's paper index, but no trainer class exists.

The canonical REINFORCE++ implementation lives in **OpenRLHF** (github.com/OpenRLHF/OpenRLHF), the framework from the paper's authors. It supports `--advantage_estimator reinforce | reinforce_baseline | group_norm | dr_grpo | rloo`. **verl** (Volcano Engine, github.com/volcengine/verl) also implements REINFORCE++. Both are designed for multi-GPU Ray/FSDP clusters and **lack BitsAndBytes/QLoRA integration** — making them impractical for your consumer GPU setup.

**The practical recommendation**: Use TRL's `GRPOTrainer` with `loss_type="dr_grpo"` (which eliminates length and difficulty biases) through **Unsloth** (which provides ~80% VRAM savings). This gives you the best available algorithm within the consumer-GPU-compatible ecosystem. For the `num_generations` parameter, keep k low (2–4) to maximize prompt diversity per batch, which partially compensates for the lack of global normalization.

| Algorithm | Implementation | QLoRA support | Consumer GPU | Best for small datasets |
|-----------|---------------|---------------|-------------|------------------------|
| REINFORCE++ | OpenRLHF, verl | ❌ No | ❌ Cluster-only | ⭐⭐⭐⭐⭐ |
| RLOO | TRL `RLOOTrainer` | ✅ Yes | ✅ Yes | ⭐⭐⭐⭐ |
| Dr. GRPO | TRL `GRPOTrainer` `loss_type="dr_grpo"` | ✅ Yes | ✅ Yes | ⭐⭐⭐⭐ |
| GRPO (DAPO) | TRL `GRPOTrainer` `loss_type="dapo"` | ✅ Yes | ✅ Yes (Unsloth) | ⭐⭐⭐ |
| GRPO (original) | TRL `GRPOTrainer` `loss_type="grpo"` | ✅ Yes | ✅ Yes | ⭐⭐ (biased) |

### VRAM savings: k=1 versus k=4–8

Each generation requires KV cache memory. For Qwen3 8B with 32 layers and K/V dimension 1024, at 1,024 completion tokens: **~125 MB per sequence**. GRPO with k=8 requires ~1 GB of KV cache alone, plus ~2.4 GB for logits (vocab size 152K × 8 sequences × 1024 tokens × 2 bytes). REINFORCE++ with k=1 needs ~125 MB KV cache and ~300 MB logits — **saving roughly 3 GB**, which is the difference between fitting and not fitting on a 12 GB GPU.

---

## 2. Reward function design for financial trade commentary

### Lessons from four 2025 financial RL papers

**Trading-R1** (Xiao et al., Sep 2025, arXiv:2509.11420) introduces the most directly relevant approach: a three-stage curriculum where process quality is learned before outcome optimization. Stage I rewards structural formatting, Stage II rewards evidence-grounded claims with citations, and Stage III applies a **volatility-normalized outcome reward** — forward returns divided by rolling 20-period volatility across 3/7/15-day horizons (weighted 0.3/0.5/0.2). This Sharpe-like signal automatically adjusts for market regime.

**Alpha-R1** (Jiang et al., Dec 2025, arXiv:2512.23515) achieved remarkable zero-shot generalization from CSI 300 to CSI 1000 (**Sharpe 4.03 on unseen data**) by training the LLM to reason about *why* alpha factors are relevant rather than memorizing statistical patterns. Removing RL entirely caused Sharpe to drop to **-0.77**, proving RL is essential, not optional. The key insight: reward the model for economic reasoning, not pattern matching.

**Fin-o1** (Qian et al., Feb 2025, arXiv:2502.08127) systematically compared PPO, DPO, and GRPO for financial reasoning. **GRPO yielded reliable gains; PPO and DPO did not.** DPO failed because financial reasoning requires dynamic, context-dependent evaluation that fixed preference pairs cannot capture.

**The Risk-Aware RL Reward paper** (Srivastava et al., Jun 2025, arXiv:2506.04358) formalizes composite rewards: R = w₁·R_ann − w₂·σ_down + w₃·D_ret + w₄·Treynor. The multi-component design prevents reward hacking — single-metric rewards (Sharpe alone, return alone) create exploitable surfaces.

### Composite reward function for Halcyon Lab

Drawing from these papers, here is a four-component reward function designed for trade commentary RL with ~100–1,000 closed trades:

```python
import numpy as np

def halcyon_reward(completion: str, trade_metadata: dict) -> float:
    """
    Composite reward for financial trade commentary RL.
    
    trade_metadata contains:
        pnl: float (realized P&L in dollars)
        atr_at_entry: float (14-period ATR at trade entry)
        mae_dollars: float (maximum adverse excursion)
        position_size: float
        conviction_stated: str ("low", "moderate", "high", "very_high")
        regime_volatility: float (rolling 20-day VIX or realized vol)
    """
    
    # === Component 1: Volatility-Normalized Outcome (weight: 0.30) ===
    # Inspired by Trading-R1's Sharpe-like signal
    pnl = trade_metadata['pnl']
    atr = trade_metadata['atr_at_entry']
    position_size = trade_metadata['position_size']
    
    # Normalize P&L by ATR (risk-adjusted return per unit of expected move)
    r_normalized = (pnl / position_size) / atr if atr > 0 else 0
    # Clip to [-3, 3] to prevent outlier domination
    outcome_score = np.clip(r_normalized, -3.0, 3.0) / 3.0  # Scale to [-1, 1]
    
    # === Component 2: Process Quality Rubric (weight: 0.35) ===
    # 6 dimensions, each scored 0-5 by rubric (rule-based or LLM judge)
    rubric_scores = score_commentary_rubric(completion)
    # Dimensions: thesis_clarity, evidence_quality, risk_identification,
    #             catalyst_specificity, position_sizing_logic, exit_plan_clarity
    process_score = sum(rubric_scores.values()) / 30.0  # Normalize to [0, 1]
    
    # === Component 3: Conviction-Outcome Calibration (weight: 0.20) ===
    conviction_map = {"low": 0.25, "moderate": 0.50, "high": 0.75, "very_high": 1.0}
    conviction = extract_conviction(completion, conviction_map)
    won = pnl > 0
    
    if won:
        # Reward high conviction on winners, mild reward for low conviction
        calibration_score = 0.5 + 0.5 * conviction
    else:
        # Penalize high conviction on losers, no penalty for low conviction
        calibration_score = 1.0 - conviction  
        # "high conviction loss" → 0.25, "low conviction loss" → 0.75
    
    # === Component 4: Risk Management (MAE/ATR) (weight: 0.15) ===
    mae = abs(trade_metadata['mae_dollars'] / position_size)
    mae_atr_ratio = mae / atr if atr > 0 else 0
    
    if mae_atr_ratio < 1.0:
        risk_score = 1.0  # Stop was tight relative to ATR — good
    elif mae_atr_ratio < 2.0:
        risk_score = 1.0 - 0.5 * (mae_atr_ratio - 1.0)  # Linear decay
    else:
        risk_score = max(0.0, 0.5 - 0.25 * (mae_atr_ratio - 2.0))  # Heavy penalty
    
    # === Composite Reward ===
    weights = {'outcome': 0.30, 'process': 0.35, 
               'calibration': 0.20, 'risk': 0.15}
    
    reward = (
        weights['outcome'] * outcome_score +
        weights['process'] * process_score +
        weights['calibration'] * calibration_score +
        weights['risk'] * risk_score
    )
    
    return reward
```

### Handling "good process, bad outcome" trades

The weight distribution above is deliberate: **process quality (35%) outweighs outcome (30%)**. A trade with excellent analysis (process_score = 0.9), low conviction appropriately (calibration_score = 0.75), tight stop (risk_score = 1.0), but an unlucky loss (outcome_score = -0.3) receives:

> 0.30 × (-0.3) + 0.35 × 0.9 + 0.20 × 0.75 + 0.15 × 1.0 = **+0.375**

This is a *positive* reward — the model learns that disciplined analysis with unlucky outcomes is acceptable. Conversely, a sloppy analysis with a lucky win gets penalized:

> 0.30 × 0.5 + 0.35 × 0.2 + 0.20 × 0.5 + 0.15 × 0.3 = **+0.365**

The lucky win barely outscores the unlucky disciplined trade, preventing the model from learning that outcomes trump process.

### Reward hacking failure modes and countermeasures

The most dangerous failure mode is **"moderate conviction convergence"**: the model always outputs "moderate conviction" to minimize calibration penalties. Counter this by tracking conviction distribution entropy across generations — if >80% of outputs use the same conviction level, add a diversity bonus or audit the calibration component. Trading-R1's asymmetric quantile thresholds (85%/53%/15%/3%) specifically address this by forcing non-uniform label distributions.

**Regime-aware scaling** prevents another failure mode: the model learning that "hold" or "no strong view" minimizes errors in sideways markets. Normalize the outcome component by regime volatility (divide r_normalized by regime_volatility/median_volatility) so that smaller moves in quiet markets carry equal weight to larger moves in volatile markets.

The **credit assignment problem** — separating trade quality from market luck — is addressed by two mechanisms: (1) the multi-component reward structure ensures process quality dominates short-term outcome noise, and (2) volatility normalization (P&L/ATR) creates a Sharpe-like signal where a +2% gain in low-volatility environment registers differently than during high volatility, automatically adjusting for market conditions.

---

## 3. Exact GPU configurations for RTX 3060 and RTX 3090

### Base memory budget

Qwen3 8B in 4-bit NF4 quantization: **~4.5–5 GB**. QDoRA adapter (rank 32, all linear targets): **~200–400 MB** trainable parameters. AdamW 8-bit optimizer states: **~400–800 MB**. Gradient checkpointing saves ~60–70% of activation memory. These components total roughly **6–7 GB** before generation overhead.

The critical variable is RL-specific memory: each generation requires KV cache (~125 MB per 1024-token sequence) plus logit storage (vocab 152K × seq_len × 2 bytes = ~296 MB per sequence). With k=4, that's **~1.7 GB** for generation overhead alone.

### RTX 3060 12GB: tight but viable with Unsloth

**Unsloth is non-negotiable on 12 GB.** Its chunked logit computation and standby mode (sharing vLLM inference memory with training weights) reduce VRAM by ~80% compared to vanilla TRL. The RTX 3060 supports BF16 natively (Ampere GA106, Compute Capability 8.6).

```python
import os
os.environ["UNSLOTH_VLLM_STANDBY"] = "1"  # Critical for 12GB

from unsloth import FastLanguageModel, PatchFastRL
PatchFastRL("GRPO", FastLanguageModel)
from trl import GRPOConfig, GRPOTrainer

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3-8B",
    max_seq_length=1024,
    load_in_4bit=True,
    fast_inference=True,
    max_lora_rank=32,
    gpu_memory_utilization=0.90,  # Leave 1.2GB headroom
)

model = FastLanguageModel.get_peft_model(
    model, r=32, lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                     "gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth",
)

training_args = GRPOConfig(
    output_dir="halcyon-rl-3060",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,      # Effective batch = 8
    num_generations=2,                   # k=2 for 12GB (try 4 with Unsloth)
    max_prompt_length=256,
    max_completion_length=512,           # Push to 1024 with Unsloth standby
    learning_rate=5e-6,
    max_grad_norm=0.1,
    loss_type="dr_grpo",                # Best bias-corrected variant
    beta=0.04,                          # KL penalty (prevent drift from SFT)
    bf16=True,
    num_train_epochs=1,
    warmup_ratio=0.1,
    lr_scheduler_type="cosine",
    logging_steps=1,
    save_steps=50,
    report_to="none",
)
```

**Estimated peak VRAM**: ~10–11 GB with Unsloth standby mode, leaving ~1 GB headroom.

### RTX 3090 24GB: comfortable with room for larger k

```python
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3-8B",
    max_seq_length=2048,
    load_in_4bit=True,
    fast_inference=True,
    max_lora_rank=32,
    gpu_memory_utilization=0.95,
)

training_args = GRPOConfig(
    output_dir="halcyon-rl-3090",
    per_device_train_batch_size=1,       # Can try 2
    gradient_accumulation_steps=4,
    num_generations=4,                    # k=4 comfortable; k=8 possible
    max_prompt_length=512,
    max_completion_length=1024,           # Push to 2048 with Unsloth
    learning_rate=5e-6,
    max_grad_norm=0.1,
    loss_type="dr_grpo",
    beta=0.04,
    bf16=True,
    num_train_epochs=1,
    warmup_ratio=0.1,
    lr_scheduler_type="cosine",
    logging_steps=1,
    save_steps=50,
)
```

**Estimated peak VRAM**: ~16–18 GB, leaving 6–8 GB headroom for larger k or longer sequences.

### Qwen3 14B on RTX 3090: feasible but constrained

14B in 4-bit ≈ 8–9 GB base model. With RL overhead, total VRAM lands around **20–22 GB** with k=2 and max_completion_length=512. This is tight but workable. Use `num_generations=2` and keep sequences short. **Not recommended unless you have a specific need for 14B** — 8B with well-designed RL will likely outperform 14B-SFT-only for your task.

### Training time estimates

On RTX 3090 with Qwen3 8B, k=4, 1024 completion length: **~30–120 seconds per step** (generation is ~70% of step time). For 500 prompts at 1 epoch: ~500 steps → **7–17 hours**. For 100 prompts at 3 epochs: ~300 steps → **2.5–10 hours**. Unsloth's vLLM integration provides ~1.5–2× speedup over standard HuggingFace generation.

### Loading your existing SFT QDoRA adapter

Two approaches exist. The recommended path for Halcyon Lab:

```python
# Approach: Merge SFT adapter → Apply fresh LoRA for RL
from peft import PeftModel
from transformers import AutoModelForCausalLM, BitsAndBytesConfig
import torch

# Load and merge SFT adapter
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
base = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen3-8B", quantization_config=bnb_config, device_map="auto"
)
model = PeftModel.from_pretrained(base, "path/to/sft_qdora_adapter")
model = model.merge_and_unload()  # SFT knowledge baked into base weights

# Now the merged model becomes the reference for KL divergence
# GRPOTrainer will apply a fresh LoRA and track KL against this reference
```

This approach is cleaner than continuing training on the same adapter, avoids a known TRL issue where `_prepare_peft_model()` can freeze LoRA weights when passed a `PeftModel` (TRL issue #3926), and means the KL divergence penalty operates against your SFT model — exactly what you want to prevent catastrophic forgetting of supervised knowledge.

---

## 4. Pipeline design: skip DPO, go straight to RL

### The evidence against DPO for financial reasoning

Fin-o1's systematic comparison is definitive: **GRPO yielded reliable gains across all financial datasets; DPO did not.** The failure mechanism is fundamental: DPO relies on static preference pairs, but financial reasoning involves ambiguous ground truth where reasonable analysts can disagree. A preference pair saying "analysis A is better than analysis B" for a given trade may reverse under different market conditions. GRPO's online policy optimization adapts to this non-stationarity; DPO's offline approach cannot.

Both Fin-R1 and Fin-o1 validated the **SFT → GRPO pipeline** without DPO:
- Fin-o1-8B (LLaMA-3.1-8B): SFT on FinCoT + GRPO → **85.0 ConvFinQA, 76.0 FinQA**
- Fin-o1-14B (Qwen2.5-14B): SFT + GRPO → 61.07% on FinReason, outperforming GPT-o1 (54.05%)

The emerging 2025 consensus, reinforced by DeepSeek-R1's demonstration that RL alone can induce reasoning: **SFT → RL is sufficient.** DPO adds pipeline complexity without clear benefit for specialized domains.

### Can GRPO provide DPO's alignment benefits?

Yes. GRPO's KL penalty (β parameter) naturally constrains the policy near the reference (SFT) model, providing the same "stay aligned" pressure DPO gives. The group-relative advantage normalization additionally provides a form of preference learning — the model learns which responses are better *relative to its own current capability* for each prompt, which is conceptually similar to DPO's preference optimization but with online, adaptive updates.

### GGUF export for Ollama deployment

The workflow is identical to SFT adapter export:

```bash
# 1. Merge RL adapter into base model (Python)
model = PeftModel.from_pretrained(base_model, "path/to/rl_adapter")
merged = model.merge_and_unload()
merged.save_pretrained("merged_rl_model/")

# 2. Convert to GGUF
python llama.cpp/convert_hf_to_gguf.py merged_rl_model/ \
    --outfile halcyon-rl-F16.gguf --outtype f16

# 3. Generate importance matrix for better quantization
./llama-imatrix -m halcyon-rl-F16.gguf -f calibration_trades.txt \
    --chunk 512 -o halcyon-imatrix.dat -ngl 32

# 4. Quantize
./llama-quantize --imatrix halcyon-imatrix.dat \
    halcyon-rl-F16.gguf halcyon-rl-Q4_K_M.gguf Q4_K_M

# 5. Create Ollama Modelfile and deploy
echo 'FROM ./halcyon-rl-Q4_K_M.gguf' > Modelfile
ollama create halcyon-rl -f Modelfile
```

With Unsloth, this simplifies to one line: `model.save_pretrained_gguf("output/", tokenizer, quantization_method="q4_k_m")`. **Critical**: use the same chat template during inference as during training. Mismatched templates cause gibberish or infinite generation.

### Incremental RL as trade data accumulates

Multiple rounds of GRPO are straightforward as your dataset grows from 100 to 200, 300, 500 trades:

```python
# Round N+1: Load previous checkpoint + expanded dataset
model = AutoModelForCausalLM.from_pretrained("checkpoint_round_n/")
# Mix 30% replay from old data with 70% new trades
combined = concatenate_datasets([
    old_dataset.select(range(int(len(old_dataset) * 0.3))),
    new_trades_dataset
])
trainer = GRPOTrainer(model=model, train_dataset=combined, ...)
trainer.train()
```

RL is **naturally more robust to catastrophic forgetting than SFT** — policy gradient updates are more conservative than supervised loss updates. The KL penalty from the reference model acts as an automatic regularizer. NVIDIA's Nemotron paper additionally recommends **periodically resetting the reference policy and optimizer states** during prolonged RL to restore training stability.

---

## 5. Monitoring, failure modes, and when to rollback

### Epoch-by-epoch metrics with specific thresholds

| Metric | Healthy range | Warning threshold | Rollback trigger |
|--------|--------------|-------------------|-----------------|
| Reward mean | Smooth upward trend | Sudden jump >20% in 10 steps | Sustained decline for 3+ checkpoints |
| Reward std | Gradual decrease | Increasing variance | — |
| Policy entropy | Slow steady decrease | <1.0 nats | **<0.5 nats** (entropy collapse) |
| KL divergence | <5–10 | >10 | **>15** (excessive policy drift) |
| Gradient norm | Stable, <1.0 | Spikes >5× baseline | Persistent instability after lr reduction |
| Completion diversity | Multiple distinct outputs per prompt | >80% identical outputs | All k generations identical |
| Holdout reward | Tracks in-sample | Diverges >15% from in-sample | Holdout drops while in-sample rises |

**Entropy collapse is the dominant failure mode in GRPO-family training.** The DAPO paper (ByteDance) shows that default symmetric clipping (ε=0.2) causes entropy collapse. The fix is asymmetric clipping: set `epsilon=0.2` (lower bound) and `epsilon_high=0.28` (upper bound) in `GRPOConfig`, which DAPO's default loss type already implements. For additional safety, monitor entropy every logging step and halt training if it drops below 0.5 nats.

### How Alpha-R1 achieved zero-shot generalization

Alpha-R1's generalization from CSI 300 (training) to CSI 1000 (unseen, Sharpe 4.03) worked because the model learned **economic reasoning principles** rather than statistical patterns. The ablation is revealing: replacing natural language factor descriptions with raw mathematical formulas dropped Sharpe from 1.62 to 0.83. The model wasn't memorizing factor returns — it was reasoning about *why* factors should work given current market conditions. This has a direct lesson for Halcyon Lab: your reward function should incentivize *reasoning about trade logic* (process component), not just outcome prediction accuracy.

### Financial-specific failure modes

**Reward hacking via hedging language**: The model generates non-committal "markets could go either way" commentary that minimizes penalties without providing actionable insight. Detect by tracking the distribution of conviction levels and analysis specificity. Counter with a minimum specificity threshold in the process rubric.

**Catastrophic forgetting of SFT knowledge**: The model produces higher-reward but lower-quality text (grammatical errors, lost formatting). Detect by running a general-quality rubric alongside the financial reward. Counter with KL penalty (β=0.04) and replay buffer mixing.

**Spurious feature exploitation**: The model learns that certain keywords ("bullish momentum," "strong support") correlate with positive rewards regardless of analytical validity. Counter by ensuring your rubric rewards evidence-grounded claims — the model must cite specific data points, not just deploy financial jargon.

### Champion-challenger evaluation framework

```python
from scipy.stats import wilcoxon
import numpy as np

def evaluate_rl_vs_sft(sft_model, rl_model, holdout_trades, reward_fn):
    sft_rewards = [reward_fn(sft_model.generate(t)) for t in holdout_trades]
    rl_rewards = [reward_fn(rl_model.generate(t)) for t in holdout_trades]
    
    differences = np.array(rl_rewards) - np.array(sft_rewards)
    non_zero = differences[differences != 0]
    
    if len(non_zero) >= 10:
        stat, p_value = wilcoxon(non_zero, alternative='greater')
        win_rate = np.mean(differences > 0)
        # Promote RL model if: p < 0.05 AND win_rate > 55%
        return {'win_rate': win_rate, 'p_value': p_value,
                'mean_improvement': np.mean(differences),
                'promote': p_value < 0.05 and win_rate > 0.55}
```

Reserve **20–30% of your trade data** as a holdout set. Never train on holdout data. Run this evaluation after each RL round and after each incremental training cycle.

---

## 6. Complete algorithm comparison

| Feature | GRPO (original) | GRPO (DAPO loss) | Dr. GRPO | RLOO | REINFORCE++ |
|---------|-----------------|-------------------|----------|------|-------------|
| **TRL class** | `GRPOTrainer` `loss_type="grpo"` | `GRPOTrainer` `loss_type="dapo"` | `GRPOTrainer` `loss_type="dr_grpo"` | `RLOOTrainer` | ❌ Not in TRL |
| **Unsloth support** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Other frameworks** | OpenRLHF, verl, ms-swift | TRL, Unsloth | TRL, Unsloth | TRL | OpenRLHF, verl |
| **QLoRA compatible** | ✅ | ✅ | ✅ | ✅ | ❌ (cluster frameworks) |
| **Samples per prompt (k)** | 8–16 typical | 8–16 | k>1 | K>1 (4–8 typical) | **k=1 supported** |
| **Advantage normalization** | Local (biased) | Local + DAPO fixes | Local (no std) | Local (leave-one-out, unbiased) | **Global batch** |
| **Estimator bias** | ⚠️ Proven biased | Reduced (DAPO fixes) | ✅ Unbiased | ✅ Unbiased | ✅ Effectively unbiased |
| **KL estimator** | k3 (biased, high variance) | k3 | β=0 (removed) | In reward signal | **k2 (unbiased)** |
| **Length bias** | ⚠️ Yes (1/\|o\| term) | ✅ Fixed | ✅ Fixed | N/A | N/A |
| **Difficulty bias** | ⚠️ Yes (std division) | Partially addressed | ✅ Fixed | N/A | N/A |
| **VRAM (8B, 4-bit, k=4)** | ~18 GB | ~18 GB | ~18 GB | ~18 GB | **~12 GB (k=1)** |
| **Small dataset (<2K prompts)** | ⭐⭐ Poor (overfits) | ⭐⭐⭐ Better | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Best |
| **Financial LLM evidence** | Fin-o1 (works), Alpha-R1 | Default in TRL | — | — | Logic-RL, ProRLv2 |
| **Training speed vs PPO** | ~50% faster | ~50% faster | ~50% faster | 2–3× faster | **138% faster** |
| **Reasoning benchmarks** | AIME avg 22.58 | — | AIME 43.3% | Outperforms PPO, DPO | **AIME avg 24.10** |

### The recommendation for Halcyon Lab

**Primary**: TRL `GRPOTrainer` with `loss_type="dr_grpo"` through Unsloth. This gives you the best bias-corrected algorithm available on consumer GPUs with QLoRA. Use k=2 on your RTX 3060 (expanding to k=4 on RTX 3090), `beta=0.04` for KL regularization, and the composite reward function above.

**If you later gain access to multi-GPU infrastructure**: Switch to OpenRLHF with REINFORCE++ (`--advantage_estimator reinforce`), which provides global normalization and k=1 sampling — ideal for your small-dataset scenario.

**Monitor aggressively**: Log entropy, KL, and holdout reward at every step. Save checkpoints every 50 steps. Rollback if entropy drops below 0.5 nats or KL exceeds 15. Run champion-challenger evaluation against your SFT baseline after each training round. With only 100–1,000 prompts, overfitting is your primary risk — the KL penalty and replay buffer are your most important defenses.
# Retraining a LoRA-tuned 8B model on 5–10 weekly examples is wasteful — here's the optimal cadence

Adding 5–10 new examples to a 1,722-example corpus represents a **0.3–0.6% data increment** that produces improvements below the noise floor of any practical evaluation setup. Power-law scaling research (Zhang et al., ICLR 2024) predicts relative improvement of ~0.1–0.3% from this increment — undetectable even with paired testing. The evidence-based recommendation is to **retrain monthly from the original Qwen3 8B base** when ~30–50 new examples have accumulated, with canary-set and regime-change override triggers. This approach eliminates NF4 quantization error accumulation, aligns with the ~5% corpus-growth threshold where improvements become measurable, and costs the same one hour per cycle.

---

## The 5% threshold: when new data starts mattering

The minimum batch size question has a clear answer grounded in scaling laws. Fine-tuning performance follows a power law: **L̂(D) = A/D^β + E**, where β for LoRA typically falls between 0.3 and 0.5. Going from 1,722 to 1,732 examples (adding 10) sits deep on the diminishing-returns plateau where gradient contributions from new examples are proportionally negligible.

LIMA (Zhou et al., NeurIPS 2023) demonstrated that **1,000 carefully curated examples** outperformed Stanford Alpaca's 52,000, with 88% of responses meeting quality requirements. But LIMA's power came from diversity, not volume — each example covered a distinct instruction pattern. Adding 5–10 equity commentary examples that resemble the existing 1,722 is fundamentally different from adding 5–10 examples spanning new capability dimensions. The marginal value of each new example depends almost entirely on whether it covers genuinely novel patterns — unusual market conditions, new trade structures, edge-case commentary formats — rather than routine trades the model already handles well.

Empirical practitioner data converges on concrete thresholds for 8B LoRA models. Classification tasks stabilize at **100–300 examples**, content generation requires **500–2,000**, and complex domain adaptation needs **1,000–5,000**. The absolute floor for measurable LoRA behavior change is approximately 50–100 diverse examples. Dataset scaling research (arXiv:2604.09389) confirms that **~30% of training data achieves ~90% of full-data accuracy**, meaning the first examples carry disproportionate weight while additions beyond the initial corpus face steep diminishing returns.

The practical batch-size thresholds for this specific scenario break down clearly:

| Cadence | New examples | % of corpus | Expected impact |
|---------|-------------|-------------|-----------------|
| Weekly (5–10) | 5–10 | 0.3–0.6% | **Not detectable** — below noise floor |
| Biweekly (10–20) | 10–20 | 0.6–1.2% | **Marginal** — detectable only for high-novelty examples |
| Monthly (20–40) | 20–40 | 1.2–2.3% | **Borderline useful** — measurable if examples are diverse |
| 6–8 weeks (40–80) | 40–80 | 2.3–4.6% | **Recommended minimum** — approaching the ~5% threshold |
| Quarterly (60–120) | 60–120 | 3.5–7.0% | **Reliably measurable** — clear signal above noise |

**The ~5% threshold (~86 new examples) is where power-law scaling produces gains distinguishable from evaluation noise.** At the current 5–10 examples per week accumulation rate, this takes 9–17 weeks. A practical monthly cadence that accepts borderline-useful updates while avoiding excessive compute waste represents the optimal balance.

---

## LoRA's forgetting-learning tradeoff favors merge-and-reset — with caveats

The continual learning literature for LoRA-based fine-tuning has matured rapidly since 2024, and the findings both validate and constrain the merge-and-reset strategy.

Biderman et al. (TMLR 2024, "LoRA Learns Less and Forgets Less") established the foundational tradeoff: LoRA **substantially underperforms full fine-tuning** on target-domain tasks but **consistently forgets less** of the base model's knowledge. On Llama-2-7B across programming and math domains, LoRA preserved source-domain capabilities (language understanding, world knowledge, common-sense reasoning) far better than full fine-tuning, while also maintaining more diverse generated solutions. Critically, they found that **LoRA rank serves as a tuning knob** — higher ranks learn more but forget more — and that MLP blocks are the primary loci for continual learning. For iterative retraining, LoRA's inherent regularization is favorable: each training cycle structurally limits damage to pre-existing knowledge.

Kalajdzievski (arXiv:2401.05605, 2024) quantified this tradeoff precisely with a **shifted power law**: forgetting increases as **F ≈ A·(x − x₀)^α + C** in both parameter count and gradient steps, paralleling Kaplan et al.'s pre-training scaling laws. The inverse linear relationship between fine-tuning performance and forgetting is fundamental — it cannot be avoided through early stopping or parameter reduction. This creates a strong rationale for experience replay (mixing old examples into each new training cycle) to counteract the unavoidable forgetting.

The most critical concern for merge-and-reset comes from Shuttleworth et al. (arXiv:2410.21228, NeurIPS 2025), who identified **intruder dimensions** — new high-ranking singular vectors that appear in LoRA-fine-tuned weight matrices but not in full fine-tuning. These intruder dimensions are causally linked to forgetting and, crucially, **accumulate during sequential fine-tuning**. Each merge-and-reset cycle permanently bakes new intruder dimensions into the base model. Mitigations include using higher rank with rank stabilization (α = 2r) and periodic reversion to the original base model — both directly applicable to this workflow.

On the positive side, ILT (Meng et al., Interspeech 2025) directly validated merge-then-retrain across three sequential iterations on Whisper-large-v3 and Qwen2-Audio, demonstrating progressive improvement. MSSR (Lu et al., arXiv:2603.09892, March 2026) showed that **memory-aware adaptive replay** with time-dependent decay works effectively for Qwen2.5-7B across 11 sequential tasks. Wang et al. (arXiv:2503.20018) demonstrated that experience replay eliminates loss of plasticity entirely — the model's ability to learn new tasks is preserved through replay without any architectural modifications. Krasheninnikov et al. (arXiv:2509.14223) revealed that LLM activations **linearly encode training recency**, meaning earlier-learned information needs periodic refreshing to avoid being deprioritized.

O-LoRA and InfLoRA, the orthogonal continual LoRA methods, are **impractical for consumer hardware**. Both require maintaining multiple task-specific LoRA adapters simultaneously, multiplying memory overhead beyond what an RTX 3060 12GB can support for 8B models. The merge-and-reset approach producing a single merged model remains the most practical strategy for consumer GPUs.

---

## NF4 quantization error demands a monthly full reset

The merge-and-reset cycle introduces a subtle but compounding degradation channel: **NF4→FP16 dequantization error**. NF4 quantization maps weights to only 16 discrete levels per block of 64 weights. Each dequantize→merge→re-quantize cycle introduces rounding error that does not cancel across cycles because each re-quantization starts from already-degraded weights.

Empirical evidence is stark. A documented case (HuggingFace Transformers issue #26492) showed perplexity jumping from **3.74 to 5.25** — a 40% increase — from a single QLoRA merge round-trip when the merged model was re-loaded in quantized form. Per-weight absolute error of ~0.002 on weights of ~0.031 (approximately **6.5% relative error** for small-magnitude weights) compounds linearly across cycles. After 5–10 cycles without maintaining an FP16 master copy, accumulated weight drift of 5–10% begins measurably degrading generation quality.

The critical mitigation is maintaining an **FP16 master copy** of the merged model. The workflow should be: (1) load original Qwen3 8B in NF4 for training, (2) train LoRA adapters, (3) dequantize NF4→FP16, (4) merge LoRA weights into FP16 copy, (5) save FP16 as the new master, (6) quantize to NF4 only for the next training cycle's forward pass. This bounds quantization error to a single round per cycle rather than accumulating.

Even with this mitigation, research on merge artifacts (DO-Merging, arXiv:2505.15875; Merge before Forget, arXiv:2512.23017) shows that LoRA modules exhibit **much larger parameter magnitude variance** than full fine-tuned weights, and this variance correlates with worse merging performance over sequential cycles. The LoRR paper (arXiv:2508.06412) explicitly advocates periodic parameter resets to preserve "network plasticity."

**Since a full retrain from the original Qwen3 8B base costs the same ~1 hour as incremental training**, the cost-benefit analysis is unambiguous: perform a full reset monthly, or after a maximum of 4–6 incremental merge cycles, whichever comes first. There is zero computational penalty for resetting, and it eliminates all accumulated quantization artifacts and intruder dimensions.

---

## Canary-set perplexity plus regime triggers beats a fixed schedule

The retraining trigger question has been studied across multiple domains. Vela et al. (Nature Scientific Reports, 2022) found that **91% of model-dataset pairs showed temporal degradation**, with finance specifically among the affected domains. Their critical insight: degradation occurs even without concept drift, making simple error thresholds insufficient. They advocate monitoring-based triggers over fixed schedules.

Zanotti et al. (arXiv:2505.00356) challenged the conventional belief that frequent retraining is essential, finding that **periodic retraining performs statistically indistinguishably from continuous retraining** (verified with Friedman-Nemenyi tests) while reducing compute costs by 50–75%. This directly supports the position that weekly Saturday retraining is unnecessary.

For drift detection at this scale, traditional statistical tests face a fundamental power problem. PSI (Population Stability Index) standard thresholds have **no formal connection to Type I error rates** and produce excessive false positives at small sample sizes (Yurdakul, 2018). KS-tests are less effective for high-dimensional LLM outputs. The most reliable approach for 5–10 new examples per week is **perplexity monitoring on a fixed canary set** of 50–100 curated, representative examples, independent of incoming data volume.

Financial language drift is **regime-based, not gradual**. Research on semantic shift in financial NLP (arXiv:2510.00205) found that models struggle to generalize across macroeconomic regime changes (pre-COVID, COVID, post-COVID, rate-hike). Vocabulary, tone, and contextual cues can shift within days of major policy announcements. This means the retraining trigger framework must include regime-change detection alongside statistical monitoring.

The recommended hybrid trigger framework combines four signals:

- **Canary-set perplexity** (primary): Flag retraining when perplexity increases >8% from post-training baseline for 2+ consecutive weekly evaluations. Requiring persistence across two evaluations reduces false alarm rates to an estimated <10%.
- **Example accumulation** (minimum gate): Don't retrain unless ≥20 new labeled examples have accumulated since the last training cycle.
- **Time-based ceiling**: Always retrain after 6 weeks maximum, regardless of other triggers, to prevent silent degradation.
- **Regime-change override**: Trigger immediate retraining when VIX spikes >30% weekly, a new monetary policy regime begins, or new regulatory terminology enters the discourse.

---

## Detecting improvement with fewer than 50 trades requires paired testing

The champion-challenger evaluation faces a stark statistical reality. The expected effect size of adding 5–10 examples to a 1,722-example model is approximately **Cohen's d < 0.05** — well below the "small" threshold of 0.20. With 50 paired observations at 80% power and α = 0.05, the minimum detectable effect is **d ≈ 0.40**. This represents an **8× gap** between the expected and detectable effect sizes, meaning individual small updates are fundamentally unverifiable.

Anthropic's "Adding Error Bars to Evals" (Miller, arXiv:2411.00640, November 2024) establishes paired-difference analysis as the gold standard for model comparison. With typical inter-model correlation of ρ = 0.3–0.7, pairing **reduces estimator variance by ~33%**, equivalent to getting 50% more evaluation questions for free. In their example, pairing reduced the Minimum Detectable Effect from **13.2% to 7.5%**. Their five recommendations: report standard errors via CLT, use clustered standard errors for grouped questions, reduce within-question variance through resampling (K=5 per prompt), always use paired differences, and conduct power analysis before deciding if an eval can detect the effect of interest.

For the binomial sign test on paired comparisons, the minimum win rates required for significance at α = 0.05 two-sided are:

| Pairs | Wins needed | Win rate required |
|-------|-------------|-------------------|
| 50 | ≥35 | 70% |
| 30 | ≥22 | 73% |
| 25 | ≥19 | 76% |
| 20 | ≥16 | 80% |

Below 6 discordant pairs, no result can reach significance regardless of the outcome.

LLM-as-judge achieves >80% agreement with human preferences (Zheng et al., 2023, MT-Bench) but suffers from documented biases: positional (favoring first-presented option), verbosity (preferring longer responses), and self-enhancement (favoring same model family). At <50 samples, mitigation requires position-swapping on every comparison, detailed domain-specific rubrics, ensemble judging with 2–3 different models, and chain-of-thought reasoning before scoring.

Canary-set perplexity as a proxy for trading performance is **necessary but not sufficient**. Research (arXiv:2504.12491) found conventional perplexity had prediction error rates **exceeding 60%** for downstream fine-tuning performance — worse than random guessing. Perplexity captures stylistic fit well but correlates poorly with reasoning quality, factual accuracy, and instruction-following. For equity commentary, a perplexity increase on domain-specific held-out data reliably signals regression, but a decrease does not guarantee improved commentary quality.

The practical evaluation protocol should be: track cumulative canary-set perplexity as a directional signal between monthly retrains, then run formal paired champion-challenger evaluation every **2–3 monthly retrains** (when ~80–120 new examples have been added), using LLM-as-judge with position-swapping on the full 50–100 example canary set. Only at this cadence will the accumulated effect size (~0.15–0.25) approach detectability.

---

## Curriculum re-sorting matters for initial training but not for monthly retrains

Trading-R1's three-stage curriculum (Xiao et al., arXiv:2509.11420) — Structure → Claims → Decision — was designed for initial training on Qwen3-4B, not for incremental updates. Each stage uses SFT warm-start followed by RL reinforcement, with capabilities deliberately stabilized before adding complexity. The paper does not address incremental example addition and explicitly notes that "excessive RL may erode structured reasoning."

The broader curriculum learning literature shows that ordering matters moderately for fine-tuning: maximum accuracy gains from curriculum reordering are approximately **1.77% per model** (arXiv:2408.07888). No single curriculum dominates — forward (easy→hard) versus reverse depends on model capacity, task complexity, and the difficulty metric used. LLM-defined difficulty consistently outperforms human-defined difficulty in curriculum design.

For the merge-and-reset monthly retrain, the practical recommendations are:

- **Do not automatically assign new examples to Stage 3.** Each new live trade example contains elements of all three stages (structure, evidence, decision). Classify new examples by which capability they primarily exercise — routine format compliance (Stage 1), grounded factual claims (Stage 2), or nuanced directional decisions under uncertainty (Stage 3).
- **Re-sort the entire corpus by difficulty each time** for the monthly full reset. Since the complete 1,722+ example corpus is retrained from scratch, re-sorting is computationally free and produces the modest but consistent gains the curriculum literature predicts. Use the current model's perplexity on each example as the difficulty metric — examples the model finds hardest go later in training.
- **For incremental mid-month retrains** (if triggered), curriculum ordering provides negligible benefit over the small 10–20 example batch. Simply shuffle and train.
- **Interleaved curriculum** (cycling through stages rather than strict sequential) sometimes outperforms blocked curriculum, with gains of up to +0.84%. Consider interleaving Stage 2 and Stage 3 examples rather than strict sequencing.

---

## The complete Saturday decision flowchart

Integrating all evidence into a single operational protocol for the weekly GPU window:

**Step 1 — Canary evaluation (run every Wednesday, ~5 minutes)**
Compute perplexity on the fixed 50–100 example canary set. Compare to the baseline established at the last retrain. Track the two-week rolling trend.

**Step 2 — Saturday decision tree**

```
START
│
├── Canary perplexity up >8% for 2+ consecutive weeks?
│   └── YES → RETRAIN (forced, full reset from original base)
│
├── Major market regime change since last retrain?
│   └── YES → RETRAIN (even with <20 new examples)
│
├── ≥6 weeks since last full reset from original Qwen3 8B?
│   └── YES → FULL RESET RETRAIN (mandatory maintenance cycle)
│
├── How many new examples accumulated?
│   ├── <10 → SKIP (insufficient new signal)
│   ├── 10–19 and contain novel patterns → RETRAIN (incremental merge)
│   ├── 10–19 and routine examples → SKIP (wait for more)
│   └── ≥20 → RETRAIN
│
├── If RETRAIN: Has it been ≥4 weeks since last full reset?
│   ├── YES → FULL RESET (from original Qwen3 8B base, all examples)
│   └── NO → INCREMENTAL (merge-and-reset LoRA)
│
└── After training: Re-run canary evaluation. 
    New perplexity becomes baseline for next cycle.
    Run paired champion-challenger every 3rd retrain.
```

**Step 3 — Training execution**
For full resets: Load original Qwen3 8B, train LoRA on entire corpus (1,722 + all new), save merged FP16 master copy. For incremental runs: Load current FP16 master in NF4, train LoRA on new examples plus a 20% random sample of old examples (~340 examples), merge into FP16 master.

**Step 4 — Backfill and live examples**
Mix all backfill and live examples together in the same training batch. If backfill examples are from a substantially different market regime, down-weight them to 0.7–0.8× relative to recent live examples (1.0×). During monthly full resets, include everything — original base, all backfill, all live — with no separate processing.

**Step 5 — DPO/GRPO transition milestones**
At **100+ preference pairs** with an RTX 3090: Begin piloting GRPO with a programmatic reward function (e.g., "did the commentary correctly identify the trade setup?"). GRPO requires only prompts plus reward functions, not labeled preference pairs, making it viable earlier. At **500+ preference pairs**: Add formal DPO as a second training pass after SFT (~30–45 minutes additional). The monthly cycle becomes: SFT full retrain (~1 hour) → DPO refinement (~30–45 minutes) = ~2 hours total, still fitting a Saturday window.

---

## Conclusion

The core insight across all seven research dimensions is that **this scenario's bottleneck is data accumulation rate, not compute**. At 5–10 new examples per week on a 1,722-example base, the system is operating deep in the diminishing-returns zone where individual updates are below the detection threshold of any practical evaluation methodology. The optimal protocol is monthly full-reset retraining (~30–50 new examples per cycle), with canary-set monitoring and regime-change triggers as override mechanisms. Experience replay is automatic in full-reset mode since the entire corpus is retrained. The champion-challenger evaluation should occur every 2–3 retraining cycles using paired LLM-as-judge comparisons with position-swapping. The single most impactful operational change is maintaining an FP16 master copy of the merged model and never allowing the canonical weights to exist only in NF4 form — this alone prevents the most severe degradation pathway documented in the quantization literature.
# The best local LLM for a financial analyst on an RTX 3060

**Qwen3 8B is the optimal starting point — and Qwen 2.5 14B is the stretch pick for maximum intelligence.** Both fit your RTX 3060 12GB, have Apache 2.0 licenses (unrestricted commercial use), lead the industry in fine-tuning responsiveness, and excel at structured output. The Qwen family dominates this decision because it's the only architecture that simultaneously wins on fine-tunability, writing quality, JSON reliability, and VRAM efficiency at your hardware tier. Deploy via Ollama, fine-tune with Unsloth using QLoRA, and expect to see meaningful improvement from as few as 500 high-quality training examples.

The broader context matters here: 2025 was a breakthrough year for small models. A fine-tuned Qwen3-4B now rivals what Qwen 2.5-72B could do out of the box. Trading-R1, the most relevant financial model for your exact use case, chose Qwen3-4B as its backbone — validating this architecture for institutional-quality trade thesis generation. Your 12GB VRAM is no longer a serious limitation for this class of work.

---

## The primary recommendation: Qwen3 8B at Q5_K_M

**Model file**: `qwen3-8b-instruct-q5_k_m.gguf` (~5.85 GB)  
**VRAM usage**: ~7.5 GB at 8K context, leaving **4.5 GB headroom** for KV cache expansion  
**Inference speed**: **35–40 tokens/sec** on RTX 3060 (Windows), ~45 tok/s on Linux  
**Context window**: 32K native, extendable to 131K with YaRN  
**License**: Apache 2.0 — fully unrestricted commercial use, fine-tuning, redistribution  
**Fine-tuning VRAM**: ~9–10 GB with QLoRA (batch=1, seq_len=2048) — **fits comfortably**

This is your daily driver. At Q5_K_M quantization, quality degradation is under 3% compared to full precision, and you get fast interactive speeds with plenty of VRAM headroom for longer contexts. The 8B size hits the sweet spot where fine-tuning is fast (1,000 examples in ~45 minutes on your RTX 3060), iteration cycles are tight, and you can experiment freely without hitting OOM errors.

**Why Qwen3 specifically over other 8B models**: In the Distillabs benchmark (2026) testing 12 models across 8 diverse tasks, Qwen3-4B-Instruct ranked #1 overall, outperforming every 8B model tested and even matching a 120B teacher model on 7 of 8 tasks after fine-tuning. The Qwen architecture shows the best *final performance* after domain adaptation — meaning your fine-tuned Qwen will be better than a fine-tuned Llama or Mistral of the same size. Qwen is also specifically noted for "high-fidelity JSON/table formatting," which matters for your structured output requirements.

---

## The stretch pick: Qwen 2.5 14B Instruct at Q4_K_M

**Model file**: `qwen2.5-14b-instruct-q4_k_m.gguf` (~9.0 GB)  
**VRAM usage**: ~10.7 GB at 8K context — **fits, but tight** (~1.3 GB headroom)  
**Inference speed**: **10–15 tokens/sec** on RTX 3060  
**Context window**: 128K native (practically limited to 4–8K tokens on 12GB VRAM)  
**License**: Apache 2.0  
**Fine-tuning VRAM**: ~10–12 GB with QLoRA (batch=1, seq_len=1024) — **feasible but at the edge**

Use this when you need the highest quality output and can tolerate slower generation. The 14B class represents the **absolute ceiling** of what fits in 12GB VRAM — both for inference and fine-tuning. The writing quality jump from 8B to 14B is substantial for analytical prose: longer coherent arguments, better risk/reward framing, more nuanced thesis construction. However, context is limited to ~8K tokens before VRAM spills to CPU, and fine-tuning requires aggressive memory management (batch_size=1, sequence length capped at 1024–2048, Unsloth's gradient checkpointing mandatory).

Why Qwen 2.5 14B rather than Qwen3 14B? For a fine-tuning-first workflow, Qwen 2.5 14B has a more mature ecosystem with more proven fine-tuning recipes and community results. Qwen3 14B is slightly newer and uses a hybrid thinking/non-thinking architecture that adds complexity during fine-tuning. Start with Qwen 2.5 14B for stability, migrate to Qwen3 14B once your fine-tuning pipeline is proven.

---

## Every model evaluated, ranked for your use case

The table below synthesizes VRAM fit, inference speed, fine-tuning feasibility, writing quality, and structured output reliability into a single ranking. Fine-tunability was weighted highest per your requirements.

| Rank | Model | Q4_K_M Size | Fits 12GB? | tok/s | QLoRA on 12GB? | Writing Quality | JSON Reliability | License |
|------|-------|------------|------------|-------|---------------|----------------|-----------------|---------|
| **1** | **Qwen3 8B** | 5.03 GB | ✅ Comfortable | 35–40 | ✅ Easy (~9 GB) | Excellent | Excellent | Apache 2.0 |
| **2** | **Qwen 2.5 14B** | 9.0 GB | ⚠️ Tight | 10–15 | ⚠️ Tight (~11 GB) | Outstanding | Excellent | Apache 2.0 |
| **3** | **Qwen 2.5 7B** | 4.9 GB | ✅ Comfortable | 38–42 | ✅ Easy (~9 GB) | Very Good | Excellent | Apache 2.0 |
| **4** | **Llama 3.1 8B** | 4.92 GB | ✅ Comfortable | 35–40 | ✅ Easy (~9 GB) | Very Good | Good | Llama Community |
| **5** | **DeepSeek-R1-Distill-Qwen-14B** | 8.95 GB | ⚠️ Tight | 10–15 | ⚠️ Tight (~11 GB) | Good (reasoning-focused) | Good | Apache 2.0 |
| **6** | **Phi-4** | 9.05 GB | ⚠️ Tight | 10–15 | ⚠️ Tight (~11 GB) | Good (analytical) | Good | MIT |
| **7** | **Mistral Nemo 12B** | 7.48 GB | ✅ Comfortable | 15–25 | ⚠️ Feasible (~10 GB) | Very Good | Good | Apache 2.0 |
| **8** | **Gemma 3 12B** | 7.20 GB | ⚠️ KV cache issue | 12–18 | ⚠️ Feasible (~10 GB) | Good | Moderate | Gemma ToU |
| **9** | **DeepSeek-R1-Distill-Qwen-7B** | 4.68 GB | ✅ Comfortable | 35–40 | ✅ Easy (~9 GB) | Moderate (verbose reasoning) | Moderate | Apache 2.0 |
| **10** | **Phi-4-mini** | 2.49 GB | ✅ Plenty of room | 60–80 | ✅ Very easy (~5 GB) | Moderate | Moderate | MIT |
| **11** | **Mistral 7B v0.3** | 4.1 GB | ✅ Comfortable | 35–45 | ✅ Easy (~8 GB) | Good | Moderate | Apache 2.0 |
| **12** | **Gemma 2 9B** | 5.76 GB | ✅ Comfortable | 30–38 | ⚠️ Special handling needed | Good | Moderate | Gemma ToU |

**Models explicitly NOT recommended for your hardware**: Llama 3.3 70B (42.5 GB, unusable at 1–2 tok/s), Llama 4 Scout (33.8 GB minimum, doesn't fit), Llama 4 Maverick (122 GB+), Qwen3-30B-A3B MoE (~18.6 GB, doesn't fit), Gemma 3 27B (~16.5 GB), any 32B+ dense model for interactive use.

---

## Quantization: the sweet spot is Q5_K_M for 8B and Q4_K_M for 14B

For your 12GB VRAM, the quantization decision is straightforward. At the **8B parameter class**, you have enough headroom to afford Q5_K_M or even Q6_K, which preserves nearly all model quality while keeping inference fast. At the **14B parameter class**, Q4_K_M is the only option that fits — and it works well, with quality degradation typically under 5% on benchmark tasks.

**The math on what fits**: VRAM usage = model file size + KV cache (~50–80 MB per 1K context tokens for 8B, ~120–150 MB per 1K for 14B) + ~0.5–1 GB CUDA overhead. So for Qwen3 8B at Q5_K_M (5.85 GB file), at 8K context you need roughly 5.85 + 0.5 + 0.5 = ~7 GB, leaving 5 GB headroom. For Qwen 2.5 14B at Q4_K_M (9.0 GB file), at 8K context you need roughly 9.0 + 1.0 + 0.7 = ~10.7 GB, leaving just 1.3 GB.

**If you want maximum quality from the 8B class**, run Qwen3 8B at Q8_0 (8.71 GB). It fits with ~8K context and delivers near-lossless quality. This is worth testing against Q5_K_M for your specific financial writing task — the difference in analytical precision may matter.

---

## Fine-tuning is the real game: Unsloth + QLoRA on your RTX 3060

Fine-tunability is your stated #1 priority, and this is where the recommendation gets concrete. **Unsloth is the only tool that makes 14B fine-tuning feasible on 12GB VRAM**, and it's the clear best choice at every model size.

**VRAM during QLoRA training (Unsloth, measured)**:

| Model | Base QLoRA VRAM | With seq_len=2048, batch=1 | Headroom on 12GB |
|-------|----------------|---------------------------|------------------|
| Qwen3 8B | ~6 GB | ~9–10 GB | ✅ 2–3 GB |
| Qwen 2.5 7B | ~5 GB | ~8–9 GB | ✅ 3–4 GB |
| Qwen 2.5 14B | ~8.5 GB | ~10–12 GB | ⚠️ 0–2 GB |
| Llama 3.1 8B | ~6 GB | ~9–11 GB | ✅ 1–3 GB |
| Phi-4 14B | ~8.5 GB | ~10–12 GB | ⚠️ 0–2 GB |

**Why Unsloth over alternatives**: Unsloth's custom Triton kernels deliver **2–5x faster training** and **up to 70–80% less VRAM** than standard HuggingFace implementations. Its "unsloth" gradient checkpointing mode shaves an additional 30% off VRAM usage at only ~2% speed cost. For 12GB VRAM, this isn't optional — it's the difference between training working and hitting OOM. Unsloth also provides one-click GGUF export, which means you can go from fine-tuned weights to a deployable Ollama model in a single command.

**Recommended LoRA hyperparameters for your use case**:

```python
# For initial fine-tuning (500-1,000 examples)
lora_config = {
    "r": 16,                    # LoRA rank — low to prevent overfitting on small data
    "lora_alpha": 32,           # Alpha = 2x rank (empirically validated sweet spot)
    "lora_dropout": 0.05,       # Light regularization for small datasets
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", 
                       "gate_proj", "up_proj", "down_proj"],
    "bias": "none",
}

training_args = {
    "per_device_train_batch_size": 1,     # Must be 1 on 12GB
    "gradient_accumulation_steps": 16,     # Effective batch size = 16
    "max_seq_length": 2048,                # 1024 for 14B models
    "num_train_epochs": 1,                 # Single epoch to avoid overfitting
    "learning_rate": 2e-4,
    "use_gradient_checkpointing": "unsloth",  # Critical VRAM savings
}
```

**Training time estimates on RTX 3060 12GB**:

| Dataset Size | 8B Model | 14B Model |
|-------------|----------|-----------|
| 500 examples | ~20–30 min | ~45–60 min |
| 1,000 examples | ~45–60 min | ~1.5–2 hours |
| 5,000 examples | ~3–4 hours | ~6–8 hours |
| 10,000 examples | ~5–7 hours | ~10–14 hours |

As your dataset grows, increase LoRA rank to 32–64 and alpha proportionally. With 5,000+ examples, you can drop dropout to 0.0 and potentially run 2 epochs.

---

## Financial domain strategy: how to build your training data

No off-the-shelf financial model does what you need. FinGPT excels at sentiment classification but produces poor generative writing. FinMA is based on dated LLaMA 1 architecture. BloombergGPT is proprietary. The most relevant model — **Trading-R1** (Tauric Research, September 2025) — uses a Qwen3-4B backbone and generates structured investment theses with entry/exit reasoning, which is almost exactly your use case. But it's trained on public equity data, not your proprietary trading system's feature set.

**The right approach is fine-tuning a strong general model on your own data.** Here's the specific strategy:

**Phase 1 — Bootstrap with synthetic data (weeks 1–2)**. Use GPT-4 or Claude to generate 500–1,000 example trade commentaries from your historical structured data. Feed each example your actual feature inputs (trend state, relative strength, pullback depth, ATR, etc.) and have the API model produce the kind of institutional-quality commentary you want. This gives your model a strong formatting and style foundation.

**Phase 2 — Incorporate real outcomes (weeks 3–8)**. As your trading system generates real data, create postmortem training examples. Each example should include the pre-trade feature data, the thesis that was generated, the actual outcome (P&L, max adverse excursion, holding period), and a structured analysis of what worked and what didn't. Include both winners and losers — the losing trades are more instructionally valuable.

**Phase 3 — Iterative reinforcement (ongoing)**. Retrain every 2–4 weeks as new outcome data accumulates. At 5,000+ examples, consider adding Direct Preference Optimization (DPO) — pair a good trade setup that worked with a similar-looking setup that failed, and train the model to prefer the winning pattern's reasoning.

**Training data format** — use instruction-tuning with consistent structured inputs:

```json
{
  "instruction": "You are a senior equity analyst. Analyze this setup and write a trade thesis with entry reasoning, risk analysis, and exit strategy.",
  "input": "Ticker: NVDA | Trend: Uptrend (confirmed) | RS vs SPY: +4.2% 20d | Pullback: 38.2% Fib retracement | ATR(14): $8.73 | Volume: 1.4x 20d avg | Support: $842 | Resistance: $920 | RSI(14): 54.8 | Sector: Technology (leading) | Macro: Fed hold, yields declining",
  "output": "## NVDA Long — Pullback Entry in Confirmed Uptrend\n\n**Thesis**: NVIDIA presents a textbook continuation setup..."
}
```

**Critical implementation details**: Always present pre-computed indicators rather than asking the model to calculate them — small LLMs struggle with numerical computation. Randomize the order of features occasionally in training to prevent positional memorization. Keep the input format identical between training and inference.

**Minimum viable dataset**: Research shows **50–100 examples** are sufficient for the model to learn your output format and writing style (one study demonstrated 96% formatting accuracy from just 50 examples on Phi-3-mini). **500–1,000 examples** produce meaningful domain adaptation. **5,000–10,000 examples** reach production quality. Trading-R1 used 100K examples for full thesis-generation capability, but your narrower domain needs fewer.

---

## Deploy with Ollama for the simplest Python integration

**Ollama is the recommended deployment option.** It runs natively on Windows 11, auto-detects your RTX 3060's CUDA, serves an OpenAI-compatible API, and handles GPU memory management automatically. Setup takes under 5 minutes.

```python
# Install: pip install openai
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

response = client.chat.completions.create(
    model="qwen3-8b",
    messages=[{"role": "user", "content": prompt}],
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "trade_thesis", "schema": your_schema}
    }
)
```

Ollama's structured output support is first-class — pass a Pydantic schema and get guaranteed schema-compliant JSON every time, powered by grammar-constrained decoding from llama.cpp underneath. This eliminates the need for post-processing JSON parsing hacks.

**To deploy your fine-tuned model**: After exporting from Unsloth to GGUF, create an Ollama Modelfile (`FROM ./my-finetuned-qwen3-8b.Q5_K_M.gguf`) and run `ollama create my-financial-model -f Modelfile`. Your custom model is now accessible through the same API.

**Alternative for lowest latency**: If you're building a tight Python pipeline where every millisecond matters, **llama-cpp-python** embeds the model directly in your Python process — no HTTP overhead, no separate server. It gives ~5–10% faster inference and the most powerful grammar-based JSON constraints. The trade-off is more manual setup and model management.

**Skip vLLM** for this setup. It doesn't support GGUF, requires WSL2 on Windows, can't do partial CPU offloading, and pre-allocates VRAM aggressively — all dealbreakers for 12GB VRAM.

---

## What about the models you specifically asked about?

**Llama 3.1 8B**: Excellent #2 choice. The most battle-tested fine-tuning ecosystem and highest "tunability" (largest improvement from base to fine-tuned). Slightly behind Qwen on final post-fine-tuning quality and JSON reliability. Llama Community License is fine for commercial use unless you have >700M monthly active users. If you're nervous about picking Qwen, Llama 3.1 8B is the safe fallback.

**Llama 3.3 70B / Llama 4 Scout / Maverick**: All impossible on your hardware. Llama 3.3 70B at Q4_K_M is 42.5 GB — even with 64GB RAM offloading, you'd get 1–2 tok/s, making it unusable. Llama 4 Scout needs minimum 24GB VRAM even at extreme quantization. Skip entirely.

**Mistral 7B and Mistral Nemo 12B**: Solid models with Apache 2.0 licenses. Mistral Nemo 12B at Q4_K_M (7.48 GB) fits comfortably and delivers **15–25 tok/s** — a good middle ground between 8B speed and 14B quality. However, Qwen outperforms both on fine-tuning benchmarks and structured output.

**Phi-3 Mini and Phi-4**: Phi-4 (14B, MIT license) has the **best mathematical reasoning** at this parameter count — it outperforms DeepSeek-R1-Distill-70B on math benchmarks. If your trade analysis is heavily quantitative (calculating risk/reward ratios, probability-weighted outcomes), Phi-4-reasoning is worth testing alongside Qwen. Phi-3 Mini (3.8B) demonstrated **96% accuracy** on financial classification tasks after fine-tuning versus GPT-4o's 80% — remarkable for such a small model. Consider it for a lightweight, fast classifier component in your pipeline.

**Gemma 2 9B and Gemma 3 12B**: Gemma 3 12B is multimodal with 128K context, but has an architectural quirk: its sliding-window attention causes unusually high KV cache memory usage (~12.4 GB at 8K context), making it barely fit your VRAM. Gemma 2 9B has a softcapping mechanism that disables Flash Attention, causing quadratic memory scaling. Both work but require special handling that Qwen and Llama models don't need.

**DeepSeek-R1 distilled models**: The R1-Distill-Qwen-14B fits at Q4_K_M and brings strong chain-of-thought reasoning. It generates `<think>...</think>` blocks showing its work, which could be valuable for transparent trade reasoning. However, it tends toward verbose reasoning chains and is optimized for reasoning tasks rather than polished analytical writing. Better suited as a secondary model for complex analytical problems.

**Nous-Hermes variants**: These are fine-tuned versions of base models (typically Llama or Mistral). OpenHermes 2.5 (based on Mistral 7B) is well-regarded for instruction following, but you'll get better results fine-tuning the latest Qwen3 on your own data than using a general-purpose fine-tune from 2024.

**Financial domain models (FinGPT, FinMA, etc.)**: FinGPT v3.2 (LLaMA2-7B base) achieves F1 of 87.6% on financial sentiment but scores only 28.5% on Financial QA and nearly 0% on summarization — it's a classification tool, not a writer. FinMA-7B is based on outdated LLaMA 1. Neither produces the institutional-quality analytical prose you need. The most relevant model is **Trading-R1** (Qwen3-4B backbone, September 2025), which generates structured investment theses — but it's trained on public market data, not your feature set. Use it as inspiration for your training data format, not as a drop-in solution.

---

## Conclusion: the path from decent to progressively better

Your optimal setup is **Qwen3 8B at Q5_K_M deployed via Ollama, fine-tuned with Unsloth using QLoRA**. This combination maximizes the feedback loop speed: fast inference (~37 tok/s) for testing, fast training (~45 minutes for 1,000 examples), comfortable VRAM margins for experimentation, and the best post-fine-tuning quality of any architecture in this size class.

Start by generating 500 synthetic training examples using GPT-4/Claude from your historical trade data. Fine-tune, evaluate the output quality, iterate on your training data. Within 2–4 weeks you should have a model that reliably produces trade commentary in your voice. As real outcome data accumulates, retrain biweekly — the model will progressively learn which setups lead to profitable trades and which don't.

When you've validated your pipeline and want more quality, switch to **Qwen 2.5 14B at Q4_K_M** for the final production model. The 14B class produces meaningfully better analytical writing but requires more careful VRAM management during both inference and training. Keep the 8B model for rapid iteration and experimentation.

The key insight from 2025's financial LLM research is that **data quality dominates model size**. A well-fine-tuned 8B model with 5,000 curated trade examples will outperform an untuned 70B model on your specific task. Your competitive advantage comes from proprietary training data, not from raw parameter count. The RTX 3060 12GB is genuinely sufficient for this — the constraint is building excellent training data, not hardware.
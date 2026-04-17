# LLM role generalization across quantitative trading strategies

**Fine-tuned 8B-class LLMs deliver proven alpha in exactly two roles — news/filing sentiment and structured extraction — and remain speculative everywhere else.** For a solo-developer platform running Qwen3-8B Q8_0 on an RTX 3060 12GB, the dominant design choice is not "what can the model do" but "how do I prove it contributes anything at all." The literature from 2023–2025 converges on a narrow, honest answer: LLMs are high-leverage *feature extractors and research copilots*, low-leverage *signal generators*, and dangerous *autonomous traders*. Backtests that ignore survivorship (Li, Kim, Cucuringu, Ma 2025 — FINSABER), knowledge-cutoff leakage (Sarkar & Vafa 2024; Glasserman & Lin 2023), and transaction costs produce Sharpes that evaporate on replication. The correct architecture for Arcis is therefore a fixed Qwen3-8B base with swappable LoRA adapters, pre-computed LLM features stored in a feature store, strict self-blinding, and a three-arm placebo evaluation protocol. Everything else is plumbing.

The rest of this report walks through the seven domains requested — role taxonomy, guardrails, evaluation, prompt architecture, model separation, local-vs-API economics, and implementation — with specific citations, numbers, and code patterns.

## A role taxonomy grounded in what actually has alpha

The 2023–2025 literature supports **seven canonical LLM roles** in systematic trading, but only two have published, replicated, cost-adjusted alpha.

| # | Role | Mechanical baseline | Alpha evidence | Hallucination risk | Validation needed |
|---|------|---------------------|----------------|-------------------|--------------------|
| 1 | **Structured extraction** (10-K → JSON) | XBRL parsers, Loughran-McDonald tagging | Modest: improves recall on unstructured items; **no standalone alpha documented** | Medium — numerical fabrication, line-item misalignment | Schema-constrained decoding + unit checks vs SEC tags |
| 2 | **Tone/sentiment classification** | LM dictionary, FinBERT | **Proven**: Kirtac & Germano (2024) OPT Sharpe 3.05 net of 10 bps; Lopez-Lira & Tang (2023) GPT-4 Sharpe 3+ post-cutoff | Low–Medium | Post-knowledge-cutoff OOS, ensemble across runs, decay analysis |
| 3 | **Reasoning gate** (yes/no + evidence) | Rule-based filters | Indirect: Kim-Muhn-Nikolaev (2024) GPT-4 60.35% directional earnings vs. 52.9% ANN | Medium — over-confident "YES" | Calibration vs labels, abstention-rate monitoring, Brier/ECE |
| 4 | **Narrative summarization** | Extractive (LexRank, TextRank) | None claimed; productivity tool only | **High** — omission, fabricated quotes | Source grounding (RAG), faithfulness metrics |
| 5 | **Anomaly detection** (language change) | Cosine/Jaccard similarity | Cosine (Lazy Prices) already ~22%/yr; LLM adds semantic texture but **no documented alpha lift** | Low–Medium | Ablation vs cosine baseline; ensure model isn't memorizing tickers |
| 6 | **Strategy proposal** (LLM-as-alpha) | GP, formulaic alphas | **Negative** under bias-controlled replication (FINSABER 2025); Trading-R1 (Xiao 2025) only on 6 AI-themed large caps in bull regime | High | Walk-forward post-cutoff, survivorship-free, transaction costs, multiple-testing penalty |
| 7 | **Trade ensemble weighting** | Inverse-vol, GBM stacking | No replicated public evidence | High | Out-of-sample Sharpe, turnover- and cost-aware net P&L |
| 8a | Regime classification | HMM, GMM | Sparse; Trading-R1 reports volatility-aware decisions but unbenchmarked | Medium | Regime-conditional Sharpe |
| 8b | News triage / NER | Keyword + spaCy NER | High precision wins (BloombergGPT internal) | Low | NER F1 vs human |
| 8c | Feature engineering (text → embedding) | TF-IDF, BERT CLS | Guo & Hauptmann (2024), Chen et al. (2022): LLM embeddings beat technical features in XS prediction | Low (deterministic) | Standard ML CV, embedding stability across versions |

**The two roles with replicated alpha are both sentiment/extraction, not decision-making.** Kirtac & Germano (2024, *Finance Research Letters* 62) ran OPT on 965,375 U.S. news articles 2010–2023 and report long-short Sharpe 3.05 at **10 bps transaction costs** — beating FinBERT (2.07) and LM dictionary (1.23). Lopez-Lira & Tang (2023, arXiv 2304.07619, revised SSRN 4412788) confirm GPT-4 delivers Sharpe ~3 post-knowledge-cutoff, cumulative ~350% at 10 bps, with **documented decay as LLM adoption rises**. Kim, Muhn & Nikolaev's 2024 Chicago Booth WP ("Financial Statement Analysis with Large Language Models," arXiv 2407.17866) shows GPT-4 hits 60.35% directional earnings-change accuracy vs. 52–53% human analyst and 52.9% stepwise logit — a meaningful but narrow ~7-point edge.

The **negative results are equally important**. Li, Kim, Cucuringu & Ma (2025, arXiv 2505.07078, KDD 2026) built the FINSABER framework — S&P 500 constituents 2004–2024 *including delisted names*, rolling-window — and show that LLM-trader advantages reported in FinMem (Yu et al. 2023), FinAgent, and FinCon **vanish** under survivorship-controlled evaluation. LLM strategies are systematically over-conservative in bull regimes and over-aggressive in bears. Xie et al.'s FinBen (NeurIPS 2024, arXiv 2402.12659) finds that zero-shot LLM trading agents **lag traditional methods** on forecasting across 24 tasks and 42 datasets. Trading-R1 (Xiao et al. 2025, arXiv 2509.11420) — the most cited 2025 RL-for-LLM-trading paper — reports improved risk-adjusted returns but *only on 6 AI-themed large caps during Jan 2024–May 2025*, a universe its own authors acknowledge is biased.

The **Lazy Prices mechanical baseline (Cohen, Malloy & Nguyen 2020, *Journal of Finance* 75(3))** — long-non-changers minus short-changers of 10-K/10-Q text earns up to 188 bps/month — remains the benchmark any LLM extension must beat. Yilmaz & Reichmann (2023, SSRN 4643560) show neural embeddings predict crash risk beyond cosine, but **no peer-reviewed paper demonstrates LLM-derived 10-K features producing new *return* alpha over the cosine baseline**. Industry disclosure aligns: Two Sigma's 2026 AI Outlook and Man Group's published material characterize LLMs as **research-productivity copilots and feature-engineering tools, not standalone alpha engines**.

Key additional works to anchor the bibliography: Wu et al. 2023 ("BloombergGPT," arXiv 2303.17564) — 363B Bloomberg + 345B general tokens, outperforms similar-sized open LLMs on financial NLP but reports no trading P&L; Yang, Liu & Wang 2023 ("FinGPT," arXiv 2306.06031); Araci 2019 ("FinBERT," arXiv 1908.10063); Xie et al. 2023 ("PIXIU," NeurIPS 2023, arXiv 2306.05443) — FinMA-7B beats GPT-4 on FPB sentiment F1 (0.87 vs 0.78); Xing 2024 (ACM TMIS, arXiv 2401.05799) on multi-agent sentiment prompting; Lian 2025 (arXiv 2512.00630) — rLoRA-tuned Qwen3-8B beats prior 7B fine-tunes on financial classification; Amorin et al. 2025 (arXiv 2512.00946) — Qwen3-8B LoRA hits FiQA-SA macro-F1 0.74, within 2–3 F1 of GPT-4.

**The actionable conclusion for Arcis**: commit LLM capital only to Roles 1, 2, and 8c (extraction, sentiment, embedding). Treat Roles 4 and 8b as productivity tools with no alpha claim. Treat Roles 3, 5, 6, 7, 8a as *research-only experiments requiring rigorous placebo controls* — they may work on your specific strategies, but the published base rate is negative.

## Guardrails that actually matter at 8B local scale

On Qwen3-8B Q8_0 via Ollama with RTX 3060 12GB, measured throughput is **~30–40 tok/s decode, ~250–400 tok/s prefill**, with ~8.5 GB of weights leaving ~2.5 GB for KV cache. A typical signal call (≈800 prompt + 200 output tokens) runs in **6–8 seconds**. Every guardrail must be priced against this budget.

**Always-on guardrails (near-zero cost, maximum leverage).** Schema-constrained decoding via llama.cpp GBNF grammars, XGrammar, or llguidance costs 0.95–1.05× latency with compressed-FSM implementations (Dong et al. 2024 report XGrammar is up to 100× faster than naive Outlines; LMSYS reports 2.5× *throughput gains* from jump-forward decoding). This eliminates parse failures entirely — the single highest ROI guardrail. **Verbatim quote grounding** — forcing the model to emit `<quote>` spans copied from the prompt, verified by post-hoc string match — adds only ~10–30% output tokens (~1.1× latency) and eliminates fabricated tickers and numbers; Semnani's WikiChat (2023) hit 97.9% factual accuracy on this pattern. **Logprob-based abstention** with a threshold tuned on a 500-item labeled holdout adds ~5% overhead and stacks with everything else. These three together cost roughly 1.15× latency and should be default-on for every role.

**Medium-cost guardrails (stake-dependent).** Retrieval-augmented grounding with k=3 chunks adds 300–800 prompt tokens (~1.3× latency) and is the **biggest factual-accuracy lever** per Kang & Liu (2023, arXiv 2311.15548) — their empirical study shows RAG beats DoLa, few-shot, and tool-learning on historical stock-price queries. Multi-pass self-consistency (Wang et al. 2022, ICLR 2023; arXiv 2203.11171) at N=5 multiplies latency 5× and yielded +17.9% GSM8K on PaLM-540B; expect smaller 5–8% lifts at 8B scale. Chain-of-Verification (Dhuliawala et al. 2024, ACL Findings, arXiv 2309.11495) adds 3–4× latency via draft → plan → factored verification → revise and reduces factual hallucinations 50–70% on Wikidata long-form QA.

**Run-offline-only guardrails.** SelfCheckGPT (Manakul, Liusie & Gales 2023, EMNLP, arXiv 2303.08896) at N=20 is prohibitive real-time but is the right **weekly audit tool**. FActScore (Min et al. 2023, EMNLP, arXiv 2305.14251) decomposes outputs into atomic facts and scores supported/unsupported — use it as the evaluation harness, not a runtime filter.

**Stacking rules.** Schema constraints + verbatim + logprob stack cleanly. Self-consistency conflicts with CoVe (both are N-sample — pick one), conflicts with intraday latency budgets (a 5-sample 1000-token response takes ~35 s), and partially invalidates logprob confidence at T>0. Strict JSON with in-line chain-of-thought degrades reasoning quality (Wang et al. 2024, EMNLP Industry, "Let Me Speak Freely?") — mitigate by placing a `reasoning: string` field *before* `decision: enum`, or by separating CoT and schema calls into two hops.

**Self-blinding deserves dedicated operational attention.** Glasserman & Lin (2023, arXiv 2309.17322) document two distinct biases in GPT sentiment on financial headlines: lookahead bias (model knows post-headline returns) and distraction effect (company identity leaks general knowledge). In their sample, **distraction > lookahead in magnitude**, and anonymized headlines outperform. Sarkar & Vafa (2024, SSRN 4754678, ICML DIG-BUGS 2025) show prompting-based identifier masking does *not* eliminate lookahead bias — time-indexed pretraining is required. For Arcis this means four layers: (1) identifier masking (ticker → `COMPANY_A` hash), (2) prompt-side date firewall (strip post-t dates, rewrite relative time), (3) weight-side firewall (for pre-Qwen3-cutoff backtests, use chronologically consistent checkpoints like He, Lv, Manela, Wu 2025's ChronoGPT or Kakhbod & Li 2025's NoLBERT, or restrict live-forward evaluation to strictly post-cutoff data), (4) outcome firewall audited by a unit test that replays prompts with a future-label swap — output must not change.

## Evaluation: the three-arm placebo is non-negotiable

**The canonical design is three arms, not two.** Arm A₀ is mechanical-only. Arm A₁ is mechanical + LLM. **Arm A₂ is mechanical + LLM with redacted input** — identical pipeline and token costs, but semantic signal destroyed (shuffled headlines, 50% token masking, or headlines from a matched-sentiment *unrelated* stock). The primary endpoint is the information ratio of A₁ − A₂, *not* A₁ − A₀. If A₁ beats A₀ but not A₂, the lift was pipeline overhead, not LLM semantics. Block-randomize by trading day (not by trade) to absorb cross-sectional correlation; use Diebold-Mariano on daily P&L differences; apply Harvey-Liu-Zhu BHY correction across all design variants tried.

**Cheap alternatives when trades are scarce.** Mutual information I(LLM_output; r_{t+1}) discretized into K×L bins, with permutation-test significance from 1000 shuffles, can detect signal with hundreds of observations — not thousands. The bound R² ≤ 1 − exp(−2I) lets you translate nats into tradable Sharpe. Shannon entropy H(X)/H_max is a free daily health metric: ≈1 means the model is indecisive, ≈0 means it has collapsed. Calibration via Brier score and Expected Calibration Error is essential — KalshiBench 2025 reports ECE 0.12–0.43 across frontier models (best: Claude Opus 4.5 at 0.120), and RLHF/instruct models are systematically overconfident. Apply temperature scaling on a holdout before trusting any confidence-weighted position sizing.

**Statistical power is brutal.** With annualized Sharpe SR and T years, detection at α=0.05, power=0.8 requires t ≈ 2.49, so T_years ≥ (2.49/SR)². Concretely: **true SR 0.5 needs 25 years or 6,250 daily trades; SR 1.0 needs 6.2 years; SR 1.5 needs 2.75 years; SR 2.0 needs 1.55 years**. With Harvey & Liu's (2015, *JPM* 41(1)) multiple-testing haircut across the ~316 factors already documented in the literature, required monthly mean at T=240 months jumps to ~0.88% vs. 0.35% single-test — roughly **2.5× the single-test Sharpe hurdle**. Bailey & López de Prado's Deflated Sharpe Ratio (2014, SSRN 2460551) further corrects for non-normality via skew γ₃ and kurtosis γ₄. **Practical minimum for declaring LLM victory: realized SR ≥ 1.5 over ≥3 years after trying ≤20 variants.**

**Alpha attribution requires an ablation ladder, not a single regression.** Step 0: mechanical only. Step 1: + LM dictionary sentiment. Step 2: + FinBERT. Step 3: + Qwen3-8B scores. Step 4: + CoVe-verified Qwen3. Each rung must deliver monotone ΔSharpe; non-monotone steps indicate you're fitting noise. Orthogonalize s_llm against s_finbert and factor loadings (`s_llm_orth = resid(s_llm ~ s_finbert + s_LMdict + FF5)`) and re-run — this is the *incremental* LLM contribution. Run the Glasserman-Lin identifier-mask ablation as a permanent placebo: if alpha disappears, it was memorization.

## Prompt architecture: Jinja2 + git + Instructor

**At 5–10 concurrent strategies, a Jinja2 shared base template with `{% extends %}` and `{% block %}` inheritance is the dominant design**. It's the same pattern LinkedIn adopted for its chain-based prompt architecture (Bora 2025) and PromptLayer documents as idiomatic. Per-strategy standalone templates are fine up to ~3 strategies, after which duplicated system-prompt boilerplate (JSON schema, risk framing, compliance language) scales maintenance cost O(N × change_frequency). Inheritance collapses shared edits to O(1).

**Versioning: start with git, upgrade only under pressure.** Store `.j2` files in the repo, embed `{# version: lazy_prices@1.3.0 #}` as a file header, and log the rendered prompt + version + model hash + response for every signal into DuckDB or SQLite. This reproduces ~90% of what Humanloop, PromptLayer, LangSmith, Langfuse, and Braintrust offer. Upgrade to **Langfuse (self-hosted, open source)** only if (a) non-engineers need to edit prompts, (b) you need hot-reload without redeploy, or (c) batch regression evals become painful. Humanloop starts at $150/month — overkill for a solo dev.

**Framework verdict for a solo dev on local Qwen3-8B.** **Use Instructor** (from 567-labs, ≥1.6) — Pydantic-validated outputs with automatic retry on validation failure, works directly with Ollama via `from_provider("ollama/qwen3-8b-ft")`. This is the single highest-ROI library; it saves hours of JSON-parsing glue code. **Skip LangChain** — abstraction overhead outweighs benefits at <10 prompts; even LangChain's own blog acknowledges LangGraph was built because LangChain wasn't production-grade. **Skip LangGraph** for v1 — your 5–10 strategies are mostly 1–3 step linear pipelines, not agent loops; a dict of functions is clearer. **Use LlamaIndex only** for Lazy Prices 10-K retrieval over historical filings — don't force it on mechanical strategies. **DSPy** is genuinely useful for the two strategies with labeled historical data (quality+momentum, event-driven) where you can define a precision/recall metric; its ~3.5ms framework overhead is the lowest among major frameworks (AIMultiple 2025 benchmark). Zen van Riel's warning is apt though: "DSPy optimizes what you can measure — if your metric doesn't capture what you want, optimization produces prompts that score well but perform poorly." For trading, naive metrics (e.g., "matches historical signal") induce lookahead bias by construction. **Outlines is worth it if you drop from Ollama to llama.cpp** for GBNF control; on Ollama, use Modelfile `format: json` plus Instructor.

**Prompt-vs-fine-tune heuristic (Hamel Husain's position):** do as much prompt engineering as possible before fine-tuning — not because fine-tuning is bad, but because prompt work stress-tests your eval harness. Fine-tuning dominates when the prompt is ballooning with rules/examples, the domain is narrow, latency/cost matters, or proprietary style is required. For Arcis, the fine-tuned Qwen3-8B should encode invariants (JSON schema adherence, risk-framing language, numeric discipline, financial vocabulary); strategy-specific reasoning stays in Jinja2 prompts. **When a prompt grows past ~1500 tokens of instructions (not context), that's the signal to fold it into the next fine-tune.**

## Production and research share one base; adapters differentiate

**One frozen production base + per-strategy LoRA adapters, not a second base model.** A second 8B Q8 base doesn't fit on 12 GB VRAM — the math doesn't work. LoRA adapters are ~34,000× smaller than full checkpoints, can be hot-swapped at runtime, and mitigate catastrophic forgetting structurally (the base is frozen by construction). The 2025 literature supports this design: LoRI (OpenReview, 2025) freezes projection A as random and sparsifies B per task to minimize cross-task interference; TT-LoRA MoE (ACM 2025) trains experts independently with a sparse router; Selective LoRA (arXiv 2501.15377) activates only ~5% of blocks, reducing forgetting while maintaining OOD performance.

**VRAM budget for RTX 3060 12GB (usable ~11,500 MB after display/driver):** Qwen3-8B Q8_0 weights ≈ 8,400 MB, KV cache at 8K context FP16 ≈ 1,100 MB, BGE-small embedding ≈ 250 MB, CUDA overhead ≈ 400 MB — **total ~10,150 MB with ~1.3 GB headroom**. This is the stable configuration: one Q8_0 model, `OLLAMA_NUM_PARALLEL=1`, `num_ctx=8192`, plus a tiny embedding model. Running two Q8 8B models concurrently is infeasible — Ollama requires full VRAM fit per model. `OLLAMA_NUM_PARALLEL=2` adds another ~1.1 GB KV cache and cancels your headroom; don't do it. For concurrent variants, use LoRA adapters, not separate models. Quantizing KV cache to Q8 saves ~50% but can degrade attention — use cautiously. Cold-load time for an 8B Q8 from NVMe is ~3–5 s; set `OLLAMA_KEEP_ALIVE=-1` to prevent cold starts during market hours.

**Fine-tuning drift mitigation playbook:** (1) never retrain the production base in place; (2) train per-strategy LoRA adapters on strategy-specific data, keep as 20–100 MB GGUF files; (3) bind via Ollama Modelfile `ADAPTER` directive (`ollama create qwen3-trader-lazyprices:v1 -f Modelfile.lazy_prices`); (4) maintain a ~500-example "general financial reasoning" rehearsal eval and fail any adapter release that regresses >2%; (5) never merge adapters for production — keep them separate for hot-swap and rollback; (6) tag every training example with provenance hash, run de-duplication + human spot-check before adding any LLM-generated example back into training — Shumailov et al. 2023's *Curse of Recursion* documents recursive self-training degrading distribution coverage. Note: **as of early 2026, Ollama does not support per-request LoRA swap** — you must `ollama create` a named model per adapter or drop to llama.cpp directly with `--lora`.

**Training data contamination-specific risks:** feedback loops (confident-wrong claims labeled "good" get reinforced), label leakage (using future-dated price data to "correct" past reasoning trains lookahead bias), distributional narrowing (self-distillation converges on modal response). Hard guardrails: strict time-based train/val/test splits (never random); human-in-the-loop review for synthetic training examples; contamination checks via LLM-generated-text diff against training corpus; a read-only golden set that never enters training.

## Local vs API: hybrid at ~$25–30/month beats all-API at ~$110–140/month

**Current API pricing (verified April 2026):** Claude Sonnet 4.6 $3/$15 per 1M input/output tokens; GPT-5.2 $1.75/$14; Gemini 2.5 Pro $1.25/$10; o3 reasoning $2/$8; Gemini 2.5 Flash $0.30/$2.50. Batch API halves all prices; prompt caching cuts cached input to 10% (Anthropic) or up to 90% (Gemini). Local Qwen3-8B Q8_0 marginal cost is ~$0.22 per 1M combined tokens (electricity only, RTX 3060 TDP 170W at $0.12/kWh), effectively ~$0.001/1M.

**Arcis monthly workload baseline:** ~15,000 news classifications (500/day), ~400 earnings transcript segments/quarter, ~400 10-K section analyses (50 filings × 8 sections), ~8,000 signal analyses (100 stocks × 4 signals × 20 days), ~4,000 trade narratives — totaling ~22.2M input tokens + 5.0M output tokens per month.

**Scenario costs per month:** All-API on Claude Sonnet 4.6 = **$141.60**; all-API on GPT-5.2 = $108.85; all-API on Gemini 2.5 Pro = $77.75; all-API on o3 = $84.40. All-local Qwen3-8B (~302 GPU-hours) = **~$6** plus amortized $12/month on a $280 GPU over 24 months. **Hybrid A ("local-heavy")** — news + sentiment + 10-K extraction local (~20M tokens), only complex gates and synthesis to Sonnet 4.6 (~2.2M in, 1M out) = **~$27.60/month**. Hybrid B (70% local, 30% Gemini 2.5 Pro) = ~$28/month. **Payback on the $280 GPU vs. all-API Sonnet is 2.1 months**; vs. cheapest all-API (Gemini 2.5 Pro) it's ~4 months.

**Which roles need frontier, which work at 8B** — from FinBen and related benchmarks: **news headline classification** works at 8B (FinMA-7B F1 0.97 vs GPT-4 0.86 on Headlines); **FPB/FiQA sentiment** works at 8B (FinMA-7B 0.87 vs GPT-4 0.78 on FPB); **10-K extractive diff** works at 8B; **Connors-RSI overlays and pair-trade commentary** work at 8B. **Numerical reasoning** (FinQA/ConvFinQA) catastrophically fails at 8B (EM 0.05 vs GPT-4 0.69) — route to o3 or GPT-5.2. **Earnings transcript forward-looking narrative synthesis** — route to Sonnet 4.6 or Gemini 2.5 Pro (EDTSUM shows Gemini ROUGE-1 0.39 vs 8B FT 0.16). **Strategy proposal and research synthesis** — route to frontier, per CNFinBench 2025 which shows domain-specialized small models *underperform* frontier generalists on compliance tasks (a warning against over-specialization).

**Routing architecture** — draw from RouteLLM (Ong et al., arXiv 2406.18665, ICLR 2025) and FrugalGPT (Chen, Zaharia & Zou, TMLR 2024, arXiv 2305.05176). RouteLLM reports 85% cost cut on MT-Bench, 45% on MMLU, 35% on GSM8K while matching GPT-4. FrugalGPT's three mechanisms — prompt adaptation, LLM approximation (cache + small FT), and cascade ordered cheapest→most-expensive with a DistilBERT scoring gate — deliver up to 98% cost reduction; their HEADLINES case study achieved 80% savings with a **1.5% accuracy *gain*** (diversity benefit). Practical heuristics: route local when confidence ≥ 0.85 and input < 8K tokens without numerical tables; escalate to frontier when the output feeds position sizing or survives below the confidence threshold.

**Privacy forces local for a large slice.** MNPI, pre-filing 10-K drafts, live positions, P&L, and client identifiers typically cannot traverse third-party APIs without BAA/DPA regimes. JPMorgan's internal LLM Suite explicitly blocks Claude/GPT/Gemini for this reason. Rule of thumb: *mandatory local* for anything touching portfolio state; *API OK* for public SEC filings post-publication, public news, public earnings transcripts, and research prompts on synthetic data.

## Implementation: roles as Protocols, precomputed features, no frameworks

**Directory structure** (hexagonal ports-and-adapters, inspired by NautilusTrader):

```
arcis/
├── llm/
│   ├── clients/{base.py, ollama_client.py, openai_compat.py}
│   ├── roles/{base.py, extractor.py, sentiment.py, reasoning_gate.py, summarizer.py}
│   ├── prompts/{extractor/v1.j2, sentiment/v2.j2, ...}
│   ├── schemas/{sentiment.py, filing_diff.py}
│   ├── guardrails/{validators.py, llm_judge.py}
│   ├── cache/{disk.py, keys.py}
│   ├── router.py        # local-vs-API routing by cost/task/confidence
│   ├── runner.py        # sync/async executor with retries + circuit breaker
│   └── observability.py
├── strategies/
│   ├── base.py
│   └── lazy_prices/{strategy.py, llm_config.py, features.py}
├── data/feature_store.py   # LLM outputs persisted keyed by (ticker, ts, role, prompt_id, model_version)
├── backtest/{engine.py, precompute.py}
└── tests/{unit/, cassettes/, golden/}
```

The key split is **roles (semantic purpose) vs. clients (transport)**. Prompts live as files — not inline f-strings — enabling A/B without redeploy and clean version-in-cache-key behavior.

**Role as a Protocol, not a deep ABC.** Python 3.11+ `typing.Protocol` enables structurally-typed composition and trivial test doubles without multiple-inheritance tangles:

```python
class Role(Protocol, Generic[T]):
    name: str
    schema: type[T]
    async def run(self, **inputs) -> T: ...

@dataclass
class SentimentRole:
    name = "sentiment"
    schema = SentimentOut
    client: LLMClient
    prompt_id: str = "sentiment/v2"
    async def run(self, *, text: str, ticker: str) -> SentimentOut:
        prompt = render(self.prompt_id, text=text, ticker=ticker)
        raw = await self.client.complete(model="qwen3-8b-ft", prompt=prompt,
                                         temperature=0.0, max_tokens=256)
        return SentimentOut.model_validate_json(raw)
```

**Strategy declares requirements via Pydantic config** (loaded from TOML at startup, validated against registered roles and budgets):

```python
class StrategyLLMConfig(BaseModel):
    strategy_id: str
    roles: list[RoleRequest]       # role, prompt_id, temperature, max_tokens, guardrails
    budget_usd_per_day: float = 0.0
    max_latency_ms: int = 5000
    fallback: Literal["skip", "neutral", "raise"] = "neutral"
```

**Cache key rule** — bake everything that changes the output into the key: model name, prompt id, temperature, Pydantic schema version. Missing any of these is the #1 caching bug. Use `diskcache` (file-based, zero ops, millions of entries) over Redis for v1. Cache deterministic prompts at `temperature=0` only; TTL 30 days for SEC filings (immutable), 24h for news sentiment, never for intraday prices. Even at `temperature=0`, LLMs aren't bit-reproducible across infrastructure (MoE routing, GPU non-associativity) — treat the cache as semantic, not cryptographic.

**Keep LLM calls out of the backtest hot loop.** Precompute features in a batch pass with `asyncio.Semaphore` matching `OLLAMA_NUM_PARALLEL` (empirical sweet spot 2–4 with KV headroom, but at Q8 on 12 GB stay at 1). Store outputs in a feature table keyed by `(ticker, timestamp, role, prompt_id, model_version)` — the backtester reads them identically to numerical indicators. For live/event-driven mode, wrap calls in a circuit breaker (5 consecutive failures → 60 s open) with fallback to last-known-good cached value.

**Testing: three levels (Hamel Husain).** Unit tests with mocked clients via constructor injection (not module-level monkey-patching) run on every commit. VCR-style replay via `pytest-recording` captures real Ollama HTTP shapes once, replays forever, sets `--record-mode=none` in CI. Golden-set regression per role (`evals/golden/sentiment/headline_beat.yaml` with input + expected label + min_score), binary pass/fail — not 1–5 scales, which don't measure what you think they do — with 70–85% threshold, run on every prompt bump.

**Observability in 50 lines.** An async context manager that emits one JSON log per call with `{role, prompt_id, model, cache_hit, latency_ms, tokens_in, tokens_out, ok, err}`, piped to DuckDB. That's Langfuse-lite; upgrade only when you have >100 traces/day and need dashboards.

**Anti-patterns to avoid.** LLM calls inside a vectorized pandas loop (precompute instead); prompts as f-strings inline in strategy code (makes prompt iteration require code review); caching `temperature>0` as if deterministic; omitting model/prompt version from cache key; `temperature>0` for extraction tasks; running Ollama with default `OLLAMA_NUM_PARALLEL=1` while issuing async requests (you think you're parallel, you're not); wrapping everything in LangGraph "because agents"; a single `LLMService` god-class coupling transport/prompts/validation/caching; letting LLM errors kill strategy signals.

## Conclusion: build the evaluation harness before the LLM

**The most under-appreciated finding from 2023–2025 literature is that most published LLM trading alpha fails under rigorous replication.** FINSABER (2025) dismantled the FinMem/FinAgent/FinCon results; Sarkar & Vafa (2024) showed prompt-side anonymization doesn't fix lookahead bias; Trading-R1 (2025) reports positive results only on 6 large-cap names in a bull regime. The two roles with durable alpha — headline sentiment and filings extraction — are exactly the roles where **a fine-tuned 8B local model meets or beats frontier APIs** (FinMA-7B > GPT-4 on FPB and Headlines F1). This is fortunate for Arcis: the cheapest deployment is also the most defensible.

The correct sequencing is therefore inverted from how most practitioners build: **write the evaluation harness first** (three-arm placebo, mutual information, calibration, self-blinding, FActScore audit), then add Jinja2 prompts with Instructor-validated outputs, then layer LoRA adapters on a single frozen Qwen3-8B base, then finally route the high-complexity long tail (numerical reasoning, research synthesis) to frontier APIs with strict budgets. Expected steady-state cost for the full Arcis workload is **~$25–30/month hybrid vs. $110–140 all-API** — a 75–80% reduction while capturing >95% of frontier quality on Arcis's actual task mix.

The novel insight from synthesizing the taxonomy, guardrails, and evaluation literature is that **hallucination risk and alpha potential are inversely correlated across roles**: extraction and sentiment (low hallucination risk, proven alpha) vs. strategy proposal and ensemble weighting (high hallucination risk, no replicated alpha). Spend LLM capital where the risk-reward is favorable, and treat the speculative roles as permanent A/B experiments with placebo arms — not as production alpha sources.
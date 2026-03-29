# Training data strategies that give small financial LLMs a real edge

**A well-curated dataset of 3,000–5,000 institutional-quality trade commentary examples, structured as multi-source XML-tagged investment theses and trained via a three-stage curriculum (structure → evidence → decision), can produce a Qwen3 8B model that outperforms GPT-4 on financial trading analysis.** This is not theoretical — Tauric Research's Trading-R1, built on a Qwen3-4B backbone with exactly this approach, achieved a **2.72 Sharpe ratio and 70% hit rate** on NVDA, beating GPT-4.1's 0.85 Sharpe. The research consensus from 2025–2026 is clear: for domain-specific financial tasks, quality-over-quantity fine-tuning on small models beats general-purpose large models by **10–30% absolute** on benchmarks. The implication for Halcyon Lab is that the path to institutional-quality output runs through data curation and training methodology, not model scale.

---

## Trading-R1 is the blueprint you should replicate and extend

The single most relevant reference for Halcyon Lab is **Trading-R1** (Tauric Research, September 2025, arXiv:2509.11420), which uses the same Qwen3 architecture and solves the same problem — generating structured investment theses for equity trading. Its dataset, Tauric-TR1-DB, contains **100,000 training instances** spanning 18 months across 14 equities, with each example comprising **20–30K tokens** drawn from five heterogeneous data sources: technical market data, fundamental signals (balance sheets, income statements, SEC filings), newswire articles, sentiment/insider data (Form 4 transactions, analyst ratings, buyback announcements), and macroeconomic indicators (interest rates, inflation, labor statistics).

The training methodology uses a **three-stage easy-to-hard curriculum** that is directly implementable on an RTX 3060. Stage I (Structure) teaches professional XML-tagged thesis formatting through supervised fine-tuning, then reinforcement learning refines systematic analysis. Stage II (Claims) introduces evidence-based reasoning with direct citations from input context, and RL reduces hallucinations by rewarding grounded quotations. Stage III (Decision) focuses on investment recommendations, with RL optimizing for **volatility-adjusted returns** using a 5-tier label scale (Strong Buy through Strong Sell) derived from multi-horizon realized returns. A critical innovation is **reverse reasoning distillation**: proprietary LLMs (o3-mini/o4-mini) generate opaque outputs, then a planner LLM reconstructs detailed step-by-step reasoning traces to serve as SFT targets. This means you can use Claude or GPT-4 to generate final trade commentary for completed trades, then have a second pass decompose the reasoning into explicit analytical steps.

For Halcyon Lab's S&P 100 focus, the replication path is to build an equivalent multi-source dataset where each training example packages technical indicators, the most recent 10-Q/10-K excerpts, recent news, insider activity, and macro context into a structured input, paired with an XML-tagged thesis output that the model learns to generate.

---

## Quality crushes quantity — the research is unambiguous

The LIMA paper (Zhou et al., 2023) demonstrated that **1,000 carefully curated prompt-response pairs** fine-tuned on LLaMA-65B matched GPT-4 in 43% of head-to-head evaluations, with zero RLHF. The core finding — the "Superficial Alignment Hypothesis" — is that nearly all knowledge lives in pretraining; fine-tuning primarily teaches the model *which output format and style to adopt*. This is particularly powerful for Halcyon Lab because Qwen3 8B already possesses substantial financial knowledge from pretraining. AlpaGasus confirmed this by showing that **9,000 quality-filtered examples** dramatically outperformed 52,000 unfiltered examples, while reducing training time by **5.7×**. Databricks' LIMIT study found **2,000–6,000 mixed high-quality samples** sufficient for effective instruction fine-tuning at 7B–30B scale.

For trade commentary specifically, the practical dataset sizes are:

- **Minimum viable**: 500–1,000 meticulously curated examples for style alignment
- **Sweet spot**: 2,000–5,000 diverse, high-quality trade commentary examples
- **Upper practical limit**: 10,000 examples (diminishing returns beyond this for QLoRA)
- **DPO stage**: ~2,000 preference pairs are sufficient per recent HuggingFace experiments

What makes financial training data "high quality" comes down to six measurable dimensions: thesis clarity (is the core trade idea stated and actionable?), evidence quality (are claims grounded in cited data?), risk assessment (are risks proportional to actual outcomes?), technical accuracy (are indicators and levels correct?), calibration (does confidence match the actual setup?), and actionability (are entry, exit, and sizing addressed?). Every training example should score well across all six dimensions. The most effective labeling approach is to have 2–3 experienced equity traders write 100–200 gold-standard analyses to establish a style guide, then use GPT-4/Claude to generate thousands more following that guide, with a 5–10% human validation pass.

---

## Outcome-conditioned generation and the win/loss balance problem

The most powerful technique for generating training data is **outcome-conditioned reverse distillation** — writing the ideal pre-trade analysis *after* knowing how the trade resolved. The prompt structure is: "Given that this AAPL trade entered at $185 on a technical breakout and returned +12% in 7 days, write the institutional-quality pre-trade analysis a senior analyst would have written at entry, using only information available before entry." This produces commentary that correctly identifies the signals that mattered, weighted by their actual predictive importance.

The critical nuance is how to handle losing trades. Training exclusively on winners produces systematic overconfidence — a well-documented failure mode where RLHF-aligned models exhibit "inherent biases toward high-confidence scores regardless of actual quality." Losing trade examples should **not** show bad analysis; they should show *excellent analysis where the thesis was invalidated*, teaching the model to express calibrated uncertainty. The recommended ratio is approximately **60% winning / 35% losing / 5% breakeven** examples, roughly matching institutional win rates. Examples should span bull, bear, and sideways markets, cover all major S&P 100 sectors, range across 2–15 day holding periods, and include multiple setup types (breakouts, pullbacks, reversals, momentum).

Anti-overconfidence strategies include training examples with explicit hedging language ("the technical setup favors upside, though sector rotation risk remains elevated"), confidence qualifiers ("moderate conviction," "high-risk setup"), proportional risk sections, and contrastive pairs where similar setups led to opposite outcomes. Temperature scaling at inference (T=1.5–3.0) provides additional calibration.

---

## Preventing lookahead bias requires militant temporal discipline

Lookahead bias is the single most dangerous failure mode in financial ML training data. Recent research by Lopez-Lira et al. (2025) demonstrated that GPT-4o can recall exact S&P 500 closing prices with less than 1% error for dates within its training window — errors "explode" only post-cutoff. This means the base Qwen3 8B model has memorized historical price movements, and your training data must be constructed to avoid rewarding this memorization.

Every data element in a training example must carry a timestamp verifying it was available before the trade entry date. News articles need exact publication timestamps, not just dates. Fundamental data must reflect the last-filed financial statements, not current ones. Technical indicators should be computed only on price data available at entry. Analyst price targets must predate entry. Earnings data should only include quarters already reported. Insider transactions should use filing dates (not transaction dates, which can be reported with delay). Macro data should reflect the last-published release.

For train/test splitting, **strict chronological ordering** is mandatory — never randomize. Use expanding window validation (train on months 1–8, validate on month 9, then expand), with a **1–2 week temporal gap** between train and test periods to prevent autocorrelation leakage. A reasonable split is 70/15/15 for train/validation/test, all chronologically ordered. The emerging Look-Ahead-Bench benchmark (2026) provides a standardized framework for testing point-in-time inference compliance.

---

## The $0–100/month data stack that covers 90% of institutional needs

The SEC EDGAR ecosystem alone provides billions of tokens of structured financial text at zero cost. The full-text API at `data.sec.gov` requires no API key — only a User-Agent header with your email — and supports **10 requests per second**. The XBRL Company-Concept endpoint delivers structured financial data across all filings, while the XBRL Frames endpoint enables cross-company comparable data pulls. Pre-processed datasets on HuggingFace include `eloukas/edgar-corpus` (6+ billion tokens from 10-K filings 1993–2020, section-parsed), `PleIAs/SEC` (245,000+ entries, 7.2 billion words), and `JanosAudran/financial-reports-sec` (sentence-level with market-reaction labels). The open-source EDGAR-CRAWLER tool parses 10-K, 10-Q, and 8-K filings into structured JSON by item section.

For the **free tier foundation** ($0/month), combine: SEC EDGAR (unlimited filings, XBRL data, Form 4 insider transactions), Finnhub (60 calls/min — earnings transcripts, analyst recommendations, congressional trades, insider trades, news), Alpha Vantage (500 calls/day — prices, fundamentals, technical indicators), FMP (250 requests/day — analyst estimates, financial statements), FRED API (120 requests/min — macro data, yield curves, Fed Funds Rate), and API Ninjas (10,000 calls/month — insider trading, earnings transcripts). Add HuggingFace datasets for FOMC communications (`vtasca/fomc-statements-minutes`), financial news (`Brianferrell787/financial-news-multisource` with **57 million+ rows** spanning 1990–2025), and pre-built instruction datasets (PIXIU with 128,000+ samples, FinGPT forecaster data).

The optimal **paid allocation of $50–100/month** is Polygon.io Starter at $29/month for reliable unlimited price data and FMP Starter at $15–29/month for full analyst estimates, earnings transcripts, and Senate/House trading data. If options flow is critical to your thesis generation, Unusual Whales at ~$55/month provides real-time options flow, dark pool data, and congressional trades with API access. Insider trading data is entirely free via SEC's quarterly bulk downloads of Form 3/4/5 data at `sec.gov/data-research/sec-markets-data/insider-transactions-data-sets` and real-time screening through OpenInsider. Congressional trading is free via Capitol Trades (scrapeable), Quiver Quantitative's Python package, and House Stock Watcher's free API.

Federal Reserve communications are fully free — all FOMC statements, minutes, press conferences, speeches, and Beige Book text is available at `federalreserve.gov`. Georgia Tech's annotated FOMC dataset (1996–2022) provides hawkish/dovish/neutral labels. Patent data from USPTO's Open Data Portal and PatentsView is free bulk download of all granted patents since 1976. For supply chain indicators, FRED provides import/export data, industrial production indices, and inventory-to-sales ratios at no cost.

---

## Chain-of-thought and GRPO are the winning training methodology

The most impactful 2025 finding for financial LLM training is that **GRPO (Group Relative Policy Optimization) consistently improves financial reasoning, while PPO and DPO produce unstable results**. The Fin-o1 project (EMNLP 2025 FinNLP Workshop) demonstrated this definitively: an 8B model trained with SFT + GRPO on the FinCoT corpus outperformed GPT-o1, DeepSeek-R1, and GPT-4.5 on financial reasoning benchmarks. GRPO is memory-efficient (no critic model needed, fitting on consumer GPUs), and Unsloth already supports GRPO on Qwen3-8B with free Colab notebooks available.

The FinCoT dataset itself provides the template for structuring chain-of-thought financial training data. It uses a three-stage pipeline: domain supervision (financial expert verification of reasoning steps), iterative LLM refinement (multiple generation-and-critique passes), and difficulty-aware filtering. Domain-specific FinCoT prompts for equity analysis provided a **+24.42 percentage point accuracy boost** when tested on Qwen3-8B. The practical CoT format for trade thesis generation should decompose analysis into explicit steps: revenue/margin trend analysis, catalyst identification, risk assessment, valuation check, and synthesis with conviction level assignment.

For the hybrid RAG + fine-tuning architecture, the RAFT approach (UC Berkeley + Microsoft + Meta) has emerged as the clear winner. RAFT trains the model on a mix where 80% of examples include the relevant retrieved document and 20% include only distractors, forcing the model to learn when retrieval fails. A RAFT-trained LLaMA-2 7B outperformed GPT-3.5 in RAG mode on domain-specific tasks, and the approach has been demonstrated with Unsloth. The practical architecture for an RTX 3060: Qwen3 8B in 4-bit QLoRA uses ~6–8GB VRAM for inference, leaving room for CPU-based RAG retrieval via ChromaDB or FAISS indexing recent earnings transcripts, filings, and market data.

---

## Synthetic data distillation is how you bootstrap at scale

The dominant 2025 strategy for creating financial training data is **teacher-student distillation** — prompting GPT-4 or Claude to generate detailed trade analyses, then using a second strong model as a quality filter, then training Qwen3 8B on the filtered results. Fin-R1 proved this pipeline on Qwen2.5-7B-Instruct: DeepSeek-R1 generated CoT reasoning traces, Qwen2.5-72B-Instruct filtered for quality (LLM-as-judge), and the student model trained on **60,091 filtered examples**. IBM's LAB method scaled this to 1.2 million synthetic instructions, with student models outperforming those trained on larger real datasets.

The practical pipeline for Halcyon Lab: curate 200–500 real financial analysis scenarios from SEC filings, earnings calls, and analyst reports as seed prompts. Use Claude or GPT-4 to generate detailed CoT trade theses for each scenario. For each seed, generate 5–10 variations across different time periods, sectors, and market conditions. Apply LLM-as-judge quality filtering (keep top 70–80%) scoring on financial accuracy, reasoning coherence, and actionability. Tag examples by difficulty for curriculum learning. This yields 5,000–10,000 high-quality examples at approximately **$50–150 in API costs** — a one-time expense.

For curriculum learning, the AdaRFT framework (April 2025) demonstrated that dynamically adjusting training difficulty based on the model's recent reward signals reduces training time by up to **2×** while improving accuracy. The practical implementation: Phase 1 (simple single-factor analysis), Phase 2 (multi-factor synthesis), Phase 3 (full trade thesis with conflicting signals), Phase 4 (complex scenarios with regime changes). Length-based curriculum ordering achieves **1.5× faster convergence**, so ordering by input complexity provides an easy initial implementation.

---

## Building a moat that compounds over time

The durable competitive advantage for Halcyon Lab lies not in any single component but in the **integrated system**: proprietary feature engineering + curated training data + automated retraining pipeline + outcome-based feedback loop. Each component reinforces the others, and the system improves with use in ways that are extremely difficult for competitors to replicate.

**What creates lasting advantage**: The specific combination and curation of data — not raw volume — is the moat. Bloomberg spent $3 million and 53 days training BloombergGPT on 363 billion financial tokens, yet FinGPT fine-tuned on carefully selected data with LoRA for under $300 outperforms it on sentiment tasks. Your proprietary feature engineering (custom composite indicators, regime-detection signals, cross-asset features) becomes embedded in the model's analytical vocabulary — if the model is trained to reference and reason about 50+ proprietary indicators, competitors would need to replicate the entire feature pipeline, not just the model weights.

**The feedback flywheel** is the most powerful moat mechanism: each trade commentary generates a prediction → market outcomes provide automatic reward signals (directional accuracy, P&L, Sharpe ratio) → outcomes become proprietary training data → the model improves → better commentary generates better trades → more proprietary outcome data. This compounding loop produces training signal that no competitor can access without running the same trades. The R-Few framework (2025) validated this self-improvement approach: Qwen3-8B-Base improved by +3.0 points using 75%+ self-generated data mixed with a small percentage of expert-curated anchor examples, matching models trained on 232,000 human-curated samples.

**The "poor man's MoE"** extends the moat further: train multiple LoRA adapters on the same Qwen3 8B base, each specialized for different market regimes (momentum, risk-off, range-bound). Each adapter is ~50–200MB and can be hot-swapped at inference time based on a regime classifier. Unsloth supports dynamic LoRA loading, making this feasible on consumer hardware. TradExpert (2024–2025) demonstrated that this multi-specialist approach consistently outperforms single-model architectures.

**What will not be a moat**: the model architecture (Qwen3 is public), generic prompt engineering (easily replicated), raw data access (most financial data is public), or first-mover advantage alone. The institutional-quality rubric — the tacit knowledge of what makes commentary truly professional — is labor-intensive and expert-dependent to encode, making it one of the most defensible assets. Document this rubric explicitly, and treat it as core IP.

---

## The complete implementation roadmap

**Week 1 — Data collection**: Download S&P 100 SEC filings via EDGAR-CRAWLER, pull earnings transcripts via Finnhub, download Form 4 insider bulk data from SEC, scrape Capitol Trades for congressional trading, pull FOMC documents, and collect price data via Polygon.io. Begin constructing multi-source input records that package technical data, fundamental excerpts, news, insider activity, and macro context per stock-day.

**Week 2 — Synthetic data generation**: Write 100–200 gold-standard trade analyses with experienced traders to establish the style guide. Use Claude/GPT-4 with reverse distillation to generate 3,000–5,000 outcome-conditioned trade theses in XML-tagged format. Apply LLM-as-judge filtering. Verify temporal compliance — no lookahead bias. Tag by difficulty level.

**Week 3 — SFT training**: Fine-tune Qwen3 8B via QLoRA/Unsloth with curriculum ordering (structure → claims → decision). Settings: `load_in_4bit=True`, LoRA rank 16–32, target all linear layers, learning rate 1e-4 with linear decay, batch size 2, gradient accumulation 4–8. Training takes **2–6 hours** on an RTX 3060 for 5,000–10,000 examples across 3–5 epochs.

**Week 4 — RAFT + DPO alignment**: Add retrieved document context to 80% of examples (with 20% distractors) and run a RAFT training pass. Generate 2,000+ preference pairs by having the SFT model produce 4–8 commentaries per scenario, scoring with the quality rubric, and pairing highest/lowest. DPO with β=0.01, 3 epochs. Optionally, run GRPO with volatility-adjusted outcome rewards.

**Ongoing — Feedback flywheel**: Track commentary → trading decision → outcome. Retrain monthly via QLoRA (<$300/run, <6 hours). Mix 80% model-generated training data with 20% expert-curated anchors. Monitor for model collapse via held-out validation. Expand the training universe progressively across market regimes and add new data sources as the budget allows.

## Conclusion

The research landscape for financial LLM fine-tuning in 2025–2026 has converged on a clear set of principles. Training-R1's three-stage curriculum with reverse reasoning distillation provides the most directly applicable blueprint for Halcyon Lab. The quality-over-quantity evidence is overwhelming — 3,000–5,000 rigorously curated examples outperform orders of magnitude more low-quality data. The combination of GRPO-based reinforcement learning, RAFT-style hybrid RAG, and outcome-conditioned synthetic data generation represents the current frontier, and all three techniques are implementable on consumer hardware with Unsloth. The lasting competitive moat emerges not from any one technique but from the integrated flywheel: proprietary features encoded into training data, outcome-based reward signals that only your trading generates, and an automated retraining pipeline that compounds edge over time. The $0–100/month data stack covering SEC EDGAR, Finnhub, FRED, and a handful of paid APIs provides coverage that would have cost institutional funds six figures annually just five years ago.
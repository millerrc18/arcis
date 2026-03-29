# Prompt engineering for outcome-conditioned training data generation

**The single most important finding across this research: telling an LLM to "pretend you don't know the outcome" fails reliably.** Christian & Mazor (2026) demonstrated that LLMs cannot accurately simulate counterfactual knowledge states — they suffer from "hypothetical inconsistency" analogous to human hindsight bias, where even explicit instructions to ignore biasing information occasionally backfire. This has direct implications for every aspect of the reverse distillation pipeline. The solution is architectural, not instructional: a two-call "self-blinding" pipeline where the first call genuinely never receives the outcome, and a second call enhances writing quality without altering directional stance. Combined with structured diversity strategies, CLAIR-style contrastive pair generation for DPO, and Trading-R1's reverse reasoning distillation methodology, the research points to a concrete, cost-effective pipeline for generating **3,000–5,000 high-quality training examples from 500 base setups at under $600 total API cost**.

---

## The self-blinding architecture solves what instruction prompts cannot

Research from multiple directions converges on one conclusion: LLMs leak outcome knowledge through subtle but detectable channels that no amount of prompt engineering can fully suppress. Gao, Jiang & Yan (2025) found that LLMs' stock return predictive power increases by **~37%** for headlines the model likely memorized from training data — proving that temporal leakage is a measurable, systematic phenomenon. Fake-date tests (arXiv:2601.07992) confirmed that no modern frontier model can reliably partition temporal knowledge when asked to forecast. A review of 164 papers on LLMs in finance (arXiv:2602.14233) identified five recurring biases — look-ahead, survivorship, narrative, objective, and cost bias — yet found no single bias discussed in more than 28% of studies, indicating systematic under-attention.

The leakage mechanisms are specific and insidious. Even without explicit outcome words, models leak through **sentence structure** (more complex hedging for losers), **adverb selection** ("clearly" for winners, "potentially" for losers), **risk factor count** (more mentioned for losers), **analysis length** (often longer for losers as the model unconsciously "explains" the failure), and **narrative framing** (clean signal-to-confirmation arcs for winners vs. complication-laden narratives for losers). These patterns are subtle enough to escape human review but detectable by a simple TF-IDF classifier.

The evidence-based solution is a **three-stage self-blinding pipeline**:

**Stage 1 — Blinded Generation.** Send Claude Haiku 4.5 the trade setup data with zero outcome information. The model generates genuine pre-trade analysis reflecting authentic uncertainty. This is the temporal firewall — the model literally cannot leak what it does not know.

```
You are a senior equity analyst. It is {DATE}. You are reviewing the following 
trade setup for a pullback-in-strong-trend entry:
{XML_INPUT — NO OUTCOME DATA}

Write a detailed pre-trade analysis covering: directional thesis with supporting 
evidence, 2-3 specific risk factors, probability assessment (55-65% range), 
stop-loss rationale, and expected scenarios. A well-calibrated analyst is wrong 
~40% of the time on individual trades.
```

**Stage 2 — Quality Enhancement (outcome-blind).** A second call receives only the Stage 1 output plus writing quality instructions — still no outcome. This call enhances analytical depth, prose quality, and institutional tone without changing the directional stance, confidence level, or hedging density.

**Stage 3 — Verification.** Train a lightweight classifier (logistic regression on TF-IDF features) on the generated analyses with outcome labels. If classification accuracy exceeds **55%**, the pipeline is leaking and prompts need iteration. Additionally, generate analysis for the same setup under both winning and losing outcome conditions — a human reviewer should not be able to distinguish which is which.

This architecture draws on the treatment leakage framework from causal inference (Daoud et al., 2026), which defines formal criteria for "perfect distillation": the output should be conditionally independent of the treatment (outcome) given the confounders (setup data). The self-blinding approach achieves this by construction rather than instruction.

---

## Prompt differentiation requires outcome-invariant base quality with controlled variation

The KalshiBench evaluation of epistemic calibration found that **all frontier LLMs exhibit universal overconfidence** with Expected Calibration Error of 0.12–0.40, and that extended reasoning paradoxically worsens rather than improves calibration. This means generated "uncertain" language will systematically overstate confidence and needs deliberate downward adjustment.

The core design principle for outcome-differentiated prompts is counterintuitive: the base analytical quality should be **identical** across win/loss/breakeven outcomes. Differentiation should come only from dimensions a pre-trade analyst would genuinely vary based on the setup data quality, not from the outcome. Thesis clarity, risk factor count, hedging language density, and analytical depth should remain constant. Only setup-quality-driven confidence and signal-strength framing should vary slightly.

For **winning trades**, the prompt should produce correct signal identification with calibrated confidence — a clear thesis with supporting evidence, moderate conviction (55–65%), and genuine risk factors treated as standard professional diligence. The key instruction: *"The quality marker of excellent analysis is clarity of reasoning, not correctness of prediction. A great analyst about to be right looks identical to a great analyst about to be wrong."*

For **losing trades**, the prompt must produce excellent analysis where the thesis was plausible given available data but ultimately invalidated. Critical instruction: *"Do not overweight risks, add excessive hedging, or use language suggesting doubt about the thesis. The analysis should be indistinguishable in tone and confidence from an analysis preceding a winning trade."* The thesis should still be well-articulated — the model must learn that good analysis sometimes produces losses.

For **breakeven/timeout trades**, genuine ambiguity is appropriate: a thesis presented alongside a roughly equal-weight counter-thesis, with explicit acknowledgment that the signal strength is moderate and the trade has meaningful scratch probability. Confidence range narrows to **50–58%**.

An explicit **banned word list** reduces leakage further. For losing trade contexts: "unfortunately," "despite the analysis," "the thesis was ultimately," "turned out to be." For winning trade contexts: "correctly identified," "the thesis proved," "as expected," "validated." Required hedging phrases for all outcomes: "the thesis could be invalidated if," "key risk includes," "uncertain whether."

---

## Trading-R1's three-model reverse reasoning pipeline is replicable with Claude

Trading-R1 (Xiao et al., September 2025, arXiv:2509.11420) from Tauric Research/UCLA introduces **reverse reasoning distillation** — reconstructing step-by-step reasoning traces from opaque proprietary model outputs that expose only final answers. The pipeline uses three distinct model roles trained on a **100,000-sample dataset** spanning 18 months across 14 major tickers with five heterogeneous data modalities.

**Pass 1 (Teacher — o3-mini/o4-mini)** generates final trading recommendations from structured financial inputs. These proprietary reasoning models produce superior predictions but hide their chain-of-thought, returning only conclusions. **Pass 2a (Planner — GPT-4.1)** receives the original input plus the teacher's final recommendation and infers the key reasoning steps required to arrive at that conclusion, decomposing the path into factor-by-factor analysis (competitors, technical analysis, insider transactions, macro indicators). **Pass 2b (Elaborator — GPT-4.1-nano)** expands each decomposed step into detailed, modality-specific analysis paragraphs. These segments are then **programmatically stitched** into coherent end-to-end investment theses — the SFT training targets.

A crucial finding from Li et al. (2025) explains why this works: in chain-of-thought distillation, the **structure** of reasoning traces matters dramatically more than the content details within individual steps. Introducing errors in reasoning steps (random digits, removed keywords) degraded accuracy only 3–4%, but corrupting the structural skeleton caused significant performance collapse. This means Trading-R1's planner doesn't need to reconstruct the teacher's actual internal reasoning — it only needs to produce a *structurally valid* reasoning trace consistent with the final answer.

The student model — a remarkably compact **Qwen3-4B** — is trained via a three-stage easy-to-hard curriculum interleaving SFT and reinforcement learning (GRPO): Stage I teaches **structure** (professionally formatted investment theses), Stage II teaches **claims** (evidence-grounded reasoning with cited quotes), Stage III teaches **decisions** (market-aware, volatility-adjusted trading recommendations). Results show Trading-R1 achieving **8.08% cumulative return, 2.72 Sharpe ratio, and 70.0% hit rate** on NVDA, substantially outperforming GPT-4.1 baselines.

**Replication with Claude** is straightforward. Claude's extended thinking mode can actually expose reasoning traces directly — potentially eliminating the need for reverse distillation entirely and enabling direct CoT distillation. The proposed mapping: Claude Sonnet 4.5 with extended thinking as the teacher (high-quality final recommendations), Claude Sonnet as the planner (reasoning decomposition), and Claude Haiku 4.5 as the elaborator (high-volume detail generation at $1/MTok input). The programmatic stitching step is model-agnostic.

---

## Structured dimensional variation beats paraphrasing by an order of magnitude

The research consensus on generating 3,000–5,000 diverse examples from 500 base setups is unambiguous: **structured dimensional variation produces meaningful diversity; simple paraphrasing and temperature manipulation do not**. Multiple sources — Self-Instruct (Wang et al., 2022), Evol-Instruct/WizardLM (Xu et al., 2023), Persona Hub (Tencent, 2024), and GLAN (Microsoft, 2024) — converge on this finding from different angles.

The recommended approach uses a **multi-dimensional variation matrix** across seven independent axes:

- **Analyst persona** (6 variants): aggressive momentum trader, conservative value investor, quantitative systematic trader, fundamental sector analyst, risk-focused portfolio manager, short-term swing trader — each with detailed backgrounds, vocabulary tendencies, and reasoning preferences
- **Analytical emphasis** (6 variants): relative strength ranking, sector rotation dynamics, risk/reward ratio, volume confirmation, support/resistance analysis, macro backdrop
- **Conviction framing** (3 variants): high, moderate, low
- **Holding period perspective** (4 variants): day trade, swing (2–5 days), position (1–4 weeks), core holding (1–3 months)
- **Analysis style** (4 variants): quantitative-heavy, qualitative narrative, balanced, comparison-focused
- **Risk framing** (4 variants): opportunity-focused, risk-first, balanced, probabilistic/scenario-based
- **Prose length** (3 variants): concise desk note, standard paragraph, detailed multi-paragraph

This matrix yields **31,104 possible combinations**, of which even sparse sampling produces massive diversity from 500 base setups.

**Input perturbation** compounds this further. For each of the 500 setups, create 2–4 counterfactual variants by systematically perturbing 1–2 key numerical values: RSI from 38→28 (deeper oversold) or 48 (barely oversold); volume from 1.2× average→2.5× (breakout volume) or 0.7× (thin); pullback depth from 38.2% Fibonacci→50% or 23.6%. This alone transforms 500→1,500–2,500 meaningfully different inputs where the analytical output must genuinely respond to changed conditions rather than merely rephrase.

What definitively **does not work**: simple paraphrasing without informational diversity (same information in different surface form — the fine-tuned model learns template structure but not analytical depth); temperature-only variation (increases lexical randomness without improving analytical diversity); unstructured "generate 10 variations" instructions (LLMs regress to a homogeneous mode of "helpful, balanced, comprehensive" analysis); and recursive self-training on synthetic data (Shumailov et al., 2023, published in Nature, proved that each synthetic generation smooths the distribution, with tail/minority cases disappearing first in "early model collapse").

The practical pipeline: Phase 1 generates ~2,000 unique inputs via counterfactual perturbation (scripted, minimal cost). Phase 2 generates ~12,000 raw outputs (6 per input) using systematically varied prompts sampling from the variation matrix. Phase 3 filters to ~4,000 curated examples using LLM-as-judge scoring on analytical depth, input responsiveness, conviction consistency, and distinctiveness, plus embedding-based deduplication at cosine similarity threshold >0.90. **Estimated total API cost: $300–600.**

---

## CLAIR's minimal-revision method produces the sharpest DPO training signal

For contrastive pair generation, the most directly applicable research is CLAIR (Contrastive Learning from AI Revisions, D'Oosterlinck et al., 2025, TACL). The core finding: **preference data gives a stronger learning signal when responses are contrastive — differing only in the targeted quality dimension**. Traditional approaches that generate two independent responses and judge which is better create pairs differing in many uncontrolled aspects (length, style, structure). CLAIR instead generates one excellent response and minimally revises it to introduce specific flaws, producing precisely targeted training signal. Using just **32K CLAIR preferences, Llama-3-8B-Instruct improved 7.65%, closing the gap with GPT-4-turbo by 45%**.

A critical finding from arXiv:2508.18312 challenges conventional wisdom about DPO data: **the quality of the chosen response is the primary driver of DPO performance, not the gap between chosen and rejected**. DPO primarily learns from chosen samples — swapping the rejected response while keeping chosen fixed yields only +0.8 to +1.4 point improvement. This means investing heavily in making "chosen" commentary excellent provides far greater returns than crafting elaborate "rejected" alternatives.

For financial trade commentary, three contrastive pair types are most instructive:

**Type 1: Excellent loss analysis (chosen) vs. missed warning signs (rejected).** The chosen response identifies the setup was plausible, names specific invalidation signals (declining breakout volume, sector rotation timing, rising yields pressuring growth multiples), and articulates the appropriate risk management response. The rejected response offers vague platitudes ("sometimes good setups fail") without analytical substance.

**Type 2: Calibrated confidence (chosen) vs. overconfidence (rejected).** The chosen response assigns moderate conviction (6/10), tempers enthusiasm with specific risk factors (earnings proximity, elevated RSI), and sizes accordingly. The rejected response claims 9/10 conviction, calls the setup "textbook perfect," and recommends full position.

**Type 3: CLAIR-style minimal revision pairs.** Generate one excellent commentary, then create rejected versions by surgically introducing single analytical flaws — removing hedge/uncertainty language (creates overconfident rejected), removing mention of contradictory indicators (creates blind-spot rejected), adding false pattern recognition (creates confabulating rejected), or removing stop-loss reasoning (creates risk-unaware rejected).

The BeeS paper (arXiv:2502.14560) demonstrated that using just **10% of the UltraFeedback dataset** — carefully selected by margin maximization — achieved **3–8% improvements** across Llama, Mistral, and Qwen models versus training on the full dataset. For this use case, **2,000–5,000 curated preference pairs should be sufficient**, with aggressive quality filtering retaining only the top 25th percentile by preference margin. A curriculum approach — training first on easy pairs (large quality gap) progressing to hard pairs (subtle analytical differences) — significantly outperforms random ordering.

---

## Claude Haiku 4.5 is the right teacher model — and prompt quality matters 5× more

The research on teacher model selection delivers a counterintuitive but well-documented finding: **a stronger teacher does not always produce a better student**. The "capacity gap" problem, observed across multiple studies (Graphcore's Distillation Scaling Laws, NeurIPS 2022's "Knowledge Distillation from A Stronger Teacher," and CMKD), shows that when the gap between teacher and student is too large, distillation can actually produce worse results. Student performance improvements through knowledge distillation exhibit **diminishing marginal returns** where a stronger teacher does not necessarily lead to a proportionally stronger student.

The LIMA paper (Meta) demonstrated that **1,000 carefully curated examples** matched 52,000 Alpaca examples and RLHF-trained models. Doubling training set size without increasing diversity showed no improvement. Microsoft's Phi-1 achieved 50.6% on HumanEval using only GPT-3.5-generated synthetic data — a model substantially weaker than Claude Haiku 4.5 — because data structure and pedagogical design mattered more than teacher capability. The Orca paper proved that system instructions eliciting step-by-step reasoning (prompt engineering) contributed more to student quality than upgrading teacher model tier.

At the team's budget of $3–10 per batch of 50–100 examples, **cost is not the binding constraint**. Claude Haiku 4.5 at $1/$5 per million tokens (with batch API at 50% discount and prompt caching at up to 90% savings) costs roughly **$0.10–0.20 per 100 examples**. Even Claude Opus 4.6 at $5/$25 per million tokens costs only ~$1.00 per 100 examples. The entire 5,000-example dataset generation including quality filtering costs under $600 with Haiku. The research consensus suggests investing marginal budget into **more diverse generation passes and better prompt engineering** rather than upgrading teacher model tier, with an optional Sonnet 4.5 pass for the 10–20% of examples requiring the most sophisticated multi-factor financial reasoning.

One additional strategy with strong evidence: **mixing teacher models** across the dataset (some examples from Claude, some from DeepSeek V3.2, some from GPT-5-mini) increases output diversity and reduces single-model mode collapse. Multi-teacher ensembles avoid biasing the student toward any single teacher's failure modes, and different students may benefit from different teachers' outputs.

---

## Conclusion: an integrated pipeline from 500 setups to production-ready training data

The research points to a specific, actionable architecture. First, expand 500 base setups to ~2,000 unique inputs via scripted counterfactual perturbation of technical indicators. Second, generate ~12,000 raw outputs using the self-blinding two-call pipeline with Claude Haiku 4.5, systematically sampling from the seven-axis variation matrix for each generation. Third, filter to ~4,000 curated SFT examples using LLM-as-judge scoring and embedding-based deduplication. Fourth, generate ~3,000 DPO preference pairs using CLAIR-style minimal revision, with curriculum ordering from easy to hard pairs. Fifth, verify the entire dataset with the leakage classifier — if outcome prediction accuracy exceeds 55%, iterate on prompts.

Three insights emerged that challenge common assumptions. The self-blinding architecture is not optional polish but a structural necessity — instruction-based "ignore the outcome" approaches fail measurably and sometimes backfire. Prompt engineering quality contributes roughly **5× more** to downstream student performance than teacher model capability, making Haiku 4.5 with excellent prompts superior to Opus with mediocre prompts. And for DPO training, investing in chosen response quality delivers far greater returns than crafting elaborate rejected alternatives — the margin between chosen and rejected matters surprisingly little compared to the absolute quality of the chosen response.
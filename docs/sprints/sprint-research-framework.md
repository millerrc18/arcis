# Task: Build the Arcis Research Framework

> **Output:** `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`
> **Purpose:** Master research synthesis — serves TWO audiences simultaneously
> **Submit as PR when complete.**

## The Two Audiences

This document serves two purposes and must be structured to work for both:

1. **AI Agents** — need fast lookup. They scan tables, find the relevant finding, get the citation, and move on. They care about "what did we decide and why" in under 30 seconds.

2. **Ryan (the founder)** — needs to deeply understand the research behind every decision. He's learning quantitative finance, portfolio theory, and ML engineering simultaneously. He wants to understand WHY the Kelly criterion is fractional, not just THAT it is. He wants the intuition, the caveats, the edge cases, the "what would make this wrong."

**The structure that solves both:** Each section has two layers:

```markdown
## 3. LLM Training Pipeline

### Quick Reference (for agents)

| Decision | Finding | Citation | Confidence |
|---|---|---|---|
| Self-blinding | Architectural, not instructional — 2-call pipeline | Christian & Mazor 2026 | HIGH |
| Training format | XML-tagged, 350-500 tokens, 11 sections | Trading-R1 (2025) | HIGH |
| Quality rubric | 6 dimensions, thesis clarity 25% weight | Internal research | MEDIUM |
| Retraining | Weekly = nightly at 90% lower cost | arXiv 2505.00356 | HIGH |
| DPO | Skip — inconsistent for financial reasoning | Fin-o1 (EMNLP 2025) | MEDIUM |
| GRPO | Start at 100+ closed trades, num_generations=8 | Fin-o1, confirmed feasible | MEDIUM |

### Deep Dive (for study)

**Why self-blinding must be architectural, not instructional.**

Christian & Mazor (2026) demonstrated that LLMs cannot accurately simulate
counterfactual knowledge states — they suffer from "hypothetical inconsistency"
analogous to human hindsight bias. In practice, this means...

[2-3 paragraphs explaining the research, the mechanism, the implications,
and what would change this conclusion]

**Why 350-500 tokens is the sweet spot.**

The tension is between horizontal feature density (more signal dimensions per
example) and the model's ability to attend to all of them during training.
Trading-R1 used 20-30K tokens per example with a 4B model, but they had...

[continue for each major finding in the section]
```

This way, an agent reads the table in 10 seconds. Ryan reads the full section in 10 minutes and actually understands the research.

---

## Phase 1: Read the existing corpus

Read these files in order. Take notes on key findings, contradictions, and gaps.

**Deep research results (highest authority):**
1. `docs/research/deep-research/full-strategy-RESULTS.md` (984 lines)
2. `docs/research/deep-research/horizontal-training-data-RESULTS.md` (228 lines)
3. `docs/research/deep-research/scanning-intervals-RESULTS.md` (240 lines)
4. `docs/research/deep-research/SYNTHESIS-framework-update-roadmap-changes.md` (237 lines)

**Core research (read title + first 50 lines of each — skip if fully covered by deep research):**
5. `docs/research/The_Halcyon_Framework__Compute__Value__and_Moat_for_a_Solo_AI_Trading_System.md`
6. `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`
7. `docs/research/Training_Data_Strategies_That_Give_Small_Financial_LLMs_a_Real_Edge.md`
8. `docs/research/Optimal_Training_Formats_for_Fine-Tuning_Equity_Trade_Commentary_Models.md`
9. `docs/research/Prompt_Engineering_for_Outcome-Conditioned_Training_Data_Generation__Self-Blinding_Pipelines_and_Reverse_Reasoning_Distillation.md`
10. `docs/research/Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining__Data_Accumulation__Golden_Ratio_Mixing__and_Champion-Challenger_Evaluation.md`
11. `docs/research/Gold-Standard_Rubric_for_Scoring_Equity_Trade_Commentary__Process-Driven_LLM_Evaluation_Framework.md`
12. `docs/research/GRPO_for_Financial_LLMs_on_Consumer_Hardware__Practical_Implementation_and_Reward_Design.md`
13. `docs/research/Best_Local_LLM_for_Financial_Analysis_on_RTX_3060__Qwen_Model_Selection_and_Fine-Tuning_Guide.md`
14. `docs/research/From_Solo_AI_Trader_to_Fund_Manager__A_Complete_Operational_Roadmap.md`
15. `docs/research/Alternative_Data_Signals_for_Large-Cap_Short-Horizon_Trading__A_Cost-Benefit_Analysis_for_the_Halcyon_Lab_Stack.md`
16. `docs/research/Halcyon_Lab_Scaling_Plan_Through_2026.md`
17. `docs/research/Halcyon_Lab__AI-Powered_Equity_Research_Investor-Ready_Business_Plan.md`
18. `docs/research/Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md`
19. `docs/research/Risk_Budgeting_for_3-Strategy_Equity_System.md`
20. `docs/research/Volatility-Adaptive_Position_Management_for_Pullback_Trading.md`
21. `docs/research/Walk-Forward_Backtesting_Protocol_for_Small-Sample_Strategies.md`
22. `docs/research/Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md`
23. `docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md`
24. `docs/research/AI_Council_Redesign_v2__Architecture_and_Implementation.md`
25. `docs/research/Competitive_Benchmarking_Report.md`
26. `docs/research/Market_Data_APIs_Comprehensive_Comparison_2026.md`
27. `docs/research/Optimal_Holding_Periods_for_Halcyon_Lab_Three_Equity_Strategies.md`
28. `docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md`
29. `docs/research/Strategy_2_Selection__Mean_Reversion_Wins.md`

Also read `MASTER.md` for current system state and `docs/sprints/arcis-master-implementation-plan.md` for roadmap context.

---

## Phase 2: Identify gaps and validate with /research

After reading the corpus, identify 5-8 areas where the research is weakest, stale, contradictory, or uncited. Then run `/research` to fill each gap. **Run at least 5 queries.** Examples (adapt based on what gaps you actually find):

```bash
# Competitive landscape (our research is from early 2026 — what's new?)
/research "LLM-based equity trading systems 2026 — Trading-R1 successors, FinRL updates, new entrants, performance benchmarks" --depth deep --domain trading

# Mean reversion validation (Strategy #2 just went live)
/research "Connors RSI(2) mean reversion for large-cap equities — post-2024 evidence, regime sensitivity, optimal parameters, survivorship bias concerns" --depth moderate --domain trading

# Alpha attribution methodology (our #1 experiment)
/research "Alpha attribution in systematic trading — matched pair experimental design, McNemar's test for strategy comparison, minimum sample sizes, bootstrap methods" --depth moderate --domain trading

# Position management (we chose mechanical brackets — validate)
/research "Mechanical vs discretionary exits for swing trades — trailing stops, time-based tightening, ATR-based stop effectiveness, disposition effect in systematic systems 2024-2026" --depth moderate --domain trading

# Training data for financial LLMs (fast-moving field)
/research "Fine-tuning small language models for financial reasoning 2025-2026 — GRPO results, curriculum learning, self-play, outcome-conditioned generation, data quality vs quantity" --depth deep --domain software-ai
```

Focus `/research` on areas where:
- Existing research cites papers from 2024 or earlier and the field may have moved
- Key claims lack citations or have only "practitioner consensus"
- The deep research results flagged uncertainty or open questions
- The competitive landscape may have shifted

---

## Phase 3: Write the framework document

Create `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`. Target **1,500-2,500 lines** — larger than MASTER.md because this is both a reference AND a study guide.

### Document structure:

```markdown
# Arcis Research Framework

> **Last updated:** {date}
> **Sources:** {N} internal research documents + {N} /research queries
> **How to read this:**
> - **Agents:** Read the "Quick Reference" table at the top of each section. That's all you need.
> - **Humans:** Read the "Deep Dive" prose below each table for full understanding.
> - **Citations:** Every factual claim has a citation. [UNCITED] marks practitioner consensus without academic backing.

---

## Table of Contents
[auto-generate from sections]
```

### Sections:

**1. Trading Strategy Research (~250 lines)**

Quick Reference table: every strategy decision with finding, citation, effect size, confidence.

Deep Dive prose covering:
- Pullback-in-uptrend: what it is mechanically, why it works (behavioral explanation + academic evidence), S&P 100 applicability, expected parameters (win rate, R:R, holding period), what conditions break it
- Mean reversion RSI(2): Connors' original research, why RSI(2) not RSI(14), the 200 EMA filter and why it matters, expected performance, regime sensitivity, how it complements pullback (ρ ≈ −0.35)
- Why PEAD is dead for large caps: the full story from Jegadeesh & Titman through Martineau 2022 and Subrahmanyam 2025, what killed it (ETF arbitrage, speed), why we still use earnings data as context
- Exit management: the disposition effect (Shefrin & Statman), why mechanical beats discretionary for systematic traders, ATR-based stops vs percentage stops, time-based tightening evidence, when LLM exits become viable (200+ trades)
- Position sizing: Kelly criterion derivation (intuitive, not just formula), why fractional Kelly (½K or ¼K), the small account problem, how sizing changes by capital tier
- Options: why naked options destroy small accounts (the math), vertical spread minimum capital derivation, theta drag, bid-ask drag for S&P 100 options
- Portfolio construction: why equal weight beats optimization at small N (DeMiguel et al. 2009), Herfindahl index targets by tier, concentration vs diversification paradox

**2. Data & Signal Research (~200 lines)**

Quick Reference: every signal dimension with orthogonality assessment, evidence, data source, refresh rate.

Deep Dive:
- The orthogonality thesis: why 8 independent dimensions beats 20 correlated ones, eigenvalue intuition, Trading-R1's empirical validation
- Each of the 7-8 orthogonal dimensions: what it measures, why it works for this holding period, the specific paper(s), the effect size, and critically — what would make it stop working
- The anti-recommendations: why Google Trends, Reddit sentiment, congressional trading, short interest DON'T work for S&P 100 mega-caps (with the specific evidence for each)
- McLean & Pontiff (2015): the full story of post-publication anomaly decay, what 58% means in practice, implications for signal selection
- API stack economics: binding constraints, optimal allocation of FMP's 250/day, why Finnhub free tier is underutilized
- The 4-tier scanning cadence: information half-life concept, why position monitoring ≠ universe scanning, staleness thresholds and the reasoning behind each

**3. LLM Training Pipeline Research (~250 lines)**

Quick Reference: every training decision with finding, citation, confidence.

Deep Dive:
- Self-blinding: WHY LLMs can't "pretend they don't know" (the cognitive science, Christian & Mazor 2026), how the 2-call architecture solves it, the TF-IDF leakage test and why 55% is the threshold
- Training format: the token budget constraint and what it means for information density, XML vs JSON vs natural language (evidence), random source subsetting (Trading-R1's approach and why we adopt it)
- Quality rubric: each of the 6 dimensions explained, why thesis clarity gets 25% weight, how to use the rubric, calibration examples
- Outcome-conditioned generation: why the same prompt for all outcomes is wrong, how contrastive pairs create natural DPO data, the 3-5x yield math
- Curriculum learning: structure → evidence → decision, why this order matters, what happens if you skip stages
- Model degradation: Shumailov et al.'s model collapse finding, the golden ratio (62/38), why you retrain from clean base, champion-challenger evaluation framework
- GRPO: what it is (vs PPO, DPO), why it works on consumer GPU (Unsloth), why 100+ trades is the minimum, the reward function design for financial reasoning

**4. Model Architecture Research (~150 lines)**

Quick Reference: model selection, quantization, training stack decisions.

Deep Dive:
- Why Qwen3 8B: tokenizer comparison, financial term handling, the 8B sweet spot on 12GB VRAM, alternatives considered and rejected
- Quantization: why Q8_0 not Q4_0 (precision matters for financial reasoning), the specific quality degradation measurements
- Training stack: PEFT + TRL + BitsAndBytes, why not Unsloth for training (OOM on 12GB), why Unsloth IS viable for GRPO
- Inference: Ollama architecture, why 47s/packet is slower than expected, optimization paths
- Hardware scaling: what each GPU tier unlocks (12GB → 24GB → 48GB), when multi-GPU becomes necessary, cloud burst vs local tradeoffs

**5. Risk & Portfolio Construction Research (~200 lines)**

Quick Reference: risk parameters with evidence.

Deep Dive:
- ATR-based stop widening: the VIX regime framework (Normal/Elevated/Crisis), why 2.0/2.5/3.0× specifically, the Kaminski & Lo (2014) stop-loss effectiveness research
- Position sizing by capital tier: the full progression from $5K to $5M with reasoning at each step
- Stress testing: what 2008/2020/2022 scenarios test (different failure modes), survivorship bias and how to handle it honestly
- The small account problem: why $5K with 1% risk on $500 stocks is mechanically challenging, fractional shares as solution, when dollar amounts start to matter
- Correlation management: sector concentration limits, why 30% max, the industrial concentration problem from our log review

**6. Competitive Landscape (~150 lines)**

Quick Reference: competitor matrix.

Deep Dive:
- Trading-R1: the closest blueprint — what they did, their results (Sharpe 2.72), what we can learn, where we diverge
- Renaissance/Two Sigma/DE Shaw: what they do better (and whether it matters at our scale), structural weaknesses we exploit
- The insurgent advantage thesis: decision speed 10-100×, cost 500:1, transparency, experimental velocity
- What would kill this thesis: conditions under which large funds could replicate our approach faster than we can scale

**7. Business & Fund Formation Research (~150 lines)**

Quick Reference: revenue milestones and fund economics.

Deep Dive:
- Fund economics: the $2M AUM break-even math, 1.5%+17.5% fee structure, why this and not 2/20
- Revenue sequencing: why signal marketplace before fund, Collective2 economics, RIA research services
- Alpha leakage: why publishing S&P 100 swing signals has effectively zero market impact (the capacity math)
- Regulatory landscape: publisher's exclusion, SEC AI-washing enforcement, FINRA 24-09, what changes with fund formation
- The "quit the day job" math: capital injection modeling, at what AUM trading income exceeds salary

**8. Flywheel & Moat Research (~120 lines)**

Quick Reference: flywheel components and velocity metrics.

Deep Dive:
- The compounding loop explained: each link, the friction in each handoff, the fixes
- Why training data quality is the moat (not the model, not the returns): the replicability analysis
- Data degradation: the 6-12 month half-life finding, what happens during bear market silence, why mean reversion is flywheel insurance
- GPU utilization: the Kingman's formula intuition, why 75% is the ceiling, the priority stack

**9. Open Questions & Research Agenda (~60 lines)**

Table of unresolved questions, ranked by impact, with:
- The question
- Current best guess
- What evidence would resolve it
- When we'll have enough data to answer
- Which sprint addresses it

**10. Citation Index (~150 lines)**

Every paper cited, organized by topic:
```markdown
### Trading Strategy
- **Shefrin & Statman (1985)** "The Disposition to Sell Winners Too Early and Ride Losers Too Long" *J. Finance*. Disposition effect: investors sell winners 1.5x faster than losers. → Informs mechanical exit decision.
- **Odean (1998)** "Are Investors Reluctant to Realize Their Losses?" *J. Finance*. Individual investor loss aversion quantified. → Supports systematic over discretionary.
...
```

---

## Phase 4: Quality checks before PR

Before submitting:
- [ ] Every factual claim has a citation or explicit `[UNCITED — practitioner consensus]` marker
- [ ] Every Quick Reference table can be read independently (agent doesn't need the prose)
- [ ] Every Deep Dive section teaches, not just states (Ryan can learn from reading it)
- [ ] /research findings integrated — note where they update or contradict existing corpus
- [ ] No newsletter/subscriber references anywhere (fund AUM model only)
- [ ] Effect sizes included wherever the paper reports them
- [ ] Confidence levels (HIGH/MEDIUM/LOW) on every major decision
- [ ] Open questions section is honest about what we don't know
- [ ] Citation index is complete and organized by topic

## Phase 5: Submit PR

```bash
git checkout -b docs/research-framework
git add docs/research/ARCIS_RESEARCH_FRAMEWORK.md
git commit -m "docs: Arcis Research Framework — master synthesis of 60+ research documents

Two-tier structure: Quick Reference tables (agent lookup) + Deep Dive prose (human study).
Validated with N /research queries filling gaps in: [topics].
10 sections, ~X lines, ~Y citations."
git push origin docs/research-framework
```

Open PR with description noting:
- Total line count
- Number of /research queries run and what they found
- Any findings that contradict or update the existing research corpus
- Any papers discovered by /research that should be added to the project knowledge

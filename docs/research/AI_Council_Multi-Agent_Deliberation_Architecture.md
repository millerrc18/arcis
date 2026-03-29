# Multi-agent AI deliberation architectures for autonomous equity trading

**A 7-agent "AI Council" using Claude API calls is technically viable and architecturally well-supported by recent research, but the design choices matter far more than the agent count.** The most critical finding across the literature is that **agent diversity trumps agent quantity** — two genuinely heterogeneous agents can outperform sixteen homogeneous ones. For Halcyon Lab's council, this means the system prompt engineering, deliberation protocol, and failure-mode mitigations are where the real alpha lives, not the number of seats at the table. The cost is remarkably low (~$0.16–$0.47 per deliberation session), and parallel API calls compress latency to 3–6 seconds per full 3-round deliberation. Several published multi-agent trading systems — most notably TradingAgents (AAAI 2025) and FinCon (NeurIPS 2024) — validate the council architecture with empirical outperformance over single-agent and traditional baselines.

---

## 1. The academic landscape for multi-agent LLM deliberation

### Core architecture patterns and their evidence base

Six distinct patterns dominate the literature, each with different strengths for financial decision-making:

**Multi-Agent Debate (MAD)** is the most studied pattern. Du et al. (2023, "Improving Factuality and Reasoning in Language Models through Multiagent Debate," ICML 2024) established the canonical setup: 3 agents generate independent responses, read each other's outputs, and revise over 2 rounds. They demonstrated improvements on arithmetic, GSM8K, MMLU, and biography factuality benchmarks. However, a comprehensive ICLR 2025 evaluation of 5 MAD frameworks across 9 benchmarks found that **current MAD frameworks fail to consistently outperform simpler strategies** like self-consistency — GPT-4o-mini achieved 82.13% on MMLU with self-consistency versus just 74.73% with MAD. Smit et al. (2024, "Should we be going MAD?," ICML 2024) confirmed this, noting MAD is "more sensitive to hyperparameter settings and difficult to optimize." The most theoretically rigorous result comes from "Debate or Vote" (arXiv:2508.17536, NeurIPS 2025), which **proves multi-agent debate is a martingale** over agents' beliefs — meaning the expected belief remains unchanged across debate rounds, and "majority vote does essentially all the work."

**LLM-as-Jury systems** use panels of diverse model judges. Verga et al. (2024, "Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models," arXiv:2404.18796) showed a diverse panel of smaller models outperforms a single large judge while reducing intra-model bias. Li et al. (2025, "LLM Jury-on-Demand," arXiv:2512.01786) extended this with dynamic reliability predictors that achieve higher correlation with human judgment than static juries.

**Adversarial deliberation** assigns agents opposing roles. The foundational work is Irving, Christiano, and Amodei (2018, "AI Safety via Debate," arXiv:1805.00899), proposing debate as a safety technique. Liang et al. (2023, "Encouraging Divergent Thinking in LLMs through Multi-Agent Debate," EMNLP 2024) operationalized this with affirmative/negative debaters plus a judge, identifying the "Degeneration-of-Thought (DoT)" problem where LLMs lock into confident but incorrect positions. Khan et al. (2024, "Debating with more persuasive LLMs leads to more truthful answers," arXiv:2402.06782) showed debate improves truthfulness when the stronger model argues for correctness, but warned that "vivid but incorrect arguments can override correct ones."

**The Delphi method adapted for LLMs** mirrors anonymous independent assessment → share → revise. The Iterative Consensus Ensemble (ICE, 2025) raised GPQA-diamond performance from **46.9% to 68.2%** (a 45% relative gain) using this pattern. DelphiAgent (2025, ScienceDirect) achieved macF1 improvements up to 6.84% on fact verification through multi-personality Delphi workflows. The Delphi approach naturally maps to the independence-first principle that research consistently endorses.

**Society of Mind approaches** use specialized agents. The Mixture of Agents (MoA) pattern orchestrates multiple LLMs in layered structures. The CIR3 framework (Collective Intentional Reading through Reflection and Refinement) uses specialized roles including a "curmudgeon" as disruptive signal, improving QA comprehensiveness by +23 points and faithfulness by +17 points. A-HMAD (Adaptive Heterogeneous Multi-Agent Debate, 2025, Springer) found heterogeneous agents consistently outperform homogeneous configurations.

**Deliberative Council Intelligence (DCI)** is the newest and most directly relevant pattern (arXiv:2603.11781, 2025). It introduces typed epistemic interactions — agents exchange structured reasoning moves (propose, challenge, bridge, synthesize) rather than undifferentiated text, with explicit tension preservation and guaranteed procedural closure. DCI showed significant improvement over unstructured debate on non-routine tasks.

### Major multi-agent frameworks

**AutoGen** (Wu et al., 2023, Microsoft, arXiv:2308.08155) provides the most flexible multi-agent conversation framework, achieving #1 accuracy on the GAIA benchmark. Its GroupChat pattern supports deliberation, but "a 4-agent debate with 5 rounds is 20 LLM calls minimum." **MetaGPT** (Hong et al., 2023, ICLR 2024) encodes Standardized Operating Procedures into prompt sequences, achieving 85.9% Pass@1 on HumanEval and reducing cascading hallucinations through structured intermediate outputs. **CrewAI** offers the fastest prototyping with role-based agent design and claims 5.76× speed over LangGraph, but production teams often migrate to **LangGraph** for its superior observability (LangSmith integration), checkpointing, and cyclic graph support for iterative debate. **ChatEval** (Chan et al., 2023, ICLR 2024) demonstrated that diverse role prompts are essential — using identical role descriptions degrades multi-agent performance to single-agent levels.

For Halcyon Lab's specific needs (structured deliberation with fixed agents and rounds), **a custom implementation** of ~200 lines using `AsyncAnthropic` + `asyncio.gather` is recommended over any framework. The deliberation pattern is too well-structured to benefit from framework flexibility, and the overhead of AutoGen or CrewAI adds complexity without proportional value.

---

## 2. Published multi-agent trading systems validate the council architecture

### TradingAgents is the closest architectural precedent

**TradingAgents** (Xiao et al., 2024, "TradingAgents: Multi-Agents LLM Financial Trading Framework," AAAI 2025, UCLA/MIT) is the most directly relevant system. It simulates a full trading firm with **7 distinct agent roles**: Fundamentals Analyst, Sentiment Analyst, News Analyst, Technical Analyst, Bull Researcher, Bear Researcher, and Risk Manager. The deliberation follows five stages: concurrent analyst data gathering → adversarial bull/bear debate → trader synthesis → risk management assessment → fund manager approval. Built on LangGraph and using the ReAct prompting framework, it outperformed Buy & Hold, MACD, and other baselines on **cumulative return, Sharpe ratio, and maximum drawdown** across AAPL, NVDA, MSFT, META, GOOGL, and AMZN from January to November 2024. The codebase is open-source at github.com/TauricResearch/TradingAgents.

**FinCon** (Yu et al., 2024, NeurIPS 2024 main conference) employs a manager-analyst hierarchy inspired by real investment firms, with **7 types of analyst agents** feeding a manager agent. Its key innovation is **Conceptual Verbal Reinforcement (CVRF)** — updating "investment beliefs" episodically and propagating them selectively. FinCon outperformed all baselines including DRL agents (A2C, PPO, DQN) and LLM agents (FinGPT, FinMem, FinAgent) on cumulative return and Sharpe ratio.

**RAPTOR** (submitted to NeurIPS 2025) advances the architecture with bull/bear cross-examination, calibrated **Black-Litterman portfolio integration**, and persistent structured memory. It achieved a **Sharpe ratio of 1.0** over an 8-month backtest. An Orchestration Framework for Financial Agents (Li, Grover et al., NeurIPS 2025 Workshop) maps the entire algorithmic trading pipeline to specialized agents using MCP and A2A protocols, with different LLMs (GPT-4o, Llama3, FinGPT) powering different roles.

### Institutional investment committees provide structural validation

Real investment committees typically seat **3–7 voting members**, with a CIO (often non-voting), analysts providing research, and external advisors. Most use **majority voting**, though Harvard Business School research (Working Paper 21-131, "Catching Outliers") revealed that a majority of the 50 largest U.S. VC firms use a "champions voting rule" for early-stage investments — a single partner's conviction can greenlight a deal, since majority rule results in "mush in the middle." Later-stage investments shift to consensus-based voting.

**Bridgewater Associates** pioneered algorithmic decision-weighting through its **"Dot Collector"** app and "believability-weighted" voting, where more credible individuals (proven track record on a topic) get greater weight. Ray Dalio's framework — "collective decision-making is so much better than individual decision-making if it's done well" — directly informs AI council design. Bridgewater's AIA Labs AI-driven strategy has surpassed **$5 billion AUM** as of 2026. **BlackRock Systematic** ($336B AUM, 230 people) uses ML and LLMs for forecasting, with ~90% of funds outperforming peer medians over 5 years.

### The wisdom of crowds literature sets important constraints

Schoenegger et al. (2024, "Wisdom of the Silicon Crowd," Science Advances) demonstrated an ensemble of **12 diverse LLMs** was statistically indistinguishable from **925 human forecasters** in a 3-month tournament. However, Abels et al. (2025, "Wisdom from Diversity," arXiv:2505.12349) found LLMs exhibit **much higher inter-correlation** (Q-statistic ~0.855) than humans, meaning simply averaging outputs from the same model can amplify shared biases. Chen et al. (2024, "Are More LLM Calls All You Need?," NeurIPS 2024) proved performance **first increases, then decreases** with the number of LLM calls — more calls help on easy queries but hurt on hard ones. **An optimal number exists and can be estimated from a small sample.**

---

## 3. Why 5 agents may beat 7, and how to engineer genuine diversity

### The empirical case for council sizing

A-HMAD (2025, Journal of King Saud University Computer and Information Sciences) provides the most explicit scaling data on arithmetic tasks: **1 agent: 72%, 3 agents: 87% (+15pp), 5 agents: 90% (+3pp), 7 agents: 91% (+1pp)**. The jump from 1→3 is massive, 3→5 is moderate, and 5→7 is marginal. Du et al. (2023) chose 3 agents and 2 rounds as the cost-optimal configuration. The Condorcet Jury Theorem predicts monotonic improvement with independent voters of accuracy >0.5, but its key assumption — **independence** — is violated when agents share the same base model.

The strongest finding comes from "Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity" (arXiv:2602.03794, 2025): **L4 (full diversity) with just 2 agents surpasses L1 (no diversity) with 16 agents** — an 8× reduction. This means Halcyon Lab's 7-agent council is defensible only if the system prompts generate genuinely diverse reasoning, not just differently-worded agreement.

### Engineering diversity from the same base model

Research converges on a hierarchy of diversity levers:

- **Best: Different base models** (e.g., Claude + GPT + Gemini). ICLR 2025 showed combining GPT-4o-mini + Llama3.1-70b achieved 88.2% on MMLU versus 84.2% for Llama-only or 82.1% for GPT-only. Since Halcyon Lab commits to Claude-only, this lever is unavailable, making the others critical.
- **Good: Distinct professional personas with domain expertise.** ChatEval (ICLR 2024) proved diverse role prompts are essential — identical descriptions degrade to single-agent performance. Solo Performance Prompting (Wang et al., 2023, arXiv:2307.05300) showed fine-grained personas improve problem-solving, but only in GPT-4-class models.
- **Moderate: Temperature ≥0.7.** At temperature 0, all N samples are mathematically identical — "voting among clones just amplifies a single hallucination." However, "Wisdom of the Machines" (2025) found temperature-induced diversity introduces more noise than signal; model diversity is more effective. A practical range of **T=0.7–1.0** balances creativity and coherence.
- **Additional: Information asymmetry.** Giving agents different data subsets is under-explored but theoretically promising. The Risk Manager could see portfolio exposure data; the Alpha Strategist could see momentum signals; the Market Regime Analyst could see macro indicators.
- **Marginal: Fine-grained persona backstories** add minimal additional value over coarse role descriptions (arXiv:2505.17390).

### The Devil's Advocate should rotate, not be permanent

Nemeth et al. (2001, European Journal of Social Psychology) established that **"authentic dissent" is more effective than role-played devil's advocacy** — DA tends to produce cognitive bolstering of the initial viewpoint rather than genuine divergent thought. MIT Sloan Management Review (2024) found teams with a critical reviewer improved meeting effectiveness by **33%** and decision quality by **23%**. However, Kreitner and Kinicki (2010) warn permanent devil's advocates develop a "negative reputation" and get dismissed. Schweiger et al. (1986, Academy of Management Journal) found **dialectical inquiry** — where two teams develop full alternative plans — outperforms simple devil's advocacy.

For Halcyon Lab, the recommended approach is to **rotate the Devil's Advocate role** across agents each session, using a system prompt modifier that instructs the designated agent to steel-man the opposing position and identify failure modes. The permanent "Devil's Advocate" agent role should focus on risk identification and assumption-challenging rather than reflexive opposition.

---

## 4. The optimal deliberation protocol is Delphi-like with structured moves

### Two to three rounds capture nearly all the value

Across virtually all research, **2–3 rounds of deliberation represent the sweet spot**. Du et al. (2023) used 2 rounds as default. Wu et al. (2025, "Can LLM Agents Really Debate?," arXiv:2511.07784) recommended "limit debate depth to one pass unless stability demands more." The martingale proof from "Debate or Vote" (NeurIPS 2025) formally demonstrates that the initial diverse sampling contributes more than iterative refinement. HAJailBench (2025) confirmed "a small number of debate rounds is sufficient to capture most of the gain."

### The recommended Halcyon Lab protocol

Based on the DCI framework and converging evidence:

1. **Round 0 — Independent assessment.** All 7 agents receive the question and relevant data simultaneously, generate positions independently with **no access to other agents' outputs**. This enforces the structural independence that CJT requires.
2. **Round 1 — Structured critique.** All agents receive anonymized summaries of Round 0 positions. Each agent uses typed epistemic moves: agree/disagree with justification, challenge assumptions, or propose synthesis. Presentation order is randomized.
3. **Round 2 — Final position.** Agents incorporate feedback, may update votes, and submit final confidence-weighted positions. Early termination if 5/7 supermajority is reached with average confidence >0.7.
4. **Aggregation — Confidence-weighted majority vote.** Ties broken by highest-confidence agent, then fresh judge agent.

### Confidence-weighted voting is theoretically optimal

Meyen et al. (2021, "Group Decisions based on Confidence Weighted Majority Voting," Cognitive Research: Principles and Implications) proved CWMV is the theoretically optimal aggregation method (per Grofman et al. 1983; Nitzan & Paroush 1982). Kaesberg et al. (2025, "Voting or Consensus?," ACL Findings) systematically compared 4 voting and 3 consensus protocols: **simple and ranked voting showed the strongest improvements (~3.3% over baseline)** on reasoning tasks, while consensus protocols performed better on knowledge tasks. Cumulative voting, supermajority, and unanimity performed slightly worse overall.

For Halcyon Lab, use **simple majority (4/7) for routine rebalancing decisions** and **supermajority (5/7) for high-stakes decisions** (regime changes, new position entries, significant allocation shifts). Unanimity is counterproductive — human jury research shows it can increase probability of false outcomes (Feddersen & Pesendorfer). **Confidence scores should use log-odds weighting** rather than linear scaling, and scores must be calibrated since LLMs are generally overconfident.

---

## 5. Failure modes demand specific architectural countermeasures

### Groupthink and monoculture collapse

When multiple agents share the same base model, they exhibit **correlated strategies and failure modes** — a phenomenon Reid et al. (2025, "Risk Analysis Techniques for Governed LLM-based Multi-Agent Systems," arXiv:2508.05687, Gradient Institute) term "monoculture collapse." Estornell and Liu (NeurIPS 2024) formally proved that with similar models, debate can stagnate into static dynamics where all agents repeat the majority opinion. The DReaMAD framework (Oh et al., 2025) confirmed debate amplifies model biases rather than correcting them when agents share reasoning patterns.

**Mitigations:** Assign maximally distinct persona prompts with different analytical frameworks (quantitative vs. qualitative, short-term vs. long-term, momentum vs. mean-reversion). Use information asymmetry — each agent sees different data subsets. Employ Estornell and Liu's diversity-pruning algorithm to remove overly similar responses each round.

### Sycophancy cascades

Sharma et al. (ICLR 2024, "Towards Understanding Sycophancy in Language Models," Anthropic) demonstrated all major AI assistants consistently exhibit sycophancy, driven partly by RLHF training that rewards agreeable responses. In multi-agent settings, this manifests as agents deferring to the apparent majority. The ELEPHANT benchmark (Cheng et al., 2025) found LLMs preserve conversational face **45 percentage points more than humans**.

**Mitigations:** Enforce independent Round 0 before any information sharing. Use explicit anti-sycophancy instructions: "Maintain your independent assessment even if it contradicts the majority. Your value comes from providing a genuinely different perspective." The CAUSM framework (ICLR 2025) proposes causal head reweighting to address sycophancy at the model level. Contrastive Activation Addition (Rimsky et al., 2023) can steer representations toward less sycophantic directions.

### Anchoring bias from first response

Lou and Sun (2024) found LLMs exhibit strong anchoring bias where initial information disproportionately influences subsequent judgments, and "simple Chain-of-Thought or Reflection fail to fully resolve" this. Political debate research (arXiv:2506.11825) confirmed speaking order significantly shifts outcomes.

**Mitigations:** **Randomize presentation order** in Round 1 — each agent sees peers' responses in a different shuffled order. Use the Delphi method's anonymization so agents don't know which role produced which argument. Require agents to "first summarize key findings and only then generate a differential" (two-step prompting from Nature Digital Medicine, 2025).

### Information cascades and confidence contagion

"Talk Isn't Always Cheap" (arXiv:2509.05396) showed multi-agent debate can degrade performance, with **correct answers becoming corrupted during debate**. Wu et al. (2025) found "majority pressure suppresses agents' independent correction" — when most agents hold the wrong answer, correct minority agents capitulate. Critically, **hiding confidence scores is generally preferred** — making them visible induces over-confidence cascades.

**Mitigations:** Collect blind votes in Round 0 before any discussion. Do not share confidence scores between agents during deliberation — only use them for final aggregation. Maintain a "moderate level of contradiction between agents" through dynamic disagreement regulation (Chang, 2024). The CIR3 framework's curmudgeon agent serves as variation-maintenance mechanism.

### Verbosity dominance

Saito (2023, "Verbosity Bias in Preference Labeling by Large Language Models," arXiv:2310.10076) showed GPT-4 systematically prefers longer responses. **GPT-4o prefers longer completions 85% of the time** even from the same model. In multi-agent deliberation, a verbose but incorrect agent can receive disproportionate weight.

**Mitigations:** Use **structured JSON output** (not free-form text) for votes and reasoning, enforcing a fixed schema with character limits. Evaluate information density (quality per token) rather than response length. Include explicit instructions: "Concise reasoning is valued over verbose explanations."

---

## 6. Implementation architecture delivers $0.16/session with 3-second latency

### Cost analysis for the 7-agent council

Using current Claude API pricing (March 2026) with estimated token usage of 2,500 input + 1,000 output tokens per agent per round:

| Model | Per Session (7×3) | Monthly (daily) | With Batch API | With Prompt Caching |
|-------|-------------------|-----------------|----------------|---------------------|
| **Haiku 4.5** ($1/$5 MTok) | **$0.158** | $4.73 | $2.37 | ~$3.50 |
| **Sonnet 4.5** ($3/$15 MTok) | **$0.473** | $14.18 | $7.09 | ~$10.50 |
| Mixed (5 Haiku + 2 Sonnet) | **$0.26** | $7.80 | $3.90 | ~$5.70 |

**Prompt caching** offers 90% savings on shared context (system prompts cached across agents at 0.1× base price). **Batch API** provides 50% discount with a 24-hour processing window (suitable for non-urgent scheduled deliberations). Combined, these can reduce costs by up to 95%.

### Parallel execution compresses latency dramatically

Using `AsyncAnthropic` with `asyncio.gather`, all 7 agents run concurrently within each round. With Haiku's ~1-second response time, a full 3-round deliberation completes in **~3 seconds** (versus ~21 seconds sequential). Even Tier 1 rate limits (50 RPM) comfortably handle 7 concurrent requests. Cached tokens don't count toward input token-per-minute limits, effectively multiplying throughput.

```python
async def run_deliberation_round(agents: list, context: str) -> list:
    tasks = [run_agent(agent, context) for agent in agents]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

### Structured output enforcement

Claude 4.5+ supports **native structured outputs** via `output_config.format` with JSON schema, guaranteeing valid responses:

```python
response = await client.messages.create(
    model="claude-haiku-4-5-20250929",
    max_tokens=1024,
    system=agent_system_prompt,
    messages=[{"role": "user", "content": context}],
    output_config={
        "format": {
            "type": "json_schema",
            "json_schema": {
                "name": "deliberation_vote",
                "schema": {
                    "type": "object",
                    "properties": {
                        "vote": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reasoning": {"type": "string"},
                        "risk_assessment": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                        "key_factors": {"type": "array", "items": {"type": "string"}},
                        "dissenting_considerations": {"type": "string"}
                    },
                    "required": ["vote", "confidence", "reasoning", "risk_assessment", "key_factors"]
                }
            }
        }
    }
)
```

An alternative is forced tool calling (`tool_choice={"type": "tool", "name": "submit_vote"}`), but this adds ~300–500 overhead tokens per request.

### SQLite audit trail for compliance

The schema captures every deliberation artifact for regulatory compliance (financial services typically require 7+ year retention):

```sql
CREATE TABLE deliberation_sessions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    question TEXT NOT NULL,
    context_data TEXT,        -- JSON: market data, signals
    final_decision TEXT,      -- BUY/SELL/HOLD
    final_confidence REAL,
    consensus_reached BOOLEAN,
    total_rounds INTEGER,
    total_cost_usd REAL,
    metadata TEXT
);

CREATE TABLE deliberation_votes (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES deliberation_sessions(id),
    agent_name TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    vote TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    risk_assessment TEXT,
    key_factors TEXT,          -- JSON array
    dissenting_considerations TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER,
    raw_response TEXT,         -- Full API response
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

All vote records should be **append-only** — never update or delete for audit integrity. A FastAPI SSE endpoint enables real-time dashboard streaming of deliberation progress.

---

## 7. Decision scope should follow a tiered autonomy model

### Which decisions warrant council deliberation

Multi-agent deliberation is most valuable for **high-ambiguity, high-stakes, multi-dimensional decisions** where evidence is conflicting or incomplete (what the DCI framework calls "hidden profile tasks"). It adds limited value for well-defined tasks with clear correct answers.

For Halcyon Lab, a tiered decision framework:

| Decision Type | Council Role | Human Override |
|---|---|---|
| **Regime change detection** (bull→bear, sector rotation) | Full 3-round deliberation, supermajority (5/7) required | Yes — must confirm |
| **New position entry / significant reallocation** (>5% portfolio) | Full deliberation, simple majority (4/7) | Yes — must confirm |
| **Routine rebalancing** (within ±2% drift bands) | 1-round vote, simple majority | No — auto-execute with audit |
| **Stop-loss / risk limit triggers** | Bypass council — auto-execute | Alert only |
| **Daily portfolio review** | Abbreviated 1-round assessment | No — informational |

### Event-triggered over fixed schedules

Research converges on **event-triggered deliberation** over fixed schedules. The council should convene when: volatility exceeds threshold, portfolio drift exceeds bands, macro regime indicators shift, or a risk limit approaches breach. Periodic reviews (daily or weekly depending on strategy frequency) supplement event triggers. Maintain **10–15% escalation rates** for sustainable human-in-the-loop operations (Galileo, 2025).

### Decision fatigue has an LLM analog

While LLMs don't experience biological fatigue, **context window degradation** serves as an analog — performance degrades as context grows. Each deliberation session should use fresh context windows rather than accumulating history. Stanford HAI (2024) found heavy AI delegation reduced human ability to identify novel solutions by 37%, suggesting the council should support, not replace, human strategic judgment for the highest-stakes decisions.

---

## Conclusion: design principles for Halcyon Lab's AI Council

The research supports five core design principles. First, **independence before deliberation** — the Delphi-like pattern of blind independent assessment followed by structured critique consistently outperforms real-time debate. Round 0 must enforce complete isolation between agents. Second, **diversity is the system's immune system** — since all agents share Claude's base model, the system prompts must create maximally distinct analytical frameworks, and information asymmetry (different data feeds per agent) is the strongest available lever. The 7-agent count is defensible but operates at the diminishing-returns boundary; 5 well-differentiated agents would likely perform comparably at lower cost. Third, **structured moves over free-form debate** — the DCI framework's typed epistemic acts (propose, challenge, bridge, synthesize) outperform unstructured text exchange, and JSON-schema-enforced outputs prevent verbosity dominance. Fourth, **confidence-weighted majority voting with hidden scores during deliberation** — share confidence scores only at aggregation time to prevent cascade effects. Fifth, **the Devil's Advocate role should rotate** — permanent contrarians get dismissed, but rotating the dissenter prompt across agents each session maintains productive tension.

The most counterintuitive finding is that the initial diverse sampling matters more than the debate itself — the martingale proof suggests investing engineering effort in Round 0 diversity will yield more than optimizing Rounds 1–2. For a Claude-only system, this means the 7 system prompts are the single most important design artifact. Each should embody a fundamentally different analytical lens: the Risk Manager should think in terms of tail risks and drawdown protection; the Alpha Strategist in momentum and factor exposures; the Data Scientist in statistical significance and data quality; the Market Regime Analyst in macro cycles and cross-asset correlations; the Operations Officer in execution costs and liquidity; the Portfolio Architect in diversification and correlation structure; and the rotating Devil's Advocate in assumption-challenging and failure-mode identification. This is where Halcyon Lab's intellectual property lives — not in the orchestration code, which is ~200 lines of Python, but in the cognitive architecture encoded in those prompts.
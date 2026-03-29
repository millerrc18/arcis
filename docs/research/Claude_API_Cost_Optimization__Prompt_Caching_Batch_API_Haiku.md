# Cutting Halcyon Lab's Claude bill by 60%

**Your $20–30/month Sonnet spend can drop to roughly $10–14 by stacking three levers: prompt caching on your council sessions, the Batch API for overnight work, and Haiku 4.5 for scoring and generation tasks.** The combined effect of these optimizations is multiplicative, not additive—cached batch reads on Sonnet 4.6 cost just 5% of standard input pricing. More importantly, Haiku 4.5 now benchmarks within striking distance of Sonnet on structured evaluation tasks, making it a credible choice for 80% of your token volume. Here's the full breakdown with March 2026 pricing, exact cost math, and the architectural decisions that matter.

---

## Current pricing and the three discount levers

All prices below are confirmed as of March 2026 across Anthropic's official documentation and multiple third-party sources. The Sonnet tier has held steady at **$3/$15 per million input/output tokens** across four generations. Haiku 4.5 sits at **$1/$5**, and the newly affordable Opus 4.6 at **$5/$25** (a 67% cut from the old Opus 4.1 at $15/$75).

| Model | Standard Input | Standard Output | Batch Input | Batch Output | Cache Read (standard) | Cache Read (batch) |
|---|---|---|---|---|---|---|
| **Sonnet 4.6** | $3.00 | $15.00 | $1.50 | $7.50 | $0.30 | $0.15 |
| **Haiku 4.5** | $1.00 | $5.00 | $0.50 | $2.50 | $0.10 | $0.05 |
| **Opus 4.6** | $5.00 | $25.00 | $2.50 | $12.50 | $0.50 | $0.25 |

The three discount mechanisms are:

- **Prompt caching**: Cache reads cost **0.1× base input** (90% cheaper). Cache writes cost 1.25× for a 5-minute TTL or 2× for a 1-hour TTL. Break-even occurs after just **two cache reads**.
- **Batch API**: A flat **50% discount** on all tokens, both input and output, in exchange for asynchronous processing within 24 hours (most batches complete in under an hour).
- **Combined**: These discounts stack multiplicatively. A cached read inside a batch request costs **0.1 × 0.5 = 0.05× the standard input price**, yielding **95% savings** on that portion of input tokens.

Extended thinking tokens are billed at the model's **output rate**—$15/MTok for Sonnet 4.6, $5/MTok for Haiku 4.5—with no separate pricing tier. You set a budget (minimum 1,024 tokens) and pay for actual usage.

---

## Prompt caching mechanics and your council architecture

Anthropic's prompt caching stores key-value representations of your prompt prefix in memory. The system uses **cryptographic hashing with exact prefix matching**: tools are processed first, then system messages, then conversation history. Even a single character difference—an extra space, a changed timestamp—produces a cache miss.

**Minimum cacheable token thresholds** are critical for Halcyon Lab:

| Model | Minimum Tokens |
|---|---|
| Sonnet 4.6 | **2,048** |
| Haiku 4.5 | **4,096** |
| Opus 4.6 | 4,096 |

This threshold has a direct consequence: your **500-token scoring system prompt** and **800-token generation system prompt** are both below the minimum for every model. Caching simply won't activate on these prompts—it fails silently with no error, just zero cache hits. To enable caching on batch tasks, you'd need to expand system prompts to meet the threshold, for instance by embedding few-shot examples or detailed rubrics into the system prompt itself.

For the council sessions, caching works perfectly. With 5 agents sharing an identical system prompt of **10K+ tokens** (well above the 2,048 minimum for Sonnet 4.6), you implement it by placing `cache_control: {"type": "ephemeral"}` on the system prompt block. The first agent's request writes to cache; agents 2–5 get cache reads at 90% off. One essential timing detail: **the cache entry only becomes available after the first response begins streaming**, so fire agent 1 first, wait for the stream to start, then launch agents 2–5 in parallel.

Never inject dynamic data (timestamps, current prices, portfolio state) into the cached system prompt. Instead, append dynamic context as the user message, which sits after the cached prefix. The Claude Code team treats cache-breaking changes as severity incidents—their production system achieves **92–96% cache hit rates** with an **81% cost reduction**.

For batch processing, use **1-hour cache TTL** (`"ttl": "1h"`) because batch jobs typically take 5–60 minutes, making the default 5-minute TTL unreliable. The recommended pattern is to send a single "seed" request with the shared prefix and 1-hour cache, wait for completion, then submit the full batch.

---

## Batch API: overnight scoring and generation

The Message Batches API accepts up to **100,000 requests or 256 MB** per batch, processed asynchronously. Each request in the batch is independent—you can mix different models, different parameters, even different features (vision, tool use, extended thinking) in a single batch. Submit via `POST https://api.anthropic.com/v1/messages/batches` with a `requests` array, each containing a `custom_id` and standard Messages API `params`.

Results return as streamed JSONL, **not in input order**—always match by `custom_id`. If individual requests fail, you still get results for everything else. Each result carries one of four types: `succeeded`, `errored`, `canceled`, or `expired`. Only succeeded requests are billed. There's no built-in retry; you parse results, collect failed IDs, and resubmit.

For Halcyon Lab's overnight workloads, the practical implications are straightforward. A batch of 100 scoring requests and 20 generation requests is trivially small relative to the 100K limit. Both tasks can go in the **same batch** even if they use different models (Haiku for scoring, Sonnet for generation). Most batches of this size will complete in minutes, well within the 24-hour window.

---

## When Haiku 4.5 is enough and when it isn't

The question of whether Haiku can replace Sonnet for your scoring and generation tasks has a nuanced answer backed by recent benchmarks. On the Qodo PR benchmark (400 real GitHub PRs), Haiku 4.5 **outperformed Sonnet 4** with a 55% win rate and higher average quality scores. GitHub Copilot reports "comparable quality to Sonnet 4" for structured tasks. Anthropic's own data shows Haiku 4.5 achieves roughly **90% of Sonnet 4.5's performance** on agentic coding evaluations.

However, the gap widens dramatically on complex reasoning. On **GPQA Diamond** (graduate-level reasoning), Sonnet 3.5 scored 65% vs Haiku 3.5 at 41.6%—a **23-point gap**. On the FinanceReasoning benchmark (238 hard financial questions), the hierarchy is stark: Opus 4.6 at 87.8%, Sonnet 4.6 at 83.6%, and Sonnet 4 at 76.1%.

For your specific tasks:

- **Training data quality scoring** (rubric-based, structured output): Haiku 4.5 is likely sufficient. Research on smaller LLM-as-judge models shows that even 7B-parameter fine-tuned models achieve >90% agreement with GPT-4 judges when given explicit rubrics and low-precision scales. Your binary/ordinal scoring fits this pattern. The key is providing **clear rubrics and few-shot examples** in the prompt.
- **Self-blinded training data generation** (structured, schema-driven): Haiku 4.5 should handle this well. Well-defined output schemas keep smaller models on track. The capacity gap in knowledge distillation research suggests problems emerge only when the student model needs to capture subtle reasoning patterns the teacher exhibits.
- **"What could kill this trade?" adversarial analysis**: Keep this on Sonnet. Multi-step financial reasoning with scenario generation is precisely where the 20+ percentage-point quality gap emerges. Extended thinking amplifies this advantage—Sonnet with thinking showed **+16.8 percentage points** on GPQA Diamond (68% → 84.8%).
- **Modified Delphi council sessions**: Use Sonnet for all five agents, but consider enabling extended thinking **selectively** for the Devil's Advocate or risk-analysis agent. You can set the `thinking` parameter per-request, so one agent gets deep reasoning while others run in standard mode.

---

## Extended thinking: selective deployment beats blanket activation

Extended thinking tokens are billed as output tokens at the model's standard output rate. For Sonnet 4.6, that's **$15/MTok**—the same as regular output. The cost impact depends entirely on your thinking budget: a 4K thinking budget adds roughly $0.06 per request on Sonnet. The gains are enormous for the right tasks (243% improvement on math benchmarks, 25% on graduate reasoning) but negligible for classification or scoring.

Extended thinking works with prompt caching—cached system prompts remain valid when thinking parameters change. It also works with the Batch API; Anthropic specifically recommends batch processing for thinking budgets above 32K tokens. However, **changes to the thinking budget invalidate message-level cache entries** that include conversation history, so keep thinking parameters stable across requests.

For Halcyon Lab, the optimal strategy is to enable extended thinking only for the council agent performing adversarial risk analysis, with a modest budget of **4,000–8,000 tokens**. This adds ~$0.06–0.12 per day while providing meaningfully better reasoning on the highest-stakes question in your workflow. Don't enable it for scoring or generation tasks—the quality gain is minimal for structured output.

---

## Exact cost calculations for Halcyon Lab

### Scenario A: Daily council session (5 agents, real-time, Sonnet 4.6)

Assumptions: 10K shared system prompt tokens (cached), 5K unique tokens per agent, 2K output per agent.

| Component | Without caching | With caching |
|---|---|---|
| Agent 1 input (cache write) | — | 10K × $3.75/MTok = $0.0375 |
| Agent 1 uncached input | — | 5K × $3.00/MTok = $0.015 |
| Agents 2–5 input (cache read) | — | 10K × $0.30/MTok × 4 = $0.012 |
| Agents 2–5 uncached input | — | 5K × $3.00/MTok × 4 = $0.060 |
| All input (no caching) | 75K × $3.00/MTok = $0.225 | — |
| All output (5 × 2K) | 10K × $15.00/MTok = $0.150 | 10K × $15.00/MTok = $0.150 |
| **Daily total** | **$0.375** | **$0.275** |
| **Monthly (30 days)** | **$11.25** | **$8.24** |

Add **$0.06/day ($1.80/month)** if enabling extended thinking on one agent with a 4K token budget.

### Scenario B: 100 scoring examples via Batch API

Per example: ~1,300 input tokens, ~300 output tokens. No caching possible at 500-token system prompt.

| Model | Batch Input Cost | Batch Output Cost | **Daily Total** | **Monthly** |
|---|---|---|---|---|
| **Haiku 4.5** | 130K × $0.50 = $0.065 | 30K × $2.50 = $0.075 | **$0.14** | **$4.20** |
| Sonnet 4.6 | 130K × $1.50 = $0.195 | 30K × $7.50 = $0.225 | $0.42 | $12.60 |

### Scenario C: 20 generation examples via Batch API

Per example: ~1,400 input tokens, ~500 output tokens. No caching at 800-token system prompt.

| Model | Batch Input Cost | Batch Output Cost | **Daily Total** | **Monthly** |
|---|---|---|---|---|
| **Haiku 4.5** | 28K × $0.50 = $0.014 | 10K × $2.50 = $0.025 | **$0.039** | **$1.17** |
| Sonnet 4.6 | 28K × $1.50 = $0.042 | 10K × $7.50 = $0.075 | $0.117 | $3.51 |

### Monthly totals compared

| Configuration | Council | Scoring | Generation | **Monthly Total** |
|---|---|---|---|---|
| All Sonnet, no optimization | $11.25 | $25.20 | $7.02 | **$43.47** |
| All Sonnet, batch for overnight | $11.25 | $12.60 | $3.51 | **$27.36** |
| Sonnet cached council + Haiku batch | $8.24 | $4.20 | $1.17 | **$13.61** |
| + Extended thinking (1 agent) | $10.04 | $4.20 | $1.17 | **$15.41** |

The optimized configuration delivers **a 55–69% reduction** from unoptimized Sonnet-everywhere spend. The largest single lever is switching overnight batch tasks to Haiku 4.5 (saves ~$15/month), followed by the Batch API discount itself (saves ~$10/month on Sonnet), followed by prompt caching on council sessions (saves ~$3/month).

---

## When Opus 4.6 enters the picture

At $5/$25 per MTok (batch: $2.50/$12.50), Opus 4.6 is only **67% more expensive** than Sonnet per token—but it uses up to **65% fewer tokens** to solve equivalent problems. On the FinanceReasoning benchmark, Opus 4.6 scored **87.8%** vs Sonnet 4.6's **83.6%**, while using comparable token counts (164K vs 161K). Opus supports both batch processing and prompt caching with the same stacking discounts.

For Halcyon Lab, Opus makes sense in exactly one scenario: if your council's adversarial analysis agent consistently produces insufficient risk assessments with Sonnet. A single Opus agent within the council (replacing the Devil's Advocate role) would add approximately **$0.05/day** over Sonnet with caching—a trivial premium for the highest-capability reasoning on your most critical question. You could also use Opus as a **spot-check reviewer** on a 5–10% sample of Haiku's scoring output, at a cost of pennies per day.

---

## Practical implementation roadmap

The highest-ROI optimizations in priority order: First, move all overnight scoring and generation to the **Batch API with Haiku 4.5**—this alone saves roughly $18/month and requires minimal code changes. Second, implement **prompt caching on council system prompts**—ensure the shared prompt exceeds 2,048 tokens (add detailed methodology, rubrics, or portfolio context), remove all dynamic content from the system prompt, and sequence the first agent's request before the other four. Third, **A/B test Haiku vs Sonnet** on scoring by running both on 50 identical examples and using pairwise comparison with a Sonnet judge. Use the Wilcoxon signed-rank test to detect statistically significant quality differences. Fourth, enable **extended thinking selectively** for the risk-analysis agent and measure whether the $1.80/month premium produces materially better adversarial scenarios.

One critical caveat: your current system prompt sizes (500 and 800 tokens) are **below the minimum caching threshold** for every Claude model. Caching cannot activate on these prompts, and it fails silently—no error, just full-price processing. If caching matters for batch tasks, expand your system prompts to include few-shot examples, detailed rubrics, and output schemas until they exceed 4,096 tokens for Haiku or 2,048 for Sonnet. This expansion actually serves double duty: richer prompts with few-shot examples measurably improve Haiku's scoring accuracy, closing the gap with Sonnet.

## Conclusion

The path from ~$27/month to ~$14/month requires no architectural redesign—just three API-level changes: batch processing for overnight work, prompt caching for the council, and Haiku for structured tasks. The combined batch + cache discount reaching 95% on input tokens is the most powerful lever, but it only activates above minimum token thresholds that your current prompts don't meet. The deeper strategic insight is that model selection per task matters more than global model choice. Haiku 4.5 at batch pricing ($0.50/$2.50) processes scoring at **1/6th the cost** of real-time Sonnet, and the quality difference is negligible for rubric-based evaluation with good prompts. Reserve Sonnet's reasoning capacity for the council sessions where multi-step financial logic genuinely requires it, and consider Opus only for the single highest-stakes agent role where a 4-point accuracy gain on financial reasoning justifies the premium.
# Qwen3 8B numerical tokenization and financial reasoning: what works

**Qwen3's single-digit tokenizer gives it a structural edge for arithmetic, but an 8B model should never be trusted to compute.** Halcyon Lab's equity analysis pipeline should pre-compute all derived quantities—percentage changes, ratios, moving averages—and reserve the model exclusively for qualitative synthesis, signal interpretation, and thesis generation. This approach, validated by Trading-R1's architecture on a smaller 4B backbone, leverages what small models do well (reasoning, narrative) while sidestepping what they demonstrably cannot do (multi-digit arithmetic). The conviction scoring system should shift from numerical 1–10 scales to structured categorical outputs backed by binary sub-criteria, since LLM-generated numbers are token classifications masquerading as continuous scores.

---

## Qwen3's tokenizer splits every digit individually

Qwen3 uses **byte-level byte-pair encoding (BBPE)** with a vocabulary of **151,669 tokens** (151,643 regular BPE tokens plus 26 special tokens including `<think>`/`</think>` for its hybrid reasoning mode). The tokenizer is inherited unchanged from Qwen2, implemented as `Qwen2Tokenizer` in HuggingFace Transformers. The critical design choice lies in the pre-tokenization regex, which matches numbers with `\p{N}`—exactly **one Unicode numeric character at a time**. Because BPE merges only operate within pre-tokenized chunks, this means every digit becomes its own token. No multi-digit number tokens exist in the vocabulary.

This has concrete consequences for financial text. The stock price `$142.57` becomes 6 tokens: `$`, `1`, `4`, `2`, `.`, `5`, `7`. A formatted amount like `$1,234.56` consumes 9 tokens. A large number `1,000,000` also takes 9 tokens. Every comma, decimal point, dollar sign, and percent sign occupies its own token position.

This contrasts sharply with GPT-4 (cl100k_base) and Llama 3, which use `\p{N}{1,3}` in their pre-tokenization regex, grouping up to three digits per token. The same `$142.57` takes only 3 number tokens in GPT-4 (`142`, `.`, `57`), and `$1,234.56` takes 6 tokens versus Qwen3's 9. The table below shows the practical token cost difference:

| Input | Qwen3 tokens | GPT-4/Llama 3 tokens |
|-------|:-----------:|:-------------------:|
| `142.57` | 6 | 3 |
| `$1,234.56` | 9 | 6 |
| `1,000,000` | 9 | 5 |
| `-3.2%` | 5 | 5 |
| `25bps` | 3 | 2–3 |

The tradeoff is important: Qwen3's single-digit approach costs **~50–80% more tokens** for number-heavy financial text, but Singh and Strouse's foundational research on tokenization and arithmetic (arXiv:2402.14903) demonstrates that single-digit tokenization avoids the "alignment problem" where GPT-4's 3-digit chunks create inconsistent boundaries across operands and results. Their work showed that enforcing right-to-left digit alignment improved GPT-4's arithmetic accuracy by over 20 percentage points. Qwen3's digit-level tokenization inherently provides this alignment, giving it a structural advantage for numerical tasks—**consistent, position-aligned representation** where each token maps to exactly one decimal place.

---

## 8B models reason about numbers but cannot compute them

Qwen3-8B achieves **88.8% on MATH 500** and **87.9% on GSM SYM p2** in thinking mode, placing it competitively within the 7–9B parameter class. These scores demonstrate strong mathematical reasoning on word problems. However, three critical caveats apply to financial deployment.

First, **robustness is poor**. When MATH problems are rephrased with identical mathematics but different wording, Qwen3-8B drops **13.3 percentage points** to 74.4%—the largest robustness degradation in the entire Qwen3 model family. This means a financial prompt that asks "what is the percentage increase" versus "compute the return" may produce different numerical answers.

Second, **raw arithmetic fails beyond 4–5 digits**. Multiple studies converge on a consistent picture: 8B models handle 3–4 digit addition at ~90–95% accuracy, but performance degrades sharply at 5–6 digits. Multi-digit multiplication (m×n where both m,n > 1) is classified as fundamentally "unlearnable" for autoregressive transformers without step-by-step decomposition. Percentage calculations on financial figures combine multiplication and division—both weak areas. A study on notation invariance found that Claude-3.5-Sonnet's addition accuracy collapses from **99.8% to 7.5%** when digits are mapped to novel symbols, proving reliance on memorized base-10 patterns rather than genuine algorithmic understanding.

Third, **LLMs have implicit number sense but struggle to express it**. Research published in early 2025 ("LLMs Know More About Numbers than They Can Say") revealed a striking disconnect: internal probes can successfully extract magnitude information from hidden states (log-magnitude regression succeeds), but the model's verbalized comparisons degrade for larger numbers and more digits. The model "knows" that 142.57 > 138.15 at the representation level but may not reliably state this when prompted to compare, especially amid many competing numbers. The Number Cookbook benchmark (ICLR 2025) confirmed that current LLMs fail on basic numerical processing tasks like correctly determining that 9.9 > 9.11—a classic financial decimal trap.

**Chain-of-thought helps, but tool-integrated reasoning helps more.** Qwen3-8B's distilled thinking mode, trained via knowledge distillation from Qwen3-32B and Qwen3-235B, enables effective reasoning chains that smaller models historically could not produce. However, Qwen2.5-Math-7B experiments showed that generating Python code for computation (tool-integrated reasoning) improves MATH scores from 83.6% to 85.3%. For financial applications, the FinanceReasoning benchmark (ACL 2025) found that Program-of-Thought prompting with OpenAI o1 reached **89.1% accuracy** versus lower scores for pure chain-of-thought—confirming that **offloading computation beats reasoning through it**.

---

## Pre-compute everything, let the model synthesize

The evidence overwhelmingly supports pre-computing all derived numerical quantities before they reach the model. Trading-R1 (arXiv:2509.11420), built on a Qwen3-4B backbone for equity trading, provides the most directly relevant validation. It pre-computes every technical indicator—50-SMA, 200-SMA, MACD, RSI, KDJ, Bollinger Bands, ATR, ADX, and more—using a 2-year lookback window processed through the stockstats library. Raw OHLCV prices are also provided alongside these computed features in a **dual-input** design, structured with XML tags (`<macd>`, `<rsi>`, `<sentiment>`, `<news>`). This system achieved **Sharpe ratios of 1.60–2.72** across major equities, outperforming GPT-4.1, DeepSeek-R1, and O4-mini.

Trading-R1's designers explicitly noted that "smaller models tend to be more stubborn" and that unstructured input caused the model to "struggle to identify sources effectively." Structured, pre-computed input was not optional—it was essential to performance at the 4B scale, and the same logic applies at 8B.

The decision framework breaks into three tiers:

**Always pre-compute (never leave to the model):** Percentage changes from prices, all technical indicators (MACD, RSI, moving averages, ATR), financial ratios (P/E, P/B, debt-to-equity), volatility metrics, relative comparisons (price vs. 52-week range), and composite signals. These are deterministic calculations where the model adds zero value but substantial error risk.

**Provide both raw and derived together:** Raw OHLCV prices alongside pre-computed indicators, raw financial statement items alongside computed ratios, and raw news alongside pre-computed sentiment scores. The Financial Statement Analysis literature (arXiv:2407.17866) found that dual-input models combining raw data with analytical narratives achieved the highest performance at **63.2% accuracy and 66.3% F1**. The model uses raw numbers for evidence-grounding and derived quantities for pattern recognition.

**Reserve for the model:** Qualitative synthesis across signals, risk assessment weighing conflicting indicators, evidence-grounded thesis construction, and buy/sell/hold decisions with justification. The FCLAgent framework explicitly validates this division—it uses the LLM only for qualitative direction while computing order prices and volumes through deterministic rules.

Pre-computation also has a practical advantage over tool-augmented approaches: no inference-time latency from tool calls, no risk of the model failing to invoke a calculator, and guaranteed correctness of all derived quantities. The model receives pre-verified numbers and focuses entirely on interpretation.

---

## Conviction scores need a categorical redesign

When Qwen3-8B outputs "7" on a 1–10 conviction scale, it is performing **token-level classification, not regression**. The model computes logits over its full 151,669-token vocabulary, applies softmax, and selects among discrete number tokens. The "decision" between outputting 7 versus 8 is a categorical choice between two unrelated vocabulary entries, not an incremental adjustment along a continuous scale.

Research on number token embeddings ("Language Models Do Not Embed Numbers Continuously," arXiv:2510.08009) shows that while the first principal component of number embeddings correlates with numerical order (R² > 0.95 for linear reconstruction), **substantial noise** dominates the embedding space. Adjacent tokens like 7 and 8 are closer to each other than to "elephant," but the relationship is noisy and imprecise—far too unreliable to ground trading decisions on the difference between a 7 and 8 conviction.

Calibration research makes the case even stronger. A 2025 study across 12 LLMs on medical questions found that **the correlation between confidence scores and accuracy was inverse**—more confident did not mean more correct. In 84.3% of 351 experimental scenarios, LLMs were overconfident. The G-Eval framework demonstrated that on a 1–5 scale, the token "3" has disproportionately high base probability, creating systematic center-bias. RLHF training—used in all instruction-tuned models including Qwen3—actively damages probability calibration by concentrating mass on preferred tokens.

Halcyon Lab should implement a **structured categorical conviction system** with 4–5 levels (Strong Buy → Buy → Lean → Monitor → Pass), each backed by binary sub-criteria that the model evaluates individually:

- Clear identifiable catalyst with timeline? (Y/N)  
- Asymmetric risk/reward profile? (Y/N)  
- Favorable technical setup confirmed by pre-computed indicators? (Y/N)  
- Strong fundamental support from pre-computed ratios? (Y/N)  
- Manageable and quantified downside risk? (Y/N)  

The count of affirmative responses maps deterministically to a conviction category. This approach provides three advantages: it eliminates the false precision of 1–10 scores, produces explainable outputs (why is this a Strong Buy?), and leverages what LLMs do well—binary classification—rather than what they do poorly—continuous numerical estimation. If continuous scores are absolutely required for downstream portfolio optimization, use the **G-Eval probability-weighted method**: extract logprob distributions over score tokens and compute an expected value, which accesses the model's distributional "belief" rather than its generated text.

---

## Managing numerical interference in long contexts

Qwen3-8B's **128K context window** is a double-edged sword for financial analysis. The "lost-in-the-middle" phenomenon, demonstrated by Liu et al. at Stanford, shows a **U-shaped attention curve** where information at the beginning and end of context is processed accurately, but middle content degrades by **30% or more**. This effect persists regardless of context window size—extending the window creates a larger dead zone, not better coverage. For a prompt containing 20 financial metrics across multiple equities, values placed in positions 8–14 face the highest risk of being ignored, swapped, or fabricated.

Research on multi-attribute numerical confounding reveals a subtler problem: **numbers interfere with each other systematically**. When an entity has multiple numerical attributes (price, P/E, market cap, volume), the model's internal representation of one attribute "bleeds into" others, with dominant attributes (like price, which appears frequently in training data) distorting less common metrics. This interference is directional, not random.

Numerical hallucination is equally systematic. The MARCH framework (2026) found that LLMs in data-intensive settings "frequently misquote figures or alter numerical values during context integration"—so frequently that they designed a zero-tolerance binary reward where any single misquoted figure invalidates the entire output. A Towards Data Science mechanistic analysis of 7 models found that during hallucination, the model doesn't passively fail to retrieve the correct number—it **actively moves probability mass away** from the correct token.

For practical capacity, converging evidence suggests limiting the **active working set** to approximately **10–15 distinct numerical values** that the model must simultaneously reason about. Simple retrieval (looking up a labeled value) can handle more, especially with structured formatting, but accuracy degrades above ~100–200 records even with optimal structure. The Improving Agents benchmark tested 1,000 records with 8 numerical attributes each and found accuracy ranging from only **41% to 61%** depending on format.

The mitigation strategy is structural. Place the most critical numbers at the **beginning and end** of the prompt (primacy and recency effects). Use explicit labels for every number—never include orphaned values. Separate entities clearly so cross-entity numerical confusion is minimized. Trading-R1 validates this approach: their 20,000–30,000 token inputs used XML-tagged sections with brief descriptions for each indicator, and they explicitly found this essential for their small model's performance.

---

## Formatting guidelines for each financial data type

Benchmark testing across 11 data formats reveals a clear hierarchy. **Markdown key-value pairs** (60.7% accuracy) and **XML** (56.0%) significantly outperform JSON (52.3%), natural language (49.6%), and CSV (44.3%). For Qwen3-8B specifically, the single-digit tokenizer means commas in large numbers serve double duty: they provide human readability and enforce tokenization boundaries that align with the model's digit-level processing—matching the right-to-left carry propagation pattern that Singh and Strouse demonstrated improves arithmetic by 22+ percentage points.

**Stock prices:** Use 2 decimal places with dollar sign and commas: `$1,142.57`. Never use bare numbers without currency symbols. The unit provides semantic context that improves comprehension.

**Percentage changes:** Use 1–2 decimal places with explicit direction: `+3.2% (up)`. Include the sign and a directional word. Do not use decimal form (0.032)—the model handles `3.2%` more reliably than mathematically equivalent alternatives.

**Large dollar amounts:** Abbreviate consistently: `$394.3B` or `$2.45T`. Trading-R1 explicitly abbreviates (1000 → 1k) to save tokens. Never mix notations within a single prompt—if one revenue figure is `$394.3B`, all revenue figures must use the same format.

**Ratios:** Use 1–2 decimal places with an explicit label and trailing x: `P/E: 28.54x`. The label prevents the model from confusing a P/E ratio with an EPS figure or price.

**Basis points:** Integer only, explicitly labeled: `spread: 25 bps`. Unless fractional basis points are decision-relevant, avoid decimals.

**Consistency is non-negotiable.** The Number Cookbook (ICLR 2025) and Math-RoB benchmark demonstrate that LLMs are hypersensitive to formatting variation. Mixing `$1.4B` and `$1,400,000,000` within a single prompt forces implicit conversion—an error-prone operation. Establish rigid formatting conventions and enforce them in the feature pipeline before text reaches the model. This consistency should extend from training data through inference: format divergence between fine-tuning data and production prompts degrades performance.

The recommended prompt structure for Halcyon Lab's equity analysis follows a sandwich pattern:

```
[Key Metrics Summary — critical numbers at START]

<financial_data ticker="AAPL" as_of="2026-03-28">
  price: $142.57
  prior_close: $138.15
  change_pct: +3.2%
  pe_ratio: 28.54x
  eps_ttm: $6.42
  rsi_14d: 62.3
  macd_signal: bullish crossover on 2026-03-25
  52wk_range: $124.17 – $198.23
</financial_data>

[Analysis task description]

[Reference — repeat critical figures at END]
```

---

## Practical recommendations for Halcyon Lab's enrichment pipeline

The research converges on six actionable principles for deploying Qwen3-8B in equity trade analysis.

**1. Treat the model as a reasoning engine, never a calculator.** Pre-compute every derived quantity—returns, ratios, indicators, relative comparisons—in a deterministic feature pipeline. The model's job is synthesis and thesis generation. Trading-R1 validates this architecture at even smaller scale (4B).

**2. Structure inputs with labeled key-value pairs or XML tags.** Unstructured data degrades small-model performance measurably. Every number needs an explicit label. Use XML or Markdown-KV format, segmented by data category (technicals, fundamentals, sentiment, macro). Include brief descriptions of what each indicator means—Trading-R1 found this improves interpretation.

**3. Replace numerical conviction scores with categorical outputs.** Implement 4–5 conviction tiers backed by binary sub-criteria. If continuous scores are required, extract token logprob distributions and compute probability-weighted expected values rather than reading the generated digit. A "7" versus "8" from the model reflects token probability noise, not meaningful confidence gradation.

**4. Limit the active numerical working set to 10–15 values per reasoning task.** If a trade thesis requires evaluating 30 metrics, pre-compute a summary layer that distills them into the 10–15 most decision-relevant inputs. Place the most critical numbers at the beginning and end of the prompt to exploit primacy and recency effects.

**5. Enforce rigid formatting consistency.** Define a single canonical format for each data type and enforce it across training data and inference prompts. Abbreviate large numbers consistently (`$394.3B`), use commas in all numbers over 999, always include units inline, and never present bare uncontextualized numbers.

**6. Validate with adversarial number perturbation.** Given Qwen3-8B's 13.3% robustness gap on rephrased problems—worst in the Qwen3 family—test the fine-tuned model with numerically perturbed inputs (different stock prices, different dates, swapped ticker symbols) to measure how often the model produces logically inconsistent outputs. Build a zero-tolerance evaluation layer, following MARCH's approach, where any misquoted figure from the input context flags the output for review.
# Optimal training formats for fine-tuning equity trade commentary models

**XML-tagged output sections paired with information-dense, structured inputs deliver the best fine-tuning results for small language models generating analytical financial writing.** This conclusion draws from Trading-R1's empirical success with Qwen3-4B, DeepSeek-R1's format reward methodology, and the SLOT paper's finding that fine-tuned 7B models achieve **99.5% schema accuracy** for structured outputs. The critical insight across the research is that structured formatting helps classification-like outputs (conviction scores, trade decisions) while slightly degrading open-ended reasoning — meaning the ideal training format uses XML tags to separate structured metadata from prose analysis sections where the model reasons freely. For a single developer on consumer hardware targeting Qwen3 8B with QLoRA, the sweet spot is **300–1,000 total tokens per training example** using ChatML templates, comma-formatted numbers supplemented with verbal descriptions, and a consistent system prompt with minor paraphrasing variants.

## Trading-R1 proves XML-tagged structure works for financial reasoning at small scale

Trading-R1 (Xiao et al., September 2025) is the closest direct precedent for the system described. Built on **Qwen3-4B** — smaller than the target 8B model — it uses XML tags throughout both input and output, and its empirical findings on structured versus unstructured formatting are unambiguous.

**Input structure** wraps each data source in dedicated XML tags: `<news>` contains temporal buckets (`<3days>`, `<10days>`), `<sentiment>` nests `<rec>` (analyst recommendations) and `<insider>` (transaction data), and each technical indicator gets its own tag (`<macd>`, `<rsi>`, `<atr>`). The team explicitly tested unstructured input and abandoned it: "We initially experimented with unstructured input data without clear sectioning, but found that the model struggled to identify sources effectively." They concluded that **structured input is more effective than massive unstructured data, particularly given that the model is small while input data exists in long context.**

**Output structure** uses 5–7 XML-tagged analysis sections (`<fundamentals>`, `<technical>`, `<conclusion>`, `<Competitors>`, `<Insider Transactions>`) followed by a `<Transaction>` decision tag. Within each section, the format enforces an opinion-quote-source triad: opinions in regular text, supporting evidence in *italics*, source citations in `backtick code`. The training reward function scores structure (60% section count compliance + 40% within-section formatting), evidence quality (presence of quotes and citations), and decision accuracy against forward returns.

The Tauric-TR1-DB dataset contains **100,000 training examples** across 14 tickers with ~20 variations per date-ticker pair, achieved by randomly sampling and shuffling subsets of five data sources. Inputs average 15K–23K tokens; output theses run 6K–8K tokens. This is far longer than what a 2048-token QLoRA setup can handle, which means aggressive condensation of both input and output is essential for adapting this approach. The dataset and full codebase remain unreleased as of March 2026 — the GitHub repository contains only a placeholder README — so the paper's figures and appendices are the only verified source for format specifications.

## The empirical case for XML over JSON or plain markdown

Three converging lines of evidence favor XML-tagged sections as the output format for fine-tuning analytical writing.

**First, XML tags are demonstrably learnable through both SFT and reinforcement learning.** DeepSeek-R1's `<think>...</think>` tag architecture has been successfully distilled into models from 1.5B to 14B parameters, with 800K training samples producing reliable format compliance. The GRPO training community has standardized on XML-style tags (`<reasoning>`, `<answer>`) for format reward functions because they tokenize simply — each tag is 1–3 tokens versus JSON's nested braces, brackets, quotes, and colons. Fin-R1, also built on Qwen2.5-7B, uses `<think>...</think><answer>...</answer>` and achieves robust format compliance after two-stage SFT + GRPO training.

**Second, structured formats hurt reasoning but help classification — and trade commentary needs both.** The most rigorous format comparison study (Tam et al., 2024, "Let Me Speak Freely?") tested GPT-3.5, LLaMA-3-8B, and Gemma-2-9B across multiple tasks and found that JSON/XML/YAML format restrictions cause **10–15% performance degradation on reasoning tasks** compared to free-form output. The mechanism is "misordering" — forcing format tokens before reasoning tokens disrupts chain-of-thought. However, the same study found structured formats **matched or exceeded** free-form on classification tasks (sentiment, categorization), where rigid format reduces ambiguity. This suggests a hybrid approach: use XML tags to delineate sections (classification-like task of choosing what to discuss), but allow free-form prose within each section (reasoning task of constructing the analysis). This is exactly what Trading-R1 does.

**Third, JSON conflicts with reasoning capabilities in current model architectures.** DeepSeek's own documentation acknowledges that "the capabilities of DeepSeek-R1 fall short of DeepSeek-V3 in general purpose tasks such as JSON output." Alibaba's Qwen documentation states that thinking-mode models do not support structured JSON output — enabling `response_format: json` with thinking mode causes errors. The practical workaround adopted by the community is a two-step approach: generate reasoning in free form, then convert to structured format. The SLOT paper (EMNLP Industry 2025) validated this at scale, showing a fine-tuned Mistral-7B post-processor achieves 99.5% schema accuracy and 94.0% content similarity, outperforming Claude-3.5-Sonnet by **25 percentage points** on schema compliance.

For the specific use case of generating a "Why Now" summary plus "Deeper Analysis," the recommended output template is:

```xml
<why_now>
[2-3 sentence summary in natural prose]
</why_now>
<analysis>
[4-6 paragraphs of analytical prose with embedded evidence]
</analysis>
<metadata>
Conviction: [1-10]
Direction: [LONG/SHORT/NEUTRAL]
Time Horizon: [description]
Key Risk: [description]
</metadata>
```

This separates the reasoning-intensive prose sections (where free-form generation excels) from the classification-like metadata fields (where structured formatting excels), while XML tags provide clean parseability.

## Structuring the ChatML template for Qwen3 fine-tuning

Qwen3 uses the ChatML format with `<|im_start|>` and `<|im_end|>` delimiters. The research converges on specific best practices for how to structure system prompt, user message, and assistant response for single-task fine-tuning.

**System prompt strategy: consistent with minor paraphrasing.** For single-task fine-tuning, use the same core system prompt across all training examples with **3–5 minor wording variants** expressing identical intent. Research on "format specialization" (arXiv 2211.00635) shows that models overfit to exact training formats very early in fine-tuning — using a single identical system prompt risks the model failing when encountering even slight prompt variations at inference. But excessive variation essentially becomes multi-task training, requiring a much larger dataset. The sweet spot is 3–5 paraphrases of the same role description and output format instructions. Keep system prompts under **300 tokens** to preserve context window for actual data.

**User message diversity is critical.** Multiple studies (EMNLP 2024, MIT CSAIL 2024, ACL 2025 testing on Qwen-2.5-7B specifically) demonstrate that **instruction diversity improves worst-case performance** and model robustness. Actively vary how the trade analysis request is phrased — different sentence structures, vocabulary choices, and information ordering. Trading-R1's approach of generating ~20 variations per date-ticker pair by randomly sampling and shuffling data source subsets is a practical implementation of this principle.

**Loss masking should focus on assistant responses.** Enable `assistant_only_loss=True` in SFTTrainer (or equivalent masking). Computing loss on system and user tokens wastes model capacity learning to predict prompt boilerplate it will see verbatim at inference. One nuance from the research: for short completions, a tiny prompt loss weight (0.01–0.1) can marginally help, but for medium-to-long completions like multi-paragraph analysis, masking has no downside.

**Unsloth-specific Qwen3 settings** from official documentation: use `load_in_4bit=True`, `use_gradient_checkpointing="unsloth"`, start with `max_seq_length=2048`. Apply LoRA to all linear layers (q, k, v, o, gate, up, down) with rank 32. Critically, do NOT set `bos_token` to `<|im_start|>` — this causes double BOS tokens and degrades fine-tuning. Setting `eos_token` to `<|im_end|>` is safe. If preserving Qwen3's reasoning capabilities matters, Unsloth recommends a **75% reasoning / 25% non-reasoning** dataset mix.

## Numbers need verbal anchoring for small models to reason about them

The tokenization problem with numbers is severe at the 7B–14B scale and directly relevant to financial data presentation. LLM tokenizers split multi-digit numbers arbitrarily: "480" might be one token while "481" splits into "4" + "81." Singh and Strouse (ICLR 2025) demonstrated that **right-to-left tokenization alignment improves arithmetic accuracy by 22+ percentage points**, and that smaller models are more vulnerable to tokenization effects than larger ones.

The practical prescription for financial training data is a mixed representation approach. **Always use comma-separated numbers** ($142,500 not 142500) because commas force consistent 3-digit token grouping that aligns arithmetic operations. **Supplement every raw number with a verbal description**: "revenue of $142.5M, representing an 8.3% year-over-year increase" gives the model both the precise value and semantic context across multiple tokens. For percentage changes and ratios, provide both the figure and an interpretive qualifier: "decreased 12.3%, a notable decline from the prior quarter."

Financial tables should be **serialized into natural text** rather than fed as CSV or tabular formats. Research on FinQA benchmarks shows that LLM-based text serialization of tables significantly outperforms naive tabular input, even when the underlying data is identical. For technical indicators specifically, Trading-R1's approach of tagging each indicator (`<rsi>RSI(14) at 67.3, approaching overbought territory above 70</rsi>`) combines the structured identification benefit of XML with the verbal anchoring that helps numerical reasoning.

One finding with strong practical implications: even heavily fine-tuned models show **performance degradation on longer, more complex financial documents**, sometimes falling below base model performance. This reinforces the value of pre-extracting and condensing relevant context into the training input rather than feeding raw data. An input that states "Q3 revenue grew 8% YoY to $142.5M, beating consensus of $138M by 3.2%" is far more trainable than a full quarterly earnings table.

## The 300–1,000 token sweet spot for 2048-context QLoRA training

No single published study provides a definitive optimal input-to-output ratio for SFT, but converging evidence from multiple sources points to clear guidelines for hardware-constrained setups.

**Target 300–1,000 total tokens per training example** (input + output) when training with a 2048-token maximum sequence length. The widely-used Alpaca dataset averages ~337 tokens per example. The original QLoRA paper (NeurIPS 2023) used the OpenAssistant dataset of only 9,846 examples with moderate lengths and achieved strong results. Loss is computed only on output tokens in standard SFT, so very long inputs with short outputs produce low "training signal density" — the model processes many tokens but learns from few. Conversely, research shows that models trained on long reasoning traces tend to **memorize structure rather than learn when concise answers suffice**, producing verbose and repetitive outputs.

For the specific "Why Now" + "Deeper Analysis" format, aim for **200–400 input tokens** (condensed multi-source financial data) and **200–600 output tokens** (summary + analysis + metadata). This keeps total examples at 400–1,000 tokens, well within the 2048 limit and leaving room for the chat template overhead (~50–100 tokens for system prompt and ChatML delimiters). If inputs must exceed 1,000 tokens, use Unsloth's packing feature (`packing=True`) to efficiently fill sequences and potentially achieve **2–5x training speedups** for shorter examples.

**Hardware-specific configurations** based on community-validated benchmarks:

- **RTX 3090 (24GB)**: Qwen3-8B in 4-bit, max_seq_length=2048, batch_size=2, gradient_accumulation=4, LoRA rank=32. Comfortable fit with ~16–20GB VRAM usage.
- **RTX 3060 (12GB)**: Qwen3-8B in 4-bit, max_seq_length=1024–2048, batch_size=1, gradient_accumulation=8–16, LoRA rank=8–16. Tight but feasible with Unsloth's gradient checkpointing.

When truncation is unavoidable, **always truncate inputs, never outputs** — the completion is where the model learns its target behavior. Unsloth's SFTTrainer default `truncation_mode="keep_start"` preserves the beginning of the sequence, which is correct since system prompts and initial context carry the most information.

## Structured metadata fields outperform prose-embedded assessments for downstream reliability

The question of whether conviction scores, risk levels, and time horizons should be explicit labeled fields or woven into prose resolves clearly in favor of explicit fields, though with an important architectural nuance.

**Classification-like outputs benefit from structured formatting.** Tam et al.'s finding that structured formats match or exceed free-form performance on classification tasks applies directly to metadata fields. A "Conviction: 8/10" field is essentially a classification task — the model chooses from a bounded set of values. The SLOT paper demonstrates that fine-tuned 7B models produce structured fields with **99.5% schema accuracy** when using constrained decoding, meaning fields like conviction scores would be generated with near-perfect structural reliability. No peer-reviewed study was found specifically comparing calibration quality of explicit metadata versus prose-embedded assessments at the 7B–14B scale — this remains a gap in the literature.

The recommended approach separates metadata into its own XML section placed **after** the prose analysis. This ordering matters: it lets the model complete its reasoning before committing to structured assessments, avoiding the "misordering" effect that Tam et al. identified as the primary mechanism behind structured-format degradation. The model reasons through the analysis in `<why_now>` and `<analysis>` tags, then crystallizes its assessment in `<metadata>`. At inference time, the metadata section is trivially parseable for downstream systems while the prose sections serve human readers.

## Conclusion

The optimal training example format for this system combines five design decisions supported by empirical evidence. Use **XML-tagged output sections** with free-form prose inside analytical sections and explicit labeled fields for metadata — this architecture exploits the finding that structure helps classification while hurting reasoning, by applying each format where it excels. Present numerical inputs as **comma-formatted values with verbal descriptions** to compensate for tokenization effects that disproportionately affect 7B–14B models. Structure training examples as **ChatML conversations** with a consistent (but slightly varied) system prompt, diverse user message phrasings, and loss computed only on assistant responses. Keep total examples at **300–1,000 tokens** to maximize training signal density within a 2048-token QLoRA constraint. Finally, adopt Trading-R1's approach of **generating multiple input variations** per underlying data point through random source subsetting and shuffling, which builds the instruction diversity that research shows improves worst-case model performance.

The most significant gap in current research is the absence of controlled ablation studies comparing XML, JSON, and markdown output formats specifically during fine-tuning (as opposed to inference-time prompting) at the 7B–14B scale. Trading-R1's success with XML on Qwen3-4B and DeepSeek-R1's proven distillation pipeline provide strong practical evidence, but a rigorous format comparison during SFT remains an open research question worth tracking as more financial LLM papers appear through 2026.
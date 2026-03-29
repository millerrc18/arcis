# Halcyon Lab: Complete Research Agenda from Validation to Scale

> Deep research report — 13 questions covering validation, RL pipeline, competition, AI-dominated markets, execution, regime detection, timeline compression, research traps, data moats, multi-strategy, LLM reasoning, regulatory, and inference optimization

## Master Priority Matrix

| Priority | Action | Question | Effort | Phase Gate |
|---|---|---|---|---|
| 🔴 1 | Implement PSR/MinTRL calculators; log ALL backtest trials | Q1 | 4–6 hrs | Must do Phase 1 |
| 🔴 2 | Switch planned RL from GRPO to REINFORCE++ | Q2 | Low | Must do Phase 1 |
| 🔴 3 | Deploy Traffic Light regime system (VIX + 200-DMA + credit spreads) | Q6 | 8–16 hrs | Must do Phase 1 |
| 🔴 4 | Define drawdown stop-out rules using Triple Penance Rule | Q1 | 6–8 hrs | Must do Phase 1 |
| 🔴 5 | Start logging decision price vs fill price for every trade | Q5 | 2–4 hrs | Must do Phase 1 |
| 🔴 6 | Use Claude for training data augmentation/distillation (Fin-R1 pipeline) | Q2 | 20 hrs | Must do Phase 1 |
| 🟡 7 | Log ALL predictions (taken and rejected) with full context | Q9 | Ongoing | Important Phase 1–2 |
| 🟡 8 | Score every analysis on 1–5 rubric from trade 1 | Q11 | Ongoing | Important Phase 1–2 |
| 🟡 9 | Upgrade QLoRA to QDoRA via Unsloth | Q2, Q13 | Trivial | Important Phase 2 |
| 🟡 10 | Begin Strategy 2 research in parallel | Q7, Q10 | 40+ hrs | Important Phase 2–3 |
| ⚪ 11 | Implement CPCV validation framework | Q1 | 16–24 hrs | Can wait Phase 3 |
| ⚪ 12 | Multi-strategy LoRA adapter architecture | Q10 | Medium | Can wait Phase 3 |
| ⚪ 13 | Upgrade to RTX 3090 + Qwen3 14B | Q13 | Hardware | Can wait Phase 2–3 |
| ⚪ 14 | Advanced execution optimization (TWAP/VWAP) | Q5 | N/A | Skip until $500K+ |
| ⚪ 15 | TensorRT-LLM optimization | Q13 | N/A | Skip entirely |

## Q1: Validation — What Separates Survivors from Failures

At 5 closed trades, Halcyon has zero statistical significance. The system is in the "pre-statistical" zone where the most important work is infrastructure, not analysis.

**Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado (2014, JPM): corrects for non-normal returns and selection bias from multiple testing. Critical requirement: record ALL backtest trials from day one. If only the winning strategy is logged, DSR becomes meaningless.

**Minimum Track Record Length (MinTRL)** — Bailey & López de Prado (2012, JoR): For Sharpe 1.0 with normal returns at 95% confidence, MinTRL ≈ 68 trade-level observations. If Sharpe is only 0.5, balloons to 270+. Negative skewness and fat tails increase further.

**Walk-Forward Analysis** — Pardo (2008): industry baseline but "no harder to overfit than walk-backward" (López de Prado). Upgrade path: **Combinatorial Purged Cross-Validation (CPCV)** — AFML Chapter 12 — tests all C(N,k) combinations, producing distribution of performance metrics. Arian et al. (2024) confirmed CPCV superiority over WFA.

**Triple Penance Rule** — Bailey & López de Prado (2014, JoR): recovery from max drawdown takes ~3× the formation period. 20% DD over 2 months → ~6 months to recover. Define tolerance BEFORE scaling.

Ernest Chan's key insight: small traders have structural capacity advantage — exploit inefficiencies too small for institutions. At all planned phases ($100→$500K), positions are <0.001% of daily S&P 100 volume. Market impact is zero. Binding constraint is strategy decay and regime dependence.

Priority: Must do before Phase 2. 30–40 hours total. Claude compression: 4–5× on implementation, 0× on data collection.

## Q2: Financial LLM and RL Advances

Every successful financial reasoning model (Trading-R1, Fin-R1, Alpha-R1, DianJin-R1) follows identical pipeline: data distillation → SFT → reinforcement learning. Three adjustments needed:

### REINFORCE++ Should Replace GRPO
Hu (2025, arXiv:2501.03262): GRPO's local advantage normalization causes immediate overfitting on small prompt datasets. REINFORCE++ with global normalization learns more stably with superior OOD performance. With only 969 examples, this is the primary RL failure mode. REINFORCE++ is simpler (k=1 sample sufficient), available in TRL, requires only 12GB VRAM. Dr. GRPO (Lan, 2025) identifies and removes GRPO's question-level difficulty bias as alternative fix.

### Trading-R1 Validation
Xiao et al. (September 2025, arXiv:2509.11420): Three-stage easy-to-hard curriculum with volatility-adjusted reward labeling. On NVIDIA stock: 8.08% cumulative return, Sharpe 2.72, 70% hit rate, 3.80% max DD, outperforming GPT-4.1. Performance hierarchy: small LMs < reasoning LMs < large LMs < Trading-SFT ≈ Trading-RFT < Trading-R1.

### Alpha-R1 Confirms RL Is Not Optional
arXiv:2512.23515: Qwen3-8B WITHOUT RL produces Sharpe of -0.77 for alpha factor screening. WITH RL: dramatic improvement + zero-shot generalization from CSI 300 to CSI 1000.

### QDoRA as Best Practice
Lian (November 2025, arXiv:2512.00630): "Financial Text Classification Based on rLoRA Fine-tuning on Qwen3-8B" — closest work to Halcyon's setup. NEFTune + rLoRA + FlashAttention outperforms T5, BERT, RoBERTa, both LLaMA variants. Community consensus: QLoRA + DoRA via Unsloth is current best practice. DoRA decomposes weights into magnitude and direction, applying LoRA only to direction. ~8% VRAM savings, no quality loss. Implementation: `use_dora=True` in Unsloth.

### Self-Blinding Validation
Gao, Jiang, and Yan (December 2025, arXiv:2512.23847): "Lookahead Propensity" (LAP) metric — LLMs memorize historical outcomes and inflate backtesting performance. Entity-neutering (Engelberg et al., 2025) validates Halcyon's self-blinding approach as gold standard.

**Constrained decoding via XGrammar** (Dong et al., MLSys 2025): standard for guaranteed structured JSON output from local models with near-zero overhead. Adopt for production reliability.

Priority: REINFORCE++ and data augmentation are Must do Phase 1. DoRA and constrained decoding are Important Phase 2.

## Q3: The Crowding Landscape

### The Brutal Assessment
Pullback-in-uptrend on S&P 100 is among the most competed strategy-universe combinations in existence. QuantConnect: 300,000+ registered users. Freqtrade: 39,900 GitHub stars. AI powers >70% of U.S. equity trades.

### But the Pipeline Attrition Tells a Different Story
- 30–40% complete a working backtest
- 5–10% pass robustness testing
- 3–5% deploy live
- 1–2% sustain beyond six months
- **0.1–0.5% sustain profitable live trading beyond two years**

300,000 QuantConnect users → perhaps 300–1,500 sustained profitable operators. Fine-tuning open-source LLMs on financial data and deploying live: likely low hundreds globally.

### Alpha Decay
McLean and Pontiff (2016, JoF): 97 published predictors — returns 26% lower out-of-sample, 58% lower post-publication. Additional 32% decline attributed to publication-informed trading. Worst for high in-sample returns + low idiosyncratic risk + high liquidity (= S&P 100).

### But Momentum Persists
Jegadeesh and Titman (2023): momentum profits remained large and significant across three decades post-publication. Driven by deep behavioral biases (underreaction) rather than simple mispricing.

### Key Question for Halcyon
Whether the AI layer adds genuine signal above what's already priced in. Stambaugh, Yu, and Yuan (2012, 2015): anomaly returns concentrate in the short leg (overpriced stocks). Long-only on liquid S&P 100 captures less anomaly alpha. **Expanding beyond S&P 100 to mid-caps would access less-competed alpha.**

## Q4: AI-Dominated Price Discovery

### Grossman-Stiglitz Paradox (1980)
If markets were perfectly efficient, no one would gather information, causing prices to become uninformative. There is always a floor to alpha — set by the cost of building and maintaining AI systems.

### Market Ecology (Farmer, 2002)
As more AI agents run pullback strategies, pullbacks become shallower and briefer — reducing per-trade alpha but not eliminating it.

### HFT Precedent
Budish, Cramton, and Shim (2015): arms race did not reduce arbitrage prize size — just compressed time window. Competition becomes winner-take-most, but total alpha persists.

### Edge Shifts To
- Identifying pullbacks algorithms won't buy (catalytic/fundamental triggers)
- Regime detection (genuine dislocation vs noise)
- Position sizing and risk management (may now contain more alpha than signal generation)

### Most AI-Resistant Alpha Sources
- Regime awareness and adaptation
- Catalyst-driven pullbacks
- Behavioral and positioning signals (crowding, options positioning)
- Stress/dislocation trading

**Key insight: "AI as market infrastructure" (table stakes) not "AI as alpha generator" (edge). Build for a world where everyone has AI; edge comes from proprietary data, regime awareness, and execution quality.**

## Q5: Execution Quality

At $25K order on AAPL (daily volume ~$16B): Bouchaud square-root law predicts impact of ~0.002 bps — unmeasurable. Even at $1M: ~0.01 bps. TWAP/VWAP solve problems that don't exist at this scale.

Threshold where execution matters for S&P 100: ~$5M per order. That's 200× beyond Phase 6 maximum.

**What matters now:** Implementation Shortfall (Perold, 1988) — log decision price, execution price, compute per-trade IS in bps from day one. Switch from market orders to limit orders at the ask (saves 0.5–2 bps, no execution risk on liquid names). Total effort: 2 hours.

## Q6: Minimum Viable Regime Detection

Biggest structural vulnerability: generating zero signals in bear markets (partially protective). Real danger is regime transitions — catching falling knives.

### Traffic Light System (Minimum Viable)
Three indicators chosen for low overfitting risk:

| Indicator | Green | Yellow | Red |
|---|---|---|---|
| VIX level | <20 | 20–30 | >30 |
| S&P 500 vs 200-DMA | Above | Within 3% | Below |
| HY credit spread z-score | <0.5σ | 0.5–1.5σ | >1.5σ |

Score: Green=2, Yellow=1, Red=0. Total 0–6.
- 5–6: Full position sizing
- 3–4: 50%
- 0–2: Cash or minimal positions

Properties: 3 inputs (nearly impossible to overfit), rules-based (no parameter estimation), validateable across 50+ years.

**Regime-aware position sizing > regime-aware strategy selection for Phase 1–2.** Less prone to overfitting, works even when detection is noisy.

Advanced path: Statistical Jump Models (Shu et al., 2024) better stability than HMMs. Wasserstein HMM (2025): Sharpe 2.18 vs 1.18 SPX buy-and-hold, max DD -5.43% vs -14.62%.

## Q7: Critical Path to Phase 4

At 35 trades/month with single strategy:
- April 2026: ~40 trades (first statistical signal)
- June 2026: ~110 (MinTRL possibly satisfied, Phase 1→2)
- August 2026: ~180 (regime coverage assessment)
- September 2026: ~215 (reliable CPCV, DSR computable)

**500 trades with one strategy: ~14 months → March 2028. Phase 4 by December 2026 is impossible with single strategy.**

With dual-strategy (Strategy 2 by August 2026): combined ~70/month. August–December: 5 months × 70 = 350 + ~175 = ~525 total. Probability: **25–35% of reaching Phase 4 by December 2026.**

### Claude Compression
- Training data generation: 10×
- Quality scoring: 8×
- Research parallelization: 5×
- Strategy 2 development: 3–4× (3–6 months → 4–8 weeks)

### Cannot Compress
- 15-day hold periods
- Closed trade outcomes
- Regulatory timelines
- Need for multiple regime exposures

**Single highest-leverage action: begin Strategy 2 research immediately. Target live by August 2026.**

## Q8: Research Traps vs Valuable Topics

### Clear Traps (avoid Phase 1–2)
- **HFT tick data** (95% trap): entirely different business
- **Neural architecture search** (95%): bottleneck is data not architecture
- **Custom transformers from scratch** (95%): 969 examples is mathematically absurd
- **Real-time social media sentiment** (85%): R² of 0.0006 for daily sentiment vs returns
- **Custom data infrastructure** (85%): PostgreSQL + Docker + Airflow for what yfinance does in 3 lines
- **Real-time news NLP** (80%): by NLP processing time, info is priced in

### Traps Now, Valuable Later
- Complex portfolio optimization (75% trap now, Phase 3+)
- Crypto/forex expansion (70% now): prove core first
- Proprietary backtesting engine (65%): lightweight script yes, full engine no
- Options pricing (90% now): $100 capital makes options infeasible

## Q9: Data Moat Assessment

### a16z Challenge
Casado and Lauten (2019): "The Empty Promise of Data Moats" — data scale effects have diminishing returns. Defensibility is not inherent to data itself.

### Refined Thesis
Moat is not data itself but **accumulated mapping of signal → context → outcome** across diverse market conditions. Two Sigma processes 380+ petabytes from 10,000+ sources — moat is processing know-how, not raw data.

### Tier 1 Data to Collect Immediately (Zero Cost)
- Every prediction (taken AND rejected) with subsequent price movement
- Full trade execution logs with market context
- Model confidence calibration data
- **"Near miss" data** — setups that almost triggered but didn't (most underrated)

### Moat Measurement
Track: OOS Sharpe (rolling 6-month), Information Coefficient per feature, Brier score calibration, alpha decay rate per signal. Monthly "Moat Scorecard" — if 3+ metrics red for 2+ months, moat is shrinking.

## Q10: Multi-Strategy Framework

Adding Strategy B improves portfolio Sharpe if and only if: **SR_B > ρ(A,B) × SR_A**. If uncorrelated (ρ=0), any positive-Sharpe strategy helps. If ρ=0.3 and SR_A=1.0, need only SR_B > 0.3.

Minimum track record before deploying Strategy 2: 100 trades (minimum) to 200+ (recommended, covering significant drawdown). Combined with PSR > 0.95.

Strategy interference detection: rolling 30-day correlation, alert when |ρ| > 0.3. Fisher z-transformation: with N=100, minimum detectable correlation at 80% power is ρ ≥ 0.28.

From Citadel/Millennium: independent P&L per strategy, centralized risk management, dynamic capital reallocation on rolling Sharpe, strict per-strategy stop-losses (10% DD → reduce 50%; 15% → pause).

## Q11: LLM Reasoning Quality

Kim et al. (2024): GPT-4 achieves ~60% accuracy predicting earnings direction. Higher confidence: 64% vs 57%.

**Critical finding from "Reasoning or Overthinking" (arXiv:2506.04574): for financial sentiment, prompting LLMs for explicit reasoning REDUCES alignment with correct answers.** GPT-4o with no CoT achieved highest accuracy. Performance monotonically declined with increasing completion length.

CoT faithfulness is concerning: Turpin et al. (2023, NeurIPS) — CoT explanations influenced by biasing features models fail to mention. Lanham et al. (2023, Anthropic): larger models produce less faithful reasoning. "Is CoT Reasoning a Mirage?" (2025): structured reasoning is "fragile and prone to failure under moderate distribution shifts."

### Practical Framework
- Stage 1 (50–100 trades): Score every analysis 1–5, build contingency tables
- Stage 2 (100–200): Spearman correlation between quality scores and P&L. Minimum detectable ρ ≥ 0.28 at N=100
- Stage 3 (200–500): Logistic regression P(win) ~ quality + confidence + regime + vol
- Stage 4 (500+): A/B test "detailed reasoning" vs "simple signal" — only causal test

**Design around outcomes, not reasoning plausibility. The model may produce convincing analysis while keying on simpler features.**

## Q12: Regulatory Environment

Most favorable in years under Chair Atkins. Predictive Analytics Rule formally withdrawn June 12, 2025. No new AI-specific rules anticipated.

Trading personal funds through LLC requires no registration. Critical line: **managing even one other person's money for compensation activates adviser registration.**

SEC focus is "AI washing" enforcement — punishing firms that lie about AI capabilities, not regulating AI use. No enforcement action has targeted legitimate AI-driven trading.

Pattern Day Trader rules: $25K+ equity for 4+ day trades in 5 business days. Maintain comprehensive audit logs.

## Q13: Optimal Inference Stack

### Current RTX 3060
Qwen3 8B at Q4_K_M (~5.0GB), ~40 tok/s through Ollama. Q5_K_M (~5.7GB) = 95% quality retention, sweet spot for 12GB.

### RTX 3090 (planned)
Primary: **Qwen3 14B Q5_K_M (~10.5GB)** — 81.1 MMLU, major quality improvement.
Alternative: **Qwen3 30B-A3B (MoE) Q4_K_M (~18.6GB)** — only 3B active params, ~87 tok/s (faster than 8B dense!), 14B-class quality.

### PEFT Winner
Comprehensive eval (arXiv:2512.23165, Dec 2025): **DoRA surpasses full fine-tuning** at 46.6% vs 44.9%, outperforming standard LoRA by 4.1pp. PiSSA: catastrophic failure in RL (0.2% accuracy) — avoid. QDoRA via Unsloth = recommended: `use_dora=True`.

Caveat: "Learning Rate Matters" (arXiv:2602.04998): with proper tuning, all methods converge within 0.43% at rank 128.

### Inference Engines
At concurrency=1: differences shrink to 10–20%. Stay with **Ollama for Phase 1**, consider llama-server Phase 2 (speculative decoding). **Skip TensorRT-LLM entirely** — 10–30% gain imperceptible for single-user.

Speculative decoding with Qwen3 0.6B draft model (~0.7GB): 1.5–2× speedup for structured financial outputs. Implementation: `--model-draft` flag in llama.cpp.

### Optimal RTX 3090 Config
| Component | Choice | Rationale |
|---|---|---|
| Model | Qwen3 14B Q5_K_M (~10.5GB) | Best quality/VRAM |
| Alternative | Qwen3 30B-A3B Q4_K_M (~18.6GB) | 14B quality, faster inference |
| Fine-tuning | QDoRA via Unsloth | Best PEFT for reasoning |
| Draft model | Qwen3 0.6B Q8_0 (~0.7GB) | Speculative decoding |
| KV cache | Quantized (q8_0 keys, q4_0 values) | ~50% VRAM savings |
| Engine | Ollama → llama-server Phase 2 | Simplicity → spec. decoding |
| Total VRAM | ~14–15GB of 24GB | 9–10GB headroom |

## Conclusion: Three Moves That Matter Most

1. **Statistical infrastructure > AI**: PSR/MinTRL/DSR/Triple Penance Rule cost 20 hours and provide the decision-making foundation for every phase gate.

2. **RL is not optional but GRPO is wrong for 969 examples**: REINFORCE++ is explicitly more stable on small prompt datasets. This single choice may determine whether RL produces a better model or an overfit one.

3. **Binding constraint is closed trades**: Only way to Phase 4 by December 2026 is launching Strategy 2 by August. Every other bottleneck compresses 3–10× with Claude. Market time cannot.

Competitive landscape: 0.1–0.5% survival rate means simply sustaining 12+ months places Halcyon in rarefied territory. Pullback on S&P 100 faces genuine alpha compression (McLean & Pontiff 58% post-publication decay), but Grossman-Stiglitz floor guarantees some edge remains. Path forward: regime awareness, less-competed universes, obsessive data collection.

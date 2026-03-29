# Halcyon Lab: Complete research agenda from validation to scale

**The single most important finding across all 13 research questions is this: Halcyon Lab's current pipeline design (Qwen3 8B + QLoRA + SFT → GRPO) is architecturally validated by every successful financial reasoning model published in 2025–2026, but three critical adjustments should be made before Phase 2.** First, switch the planned GRPO stage to REINFORCE++ — research shows GRPO's local normalization causes overfitting on small prompt datasets like the 969-example training set. Second, implement the Deflated Sharpe Ratio and Minimum Track Record Length frameworks immediately — at 5 closed trades, the system has zero statistical significance, and these tools define exactly when evidence becomes trustworthy. Third, deploy a simple three-indicator regime detection overlay (VIX + 200-DMA + credit spreads) to address the system's biggest structural weakness: generating zero signals in bear markets.

The broader research landscape reveals a paradox. The AI-powered retail quant space is simultaneously more crowded than ever — **300,000+ registered users on QuantConnect alone** — and less competitive than it appears, because fewer than 1% of experimenters sustain live trading beyond six months. Pullback-in-uptrend on S&P 100 is among the most competed strategy-universe combinations possible, yet the Grossman-Stiglitz paradox guarantees alpha cannot reach zero. The path forward depends on execution, not novelty. With unlimited Claude access, the realistic fastest path to Phase 4 reaches December 2026 at approximately **25–35% probability**, gated primarily by the irreducible constraint of needing ~500 closed trades across two strategies.

---

## Master priority matrix across all 13 questions

Before diving into each question, this matrix distills the single most important action from each research area, ranked by urgency.

| Priority | Action | Question | Effort | Phase gate |
|----------|--------|----------|--------|------------|
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
| 🟢 11 | Implement CPCV validation framework | Q1 | 16–24 hrs | Can wait Phase 3 |
| 🟢 12 | Multi-strategy LoRA adapter architecture | Q10 | Medium | Can wait Phase 3 |
| 🟢 13 | Upgrade to RTX 3090 + Qwen3 14B | Q13 | Hardware | Can wait Phase 2–3 |
| ⚪ 14 | Advanced execution optimization (TWAP/VWAP) | Q5 | N/A | Skip until $500K+ |
| ⚪ 15 | TensorRT-LLM optimization | Q13 | N/A | Skip entirely |

---

## Q1: What separates systems that survive validation from those that fail at scaling

The academic literature converges on a clear hierarchy of validation tools, and Halcyon Lab's current position — 5 closed trades, 23 open — places it in the "pre-statistical" zone where the most important work is *infrastructure*, not analysis.

**The Deflated Sharpe Ratio (DSR) framework** from Bailey and López de Prado (2014, *Journal of Portfolio Management*) corrects for two inflation sources: non-normal returns and selection bias from multiple testing. The critical requirement is recording ALL backtest trials from day one. If only the winning strategy is logged, DSR becomes meaningless later. The companion Probabilistic Sharpe Ratio (PSR) from Bailey and López de Prado (2012, *Journal of Risk*) provides the **Minimum Track Record Length (MinTRL)** formula, which tells Halcyon exactly when its results become statistically trustworthy. For a strategy with an annualized Sharpe of 1.0, normally distributed returns, and 95% confidence, MinTRL requires approximately **68 trade-level observations**. If the Sharpe is only 0.5, this balloons to 270+. Negative skewness and fat tails increase the requirement further.

**Walk-Forward Analysis**, invented by Robert Pardo (2008, *The Evaluation and Optimization of Trading Strategies*, Wiley), remains the industry baseline but has known weaknesses documented by López de Prado: it tests only a single historical path and is "no harder to overfit than walk-backward." The upgrade path is **Combinatorial Purged Cross-Validation (CPCV)** from *Advances in Financial Machine Learning* (2018, Chapter 12), which partitions data into N groups and tests all C(N,k) combinations, producing a distribution of performance metrics rather than a single point estimate. Arian et al. (2024, *Knowledge-Based Systems*) confirmed CPCV's superiority over WFA in a controlled synthetic environment.

The **Triple Penance Rule** (Bailey and López de Prado, 2014, *Journal of Risk*) provides the psychological scaffolding for scaling: **recovery from maximum drawdown takes approximately 3× the formation period** under standard assumptions. A 20% drawdown that forms over 2 months will take ~6 months to recover. At $100 this is trivial; at $25K (Phase 4), a 20% drawdown is $5,000. Drawdown tolerance must be defined before scaling, not during — and Halcyon's graduated six-phase approach is precisely the right architecture for building psychological tolerance alongside capital.

**Ernest Chan's** key insight from *Quantitative Trading* (2009, Wiley) is that small traders have a structural **capacity advantage** — they can exploit inefficiencies too small for institutional funds. At all planned phases ($100→$500K), Halcyon's positions represent less than 0.001% of daily volume for any S&P 100 stock. Market impact is essentially zero. The binding constraint is not liquidity but strategy decay and regime dependence.

**Priority tier:** Must do before Phase 2. **Estimated effort:** 30–40 hours total for full implementation (PSR, DSR, drawdown protocol, execution tracking). **Claude compression:** 4–5× acceleration on implementation, 0× on data collection. **Failure modes:** Not recording all trials; premature scaling based on insufficient evidence; abandoning strategy during normal drawdown.

---

## Q2: Financial LLM and RL advances that should change the pipeline

The last twelve months produced a remarkable convergence: **every successful financial reasoning model** (Trading-R1, Fin-R1, Alpha-R1, DianJin-R1) follows the identical pipeline of data distillation → SFT → reinforcement learning, validating Halcyon's planned architecture. But three specific findings demand immediate pipeline adjustments.

**REINFORCE++ should replace GRPO** as the planned RL method. Hu (2025, arXiv:2501.03262) demonstrated that GRPO's local advantage normalization causes immediate overfitting on small prompt datasets, while REINFORCE++ with global normalization learns more stably and shows superior out-of-distribution performance. With only 969 training examples, this is not a theoretical concern — it is the primary failure mode for the RL stage. REINFORCE++ is simpler than GRPO (k=1 sample sufficient), available in TRL, and requires only **12GB VRAM**. The related Dr. GRPO (Lan, 2025) identifies and removes GRPO's question-level difficulty bias, offering an alternative algorithmic fix if GRPO is retained.

**Trading-R1** (Xiao et al., September 2025, arXiv:2509.11420) is the most directly comparable system to Halcyon Lab. It uses a three-stage easy-to-hard curriculum with volatility-adjusted reward labeling on the Tauric-TR1-DB dataset (100K samples, 14 equities, 5 data sources). On NVIDIA stock, it achieved **8.08% cumulative return, Sharpe 2.72, 70% hit rate, and 3.80% max drawdown**, outperforming GPT-4.1. The clear performance hierarchy was: small LMs < reasoning LMs < large LMs < Trading-SFT ≈ Trading-RFT < Trading-R1 — confirming that RL on top of SFT produces a meaningful leap.

**Alpha-R1** (arXiv:2512.23515, 2025) provides the starkest validation: a **Qwen3-8B base model without RL alignment produces a Sharpe of -0.77** for alpha factor screening. With RL optimization, performance dramatically improves with zero-shot generalization from CSI 300 to CSI 1000. This confirms that SFT alone is insufficient — the RL stage is not optional for Halcyon.

On the fine-tuning side, Lian (November 2025, arXiv:2512.00630) published **"Financial Text Classification Based on rLoRA Fine-tuning on Qwen3-8B"** — the closest existing work to Halcyon's setup. It uses NEFTune + rLoRA + FlashAttention on the exact same base model for financial tasks and outperforms T5, BERT, RoBERTa, and both LLaMA variants. This paper should be read immediately. The broader community consensus is that **QLoRA + DoRA via Unsloth** is the current best practice for consumer GPU fine-tuning. DoRA (Liu et al., ICML 2024) decomposes weights into magnitude and direction, applying LoRA only to direction, yielding ~8% VRAM savings with no quality loss. Implementation is trivial: `use_dora=True` in Unsloth.

For self-blinding validation, the field has rapidly matured. Gao, Jiang, and Yan (December 2025, arXiv:2512.23847) introduced the **"Lookahead Propensity" (LAP) metric** demonstrating that LLMs memorize historical outcomes and inflate backtesting performance. Entity-neutering (Engelberg et al., 2025) — removing identifying details from prompts — validates Halcyon's self-blinding approach as the gold standard. ChronoBERT and NoLBERT (2025) further confirm that training-time data control is essential for preventing lookahead bias.

**Constrained decoding** via XGrammar (Dong et al., MLSys 2025) has become the standard for guaranteed structured JSON output from local models, with near-zero overhead. This is a significant advantage of self-hosted inference over API-based models and should be adopted for production reliability.

**Priority tier:** REINFORCE++ switch and data augmentation are Must do before Phase 2; DoRA upgrade and constrained decoding are Important for Phase 2. **Estimated effort:** 8–12 hours for REINFORCE++ research and adaptation; 20 hours for Claude-powered data augmentation. **Claude compression:** 10× on data augmentation and quality scoring. **Key failure mode:** Skipping the RL stage entirely, which Alpha-R1 proves is the difference between negative and positive Sharpe.

---

## Q3: The crowding landscape is worse than it looks — and better than it looks

The brutal honest assessment: **pullback-in-uptrend on S&P 100 is among the most competed strategy-universe combinations in existence**. But the competition is far less capable than the raw numbers suggest.

QuantConnect reports **300,000+ registered members** and 200,000+ lifetime live algorithm deployments. Freqtrade has 39,900 GitHub stars. The global algorithmic trading market reached **$18.7 billion in 2025**, with retail investors accounting for ~43% of algo-trading activity. AI now powers over 70% of U.S. equity trades. These numbers look terrifying.

But the pipeline attrition data tells a different story. The realistic funnel: of everyone who starts learning quant trading, approximately **30–40% complete a working backtest**, 5–10% pass robustness testing, 3–5% deploy live (paper or real), 1–2% sustain live trading beyond six months, and **0.1–0.5% sustain profitable live trading beyond two years**. This means QuantConnect's 300,000 users translate to perhaps 300–1,500 sustained profitable operators. The number fine-tuning open-source LLMs specifically on financial data and deploying live is likely in the **low hundreds globally**.

The academic evidence on alpha decay is unambiguous. McLean and Pontiff (2016, *Journal of Finance*) studied 97 published return predictors and found portfolio returns are **26% lower out-of-sample and 58% lower post-publication**. The additional 32% decline is directly attributed to publication-informed trading. Critically, post-publication declines are greatest for predictors with higher in-sample returns and for stocks with low idiosyncratic risk and high liquidity — **exactly the S&P 100 characteristics**.

However, momentum — the closest academic cousin to pullback-in-uptrend — tells a more optimistic story. Jegadeesh and Titman's 2023 thirty-year follow-up found that **momentum profits remained large and significant across three decades post-publication**, likely because the effect is driven by deep behavioral biases (underreaction) rather than simple mispricing. This suggests that behavioral alpha sources can survive widespread knowledge, though momentum crash risk has increased (Daniel and Moskowitz, 2016, *Journal of Financial Economics*).

Pairs trading provides the cautionary tale. Gatev, Goetzmann, and Rouwenhorst (2006, *Review of Financial Studies*) documented 11% annualized excess returns. Returns dropped from **118 bps/month pre-1989 to 38 bps/month post-1989**. Do and Faff (2010, *Financial Analysts Journal*) confirmed the continuing decline, finding that after time-varying transaction costs, the distance method on average yields zero positive returns.

The key question for Halcyon is not whether pullback alpha exists — it does — but whether the AI layer adds genuine signal above what is already priced in. Stambaugh, Yu, and Yuan (2012, 2015) found anomaly returns concentrate in the **short leg** (overpriced stocks). Long-only strategies on liquid S&P 100 stocks capture less anomaly alpha because the short leg is where mispricing concentrates, and S&P 100 stocks have the lowest idiosyncratic risk in the market. Expanding beyond S&P 100 to mid-caps would access less-competed alpha, consistent with McLean and Pontiff's finding that anomaly returns persist more in stocks with high idiosyncratic risk and low liquidity.

**Priority tier:** Important for Phase 2–3 (strategy universe expansion research). **Estimated effort:** 12–16 hours. **Expected value:** Potentially the highest-impact strategic decision — universe expansion from S&P 100 to S&P 500 could meaningfully increase available alpha. **Claude compression:** 3× on literature review; 0× on market observation.

---

## Q4: AI-dominated price discovery compresses alpha but cannot eliminate it

The Grossman-Stiglitz paradox (1980, *American Economic Review*) provides the theoretical foundation: if markets were perfectly efficient, no one would incur the cost of gathering information, causing prices to become uninformative. **There is always a floor to alpha** — it is set by the cost of building and maintaining the AI systems themselves. The question is whether Halcyon's costs (compute, time, opportunity cost of founder labor) fall below this floor.

Agent-based modeling from the Santa Fe Institute offers empirical texture. Arthur, Holland, and LeBaron's (1997) artificial stock market showed that when many agents use similar strategies, their collective behavior can either reinforce or destabilize prices depending on the **ecology of strategies present**. Farmer (2002, *Industrial and Corporate Change*) developed the market ecology concept — financial firms as species in an ecosystem — showing that market impact limits the size of any strategy, and a market "food web" describes how strategies influence each other's profits. This is directly relevant: as more AI agents run pullback strategies, pullbacks become shallower and briefer, reducing per-trade alpha but not eliminating it.

The HFT arms race provides a concrete precedent. Budish, Cramton, and Shim (2015, *Quarterly Journal of Economics*) documented that the arms race **did not reduce the size of the arbitrage prize** — it just compressed the time window for capture. ES-SPY median arbitrage profitability remained constant at ~0.08 index points while duration compressed from 97ms to 7ms. Aquilina, Budish, and O'Neill (2022, *QJE*) found that latency-arbitrage races occur approximately once per minute per symbol for FTSE 100 stocks, with the **top 6 firms capturing over 80% of all race outcomes**. The lesson: competition becomes winner-take-most, but total alpha persists.

For pullback strategies specifically: when most pullback buyers are algorithms, pullbacks become more "efficient" — shorter duration, shallower depth, more V-shaped recoveries. The easy alpha from simple RSI-based pullback entries disappears. The edge shifts to: identifying pullbacks algorithms won't buy (catalytic/fundamental triggers), regime detection (knowing when pullbacks are genuine dislocation vs. noise), and **better position sizing and risk management**, which may now contain more alpha than signal generation itself.

The most AI-resistant alpha sources are regime awareness and adaptation (most models are trained on historical regimes), catalyst-driven pullbacks (identifying the cause rather than just the pattern), behavioral and positioning signals (crowding metrics, options positioning), and **stress/dislocation trading** — Do and Faff (2010) found pairs trading performed best during bear markets, and pullback strategies likely share this episodic alpha characteristic.

**Priority tier:** Important for Phase 2–3 (strategic positioning). **Estimated effort:** 8–12 hours. **Expected value:** Shapes the 3–5 year strategic direction. **Claude compression:** 5× on synthesis; 0× on market observation. **Key insight:** "AI as market infrastructure" (table stakes) rather than "AI as alpha generator" (edge) is the accurate framing for 2026–2030. Build for a world where everyone has AI; the edge comes from proprietary data, regime awareness, and execution quality.

---

## Q5: Execution quality is irrelevant at current scale but measurement infrastructure matters now

The math is definitive: for a $25,000 order on AAPL (daily volume ~$16 billion, σ ≈ 1.5%/day), the Bouchaud square-root law of market impact (Bouchaud, 2010; Tóth et al., 2012, *Quantitative Finance*) predicts impact of approximately **0.002 basis points** — literally unmeasurable. Even at $1 million, impact is approximately 0.01 bps. S&P 100 stocks have bid-ask spreads of **1–5 basis points**, meaning a $10,000 market order costs $1–5 in spread. TWAP, VWAP, and Almgren-Chriss optimal execution frameworks (Almgren and Chriss, 2000, *Journal of Risk*) solve problems that simply do not exist at Halcyon's planned scale.

The threshold where execution research becomes critical for S&P 100 stocks is approximately **$5 million per order** (where participation exceeds 0.1% of average daily volume). This is 200× beyond Phase 6's maximum position size.

Alpaca's execution routes through Virtu Americas, Citadel Execution Services, and Jane Street via payment for order flow. Retail order flow is considered "uninformed" by market makers, meaning they typically provide **price improvement of 0.1–1 cent per share** versus the national best bid/offer. For Halcyon's purposes, this is adequate. The difference between Alpaca and best-in-class execution (Interactive Brokers with direct market access) is less than 1–2 bps per trade at this scale.

**What matters now is building measurement infrastructure.** Implementation Shortfall (Perold, 1988, *Journal of Portfolio Management*) — the difference between paper portfolio return and actual portfolio return — is the key metric. Log the decision price (mid-price at signal generation), execution price (actual fill), and compute per-trade IS in basis points from day one. If IS exceeds 10% of gross alpha at any point, investigate. This data becomes critical later when scaling.

The practical recommendation is trivial: **switch from market orders to limit orders at the ask** (saves 0.5–2 bps per trade, adds no execution risk on liquid names during regular hours) and start logging. Total effort: 2 hours.

**Priority tier:** Limit order switch is Must do now (trivial); IS tracking is Must do before Phase 2 (4–6 hours); advanced execution research can wait until Phase 5+ ($500K). **Failure mode:** Not measuring, then discovering systematic slippage only after scaling.

---

## Q6: A minimum viable regime detection system that addresses the biggest weakness

Halcyon's most significant structural vulnerability — generating zero signals in bear markets — is actually partially protective behavior. The system self-selects favorable conditions. The real danger is not bear markets themselves but **regime transitions**: catching falling knives during the early stages of a bear before the regime is clear. Daniel and Moskowitz (2016, *Journal of Financial Economics*) documented that momentum strategies experience catastrophic crashes specifically at the transition from bear to bull markets.

Hamilton's (1989, *Econometrica*) foundational HMM regime-switching framework and Ang and Bekaert's (2002, 2004, *Review of Financial Studies* and *Financial Analysts Journal*) extensions both confirm that **regime-switching strategies outperform static strategies out-of-sample**. Two regimes (bull/bear) is standard and most robust — adding more regimes increases overfitting risk without proportional benefit. The practical limitation is detection lag: HMMs need **20–60 daily observations** to confidently identify a regime change, by which point a 10–20% drawdown may have already occurred.

The minimum viable approach is a **"Traffic Light" system** using three indicators chosen for low overfitting risk and complementary information content:

- **VIX level:** Green (<20), Yellow (20–30), Red (>30)
- **S&P 500 vs 200-day moving average:** Green (above), Yellow (within 3%), Red (below)
- **High-yield credit spread z-score** (vs 1-year moving average): Green (<0.5σ), Yellow (0.5–1.5σ), Red (>1.5σ)

Score Green=2, Yellow=1, Red=0. Total 0–6. At 5–6: full position sizing. At 3–4: 50%. At 0–2: cash or minimal positions. This system has only 3 inputs (nearly impossible to overfit), is rules-based (no parameter estimation), can be validated across 50+ years of data, and captures volatility, trend, and credit information independently.

**Regime-aware position sizing is more robust than regime-aware strategy selection** for Phase 1–2. Position sizing adjusts one parameter gradually, is less prone to overfitting, and works even when regime detection is noisy. Strategy selection requires multiple validated strategies and carries higher complexity. Per Nystrup et al. (2015, 2017), volatility-targeting frameworks that scale position sizes by inverse realized volatility capture most of the regime-adjustment benefit.

The advanced path — HMM-based detection using Hamilton's framework — becomes viable in Phase 2–3 once sufficient data accumulates. Recent work by Shu et al. (2024, arXiv:2402.05272) shows Statistical Jump Models capture regime changes with better stability than HMMs. A Wasserstein HMM approach (arXiv:2603.04441, 2025) achieved Sharpe 2.18 versus 1.18 for SPX buy-and-hold with maximum drawdown of -5.43% versus -14.62%.

**Priority tier:** Traffic Light system is Must do before Phase 2 (8–16 hours). HMM implementation is Important for Phase 2–3. **Claude compression:** Claude can pull VIX, credit spreads, and breadth data daily and compute regime scores — and uniquely, can combine quantitative signals with qualitative judgment about current conditions, something pure quant systems cannot do. **Failure modes:** Overfitting (resist adding indicators), whipsaw (require 5+ day persistence filter), hindsight bias (strict walk-forward validation only).

---

## Q7: The critical path to Phase 4 runs through Strategy 2 launch by August 2026

**Irreducible constraints define the timeline.** With 23 open positions cycling every ~15 days, steady-state throughput is approximately **30–40 closed trades per month**. At 5 closed trades as of March 27, Halcyon has zero statistical significance. The MinTRL formula requires 30–70 trades minimum for preliminary PSR assessment (depending on observed Sharpe) and 200+ for reliable validation per López de Prado's institutional standard.

The critical path model, using 35 trades/month with a single strategy:

| Date | Cumulative trades | Milestone |
|------|-------------------|-----------|
| April 2026 | ~40 | First statistical signal visible |
| June 2026 | ~110 | MinTRL possibly satisfied; Phase 1→2 transition |
| August 2026 | ~180 | Regime coverage assessment possible |
| September 2026 | ~215 | Reliable CPCV; DSR computable |

**With one strategy alone, 500 trades requires ~14 months — reaching March 2028.** Phase 4 by December 2026 is impossible with a single strategy.

**With dual-strategy operation:** If Strategy 2 launches by August 2026 and generates ~35 trades/month, combined throughput doubles to ~70/month. From August to December: 5 months × 70 = 350 new trades + ~175 already closed = **~525 total.** This reaches the 500-trade threshold. Probability estimate: **25–35%** of reaching Phase 4 by December 2026. Primary risks: strategy underperformance forcing delays at any gate, or Strategy 2 development taking longer than expected.

Unlimited Claude access compresses dramatically: training data generation (**10×** faster), quality scoring (**8×**), research parallelization (**5×**), Strategy 2 development (**3–4×** — from 3–6 months down to 4–8 weeks), code implementation (**5×**), and statistical framework setup (**4–5×**). But Claude **cannot** compress: 15-day hold periods, closed trade outcomes, regulatory timelines, or the need for multiple regime exposures. If March–December 2026 is entirely bullish, there is zero bear market data regardless of Claude's capabilities.

**The single highest-leverage action for timeline compression is beginning Strategy 2 research immediately** — using Claude to parallelize strategy development while Strategy 1 accumulates trades. Target: Strategy 2 live by August 2026.

---

## Q8: Ten popular research topics evaluated as traps or valuable

The evaluation framework: at Halcyon's current scale ($100 live, solo founder, RTX 3060, 969 examples), the opportunity cost of distraction is existential. Every hour spent on marginal research is an hour not spent improving the core pullback signal and expanding training data.

**Clear traps (avoid entirely in Phase 1–2):**

**High-frequency tick data** (95% confidence trap): Halcyon trades 2–15 day holds. HFT requires co-location ($10K–$50K/month), FPGAs, and millions in capital. This is an entirely different business with zero overlap.

**Neural architecture search** (95% trap): NAS requires enormous compute; with 969 examples, the bottleneck is data not architecture. NAS would find the architecture that overfits most elegantly.

**Building custom transformers from scratch** (95% trap): Halcyon is already fine-tuning Qwen3 8B — this is the correct approach. Training from scratch on 969 examples is mathematically absurd. Even Renaissance Technologies' edge is automated signal discovery pipelines, not custom architectures.

**Real-time social media sentiment** (85% trap): Academic evidence shows R² of 0.0006 for daily sentiment versus next-day stock returns (arXiv:2508.02089). Infrastructure costs ($100–500/month) dwarf a $100 account. For 2–15 day holds, social media is primarily a short-term signal.

**Custom data infrastructure** (85% trap): Polygon, Alpha Vantage, and yfinance provide sufficient daily OHLCV for S&P 100 at $0–30/month. Building PostgreSQL + Docker + Airflow pipelines for data fetchable in 3 lines of Python is the "data engineer identity trap."

**Real-time news NLP** (80% trap): For 2–15 day holds, news alpha exists in the first minutes. By the time NLP processes it, the information is priced in. Use pre-built APIs if needed.

**Traps at current scale but valuable later:**

**Complex portfolio optimization** (75% trap now, valuable at Phase 3+): With $100 and 1–3 positions, mean-variance is irrelevant. Simple equal-weight or inverse-volatility suffices. Black-Litterman requires reliable return views that cannot be produced yet.

**Crypto/forex expansion** (70% trap now): Strategy diversification before proving core strategy is a classic mistake. Pursue only after 12+ months of profitable equity trading.

**Proprietary backtesting engine** (65% trap): Backtrader, VectorBT, and QuantConnect cover 90%+ of needs. A lightweight script tailored to pullback scanning (1–2 weeks) is valuable; a full "engine" (3–6 months) becomes the product instead of the strategy.

**Options pricing** (90% trap now): At $100 capital, options trading is infeasible. Use QuantLib if needed in Phase 4+.

---

## Q9: The data moat thesis is partially valid but needs refinement

Halcyon's thesis that the data asset is the most defensible component is challenged by Andreessen Horowitz's landmark analysis, **"The Empty Promise of Data Moats"** (Casado and Lauten, 2019). Their central finding: data scale effects have **diminishing returns** — the cost of unique data increases while incremental value decreases. "Defensibility is not inherent to data itself." The AI flywheel effectiveness is moderated by localized learning and diminishing returns (Hampton Global Business Review, 2025).

However, Two Sigma's example supports a refined version of the thesis. Processing **380+ petabytes from 10,000+ sources**, their pipeline — source → clean/label/validate → transform into features → model → execute — demonstrates that the moat lies not in raw data but in the **processing know-how** that transforms data into predictive features. Renaissance Technologies' approach, as documented in Zuckerman's *The Man Who Solved the Market* (2019) and the Acquired podcast (Season 14, Episode 3, 2024), emphasizes automated signal discovery: they don't hire researchers to derive models but to improve methods for **automatically extracting signals**. Whether data is public makes little difference because signals come from combining tens of thousands of indicators.

The refined thesis for Halcyon: the defensible moat is not the data itself but the **accumulated mapping of signal → context → outcome** across diverse market conditions. This maps to a specific data collection strategy starting from day one.

**Tier 1 data to collect immediately (zero cost):** Every prediction the model makes (taken and rejected) with subsequent actual price movement. Full trade execution logs with market context (VIX, SPY trend, sector rotation, model confidence, features used). Model confidence calibration data (predicted probability vs. actual hit rate). "Near miss" data — setups that almost triggered but didn't. This last category is the most underrated: **negative examples are equally valuable as positive ones**, and logging rejected trades avoids the selection bias that plagues most training datasets.

**Moat measurement over time:** Track out-of-sample Sharpe ratio on a rolling 6-month basis (declining = shrinking moat), Information Coefficient of features over rolling windows, model calibration via Brier score, and alpha decay rate for each signal. Create a monthly "Moat Scorecard." If 3+ metrics go red for 2+ months, the moat is shrinking and strategy needs revision.

**Porter's framework** applied to Halcyon yields one viable strategy: **focused differentiation** in a low-capacity niche that large firms ignore. Cost leadership is impossible against institutional resources. Broad differentiation requires unavailable scale. The S&P 100 pullback niche with AI-driven filtering at small position sizes is precisely the kind of niche that falls below institutional radar.

**Priority tier:** Data logging infrastructure is Must do before Phase 2; moat measurement is Important for Phase 2–3. **Estimated effort:** 4–8 hours for logging infrastructure, 6–8 hours for moat scorecard. **Key resource:** Zuckerman, *The Man Who Solved the Market* (2019) — essential reading for understanding how small quant firms built durable advantages.

---

## Q10: Multi-strategy framework built on inverse-volatility weighting and LoRA adapters

The mathematical conditions for when adding a second strategy improves risk-adjusted returns are elegantly simple. Adding Strategy B to existing Strategy A improves portfolio Sharpe if and only if **SR_B > ρ(A,B) × SR_A**, where ρ is the correlation between strategy returns. If strategies are uncorrelated (ρ=0), any positive-Sharpe strategy improves the portfolio. If ρ=0.3 and SR_A=1.0, Strategy B needs only SR_B > 0.3. This is from Sharpe (1994) and Grinold and Kahn's (2000) *Active Portfolio Management*.

For capital allocation with limited track records, **inverse-volatility weighting** (risk parity lite) is the clear starting point — it requires only variance estimates, not return forecasts, making it robust with small samples. Fractional Kelly (¼ to ½ Kelly) is the Phase 3 upgrade once 200+ trades per strategy are accumulated. MacLean, Thorp, and Ziemba (2010, *The Kelly Capital Growth Investment Criteria*, World Scientific) showed that half-Kelly achieves ~75% of optimal growth with ~50% of volatility. Full Kelly is never appropriate with estimation uncertainty this high. Hierarchical Risk Parity (López de Prado, 2016) provides the advanced framework but degenerates to inverse-variance weighting with only 2 strategies.

**Strategy-specific LoRA adapters are well-supported by research.** S-LoRA (Sheng et al., 2023) demonstrated serving thousands of concurrent LoRA adapters from a single base model with unified memory management. Each adapter is only **16–50MB** for an 8B model. META-LORA (2024) showed effective multi-task fine-tuning with as few as 50 examples per task. TT-LoRA MoE (2025) adds sparse routing that automatically selects the appropriate adapter per input using only 0.03% of AdapterFusion parameters. The architecture — frozen Qwen3 8B base with hot-swappable per-strategy LoRA adapters — is highly feasible and memory-efficient.

The minimum track record before deploying a second strategy is **100 live trades** (absolute minimum, basic statistical reliability) to **200+ trades** (recommended, covering at least one significant market drawdown). Combined with PSR > 0.95, this provides reasonable confidence that Strategy 1 is genuinely profitable. At Halcyon's frequency, 100 trades requires 3–6 months; 200 trades requires 6–12 months.

Strategy interference detection should track rolling 30-day correlation between strategy returns, alerting when |ρ| > 0.3. With only 100 trades per strategy, Fisher z-transformation gives a 95% confidence interval of ±0.20 around the point estimate — sufficient to distinguish ρ=0 from ρ=0.4 but not from ρ=0.2. Use block bootstrap for more robust confidence intervals.

From the Citadel/Millennium pod model, the scalable elements for a solo operation are: **independent P&L tracking per strategy** (essential), centralized risk management (single set of portfolio-level rules), dynamic capital reallocation based on rolling Sharpe, and strict per-strategy stop-losses (10% drawdown → reduce allocation 50%; 15% → pause).

**Priority tier:** LoRA adapter architecture planning is Important for Phase 2; implementation is Phase 3. Capital allocation and interference monitoring are Must do at Phase 3 entry. **Estimated effort:** 20–30 hours for framework design and implementation. **Hardware:** On RTX 3090, the base model in 4-bit (~5GB) plus 2–3 LoRA adapters (~50MB each) leaves ample headroom. Scanning 100 tickers takes ~20–25 minutes per strategy.

---

## Q11: LLM reasoning quality is useful but unreliable — design around outcomes, not plausibility

The question of whether better LLM commentary produces better trading outcomes has no definitive answer, but the evidence leans toward a nuanced "sometimes, and less than you'd hope."

Kim et al. (2024, "Financial Statement Analysis with Large Language Models") found GPT-4 achieves ~60% accuracy in predicting earnings direction, with higher-confidence predictions showing **64% vs 57% accuracy** for high versus low confidence bins. Trading-R1 (2025) demonstrated that structured multi-stage reasoning outperforms unstructured approaches. But a critical 2025 finding from "Reasoning or Overthinking" (arXiv:2506.04574) showed that for financial sentiment analysis, **prompting LLMs for explicit reasoning reduces alignment with correct answers**. GPT-4o with no chain-of-thought achieved highest accuracy, and performance monotonically declined with increasing completion length.

The chain-of-thought faithfulness literature is sobering. Turpin, Michael, Perez, and Bowman (2023, NeurIPS) demonstrated that CoT explanations can be heavily influenced by biasing features that models fail to mention — they are **"plausible yet misleading."** Lanham et al. (2023, Anthropic) found that larger, more capable models produce *less faithful* reasoning, and models often "already know" the answer before completing their reasoning chain. The 2025 paper "Is CoT Reasoning a Mirage?" concluded that structured reasoning capability "largely arises from inductive biases shaped by in-distribution training data" and is "fragile and prone to failure even under moderate distribution shifts."

Kahneman and Klein's (2009, *American Psychologist*) framework on conditions for intuitive expertise is directly applicable: intuition can be trusted only when the environment has sufficient regularity ("valid cues") and the person has had adequate opportunity to learn regularities through practice with feedback. Pullback trading on S&P 100 has **moderate** environmental validity — patterns exist but are noisy — so structured process has value but cannot guarantee outcomes.

**The practical framework for Halcyon** has four stages. Stage 1 (50–100 trades): score every analysis 1–5 on a predefined rubric, track outcomes, build contingency tables. Too few trades for statistical significance; use as hypothesis generator. Stage 2 (100–200 trades): Spearman rank correlation between quality scores and P&L with bootstrap 95% CI. Fisher z-transformation shows that with N=100, the minimum detectable correlation at 80% power is **ρ ≥ 0.28**. If no signal at N=100, the relationship is either weak or nonexistent. Stage 3 (200–500 trades): logistic regression modeling P(win) as a function of quality, confidence, market regime, and volatility. Stage 4 (500+ trades): A/B test randomly assigning trades to "detailed reasoning" vs "simple signal" paths — the only way to establish causal evidence.

**The actionable takeaway:** Score every analysis from trade 1 so data accumulates, but design the system around outcome metrics rather than reasoning plausibility. Treat model commentary as a useful but unreliable window. The model may produce convincing pullback analysis while actually keying on simpler features. Monitor for distribution shift by comparing recent market conditions to training data characteristics.

**Priority tier:** Rubric scoring is Must do from day one (ongoing, minimal effort). Correlation testing is Important for Phase 2. A/B testing is Can wait until Phase 4+. **Failure mode:** Over-investing in reasoning quality at the expense of signal quality — beautiful analyses that lose money.

---

## Q12: The regulatory environment is the most favorable it has been in years

Under Chair Atkins (Trump administration), **no new AI-specific securities rules are anticipated**. The landmark 2023 Predictive Analytics Rule — which would have required firms to eliminate conflicts from AI use — was formally withdrawn on June 12, 2025 (SEC Release 33-11377). Any future action requires an entirely new proposal.

For Halcyon Lab trading personal funds through an LLC, the regulatory picture is straightforward. The Investment Advisers Act of 1940 defines an "investment adviser" as someone who advises **others** about securities for compensation. Trading your own money is not advisory activity and requires no registration. The critical line: **the moment Halcyon manages even one other person's money for compensation, investment adviser registration obligations activate**. Below $100M AUM, state registration applies; above $100M, SEC registration.

The SEC's 2025–2026 posture focuses on **"AI washing" enforcement** — punishing firms that lie about their AI capabilities — rather than regulating AI use itself. Key enforcement actions include Delphia + Global Predictions ($400K combined penalties, March 2024), Rimar Capital (~$310K, October 2024), and a $14M fraud case involving fake "AI-generated investment tips" (December 2025). Securities class actions targeting AI misrepresentations increased **100% between 2023–2024**.

The SEC created the Cyber and Emerging Technologies Unit (CETU) in February 2025 for investigating AI-related violations, and AI is an explicit FY2026 examination priority. But the focus is on registrant AI representations for accuracy, not on the use of AI for trading decisions. No enforcement action has targeted legitimate AI-driven trading.

Internationally, the EU AI Act explicitly does **not** classify AI-based algorithmic trading as high-risk. MiFID II applies technology-neutral organizational and conduct requirements. ESMA's February 2026 supervisory briefing addresses AI-specific risks including accumulated model drift. The UK FCA has taken a wait-and-see approach with no AI-specific rules, though the Treasury Committee has pushed for guidance by end of 2026.

**The specific risks for an autonomous AI system:** Market manipulation liability applies regardless of AI autonomy — if the system places orders interpretable as spoofing or layering, the operator is liable. Pattern Day Trader rules require $25K+ equity for 4+ day trades in 5 business days. Maintain comprehensive audit logs of all model decisions and trading rationale as a best practice.

**Priority tier:** Audit log infrastructure is Must do before Phase 2 (overlaps with data moat logging); regulatory monitoring is ongoing low-effort. SEC registration research is Must do before Phase 5 (managing others' money). **Estimated effort:** 2 hours to set up monitoring checklist; 8–12 hours for registration research when needed. **Key timeline risk:** Political composition change post-2028 could revisit AI rulemaking. Build good practices now.

---

## Q13: The optimal inference stack for RTX 3090 centers on Qwen3 14B with QDoRA

The hardware optimization research yields clear recommendations at each phase.

**On the current RTX 3060 12GB:** Qwen3 8B at Q4_K_M quantization (~5.0GB) leaves sufficient room for KV cache and delivers ~40 tok/s through Ollama. This is adequate for Phase 1. Q5_K_M (~5.7GB) offers 95% quality retention and is the sweet spot for 12GB VRAM.

**On RTX 3090 24GB (planned upgrade):** The primary model should be **Qwen3 14B at Q5_K_M** (~10.5GB), which scores 81.1 on MMLU and represents a major quality improvement over the 8B. An intriguing alternative is the **Qwen3 30B-A3B (MoE)** at Q4_K_M (~18.6GB): with only 3B active parameters, it runs at ~87 tok/s on the 3090 — *faster* than the 8B dense model — while delivering 14B-class quality. Both fit comfortably with room for quantized KV cache at 32K context length. QLoRA fine-tuning of the 14B model requires ~12–14GB VRAM via Unsloth, leaving headroom on the 3090.

**PEFT methods have a clear winner.** A comprehensive evaluation of 12+ methods (arXiv:2512.23165, December 2025) found **DoRA surpasses full fine-tuning** at 46.6% average accuracy versus 44.9%, outperforming standard LoRA by 4.1 percentage points. PiSSA suffered **catastrophic failure** (0.2% accuracy) in RL settings due to spectral misalignment — avoid it entirely. VeRA's extreme parameter reduction creates an expressivity floor insufficient for reasoning tasks. The practical recommendation is **QDoRA via Unsloth** (QLoRA + DoRA), activated with a single flag: `use_dora=True`.

An important caveat: "Learning Rate Matters" (arXiv:2602.04998, February 2026) argues that with proper hyperparameter tuning, all methods converge within 0.43% at rank 128 — suggesting hyperparameter tuning matters more than method selection. Still, DoRA is the default recommendation given its consistency.

**For inference engines:** At concurrency=1 (single-user), the differences between Ollama, vLLM, and SGLang shrink to 10–20%. The throughput hierarchy is TensorRT-LLM > SGLang ≥ vLLM > llama.cpp > Ollama, but **TensorRT-LLM should be skipped entirely** — the 10–30% gain is imperceptible for single-user workloads, and setup takes days. Stay with Ollama for Phase 1, consider llama-server for Phase 2 (speculative decoding support), and SGLang only if building multi-step agentic pipelines benefiting from RadixAttention prefix caching.

**Speculative decoding** with a Qwen3 0.6B draft model (~0.7GB) provides **1.5–2× speedup** for structured financial outputs, which have high token acceptance rates. Implementation via llama.cpp is straightforward with the `--model-draft` flag.

**Flash Attention 2** is supported on both RTX 3060 (Ampere) and RTX 3090, providing **2.5–4.5× speedup** over standard attention and 10–20× memory savings. Flash Attention 3 is Hopper-only (H100) — irrelevant for consumer GPUs. Most inference engines already use optimized CUDA kernels that capture partial FA2 benefits.

**The optimal RTX 3090 configuration:**

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Model | Qwen3 14B Q5_K_M (~10.5GB) | Best quality/VRAM ratio |
| Alternative | Qwen3 30B-A3B Q4_K_M (~18.6GB) | 14B quality, faster inference |
| Fine-tuning | QDoRA via Unsloth | Best PEFT method for reasoning |
| Draft model | Qwen3 0.6B Q8_0 (~0.7GB) | Speculative decoding |
| KV cache | Quantized (q8_0 keys, q4_0 values) | ~50% VRAM savings |
| Engine | Ollama → llama-server (Phase 2) | Simplicity, then spec. decoding |
| Context | 32K tokens | Full earnings reports |

Total VRAM budget: ~14–15GB of 24GB, leaving 9–10GB headroom.

**Priority tier:** Quantization optimization is a Phase 1 quick win; GPU upgrade and model switch are Important for Phase 2; speculative decoding is Can wait until Phase 2–3. TensorRT-LLM is Skip entirely. **Estimated effort:** 2–4 hours for Phase 2 setup after GPU upgrade.

---

## Conclusion: Three moves that matter most right now

Across all 13 research questions, the evidence converges on three meta-insights that should shape Halcyon Lab's next 90 days.

**First, the statistical infrastructure is more important than the AI.** At 5 closed trades, the system has no statistical evidence of edge. The PSR/MinTRL framework tells you exactly when evidence becomes trustworthy, the DSR prevents you from fooling yourself with multiple testing, and the Triple Penance Rule prevents you from abandoning a working strategy during normal drawdown. These tools cost 20 hours to implement and provide the decision-making foundation for every phase gate. Without them, every scaling decision is a guess.

**Second, the RL stage is not optional — but GRPO is the wrong algorithm for 969 examples.** Every successful financial reasoning model in 2025–2026 shows that SFT alone is insufficient and RL produces a meaningful performance leap. But REINFORCE++ is explicitly more stable than GRPO on small prompt datasets. This single methodological choice may determine whether the RL stage produces a better model or an overfit one.

**Third, the binding constraint is closed trades, and the only way to reach Phase 4 by December 2026 is launching Strategy 2 by August.** Every other bottleneck — data quality, model training, infrastructure, research — can be compressed 3–10× with unlimited Claude access. Market time cannot. Starting Strategy 2 research now, using Claude for parallelized development, is the highest-leverage action for the 9-month timeline.

The broader competitive landscape is both more crowded and less threatening than expected. The 0.1–0.5% survival rate among retail quant traders means that simply sustaining operation beyond 12 months places Halcyon in rarefied territory. The pullback strategy on S&P 100 faces genuine alpha compression — McLean and Pontiff's 58% post-publication decay applies in full force to liquid large-caps — but the Grossman-Stiglitz floor guarantees that informed, well-executed trading retains some edge. The path to a durable position runs through regime awareness, expanding to less-competed universes, and obsessive data collection that compounds into a genuine knowledge asset over years.
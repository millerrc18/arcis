# Arcis Research Framework

> **Last updated:** 2026-04-03
> **Sources:** 60+ research documents + 5 live research queries (Consensus, WebSearch)
> **Purpose:** Single authoritative research reference for all Arcis development decisions
> **Reading modes:** Collapsed `<details>` = agent reference (~900 lines) | Expanded = investor/educational (~1,500+ lines)

---

## 1. Trading Strategy Research

### 1.1 Pullback-in-Uptrend: The Primary Strategy

The pullback-in-uptrend strategy exploits the disposition effect — investors' tendency to sell winners too early and hold losers too long (Shefrin & Statman 1985). Frazzini (2006) demonstrated this creates momentum underreaction worth 2-4% annual alpha, which pullback entries harvest by buying temporary weakness within established uptrends.

<details>
<summary>What is a pullback-in-uptrend strategy?</summary>

Imagine a stock that has been steadily climbing for months. Occasionally, it dips — maybe bad news hits the sector, or the broader market has a rough week. A pullback strategy buys during these temporary dips, betting that the long-term upward trend will resume. It is like buying your favorite product on sale — the underlying value has not changed, you are just getting a better price.
</details>

**Academic evidence for S&P 100 applicability:**

| Finding | Effect Size | Source |
|---------|------------|--------|
| Pullback alpha concentrates in days 1-5 | 82-83% win rate, avg hold 3-5 days | Connors & Alvarez (multiple) |
| Momentum underreaction from disposition effect | 2-4% annual alpha | Frazzini 2006, *J. Finance* |
| Reversal returns amplify with VIX | Conditional Sharpe multiples of calm periods | Nagel 2012, *Rev. Financial Studies* |
| RSI(2) < 5 with 5-day time stop | 45 bps/trade, 64% hit rate (114,189 trades) | Concretum Group |
| Higher-vol stocks revert faster, more strongly | Reversals dissipate within ~2 weeks for large-caps | Dai, Medhat et al. 2024 |
| Post-crash rebounds create amplified MR alpha | Extreme positive returns post-momentum-crash | Daniel & Moskowitz 2016, *J. Financial Economics* |

**Optimal mechanical exit parameters (from deep research):**

| Parameter | Normal VIX (<20) | Elevated (20-30) | Crisis (>30) |
|-----------|-----------------|-------------------|---------------|
| Initial Stop | 2.0× ATR(14) | 2.5× ATR(14) | 3.0× ATR(14) |
| Profit Target | 2.0× ATR(14) | 2.5× ATR(14) | 3.0× ATR(14) |
| Timeout | 8 trading days | 7 days | 5 days |
| Stop Tightening | 2.0×→1.5× by day 5 | 2.5×→1.75× by day 5 | None |
| Signal Exit | Close > 5-day SMA | Close > 5-day SMA or RSI > 50 | First profitable close |

<details>
<summary>What is ATR and why does it matter for stops?</summary>

ATR (Average True Range) measures how much a stock typically moves in a day. A stock that moves $5/day has a different "normal" range than one that moves $0.50/day. Setting stops as a multiple of ATR means the stop adapts to each stock's personality — a volatile stock gets a wider stop so normal fluctuations do not trigger a premature exit, while a calm stock gets a tighter stop because a large move is genuinely unusual.
</details>

**Key insight — stops hurt mean-reversion entries:** Kaminski & Lo (2014, *J. Financial Markets*) found stop-losses help trend-following but hurt mean-reverting strategies. Connors Research (2004-2012) consistently found traditional stops reduce pullback performance. The optimal approach is **time-based exits** (timeout after 5-8 days) rather than tight price-based stops. The 2.0× ATR stop serves as a catastrophic-loss prevention floor, not an active management tool.

### 1.2 Mean Reversion (RSI-2): Strategy #2

Mean reversion via extreme RSI(2) readings provides the natural complement to pullbacks — it generates signals precisely when pullback setups go silent in bear markets.

<details>
<summary>What is mean reversion?</summary>

Mean reversion is the tendency of prices to snap back toward their average after moving too far in one direction. Think of a rubber band — stretch it too far and it snaps back. When a stock drops dramatically in a short period (becoming "oversold"), there is statistical evidence it tends to bounce back within days. This is the opposite of momentum — momentum says "what goes up keeps going up," while mean reversion says "what goes down too far bounces back."
</details>

**Post-publication evidence (2023-2026):**

The mean reversion anomaly shows regime-dependent survival. Giner et al. (2023, *Economic Modelling*) developed a semi-Markov model demonstrating that mean reversion is induced by age-dependent state termination probabilities — the longer a market state persists, the more likely it reverses. This provides theoretical grounding for RSI-based strategies.

However, Kitkanasiri et al. (2025, *ABAC Journal*) found RSI-based trading rules **do not significantly outperform buy-and-hold in most efficient markets** across 10 Asian exchanges (2013-2023). Mean reversion in returns is **stronger for small-caps than large-caps** across all horizons (Journal of Accounting and Finance, 2023). Micaletti (2023, *SSRN*) found modified oscillators outperform standard RSI across global equities.

**Implication for Arcis:** RSI(2) mean reversion for S&P 100 mega-caps faces the same efficiency headwind as other anomalies. Its value is primarily as a **regime complement** and **data generation engine** for the flywheel, not as a standalone alpha source. Effect sizes are attenuated for large-caps but non-zero in high-volatility regimes.

| Attribute | Pullback | Mean Reversion |
|-----------|----------|----------------|
| Signal | Price pulls back to support in uptrend | RSI(2) < 10 or price > 2 SD below 20-day MA |
| Hold period | 5-8 days | 1-5 days |
| Bear market signal freq | Drops to 0-1/month | **Increases** (more oversold readings) |
| Correlation with pullback | — | Low to negative |
| Primary value at $5K | Alpha generation | Data generation + regime continuity |

### 1.3 Why PEAD Is Dead for Large Caps

Post-Earnings Announcement Drift was once the strongest anomaly in finance. **It is now completely dead for S&P 100 stocks.**

Martineau (2022, *Critical Finance Review*) demonstrated PEAD has been zero for large caps since 2006, with prices fully adjusting on announcement day. Subrahmanyam (2025, working paper) confirmed that removing microcap stocks drops PEAD's t-statistic from 2.18 to 1.43 — well below significance.

<details>
<summary>What was PEAD?</summary>

Post-Earnings Announcement Drift was the finding that stocks which reported better-than-expected earnings continued to drift upward for weeks afterward — as if the market was slow to fully digest the good news. For decades, this was one of the most reliable patterns in finance. But for large, heavily-followed companies like those in the S&P 100, so many traders now jump on earnings surprises instantly that the drift has disappeared. The price adjusts within hours, not weeks.
</details>

**Implication:** Strategy #3 (Evolved PEAD) remains gated to Phase 3 and should target earnings revisions momentum rather than the classic drift, which no longer exists for the Arcis universe.

### 1.4 Position Sizing

**Kelly Criterion for Arcis parameters** (conservative: p=0.60, b=2.0):

```
f* = (p/a) - (q/b) = 0.60 - 0.20 = 0.40 (Full Kelly = 40% risk per trade)
```

<details>
<summary>What is the Kelly Criterion?</summary>

The Kelly Criterion is a formula that tells you the mathematically optimal amount to bet given your edge. If you win 60% of the time and your wins are twice your losses, Kelly says bet 40% of your bankroll each time. In practice, this is extremely aggressive — a bad streak would devastate your account. So professional traders use "fractional Kelly" — typically betting one-quarter to one-half of the Kelly amount. Arcis uses approximately quarter-Kelly (1% risk per trade), which limits maximum drawdowns to 5-8%.
</details>

| Parameter | Full Kelly | Half-Kelly | Quarter-Kelly | **Arcis Phase 1** |
|-----------|-----------|------------|---------------|-------------------|
| Risk per trade | 40% | 20% | 10% | **1%** |
| Max drawdown (95th %ile) | ~50% | ~25% | ~12% | ~5-8% |
| Growth rate (% of optimal) | 100% | 75% | 50% | ~15-20% |

**Equal weight (1/N) beats optimization until 200+ trades** — confirmed by deep research. DeMiguel, Garlappi & Uppal (2009) showed naive diversification outperforms mean-variance optimization for estimation windows under 250 months. With 13 closed trades, optimization is statistically meaningless.

### 1.5 Options Timing

**Minimum viable capital: $15-25K for defined-risk vertical spreads.**

The binding constraint is **bid-ask spread drag**. At $5K, options spread friction costs 19.2% annually — destructive. At $25K, friction drops to 3.8% — tolerable. At $50K, friction reaches 1.9% — acceptable.

<details>
<summary>What is a vertical spread?</summary>

A vertical spread is an options strategy where you buy one option and sell another at a different price on the same stock and expiration date. This caps both your maximum loss and maximum gain. Unlike buying a single option (where you could lose the entire premium), a vertical spread limits your risk to a known, fixed amount — typically $100-$250 per spread. It is like buying insurance with a deductible: you know exactly how much you could lose before you enter the trade.
</details>

---

## 2. Data & Signals

### 2.1 The 8 Orthogonal Signal Dimensions

For S&P 100 mega-caps at 2-15 day horizons, the maximum number of genuinely independent signal dimensions is approximately **8**. Additional dimensions add noise, not signal.

<details>
<summary>What does "orthogonal" mean here?</summary>

Orthogonal means the signals provide truly independent information — knowing one tells you nothing about the other. If you track both RSI and Stochastic Oscillator, they measure the same thing (short-term overbought/oversold) and are redundant. But RSI and credit spreads measure completely different aspects of the market. Having 8 orthogonal dimensions means 8 genuinely different lenses on each stock, which is far more valuable than 15 redundant indicators.
</details>

| # | Dimension | Source | Correlation w/ Others | Status |
|---|-----------|--------|----------------------|--------|
| 1 | Momentum/Trend | yfinance (EMA, ADX) | Anti-correlated w/ MR at −0.65 | Active |
| 2 | Mean-Reversion | yfinance (RSI, pullback depth) | Anti-correlated w/ momentum | Active |
| 3 | Volume/Liquidity | yfinance (OBV, vol ratio) | Low (0.10-0.20) | Active |
| 4 | Options-Implied | yfinance chains + Unusual Whales | Low (0.05-0.20) | Passive collection |
| 5 | Earnings Revisions | FMP (est_revisions) | Moderate w/ momentum (0.35) | **Highest-value unbuilt** |
| 6 | News/Sentiment | Finnhub | Moderate w/ momentum (0.30) | Active |
| 7 | Macro Regime | FRED (HY OAS, VIX, yields) | Low-moderate | Active (partial) |
| 8 | Cross-Asset | yfinance (DXY, gold/copper, BTC) | Moderate w/ macro (0.40) | Not built |

**Earnings revision momentum** is the highest-value signal not yet tracked. Chan, Jegadeesh & Lakonishok (1996, *J. Finance*) and Novy-Marx (2015) demonstrated it is significant even in the largest quintile with ~22%/yr gross returns and low post-publication decay.

### 2.2 What Does NOT Work for Mega-Caps

McLean & Pontiff (2016, *J. Finance*): published anomalies lose **58% of returns** post-publication, with decay greatest for large-cap, low-idiosyncratic-risk stocks.

| Signal | Why It Fails for S&P 100 | Source |
|--------|-------------------------|--------|
| Google Trends | Effect is "most pronounced among small stocks" | Da, Engelberg & Gao 2011, *J. Finance* |
| Reddit/StockTwits | No significant effect on mega-cap returns | Keasey 2025; Cookson et al. 2024, *JFE* |
| Congressional trading | No stock-picking alpha post-STOCK Act; 45-day delay | Belmont et al. 2022, *J. Public Economics* |
| Short interest | Negligible for easy-to-borrow mega-caps | Muravyev et al. 2021 |
| PEAD | Dead since 2006 for large caps | Martineau 2022, *Critical Finance Review* |
| Analyst dispersion | Concentrated in small stocks, learned away | Diether et al. 2002, *J. Finance* |
| Customer-supplier momentum | Lost significance post-discovery | Cohen & Frazzini 2008, *J. Finance* |

### 2.3 API Stack & Rate Limits

| Source | Daily Calls Used | Daily Limit | Binding? | Status |
|--------|-----------------|-------------|----------|--------|
| yfinance | ~26 batch | ~200-300 | Moderate risk (unofficial) | Active |
| Finnhub | ~3,000-5,000 | 23,400 | No | Active |
| **FMP** | ~99-200 | **250** | **Yes — primary constraint** | Active |
| FRED | ~20 | 46,800 | No | Active |
| SEC EDGAR | ~300 | 864,000 | No | Active |
| Alpha Vantage | ~20 | **25** | Yes — nearly useless | Deprioritized |

**FMP's 250/day free tier is the binding constraint.** The $19/month Starter plan is the single highest-ROI data expenditure available.

### 2.4 Four-Tier Scanning Cadence

| Tier | Interval | What | Rationale |
|------|----------|------|-----------|
| Position Monitor | 15 min (5 min near boundaries) | Open positions: price, stop/target proximity | Optimal stopping theory: near boundaries, checking more often is rational |
| Fast Scan | 30 min | Full universe: OHLCV, technicals, ranking | Price/technical half-life ~6.5 hrs |
| Medium Scan | 60 min | VIX, news, options, regime, LLM inference | Sentiment half-life 1-5 days |
| Slow Scan | Daily pre-market | FRED, insider, earnings, fundamentals | Half-life weeks to months |

<details>
<summary>Why not just scan everything every few minutes?</summary>

Different types of information go stale at vastly different rates. A stock's price changes every second, but a company's earnings report is relevant for months. Scanning earnings data every 30 minutes wastes API calls and compute without gaining useful information. The four-tier system matches scanning frequency to how fast each type of data actually changes — like checking weather hourly but your tax return annually.
</details>

**Staleness tolerance matrix (critical thresholds):**

| Dimension | Critical Threshold | Action |
|-----------|-------------------|--------|
| Price | > 15 min | Reduce position sizes 50%; skip new entries |
| VIX/Regime | > 2 hr | Assume neutral regime; widen stops |
| Sentiment | > 24 hr | Exclude from composite score |
| Fundamentals | > 7 days | Flag for manual review |

---

## 3. LLM Training Pipeline

### 3.1 Self-Blinding Architecture

The self-blinding pipeline is Arcis's most novel architectural decision. **No outcome information leaks into training data — by architecture, not instruction.**

<details>
<summary>What is self-blinding and why does it matter?</summary>

When training an AI to analyze trades, you need examples of trade analyses. But if the AI knows a trade was profitable when writing the analysis, it subtly cheats — using confident language for winners and hedging for losers. A human cannot spot this, but the trained model learns to fake confidence rather than develop real judgment.

Self-blinding solves this by never showing the AI the outcome. The first AI call writes the analysis with genuinely no knowledge of what happened. A second call improves writing quality — still without seeing the result. This is like asking a doctor to diagnose a patient without telling them the test results first.
</details>

**Two-stage pipeline:**
1. **Stage 1 (Claude Haiku 4.5):** Generate trade commentary from market data packet. Model has NO access to trade outcome.
2. **Stage 2 (Claude Haiku 4.5):** Improve writing quality of Stage 1 output. Still no outcome access.

**Validation:** Leakage detection classifier (balanced accuracy) verifies pipeline integrity. Any training example where a classifier can predict outcome from the commentary at above-chance rates indicates leakage.

**External validation gap:** No external academic citation validates self-blinding for financial training data specifically. The concept draws from clinical trial blinding methodology and adversarial debiasing frameworks (Beutel et al. 2019). This remains a practitioner innovation without peer-reviewed validation — but the logic is sound and the leakage detector provides empirical verification.

### 3.2 Training Data Format

**11-section XML-tagged telegraphic format, 350-500 tokens per example.**

```xml
<input>
  <!-- TIER 1: ALWAYS PRESENT (~200 tokens) -->
  <ctx ticker="AAPL" date="2026-03-15" hold="2-15d"/>
  <price close="172.50" chg1d="-2.1%" atr14="3.42" vol_ratio="1.4"/>
  <trend ema9="174.1" ema21="176.3" regime="UPTREND" pullback="38.2%_fib"/>
  <momentum rsi14="38" macd="-1.2" rel_str_spy="+4.2%_20d"/>
  <regime vix="18.5" vix_slope="+0.28/mo" vvix="95" spy_trend="UP"/>

  <!-- TIER 2: HIGH-PRIORITY (~120 tokens, 80-90% inclusion) -->
  <fundamentals pe_fwd="24.1" est_revisions="+3_30d" next_earn="42d"/>
  <macro hy_oas="385bp" fed_rate="5.25%" yield_2s10s="+45bp"/>
  <sentiment news_3d="-0.3" insider_net="-2.1M" analyst_consensus="BUY"/>

  <!-- TIER 3: ENHANCEMENT (~80 tokens, 40-60% inclusion) -->
  <options iv_rank="45" pc_oi="0.85" sweep_bias="BULLISH"/>
  <intermarket gold_copper="530" crude_chg="-1.2%" peer_avg_chg="-1.8%"/>
  <calendar fomc_days="3" opex_days="8" earn_density="22%"/>
</input>
```

<details>
<summary>Why XML tags instead of natural language?</summary>

Writing "The 14-period RSI is at 38, indicating oversold conditions" costs 15-20 tokens. Writing `rsi14="38"` costs 4-5 tokens. With a strict 350-500 token budget per training example, this compression means fitting 11 data dimensions instead of 4-5. The AI model (Qwen3) handles XML parsing well from its code pretraining. Its job becomes synthesis and decision-making rather than information extraction.
</details>

**Modified random subsetting** (adapted from Trading-R1): Keep all Tier 1 sections in every example. Randomly include 2-3 of 3 Tier 2 sections (p=0.85 each). Randomly include 0-2 of 3 Tier 3 sections (p=0.45 each). This produces **5-8 variations per date-ticker** — providing data augmentation, robustness to missing data, and regularization.

**When sections are excluded, include null markers** (`<options available="NO"/>`) to teach the model to reason about missing information rather than silently ignoring it.

### 3.3 Quality Rubric

Six-dimension scoring framework, blind to trade outcome:

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Thesis clarity | 25% | Clear, falsifiable directional thesis |
| Evidence grounding | 20% | Claims supported by specific data points |
| Risk identification | 20% | Identifies what could go wrong |
| Catalyst awareness | 15% | Upcoming events that could affect thesis |
| Quantitative precision | 10% | Specific numbers, not vague qualitative claims |
| Internal consistency | 10% | No contradictions within the analysis |

<details>
<summary>Why score blind to outcome?</summary>

If you score analyses based on whether the trade was profitable, you are rewarding luck, not skill. A brilliant analysis of a stock that happened to drop due to an unforeseeable event would score poorly. A sloppy analysis of a stock that happened to rise would score well. By scoring the quality of reasoning independently of the outcome, the training pipeline selects for genuine analytical skill — the only thing that compounds over time.
</details>

**Rubric evolution (post-200 trades):** Run regression of rubric dimensions against trade outcomes. Adjust weights based on which dimensions best predict performance. The rubric itself learns — a novel capability no institutional system implements.

### 3.4 Outcome-Conditioned Generation

Different prompts for different trade outcomes — 3-5× data yield per closed trade:

| Outcome | Prompt Focus | Value |
|---------|-------------|-------|
| Winner | Thesis validation — what confirmed the setup | Reinforces correct reasoning |
| Loser | Risk weighting — what should have been weighted more | Teaches risk identification |
| Timeout | Signal decay — why the setup expired | Teaches timing |
| PASS decision | Why NOT to trade — equally valuable | Prevents overtrading |
| Contrastive pair | High-quality vs low-quality analysis of same trade | DPO training signal |

### 3.5 Model Degradation Prevention

**Golden ratio: 62/38 curated/model-generated** training data. AlpaGasus (Chen et al. 2023) showed 9K high-quality examples outperform 52K unfiltered ones.

<details>
<summary>What is model collapse and why is the golden ratio important?</summary>

When a model is retrained on its own outputs, it gradually loses diversity and quality — like making a photocopy of a photocopy. Each generation is slightly worse. The "golden ratio" of 62% human-curated to 38% model-generated data prevents this. The curated data acts as an anchor, ensuring each retraining cycle has a foundation of genuine quality. Without this, after 3-4 retraining cycles, the model's outputs become bland, repetitive, and unreliable.
</details>

**Prevention protocol:**
1. Accumulate real data — never replace real examples with synthetic
2. Retrain from clean base each cycle (not iterative fine-tuning)
3. Champion-challenger evaluation — new model must beat current on holdout
4. Catastrophic forgetting detection via Fisher Information Matrix diagonal (Kirkpatrick et al. 2017)
5. Canary evaluations — fixed test set run after every retrain to detect drift

---

## 4. Model Architecture

### 4.1 Why Qwen3 8B

| Factor | Qwen3 8B | Alternatives | Verdict |
|--------|----------|-------------|---------|
| Tokenizer quality | Excellent for financial text + XML | Llama 3 slightly worse on numbers | Qwen wins |
| Context window | 32K native | Most 8B models: 8K-32K | Adequate |
| Multilingual tax | Minimal — shared representations | Some models waste capacity | Acceptable |
| Financial reasoning | Strong zero-shot; FinGPT benchmarks | Phi-3: competitive but less tested | Qwen preferred |
| GGUF support | Full (Q8_0 at 8.7GB) | All major models supported | Parity |
| Training ecosystem | PEFT + TRL + BitsAndBytes proven | Llama equally supported | Parity |

**Q8_0 quantization is safe for financial reasoning.** Inference at ~35 tok/s generation, ~1,200 tok/s prompt processing on RTX 3060. No measurable quality loss versus FP16 for the thesis generation task.

<details>
<summary>What is quantization?</summary>

Neural networks store their knowledge as billions of numbers (parameters). Normally these are stored with high precision (16 decimal places). Quantization reduces this to fewer decimal places (8 in Q8_0). This cuts the model's memory footprint roughly in half, letting it run on consumer GPUs. For most tasks, this precision loss is imperceptible — like the difference between a 24-megapixel and 20-megapixel photo. You cannot tell the difference in practice.
</details>

### 4.2 Training Stack

- **PEFT (Parameter-Efficient Fine-Tuning):** Only trains ~2% of model parameters via LoRA adapters
- **TRL 0.24:** Hugging Face training library for SFT and RLHF
- **BitsAndBytes:** 4-bit quantization for training (not Unsloth — OOM on 12GB for training)
- **QLoRA rank 32, alpha 64:** Validated sweet spot (alpha = 2× rank per Lightning AI experiments)
- **Unsloth:** Used for inference speedup (2×), not training

<details>
<summary>What is LoRA / QLoRA?</summary>

Instead of retraining all 8 billion parameters of the model (which would require enormous compute), LoRA (Low-Rank Adaptation) adds tiny "adapter" layers — about 2% of the model's size — and only trains those. The original model stays frozen. QLoRA goes further by also compressing the frozen model to save memory. The result: you can customize a powerful AI model on a consumer graphics card in hours instead of needing a data center for weeks.
</details>

### 4.3 Inference Performance

| Metric | Current | Expected (3090) |
|--------|---------|-----------------|
| Generation speed | ~35 tok/s | ~55-70 tok/s |
| Prompt processing | ~1,200 tok/s | ~2,000 tok/s |
| Time per LLM packet | ~47s (slower than expected) | ~25-30s |
| Concurrent training | **Not possible** (VRAM mutex) | Possible (24GB breaks mutex) |

**Known issue:** Conviction parsing broken — 99% of trades return None, all use default conviction=5 (#183). Root cause: LLM output format does not match parser regex. Fix path: structured output enforcement via GBNF grammar.

### 4.4 Hardware Path

| Phase | GPU | VRAM | Key Unlock |
|-------|-----|------|-----------|
| 1 (now) | RTX 3060 | 12GB | Single-task: inference OR training |
| 2 | RTX 3090 | 24GB | Concurrent inference + training; 14B models |
| 3+ | RTX 4090/5090 | 24GB | 2× speed; experimental iteration |
| Stretch | Dual GPU | 24+12GB | Dedicated inference + training; no VRAM handoff |

---

## 5. Risk & Portfolio Construction

### 5.1 Equal Weight Beats Optimization (For Now)

DeMiguel, Garlappi & Uppal (2009): 1/N outperforms mean-variance optimization with fewer than ~250 months of estimation data. At 13 trades, any optimization is curve-fitting noise.

<details>
<summary>Why not optimize the portfolio?</summary>

Portfolio optimization (like Markowitz mean-variance) needs reliable estimates of how every stock's returns relate to every other stock's returns. With only 13 trades, these estimates are wildly unreliable. Using them would be like predicting next year's weather based on two weeks of data. The "naive" approach of giving every position equal weight actually performs better until you have hundreds of data points to work with.
</details>

### 5.2 ATR-Based Stop Widening by VIX Regime

| VIX Regime | Stop Width | Target | Timeout | Rationale |
|------------|-----------|--------|---------|-----------|
| Normal (<20) | 2.0× ATR | 2.0× ATR | 8 days | Standard parameters |
| Elevated (20-30) | 2.5× ATR | 2.5× ATR | 7 days | Wider stops prevent noise-triggered exits |
| Crisis (>30) | 3.0× ATR | 3.0× ATR | 5 days | Maximum width but shorter timeout |

<details>
<summary>What is VIX?</summary>

The VIX (Volatility Index) measures how much the market expects stock prices to fluctuate over the next 30 days. Below 20 means calm markets; 20-30 means elevated anxiety; above 30 means crisis-level fear. When VIX is high, stocks swing wildly — so stops need to be wider to avoid getting knocked out by normal turbulence, like widening the lanes on a highway during a storm.
</details>

### 5.3 Position Sizing by Capital Tier

| Tier | Capital | Positions | Risk/Trade | Strategy Mix |
|------|---------|-----------|-----------|--------------|
| 1 | $1K-$10K | 2 | 1% | Pullback only (research instrument) |
| 2 | $10K-$50K | 3-5 | 1-1.5% | Pullback (live) + MR (paper) |
| 3 | $50K-$250K | 7-12 | 1-2% | Multi-strategy live + options paper |
| 4 | $250K-$1M | 12-18 | 1-1.5% | 3-4 desks including options |
| 5 | $1M-$5M+ | 15-25 | 0.5-1.5% | Full multi-desk + SPY overlay |

### 5.4 Stress Testing: What Historical Crashes Would Look Like

| Scenario | Duration | Max DD | Pullback Signal Freq | MR Signal Freq | Key Test |
|----------|----------|--------|---------------------|----------------|----------|
| 2020 COVID | 23 days, −34% | Severe | Near-zero | **High** | Simultaneous stop triggers |
| 2022 Rate Shock | 10 months, −27% | Moderate-severe | 0-1/month | Moderate | Flywheel pause tolerance |
| 2008 GFC | 6 months, −57% | Catastrophic | Zero | **Very high** | Dead-cat-bounce avoidance |

**Status:** Historical stress tests are designed but not yet executed. Gated as Phase 1 requirement.

---

## 6. Competitive Landscape

### 6.1 LLM Trading Systems (2024-2026)

The field has exploded since the existing corpus was written. Key systems as of April 2026:

| System | Architecture | Key Result | Relevance to Arcis |
|--------|-------------|------------|---------------------|
| **Trading-R1** | Qwen3-4B + 3-stage curriculum RL (SFT→RL) | Sharpe 2.72; 100K training samples, 14 equities | Closest blueprint — same base model family, same RL trajectory |
| **Alpha-R1** | 8B reasoning model via RL | Zero-shot generalization CSI 300→CSI 1000 | Demonstrates regime-aware factor screening works |
| **FLAG-Trader** (Xiong et al. 2025) | Unified LLM + gradient RL, partial fine-tuning | Improves both trading AND financial NLP tasks | Validates LLM-as-policy-network approach |
| **FinRL-DeepSeek** (Benhenda 2025) | CPPO + LLM risk/sentiment signals, DeepSeek V3/Qwen 2.5 | Risk-sensitive trading on Nasdaq-100 | Shows LLM signals improve risk management in RL |
| **DAPO-Trading** (Zha et al. 2025) | Improved GRPO for trading with LLM signals | 230.49% cumulative return; 2.5hr vs 8hr training | Directly applicable — GRPO variant for financial RL |
| **AlphaQuanter** (Deng et al. 2025) | Single-agent RL with tool-orchestrated reasoning | State-of-the-art financial metrics | Interpretable reasoning reveals strategies |
| **FinCon** (Yu et al. 2024) | Multi-agent LLM with conceptual verbal RL | 69 citations; manager-analyst hierarchy | Validates multi-agent council approach |
| **QuantAgent** (Wang et al. 2024) | Two-loop self-improving agent for signal mining | 23 citations; automatic knowledge base enhancement | Validates self-improving flywheel concept |

<details>
<summary>What does "Sharpe ratio" mean?</summary>

The Sharpe ratio measures return per unit of risk. A Sharpe of 1.0 means you earned 1% extra return for every 1% of volatility you endured. Above 1.0 is good, above 2.0 is excellent, and above 3.0 is exceptional (and often too good to be true outside of backtests). For context, the S&P 500's long-term Sharpe ratio is about 0.4-0.5. Trading-R1's reported Sharpe of 2.72 is strong but should be viewed cautiously until validated in live trading.
</details>

**Key takeaway:** The LLM-for-trading field has validated every major Arcis architectural choice — LLM-as-analyst (not just feature extractor), RL-based optimization, multi-agent deliberation, and self-improving training loops. Arcis's differentiator is **self-blinding + process-quality scoring** — no other system filters training data by reasoning quality independent of outcome.

### 6.2 What Renaissance/Two Sigma Cannot Do That We Can

| Arcis Advantage | Why Structural | Evidence |
|----------------|----------------|----------|
| Decision speed 10-100× | 1-7 days to add data source vs 2-6 months institutional | Organizational inertia literature |
| Operating cost 500:1 | $768/yr vs $400-650K analyst team | Direct calculation |
| Transparency as weapon | LLM theses are human-readable artifacts | 78% of pension CIOs rate transparency "essential" |
| No capacity constraints | Strategies viable only at small scale | Berk & Green 2004: returns decrease 0.7-1.0% per 10× AUM |
| LLM-native architecture | Legacy systems designed for tabular data, not text | Cannot retrofit self-blinding onto existing pipelines |

### 6.3 What They Do Better

| Institutional Edge | Impact at Arcis Scale | Neutralizable? |
|-------------------|-----------------------|----------------|
| Execution infrastructure | LOW — S&P 100 liquidity | Already neutralized |
| Data scale ($10M+/yr) | MODERATE but declining | Partially — LLM extracts more from free data |
| 300 PhDs | REAL but asymmetric | 1 operator + LLM ≈ 5-10 analysts on narrow domain |
| Diversification | REAL but accepted | Multiple desk architecture (12-24 months) |

---

## 7. Business & Fund Formation

### 7.1 Revenue Sequencing

| Month | Revenue Stream | Milestone |
|-------|---------------|-----------|
| 0 (now) | Personal trading + capital injections ($1K/mo) | Start |
| 3 | Collective2 account (~$99/mo) | Track record clock starts |
| 6 | Phase 1 gate → go live ($5-10K) | Verifiable live returns |
| 12 | Signal marketplace ($200-$1K/mo) + RIA outreach | First external revenue |
| 18 | Wyoming LLC + Section 475(f) | Legal entity |
| 24 | Fund formation at $1-2M AUM | Management + performance fees |
| 36 | Fund self-sustaining at $2M+ AUM (1.5%+17.5%) | Day job optional |

<details>
<summary>What is Section 475(f)?</summary>

Section 475(f) is a US tax election that lets active traders treat their gains and losses as ordinary income rather than capital gains. The main benefit: you can deduct trading losses against all other income without the $3,000 annual cap that normally applies to capital losses. For an active trading system generating hundreds of trades per year, this can save thousands in taxes. The election must be filed before the tax year begins.
</details>

### 7.2 Fund Economics

| Fee Structure | Breakeven AUM (covers $80K living + $30K fund costs) |
|--------------|------------------------------------------------------|
| 1.5% management only | $7.3M |
| 1.5% + 17.5% performance (at 20% return) | **$2.0M** |
| 2% + 20% (aggressive) | $1.6M |

<details>
<summary>What is AUM and why does it matter?</summary>

AUM (Assets Under Management) is the total amount of money a fund manages. A fund that manages $2M and charges 1.5% management fee earns $30K/year just from that fee. If the fund also earns 20% returns and charges 17.5% of profits, that is another $70K. Combined, $100K in revenue from $2M AUM — enough to be self-sustaining. The challenge is getting to $2M, which typically requires a 2-3 year auditable track record.
</details>

### 7.3 Alpha Leakage from Signal Publication

**Alpha leakage is effectively zero for S&P 100 swing trades at any realistic subscriber count.**

Average daily dollar volume for S&P 100: $1-5 billion per stock. Required simultaneous followers to move price: 2,000-20,000 at $5K positions. Collective2/Darwinex scale (50-500 followers): negligible impact.

**Signal marketplace is primarily a track-record tool** until subscriber counts exceed 100. The value of a 24-month independently verified track record is potentially worth $500K+ in accelerated fund formation.

### 7.4 Regulatory Landscape (Updated April 2026)

**SEC AI-Washing Enforcement:** Since March 2024, the SEC has brought multiple enforcement actions against advisers for false or misleading AI claims under Section 206 anti-fraud provisions. The SEC's 2025 examination priorities expanded AI oversight, including reviewing registrant AI capabilities for accuracy.

**FINRA 2026 Oversight Report:** New section on GenAI covering recordkeeping, customer information protection, risk management, and Reg BI compliance. Firms must ensure AI governance covers model risks, customer communications, and vendor diligence.

<details>
<summary>What is "AI-washing"?</summary>

AI-washing is when a company exaggerates its use of artificial intelligence — claiming sophisticated AI capabilities that do not actually exist. The SEC has started cracking down on investment firms that market themselves as "AI-powered" when they actually use simple rules or spreadsheets. For Arcis, the key is to use accurate language: "AI-informed" and "systematic" rather than overclaiming. Since Arcis genuinely uses a fine-tuned LLM at every decision point, the description is accurate — but regulatory language must be precise.
</details>

**Compliance language for Arcis:** Use "AI-informed," "systematic," "research-driven." Avoid "AI-powered" without substantiation. Document every AI-generated thesis as an auditable artifact.

**Entity path:** Arcis → Arcis Capital Management, LLC → Arcis Labs

---

## 8. Flywheel & Moat

### 8.1 The Compounding Loop

```
Trades → Outcomes → Training Data → Better Model → Better Trades
   ↑                                                        |
   +---------------------- MORE CAPITAL ←-------------------+
```

<details>
<summary>What is the "flywheel" in this context?</summary>

Amazon's flywheel: more customers → lower prices → more customers. Arcis's flywheel: more trades generate more training data, which trains a better AI model, which makes better trades, which generates more training data. Each rotation makes the system slightly better. The key insight is that this loop compounds — after 500 trades the model has seen far more market patterns than any human could study in a lifetime, and each new trade adds to that knowledge.
</details>

### 8.2 Training Data Quality IS the Moat

The moat is not the model (Qwen3 8B is open-source), not the code (visible on GitHub), and not the returns (replicable in hindsight). The moat is the **accumulated corpus of self-blinded, quality-scored, outcome-conditioned training data** that has been filtered for reasoning quality rather than outcome luck.

This corpus:
- Cannot be replicated without executing the same trades over the same timeframes
- Compounds with every trade (3-5 examples per closed position)
- Is validated by the leakage detector (no outcome contamination)
- Is scored by a rubric that itself improves over time

### 8.3 Flywheel Friction Points

| Link | Friction Level | Top Fix | Impact |
|------|---------------|---------|--------|
| Trades → Outcomes | MEDIUM | Add 8 metadata columns (regime, VIX, MFE/MAE) | +40% signal capture |
| Outcomes → Training Data | **HIGH** | Outcome-conditioned prompts, 3-5 examples/trade | **+250% data yield** |
| Training Data → Better Model | MEDIUM | Marginal improvement tracking per cycle | Prevents wasted cycles |
| Better Model → Better Trades | **HIGH** | Alpha attribution experiment (existential) | Validates entire thesis |
| Meta-Flywheel (evaluation) | **HIGH** | Outcome-validated rubric weights post-200 trades | Self-improving evaluation |

### 8.4 Data Degradation Timeline

ML model performance typically decays with a **half-life of 6-12 months** without retraining (Lim & Zohren 2021). The flywheel must not pause for more than 4-6 weeks. Mean reversion strategy provides signal continuity during bear markets when pullback signals go silent.

### 8.5 GPU Utilization: From 4.4% to Target 40-70%

| Time Block | Current | Target | Activities |
|------------|---------|--------|-----------|
| Market hours | 4.4% | 30-40% | Inference + alpha backtest warmup |
| Post-close | ~5% | 40-60% | Stress testing + outcome-conditioned data gen |
| Overnight | ~10% | 50-70% | Continuous eval + parameter backtesting |
| Weekend | Training only | 70-80% | Full retrain + exhaustive backtest |

<details>
<summary>Why does GPU utilization matter?</summary>

The RTX 3060 is a $300+ investment that runs 24/7, consuming electricity constantly. At 4.4% utilization, it sits idle 95% of the time — like owning a factory that only runs one shift per week. By scheduling backtesting, stress testing, and training data generation into idle periods, the same hardware produces dramatically more value without any additional cost. The GPU is the only capital asset that improves the system when utilized.
</details>

---

## 9. Open Questions & Research Agenda

### 9.1 Existential Question: Does the LLM Add Alpha?

**Status:** Experiment designed, not yet running.

The entire AI thesis is unvalidated. All 13 winning trades were ranker-qualified first. The LLM adds narrative and conviction scoring, but we do not know if it filters bad trades, improves sizing, or simply adds expensive commentary.

**Experiment:** Parallel ranker-only shadow portfolio (second Alpaca paper account). McNemar's test on discordant pairs. **200+ paired trades needed for 80% power to detect 10% win rate difference** (6-8 months at current pace).

<details>
<summary>What is alpha attribution?</summary>

Alpha attribution answers the question: "Which part of the system is actually making money?" If you remove the AI and just use the simple scoring rules, does performance change? If not, the AI is adding cost without adding value. This is the single most important experiment for Arcis — it determines whether the system is a novel AI trading platform or an overengineered stock screener.
</details>

**If LLM adds alpha:** GRPO/RL becomes #1 priority. Training data investment scales to 2,000-5,000 examples. Hardware upgrade accelerates.

**If LLM does NOT add alpha:** Pure systematic scanner is viable for personal capital but commoditized (300,000+ QuantConnect users). LLM retains value for commentary/marketing, training data factory, and research assistant. Signal marketplace viability drops to $5K-$50K ARR.

### 9.2 Remaining Open Questions

| Question | Current Evidence | Required Data | Timeline |
|----------|-----------------|---------------|----------|
| Optimal holding period (8 days vs alternatives) | Connors/Alvarez suggest 3-5 days optimal | MFE/MAE analysis on 50+ trades | Phase 1 gate |
| GRPO vs second SFT at 100+ trades | Trading-R1 shows GRPO dramatically improves Qwen | 100+ closed trades for reward signal | 6-12 months |
| When to expand universe beyond S&P 100 | McLean & Pontiff: anomalies stronger in small caps | Positive alpha attribution + $30K AUM | Phase 2 |
| LLM conviction ↔ position sizing | Cohen, Polk & Silli: highest-conviction outperforms 1-4%/yr | Fix conviction parsing (#183) + 200+ trades | 6-12 months |
| Options desk research priorities | Minimum $15-25K for verticals | Paper-trade data at Tier 2 capital | Phase 2 |
| Does ensemble inference (3-5 prompts) add value? | General ML: ensembles improve 5-15% | Compute budget available (95% GPU idle) | Phase 2 |

### 9.3 GRPO Roadmap

GRPO (Group Relative Policy Optimization) is now the dominant RL optimizer for open LLMs, popularized by DeepSeek-R1. Directly applicable to financial LLMs:

- **DAPO-Trading** (Zha et al. 2025) achieved 230.49% cumulative return with improved GRPO, reducing training time from 8hr to 2.5hr
- **Feasible on consumer hardware** via Unsloth optimizations — but likely requires RunPod A100 ($14/session) for initial training
- **Reward design challenge:** Trading rewards are delayed (outcome known only after trade closes) and noisy. Verifiable rewards (the standard for math/code GRPO) do not directly apply
- **Arcis timeline:** Gated at 100+ closed trades to ensure sufficient reward signal

<details>
<summary>What is GRPO?</summary>

Traditional reinforcement learning compares the model's output against a separate "reward model" to determine what is good. GRPO simplifies this: generate multiple outputs for the same input, compare them against each other within the group, and reinforce the better ones. This eliminates the need for a separate reward model, reducing memory requirements enough to run on consumer GPUs. For trading, this means generating multiple trade analyses for the same market situation, scoring them, and training the model to produce more analyses like the best ones.
</details>

---

## 10. Citation Index

### Trading Strategy

| Citation | Key Finding | Effect Size | Arcis Decision |
|----------|-------------|-------------|----------------|
| Shefrin & Statman 1985, *J. Finance* | Disposition effect framework | Theoretical | Pullback strategy exploits this |
| Frazzini 2006, *J. Finance* | Disposition creates momentum underreaction | 2-4% annual alpha | Core pullback thesis |
| Connors & Alvarez (multiple) | Pullback alpha concentrates days 1-5 | 82-83% WR, 3-5 day hold | Timeout calibration |
| Kaminski & Lo 2014, *J. Financial Markets* | Stops help trending, hurt mean-reverting | Strategy-dependent | Wide catastrophic stops only |
| Nagel 2012, *Rev. Financial Studies* | Reversal returns amplify with VIX | Conditional Sharpe multiples | VIX-adaptive parameters |
| Daniel & Moskowitz 2016, *JFE* | Post-crash rebounds create amplified MR alpha | Extreme positive returns | Mean reversion as complement |
| Martineau 2022, *Critical Finance Review* | PEAD dead for large caps since 2006 | Zero effect | PEAD strategy deprioritized |
| Subrahmanyam 2025, working paper | Removing microcaps drops PEAD t-stat 2.18→1.43 | Below significance | Confirms PEAD death for S&P 100 |
| DeMiguel et al. 2009 | 1/N beats optimization with limited data | Outperforms mean-variance | Equal weight through Phase 2 |
| Giner et al. 2023, *Economic Modelling* | Semi-Markov model explains MR + momentum | Regime-dependent | Theoretical grounding for RSI strategy |
| Kitkanasiri et al. 2025, *ABAC Journal* | RSI does not outperform buy-and-hold in efficient markets | Not significant (most markets) | Tempers MR expectations for S&P 100 |

### Data & Signals

| Citation | Key Finding | Effect Size | Arcis Decision |
|----------|-------------|-------------|----------------|
| McLean & Pontiff 2016, *J. Finance* | Published anomalies lose 58% of returns | 26% data mining + 32% arbitrage | Signal selection |
| Gordon, Schneider & Strauss 2025 | Only 3/13 anomaly themes survive post-2005 | Low-risk, momentum, quality | Universe of viable signals |
| Chan, Jegadeesh & Lakonishok 1996, *J. Finance* | Earnings revision momentum | ~22%/yr gross in large-cap samples | Build earnings revision tracker |
| Novy-Marx 2015 | Revision momentum significant in largest quintile | Persistent | Priority enrichment |
| Cookson et al. 2024, *JFE* | Social media sentiment reverses, deteriorated post-2021 | No mega-cap effect | Skip Reddit/StockTwits |
| Da, Engelberg & Gao 2011, *J. Finance* | Google Trends: "most pronounced among small stocks" | Near-zero for S&P 100 | Skip Google Trends |
| Pan & Poteshman 2006, *RFS* | Options volume predicts returns | ~40 bps next-day; attenuated mega-caps | Options flow as confirmation |
| Gilchrist & Zakrajšek 2012, *AER* | Excess bond premium predicts economic activity | 100 bps → >1.25pp GDP deceleration | Credit spreads in macro section |
| Tetlock 2007/2011, *J. Finance* / *RFS* | News sentiment predictive; absorbed in 1-5 days for large caps | 1-5 day half-life | 60-min scan appropriate |

### LLM & Training

| Citation | Key Finding | Effect Size | Arcis Decision |
|----------|-------------|-------------|----------------|
| Zhou et al. 2023 (LIMA) | Superficial alignment: small high-quality data outperforms large noisy data | 1K examples sufficient | Quality over quantity |
| Chen et al. 2023 (AlpaGasus) | 9K filtered > 52K unfiltered | ~5.6× more efficient | Golden ratio validation |
| Kirkpatrick et al. 2017, *PNAS* | Elastic Weight Consolidation prevents catastrophic forgetting | Continual learning | Degradation prevention |
| Schaul et al. 2016, *ICLR* | Prioritized Experience Replay: 2× faster learning | Uniform → prioritized | Regime memory replay |
| Kahneman, Sibony & Sunstein 2021 | Human judgment noise: 55% variance in same-case decisions | 20-40% error from noise alone | LLM consistency advantage |
| Bansal et al. 2021, *CHI* | Human oversight often degrades AI performance | Conditional on expertise | Operator as architect, not trader |
| Xiong et al. 2025 (FLAG-Trader) | Unified LLM + gradient RL improves both trading and NLP | 11 citations | Validates LLM-as-policy-network |
| Benhenda 2025 (FinRL-DeepSeek) | CPPO + LLM risk/sentiment on Nasdaq-100 | Uses Qwen 2.5, DeepSeek V3 | Risk-sensitive RL feasible |
| Zha et al. 2025 (DAPO-Trading) | Improved GRPO: 230.49% return, 2.5hr training | 3.2× faster than baseline | GRPO for financial RL validated |
| Yu et al. 2024 (FinCon) | Multi-agent verbal RL with manager-analyst hierarchy | 69 citations | Council architecture validated |
| Wang et al. 2024 (QuantAgent) | Two-loop self-improving trading agent | 23 citations | Flywheel concept validated |
| Jadhav et al. 2025, *Frontiers in AI* | Survey of 84 LLM-equity studies (2022-2025) | Comprehensive review | Field landscape reference |

### Risk & Portfolio

| Citation | Key Finding | Effect Size | Arcis Decision |
|----------|-------------|-------------|----------------|
| Kelly 1956, *Bell System Tech J.* | Optimal position sizing formula | f* = p/a - q/b | Foundation for risk per trade |
| Thorp 2006 | Half-Kelly practical recommendation; full Kelly → ~50% DD | 1-in-20 periods | Never exceed 2% risk |
| Kacperczyk et al. 2005 | Concentrated funds outperform | +1.5%/yr | Concentration justified with controls |
| Cohen, Polk & Silli 2010 | Highest-conviction positions outperform 1-4%/yr | Diversifying positions destroy value | Conviction-weighted sizing (post fix) |
| Berk & Green 2004, *JPE* | Returns decrease 0.7-1.0% per 10× AUM | Capacity constraint | Small-scale advantage |
| Lim & Zohren 2021 | ML model performance half-life 6-12 months | Requires continuous retraining | Flywheel cannot pause > 4-6 weeks |

### Business & Regulatory

| Citation | Key Finding | Effect Size | Arcis Decision |
|----------|-------------|-------------|----------------|
| Belmont et al. 2022, *J. Public Economics* | No congressional stock-picking alpha post-STOCK Act | Underperform by 26 bps/6mo | Skip congressional data |
| Preqin/Eurekahedge | Emerging manager survival: 40-50% at year 5 | Primary failure: AUM, not returns | $768/yr cost is survival advantage |
| SEC 2024-2026 enforcement | AI-washing actions under Section 206 | Multiple settlements | Use precise AI language |
| FINRA 2026 Oversight Report | New GenAI section; governance requirements | Recordkeeping, model risk | Document all AI-generated artifacts |

---

## Research Metadata

- **Corpus size:** 60+ research documents (17 core + 4 deep research + 40+ supporting)
- **Research queries executed:** 5 (Consensus academic search × 3, WebSearch × 2)
- **New papers discovered:** 15+ (2024-2026 publications)
- **Key contradictions resolved:**
  - RSI mean reversion for efficient markets: weaker than corpus suggests for S&P 100 — reframed as regime complement
  - GRPO feasibility: confirmed by multiple 2025 papers (DAPO-Trading, FinRL-DeepSeek)
  - Competitive landscape: 8+ new LLM trading systems since corpus was written — all validate Arcis architecture
- **Gaps remaining:**
  - Alpha attribution experiment (designed, not running)
  - Self-blinding external validation (no peer-reviewed citation)
  - Historical stress test results (designed, not executed)
  - Conviction parsing fix (#183)
- **Document generation:** April 3, 2026
- **Next review trigger:** After Phase 1 gate (50 closed trades) or 90 days, whichever comes first

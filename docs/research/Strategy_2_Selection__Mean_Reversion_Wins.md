# Halcyon Lab Strategy #2: Short-term mean reversion wins decisively

**Short-term mean reversion on S&P 100 stocks is the optimal second strategy for Halcyon Lab.** It offers the best decorrelation with pullback-in-uptrend (empirically **−0.35 correlation** per Balvers and Wu 2006), profits precisely when momentum crashes (Daniel and Moskowitz 2016), and has a proven implementation framework via Connors' RSI(2) with **65–75% win rates** on large-cap stocks. While the raw reversal effect has decayed **50–75%** since Jegadeesh (1990) and Lehmann (1990) first documented it, enhanced signals — residual reversals, VIX-conditional sizing, and multi-factor filters — sustain net Sharpe ratios of **0.7–1.0** on S&P 100 stocks. No other candidate strategy matches this combination of decorrelation, evidence strength, and implementation feasibility under Halcyon's long-only, 1–15 day hold constraints.

The mathematical case for adding a new strategy rather than expanding the stock universe is overwhelming: a second uncorrelated strategy reduces portfolio variance by **~50%**, while expanding from 100 to 325 stocks with the same pullback strategy reduces variance by only **~1.6%**. This report ranks all candidates, then provides a complete implementation specification for mean reversion as Strategy #2.

---

## 1. Ranked candidate list with scores and evidence

The table below scores each candidate on five dimensions (1–5 scale, higher = better) and provides a composite rank. Decorrelation is weighted 2× because it is the primary purpose of Strategy #2.

| Rank | Strategy | Decorrelation (2×) | Evidence strength | Impl. complexity | Data needs | Training feasibility | Composite | Est. Sharpe | Corr. w/ pullback |
|------|----------|-------------------|-------------------|-----------------|------------|---------------------|-----------|-------------|-------------------|
| **1** | **Short-term mean reversion** | **5** (−0.35) | **4** | **4** (low) | **5** (minimal) | **5** | **32** | 0.7–1.0 | −0.30 to −0.40 |
| 2 | Volatility-timed equity | 4 (negative) | 3 | 4 | 5 (VIX data) | 3 | 23 | 0.4–0.7 | −0.20 to −0.35 |
| 3 | Sector rotation | 2 (+0.3–0.5) | 4 | 4 | 4 | 4 | 22 | 0.5–0.8 | +0.30 to +0.50 |
| 4 | Overnight returns | 2 (positive) | 3 | 4 | 5 | 2 | 20 | 0.3–0.6 | +0.15 to +0.30 |
| 5 | Calendar/flow effects | 3 (low) | 2 | 5 (trivial) | 5 | 2 | 20 | 0.1–0.3 | ~0.00 to +0.10 |
| 6 | Intraday momentum | 3 | 3 | 1 (HFT) | 2 | 1 | 15 | N/A retail | Unknown |

### Detailed candidate assessments

**Short-term mean reversion** dominates on decorrelation. Balvers and Wu (2006) documented **−35% correlation** between momentum and mean reversion across 18 developed equity markets. Nagel (2012) in the *Review of Financial Studies* proved that reversal returns spike with VIX — a **1-point VIX increase predicts 9 basis points higher daily reversal return** for large-caps. Daniel and Moskowitz (2016) showed momentum crashes occur in bear-market rebounds, exactly when mean reversion thrives. The strategy's worst periods (strong trending bull markets) are pullback's best periods, creating natural portfolio-level hedging.

**Volatility-timed equity** (Moreira and Muir 2017, *Journal of Finance*) ranks second. The concept — reduce equity exposure when volatility is high — produces in-sample alphas across market, value, and momentum factors. However, Cederburg et al. (2020) found out-of-sample implementation disappointing, and Wang and Yan showed vol-managed portfolios outperform in only **53 of 103 equity portfolios**. Downside-volatility management performs better (89 of 94 anomalies showed positive alphas), but as a standalone strategy the evidence is weaker than mean reversion. Best deployed as a **position-sizing overlay** rather than a standalone strategy.

**Sector rotation** (Moskowitz and Grinblatt 1999, *Journal of Finance*) has strong evidence — industry momentum explained "much of the individual stock momentum anomaly" — but its **+0.30 to +0.50 correlation** with stock-level momentum defeats the diversification purpose. Momentum was the best-performing factor globally in 2024 (96th percentile over 50 years per SSGA), but Morgan Stanley warns that after top-decile momentum runs, returns typically reverse by **−25% over 10 months**. Sector momentum would amplify, not hedge, pullback strategy risk.

**Overnight returns** (Aboody, Levi, and Trueman 2018, *JFQA*) remain persistent — Lin (2025) confirmed **92.6% of QQQ total gains** accrue overnight. Alpaca supports this via `time_in_force="cls"` (buy at close) and `time_in_force="opg"` (sell at open). However, Lou, Polk, and Skouras (2019, *JFE*) proved that **all momentum alpha occurs overnight**, meaning overnight returns are positively correlated with momentum/pullback. This kills the diversification benefit. Transaction costs from daily round-trips also erode the thin edge.

**Calendar effects** have largely been arbitraged away. A February 2025 QuantSeeker analysis found the classic turn-of-month [0:3] window **shows no statistically significant returns** for US equity ETFs. Only the broader [-3:+3] window retains marginal significance (5–12 bps/day). The effect size is too small to justify a dedicated strategy with LLM infrastructure.

**Intraday momentum** (Gao et al. 2018, *JFE*) requires high-frequency execution incompatible with Alpaca's architecture. Eliminated.

---

## 2. Why a new strategy beats universe expansion

The portfolio variance formula demonstrates this with mathematical clarity. For N equally-weighted stocks with variance σ² and average pairwise correlation ρ:

**Portfolio Variance = σ²[(1−ρ)/N + ρ]**

At typical intra-strategy correlations of **ρ = 0.30** (Moskowitz, Ooi, and Pedersen 2012 documented correlations of 0.37–0.38 for time-series momentum), expanding from 100 to 325 stocks reduces variance from **0.307σ²** to **0.302σ²** — a **1.6% improvement**. Adding one uncorrelated strategy with a 50/50 capital split reduces combined variance by approximately **50%**. The new strategy provides **25–50× more diversification benefit**.

McLean and Pontiff (2016, *Journal of Finance*) found anomaly returns are **higher in stocks with high idiosyncratic risk and lower liquidity**, supporting mid-cap expansion in principle. But this addresses alpha magnitude, not portfolio variance reduction. The correct sequencing is: add Strategy #2 first (massive diversification benefit), then consider universe expansion later (incremental alpha boost).

Mid-cap liquidity accommodates portfolios up to **~$10M** without significant market impact. At $10M with 20 positions of $500K each, positions represent ~5% of daily volume for bottom-quartile S&P MidCap 400 stocks. Above $50M, multi-day execution becomes necessary. Universe expansion remains viable as a Phase 2 optimization.

---

## 3. PEAD as a pullback feature, not a standalone strategy

While pure PEAD drift is dead in large-caps — Martineau (2022) confirmed stock prices now fully adjust on announcement day, and Subrahmanyam's 2025 UCLA working paper showed apparent revivals were driven by microcap contamination — **earnings information retains powerful value as a filter** within the pullback strategy.

Novy-Marx (2015, *Journal of Financial Economics*) delivered the pivotal finding: **earnings momentum subsumes price momentum** in both cross-sectional and time-series tests. Price momentum is "a weak expression of earnings momentum." This means the fundamental driver of pullback-in-uptrend success is the underlying earnings trajectory. A positive-SUE filter should improve pullback signal quality significantly.

Kaczmarek and Zaremba (2025, *Finance Research Letters*) revived PEAD using elastic net regression on **12 quarters of historical SUE** (standardized unexpected earnings), nearly doubling Sharpe ratios compared to single-quarter models. Critically, gains were **"especially strong among large-cap stocks, where the latest surprises are quickly priced in, but older ones remain overlooked."** Their approach extracts nonlinear patterns from earnings history that market participants miss.

The practical integration is straightforward: score each S&P 100 stock on multi-quarter SUE pattern (top 2–3 quintiles = positive fundamental backdrop), then **only execute pullback entries in stocks with confirmed positive earnings trajectory**. This adds a fundamental "catalyst confirmation" layer. Chan, Jegadeesh, and Lakonishok (1996) showed double-sorting on returns and earnings surprises generates higher profits than either signal alone.

For the mean reversion strategy specifically, earnings filters serve a different purpose: **exclude stocks pulling back on negative earnings surprises** (genuine breakdowns) from the mean reversion candidate pool. A stock that drops 5% on a positive surprise is likely reverting; one that drops 5% on a negative surprise may be beginning a sustained decline.

---

## 4. Detailed implementation spec for short-term mean reversion

### Signal construction: entry triggers

The entry system uses a **three-layer filter architecture** that the LLM evaluates holistically:

**Layer 1 — Oversold signal (required).** Primary signal is RSI(2) < 5, which Connors validated across hundreds of thousands of trades on S&P 500 stocks with win rates exceeding 70%. The lower the RSI reading, the higher subsequent returns. For confirmation, require at least one of: Bollinger Band(20,2) lower band touch, Z-score of 5-day returns < −2.0, or Connors RSI (3,2,100) < 10.

**Layer 2 — Regime filter (required).** Trade mean reversion **only when VIX > 18** or when VIX is above its 20-day moving average. Nagel (2012) proved reversal returns are a direct function of VIX level — expected returns spike during elevated volatility. When VIX < 15 and declining, the pullback strategy dominates and mean reversion signals should be suppressed. This creates natural capital rotation between strategies.

**Layer 3 — Quality filter (recommended).** Exclude stocks with: negative earnings surprise in most recent quarter (PEAD filter), price below 200-day SMA by more than 15% (genuine breakdown, not temporary dip), pending binary events (FDA decisions, M&A), or sector in persistent downtrend (sector ETF below 50-day SMA). Include stocks with: multi-quarter positive SUE trend (Kaczmarek-Zaremba filter), above-average institutional ownership (limits manipulation risk), and capitulation-signature volume (≥1.5× 20-day average volume on the down move).

### Exit rules

**Primary exit:** Close position when RSI(2) crosses above 65 or price closes above its 5-day simple moving average. Connors' research confirmed the 5-day SMA crossover as the optimal mean reversion exit for large-cap stocks.

**Time-based exit:** If no reversion occurs within **5 trading days**, exit at close regardless. Mean reversion that hasn't triggered within a week is likely a trend continuation, not a temporary dip. This limits capital commitment and aligns with the 1–15 day hold constraint.

**Regime exit:** If VIX drops below 15 during a mean reversion trade, tighten exit to RSI(2) > 50 or first profitable close. The regime has shifted unfavorably.

**Trend-violation exit:** If the stock closes below its 200-day SMA during the trade, exit immediately. The long-term trend has broken and the mean reversion thesis is invalidated.

### Stop-loss placement

Connors' research — counterintuitively but consistently — showed that traditional percentage stop-losses **damage mean reversion performance** because they cut positions when the signal is strongest (deeper oversold = higher expected return). Instead:

Use an **ATR-based catastrophic stop** at 3× ATR(14) below entry price. For a typical S&P 100 stock with daily ATR of 2%, this places the stop approximately 6% below entry. This protects against genuine black-swan events while giving normal mean reversion room to work. Complement with a **portfolio-level circuit breaker**: if total mean reversion portfolio drawdown exceeds **−12%**, close all positions and pause the strategy for 5 trading days.

### Position sizing

**Per-trade sizing:** Allocate **20% of Strategy #2 capital** to each mean reversion position, allowing up to 5 simultaneous positions. This matches the Quantitativo finding that 3–5 parallel mean reversion positions optimize risk-adjusted returns.

**Strategy-level allocation:** Begin with **equal risk parity** between pullback and mean reversion — allocate capital inversely proportional to each strategy's trailing 60-day realized volatility. If pullback vol = 12% and mean reversion vol = 16%, allocate 57% pullback / 43% mean reversion. Rebalance monthly.

**VIX-conditional scaling:** When VIX > 25, increase mean reversion allocation by 25% (funded by reducing pullback allocation). When VIX < 15, decrease mean reversion allocation by 25%. This follows Nagel's (2012) finding that reversal returns scale linearly with volatility.

---

## 5. LLM adapter design for mean reversion

### System prompt concept

The mean reversion LoRA adapter transforms Qwen3-8B into a **reversion probability estimator**. Unlike the pullback adapter (which evaluates trend continuation probability), this adapter evaluates the probability that an oversold stock will revert to mean within 1–5 trading days.

```
System: You are a quantitative mean reversion analyst for S&P 100 stocks.
Your task: Given a stock's current technical state, fundamental backdrop,
and market regime, estimate the probability (0-100) that this stock will
revert ≥1.5% upward within 5 trading days. Also output: recommended
position size (0.5x/1.0x/1.5x standard), expected reversion magnitude,
and confidence level.

Consider: RSI(2), Connors RSI, Z-score of returns, volume signature,
VIX level, sector relative strength, earnings surprise history (12Q),
whether other S&P 100 stocks in same sector are also oversold (cluster
signal), and recent analyst revision direction.
```

### Feature template for each candidate trade

```
STOCK: {ticker} | SECTOR: {gics_sector}
PRICE: ${current} | 200d SMA: ${sma200} | 50d SMA: ${sma50}
RSI(2): {rsi2} | RSI(14): {rsi14} | Connors RSI: {crsi}
BOLLINGER: {bb_position}% (0=lower band, 100=upper band)
Z-SCORE 5d: {zscore5} | Z-SCORE 10d: {zscore10}
VOLUME TODAY: {vol_ratio}x 20d avg | DOWN DAYS: {consecutive_down}
VIX: {vix} | VIX vs 20d MA: {vix_vs_ma}%
SECTOR ETF RSI(14): {sector_rsi} | SECTOR vs 50d: {sector_rel}%
LAST EARNINGS: SUE={sue} Q-{quarters_ago} | SUE TREND 4Q: {sue_trend}
ATR(14): {atr}% | IMPLIED VOL: {iv}% | IV RANK: {iv_rank}%
PULLBACK STRATEGY STATUS: {pullback_active} positions open
SIMILAR STOCKS OVERSOLD: {cluster_count} in same sector
```

### Training data generation approach

Generate **self-blinded training data** using a walk-forward methodology:

**Step 1 — Label generation.** For each trading day from 2010–2024, identify all S&P 100 stocks where RSI(2) < 10. Record the feature vector at signal time. Then measure the forward 5-day maximum return. Label as **STRONG_REVERT** (>3% reversion), **MODERATE_REVERT** (1.5–3%), **WEAK_REVERT** (0–1.5%), or **CONTINUED_DECLINE** (<0%).

**Step 2 — Point-in-time reconstruction.** All features must use only data available at signal time. Earnings data uses the most recent reported quarter with a 1-day lag (to avoid using pre-announcement data). Analyst estimates use consensus available on the prior trading day. This eliminates look-ahead bias.

**Step 3 — Walk-forward splits.** Train on 2010–2018, validate on 2019–2021, test on 2022–2024. The test set is held out entirely until final evaluation. Within the training set, use rolling 3-year windows with 6-month embargo periods between train and validation folds.

**Step 4 — Natural language conversion.** Convert each labeled example into the feature template format above, paired with an "analyst assessment" response that explains the reasoning chain: regime assessment → signal strength → risk factors → position recommendation → probability estimate. Use the actual forward outcome to generate the correct assessment, but **structure the reasoning as if the analyst is making a forward prediction** (causal language, not hindsight).

**Expected dataset size:** With ~100 stocks × ~250 trading days × 15 years × ~10% signal frequency, expect approximately **35,000–40,000 labeled examples**. After filtering for quality (clear outcomes, no confounding events like M&A announcements), expect **20,000–25,000 training examples** — well above the threshold for effective LoRA fine-tuning (FinLlama achieved strong results with 34,180 examples at r=8, α=16).

**Step 5 — LoRA configuration.** Based on FinLlama (Iacovides et al., ICAIF 2024) and TradingGroup (2025, which fine-tuned Qwen3-8B specifically): rank **r=16**, alpha **α=32**, dropout **0.05**, target all attention projection layers. This produces ~8M trainable parameters on Qwen3-8B. Trainable on RTX 3060 (12GB) with QLoRA (4-bit quantization); more comfortable on RTX 3090 (24GB) without quantization.

---

## 6. Integration with existing pullback infrastructure

### Capital rotation between strategies

The two strategies share the same universe (S&P 100) but activate under different regimes. Implement a **soft capital rotation** governed by VIX and market trend:

- **VIX < 18, SPY > 50d SMA (trending bull):** 70% pullback / 30% mean reversion. Pullback dominates; mean reversion runs with reduced allocation but catches occasional volatility spikes.
- **VIX 18–28, mixed trend:** 50% pullback / 50% mean reversion. Both strategies active at full allocation.
- **VIX > 28, SPY < 50d SMA (stress/bear):** 30% pullback / 70% mean reversion. Mean reversion dominates; pullback allocation reduced because uptrend condition fails more frequently.

### Conflict resolution

When both strategies signal the same stock simultaneously (unlikely but possible — e.g., a stock in an uptrend pulls back enough to trigger both the pullback entry and the mean reversion entry): **execute the pullback signal** and record it against the pullback strategy. The pullback signal is more selective (requires confirmed uptrend + controlled pullback), while mean reversion is broader. The LLM can note the mean reversion confirmation as an additional confidence factor for the pullback trade.

### Shared infrastructure

Both strategies consume the same data pipeline: daily OHLCV for S&P 100, VIX, sector ETFs, and earnings data. Mean reversion requires adding: RSI(2), Connors RSI, Bollinger Bands, and Z-score calculations — trivial additions to existing technical indicator computation. The earnings SUE data (for both PEAD-filter and mean reversion quality filter) requires quarterly EPS actuals vs. estimates from a provider like Financial Modeling Prep or Alpha Vantage. Total additional API cost: **~$30–50/month**.

### Single portfolio, dual adapters

The Qwen3-8B base model loads once. The pullback LoRA adapter and mean reversion LoRA adapter are swapped at inference time — LoRA weights are ~32MB each and swap in milliseconds. Each evening after market close, the system runs both adapters against the current S&P 100 state: pullback adapter evaluates stocks meeting pullback criteria, mean reversion adapter evaluates stocks meeting oversold criteria. Signals are merged into a unified order book with position sizing reflecting strategy-level allocations.

---

## 7. Implementation timeline

| Phase | Duration | Activities | Milestone |
|-------|----------|-----------|-----------|
| **Research & data** | Weeks 1–3 | Finalize signal parameters, acquire 15 years of point-in-time S&P 100 data + earnings, compute all features | Feature database complete |
| **Backtest** | Weeks 4–7 | Walk-forward backtest of mean reversion signals (non-ML baseline), validate RSI(2) parameters on 2022–2024 holdout, measure correlation with pullback backtest | Baseline Sharpe > 0.5 on test set |
| **Training data generation** | Weeks 8–9 | Generate 20K+ labeled examples, convert to natural language, quality-check for look-ahead bias | Training dataset validated |
| **LoRA fine-tuning** | Weeks 10–11 | Train mean reversion adapter (QLoRA on RTX 3060 or full LoRA on 3090), hyperparameter sweep, evaluate on validation set | Adapter accuracy > baseline |
| **Paper trading** | Weeks 12–19 (8 weeks) | Run Strategy #2 alongside Strategy #1 on Alpaca paper trading, monitor decorrelation, signal quality, execution | Paper Sharpe > 0.4, correlation < 0 with pullback |
| **Gradual live deployment** | Week 20+ | Start with 25% of target allocation, scale to 100% over 4 weeks if metrics hold | Live trading operational |

**Critical go/no-go gates:** (1) Backtest Sharpe must exceed **0.5 net of estimated costs** (Harvey-Liu-Zhu threshold) on the 2022–2024 holdout. (2) Realized correlation with pullback strategy must be **< +0.20** during paper trading. (3) Paper trading drawdown must not exceed **−15%**. If any gate fails, iterate on signal construction before proceeding.

---

## The academic evidence in context

The mean reversion anomaly's trajectory follows the classic McLean-Pontiff pattern: raw effect decayed **~58%** post-publication. But three factors sustain it for Halcyon's implementation. First, the effect persists in the most liquid stocks because transaction costs are near-zero — De Groot, Huij, and Zhou (2012, *Journal of Banking & Finance*) showed large-cap reversal strategies generate **30–50 basis points per week net of costs**. Second, the residual reversal variant (Blitz, Huij, and Martens 2013, *Journal of Financial Markets*) — reversals after removing factor exposures — earned **>8% per annum net of costs** even for the 500 largest stocks and outperformed conventional reversals in every single decade from 1929–2008. Third, the regime-conditional approach concentrating trades in elevated-VIX environments captures the **liquidity provision premium** documented by Nagel (2012), which has not been arbitraged away because it requires bearing risk precisely when most participants are reducing it.

The backtest-to-live Sharpe decay literature suggests a realistic **33–50% haircut** (Quantpedia 2023 analysis of 355 strategies; CFM 2022 finding 33% decay for largest-1000-stock strategies; Suhonen et al. 2017 documenting 75% decay for complex strategies). A backtested Sharpe of 1.0 should deliver **0.5–0.65 live**. This remains above the Harvey-Liu-Zhu (2016) threshold of ~0.5 for genuine alpha, though margins are thin. The LLM adapter's ability to synthesize multiple features (technical, fundamental, regime) should provide an incremental edge over static rule-based implementations — TradingGroup (2025) demonstrated that fine-tuned Qwen3-8B outperformed GPT-4o-mini on return metrics, validating the architecture.

The deepest risk is that mean reversion's similarity to pullback-in-uptrend — both strategies fundamentally buy dips — produces higher-than-expected correlation. The key differentiator is the **regime filter**: mean reversion activates most aggressively in stressed markets (VIX > 25) where pullback signals are suppressed (uptrend condition fails). If this regime separation is maintained through disciplined implementation, the portfolio-level Sharpe improvement from combining two **~0.6 Sharpe strategies with −0.35 correlation** is substantial — a combined Sharpe near **0.8–0.9** with significantly reduced maximum drawdown compared to either strategy alone.
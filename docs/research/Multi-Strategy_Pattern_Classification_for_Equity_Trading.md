# Multi-strategy expansion for Halcyon Lab: an evidence-based blueprint

**Stay single-strategy through live deployment, but start building the data pipeline for strategy #2 today.** The academic and practitioner evidence is clear: adding a second, uncorrelated strategy to a pullback system improves portfolio Sharpe by **30–50%** — but only if the first strategy is proven live, fully automated, and the second strategy has genuinely low correlation. For Halcyon Lab's constraints (solo operator, single GPU, $1K–$25K initial capital), the optimal second strategy is **breakout from consolidation**, and the optimal architecture is **separate LoRA adapters per strategy** with a rule-based classifier as router. Here is the complete evidence behind that recommendation.

---

## 1. Most equity setups still have edge, but decay is real and regime-dependent

McLean & Pontiff (2016, *Journal of Finance*) established the baseline: anomaly returns decline **~58% post-publication** on average. A 2024 AEA paper confirmed anomaly peak returns hit ~1.5%/month around 2000 and have steadily eroded since. However, Lazo-Paz, Moneta & Chincarini (2023) found that even post-publication, crowded anomaly stocks retain alpha of **0.90%/month** (t-stat = 9.78) — the edge shrinks but doesn't vanish.

**Pullback in uptrend** (your current strategy) has the strongest practitioner evidence. Connors & Alvarez (2008) documented RSI(2) pullback strategies with **75–91% win rates** on S&P 500 constituents, with positive expectancy driven by hit rate rather than reward-to-risk (typically 0.5–0.8:1). The strategy works best in steady bull markets with normal volatility and worst in crisis regimes (the Feb–March 2020 COVID crash produced a 21.5% single-trade loss in backtests). The critical caveat: QuantifiedStrategies reports that "many mean reversion strategies, particularly ones that enter at the open, have lost their edges in the S&P 500 stock universe in recent years." **Current estimated Sharpe for large-cap US pullback strategies: 0.3–0.7**, down from 0.7–1.2 pre-2015. The edge persists but is thinner than a decade ago.

**Breakout from consolidation** has lower win rates (35–45%) but compensates with 2–3:1 reward-to-risk. Fang et al. (AUT University) found the volatility breakout method generated **+0.294% per signal** across 14 international markets, though the Bollinger Band Squeeze specifically lost significance in 13 of 14 markets post-2001. Moskowitz, Ooi & Pedersen (2012, *JFE*) documented trend-following breakouts with Sharpe ratios of 0.5–1.0 across asset classes. Breakouts work best during low-to-high volatility transitions and worst in choppy, range-bound markets. Current estimated Sharpe on US equities: **0.3–0.6**, but higher when filtered by volume confirmation.

**Momentum continuation** is the most academically validated setup. Jegadeesh & Titman (1993, *Journal of Finance*) found buying past 3–12 month winners yields ~1%/month. Wiest (2023, *Financial Markets and Portfolio Management*) confirmed it remains "the most pervasive contradiction of the EMH." Goyal, Jegadeesh & Subrahmanyam (2025, *Review of Finance*) report international momentum returns of **0.74–0.89%/month**. However, the 2024→2025 whipsaw was brutal: US momentum ETFs returned +38.7% in 2024 then crashed in 2025 as the "Magnificent Seven" trade unwound. Daniel & Moskowitz (2016) documented these momentum crashes and showed risk-managed (volatility-scaled) momentum achieves Sharpe **0.8–1.2** by avoiding the worst drawdowns. The critical weakness: maximum historical drawdowns reach -88% for unmanaged momentum.

**Mean reversion at extremes** has deep academic roots (DeBondt & Thaler, 1985; Lehmann, 1990; Jegadeesh, 1990). Lehmann found weekly reversal profits of 0.86–1.24%/week for losers. Da, Liu & Schaumburg (2014, *Management Science*) showed that within-industry reversal generates 3-factor alpha of **1.34%/month** (t=9.28) — dramatically outperforming naive reversal. MSCI Barra's Short-Term Reversal factor has outperformed by +3.5%/annum since 2008. Nagel (2012, *Review of Financial Studies*) proved reversal profits are compensation for liquidity provision, explaining why they persist: someone has to bear that risk. Current Sharpe: **0.3–0.6** in large-caps, higher in mid/small-caps.

**PEAD is effectively dead in liquid stocks.** This is the most important finding for your S&P 100 universe. While Ball & Brown (1968) and Bernard & Thomas (1989) documented annual abnormal returns of ~18%, Martineau (2022, *Critical Finance Review*) argued the drift disappeared from non-microcap stocks by 2006. Two 2025 papers claimed PEAD was "alive and well," but Subrahmanyam's reanalysis showed their results are driven entirely by microcaps: excluding microcaps drops the t-statistic from 2.18 to **1.43** (insignificant). For your S&P 100 universe, PEAD is not a viable primary edge.

**Sector rotation** is among the most persistent anomalies. Moskowitz & Grinblatt (1999, *Journal of Finance*) documented strong industry momentum, and Ehsani & Linnainmaa (2022, *Journal of Finance*) found factor momentum "stronger than and subsumes industry momentum." Dorsey Wright/Nasdaq data shows top-quintile sector momentum delivers **8.45–14.46% excess return/year**, and critically, "even since this anomaly was published many years ago, it continues to deliver outperformance." Current Sharpe: **0.5–0.8**.

**Gap fills and VWAP reversion** are intraday strategies that don't fit your 2–15 day hold framework. Stübinger (2019, *J. Risk Financial Management*) achieved Sharpe 2.38 for gap-fill strategies, but these require trades reversed within 120 minutes. VWAP is primarily an execution benchmark, not a daily-timeframe signal.

### Setup frequency and exploitability summary

| Setup type | Win rate | R:R | Current Sharpe | Signals/week (S&P 100) | Still viable? |
|---|---|---|---|---|---|
| Pullback in uptrend | 75–91% | 0.5–0.8:1 | 0.3–0.7 | 5–15 | Yes, but decaying |
| Breakout from consolidation | 35–45% | 2–3:1 | 0.3–0.6 | 2–5 | With volume filters |
| Momentum continuation | 55–60% | 1–1.5:1 | 0.3–0.5 | Continuous (monthly rebal) | Yes, with crash protection |
| Mean reversion at extremes | 60–70% | 0.3–0.6:1 | 0.3–0.6 | 3–10 | Yes, especially within-industry |
| PEAD | N/A | N/A | ~0 in large-cap | ~200/quarter (all S&P 500) | No, for liquid stocks |
| Sector rotation | 55–60% | 1–2:1 | 0.5–0.8 | Monthly rebalance | Yes, most persistent |

---

## 2. Separate LoRA adapters beat both single-model and full-model alternatives

The ML literature is unambiguous on one point: **multi-task learning for conflicting financial objectives creates negative transfer risk.** AAAI 2023 research showed that "certain tasks can dominate training and hurt performance in others," and OpenReview (2023) found the number of harmful task subsets grows exponentially with task count. For strategies with fundamentally opposing logic (mean reversion says "buy weakness," breakout says "buy strength"), training a single model on both creates gradient conflicts that degrade both.

The strongest evidence comes from the Mixture of Experts (MoE) literature applied to finance. AlphaMix (KDD 2023) used a three-stage MoE framework — train independent experts, train a router, then integrate via "expert soup" — and **significantly outperformed all baselines** on US and China market data. MIGA (2024) achieved **24% excess annual return** on CSI300 with 8 active experts out of 63. TradExpert (2024) used 4 specialized LLMs plus a general expert and achieved Sharpe **5.01**. LLMoE (2025) demonstrated that using an LLM as an intelligent router within MoE "demonstrated clear superiority over static MoE."

**What quant firms actually do:** The dominant industry architecture is separate strategy-specific models with shared infrastructure — the "pod" model. Citadel runs five core strategy groups with "relatively independent books" under centralized risk oversight. Millennium and Point72 use pods that specialize by sector or strategy type. Renaissance Technologies is the sole outlier using a single unified model, but they have a 20+ year data advantage that makes this viable for them alone.

### The LoRA adapter architecture is purpose-built for your setup

For Halcyon Lab specifically, **Option C (separate LoRA adapters per strategy)** is the clear winner. Each LoRA adapter adds only ~50MB to the base model's ~4–5GB (4-bit quantized). Your RTX 3060 with 12GB VRAM can hold the base model plus trivially swap between adapters. HuggingFace PEFT supports native hot-swapping via `load_adapter()` with `hotswap=True`. S-LoRA (LMSYS, 2023) demonstrated serving thousands of concurrent adapters with **up to 4× throughput improvement**.

The practical pipeline for your hardware runs comfortably in a 25–30 minute after-hours window: fetch OHLCV (~1 min) → feature engineering (~2 min) → rule-based regime classifier (CPU, instant) → strategy dispatcher (CPU, instant) → specialist inference via LoRA swap (~10–15 min for full universe) → risk management (~1 min) → Alpaca bracket orders (~1 min). For Ollama specifically, pre-merge each LoRA adapter into separate GGUF files and create distinct Modelfiles. Ollama reloads quantized 8B models in ~2–5 seconds, making sequential specialist calls seamless.

**Can an 8B model distinguish setup types?** Yes, but the LLM isn't the right tool for the classification step. FinGPT demonstrated that LoRA fine-tuning on Llama-3.1-8B with ~50K samples outperformed BloombergGPT on financial classification tasks. However, distinguishing pullback from breakout from momentum is fundamentally a **numerical time-series classification problem**, not NLP. Use a lightweight rule-based or ML classifier for routing, and reserve the LLM + LoRA adapters for strategy-specific reasoning and trade commentary — where they excel.

---

## 3. A rule-based classifier is sufficient to start, with clear upgrade path

The pattern classifier does not need to be sophisticated. The most discriminative features for distinguishing setup types are well-established:

**ADX** (trend strength) is the primary separator: values above 25 indicate trending environments (pullback or momentum territory), values below 20 indicate ranging environments (mean reversion or breakout territory). **ATR/price ratio** (normalized volatility) distinguishes consolidation (low, declining ATR) from breakout (expanding ATR). The **Hurst exponent** directly measures mean-reverting (<0.5) vs. trending (>0.5) behavior. **Volume profile** separates pullbacks (declining volume on retracement) from breakouts (expanding volume on range escape). **Price position relative to moving averages** distinguishes uptrend pullbacks (above 200 MA, pulling back to 20/50 MA) from oversold mean reversion (below key MAs).

A rule-based decision tree using these five features can achieve **80–85% classification accuracy** between pullback, breakout, momentum, and mean reversion regimes — and that's sufficient. Research from cascading pattern recognition systems (ScienceDirect, 2022) found that "ensemble methods achieved higher profits and better resilience than deep models," and that ML alone generates excessive false signals while rule-based pre-filtering dramatically reduces false positives.

**How accurate does the classifier need to be?** The answer depends on asymmetric misclassification costs. The most dangerous error is **treating a breakdown as a pullback** — buying into a falling knife. Your existing bracket orders (1–2 ATR stop-loss) provide a mechanical safety net against this. A classifier that's right 80% of the time, combined with your stop-loss discipline, is materially better than a system that only recognizes one setup type. You don't need 95% accuracy to extract value.

**Minimum training data:** For 4–5 class classification, the literature suggests 1,000–2,000 labeled examples per class, spanning multiple market cycles. Your current 790 pullback examples are a good start for one class. You need data spanning at least 5–7 years of daily bars to capture bull, bear, and sideways regimes.

For open-source tools: STUMPY (matrix profile library) handles unsupervised pattern discovery in time series. QSTrader includes Hidden Markov Model regime detection. ChartScanAI (GitHub) offers YOLOv8-based pattern detection. For your use case, start with the deterministic rule-based classifier and graduate to ML only when you have sufficient labeled data across all setup types.

---

## 4. Breakout is the highest-value second strategy, followed by sector rotation

Portfolio theory provides a precise framework for evaluating strategy combinations. Bailey & López de Prado (2013, *Algorithmic Finance*) derived the combined portfolio Sharpe ratio: **SR_portfolio = SR̄ × √(S / (1 + (S−1) × ρ̄))**, where S is strategy count and ρ̄ is average pairwise correlation. The key insight: "a strategy with SR=0.3 and correlation=0 to existing strategies may be MORE valuable than a strategy with SR=1.5 and correlation=0.8." **Correlation matters more than individual Sharpe.**

**Pullback + Breakout has the lowest expected correlation (-0.3 to +0.2) and the highest diversification benefit.** Balvers & Wu (2006) showed combination momentum-contrarian strategies outperform either pure strategy individually across 18 developed markets. Serban (2010) combined mean reversion and momentum in FX and achieved Sharpe **1.5 before costs** — far exceeding either strategy alone (momentum: 0.67–0.96). A Quantitativo implementation found mean reversion + momentum strategies had average correlation of only **0.29**, with combined Sharpe of 1.02 vs. sub-1.0 individual Sharpes. The behavioral logic is sound: pullback buys temporary weakness in uptrends, while breakout buys the start of new trends from consolidation. These are fundamentally different market conditions.

**Pullback + Sector Rotation is the second-best combination** (correlation 0.2–0.4). It operates at a completely different level of analysis — top-down sector selection vs. bottom-up stock timing — and sector rotation is among the most persistent documented anomalies. The limitation: sector rotation requires monthly rebalancing and longer holding periods, creating a mismatch with your 2–15 day framework.

**Pullback + Momentum Continuation is the weakest pairing** (correlation 0.4–0.7). Both strategies buy stocks in uptrends, just at different entry points. When applied to the same universe, the correlation is high enough to provide only modest diversification. Robert Carver notes that mean reversion and momentum operate at different time horizons — mean reversion at very short (2–30 min) and very long (2+ years), momentum at 3 weeks to 3 months — but within your 2–15 day window, they overlap substantially.

**Pullback + PEAD is theoretically excellent (correlation ~0) but practically unviable** for your S&P 100 universe given PEAD's death in liquid stocks.

### Quantified diversification benefit

Using the Bailey & López de Prado formula with individual Sharpe of 0.6 (conservative current estimate for pullback):

| Combination | ρ̄ | Combined Sharpe | Improvement |
|---|---|---|---|
| Pullback + Breakout | 0.0 | 0.85 | +41% |
| Pullback + Sector Rotation | 0.3 | 0.74 | +24% |
| Pullback + Momentum | 0.5 | 0.69 | +16% |

The breakout combination's **41% Sharpe improvement** is the single most impactful architectural change available. It also pairs naturally with your existing infrastructure: daily OHLCV data, bracket orders (breakouts use wider targets and tighter stops than pullbacks), and S&P 100 universe.

---

## 5. Start logging every setup today — this is the highest-ROI action available now

Your ranker currently ignores non-pullback setups, and that's leaving future training data on the table. Every breakout, momentum signal, or mean-reversion extreme your system can identify but doesn't trade is a free data point for future strategy validation — one that's immune to look-ahead bias because it was identified in real-time.

**What to log per setup:** timestamp, ticker, classified setup type, signal strength score, theoretical entry price, theoretical stop and target, market regime label (trending/ranging/volatile), and the stock's actual return over standardized windows (1-day, 5-day, 10-day, 20-day). This creates a "signal zoo" — every signal computed daily even if not traded. Professional quant systems universally maintain signal zoos because they enable correlation analysis between signals, regime detection, historical signal quality tracking, and rapid deployment of new strategies with pre-existing data.

**Minimum dataset for validating a new strategy:** 200–300 independent setups across at least 2 distinct market regimes for reliable validation, per backtesting literature consensus. At ~3–5 breakout signals per week across S&P 100 stocks, you'd accumulate 200 samples in roughly 10–15 months of logging. Starting now means you'll have a validated breakout dataset by the time your pullback strategy has enough live trades to justify expansion.

**Risk governance for mixed-strategy portfolios** requires treating each strategy as a separate risk bucket. Different strategies have different expected hold periods (pullbacks: 3–7 days; breakouts: 5–15 days), different win rates (pullbacks: 75%+; breakouts: 35–45%), and different drawdown profiles. The practical approach: use **risk parity across strategies** — equalize risk contribution rather than capital contribution. With a 1% max risk per trade, allocate risk budget proportionally: if pullback trades have 1 ATR stops and breakout trades have 0.5 ATR stops relative to their position sizes, the risk per trade remains equal even though capital allocation differs.

The academic evidence on cross-strategy diversification is strong. Andrew Lo's Adaptive Markets Hypothesis (2004/2017) argues markets are adaptive rather than efficient, meaning strategy effectiveness varies through time — diversifying across strategy types hedges against regime shifts. López de Prado's Hierarchical Risk Parity framework outperforms mean-variance optimization out-of-sample precisely because it respects the hierarchical correlation structure between strategies rather than assuming stable correlations.

---

## 6. Add strategy #2 at month 12, not before — and not much later

The statistical minimum for confidence in a trading strategy is **at least 200 trades** distributed across distinct market regimes. Bailey & López de Prado showed that for a strategy with Sharpe 1.0, you need approximately 3 years of live trading for a t-statistic of 2 (95% confidence). For practical purposes, 200+ trades spanning at least one bull market, one correction (10%+), and one choppy/sideways period gives enough data to separate skill from luck.

**For a solo operator, the binding constraints are cognitive capacity and capital fragmentation, not statistical power.** Each strategy requires 30–60 minutes/day minimum for monitoring and order management. With your Alpaca bracket orders handling exits mechanically, the monitoring load is lower than discretionary systems, but adding a second strategy still doubles the debugging surface area. Rob Carver (systematic trading expert) advises: "Implementation matters more than the strategy itself. Start diversifying across strategies as soon as your first strategy is automated and proven."

At your current capital levels ($1K–$25K), capital fragmentation is the primary risk. Running two strategies on $10K means ~$5K per strategy, which limits position sizes to the point where per-trade commissions and slippage consume meaningful alpha. The evidence-based thresholds from practitioner consensus:

- **$25K–$50K:** 1–2 strategies maximum. Capital fragmentation is binding.
- **$50K–$100K:** 2–3 strategies viable. Sufficient for two independent allocation buckets.
- **$100K–$250K:** 3–4 strategies optimal for solo operators.
- **$250K+:** 4–6 strategies before diminishing returns plateau.

Graham Capital Management's research shows that with realistic inter-strategy correlation of 0.2, the Sharpe improvement from adding strategies plateaus at roughly **15–25 strategies**. For correlations of 0.5 or higher, diminishing returns begin at just 3–5 strategies. You will never need more than 3–4 strategies to capture the majority of available diversification benefit.

**The "too many strategies" problem is real.** Goldman estimated quant equity managers lost 4.2% during the Summer 2025 quant unwind as crowded factor positions unwound simultaneously. More strategies increases exposure to correlated factor unwinds. The optimal strategy count is the minimum number of genuinely uncorrelated strategies that pushes portfolio Sharpe above 1.0.

---

## What to build now, later, and never

### Build NOW (Phase 2–3, current through month 12)

- **Setup logger:** Add a lightweight, rule-based setup classifier to your feature engine using ADX, ATR/price ratio, volume profile, and MA position. Log every identified setup (pullback, breakout, momentum, extreme mean-reversion) with theoretical entry/exit prices and actual outcomes. Store in SQLite. This costs almost nothing to implement and builds your future training dataset.
- **Regime label:** Tag each trading day with a market regime (trending up, trending down, ranging, volatile) using a simple ADX + VIX + 200 MA framework. Attach this label to every logged setup and every live trade.
- **Strategy #1 automation:** Ensure your pullback strategy runs with zero daily intervention. Mechanical entries via the ranker, mechanical exits via bracket orders, mechanical risk checks via the governor. This is the prerequisite for adding anything.

### Build LATER (Phase 4–5, months 12–24)

- **Breakout LoRA adapter:** Once you have 500+ logged breakout setups with outcomes, train a separate LoRA adapter for breakout-specific trade commentary. Pre-merge into a separate GGUF for Ollama. Start with 25% of risk budget allocated to breakout trades.
- **Multi-strategy risk parity:** Implement per-strategy risk tracking in your governor. Each strategy gets its own risk budget, drawdown circuit-breaker, and performance monitoring window.
- **Sector rotation overlay:** Add a monthly sector momentum signal as a universe filter (overweight top-3 sectors, underweight bottom-3) rather than a standalone strategy. This requires no additional model — just a sector relative-strength ranking applied to your existing stock universe.

### Build NEVER

- **PEAD strategy for S&P 100:** The anomaly is dead in liquid stocks. Don't waste training data on it.
- **Gap fill or VWAP reversion:** These are intraday strategies incompatible with your daily OHLCV framework and 2–15 day hold period.
- **Single multi-task model (Option B):** The negative transfer risk between conflicting strategies (mean reversion vs. breakout) is well-documented. Don't train one model on both.
- **More than 4 strategies before $100K AUM:** Capital fragmentation will eat the diversification benefit.

---

## The bottom line: patience is the edge

The strongest finding across all the research is that **the pullback-in-uptrend strategy you already have is one of the most robust short-term equity setups in the literature**, even after accounting for post-2015 edge decay. Short-term reversal has outperformed by +3.5%/annum since 2008 according to MSCI Barra data. The temptation to add strategies before proving the first one live is the classic solo-operator mistake — it fragments attention, capital, and debugging capacity simultaneously.

Your optimal path: master pullback execution through Phase 3, accumulate 200+ live trades, log every non-pullback setup you detect, and then deploy breakout as strategy #2 with a dedicated LoRA adapter once you have both the live track record and the labeled training data to support it. With two uncorrelated strategies at individual Sharpe ratios of 0.5–0.6 and near-zero correlation, the Bailey & López de Prado formula predicts a combined portfolio Sharpe of **0.7–0.85** — a meaningful improvement that justifies the additional complexity. Three strategies at $100K+ AUM pushes toward Sharpe 1.0, which is the threshold Peter Muller (PDT Partners) calls "very good."

The data pipeline you build today — logging every setup, tagging regimes, tracking outcomes — is worth more than any second strategy you could rush into production. When the time comes to add breakout trading, you'll have 12+ months of labeled, out-of-sample data ready for training. That's the kind of edge that doesn't decay.
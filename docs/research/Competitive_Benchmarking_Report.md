# Halcyon Lab — Competitive Benchmarking Report

*Generated March 2026*

---

## 1. Top 10 Competitive Profiles (3 Tiers)

### Tier 1 — Direct Competitors (Retail/Small Fund, <$10M AUM)

**1. Trade Ideas (Holly AI)**
- **What:** Real-time AI scanner analyzing 8,000+ stocks daily. Holly AI runs overnight simulations, delivers filtered alerts with entries/exits.
- **Tech stack:** Proprietary Holly engine, cloud-based, no user coding required. Pattern recognition + backtested filters.
- **Performance:** Holly claims 60-65% win rate on day/swing trades. No auditable Sharpe ratio published.
- **Data:** Real-time Level 1/2, historical OHLCV, news feed. No options or alternative data.
- **Team:** ~50 employees (est.), private. Pricing: $228/mo (premium).
- **Edge:** Best-in-class real-time scanning speed; massive retail user base for social proof.
- **Lesson for Halcyon:** Their overnight simulation approach is similar to our pre-market pipeline. Our LLM-generated commentary is a differentiator they lack.

**2. TrendSpider**
- **What:** Automated technical analysis — auto-draws trendlines, Fibonacci, detects 150+ candlestick patterns. Multi-timeframe overlays.
- **Tech stack:** Browser-based charting platform with AI overlay. Backtesting engine, strategy bots.
- **Performance:** No published returns. Tool-based, not signal-based.
- **Data:** Real-time stocks, futures, crypto, forex. No fundamental or alternative data integration.
- **Team:** ~30 employees. Pricing: $82/mo (standard).
- **Edge:** Best automated chart pattern recognition in retail space.
- **Lesson for Halcyon:** Their automated technical analysis could inspire more visual setup classification in our signal zoo.

**3. Tickeron**
- **What:** AI-powered pattern recognition and prediction. AI Robots generate signals across stocks, ETFs, forex. Neural network-based.
- **Tech stack:** Proprietary neural networks for pattern detection. Pre-built trading bots.
- **Performance:** Claims 60-75% win rates on various strategies. No auditable track record.
- **Data:** Technical patterns, some sentiment. Limited fundamental integration.
- **Team:** ~40 employees. Pricing: $50-250/mo.
- **Edge:** Accessible AI for non-technical traders; covers multiple asset classes.
- **Lesson for Halcyon:** Their multi-strategy approach (trend-following + mean-reversion + momentum) across asset classes is broader than our single-strategy focus.

**4. QuantConnect (LEAN Engine)**
- **What:** Open-source algorithmic trading platform. Code in Python/C#, backtest against historical data, deploy live.
- **Tech stack:** LEAN engine (open source), cloud compute, supports multiple brokers. Python/C#.
- **Performance:** Platform-dependent (user strategies vary). Alpha Streams marketplace.
- **Data:** Equity, options, futures, forex, crypto. Minute-level data back 20+ years. Some alternative data.
- **Team:** ~25 employees. Free tier + $8/mo data.
- **Edge:** Most flexible platform for quant developers. 30,000+ active community members.
- **Lesson for Halcyon:** Their backtesting rigor (walk-forward, transaction costs, survivorship-bias-free) is the gold standard we should match.

**5. Kavout (K Score)**
- **What:** AI-driven stock ranking system evaluating thousands of securities. Proprietary "Kai Score" rates stocks 1-9 based on 200+ factors.
- **Tech stack:** ML models blending fundamentals, technicals, and sentiment. API access for quant funds.
- **Performance:** K Score top-decile stocks outperform S&P 500 in backtests. No live fund returns published.
- **Data:** 200+ factors: fundamental, technical, alternative data, sentiment.
- **Team:** ~20 employees. Pricing: varies (API access for institutions).
- **Edge:** Factor breadth (200+ features) and institutional API.
- **Lesson for Halcyon:** Their 200-factor scoring model vs. our ~20 features shows the gap in feature engineering breadth.

### Tier 2 — Aspirational Competitors (Emerging AI Firms, $10M-$500M AUM)

**6. Numerai**
- **What:** Crowdsourced AI hedge fund. Data scientists submit ML predictions, staked with NMR tokens. Meta-model combines thousands of models.
- **Tech stack:** Encrypted feature sets, tournament-based model selection, ensemble of thousands of models.
- **Performance:** 25.45% net return in 2024; 8% net through Oct 2025 (beating PivotalPath Equity Quant Index 3%). Sharpe estimated 1.5-2.0.
- **Data:** Proprietary encrypted features (V5.1 "Faith" dataset), global equity universe.
- **AUM:** ~$450M. $500M valuation (Series C led by JPMorgan AM).
- **Edge:** Ensemble of 10,000+ independent models; crowdsourced alpha with crypto staking incentives.
- **Lesson for Halcyon:** Their meta-model approach (combining many weak models) is the opposite of our single fine-tuned LLM. Both approaches have merit.

**7. Man AHL (Systematic)**
- **What:** One of the longest-running quant firms. Systematic strategies across all asset classes.
- **Tech stack:** Proprietary ML infrastructure, massive compute cluster, 30+ years of data engineering.
- **Performance:** AHL Alpha: ~10-15% annualized, Sharpe ~1.0-1.5 over long periods.
- **Data:** Tick-level data across all asset classes, satellite imagery, NLP on filings.
- **AUM:** ~$50B under Man Group.
- **Edge:** Decades of experience, institutional infrastructure, multi-asset diversification.
- **Lesson for Halcyon:** Their regime-adaptive approach validates our regime classification system as the right direction.

### Tier 3 — Gold Standard (Institutional, $1B+ AUM)

**8. Renaissance Technologies (Medallion Fund)**
- **What:** The most successful quantitative fund in history. Statistical arbitrage across equities, futures, currencies.
- **Tech stack:** Custom infrastructure, 300+ PhDs, proprietary everything. Estimated millions of signals.
- **Performance:** ~66% annualized returns (before fees) 1988-2018. Sharpe ratio estimated 5+. Max drawdown kept under 10%.
- **Data:** Tick-level everything, satellite, weather, alternative data. Terabytes daily.
- **AUM:** ~$106B (employee-only Medallion is ~$15B).
- **Edge:** 35+ years of accumulated alpha signals; culture of secrecy; employee-only structure eliminates AUM bloat.
- **Lesson for Halcyon:** Their approach of finding many small, independent signals (each weak individually) is the institutional gold standard. Our signal zoo is a step in this direction.

**9. Two Sigma**
- **What:** Technology-driven investment firm. ML, distributed computing, massive data infrastructure.
- **Tech stack:** 1,800+ employees including 500+ engineers. Custom ML pipelines, cloud + on-prem.
- **Performance:** Spectrum fund ~15% annualized. Sharpe ~1.5-2.0. Led 2024 quant gains.
- **Data:** Proprietary data lake, 100+ alternative data sources, satellite, credit card, web scraping.
- **AUM:** ~$84B.
- **Edge:** Engineering-first culture; massive data infrastructure; talent density.
- **Lesson for Halcyon:** Their investment in data infrastructure (100+ alternative data sources) dwarfs anything a solo operator can build. Focus on unique data rather than breadth.

**10. Citadel (Wellington/Tactical)**
- **What:** Multi-strategy hedge fund. Quantitative and fundamental strategies across asset classes.
- **Tech stack:** $1B+ annual technology spend. Custom everything. 4,000+ employees.
- **Performance:** Wellington returned ~15% in 2024, 10.8% in 2025. Sharpe ~2.0.
- **Data:** Every data source that exists. Real-time everything.
- **AUM:** ~$65B.
- **Edge:** Capital to buy any data, any talent, any infrastructure. Speed (sub-millisecond execution).
- **Lesson for Halcyon:** Their risk management sophistication (real-time VaR, stress testing, correlation monitoring) is the benchmark. Our HSHS health score is a simplified version of what they do.

---

## 2. Competitive Scorecard (15 Dimensions)

| Dimension | Halcyon Lab | Best Retail | Best Emerging | Best Institutional | Gap to Close |
|-----------|:-----------:|:----------:|:-------------:|:------------------:|:-------------|
| **TECHNOLOGY** | | | | | |
| Model sophistication | 35/100 | 40/100 | 65/100 | 95/100 | Fine-tune larger models; add ensemble methods |
| Data infrastructure | 40/100 | 30/100 | 70/100 | 98/100 | Add tick-level data, more alternative sources |
| Feature engineering | 25/100 | 35/100 | 60/100 | 95/100 | Expand from ~20 to 100+ features |
| Backtesting rigor | 15/100 | 45/100 | 75/100 | 98/100 | Build walk-forward backtester with transaction costs |
| Execution quality | 30/100 | 25/100 | 70/100 | 99/100 | Fine for our timeframe; bracket orders sufficient |
| System reliability | 55/100 | 50/100 | 80/100 | 99/100 | Add failover, monitoring dashboards (we have HSHS) |
| **STRATEGY** | | | | | |
| Strategy count | 5/100 | 30/100 | 60/100 | 95/100 | Add breakout, momentum, mean-reversion from signal zoo |
| Universe breadth | 20/100 | 40/100 | 70/100 | 95/100 | Expand beyond S&P 100 to full Russell 1000 |
| Holding period diversity | 15/100 | 35/100 | 65/100 | 95/100 | Current: multi-day only. Add intraday + monthly |
| Risk management | 40/100 | 25/100 | 65/100 | 98/100 | Add correlation monitoring, sector limits (just added!) |
| Regime adaptation | 55/100 | 20/100 | 50/100 | 85/100 | Already above average — 7 regime types, adaptive thresholds |
| **DATA ASSET** | | | | | |
| Training data volume | 20/100 | N/A | 50/100 | 95/100 | 976 → 2,800 target. Need 10K+ for Phase 3 |
| Data uniqueness | 35/100 | 15/100 | 45/100 | 90/100 | Self-blinding pipeline is unique; signal zoo is rare |
| Temporal depth | 10/100 | 30/100 | 60/100 | 95/100 | Only live data since launch. Need historical backfill |
| **BUSINESS** | | | | | |
| Track record | 2/100 | 40/100 | 60/100 | 95/100 | Zero closed trades. Need 50+ for Phase 1 gate |
| Capital under management | 2/100 | 15/100 | 50/100 | 95/100 | $100 live. Phase 2 target: $5K-25K |
| Operational maturity | 45/100 | 35/100 | 70/100 | 95/100 | Good docs, council, health scoring. Need SOPs |

**Halcyon Lab Overall: 28/100** (early stage, strong foundation in some areas)

### Scoring Notes

**Where Halcyon Lab punches above its weight:**
- Regime adaptation (55/100) — 7 categorical regimes with adaptive thresholds exceeds most retail tools
- Operational maturity (45/100) — AI Council, HSHS health scoring, compute scheduler, Telegram commands
- Data infrastructure (40/100) — Options chains (48K/night), VIX term structure, 19 FRED macro series, earnings calendar
- Risk management (40/100) — Risk governor, daily loss limits, capital guards, sector exposure alerts (new)

**Where Halcyon Lab is weakest:**
- Track record (2/100) — Zero closed trades
- Temporal depth (10/100) — No historical backtest
- Backtesting rigor (15/100) — No formal backtester
- Holding period diversity (15/100) — Single timeframe
- Strategy count (5/100) — Single strategy (pullback-in-uptrend)

---

## 3. Top 10 Capability Gaps

| # | Capability | Why It Matters | Feasible for Solo GPU? | Priority |
|---|-----------|----------------|:----------------------:|----------|
| 1 | **Walk-forward backtesting** | Without it, you don't know if your strategy works historically. Every institution runs this. Prevents overfitting. | Yes (CPU-only) | Phase 1 — Critical |
| 2 | **Multiple uncorrelated strategies** | Single-strategy risk is catastrophic. 3+ uncorrelated strategies can double Sharpe. Signal zoo already captures setups for this. | Yes | Phase 2 |
| 3 | **Ensemble model approach** | Combining many weak models outperforms single strong models. Numerai's meta-model proves this at scale. | Yes (lightweight models) | Phase 2 |
| 4 | **Historical backfill** | Can't compute meaningful statistics on weeks of data. Need 5+ years of simulated trades to build confidence. | Yes | Phase 1 — Critical |
| 5 | **Factor breadth** | 200+ features (Kavout) vs ~20 features (Halcyon). More features = more alpha signals, if properly regularized. | Partially (some alt data requires $$$) | Phase 2-3 |
| 6 | **Tick-level execution analysis** | Measuring slippage, fill quality, market impact. Institutional firms optimize this for basis points. | Yes (Alpaca provides fills) | Phase 2 |
| 7 | **Cross-asset signals** | VIX, bond yields, credit spreads, and currency moves predict equity behavior. We collect some; need to use them as features. | Yes | Phase 2 |
| 8 | **Stress testing / scenario analysis** | How does the portfolio behave in a 2008, 2020, or 2022 scenario? Institutions do this daily. | Yes | Phase 2 |
| 9 | **Real-time portfolio correlation monitoring** | Knowing if your "diversified" positions are actually correlated is critical in drawdowns. | Yes | Phase 2 |
| 10 | **Alternative data integration** | Satellite imagery, credit card data, web scraping. Institutional edge. Most requires $50K+ annual data fees. | Limited (web scraping only) | Phase 3+ / Never for satellite |

---

## 4. Top 5 Genuine Differentiators

| # | Differentiator | Is It Real? | Who Else Does It? |
|---|---------------|:-----------:|-------------------|
| 1 | **LLM-generated trade commentary with self-blinding pipeline** | **Yes, genuinely rare.** Self-blinding (hiding outcomes during training data generation) is research-grade methodology that no retail tool implements. The LLM commentary itself is novel — most systems output scores, not narratives. | No retail competitor. Numerai has encrypted features (different approach). |
| 2 | **5-Agent AI Council (Modified Delphi)** | **Yes, unique in retail.** Multi-agent deliberation for strategic decisions is cutting-edge. The 3-round protocol (independent → cross-examination → final vote) mirrors institutional investment committees but with AI agents. | Not seen in any competitor at this level. |
| 3 | **Signal zoo logging non-traded setups** | **Yes, underrated.** Capturing breakout, momentum, and mean-reversion signals even when not trading them builds a future strategy pipeline. Most systems only log what they trade. | QuantConnect captures all backtest signals, but not as a live "zoo" of real-time non-traded setups. |
| 4 | **Integrated training flywheel (live trades → training data → better model)** | **Yes, but unproven.** The architecture is sound — closed trades generate training examples that improve the model. But with zero closed trades, the flywheel hasn't turned yet. Once it does, this is powerful. | Numerai has a version of this (tournament → model improvement). No retail tool has it. |
| 5 | **Full-stack from data collection to cloud dashboard to Telegram commands** | **Partially unique.** The breadth of the integrated system is impressive for a solo build. But Trade Ideas and TrendSpider also offer end-to-end experiences (just not custom). The specific combination (LLM + council + health scoring + compute scheduler + real-time dashboard + Telegram) is unique in totality. | No single competitor has all these pieces. Each has some subset. |

**Honest assessment:** Differentiators #1 and #2 are genuinely rare and valuable. #3 and #4 are valuable but unproven. #5 is more about integration breadth than any single unique capability.

---

## 5. Monthly Tracking Framework

### 5 Core Metrics

| Metric | Formula | Phase 1 (Good) | Phase 2 (Good) | Phase 3 (Good) | Red Flag |
|--------|---------|:--------------:|:--------------:|:--------------:|:--------:|
| **Win Rate** | Wins / Total Closed Trades | >55% (n>50) | >58% (n>200) | >60% (n>500) | <45% for 20+ trades |
| **Expectancy per Trade** | Avg(P&L per trade) | >$2/trade | >$5/trade | >$10/trade | Negative for 30+ trades |
| **Sharpe Ratio (annualized)** | (Avg daily return / Std daily return) * sqrt(252) | >0.5 | >1.0 | >1.5 | <0 for 3+ months |
| **Max Drawdown** | Max peak-to-trough decline | <15% | <10% | <8% | >20% at any point |
| **Training Data Growth** | Training examples added per week | >20/week | >50/week | >100/week | 0 for 2+ weeks |

### 2 Convergence Metrics

| Metric | Formula | What It Shows |
|--------|---------|--------------|
| **Alpha vs SPY** | (Portfolio return - SPY return) annualized | Whether you're beating buy-and-hold. Must be positive by Phase 2. |
| **Strategy Count** | # of independent strategies generating trades | Diversification progress. Target 3+ by Phase 3. |

### How to Measure

- **Win Rate & Expectancy:** Direct from `shadow_trades` table (already tracked)
- **Sharpe Ratio:** Compute from daily portfolio P&L series. Need 60+ trading days minimum.
- **Max Drawdown:** Track cumulative P&L peak; measure distance from peak at each point.
- **Training Data:** Count from `training_examples` table (already tracked in data asset report)
- **Alpha vs SPY:** Compare cumulative portfolio return against SPY buy-and-hold over same period.

---

## 6. Benchmark Returns

| Benchmark | Recent Performance | Relevance to Halcyon Lab |
|-----------|:------------------:|--------------------------|
| **S&P 500 Buy-and-Hold** | +24% (2024), ~16% (2025), 10-year avg ~15.6%/yr | The minimum bar. If you can't beat this, use an index fund. |
| **10-Year Treasury (Risk-Free)** | ~4.2% yield (late 2025), trending toward 3.8% | Opportunity cost. Your Sharpe numerator is return minus this rate. |
| **Connors RSI Pullback (Academic)** | ~30% annual (multi-stock, 1999-present), 75% win rate, 35% max DD | Direct strategy benchmark. Halcyon's pullback approach should target similar returns. |
| **Best Retail Algo Tools** | Trade Ideas Holly claims 60-65% win rate. No auditable returns. | Comparison for signal quality. Most retail tools don't publish auditable returns. |
| **Numerai (Emerging)** | 25.45% (2024), 8% through Oct 2025. Sharpe ~1.5-2.0 | Aspirational benchmark. If Halcyon reaches Numerai's Sharpe, you're competitive. |
| **Two Sigma / Citadel** | ~15-18% annualized, Sharpe 1.5-2.0 | Gold standard for risk-adjusted returns. Their edge is resources, not just strategy. |
| **Medallion Fund** | ~66% before fees (historical). Sharpe ~5+. | Unreachable benchmark. Useful for humility, not targeting. |

### Realistic Targets by Phase

| Phase | Target Return | Target Sharpe | Target Win Rate | Benchmark Comparison |
|-------|:------------:|:------------:|:--------------:|---------------------|
| Phase 1 (1-6 months) | Beat risk-free (>4%) | >0.5 | >55% | Must establish basic profitability |
| Phase 2 (6-18 months) | Beat SPY (~12-16%) | >1.0 | >58% | Competitive with best retail tools |
| Phase 3 (18-36 months) | >20% annualized | >1.5 | >60% | Approaching Numerai / emerging tier |

---

## 7. Specific Recommendations

### To Move from Tier 1 Retail → Tier 2 Emerging:

1. **Build the track record first.** Nothing else matters until you have 50+ closed trades with measurable statistics. This is your Phase 1 gate for a reason.

2. **Add a walk-forward backtester.** Use historical data to simulate what your system would have done over the past 5 years. This gives you confidence intervals and identifies regime-specific weaknesses.

3. **Activate the signal zoo.** You're already logging breakout, momentum, and mean-reversion setups. Building even one additional strategy from this data doubles your strategy count and reduces single-strategy risk.

4. **Expand the feature set.** Go from ~20 features to 50+ by incorporating your existing collected data (options IV, put/call ratios, VIX term structure slope, FRED macro indicators) as direct features in the ranking model.

5. **Historical backfill.** Simulate your current strategy against 3-5 years of historical data. This doesn't require GPU — just OHLCV data and your feature engine running on CPU.

### Priority Matrix

| Priority | Action | Effort | Impact |
|----------|--------|:------:|:------:|
| **NOW** | Close 50 trades (Phase 1 gate) | Time | Critical |
| **Phase 1** | Walk-forward backtester | 2-3 weeks | High |
| **Phase 1** | Historical backfill simulation | 1-2 weeks | High |
| **Phase 2** | Second strategy from signal zoo | 2-4 weeks | High |
| **Phase 2** | Feature expansion (50+ features) | 2-3 weeks | Medium |
| **Phase 2** | Slippage/execution analysis | 1 week | Medium |
| **Phase 3** | Ensemble models | 3-4 weeks | Medium |
| **Phase 3** | Cross-asset signals as features | 2-3 weeks | Medium |
| **Never** | Satellite data, HFT infrastructure | $$$ | Low for our timeframe |

---

## Sources

- [Best AI Trading Platforms 2026 - LiquidityFinder](https://liquidityfinder.com/insight/technology/best-ai-platforms-for-trading-and-analytics)
- [AI Trading Bots - StockBrokers.com](https://www.stockbrokers.com/guides/ai-stock-trading-bots)
- [Renaissance Tech and Two Sigma Lead 2024 Quant Gains - Hedgeweek](https://www.hedgeweek.com/renaissance-tech-and-two-sigma-lead-2024-quant-gains/)
- [Top 12 Quant Trading Firms 2026 - QuantVPS](https://www.quantvps.com/blog/top-quant-trading-firms)
- [Hedge Funds 2025 Report Card - Yahoo Finance](https://ca.finance.yahoo.com/news/2025-returns-hedge-funds-rolling-234728986.html)
- [Numerai $500M Valuation - AInvest](https://www.ainvest.com/news/numerai-hedge-fund-model-hits-500m-ai-crowd-wisdom-redefine-finance-2511/)
- [Trade Ideas vs TrendSpider - Liberated Stock Trader](https://www.liberatedstocktrader.com/trade-ideas-vs-trendspider/)
- [Connors RSI Strategy: 75% Win Rate - Quantified Strategies](https://www.quantifiedstrategies.com/connors-rsi/)
- [S&P 500 Historical Returns - Macrotrends](https://www.macrotrends.net/2526/sp-500-historical-annual-returns)
- [Kavout AI Platform Review - WallStreetZen](https://www.wallstreetzen.com/blog/kavout-review/)
- [Best Quantitative Trading Firms - Quant Savvy](https://quantsavvy.com/best-quantitative-trading-firms-renaissance-technologies-two-sigma-shaw-fund/)

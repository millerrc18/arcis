# Alternative data signals worth adding to your trading stack

Options flow is the only signal that clears every hurdle — empirically validated, affordable, and genuinely hard to process correctly. Most alternative data either costs institutional money ($10K+/year), operates at the wrong time horizon, or provides negligible alpha for S&P 100 large-caps. After reviewing the academic evidence across all seven categories, the honest recommendation is to add two or three carefully chosen signals rather than chase data for completeness. The defensible advantage for Halcyon Lab lies not in any single data source but in the combinatorial complexity of fusing options-derived sentiment with existing fundamental, technical, and macro features inside an LLM pipeline — a synthesis that is rare at any budget level.

## Options flow is the highest-value addition under $100/month

Of everything researched, options market data offers the strongest combination of academic validation, budget feasibility, and genuine edge. Pan and Poteshman (2006, *Review of Financial Studies*) demonstrated that stocks with low put/call ratios outperformed high-ratio stocks by **over 1% in the subsequent week** — a finding rooted in informed trading through derivatives markets. Cremers and Weinbaum (2010, *JFQA*) found that stocks with relatively expensive calls outperformed those with expensive puts by **50 basis points per week**, driven by deviations from put-call parity. Xing, Zhang, and Zhao (2010, *JFQA*) showed the steepest volatility smirk decile earned **-7% annualized** abnormal returns, indicating informed traders buying OTM puts ahead of negative news.

These are not backtest artifacts. They are published in top-tier finance journals with rigorous controls. However, honesty demands acknowledging significant signal decay. Bondarenko and Muravyev documented that the put/call ratio's predictive power **collapsed after the 2009 insider trading crackdown** — suggesting much historical alpha came from illegal activity. Cremers and Weinbaum explicitly note decreasing predictability over their sample period. Muravyev, Pearson, and Pollet (2022) argue the IV spread/skew signals partly proxy for stock borrowing fees rather than informed trading per se.

The signals that survive decay best are **sweep activity** and **unusual OTM positioning**. Chakravarty, Jain, Upson, and Wood (2012, *JFQA*) provide genuine academic evidence — not practitioner lore — that intermarket sweep orders carry a significantly larger information share than regular trades, consistent with institutions executing on short-lived private information. A 2025 paper in *Review of Quantitative Finance and Accounting* found that substantial positions in deep OTM, short-maturity options are the strongest informed trading indicator, with long-short portfolios yielding **over 60% annually** in-sample.

For implementation, the recommended stack costs roughly **$50/month**: Unusual Whales (~$50) provides real-time sweep/block detection, dark pool data, gamma exposure, and downloadable historical flow. Supplement with free Yahoo Finance options chains via yfinance for IV computations, CBOE daily put/call ratios, and FINRA dark pool volume (2-week lag, useful as context only). The structured training example format would add an eighth section:

```
OPTIONS CONTEXT for {TICKER} as of {DATE}:
- Put/Call Volume Ratio: {value} ({percentile}th percentile vs 30-day avg)
- IV Rank: {value}% (30-day IV vs 1-year range)
- IV Spread (Call - Put): {value} ({calls/puts expensive relative to parity})
- IV Skew (OTM Put - ATM Call): {value} ({steeper/flatter than normal})
- Unusual Activity: {N} sweeps detected, {direction} bias, ${premium} total
- Net Options Sentiment: {BULLISH/BEARISH/NEUTRAL} based on composite
```

The competitive advantage here is real: processing raw options flow into meaningful features requires understanding market microstructure (opening vs. closing transactions, hedging vs. directional flow, sweep urgency classification). Most retail traders consume pre-digested "unusual activity" alerts without the contextual integration that an LLM pipeline enables. Combining options-implied sentiment with fundamental quality, technical momentum, macro regime, and insider trading creates a multi-dimensional signal that is genuinely hard to replicate.

## Google Trends provides a free attention signal with a matching time horizon

Da, Engelberg, and Gao's 2011 paper in the *Journal of Finance* — "In Search of Attention" — is among the most cited in modern empirical finance. Their finding maps almost exactly to Halcyon's use case: Google search volume increases predict **higher stock prices over the next two weeks** followed by price reversal within a year. The mechanism is retail investor attention: when individuals search for a stock ticker, buying pressure follows.

The evidence is real but substantially decayed. Curme, Preis, Stanley, and Moat (2014, *PNAS*) explicitly noted diminishing predictive value in more recent data. Preis, Moat, and Stanley's (2013) headline-grabbing 326% return from a Google Trends strategy was likely data-mined — Challet and Ayed (2013) showed random finance keywords produced comparable results. For **S&P 100 large-caps specifically**, the signal is weaker than for less-covered stocks, because the retail attention mechanism is diluted when institutional flow dominates. Salisu and Isah (2021) found Google Trends correlations with stock returns have actually **inverted** across sectors in recent data.

Despite these caveats, Google Trends remains worth implementing for three reasons. First, it costs nothing. Second, even a decayed attention signal adds a dimension (retail behavioral) not captured by Halcyon's existing technical, fundamental, or macro sources. Third, spikes in search volume may function as a **contrarian indicator** — abnormal retail attention often coincides with panic or euphoria that creates mean-reversion opportunities. The signal should be formatted as:

```
ATTENTION CONTEXT for {TICKER} as of {DATE}:
- Google Trends Index: {value} (vs 90-day moving avg: {ratio}x)
- Search Volume Spike: {YES/NO} (>2σ above 30-day mean)
- Attention Regime: {ELEVATED/NORMAL/LOW}
```

Expected marginal alpha is modest — likely **under 10 basis points per trade** for large caps — but the zero cost and minimal engineering effort make the risk-reward favorable.

## Most "impressive" alternative data fails the S&P 100 feasibility test

The strongest-evidence alternative data sources are prohibitively expensive, and the affordable ones don't work well for large-cap stocks. This is not coincidental — it reflects the Grossman-Stiglitz equilibrium, where the cost of information roughly equals its value.

**Credit card transaction data** has the most robust academic validation. Gupta, Leung, and Roscovan (2022) found long-short strategies using credit card data generated **16% per annum** after controlling for standard factors. Froot, Kang, Ozik, and Sadka (2017, *Journal of Financial Economics*) showed real-time sales proxies from 50 million mobile devices predicted earnings surprises, generating **3.4% average excess announcement returns**. The evidence is strong, published in top journals, and works for consumer-facing large caps. But Bloomberg Second Measure, Earnest Research, and Consumer Edge all charge **$10,000-$100,000+ per year**. Completely infeasible at $0-100/month.

**Satellite imagery** tells a similar story. Katona, Painter, Patatoukas, and Zeng (2023, *Journal of Financial Economics*) analyzed millions of RS Metrics parking lot images and found trading strategies yielding **4-5% abnormal returns** in the three days around earnings announcements. The signal has not been fully competed away because access remains exclusive — RS Metrics charges **$50,000-$500,000+ per year**.

**Web traffic data** (Armstrong, Konchitchki, and Zhang 2025, *The Accounting Review*) shows digital traffic is a leading indicator of revenue that generates substantial abnormal returns. But SimilarWeb's Stock Intelligence product costs several hundred dollars monthly — over budget — and the signal works primarily for consumer/tech names with transactional websites.

The pattern is clear: alternative data alpha exists, but the data vendors price it to capture most of the surplus. For a **$0-100/month budget**, the actionable universe shrinks dramatically to options flow, Google Trends, free government data, and existing Finnhub features that may be underutilized.

## Earnings revisions and congressional trades are overrated for this use case

Earnings estimate revisions carry genuine predictive power in the academic literature, but the signal is weakest precisely where Halcyon operates. Martineau (2022, *Critical Finance Review*) titled his paper bluntly: "Rest in Peace Post-Earnings Announcement Drift." Subrahmanyam (2025, UCLA) replicated PEAD using data through 2024 and found that when microcaps are excluded, the t-statistic dropped from 2.18 to **1.43 — not significant**. Gleason and Lee (2003, *The Accounting Review*) established that price adjustment to analyst revisions is "faster and more complete for firms with greater analyst coverage" — S&P 100 stocks have 25-40 analysts each.

The timeliness problem is fatal. Professional algorithmic traders receive I/B/E/S revision feeds within seconds. Free data sources (Finnhub, FMP, Alpha Vantage) provide consensus snapshots updated daily at best. By the time a free data consumer detects a revision, the S&P 100 stock has already incorporated it. The one viable approach: use Finnhub's existing earnings surprise data (already in the stack) for same-day entry signals after announcements, and build a daily consensus snapshot store using FMP's free tier over several months. Expected incremental value: **less than 0.5% Sharpe ratio improvement** for large caps.

Estimate dispersion (analyst disagreement) deserves a footnote. Diether, Malloy, and Scherbina (2002) found high-dispersion stocks underperform by **9.48% per year**, and dispersion reliably predicts higher volatility. This is useful not for directional trading but for **position sizing** — wide disagreement should trigger smaller positions.

Congressional trading is dramatically overhyped. Eggers and Hainmueller (2013, *Journal of Politics*) reanalyzed the Ziobrowski data and found **no evidence** of informed trading for 2004-2008 — Congress members actually underperformed by 2-3%. Post-STOCK Act, Belmont, Sacerdote, Sehgal, and Van Hoek (2022, *Journal of Public Economics*) found senators' purchases slightly **underperform** benchmarks. The only exception: Wei and Zhou (2025) found that roughly **10-15 congressional leaders** show persistent alpha, measured over months to years. The 30-60+ day disclosure delay makes this signal useless for 2-15 day trades regardless. The NANC and KRUZ ETFs, with over $100M in AUM each, demonstrate that systematically following congressional trades does not reliably outperform once disclosure delays are accounted for.

## Social media sentiment is noise for S&P 100 stocks

Baker and Wurgler's framework (2006, *Journal of Finance*) predicts exactly what the empirical evidence confirms: sentiment effects concentrate in "stocks whose valuations are highly subjective and difficult to arbitrage" — small, young, volatile, unprofitable firms. S&P 100 stocks are the **opposite**: covered by dozens of analysts, deeply liquid, easy to short, and dominated by institutional flow.

The foundational paper in this space has failed replication. Lachanski and Pav (2017, *Econ Journal Watch*) could not reproduce Bollen, Mao, and Zeng's (2011) 87.6% directional accuracy claim. Extended to a longer sample, the Twitter mood effect disappeared entirely. The hedge fund Derwent Capital Markets, built to implement this strategy, **closed within 18 months**. Bradley, Hanousek, Jame, and Xiao (2024, *Review of Financial Studies*) found WSB "due diligence" posts were informative pre-2021 but this predictability was **completely eliminated** after the GME episode, as the platform shifted from analysis to hype.

Cookson, Lu, Mullins, and Niessner (2024, *Journal of Financial Economics*) offer the most balanced recent assessment. They found sentiment across Twitter, StockTwits, and Seeking Alpha positively predicts next-day abnormal returns, but the effect is small (~**5-15 basis points**), mostly same-day, and deteriorated significantly post-GME. Professional users' sentiment carries more signal than retail — but accessing professional Twitter/X data costs $200-5,000+ per month.

The only zero-cost action worth taking: **test Finnhub's existing social_sentiment endpoint**, which Halcyon already has access to. If it adds marginal value in backtesting, keep it. StockTwits' free API could serve as a **volatility/attention spike detector** (>3σ post volume = upcoming volatility), useful for position sizing rather than directional prediction.

## Supply chain data is a macro context signal, not a stock-picking tool

Bakshi, Panayotov, and Skoulakis (2011) established that the Baltic Dry Index predicts global stock market returns — but at **1-3 month horizons** and at the **aggregate market level**, not for individual stocks. Every supply chain indicator examined (BDI, freight rates, ISM Supplier Deliveries, inventory ratios) operates at monthly+ frequencies with publication lags that make them irrelevant for 2-15 day individual stock selection.

The one exception is Cohen and Frazzini's (2008, *Journal of Finance*) customer-supplier momentum, which showed a long-short strategy earning **over 150 basis points monthly** by trading supplier stocks after major customer price moves. The lag operates over **1-20 trading days** — directly within Halcyon's horizon. However, for S&P 100 names (which are typically the customers, not the smaller suppliers), the effect is weaker. This strategy works better for selecting which mid-cap suppliers to trade based on S&P 100 customer signals.

The NY Fed Global Supply Chain Pressure Index (GSCPI) should be added as a **free macro regime variable**. It integrates 27 variables including shipping indices, airfreight costs, and PMI components across seven economies. Current reading (February 2026): **0.49**, slightly above average, potentially reflecting tariff-related pressures. Add it to the macro section of training examples alongside existing FRED data.

## The integration blueprint: what to build and what to skip

After evaluating all seven categories against Halcyon Lab's specific constraints (S&P 100 universe, 2-15 day holds, $0-100/month budget), here is the honest cost-benefit assessment:

**Implement now (~$50/month, high expected value):**
- **Options flow via Unusual Whales** ($50/month) — Add as 8th training example section. Extract IV rank, IV spread/skew, sweep activity, net premium flow. Academic backing from Pan & Poteshman, Cremers & Weinbaum, Xing et al., Chakravarty et al. The competitive advantage is in *processing complexity*: translating raw flow into structured natural-language context that an LLM can reason over is genuinely hard to replicate.

**Implement now ($0, moderate expected value):**
- **Google Trends** — Add as attention/contrarian indicator. Free API, 2-week predictive horizon matches holding period. Add to sector or regime section as an attention overlay.
- **NY Fed GSCPI** — Monthly supply chain pressure. Add to macro section alongside existing FRED data. Zero cost.
- **Finnhub social_sentiment endpoint** — Already accessible. Test in backtesting before committing engineering effort. Add to news section if valuable.
- **FRED inventory/ISM series** — Add ISRATIO, NAPMSDEL if not already included. Free via existing FRED integration.

**Build over time ($0, low but compounding value):**
- **FMP daily consensus earnings snapshots** — Use free tier (250 requests/day) to build a proprietary revision momentum dataset over weeks/months. The *accumulation of proprietary historical data* itself becomes a defensible advantage that compounds over time. Expected alpha is small for S&P 100 but the cost is zero.

**Skip entirely (evidence doesn't support the use case):**
- Satellite imagery, credit card data, web traffic ($10K-$500K/year)
- Patent filings, job postings (wrong time horizon)
- Congressional trading (30-60 day disclosure delay, no alpha post-STOCK Act)
- Reddit/WSB sentiment (noise for large caps post-GME)
- Twitter/X sentiment ($200-5,000/month, weak signal for S&P 100)
- Dedicated shipping/freight data feeds (macro only, monthly horizon)
- Dark pool data as directional signal (2-4 week lag)

The total recommended spend is approximately **$50/month** on Unusual Whales, with the remaining $50 reserved for potential additions like Barchart Premier ($25/month for additional options screening) or Quiver Quantitative ($10/month API for pre-aggregated alternative data including sentiment and insider trading). The updated training example structure would expand from 7 to 9 sections: technical indicators, market regime, sector context, SEC EDGAR fundamentals, Finnhub insider trading, Finnhub news headlines, FRED macro indicators (enhanced with GSCPI and ISM series), **options flow context**, and **attention/sentiment context** (Google Trends + Finnhub social sentiment).

## Conclusion

The most important finding is negative: **the vast majority of alternative data marketed to retail and semi-institutional traders is either too expensive, too slow, or simply doesn't work for large-cap short-horizon trading**. The McLean and Pontiff (2015) result — anomalies decline 58% post-publication — applies relentlessly. What remains after this filter is a narrow set of signals where the edge comes not from data access but from *processing sophistication*.

Options flow is the clear winner because it satisfies all three criteria simultaneously: empirical validation in top journals, affordability within budget, and genuine processing complexity that creates a durable advantage. The IV spread, IV skew, and sweep signals capture informed institutional positioning that is complementary to (not redundant with) Halcyon's existing technical, fundamental, and news features. Google Trends and GSCPI add low-cost behavioral and macro dimensions, respectively.

The deeper strategic insight: Halcyon Lab's moat is not in any individual data source — all of these are publicly accessible. The moat is in the **combinatorial fusion** of multiple signal types into structured LLM training examples that enable contextual reasoning across dimensions. A system that can reason about "IV skew is steep AND insider buying increased AND macro regime shifted AND Google attention is spiking" creates a synthesis that no single-signal strategy can replicate. Each additional well-chosen signal multiplies the combinatorial space of contextual patterns, making the system progressively harder to reverse-engineer. That compounding effect — not the data itself — is the defensible advantage worth building.
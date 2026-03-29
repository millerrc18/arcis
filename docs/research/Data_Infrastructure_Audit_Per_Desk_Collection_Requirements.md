# Halcyon Lab data infrastructure audit: what to collect now and why

**Your current data stack covers roughly 70% of what Desks 1–2 need but only 30–40% of Desks 3–5.** The highest-priority gap is production-grade data reliability — yfinance has suffered documented multi-day outages in September 2024, February 2025, and throughout late 2025, making it unacceptable as a sole source for a live trading system. The most valuable additions you can make today cost just **$29/month** (Polygon Starter) plus free sources (SEC EDGAR, FINRA short interest) that compound dramatically over time. Options volatility trading (Desk 3) requires the largest data infrastructure upgrade — professional Greeks, IV surface data, and historical chains that yfinance cannot provide at any price. Meanwhile, your Google Trends collection for individual S&P 100 tickers should be deprioritized: the alpha documented by Da, Engelberg, and Gao (2011) has inverted in post-2013 data for large caps, and multiple replication studies confirm the signal is no longer profitable after transaction costs.

---

## Per-desk data matrix: what exists, what's missing, what to start now

### Desk 1–2 (Equity Pullback/Research) — 80% covered

Your existing stack handles the pullback strategy well. Daily OHLCV, options-derived sentiment (put/call ratio, unusual OI), VIX term structure, macro snapshots, and the earnings calendar give strong coverage for **2–15 day holds**. The key gaps are reliability and survivorship bias rather than missing data categories.

**What's missing:** A backup OHLCV provider for the inevitable yfinance outage. Survivorship-bias-free historical data for backtesting (yfinance drops delisted tickers entirely — QuantRocket research shows datasets missing **75% of stocks** at the 10-year lookback). FINRA short interest data, which Rapach, Ringgenberg, and Zhou (2016) identified as "arguably the strongest predictor of the equity risk premium identified to date." SEC Form 4 insider trading data beyond yfinance's limited coverage — Cohen, Malloy, and Pomorski (2012) found opportunistic insider purchases generated **5.2% alpha over six months**.

**Data frequency:** Daily OHLCV is sufficient. EOD options snapshots work for signal generation. Macro data refreshes at native frequency (weekly for claims, daily for FRED financial series).

### Desk 3 (Options Volatility) — 35% covered

This desk has the largest data gap. Credit spreads and iron condors require a fundamentally different data infrastructure than equity swing trading. Your current EOD options chains via yfinance provide 14 fields; **professional options trading requires at minimum 25+ fields** including all five Greeks (delta, gamma, theta, vega, rho), theoretical values, and the full IV surface.

**Critical missing data:** Greeks per contract (yfinance computes none — delta is essential for strike selection at the 16-delta standard for credit spreads). Historical options chains for backtesting (yfinance provides only current snapshots, never historical). IV surface data across strikes and expirations (required for skew and term structure trading). Earnings volatility history — actual moves versus expected moves for the prior 8–12 quarters, which drives the core edge in selling pre-earnings premium.

**Recommended provider:** ORATS provides smoothed market values (SMV) that fall within the bid-ask spread 99% of the time, along with 500+ proprietary volatility indicators. Their delayed API runs **$99/month**, live API **$199/month**, and historical data from August 2020 costs a one-time **$1,500**. Theta Data offers a more affordable entry at **$40–160/month** with minute-level options data. These costs are unavoidable for serious options trading — empirical evidence shows implied volatility overstates realized volatility roughly 85% of the time, but capturing that edge requires accurate Greeks and IV data.

**Data frequency:** EOD is sufficient for entry decisions on 7–45 DTE strategies. Intraday refresh (every 30 minutes minimum) is needed for position monitoring and adjustment triggers when the underlying approaches short strikes.

### Desk 4 (Breakout/Momentum) — 60% covered

Daily OHLCV gets most of the way there. The primary gap is volume analytics and market internals. Breakout confirmation requires **relative volume of 1.5–2.0× the 20-day average** — a threshold documented across academic microstructure literature and confirmed by a 2024–2025 algorithmic study showing ~78% ROI on volume-filtered breakout signals versus significantly higher false breakout rates without volume confirmation.

**What's missing:** Market breadth data — NYSE advance/decline line, TICK (upticking minus downticking stocks), and TRIN/Arms Index. These are available free through Interactive Brokers' TWS API or as a **$49/month** Polygon add-on. Closing readings between 3:45–4:00 PM ET carry the highest predictive weight for next-session directional bias. You should also add computed volume features: On-Balance Volume, Chaikin Money Flow, and volume rate-of-change over 3–5 bars before potential breakouts.

**Data frequency:** Daily bars are the minimum viable dataset for identifying multi-day consolidation patterns. 60-minute bars improve entry precision but are beneficial rather than essential for 5–20 day holds.

### Desk 5 (Intraday) — 5% covered

Your current daily-frequency architecture cannot support intraday trading at all. This desk requires a fundamentally different infrastructure: **real-time Level 1 data** (NBBO + last trade + volume) at minimum, with Level 2 market depth recommended. VWAP reversion needs continuous volume data for cumulative price×volume calculation. Opening range breakout needs the first 5–30 minutes of bars plus pre-market highs/lows.

**What's missing:** Everything real-time. The most cost-effective path is **Alpaca Algo Trader Plus at $99/month** (full SIP feed + commission-free execution) or **Polygon Advanced at $199/month** (real-time WebSocket streaming for up to 50 tickers per connection). Interactive Brokers provides Level 1 + Level 2 for as little as **$4.50/month** for non-professionals but requires a brokerage account.

**Storage for 1-minute bars:** 100 stocks × 390 bars/day × 252 days = ~9.8 million rows/year, consuming roughly **1 GB/year** — highly manageable. Tick data would balloon to **20–50 GB/year** for S&P 100, which remains feasible but requires a storage strategy shift. Start with 1-minute bars; upgrade to tick data only if pursuing order-flow-based strategies.

---

## The yfinance reliability problem is your most urgent risk

yfinance is an unofficial web scraper maintained primarily by a single developer with **zero SLA and zero uptime guarantee**. The documented failure timeline is alarming: a major outage in September 2024 broke data retrieval for Nasdaq 100 constituents, Yahoo API changes in February 2025 caused widespread "possibly delisted" errors for actively traded stocks, and multiple open issues from September–November 2025 indicate continued instability. Yahoo has progressively tightened access by adding CAPTCHAs, requiring cookies, and blocking cloud IP ranges — PythonAnywhere and AWS users reported multi-day outages in October 2024.

For options chains specifically, yfinance is **categorically inadequate for production options trading**. It provides 14 fields (no Greeks, no historical chains, no intraday updates, no theoretical values). Multiple complete failures of the options endpoint are documented in GitHub issues #1738 and #1847. The implied volatility values use an undocumented Yahoo computation methodology of unknown quality.

**The fix costs $29/month.** Polygon Starter provides exchange-grade data licensed directly from exchanges, unlimited API calls, 5 years of historical minute aggregates, WebSocket streaming, and corporate action data — all with proper authentication and documented rate limits. Use yfinance as a free validation/backup layer, not as your production source.

For backtesting specifically, **survivorship bias is a silent portfolio killer**. A momentum strategy study on the Nasdaq 100 showed 46% CAGR with survivorship bias versus 16.4% CAGR without it, and max drawdown jumped from 41% to 83%. Norgate Data Platinum at **$630/year** provides the gold standard: survivorship-bias-free data back to 1990 with historical index constituents and delisting returns.

---

## Which macro series actually predict equity returns

Your 19 FRED series span a wide value range. Academic evidence strongly supports a tiered approach rather than treating all series equally.

**Tier 1 — proven leading indicators with robust academic evidence:**

The **ICE BofA High Yield OAS** is the single most valuable macro predictor in your collection. Faust, Gilchrist, Wright, and Zakrajšek (2013) used Bayesian Model Averaging across 135 predictors and found that removing credit spreads collapsed forecasting accuracy to baseline levels. The excess bond premium component predicts "significant declines in economic activity and equity prices," with HY OAS widening by 100+ basis points serving as a reliable risk-off signal that typically leads equity drawdowns by 1–3 months. The **NFCI** ranks second — constructed from 105 indicators, updated weekly, and shown by Brave and Kelley (2020) to predict substantial increases in stock market volatility when large positive revisions occur. **Initial jobless claims** provide the most timely labor market signal (weekly release) and historically signal equity weakness when the rate of change exceeds 20% from trough.

**Tier 2 — valuable regime signals:** The 2Y/10Y spread is a classic recession indicator (6 of 7 inversions preceded NBER recessions since 1976) but with highly variable lead times of 6–24 months, making it useful for portfolio regime allocation but not trade timing. Breakeven inflation rates are better for sector rotation than direct equity prediction.

**Tier 3 — context indicators with less direct alpha:** The remaining series (industrial production, capacity utilization, consumer sentiment) tend to be coincident or lagging indicators that confirm rather than predict equity movements.

**Critical implementation note:** FRED displays the latest revised data by default, creating look-ahead bias in backtesting. GDP Q1 2014 was first reported at 17,149.6, then revised to 17,101.3, then to 17,016.0 — a 0.8% swing. Use **ALFRED (ArchivaL FRED)** via the fredapi Python package's `get_series_as_of_date()` method to access point-in-time vintage data.

---

## Google Trends: the alpha has inverted

The Da, Engelberg, and Gao (2011) finding — that increased Google search volume predicts higher stock prices over two weeks followed by reversal — has not survived out-of-sample for your universe. Bijl, Kringhaug, Molnár, and Sandvik (2016) used 2008–2013 data and found that high search volumes now predict **negative returns** for S&P 500 stocks, a complete inversion of the original signal. The effect was unprofitable after transaction costs. A Lund University thesis examining S&P 100 stocks from 2016–2021 found mixed-to-null results, consistent with the original paper's own caveat that the effect was strongest in smaller, hard-to-arbitrage stocks.

**Recommendation: stop collecting per-ticker Google Trends for S&P 100.** The effort-to-value ratio is unfavorable. If you want a Google-derived signal, the aggregate **FEARS index** approach (30 negative economic keywords like "recession" and "stock market crash") retains documented predictive power for market-level volatility per Da, Engelberg, and Gao's 2015 follow-up in the Review of Financial Studies. This is a single daily collection rather than 100+ ticker-level queries.

---

## Priority-ranked data sources to add now

The following ranking balances compound value (how much more valuable 12+ months of history is versus 1 month), cost, implementation effort, and cross-desk utility.

| Priority | Source | Cost | Impl. Hours | Compound Value | Desks Served |
|----------|--------|------|-------------|----------------|--------------|
| 1 | **Polygon.io Starter** | $29/mo | 4–6 | ★★★★☆ | All 5 desks |
| 2 | **SEC EDGAR (Form 4 + filings)** | $0 | 15–25 | ★★★★★ | 1, 2, 4 |
| 3 | **FINRA short interest** | $0 | 4–6 | ★★★★☆ | 1, 2, 4 |
| 4 | **FRED via ALFRED vintages** | $0 | 3–5 | ★★★★☆ | All desks |
| 5 | **Tiingo (free tier backup)** | $0 | 2–3 | ★★★☆☆ | All desks |
| 6 | **Treasury.gov yield curve** | $0 | 2 | ★★★☆☆ | Regime detection |

SEC EDGAR earns the highest compound rating because insider trading cluster signals and 10-K/10-Q textual changes are irreplaceable once accumulated. Cohen, Malloy, and Nguyen's "Lazy Prices" paper found that firms making significant changes to filing language subsequently underperform — a signal requiring years of filing history to compute. The `edgartools` Python library (MIT license, 1,000+ tests) provides structured access to Form 4 insider transactions, XBRL financial data, and full-text filing search.

FINRA short interest is scarce data — only two observations per month — making each data point disproportionately valuable for building historical baselines. Rapach et al.'s aggregate short interest index produced out-of-sample R² of **13.24% annually** for equity risk premium prediction, far exceeding any other single predictor in the literature.

**Total Phase 1 cost: $29/month.** All other recommended additions are free.

---

## Specific data source recommendations

**ADD NOW:**
- **Polygon.io Starter ($29/mo):** Exchange-grade OHLCV, 5 years of minute aggregates, unlimited API calls, WebSocket streaming, corporate actions. Replaces yfinance as primary source. Upgrade to Developer ($79/mo) when you need 10+ years of history for crisis-period backtesting.
- **SEC EDGAR ($0):** Form 4 insider clusters, 10-K/10-Q text for NLP, 8-K event detection. Use `edgartools` library. High implementation effort (15–25 hours) but permanent infrastructure.
- **FINRA Short Interest ($0):** Bi-monthly short interest via `api.finra.org`. Supplement with daily short volume ratios for higher-frequency signals.
- **Tiingo Free Tier ($0):** 30+ years of clean EOD data from 3 exchanges with proprietary error checking. Serves as yfinance validation/backup. Limited to 500 symbols/month on free tier.
- **Alpha Vantage Free ($0):** 50+ pre-computed technical indicators. Limited to 25 requests/day — useful only as a supplementary calculation tool, not a primary data source.

**ADD AT DESK LAUNCH:**
- **ORATS ($99–399/mo):** Essential for Desk 3. Provides SMV Greeks, IV surface, 500+ volatility indicators, earnings history. No substitute exists at any lower price point. Start collecting when the options desk is 3–6 months from launch to build historical IV surface data.
- **Unusual Whales (~$48/mo):** Options flow, dark pool data (15-minute delayed), congressional trading, Greek exposure. Valuable for Desk 3 but not before it's active. Note: API pricing increased $25–50 per tier in May 2025.
- **NYSE Market Internals ($0–49/mo):** TICK, TRIN, advance/decline via Interactive Brokers TWS API (free with account) or Polygon NYSE Order Imbalances add-on ($49/mo). Needed for Desks 4 and 5.
- **Alpaca or Polygon Advanced ($99–199/mo):** Real-time streaming for Desk 5 intraday. Alpaca bundles execution + data; Polygon is data-only but broader.

**SKIP:**
- **Social sentiment (Reddit/StockTwits):** Reddit API is locked for commercial use ($12K+/year), StockTwits registration is closed. Academic evidence shows retail sentiment is mostly noise for S&P 100 large caps. WSB attention "spurs uninformed trading" and "significantly reduces holding period returns."
- **Google Trends per-ticker:** Signal inverted for large caps. Replace with aggregate fear keyword monitoring if desired.
- **Treasury.gov yield curve:** Redundant with FRED, which provides the same H.15 data via a superior API.

---

## Storage projections and infrastructure path

| Data Type | Annual Rows | Annual Storage | 5-Year Total |
|-----------|------------|----------------|--------------|
| Daily OHLCV (325 stocks) | 81,900 | ~16 MB | ~80 MB |
| Options chains, S&P 100 EOD | ~12M | ~3.3 GB | ~16.5 GB |
| Options chains, SPX/XSP EOD | ~4–5M | ~1.3 GB | ~6.5 GB |
| 1-minute bars, S&P 100 | ~9.8M | ~1 GB | ~5 GB |
| VIX/CBOE/Macro/Trends | ~100K | <10 MB | <50 MB |
| **Total (no tick data)** | **~27M** | **~5.7 GB** | **~28 GB** |
| Tick data, S&P 100 (reference) | ~500M–1.25B | ~20–50 GB | ~100–250 GB |

At **28 GB over 5 years** (excluding tick data), SQLite remains the right choice today. SQLite handles databases up to 50 GB with proper indexing and works well for your pattern: single-writer nightly batch ingestion + single-user analytical reads. The bottleneck arrives when you need **concurrent writes** (e.g., live intraday collection while running backtests simultaneously) or when the database exceeds ~50 GB.

**Recommended migration path:**
- **Now through ~30 GB:** SQLite for storage, **DuckDB for analytics**. DuckDB is the critical addition — it's an embedded columnar database that runs analytical queries 5–10× faster than SQLite, uses all CPU cores (unlike SQLite's single-threaded execution), and reads Parquet files natively. Use SQLite for ingestion/storage, export to Parquet, and query with DuckDB for feature engineering.
- **30–100 GB or multi-user:** Migrate to PostgreSQL for storage while keeping DuckDB for analytics.
- **100+ GB (tick data era):** TimescaleDB (PostgreSQL extension) for tick/intraday with continuous aggregates that auto-compute 1-minute bars from ticks.

---

## Feature data versus label data: preventing the leakage that kills backtests

The distinction between features (model inputs at inference) and labels (outcome variables for training only) is where most financial ML projects fail silently. López de Prado's framework provides the canonical approach.

**Features (what the model sees at inference):** Distance from moving averages, RSI, ATR-normalized pullback depth, support level proximity, expanding-window IV rank, VIX term structure slope, put/call ratio, NFCI level, HY OAS level, short interest ratio, sector relative strength. Every feature must pass the point-in-time test: at timestamp t, the value must be computable using only data available before t.

**Labels (outcome variables, never seen by the model):** Use the **triple-barrier method** rather than naive fixed-horizon returns. Set three barriers — take-profit (e.g., +3% or 2–3 ATR), stop-loss (e.g., –2% or 1–2 ATR), and time-limit (e.g., 15 days). Label = whichever barrier is hit first. This naturally encodes path dependency and risk management into your training signal, matching your actual mechanical bracket order execution.

**The five leakage risks specific to your system:**

First, **IV rank look-ahead bias**. Computing IV rank as (current IV – 52-week low) / (52-week high – 52-week low) requires that the 52-week extremes use only data available at time t, not the full ex-post series. Use expanding-window computation exclusively.

Second, **FRED data revision leakage**. GDP, nonfarm payrolls, and other macro series undergo significant revisions. Store ALFRED vintage data with `get_series_as_of_date()` and train on first-release values, not final revised figures.

Third, **Google Trends normalization leakage**. Google's index is relative to the maximum in the queried time window — pulling January–June gives different values than pulling January–March separately. Snapshot data at a fixed weekly schedule, store raw downloaded values with the download timestamp, and never re-fetch or overwrite historical values.

Fourth, **cross-validation leakage**. Standard K-fold randomly mixes future and past data, grossly inflating apparent accuracy. Use **purged K-fold cross-validation** with an embargo period (≥5 days) between train and test folds to prevent autocorrelation leakage.

Fifth, **survivorship bias in the training universe**. Store monthly snapshots of S&P 100 and S&P 500 composition so that at any training timestamp, the model only considers stocks that were actually in the index at that time.

| Feature Type | Desk 1–2 (Pullback) | Desk 3 (Options) | Desk 4 (Breakout) |
|---|---|---|---|
| **Price/Technical** | MA distance, RSI, ATR depth | Underlying trend, HV 20/30/60 | Consolidation duration, range width, ATR contraction |
| **Volume** | Pullback volume decline | Options volume/OI ratio | Relative volume (≥1.5× ADV), OBV, CMF |
| **Volatility** | VIX level, term structure | IV rank, IV-HV spread, skew, term slope | VIX context only |
| **Macro** | HY OAS, NFCI, claims | NFCI (predicts VIX spikes) | Regime filter only |
| **Sentiment** | Put/call ratio, insider clusters | Earnings move history | Short interest DTC |
| **Label method** | Triple-barrier: 2–3 ATR target, 1–2 ATR stop, 15-day timeout | Binary: spread expired within X% of max profit vs. breached 50% of max loss | Triple-barrier: 1.5× range target, back-inside-range stop, 10-day timeout |

---

## Monthly cost estimate and implementation timeline

**Immediate additions (Phase 1) — $29/month:**

| Source | Monthly | One-Time | Implementation |
|--------|---------|----------|---------------|
| Polygon.io Starter | $29 | — | Week 1 (4–6 hrs) |
| SEC EDGAR pipeline | $0 | — | Weeks 1–3 (15–25 hrs) |
| FINRA short interest | $0 | — | Week 1 (4–6 hrs) |
| ALFRED vintage macro | $0 | — | Week 2 (3–5 hrs) |
| Tiingo free backup | $0 | — | Week 1 (2–3 hrs) |
| DuckDB analytics layer | $0 | — | Week 2 (4–6 hrs) |
| **Phase 1 total** | **$29** | **$0** | **~35–50 hrs** |

**Desk 3 launch additions — $150–450/month:**

| Source | Monthly | One-Time |
|--------|---------|----------|
| ORATS (delayed or live API) | $99–199 | $1,500 (historical) |
| Unusual Whales | $48 | — |
| **Desk 3 total** | **$147–247** | **$1,500** |

**Desk 4–5 launch additions — $100–250/month:**

| Source | Monthly | One-Time |
|--------|---------|----------|
| Polygon upgrade to Advanced | +$170 (to $199 total) | — |
| NYSE order imbalances | $49 | — |
| Alpaca Algo Trader Plus (Desk 5) | $99 | — |
| Historical 1-min data | — | $200–500 |
| **Desk 4–5 total** | **$148–248** | **$200–500** |

**Full 5-desk steady-state: approximately $325–525/month** ($3,900–6,300/year) plus ~$2,000 in one-time historical data purchases. This is institutional-quality data infrastructure at a fraction of Bloomberg Terminal pricing ($24,000/year) and provides everything needed to train, validate, and operate all five desks.

## What to do this week

Stop relying on yfinance as your sole OHLCV source — the February 2025 outage broke most versions for days. Sign up for Polygon Starter today, point your nightly ingestion at their API, and keep yfinance as a free validation layer. Begin the SEC EDGAR pipeline with `edgartools` (pip install, start collecting Form 4 insider transactions nightly). Add FINRA short interest collection on the bi-monthly schedule. Switch your FRED pipeline to ALFRED vintage mode. And seriously consider dropping per-ticker Google Trends — the engineering time freed up is better spent on these higher-value sources. Every day of SEC insider data and short interest data you collect now is a day of irreplaceable training signal for Desks 2–4 when they launch.
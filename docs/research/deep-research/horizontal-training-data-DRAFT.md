# Deep Research Prompt: Maximizing Horizontal Feature Density in LLM Training Data for Autonomous Equity Trading

---

## Context for the Researcher

I am building **Arcis** (repo: halcyon-lab), a solo-operated autonomous AI-powered equity trading system targeting **S&P 100 stocks** with a **pullback-in-uptrend strategy** and **2–15 day holding periods**. The core LLM is **Qwen3 8B fine-tuned via QLoRA** running locally on an RTX 3060 12GB (upgrading to 3090 24GB). Each training example is a structured XML-tagged input packaging multiple data dimensions about a single stock-day, paired with an XML-tagged analytical trade thesis output. The system trades via Alpaca bracket orders.

My thesis — supported by Trading-R1's empirical results (Sharpe 2.72, 70% hit rate on Qwen3-4B) — is that **horizontal feature density per training example matters more than raw example count**. A training example with 12 orthogonal signal dimensions (technical + fundamental + news + insider + macro + options + sentiment + sector + regime + attention + supply chain + earnings context) teaches the model richer contextual reasoning than 10x more examples with only 3 dimensions each. The moat is in the **combinatorial fusion** — a system that reasons across "IV skew is steep AND insider buying increased AND macro regime shifted AND Google attention is spiking" creates synthesis no single-signal strategy can replicate. Each additional well-chosen signal dimension multiplies the combinatorial pattern space exponentially.

**Budget constraint:** $0–150/month for data, scaling with proven profitability. Currently Phase 1 (paper trading, 13 closed trades (12W/1L, 92% WR, $860 P&L), 26% through 50-trade gate).

---

## Current Data Sources (What I'm Collecting Today)

### Currently Active APIs & Data Feeds

| # | Source | Data Provided | Cost | Status |
|---|--------|--------------|------|--------|
| 1 | **yfinance** | Daily OHLCV price data for S&P 100 | Free | Active — primary price feed |
| 2 | **Finnhub** (free tier, 60 calls/min) | Earnings transcripts, analyst recommendations, insider trades, company news, social sentiment endpoint, congressional trades | Free | Active — multiple endpoints in use |
| 3 | **SEC EDGAR** (data.sec.gov, 10 req/sec) | 10-K, 10-Q, 8-K filings; XBRL structured financials; Form 3/4/5 insider transactions; bulk data downloads | Free | Active — fundamentals pipeline |
| 4 | **FRED API** (120 req/min) | Macro data: Fed Funds Rate, yield curves, VIX, unemployment, CPI, GDP | Free | Active — macro regime context |
| 5 | **Alpha Vantage** (free tier, 500 calls/day) | Supplementary price data, fundamentals, technical indicators | Free | Active — supplementary |
| 6 | **FMP** (free tier, 250 req/day) | Analyst estimates, financial statements, earnings calendars | Free | Active — supplementary |
| 7 | **Alpaca** (paper + live) | Order execution, account data, position management | Free (paper) | Active — execution layer |
| 8 | **Claude API** (Haiku 4.5) | Training data generation via teacher-student distillation | ~$2/mo | Active — synthetic data pipeline |
| 9 | **Google Trends** | 8 market sentiment terms (crash, recession, inflation, etc.) | Free | Active — overnight collector |

### Current Training Example Structure (7 XML-tagged input sections)

Each training example currently packages these dimensions per stock-day:

1. **Technical Indicators** — Trend state, RSI(14), MACD, ATR(14), volume ratio, relative strength vs SPY, pullback depth (Fibonacci levels), support/resistance levels, moving averages
2. **Market Regime** — VIX level/regime (Normal/Elevated/Crisis), yield curve shape, broad market trend, sector rotation state
3. **Sector Context** — Sector relative performance, sector momentum, peer comparison
4. **SEC EDGAR Fundamentals** — Latest 10-Q/10-K excerpts, revenue/earnings trends, margins, guidance
5. **Finnhub Insider Trading** — Recent Form 4 transactions, net insider sentiment, cluster buying/selling
6. **Finnhub News Headlines** — Recent news with temporal bucketing (3-day, 10-day windows), sentiment
7. **FRED Macro Indicators** — Fed Funds Rate, yield spreads, unemployment trend, inflation data

### Planned Additions (Confirmed by Prior Research, Not Yet Built)

- **Options flow** (Unusual Whales, ~$50/mo) — IV rank, IV spread/skew, sweep activity, net premium flow → 8th section
- **Attention/Sentiment** (Google Trends + Finnhub social_sentiment) — Retail attention spikes, contrarian signals → 9th section
- **Enhanced FRED** — NY Fed GSCPI (supply chain pressure), ISRATIO (inventory-to-sales), ISM PMI/NAPMSDEL (supplier deliveries)
- **FMP consensus snapshots** — Building proprietary earnings revision momentum dataset over time

This would bring the structure to **9 input sections**. The question is: **what else should I add to maximize the horizontal dimensionality of each training example?**

---

## The Research Question

**For an autonomous LLM-based equity trading system targeting S&P 100 stocks with 2–15 day holding periods and a pullback-in-uptrend strategy, what additional data sources and feature dimensions should be integrated into each training example to maximize the horizontal signal density — the number of orthogonal (non-redundant) information dimensions per row — while respecting temporal compliance (no lookahead bias) and budget constraints?**

### Specific Sub-Questions

#### 1. Comprehensive Signal Taxonomy
Produce a complete taxonomy of every data dimension that could plausibly inform a 2–15 day equity swing trade on S&P 100 stocks. Organize by category (technical, fundamental, sentiment, flow, macro, behavioral, structural, cross-asset, etc.). For each dimension, specify:
- What it measures and why it matters for this holding period
- Academic evidence for predictive power (cite specific papers, journals, effect sizes, and whether the effect survives for large-cap stocks specifically)
- Temporal resolution (real-time, daily, weekly, monthly, quarterly) and whether it's actionable within a 2–15 day window
- Estimated signal decay — has the anomaly been published and arbitraged away? (Reference McLean & Pontiff 2015: anomalies decline 58% post-publication)
- Redundancy with existing signals — is this genuinely orthogonal or just a rephrasing of something already captured?

#### 2. Free Tier Recommendations ($0/month)
What additional free APIs, government data sources, HuggingFace datasets, open-source tools, or scrapeable public data should I integrate? For each:
- Exact API endpoint or data source URL
- Rate limits and access requirements
- What XML-tagged training input section it maps to (new section or enrichment of existing)
- Specific feature format recommendation (how to structure it for LLM consumption in 300–1,000 token training examples)
- Expected marginal information gain — does this dimension add something genuinely new, or is it noise for S&P 100 large caps?
- Engineering effort estimate (trivial/moderate/significant)

Consider categories I may be underutilizing:
- **Cross-asset signals** (bonds, commodities, FX, crypto correlations as regime indicators)
- **Market microstructure** (bid-ask spreads, order book depth, short interest, fails-to-deliver)
- **Earnings-adjacent** (earnings whisper numbers, guidance revision tracking, estimate dispersion)
- **Corporate actions** (buyback announcements, dividend changes, share issuance, M&A activity)
- **ETF flow data** (sector ETF creation/redemption as institutional positioning proxy)
- **Seasonality/calendar** (day-of-week, month, options expiration proximity, FOMC meeting proximity, earnings season density)
- **Volatility surface** (VIX term structure, VVIX, skew indices, variance risk premium)
- **Credit markets** (HY OAS, IG spreads, CDS implied default rates as leading indicators)
- **Positioning data** (CFTC COT reports, futures positioning, put/call open interest ratios)
- **Fund flows** (mutual fund flows, ETF flows as sentiment proxies)

#### 3. Paid Tier Recommendations ($50–150/month)
Beyond Unusual Whales (already planned), what paid data subscriptions offer the highest marginal signal density per dollar? For each:
- Exact product, pricing tier, and what you get
- Academic or practitioner evidence for the signal's value
- Whether the signal is available cheaper elsewhere (many paid APIs repackage free government data)
- How it interacts with existing signals — does it amplify or merely duplicate?
- Break-even analysis: roughly how many basis points per trade would this need to add to justify the cost at current trading frequency?

#### 4. "Most Valuable" Tier (Aspirational, $150–500/month)
If budget were less constrained — say after the system proves profitability and scales to $50K+ AUM — what data sources would provide the highest absolute signal value regardless of cost? This is the "dream stack" that I build toward. For each:
- What it provides that nothing cheaper can approximate
- Why it's worth the premium specifically for S&P 100 / 2–15 day trades
- Whether there are partial free proxies that capture some of the signal

#### 5. Anti-Recommendations: What NOT to Add
Equally important: what popular data sources would actually **hurt** training data quality or add noise for this specific use case? The alternative data research shows that most marketed signals fail the S&P 100 feasibility test. Be explicit about:
- Signals that work for small-caps but not large-caps (and why)
- Signals with the wrong time horizon (too fast for 2-day minimum, too slow for 15-day maximum)
- Signals where the free version is so delayed it's worthless
- Signals that are redundant with something already in the stack
- Signals with high engineering cost but low marginal information gain

#### 6. Optimal Training Example Architecture
Given the full recommended signal set, propose the updated XML-tagged input structure. How many sections should a maximally-featured training example have? What's the tension between horizontal feature density and the 300–1,000 token sweet spot for QLoRA training? How do you prioritize when you can't fit everything?

Specifically address:
- Which signals should be **always present** vs. **conditionally included** (only when they're informationally interesting, e.g., unusual options activity only when there IS unusual activity)
- How to handle signals with different temporal resolutions (daily technical data mixed with quarterly fundamental data mixed with monthly macro data)
- The risk of **feature bloat** — at what point does adding another dimension start hurting model performance by diluting signal-to-noise in the training input?
- Trading-R1's approach of **random source subsetting** (20 variations per date-ticker by randomly including/excluding data sources) — should I adopt this, and how does it interact with horizontal density goals?

#### 7. Signal Orthogonality Analysis
Provide a correlation/redundancy matrix for the recommended signals. Which signals are genuinely independent information dimensions vs. which are correlated proxies for the same underlying factor? Use eigenvalue analysis logic: I want to maximize the number of independent eigenvectors (true signal dimensions) rather than padding with correlated features that add apparent but not real complexity.

### Output Format Requested

Structure the response as:

1. **Complete Signal Taxonomy Table** — Every plausible dimension with evidence assessment
2. **Free Tier Stack** ($0/mo) — Ranked by expected marginal value, with implementation details
3. **Paid Tier Stack** ($50–150/mo) — Ranked by information-per-dollar
4. **Most Valuable Stack** ($150–500/mo) — Aspirational targets
5. **Anti-Recommendation List** — What to skip and why
6. **Updated Training Example Architecture** — Full XML schema with all recommended sections
7. **Orthogonality Matrix** — Which signals are truly independent
8. **Implementation Roadmap** — Sequenced by effort vs. value, aligned with Phase 1→2→3 gates

### Key Constraints to Respect

- **S&P 100 universe only** — many alternative data signals work for small/mid caps but not mega-caps with 25–40 analyst coverage and deep institutional ownership
- **2–15 day holding period** — monthly/quarterly signals only matter as context, not as timing triggers
- **Pullback-in-uptrend strategy** — the model is looking for healthy retracements in confirmed uptrends, not mean reversion, momentum, or event-driven setups (though context from these frameworks enriches analysis)
- **No lookahead bias** — every data point must have a verifiable timestamp proving availability before trade entry
- **300–1,000 tokens per training example** — aggressive condensation required; raw data must be pre-processed into information-dense natural language
- **Qwen3 8B on 12GB VRAM** — the model can't process 50K-token inputs; features must be distilled
- **Solo operator** — engineering effort matters; prioritize APIs with clean JSON responses and Python libraries over scraping projects requiring ongoing maintenance
- **The moat is combinatorial fusion** — adding a 10th orthogonal dimension is worth more than doubling the depth of an existing dimension, because it multiplies the pattern space the model can reason over

### Reference Points

The researcher should be familiar with or consult:
- **Trading-R1** (Tauric Research, arxiv:2509.11420, 2025) — 5 data source categories, 20–30K tokens per example, Qwen3-4B, Sharpe 2.72
- **McLean & Pontiff (2015)** — Post-publication anomaly decay of 58%
- **Pan & Poteshman (2006)** — Options-implied directional signals (RFS)
- **Cremers & Weinbaum (2010)** — IV spread predicting returns (JFQA)
- **Da, Engelberg & Gao (2011)** — Google Trends as attention proxy (JF)
- **Grossman-Stiglitz (1980)** — Information cost ≈ information value equilibrium
- **Martineau (2022)** — PEAD death for large caps (Critical Finance Review)
- **Cookson et al. (2024)** — Social media sentiment assessment (JFE)
- **Cohen & Frazzini (2008)** — Customer-supplier momentum (JF)
- **Bakshi, Panayotov & Skoulakis (2011)** — Supply chain as macro indicator
- **Fin-o1 (EMNLP 2025)** — GRPO with FinCoT for financial reasoning
- **LIMA (Zhou et al., 2023)** — Quality over quantity in fine-tuning
- **Diether, Malloy & Scherbina (2002)** — Analyst dispersion and returns

---

*The goal is to produce the most information-dense training examples in the financial LLM space — where every row is a rich, multi-dimensional snapshot that teaches the model to synthesize across signal types the way the best human portfolio managers do intuitively. The question isn't "what data exists" but "what data, when fused into a single structured training input, creates reasoning capabilities that no single-signal system can match."*

---

## Additional Context from Live System Operation

### What We've Learned So Far (April 2026)

**System operational findings that should inform recommendations:**

1. **Training data quality is the #1 bottleneck, not quantity.** 972 examples with 7 input sections produced a model with 87% parse success rate but 99% conviction parsing failure. The model generates good prose but struggles with structured metadata extraction. Adding more input dimensions must not degrade the model's ability to parse its own output.

2. **The 300–1,000 token constraint is real.** Each training example must be aggressively condensed. The question isn't "should we add X data?" but "what do we REMOVE to make room for X?" Every new section added should specify which existing tokens it displaces and why that's a net positive.

3. **FMP 250/day free tier is the binding API constraint.** Fundamental and earnings revision data compete for the same 250 daily calls. Any new data source recommendation must specify whether it cannibalizes FMP budget or uses a separate endpoint.

4. **The overnight collection pipeline has capacity.** 12 collectors run at 9:30 PM nightly with massive headroom. New data sources that only need daily snapshots are nearly free to add to this pipeline.

5. **Options data collection is already running passively.** Full EOD options chain snapshots (50,202 contracts/day), VIX term structure, CBOE ratios, and options metrics are collected nightly. Any options-related training data section can draw from this existing data — it doesn't need a new API.

6. **Google Trends is already collecting 8 sentiment terms.** crash, recession, inflation, rates, bubble, correction, bear market, stock market crash. Whether this adds signal for S&P 100 mega-caps is the question.

7. **The schema registry (in development) will govern all data tables.** New data sources must be integrated into the central schema registry. Recommend data sources that produce clean, timestamped, ticker-keyed data that maps naturally to SQLite tables.

### Hardware Path (Affects What's Feasible)

- **Now:** RTX 3060 12GB, Qwen3 8B, 300–1,000 token examples
- **Phase 2 (~Q3 2026):** RTX 3090 24GB, Qwen3 14B possible, up to 1,500 token examples
- **Phase 3+:** RTX 4090/5090, potential multi-GPU, 2,000+ token examples

The recommendation should be **staged by hardware tier** — what to add now (300–1K tokens on 12GB) vs. what to add when context window expands.

### The Conviction Parsing Problem

The current model parses conviction from XML metadata at a 1% success rate. Before adding new input dimensions, we may need to simplify or restructure the output format. The research should address: **does adding more input complexity help or hurt output structure compliance?** Trading-R1 uses 20–30K token inputs with a 4B model and gets structured output reliably — what are they doing differently?

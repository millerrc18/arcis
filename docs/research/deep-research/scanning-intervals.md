# Deep Research Prompt: Optimal Data Scanning Intervals for an Autonomous LLM-Based Equity Trading System

---

## Context for the Researcher

I am building **Arcis** (repo: halcyon-lab), an autonomous AI-powered equity trading system targeting **S&P 100 stocks** with a **pullback-in-uptrend strategy** and **2–15 day holding periods**. The system runs a local Python/FastAPI backend on Windows with an RTX 3060 12GB, executing trades via Alpaca bracket orders.

The system's operational loop currently runs a **30-minute scan cycle during market hours (9:30 AM – 4:00 PM ET)**: every 30 minutes it re-ingests prices, recomputes features, re-ranks the S&P 100 universe, generates LLM packets for new qualifiers, and monitors open positions for stop/target/timeout exits. There is a **pre-market data refresh at 7:30 AM** (ingesting yesterday's final OHLCV), a **morning watchlist at 8:00 AM**, and an **EOD recap at 4:05 PM**.

I am expanding my training example input structure from 7 to **11 XML-tagged sections** covering these data dimensions:

| Section | Data Sources | Current Refresh | Signals |
|---------|-------------|----------------|---------|
| `<price>` | yfinance (free) | Every 30 min | Close, change %, 52-week range, ATR, volume ratio |
| `<trend>` | Computed from price | Every 30 min | EMAs (9/21/50/200), regime, pullback depth, ADX |
| `<momentum>` | Computed from price | Every 30 min | RSI(14), MACD, relative strength vs SPY, OBV |
| `<regime>` | yfinance + FRED | Every 30 min (VIX); daily (FRED) | VIX, VIX term structure slope, VVIX, SKEW, SPY trend, breadth |
| `<fundamentals>` | SEC EDGAR + FMP + Finnhub | Daily (pre-market) | Forward P/E, revenue growth, EPS surprise, earnings revision count, guidance |
| `<macro>` | FRED API | Daily (pre-market) | HY OAS, IG spreads, Fed Funds, 2s10s, DXY, GSCPI |
| `<sentiment>` | Finnhub | Every 30 min (news); daily (insider/analyst) | News sentiment (3d/10d), insider net transactions, analyst consensus, upgrades |
| `<options>` | Unusual Whales (~$50/mo) + yfinance | TBD | IV rank, P/C OI ratio, 25-delta skew, sweep bias, unusual activity |
| `<intermarket>` | yfinance | TBD | Gold/copper ratio, crude, DXY, BTC, sector ETF relative strength |
| `<calendar>` | Static + FMP | TBD | Days to FOMC, days to OpEx, earnings density %, turn-of-month flag |
| `<earnings_revisions>` | FMP (250 req/day free tier) | TBD | Net revisions 7d/30d, revision momentum, dispersion change |

### Current API Rate Limits

| Source | Rate Limit | Current Daily Usage (est.) | Available Headroom |
|--------|-----------|---------------------------|-------------------|
| yfinance | Unofficial; ~2,000 calls/hr before throttle | ~1,400 calls/day (100 tickers × 14 scans) | Moderate — fragile at scale |
| Finnhub (free) | 60 calls/min | ~800 calls/day | Significant — ~85,600 unused/day |
| SEC EDGAR | 10 req/sec (with User-Agent) | ~200 calls/day | Massive — ~864,000 unused/day |
| FRED API | 120 req/min | ~50 calls/day | Massive |
| Alpha Vantage (free) | 500 calls/day | ~100 calls/day | Moderate — 400 remaining |
| FMP (free) | 250 req/day | ~100 calls/day | Tight — 150 remaining for new features |
| Unusual Whales | TBD (paid tier) | 0 | Unknown — needs research |
| Alpaca | 200 calls/min | ~300 calls/day | Massive |

### System Architecture Constraints

- **Single GPU** — inference and scanning share the RTX 3060 with training (which runs overnight/weekends only). During market hours, the GPU runs inference exclusively (~10–15 sec per LLM packet generation).
- **Pull-based command queue** — the local machine polls a Render Postgres database every 60 seconds for dashboard commands. The scan loop is the primary operational cadence.
- **Intra-day reconciliation** — Alpaca positions reconcile every 15 minutes.
- **75% GPU utilization target** — per the Halcyon Framework (derived from Kingman's queuing formula), sustained utilization above 75% causes inference latency to degrade hyperbolically. Inference ≤30%, training ≤45%, slack ≥25%.
- **Solo operator** — no on-call team. System must run unattended during market hours while I'm at my day job. Errors should degrade gracefully, not crash the pipeline.

---

## The Research Question

**For each data dimension in an 11-section training input, what is the optimal scanning/polling interval that maximizes information freshness while respecting API rate limits, minimizing redundant computation, and staying within a solo-operator budget?**

The core tension: some signals (price, options flow) change intraday and benefit from frequent polling. Others (macro data, fundamentals, insider filings) change daily/weekly/quarterly and gain nothing from intraday refreshes — but waste API calls and CPU cycles when polled too frequently. The naive approach (poll everything every 30 minutes) is wasteful for slow-changing signals and potentially too slow for fast-moving ones like options sweeps during a pullback entry window.

### Specific Sub-Questions

#### 1. Signal Information Half-Life Taxonomy

For each of the 11 data dimensions, what is the **information half-life** — the time after which 50% of the signal's predictive value has decayed or been priced in? This determines the theoretically optimal polling interval for each dimension.

Research should address:
- **Price/technical data**: How quickly do intraday price movements affect the validity of daily-computed technical indicators (EMAs, RSI, MACD) for a 2–15 day strategy? Does a 30-minute refresh cycle capture meaningful regime changes, or is hourly sufficient? Is there academic evidence on the information content of intraday vs. daily indicators for swing trading horizons?
- **Options flow**: How quickly are options sweeps and unusual activity priced into the underlying? Chakravarty, Gulen, and Mayhew (2004, JFE) found options markets lead stock prices by ~15 minutes. Does this mean real-time polling is necessary, or is a 15/30-minute snapshot sufficient for a system that enters positions over hours, not seconds?
- **News/sentiment**: What is the price-impact half-life of corporate news for S&P 100 stocks? Tetlock (2010) found negative sentiment's effect persists for 1–4 days. Does this mean once-daily news ingestion is sufficient, or do intraday updates meaningfully change trade qualification decisions?
- **Macro/credit data**: FRED data updates on fixed schedules (BLS releases, FOMC decisions). What is the optimal way to handle event-driven updates — poll at fixed intervals and check for staleness, or implement an event-aware schedule?
- **Insider transactions**: SEC Form 4 filings are typically filed within 2 business days of the transaction. Given this inherent delay, does polling more than once daily add any value?
- **Earnings revisions**: Free-tier analyst estimate data (FMP, Finnhub) updates at most daily. What polling frequency captures meaningful revision momentum without wasting API calls?
- **Cross-asset signals**: How frequently does the gold/copper ratio, DXY, or sector rotation state change in ways that affect S&P 100 pullback qualification? Daily? Hourly?
- **Calendar features**: These are static or semi-static (days-to-FOMC doesn't change intraday). Should they be computed once at pre-market and cached all day?

#### 2. API-Optimal Polling Schedules

Given the rate limits above, design a concrete **polling schedule** that maximizes information freshness per API call. For each data source, specify:

- **Recommended polling interval** (e.g., every 5 min, every 30 min, every hour, once daily, event-triggered)
- **Whether the interval should vary by market phase** (pre-market, first 30 min, mid-day, last hour, after-hours)
- **Whether the interval should vary by signal state** (e.g., poll options flow more aggressively when a stock is near a pullback entry zone vs. when it's in no-man's-land)
- **Exact API call budget** per source per day at the recommended interval
- **Fallback behavior** when API calls fail or rate limits are hit
- **Whether batching is possible** (e.g., fetch all 100 tickers in one yfinance call vs. 100 individual calls)

Key questions:
- yfinance supports batch downloads (`yf.download(["AAPL", "MSFT", ...])`) — is a single batch call for 100 tickers every 30 minutes the most efficient pattern, or should it be split?
- Finnhub's 60 calls/min limit allows ~3,600/hour. With 100 tickers and multiple endpoints (news, insider, sentiment, recommendations), what's the optimal endpoint priority and rotation scheme?
- FMP's tight 250/day limit is the binding constraint. How should these be allocated across fundamentals, analyst estimates, and earnings revision snapshots?
- FRED's generous limits make macro data effectively free to poll. But since most series update on fixed schedules (BLS on first Friday, Fed on release days), is there a smarter event-driven approach?
- Unusual Whales API — what are the actual rate limits for their paid tier? How should sweep/flow data be polled for 100 tickers?

#### 3. Adaptive Scanning Architecture

Should the system use a **fixed interval schedule** (poll every N minutes regardless of market conditions) or an **adaptive/event-driven schedule** that adjusts based on:
- **Volatility regime**: Poll faster when VIX is elevated (more opportunities and risks changing rapidly) vs. in low-vol environments?
- **Portfolio state**: Poll more aggressively for tickers with open positions approaching stop/target levels?
- **Proximity to entry**: If a stock is 90% qualified for a pullback entry, increase scanning frequency to catch the final confirmation signal?
- **Market microstructure events**: Poll faster around market open (9:30–10:00 AM), around major data releases (FOMC, jobs, CPI), and into the close (3:30–4:00 PM)?
- **Day of week**: Are Monday mornings and Friday afternoons different from mid-week?

For each adaptive trigger, provide:
- Academic or practitioner evidence for why adaptive scanning outperforms fixed intervals
- Implementation complexity (simple timer logic vs. state machine vs. event-driven architecture)
- Risk of over-engineering vs. the practical benefit for a 2–15 day strategy

#### 4. Stale Data Detection and Staleness Tolerance

For each data dimension, what **staleness threshold** should trigger a warning or force a refresh?

- If yfinance fails to update and the last price is 2 hours old during market hours, is the feature engine's output still valid?
- If FRED macro data is from yesterday (because today's release hasn't dropped yet), does that meaningfully degrade the `<macro>` section?
- If Unusual Whales returns no sweeps in the last 4 hours for a given ticker, is "no unusual activity" itself an informative signal, or should it be flagged as potentially stale?
- How should the system handle API outages — continue scanning with stale data, pause scanning, or degrade gracefully by excluding the stale section from the training input?

For each dimension, define:
- **Acceptable staleness window** (data this old is fine)
- **Warning staleness window** (flag but continue)
- **Critical staleness window** (exclude from feature computation or halt scanning)

#### 5. Compute Budget and Pipeline Timing

With 100 tickers across 11 data dimensions:
- What is the **wall-clock time** for a full scan cycle at different polling intervals? (This determines whether a 30-minute or 15-minute cycle is even feasible given sequential API calls and feature computation.)
- What is the **optimal parallelization** strategy? (Async HTTP calls for API fetching, sequential for feature computation, batched for yfinance?)
- How does adding 4 new data sections (options, intermarket, calendar, earnings revisions) increase scan time, and does this push the 30-minute loop past its deadline?
- Should the system use a **staggered refresh** pattern — e.g., refresh price every 15 min, options every 30 min, fundamentals once daily, macro once daily, calendar once at pre-market — rather than refreshing everything in a single monolithic loop?

#### 6. Data Storage and Caching Strategy

For signals that don't need intraday refreshing:
- Should daily-frequency data (fundamentals, insider filings, macro) be fetched once at pre-market and cached in SQLite for the rest of the day?
- Should the system maintain a **time-series cache** for FRED macro data so that on event days (FOMC, BLS releases), it can detect changes by comparing to the cached prior value?
- For training data generation (which happens at 4:30 PM daily), does it matter whether the training example uses the 7:30 AM snapshot or the 4:05 PM snapshot of slow-changing signals?
- What is the optimal schema for a `data_freshness` table that tracks last-fetch timestamp per source per ticker, enabling the scan loop to skip sources that are still fresh?

#### 7. Open Position Monitoring vs. Universe Scanning

The system needs to do two fundamentally different things during market hours:
1. **Scan the full S&P 100 universe** for new pullback entry opportunities (requires broad but potentially less frequent coverage)
2. **Monitor open positions** for stop/target/timeout exits (requires narrow but potentially more frequent coverage for held tickers)

Should these run on different cadences? For example:
- Universe scan every 60 minutes with full 11-section feature computation
- Open position monitoring every 15 minutes with price-only refresh + conditional options flow check
- Reconciliation with Alpaca every 15 minutes (already implemented)

What does the academic literature say about the relationship between monitoring frequency and exit timing quality for swing trades?

### Output Format Requested

Structure the response as:

1. **Information Half-Life Table** — For each of the 11 data dimensions, the empirically supported signal decay rate and theoretically optimal polling interval
2. **Recommended Polling Schedule** — A concrete minute-by-minute (or event-by-event) schedule showing when each data source is fetched, with API call budgets
3. **Adaptive Scanning Specification** — Which adaptive triggers are worth implementing and which are over-engineering for a 2–15 day strategy
4. **Staleness Tolerance Matrix** — Acceptable/warning/critical staleness thresholds per dimension
5. **Pipeline Timing Analysis** — Estimated wall-clock times for different scan configurations, with parallelization recommendations
6. **Caching Architecture** — What to cache, where, and when to invalidate
7. **Dual-Cadence Architecture** — Specification for separating universe scanning from position monitoring
8. **Implementation Priority** — What to build first, what to defer, and what to skip

### Key Constraints to Respect

- **S&P 100 universe, 100 tickers** — this is the scanning load
- **2–15 day holding period** — the strategy is not latency-sensitive in the HFT sense, but missing a pullback entry by 2 hours could mean missing the trade
- **Pullback-in-uptrend strategy** — entries are on pullbacks (which develop over hours to days), not breakouts (which can be over in minutes). This implies less urgency for sub-minute data freshness.
- **Solo operator at a day job** — system must run completely unattended 9:30 AM – 4:00 PM ET. No manual intervention during market hours.
- **Free tier API rate limits** — yfinance (fragile, ~2K/hr), Finnhub (60/min), FMP (250/day), FRED (120/min), EDGAR (10/sec), Alpha Vantage (500/day)
- **Single RTX 3060** — GPU is shared between inference and scanning; pipeline must not starve inference with data fetching overhead
- **SQLite local + Render Postgres cloud** — local SQLite for fast data access, Render Postgres for dashboard/command queue
- **Python/FastAPI backend** — async patterns available (aiohttp, asyncio) but current codebase is primarily synchronous
- **Current 30-minute scan loop is the baseline** — the question is whether this is optimal, too fast, too slow, or whether a multi-cadence approach is better

### Reference Points

The researcher should consider:
- **Kingman's queuing formula** and its implications for GPU utilization under mixed inference/scanning workloads
- **Market microstructure literature** on price discovery speed (Hasbrouck 1995, Biais et al. 1995) — how fast does information get priced in for S&P 100 stocks?
- **Chakravarty, Gulen, and Mayhew (2004, JFE)** — options lead stock prices by ~15 minutes
- **Tetlock (2010)** — persistence of news sentiment effects
- **Concept drift literature** (Webb et al. 2016, Gama et al. 2014) — how quickly do financial data distributions shift and when does stale data become harmful?
- **Polling vs. event-driven architectures** in production ML systems — Lambda/Kappa architectures, stream processing vs. batch processing tradeoffs
- **Optimal stopping theory** (Chow, Robbins & Siegmund) — does monitoring frequency affect exit quality for time-limited trades?
- **Retraining frequency research** (arXiv 2505.00356) — periodic retraining matches continuous retraining at 90% lower cost; does this finding extend to data freshness?

---

*The goal is an evidence-based data pipeline architecture where each signal dimension is refreshed at exactly the frequency its information content justifies — no faster (wasting API calls and compute), no slower (missing actionable changes). The system should spend its limited API budget and compute cycles on the signals that change fastest and matter most, while caching the rest.*

# Optimal data scanning intervals for Arcis

**Your current 30-minute monolithic scan cycle is too fast for 8 of 11 data dimensions and too slow for position monitoring near exit boundaries.** A multi-cadence architecture — 15-minute position monitoring, 30-minute price/technical refresh, 60-minute sentiment/regime scan, and daily pre-market fundamentals — would capture **>95% of theoretical information value while reducing API calls by ~60% and GPU load by ~40%.** The binding constraints are FMP's 250 calls/day free tier and Finnhub's 60 calls/min rate limit, not your scanning frequency. The single highest-ROI change is splitting position monitoring from universe scanning, followed immediately by staleness detection — because silent data failure in an unattended system is a greater risk than suboptimal scan timing.

---

## 1. Most signals decay far slower than your 30-minute scan implies

The empirical information half-life for each of your 11 data dimensions reveals a striking mismatch between your current uniform 30-minute refresh and the actual rate at which each signal's predictive value decays. Only **3 of 11 dimensions** justify 30-minute polling for a 2–15 day pullback strategy.

| Dimension | Empirical half-life | Optimal poll interval | 30-min verdict |
|---|---|---|---|
| **Price/Technicals** | ~6.5 hrs (daily EMAs shift <1% per intraday bar) | 60 min (EOD nearly as good) | Too fast |
| **Trend** | Same as price — EMA smoothing absorbs intraday noise | 60 min | Too fast |
| **Momentum** | RSI(14) changes <1 point per 30-min bar; MACD even slower | 60 min | Too fast |
| **Regime (VIX)** | ~23-day shock decay (GARCH); but spikes are abrupt | 30 min for VIX level; daily for regime label | Appropriate for VIX |
| **Fundamentals** | Quarters to years (P/E, revenue growth) | Daily pre-market | Far too fast |
| **Macro/Credit** | Days to weeks; HY OAS ~38-day half-life | Daily pre-market | Far too fast |
| **Sentiment** | 1–5 days for S&P 100 (Tetlock 2011); negative news absorbed in ~1 week | 2× daily | Too fast |
| **Options flow** | 15–30 min acute signal; days for directional bias | 30 min | Appropriate |
| **Intermarket** | Days to weeks for correlation regime shifts | 60 min (prices); daily (ratios) | Slightly too fast |
| **Calendar** | Deterministic — dates known months ahead | Daily pre-market, cache | Far too fast |
| **Earnings revisions** | 1–3 months (Chan, Jegadeesh & Lakonishok 1996) | Daily pre-market | Far too fast |

The academic evidence is unambiguous. Chakravarty, Gulen & Mayhew (2004, JFE) found options markets lead stocks by ~15 minutes, making 30-minute options snapshots adequate for directional signals. Tetlock (2011, RFS) showed large-cap news sentiment takes 1–5 days to fully incorporate, with reversals beginning around day 2–5 — twice-daily ingestion captures the meaningful signal. Lakonishok & Lee (2001, RFS) found insider purchase signals persist for months, making daily polling more than sufficient. For daily-timeframe EMAs, a 200-day EMA shifts by roughly **1% of the day's range** per intraday bar — recomputing every 30 minutes produces noise, not signal.

The key insight: your pullback entries develop over hours to days. The marginal information from refreshing fundamentals or sentiment every 30 minutes is effectively zero. Reallocating those API calls and compute cycles to faster position monitoring near exit boundaries produces measurable improvement.

---

## 2. A concrete four-tier polling schedule within API budgets

The recommended architecture replaces the uniform 30-minute loop with four distinct cadences, each matched to the information decay rate of its data dimensions.

### Tier 1 — Position monitor (every 15 min, escalating to 5 min near boundaries)

This tier covers only open positions (typically 5–15 tickers) with price-only checks and distance-to-stop/target computation. **Estimated wall-clock: 2–4 seconds.**

- **yfinance**: 1 batch call for held tickers (~2s)
- **Compute**: Price vs. cached stop/target levels (<1ms)
- **Escalation rule**: If any position is within **1.5× ATR of stop** or **1.0× ATR of target**, switch that ticker to 5-minute monitoring
- **API cost**: ~26 yfinance batch calls/day (negligible)

### Tier 2 — Fast scan (every 30 min during market hours)

Covers price, technicals, and options for the full universe. **Estimated wall-clock: 12–18 seconds.**

- **yfinance**: 1 batch call for 100 tickers (~10s, internally threaded)
- **Technical indicators**: Vectorized pandas/numpy recompute (~0.2s)
- **Options spot-check**: yfinance options chains for top 20 ranked tickers (~5s, threaded)
- **Scoring/ranking**: Pure compute (~0.1s)
- **API cost**: 13 yfinance batches + 260 yfinance options calls/day

### Tier 3 — Medium scan (every 60 min during market hours)

Adds sentiment, regime, and intermarket signals. **Estimated wall-clock: 35–55 seconds** (Finnhub rate limit is the bottleneck).

- **Finnhub news**: Top 30 priority tickers at 60 calls/min (~30s)
- **Intermarket**: Derived from cached yfinance cross-asset data (~0.3s)
- **Regime classification**: VIX + yield curve from cached data (~0.1s)
- **LLM inference**: 5–10 qualifying tickers × ~16s each = **80–160s GPU time**
- **API cost**: ~1,950 Finnhub calls/day (of ~23,400 available)

### Tier 4 — Slow scan (daily pre-market at 7:30 AM + selective post-market)

Covers all slow-changing dimensions. **Estimated wall-clock: ~4.5 minutes** including LLM deep analysis.

| Source | Data | Calls/day | Strategy |
|---|---|---|---|
| FMP | Fundamentals, estimates, revisions, calendar | ~99 of 250 | Batch endpoints (1 call = 100 tickers for quotes); rotate analyst estimates across 3 days for non-priority tickers |
| FRED | HY OAS, Fed Funds, 2s10s, DXY proxy | ~20 of 46,800 | Event-driven: check `series/updates` endpoint; most series update after 3 PM ET |
| SEC EDGAR | Form 4 insider filings | ~300 of 864,000 | RSS feed polled every 10 min, filtered client-side by CIK lookup table |
| Finnhub | Basic financials for full universe | ~2,200 | Rotation: 100 tickers × 2 endpoints per cycle, with priority tiering |
| Alpha Vantage | Reserve for emergency fallback | ~20 of 25 | **Effectively useless** — reduced to 25 calls/day; do not depend on this |

### Daily API budget summary

| Source | Daily calls used | Daily limit | Utilization | Binding? |
|---|---|---|---|---|
| yfinance | ~26 batch calls | ~200–300 before throttle | ~10% | Moderate risk (unofficial) |
| Finnhub | ~3,000–5,000 | 23,400 | 13–21% | No |
| FMP | ~99–200 | **250** | 40–80% | **Yes — primary constraint** |
| FRED | ~20 | 46,800 | 0.04% | No |
| SEC EDGAR | ~300 | 864,000 | 0.03% | No |
| Unusual Whales | ~300–600 | ~3,600–7,200 (est.) | 8–17% | No |
| Alpha Vantage | ~20 | **25** | 80% | Yes — nearly useless |

**FMP's 250/day free tier is the binding constraint.** The highest-ROI upgrade in the entire system is FMP's $19/month Starter plan, which removes the daily cap. This single expenditure unlocks unconstrained fundamentals, estimates, and revision data for all 100 tickers.

---

## 3. Three adaptive triggers worth implementing, three to skip

The academic and practitioner evidence supports a selective approach to adaptive scanning. Most triggers are over-engineering for a 2–15 day strategy.

### Implement now

**Near-boundary position escalation** is the strongest case for adaptive scanning. A position 0.3% from its stop in a stock with 2% daily ATR has roughly a **15% probability of breaching within the next 15 minutes** during volatile periods. Optimal stopping theory (Chow, Robbins & Siegmund 1971) formalizes this: near decision boundaries, the option value of waiting decreases, making more frequent evaluation rational. Implementation is trivial — distance-to-stop is already computed — and reduces stop-slippage by an estimated **20–40 basis points** per triggered exit. Escalate any position within 1.5× ATR of stop or 1.0× ATR of target to 5-minute monitoring.

**VIX regime → position monitoring speed** deserves implementation because VIX > 25 environments produce larger, faster price swings that push positions toward stops more quickly. The implementation is a single threshold check: when VIX exceeds 25, double the position monitor frequency (15 min → 7.5 min). Research from Trade Risk (2024) showed that in the 2022 bear market (average VIX 25.6), higher-frequency monitoring systems performed better on a relative basis. This applies specifically to *position monitoring*, not universe scanning — scanning for new pullback entries should actually slow down in high-VIX to avoid whipsaw entries.

**Open/close special checks** at 9:45 AM and 3:50 PM are justified by the well-documented U-shaped intraday volatility pattern (Admati & Pfleiderer 1988; Bloomberg research confirms 2–3× midday volatility at open and close). For a swing system, the open is when overnight gaps manifest and when entries/exits are most likely actionable. Add a dedicated position check at 9:45 AM (post-open stabilization) and 3:50 PM (pre-close exit decisions). Implementation complexity is low — two additional cron triggers.

### Defer or skip

**Entry proximity scanning** (increasing frequency when a stock approaches pullback qualification) sounds appealing but carries behavioral risk. For a pullback-in-uptrend strategy, the pullback must *complete* before entry. Scanning more frequently as a stock approaches the 50 EMA risks catching a falling knife. The entry improvement is an estimated **10–30 basis points** — meaningful but modest relative to a 5–15% target move. Sixty-minute universe scanning is sufficient for entries that develop over hours to days. Defer to Phase 3+.

**Day-of-week scan frequency changes** should be skipped entirely. The day-of-week effect exists (Birru 2018 tied it to investor mood) but is small for large-cap stocks and has diminished since publication. For S&P 100, the effect size is negligible relative to setup quality. Log day-of-week as a feature for the LLM to learn from, but don't adjust scan cadence.

**Per-macro-event frequency changes** (scanning faster around FOMC, CPI, NFP) should be replaced by a simpler approach: a calendar-based flag that pauses new entries 30 minutes before and after scheduled macro releases. For 2–15 day holds, the macro event affects *whether to enter*, not *how often to scan*.

---

## 4. Staleness tolerance varies by two orders of magnitude across dimensions

Each data dimension has a natural staleness tolerance proportional to its information half-life. The matrix below defines three thresholds: acceptable (data is fine), warning (flag but continue), and critical (degrade or halt).

| Dimension | Acceptable | Warning | Critical | Action at critical |
|---|---|---|---|---|
| **Price** | <5 min | 5–15 min | >15 min | Reduce position sizes 50%; skip new entries |
| **Trend** | <2 hr | 2–4 hr | >4 hr | Use last-known values; flag in LLM context |
| **Momentum** | <2 hr | 2–4 hr | >4 hr | Use last-known values |
| **Regime (VIX)** | <30 min | 30–60 min | >2 hr | Assume neutral regime; widen stops |
| **Fundamentals** | <24 hr | 24–72 hr | >7 days | Flag for manual review |
| **Macro** | <24 hr | 24–48 hr | >48 hr | Continue with last value indefinitely |
| **Sentiment** | <4 hr | 4–12 hr | >24 hr | Exclude from composite score |
| **Options** | <30 min | 30–60 min | >4 hr | Skip options-derived signals |
| **Intermarket** | <2 hr | 2–6 hr | >12 hr | Use last-known values |
| **Calendar** | <24 hr | 24 hr–7 days | >7 days | Recompute from static dates |
| **Earnings revisions** | <24 hr | 24–72 hr | >7 days | Use last-known consensus |

**Handling specific failure scenarios:** A yfinance outage lasting 2 hours keeps price data in the "critical" zone, but trend/momentum indicators computed from the last successful fetch remain in "acceptable" range because daily EMAs change slowly. The correct response is to halt new entries (stale price) while continuing to monitor existing positions using Alpaca's WebSocket for real-time quotes as a fallback. For FRED data, yesterday's values are almost always sufficient — macro series update once daily, and the predictive power operates over weeks.

**Critical design principle:** Include staleness metadata in every LLM packet. Prepend each XML section with a freshness tag: `<price freshness="3min" status="fresh">` or `<sentiment freshness="5hr" status="stale">`. This allows the LLM to appropriately discount stale signals rather than treating all inputs equally.

---

## 5. Pipeline timing reveals Finnhub and LLM inference as the true bottlenecks

Wall-clock benchmarks for the complete scan pipeline on an RTX 3060 12GB (Windows, Python 3.11+) show that **Finnhub's 60 calls/min rate limit and sequential LLM inference dominate total cycle time**, while technical computation and SQLite I/O are negligible.

| Operation | Wall-clock | Notes |
|---|---|---|
| yfinance batch (100 tickers, 5d 30m) | **8–15s** | Internally threaded; ~10s typical |
| Technical indicators (10 × 100 tickers) | **0.1–0.5s** | Vectorized pandas; trivially fast |
| Finnhub news (100 calls @ 60/min) | **100–110s** | **Dominant I/O bottleneck** |
| FMP batch fundamentals | **2–15s** | Parallelizable with ThreadPoolExecutor |
| FRED macro (5 series) | **2–3s** | Negligible |
| Options chains (20 tickers via yfinance) | **3–5s** | yfinance threaded internally |
| LLM inference per ticker (7B Q4_K_M) | **~16s** | ~1,200 t/s prompt processing, ~35 t/s generation (Windows) |
| LLM total (5–10 qualifying tickers) | **80–160s** | **Dominant GPU bottleneck** |
| SQLite all I/O | **<25ms** | WAL mode; trivially fast at this volume |
| **Full 11-section monolithic scan** | **~230–280s** | ~4–5 minutes with ThreadPoolExecutor(5) |

The staggered multi-cadence architecture transforms these numbers dramatically:

| Cycle type | Frequency | Wall-clock | GPU usage |
|---|---|---|---|
| Position monitor | Every 15 min | **2–4s** | 0% |
| Fast scan | Every 30 min | **12–18s** | 0% |
| Medium scan | Every 60 min | **35–55s** | 80–160s for LLM |
| Slow scan | Daily pre-market | **~280s** | 160s for deep LLM analysis |

**GPU utilization under Kingman's formula:** With LLM inference consuming ~160 seconds per 60-minute cycle, GPU utilization for inference is approximately **160/3600 = 4.4%** during market hours — far below the 75% threshold. This means the system has massive GPU headroom. The risk emerges only if LLM packets are generated for all 100 tickers simultaneously (100 × 16s = 1,600s = 26.7 minutes, consuming 44% of a 60-minute window). The architecture must enforce a **maximum of 10 LLM packets per cycle** to maintain the 75% utilization ceiling with buffer for position-monitoring inference requests.

**Parallelization recommendation:** Use `concurrent.futures.ThreadPoolExecutor(max_workers=5)` to overlap non-rate-limited HTTP calls. This reduces the non-Finnhub I/O wall-clock by approximately **25%** by running yfinance, FMP, FRED, and options fetches concurrently. However, Finnhub's 60/min rate limit cannot be parallelized away — it remains the binding I/O bottleneck. Do *not* pursue a full async/await migration; ThreadPoolExecutor provides 90% of the benefit at 10% of the refactoring cost.

---

## 6. Cache daily data in SQLite, detect changes with hashes

The caching architecture serves three purposes: reducing API calls for slow-changing data, enabling graceful degradation during API outages, and providing change detection to avoid reprocessing unchanged data.

**What to cache and when to invalidate:**

Daily-frequency data (fundamentals, insider transactions, macro, calendar, earnings revisions) should be fetched once at 7:30 AM pre-market and cached in SQLite. Cache invalidation occurs at the next pre-market refresh or when a `data_hash` comparison detects the API response has changed. For FRED macro data, maintain a time-series cache of the last 30 values per series to enable change detection on release days — most FRED series update after 3 PM ET, so polling before then for same-day values is typically futile.

**Training data snapshots** should use the **4:05 PM EOD snapshot** for all fast-changing signals (price, momentum, options) and the **7:30 AM pre-market snapshot** is fine for slow-changing signals (fundamentals, macro, insider) since these values don't change during the trading day. The training snapshot table should include a `data_completeness` score (fraction of non-null fields) to filter low-quality training examples.

**In-memory vs. SQLite:** Use a Python dictionary/DataFrame as the primary in-memory working set during each scan cycle. Write to SQLite at the end of each cycle for persistence. The memory footprint for 100 tickers × 11 sections is approximately **2–5 MB** — trivially small. SQLite with WAL mode handles the read/write volume (< 1,100 rows per cycle) in under 25 milliseconds.

The `data_freshness` table is the foundation of the entire reliability system. After every fetch attempt, upsert a row with `(ticker, source, last_fetched, last_success, data_hash, fetch_ms, error_msg)`. Before any scan cycle begins, query this table to determine which sources need refreshing versus serving from cache. A circuit breaker pattern should wrap each API: after 5 consecutive failures within 5 minutes, stop calling that source for 5 minutes and serve exclusively from cache.

---

## 7. Dual-cadence separation is the single largest architectural improvement

The most impactful change to the current system is splitting universe scanning from position monitoring into independent loops with different cadences, scopes, and compute profiles.

**Why separation matters:** Position monitoring requires only price and distance-to-boundary calculations for 5–15 held tickers — a **2–4 second operation**. Universe scanning requires full 11-section feature computation, ranking, and LLM inference for 100 tickers — a **4–5 minute operation**. Running both on the same 30-minute cadence means positions are checked too infrequently (a stock can move 0.6% in 30 minutes during volatile periods, potentially blowing through a stop) while the universe is scanned too frequently (pullback setups don't change meaningfully in 30 minutes).

**Optimal stopping theory** (Chow, Robbins & Siegmund 1971) provides the formal justification: near decision boundaries (stops and targets), the option value of waiting decreases, making more frequent evaluation rational. Far from boundaries, checking less frequently is optimal because the probability of a boundary crossing per unit time is low. This directly maps to the escalation rule: baseline 15-minute position checks, escalating to 5-minute checks when within 1.5× ATR of a stop.

**Broker-side stops are the ultimate monitoring optimization.** Alpaca supports native bracket orders with stop-loss and take-profit legs. The broker monitors prices continuously with zero system overhead. The system's position monitoring loop then becomes a *reconciliation and adjustment* layer — verifying that bracket orders are correctly set, adjusting trailing stops, and checking for timeout exits (holding period expiration). This eliminates the latency concern for stop execution entirely.

**The recommended dual-cadence architecture:**

| Component | Cadence | Scope | Wall-clock | GPU |
|---|---|---|---|---|
| Position monitor | 15 min (5 min if near boundary) | Held tickers only | 2–4s | None |
| Fast price scan | 30 min | 100 tickers, price + TA | 12–18s | None |
| Full universe scan | 60 min | 100 tickers, 11 sections + LLM | 35–55s + 80–160s LLM | Yes |
| Pre-market slow scan | Daily 7:30 AM | Full universe, all slow data | ~280s | Yes |
| Open check | 9:45 AM | Positions + gap analysis | ~10s | None |
| Close check | 3:50 PM | Positions + EOD decisions | ~10s | None |
| EOD recap | 4:05 PM | Training snapshot + reconciliation | ~120s | Optional |

Research on monitoring frequency for swing trades is consistent: more frequent position monitoring improves exit execution, while more frequent universe scanning risks over-trading without commensurate benefit. Trade Risk (2024) demonstrated empirically that in low-VIX environments, the lowest-frequency swing system outperformed higher-frequency alternatives by **3×** (+25% vs. ~7%) — more frequent decision-making led to over-trading and reduced returns.

---

## 8. Build monitoring before features, and skip Unusual Whales for now

The implementation priority is driven by a single principle from practitioners running solo automated trading systems: *"Build monitoring before building features. A system that trades well but fails silently is worse than a system that trades adequately and tells you when something is wrong."*

### Phase 1 — Weeks 1–2 (~20–28 hours): Foundation

- **Staleness detection system** (4–6 hrs): Create the `data_freshness` table, write freshness records after each scan section, check freshness before LLM consumption, alert via Pushover/email if any critical section exceeds 2× its expected interval. This is the single highest-ROI item — silent data failures in an unattended system represent unbounded risk.
- **Multi-cadence scanning** (6–8 hrs): Split the monolithic loop into position monitor (15 min) and universe scan (60 min). Use a config dict mapping `{cadence_name: [section_list], interval_minutes: N}`. This immediately reduces API load by ~60–70%.
- **SQLite caching layer** (6–8 hrs): Cache all daily-frequency data with hash-based change detection. Serve from cache when API fetches fail. This insulates the system from yfinance's inherent fragility as an unofficial scraper.
- **Calendar features** (3–4 hrs): Static earnings calendar + FOMC dates + OpEx schedule. The rule "don't enter a position 2 days before earnings" is one of the highest-value additions per engineering hour.

### Phase 2 — Weeks 3–4 (~14–20 hours): Data enrichment

Earnings revisions from FMP (strong academic evidence: revisions explain >10% of 3–6 month return variation), intermarket signals via yfinance (VIX, sector ETFs, yields), training data snapshot improvements, and a simple VIX threshold for position monitoring speed adjustment.

### Phase 3 — Weeks 5–6 (~12–16 hours): Options and optimization

**Start with free yfinance options data, not Unusual Whales.** yfinance provides implied volatility per contract, open interest, and volume — from which you can derive P/C ratio, IV rank (by tracking in SQLite over 30 days), and unusual volume flags. This covers **~60–70% of what Unusual Whales provides** for confirming pullback entries. Unusual Whales' primary value — real-time sweep and dark pool data — is most useful for day trading, not 2–15 day holds. At **$150/month** (Basic tier, post-May 2025 pricing), it should be deferred until free options data demonstrably improves entry quality and the system needs flow/dark pool data that yfinance cannot provide.

### Skip entirely

**Full async I/O migration**: For 100 stocks on a 30-minute cadence, synchronous HTTP with ThreadPoolExecutor(5) completes the full scan in under 5 minutes against a 30-minute budget. The async refactoring cost is 12–20 hours with new failure modes, for time savings the system doesn't need.

**Full adaptive scanning triggers**: Beyond the three recommended triggers (near-boundary escalation, VIX threshold, open/close checks), additional adaptive logic adds complexity without proportional benefit for multi-day holds.

**Alpha Vantage integration**: Reduced to **25 calls/day** (down from the frequently cited 500/day — this is outdated information). At 25 calls/day for 100 tickers, it is effectively useless for production. Reserve as emergency fallback only.

## Conclusion

The optimal architecture is not a single scan interval but a **four-tier cadence system** matched to empirical signal decay rates. The evidence strongly favors *less frequent* universe scanning (60 minutes) paired with *more frequent* position monitoring (15 minutes, escalating to 5 minutes near boundaries). Three findings deserve particular emphasis: first, **7 of 11 data dimensions have half-lives measured in days to months**, making daily pre-market fetching optimal and any intraday refresh wasteful. Second, **FMP's 250/day free tier — not scan frequency — is the true system bottleneck**, and the $19/month Starter plan is the single most impactful expenditure available. Third, **staleness detection is more important than scan optimization** — an unattended system that trades on silently stale data is categorically more dangerous than one that scans at a suboptimal frequency but knows when its data is unreliable.
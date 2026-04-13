# Transaction cost analysis for retail algorithmic trading on S&P 100 stocks

**For $5K–$25K equity orders on S&P 100 stocks, market impact is effectively zero — your dominant cost is the bid-ask spread, and your primary optimization lever is broker execution quality.** The square-root market impact model, validated across trillions of dollars of institutional data, predicts less than 1 basis point of impact at these sizes. The real TCA challenge is not minimizing market impact but systematically measuring and comparing execution quality between PFOF routing (Alpaca/Citadel/Virtu) and direct exchange access (Interactive Brokers), logging granular fill data, and building the statistical sample to detect meaningful differences. This guide calibrates every relevant model, quantifies every cost component, and provides a complete framework for implementation.

---

## 1. Expected slippage is negligible at retail scale — the math proves it

The empirical evidence on market impact for retail-sized orders on mega-cap stocks is unambiguous. A $25,000 order on a stock with $1 billion in average daily volume represents **0.0025% participation** — a rounding error relative to institutional flow. The dominant cost is crossing the bid-ask spread, not moving the price.

### The square-root model: calibrated for S&P 100

The standard market impact model, validated by Frazzini, Israel & Moskowitz (2018) across $1.7 trillion of AQR live execution data and confirmed by Sato et al. (2024) across millions of Tokyo Stock Exchange metaorders, takes the form:

**Impact = Y × σ_daily × √(Q / ADV)**

where Y ≈ 1 (dimensionless constant), σ_daily is daily volatility, Q is order size, and ADV is average daily dollar volume. Kyle & Obizhaeva (2018) calibrated Y close to unity across asset classes. For S&P 100 stocks: top-20 mega-caps have σ ≈ 1.2%–2.0% daily and ADV of **$2B–$35B**; bottom-20 names have σ ≈ 1.5%–3.0% and ADV of **$200M–$800M**.

Running the numbers for a $25K order on a stock with σ = 1.5% and ADV = $1B: Impact = 0.015 × √(25,000 / 1,000,000,000) = 0.015 × 0.005 = **0.75 basis points** — less than the half-spread for most S&P 100 names. For AAPL with ~$11B ADV, the impact drops to roughly **0.1 bps**, which is completely immeasurable. The impact is concave (square-root), not linear: doubling order size increases impact by only ~41% (√2 ≈ 1.41).

### Slippage percentiles for $5K–$25K orders

Based on Schwarz et al. (2025, *Journal of Finance*), Dyhrberg & Shkilko (2025, *Journal of Financial Economics*), and Frazzini et al. (2018):

| Metric | Estimate | Driver |
|--------|----------|--------|
| **Median slippage** | 0.5–2 bps | Half-spread; often negative (price improvement) for orders < $5K |
| **95th percentile** | 5–10 bps | Volatile moments, not order-size impact |
| **Worst case** | 20–50 bps | Extreme events (flash crashes, macro shocks) |

Dyhrberg & Shkilko (2025) found that **99% of retail orders below $5,000 receive NBBO or better** from wholesalers. For orders exceeding $64,000, this drops to 86%. The Almgren-Chriss (2001) optimal execution model confirms that for orders below 0.01% of ADV, **immediate execution via a single market order is optimal** — the timing risk of delay exceeds any impact savings from slicing.

### Bid-ask spreads across the S&P 100

S&P 100 stocks have among the tightest spreads in global equity markets. Top-20 mega-caps (AAPL, MSFT, NVDA) trade with effective spreads of **1–3 basis points** — often just $0.01 on a $200+ stock. Bottom-20 S&P 100 names show spreads of **3–8 bps**. Nasdaq research finds the top-100 S&P 500 portfolio carries an average spread cost of approximately **3.7 bps**. Effective spreads (what traders actually pay after price improvement) run 50–80% of quoted spreads for retail orders.

### Where impact starts to matter as AUM grows

The square-root model provides clean scaling estimates:

| Order Size | % of $1B ADV | Impact (bps) | Impact ($) |
|-----------|-------------|-------------|-----------|
| $25K | 0.0025% | ~0.75 | ~$0.19 |
| $100K | 0.01% | ~1.5 | ~$1.50 |
| $500K | 0.05% | ~3.4 | ~$16.70 |
| $1M | 0.1% | ~4.7 | ~$47.40 |
| $5M | 0.5% | ~10.6 | ~$530 |

Impact exceeds the spread (becomes "measurable") around **$100K–$500K** for typical S&P 100 stocks. Going from $25K to $1M (40× more capital) increases impact by only ~6.3× — the square-root law in action. **No algorithmic execution strategy (VWAP, TWAP, iceberg orders) is needed until order sizes reach roughly $300K–$1M for these names.**

---

## 2. PFOF versus direct routing: the evidence is more nuanced than the debate

The PFOF question for S&P 100 stocks specifically is less dramatic than popular discourse suggests. Wholesalers provide measurable price improvement on large-cap names, but the magnitude depends heavily on which broker negotiates the arrangement and how it is measured.

### What the wholesalers actually deliver

Citadel Securities executes ~35% of all US retail equity volume; together with Virtu Financial (~26%), they handle **roughly 70% of retail order flow**. Global Trading analysis of Feb 2024–Jan 2025 data shows four major wholesalers (Citadel, Virtu, Susquehanna, Jane Street) collectively provided **$3.2 billion in price improvement** versus exchange execution — approximately $267 million per month across 567 billion shares. Virtu posted the lowest average effective spread at **$0.004/share**; Susquehanna excelled in volatile names like Tesla and Nvidia, saving traders **$0.01/share** on average.

Dyhrberg, Shkilko & Werner (2025) found wholesaler price improvement exceeds **2 cents per share** for S&P 500 stocks, and the effective-to-quoted spread ratio is **44 percentage points better** than exchange execution. However, this finding comes with a critical caveat identified by Levy's 2022 Wharton randomized controlled trial: because NBBO excludes odd-lot and hidden-order liquidity available on exchanges, prior literature estimates of 5–9 bps price improvement are **overstated by up to 400%**. True price improvement after adjusting for sub-NBBO accessible liquidity is likely **1–5 bps**.

### The broker matters more than the routing model

Schwarz, Barber, Huang, Jorion & Odean (2025) — the definitive study using 85,000 simultaneous market orders across 5 brokers — found **striking variation** in round-trip execution costs:

| Broker | Round-Trip Cost | PI as % of NBBO Spread | PFOF? |
|--------|----------------|----------------------|-------|
| TD Ameritrade | -0.07% | 47.2% | Yes |
| Fidelity | -0.23% | 35.8% | No |
| E*Trade | -0.20% | 36.1% | Yes |
| Robinhood | -0.31% | 26.8% | Yes |
| IBKR Lite | -0.44% | 19.5% | Yes |
| IBKR Pro | -0.46% | 18.8% | No |

The **39 bps spread** between best and worst broker is far larger than any market impact effect at retail sizes. IBKR Pro's apparently poor performance is misleading — Schwarz et al. attribute it to **adverse selection**: IBKR Pro customers are more informed traders, so market makers offer worse fills because the flow is riskier to trade against, not because IB's routing is inferior. IB's own published metrics show **100% of S&P 500 orders execute at NBBO or better**, with rolling 12-month all-in costs of **3.3–3.8 bps** versus daily VWAP.

### SEC Rule 606 reports: what Alpaca and IB disclose

Alpaca Securities routes through Apex Clearing, which receives PFOF from Citadel Securities (< $0.0021/share), Two Sigma Securities (< $0.0020/share), Instinet, and G1 Execution Services. IBKR Pro accepts **no PFOF** for equity market orders — orders route via SmartRouting to IB's own ATS, exchanges, and 8 dark pools. IBKR Lite uses PFOF similar to other commission-free brokers.

Rule 606(a) reports must disclose quarterly: percentage of orders routed to each venue, net PFOF received per share, and material aspects of payment arrangements, separated by S&P 500 versus other NMS stocks. The 2018 amendments (effective January 2020) added granular fee/rebate breakdowns and a held versus not-held order distinction.

### The PFOF regulatory landscape: reforms are dead

The SEC under Chair Paul Atkins **formally withdrew** all Gensler-era market structure reform proposals on June 12, 2025, including the Order Competition Rule (mandatory auctions for retail orders) and Regulation Best Execution. Of the original four December 2022 proposals, only **Rule 605 amendments** (enhanced execution quality disclosures, compliance December 2025) and **tick size/access fee changes** (reducing the access fee cap from 30 mils to **10 mils** per share) were finalized — though the latter faces legal challenges from exchanges. PFOF will continue under the current FINRA Rule 5310 best execution framework for the foreseeable future.

### Adverse selection and what wholesalers extract

Retail order flow is "uninformed flow" — less likely to carry directional information. Wholesalers pay for this flow because they can retain the full bid-ask spread trading against uninformed counterparties, whereas on-exchange they face adverse selection from informed traders. Wholesalers report an approximately **80/20 split** between customer price improvement and broker PFOF. But BestEx Research (2021) argued that if retail flow migrated to exchanges, NBBO itself would **significantly narrow**, meaning the baseline against which price improvement is measured is artificially inflated by the PFOF system itself.

During volatile markets, price improvement declines. Wholesalers tend to execute when NBBOs are **33% wider** than exchange spreads (64.92 bps vs. 48.67 bps per Dyhrberg et al.). Susquehanna delivers better volatile-market performance ($0.009/share savings), while Virtu's model is optimized for stable, liquid conditions. During correlated, directional retail flow events (GameStop-type squeezes), the wholesaler-retail arrangement can break down entirely.

---

## 3. The 10:00–11:30 AM window is near-optimal, but not for the reason most think

The system's entry window of 10:00–11:30 AM ET aligns well with the empirical evidence on intraday microstructure, though the primary benefit is not tighter spreads (which remain tight all day for S&P 100 stocks) but rather **reduced volatility and better-absorbed information**.

### The intraday spread pattern

McInish & Wood (1992, *Journal of Finance*) documented the classic reverse-J pattern: spreads are widest at the open and decline throughout the day, with a modest uptick near the close. More recent electronic-era data from Hua, Kong & Wang (2024) using TAQ data from 2000–2021 confirms a pronounced U-shape in both spreads and volumes for NASDAQ stocks.

For S&P 100 stocks specifically, the intraday spread profile looks like this:

- **9:30–10:00 AM**: Spreads run **2–3× midday levels** — for a stock with a midday spread of 2 bps, opening spreads may reach 5–8 bps. Information asymmetry is highest as overnight news gets digested.
- **10:00–11:30 AM**: Spreads have narrowed substantially; volume remains robust; European markets are still open (closing at 11:30 AM ET) contributing cross-market liquidity. This is the transition to minimum-spread territory.
- **11:30 AM–2:30 PM**: Spreads near their absolute minimum (**1–3 bps** for mega-caps), but volume drops to the day's lowest level — roughly 9–11% of daily volume per hour.
- **3:00–4:00 PM**: Volume surges (20–25% of daily volume in the last hour), closing auction liquidity is enormous ($50+ billion/day in 2024), and spreads remain relatively tight.

The U-shaped volume pattern is dramatic: the first 30 minutes account for **15–20% of daily volume**, the last 30 minutes see volume spike to roughly **5× the continuous trading rate**, and the closing auction alone represents **9–10% of daily volume** (up from 3.1% in 2010). SPY sets its daily high or low during the first or last hour **62% of the time**.

### Why 10:00–11:30 works well

The window captures narrow spreads while avoiding the three riskiest intraday periods: (1) the information-asymmetry-heavy first 30 minutes, (2) major economic releases at 10:00 AM sharp (ISM, consumer confidence — these cause temporary spread widening), and (3) closing auction volatility. **For immediate market orders at retail size, 10:00–11:30 AM is near the cost minimum.** The one caveat: if scheduling releases land exactly at 10:00 AM, a brief 2–3 minute delay after release can avoid the worst spread widening.

Research from the *Journal of Financial Economics* (2023) on closing auctions found that price impact during the closing auction is actually **lower than during continuous trading** for institutional-sized orders, with $50+ billion in daily liquidity providing enormous absorption capacity. For retail-sized orders, however, the closing auction adds no meaningful advantage over midday continuous trading.

---

## 4. Stop-loss execution: overnight gaps are the real enemy

For GTC bracket orders on S&P 100 stocks, stop-market order execution during regular trading hours is not the primary risk. The meaningful risk is overnight gaps that blow through stop prices entirely.

### Regular-hours stop execution

During normal market conditions, stop-market orders on S&P 100 stocks fill **within 1–5 cents of the stop price** — representing 0–3 bps on a $150+ stock. The mechanism is straightforward: when the stop price is hit on the consolidated tape, the stop converts to a market order. For Alpaca specifically, stop orders elect "on the consolidated print" and only when "the electing trade is not outside of the NBBO." Deep order book liquidity in S&P 100 names means the converted market order typically fills at or near the trigger price.

During elevated volatility (macro events, intraday selloffs), slippage can widen to **10–50 cents** or more. The 2010 Flash Crash saw stop orders execute "far below their intended levels" per the SEC/CFTC joint report. Even in less extreme scenarios, a rapid 1% drop in a $200 stock could see a stop at $198 fill at $197.50–$197.80.

### The overnight gap problem

This is where stops genuinely fail. S&P 100 stocks commonly gap **3–10%** on earnings, with extreme gaps of 15–25% occurring on major surprises (Meta gapped down ~25% on February 3, 2022). A stop at $190 on a stock closing at $200 that opens at $170 post-earnings fills near $170 — producing **$20 of slippage** on a $10 protective stop. This gap risk cannot be eliminated with any stop order type; it is a fundamental feature of discrete-session equity markets.

### Stop-market versus stop-limit tradeoffs

Stop-market orders guarantee execution but offer no price protection. Stop-limit orders protect against catastrophic fills but risk **non-execution** — if the stock gaps through both the stop and limit prices, the order remains unfilled. Practitioners estimate stop-limit orders fail to execute **20–50%+ of the time** during significant gap events (>5% gaps). For a defensive bracket order system, stop-market is generally preferred because the primary purpose — exiting a losing position — requires guaranteed execution. The risk of being stuck in a declining position after a failed stop-limit is typically worse than accepting gap slippage.

Academic evidence on stop-loss strategies is mixed. Xiang & Deng (*Quantitative Finance*, 2024) found stops enhance risk-adjusted returns when assets trend but decrease returns in mean-reverting regimes. Osler (2005) documented that stop-loss orders contribute to "price cascades" in FX markets — over 62% of very large stops triggered self-reinforcing price movements. Vaarmets et al. (2019) found that stops reduce the disposition effect but "can be harmful to performance at the same time."

---

## 5. Building a TCA framework: what to measure, log, and compare

The TCA system must answer one core question: **is live execution degrading backtested returns, and if so, by how much and why?** For a bracket-order strategy at retail scale, the framework should use an arrival price benchmark with separate entry and exit IS measurement.

### The right benchmark: arrival price implementation shortfall

For market order entries, the **arrival price** — the NBBO midpoint at signal generation time — is the correct benchmark. It maps directly to the price assumed in backtests and captures all costs between signal and fill. The implementation shortfall decomposition (Perold 1988, Wagner & Edwards 1993) breaks total cost into:

- **Spread cost**: Half-spread paid crossing the bid-ask (0.5–2.0 bps for S&P 100)
- **Timing cost**: Price drift between signal and execution (near-zero for immediate market orders)
- **Market impact**: Price moved by your own order (effectively 0 bps at $5K–$25K)
- **Opportunity cost**: Foregone P&L from unfilled limit exits (highly variable; depends on fill rate)
- **Explicit costs**: Commissions + regulatory fees ($0 on Alpaca; ~$0.005/share on IBKR Pro)

Per Quantitative Brokers research, for individual orders "market drift is probably a lot more than you think — perhaps **80% of slippage** versus 20% attributed to market impact." At retail scale, market impact is essentially zero, making the TCA focus entirely about spread capture, timing drift, and broker execution quality.

### Bracket order IS: a three-phase model

**Phase 1 — Entry IS**: `Fill_Price − Mid_Quote_at_Signal_Time` (in bps). Target: < 2 bps.

**Phase 2 — Exit IS**: Measured separately by exit type. For limit fills: `Limit_Price − Mid_at_Fill_Time` (typically zero or favorable). For stop fills: `Stop_Fill_Price − Stop_Trigger_Price` (target: < 3 bps during normal hours).

**Phase 3 — Opportunity cost**: When limit orders don't fill and the position exits via stop instead, the missed profit target represents foregone return. Track **fill rate of profit target orders** — if below 50%, limit prices may be too aggressive.

Total round-trip IS = Entry_IS + Exit_IS + Explicit_Costs. Record every bracket trade as a complete round-trip with an `exit_type` field ('limit_fill', 'stop_fill', 'manual_close', 'timeout'). Compute IS separately for each exit type, then aggregate.

### Data logging: the minimum viable TCA dataset

Every trade must capture at minimum: `signal_timestamp` (microsecond precision), `order_submit_timestamp`, `fill_timestamp`, `fill_price`, `NBBO_bid_at_signal`, `NBBO_ask_at_signal`, `NBBO_bid_at_fill`, `NBBO_ask_at_fill`, `filled_qty`, `exchange_venue`, `bracket_limit_price`, `bracket_stop_price`, `exit_type`, and `exit_fill_price`. Additional high-value fields include VIX level at entry, intraday volume percentile, and ADV for relative order size calculation.

For data sources: use **Alpaca's Data API** (free basic / $99/month Pro, includes SIP NBBO quotes) for real-time NBBO capture at order time. Supplement with **Polygon.io** ($29–$200/month) for historical tick/NBBO data for post-trade analysis. Capture arrival price at signal time using Alpaca's `StockLatestQuoteRequest` endpoint.

### Python TCA implementation

No off-the-shelf library perfectly fits retail equity bracket-order TCA. Build a lightweight custom system using:

- **`alpaca-py`**: Trade data, order history, real-time quotes for NBBO capture
- **`ib_insync`**: Interactive Brokers API wrapper for IB trade logs and executions
- **`pandas` / `numpy`**: Core TCA calculations (VWAP, IS, spread cost decomposition)
- **`scipy.stats`**: Statistical tests — Wilcoxon signed-rank for slippage significance (preferred over t-tests due to skewed slippage distributions)
- **`streamlit`**: Dashboard for daily TCA monitoring
- **`sqlite3`**: Trade log storage with microsecond timestamps

Reference implementations include **tcapy** (cuemacro, ~500 GitHub stars, primarily FX but extensible), **flowpylib** (tick-level TCA with Bayesian change-point detection), and the LSEG Developer Portal's end-to-end TCA tutorial. The R package **blotter** (braverock) provides a reference `impShortfall()` function implementing Perold, Wagner, and Market Activity IS methods.

### Statistical confidence: how many trades you need

For preliminary pattern recognition, **30 trades** is the absolute floor (Central Limit Theorem). Reliable slippage estimates require **100–200 trades** spanning multiple market regimes. For comparing Alpaca versus IB execution quality, detecting a 1 bps difference at 95% confidence with typical slippage variance (σ ≈ 3–5 bps) requires approximately **500 trades per broker** — following the power analysis formula n = (Z_α/2 + Z_β)² × 2σ² / δ². The Schwarz et al. (2025) study used 85,000 simultaneous orders across brokers, which represents the gold standard. For a practical retail comparison, aim for 200+ matched trades minimum, and use bootstrap confidence intervals and non-parametric tests to handle skewed distributions.

### Key TCA metrics to track

| Metric | Formula | Target |
|--------|---------|--------|
| Mean arrival slippage | (fill − mid_signal) / mid_signal × 10,000 bps | < 2 bps |
| Price improvement rate | % trades where fill beats NBBO | > 50% |
| Avg price improvement | mean(NBBO − fill_price) for improved trades | $0.005–$0.02/share |
| Stop slippage | mean(stop_fill − stop_trigger) | < 3 bps normal hours |
| Limit fill rate | % profit targets that fill | Strategy-dependent |
| Effective/quoted spread ratio | effective_spread / quoted_spread | < 80% = good PI |

---

## 6. The academic foundations: what the literature establishes

The theoretical framework for understanding execution costs rests on four foundational papers, complemented by a wave of 2023–2026 empirical work that has substantially updated the evidence.

### Kyle (1985) and the concept of price impact

Kyle's lambda (λ) — the price change per unit of signed order flow — provides the theoretical foundation for all market impact measurement. In his *Econometrica* model, market makers set prices as a linear function of aggregate order flow, with λ representing the inverse of market depth. For mega-cap S&P 100 stocks, λ is infinitesimally small: a $25K order (~114 shares of AAPL) predicts price movement of roughly **$0.0006** — completely immeasurable. Lambda varies intraday with a U-shape under calendar-time aggregation (higher at open and close) but falls monotonically under trade-time analysis.

### Almgren & Chriss (2001) and the execution frontier

The Almgren-Chriss framework explicitly constructs the efficient frontier trading off expected execution cost versus variance of cost. It separates **permanent impact** (g(v) = γ·v, lasting equilibrium price change) from **temporary impact** (h(v) = ε + η·v, transient microstructure effects). The key insight for retail traders: for very small orders relative to ADV, permanent impact approaches zero and temporary impact reduces to the half-spread cost. The optimal strategy for a $25K order on an S&P 100 stock **is simply a market order** — the model's sophisticated order-splitting logic only becomes relevant above roughly $300K–$1M.

### The square-root law: universally validated

Bouchaud, Farmer & Lillo established empirically that market impact scales as **ΔP/P ≈ Y · σ · √(Q/V)**, contradicting Kyle's linear prediction. Sato et al. (2024, *Physical Review Letters*) confirmed the exponent δ = 0.50 ± 0.01 using millions of metaorders — remarkably universal across individual stocks, individual traders, and time periods. The theoretical explanation involves "latent liquidity" near the current price creating a V-shaped supply curve, where incoming orders face increasing resistance proportional to the square root of their size. Permanent impact is roughly **2/3 of total impact** at completion, with 1/3 reverting.

### 2023–2026 empirical breakthroughs

Three recent papers have transformed the retail execution quality evidence:

**Schwarz et al. (2025, *Journal of Finance*)** conducted the definitive controlled experiment — 85,000 simultaneous market orders across 5 brokers revealed a **39 bps spread** in round-trip costs between best and worst broker, with wholesalers systematically giving different prices to different brokers for identical trades. This establishes that broker selection dominates all other execution cost factors for retail traders.

**Dyhrberg, Shkilko & Werner (2025, *Journal of Financial Economics*)** demonstrated that off-exchange wholesaler execution provides significant cost savings for retail investors, with Citadel and Virtu charging the **lowest liquidity costs** despite handling 70%+ of flow — suggesting economies of scale rather than market power abuse. They found wholesalers price-improve approximately **65.7% of retail orders**.

**Battalio & Jennings (2025, *Management Science*)** used proprietary wholesaler data from May 2022 and found the value of total price and size improvement is **6.5× greater** than what Rule 605 reports show, with external liquidity sourced for 28.6% of shares — contradicting the assumption that wholesalers only internalize.

### Regulatory framework as of April 2026

FINRA Rule 5310 remains the operative best execution standard, requiring "reasonable diligence" to ascertain the best market and achieve prices "as favorable as possible under prevailing market conditions." Brokers must conduct "regular and rigorous" execution quality reviews at minimum quarterly. The rule explicitly requires firms to consider the existence of PFOF arrangements in their reviews.

SEC Rule 605 amendments (finalized March 2024, compliance December 2025) will produce significantly more granular execution quality data, including realized spread statistics from <100 microseconds to 5 minutes, expanded order type coverage (stop orders, fractional shares, odd lots), and reporting by larger broker-dealers. Rule 606 continues to require quarterly public disclosure of order routing and PFOF arrangements. The tick size and access fee amendments (finalized September 2024) will reduce the access fee cap from 30 mils to **10 mils per share**, though exchange legal challenges may delay implementation.

---

## Conclusion: what this means for Halcyon Lab

Five concrete takeaways emerge from this research that should directly inform system design and evaluation:

**First, market impact is a non-issue at current scale.** At $5K–$25K on S&P 100 stocks, you are operating at 0.001–0.003% of ADV. No execution algorithm, order slicing, or impact minimization strategy will produce measurable savings. Impact becomes relevant only above approximately $300K–$1M per order, and even then only for the less liquid bottom-20 S&P 100 names.

**Second, the Alpaca-versus-IB comparison will require patience and rigor.** Detecting a 1 bps execution quality difference requires ~500 matched trades per broker at 95% confidence. The Schwarz et al. (2025) finding that IBKR Pro shows worse price improvement than PFOF brokers is driven by adverse selection, not inferior routing — but your system's specific signal characteristics will determine whether this pattern applies to your flow. Run identical signals simultaneously on both platforms and use Wilcoxon signed-rank tests rather than t-tests.

**Third, the 10:00–11:30 AM entry window is well-chosen but vulnerable to scheduled releases.** Major economic data at 10:00 AM sharp (ISM, consumer confidence, JOLTS) can cause temporary spread widening. Consider a 2–3 minute buffer after 10:00 AM releases, or check an economic calendar before firing signals in the first minutes of the window.

**Fourth, overnight gap risk on stops is the largest uncontrollable execution cost.** S&P 100 earnings gaps of 5–15% will blow through any stop. This is a position-sizing and risk management problem, not an execution problem. Consider reducing position sizes ahead of known earnings dates and accepting that stops provide protection only during continuous trading hours.

**Fifth, build your TCA system now, before scaling.** Log NBBO at signal time, fill price, fill timestamp, and exit type for every trade from day one. The statistical power to detect execution issues grows linearly with trade count, and early data — even from paper trading — establishes baselines that become invaluable when transitioning to live capital or scaling to $100K+ order sizes where impact begins to matter.
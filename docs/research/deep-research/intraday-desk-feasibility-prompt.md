# Deep Research Prompt: Intraday Trading Desk Feasibility Study

## Classification
- **Type:** Category 1 (literature and industry research)
- **Purpose:** Pre-research for Phase 6 (Intraday Desk) in the Arcis/Halcyon Lab multi-desk roadmap
- **Timeline:** This research is exploratory — intraday desk is 6-12+ months away. No implementation decisions will be made from this research alone. The goal is to understand the landscape so architecture decisions made NOW (in Phase 1 diagnostic work) don't accidentally close doors that intraday would need open later.
- **Output format:** Structured report with sections matching the 5 research areas below. Each section should include: academic citations with effect sizes where available, concrete implementation requirements, cost estimates, and an honest assessment of feasibility for a solo operator running on consumer hardware (RTX 3060 12GB, upgrading to RTX 3090 24GB within 6 months).

---

## Context About Our System (Read First)

Arcis is a solo-operated AI-powered equity trading system targeting S&P 100 stocks. Current state:

- **Phase 1 (active):** Pullback-in-uptrend mean-reversion strategy on S&P 100 with 2%/3%/7-day mechanical brackets. ~80 closed trades. Currently diagnosing whether the strategy has alpha vs SPY (forensic analysis showed per-trade Sharpe 3.38 may be SPY beta during a bull run).
- **Architecture:** Python, FastAPI, React dashboard, SQLite (local) + Postgres (cloud), Alpaca broker (paper + minimal live), watch loop polling every ~60s during market hours.
- **LLM:** Qwen3 8B fine-tuned (Q8_0 GGUF) via Ollama on RTX 3060 12GB. Inference ~2-4 seconds per call. Used for trade commentary and conviction scoring, not real-time decision-making.
- **Data sources:** FMP (250 req/day), Finnhub, yfinance, SEC EDGAR. All daily-timeframe. No streaming data infrastructure.
- **Execution:** Bracket orders (OCO stop + target) placed once and held for days. No active position management.
- **Capital:** ~$100K target for Phase 1. Not relevant for intraday research but constrains position sizing and PDT compliance.

The multi-desk roadmap: Equity Swing (Phase 1) → Equity Research (Phase 2) → Options Volatility (Phase 3-4) → Equity Momentum (Phase 5) → **Intraday (Phase 6+)**. Each desk is gated on the previous desk's profitability. The intraday desk is last because it has the highest infrastructure requirements.

---

## Research Area 1: Intraday Strategies for S&P 100 Large-Cap Equities

### Core Questions

1. **What intraday mean-reversion strategies have documented alpha on large-cap US equities post-2015?** Focus on strategies that work on the S&P 100 universe specifically (most liquid, tightest spreads, lowest market impact). Include:
   - Opening range breakout / breakdown (ORB) — what are the optimal timeframes (5-min, 15-min, 30-min opening range)?
   - VWAP mean reversion — entry on deviation from VWAP, exit on reversion. What deviation thresholds are documented?
   - Intraday momentum / reversal patterns — Gao et al. (2018) "Intraday Momentum," Elaut et al. (2018). Are these still profitable post-2020?
   - Market microstructure-based strategies — order flow imbalance, Kyle's lambda estimation at retail scale. Is this feasible without Level 2 data?

2. **What is the realistic Sharpe ratio range for intraday strategies on large-cap equities at retail scale ($100K-500K)?** Distinguish between:
   - Gross Sharpe (before costs)
   - Net Sharpe (after commissions, slippage, market impact)
   - What is the typical transaction cost drag for 5-20 round trips per day on S&P 100 stocks via Alpaca (PFOF routing)?

3. **What holding periods have the best risk-adjusted returns for intraday on S&P 100?** Compare:
   - Scalping (seconds to minutes) — likely not feasible at retail
   - Short-term intraday (5 min to 1 hour holds)
   - Intraday swing (1-4 hour holds, flat by close)
   - Which of these is most compatible with ~2-4 second LLM inference latency?

4. **What time-of-day effects are documented and exploitable?**
   - Opening auction dynamics (9:30-10:00 AM)
   - Morning momentum (10:00-11:30 AM) — we already use this window for swing entries
   - Midday lull (11:30 AM - 2:00 PM)
   - Power hour (3:00-4:00 PM)
   - Which windows have the best signal-to-noise for a systematic strategy?

5. **What is the minimum number of trades needed to validate an intraday strategy with statistical significance?** Given:
   - Higher trade frequency means faster statistical convergence
   - But also higher multiple-testing burden (more parameters to tune)
   - What's the realistic timeline to 150+ trades for an intraday strategy doing 3-10 trades/day?

### Output Format for This Section
- Table: Strategy name | Academic citation | Reported Sharpe (gross/net) | Holding period | Data requirements | Feasibility at retail scale (1-5 rating)
- Top 3 recommended strategies ranked by: (a) documented post-2020 evidence, (b) compatibility with our infrastructure, (c) simplest to implement first
- Honest assessment: which of these strategies have been arbitraged away by HFT firms, and which still have residual alpha at 1-minute+ timeframes?

---

## Research Area 2: Streaming Data Infrastructure

### Core Questions

1. **What real-time data sources are available for S&P 100 equities at retail cost?** Compare:
   - Alpaca Market Data API (free with brokerage, WebSocket streaming) — what are the actual latency characteristics and data completeness?
   - Polygon.io (Starter $200/mo, Business $600/mo) — what do you get at each tier?
   - IEX Cloud — pricing and capabilities for real-time
   - Finnhub WebSocket — is the free tier sufficient for 100 tickers?
   - IB TWS streaming (already have account, cold-stored) — what are the data quality characteristics?
   - Direct exchange feeds (likely out of scope at retail)

2. **What is the minimum data infrastructure for a functional intraday system?**
   - Level 1 quotes (bid/ask/last/volume) vs Level 2 (order book depth) — which strategies from Research Area 1 require which?
   - Bar frequency: 1-second, 5-second, 1-minute, 5-minute — what's the minimum useful frequency for each strategy type?
   - Historical intraday data for backtesting — where to get 1-minute bars for S&P 100 going back 2-5 years, and what does it cost?

3. **What does a streaming data pipeline look like in Python?** Architecture patterns for:
   - WebSocket consumer → message queue → feature computation → signal generation
   - Is Redis/Kafka needed at 100-ticker scale, or can an in-memory Python queue suffice?
   - How do you handle reconnection, missed messages, and gap detection?
   - What's the realistic end-to-end latency from market event to signal generation on consumer hardware?

4. **Storage requirements:** 
   - How much data does 1-minute bars for 100 tickers generate per day/month/year?
   - SQLite vs TimescaleDB vs InfluxDB for intraday time-series at this scale
   - Can we reuse the existing SQLite + Postgres architecture or does intraday force a different storage layer?

### Output Format for This Section
- Comparison table: Data source | Cost/mo | Latency | Data types | Free tier limits | S&P 100 coverage
- Architecture diagram (text description): recommended pipeline from WebSocket to signal
- Storage estimate: GB/month for 100 tickers at 1-minute resolution
- Recommendation: cheapest viable stack for a solo operator, with upgrade path

---

## Research Area 3: Event-Driven Execution Architecture

### Core Questions

1. **How do you architect an event-driven trading system alongside an existing batch (poll-based) system?** Our current watch loop polls every ~60s. An intraday system needs to react to streaming events. Options:
   - Replace watch loop with event loop (asyncio-based)
   - Run event-driven intraday system as a separate process alongside the watch loop
   - Hybrid: watch loop for daily-timeframe desks, event processor for intraday
   - What's the standard pattern in open-source quantitative trading frameworks (Zipline, Lean, backtrader, VectorBT)?

2. **What execution patterns are standard for intraday?**
   - Market orders vs limit orders — when to use which for intraday mean-reversion
   - Smart order routing at retail (Alpaca PFOF through Citadel/Virtu) — does the routing matter for intraday?
   - Active position management: trailing stops that update every N seconds, time-based exits, partial position scaling
   - How do you implement "flatten everything by 3:55 PM" as a hard constraint?

3. **What is the realistic latency budget for a Python-based intraday system on consumer hardware?**
   - Signal detection: how fast can you compute features on a new bar?
   - LLM inference: 2-4 seconds is too slow for hot-path decisions — what role should the LLM play?
   - Order submission to Alpaca: typical round-trip latency
   - End-to-end: from price event to order placed — what's achievable?

4. **What open-source frameworks or libraries should we evaluate?**
   - For backtesting intraday strategies specifically (not daily — different requirements)
   - For live execution with WebSocket data feeds
   - For order management (partial fills, bracket management, position tracking)
   - Which ones work well with Alpaca specifically?

### Output Format for This Section
- Architecture pattern comparison: batch vs event-driven vs hybrid, with pros/cons for our specific situation
- Latency budget table: component | typical latency | our expected latency | bottleneck?
- Framework comparison table: Name | Language | Intraday support | Alpaca integration | Active maintenance | Learning curve
- Recommendation: which pattern and which framework(s) for a solo Python developer

---

## Research Area 4: LLM Role in Intraday Trading

### Core Questions

1. **Should the LLM be in the intraday hot path at all?** Given 2-4 second inference on 8B model:
   - Option A: LLM provides daily-level context (regime, sector sentiment, earnings risk) that feeds into a purely mechanical intraday signal generator. LLM runs once pre-market, not per-trade.
   - Option B: LLM evaluates intraday setups but only for a filtered subset (e.g., top 5 candidates per hour). Inference is batched, not real-time.
   - Option C: Smaller model (Qwen3-1.5B or 4B) for sub-second inference in the hot path. What's the quality tradeoff?
   - Option D: LLM generates end-of-day training signal from intraday outcomes (reinforcement loop). Not in the trading path at all.
   - What does the academic literature say about LLM utility at intraday timeframes? Is there evidence that language models add value to sub-daily trading decisions?

2. **What training data would an intraday LLM need?**
   - Can we reuse the existing 1,782-example daily-timeframe dataset in any way?
   - What would intraday training examples look like? (Presumably: 1-minute chart context, order flow features, time-of-day, and a commentary on whether to enter/exit)
   - How many intraday training examples would be needed for a useful fine-tune?
   - Is synthetic data generation feasible for intraday (generating commentary from historical 1-minute bars)?

3. **What's the state of the art for LLMs in intraday/HFT contexts?**
   - Trading-R1 (if applicable to intraday)
   - FinRL and reinforcement learning approaches — are these more appropriate than LLM for intraday?
   - Any published results on LLM-assisted intraday trading at retail scale?

### Output Format for This Section
- Decision matrix: LLM role option (A/B/C/D) | Inference latency | Quality tradeoff | Training data needs | Recommendation
- If Option A or D is recommended: what pre-market LLM tasks add the most value to intraday?
- If Option B or C: what's the minimum model size for useful intraday commentary, and what VRAM does it require?

---

## Research Area 5: Intraday Risk Management

### Core Questions

1. **What risk controls are specific to intraday that don't apply to swing trading?**
   - Maximum loss per hour / per session
   - Maximum number of round-trips per day (tax implications, PDT rule)
   - Correlation between simultaneous intraday positions (how many can you hold at once?)
   - Time-based position limits (no new positions after 3:30 PM, flat by 3:55 PM)
   - Volatility circuit breakers (halt trading if VIX spikes intraday)

2. **Pattern Day Trader (PDT) rule implications:**
   - At $100K equity we clear the $25K minimum, but are there other regulatory constraints?
   - How does PDT interact with multiple strategies on the same account?
   - If running both swing (Phase 1) and intraday (Phase 6) on the same Alpaca account, how do you track which trades are which for PDT purposes?

3. **Transaction cost management for high-frequency trading at retail:**
   - Alpaca commission structure for active traders (currently commission-free but with PFOF)
   - Expected slippage on S&P 100 stocks for market orders at $25K position size
   - At what trade frequency does transaction cost drag exceed alpha? (Break-even analysis)
   - Should we use limit orders exclusively for intraday to control costs?

4. **How do you separate intraday P&L from swing P&L for performance attribution?**
   - Desk-level P&L isolation
   - Reporting to track record platforms (Collective2, FundSeeder) — do they support intraday?
   - Tax implications of Section 475(f) MTM election for mixed swing + intraday accounts

### Output Format for This Section
- Risk control checklist: control | purpose | implementation complexity | priority
- PDT compliance decision tree
- Transaction cost model: trades/day | avg slippage | annual cost at $100K | break-even Sharpe needed
- Desk isolation architecture recommendation

---

## Constraints on This Research

1. **Do not recommend strategies that require colocation, direct market access, or sub-millisecond latency.** We are retail, running on consumer hardware from a home office. Strategies must be viable at 100ms+ latency.

2. **Do not recommend data sources costing more than $500/month.** The system needs to be self-sustaining before scaling data costs. Prefer free or low-cost sources with upgrade paths.

3. **Do not recommend infrastructure that requires Kubernetes, cloud GPU clusters, or enterprise-grade message queues.** The system runs on one Windows 11 machine with one GPU. Infrastructure recommendations should work on this setup with a clear upgrade path.

4. **Do not assume IB is available.** IB integration is cold-stored through Phase 1. Research should assume Alpaca as the primary broker for intraday, with IB as a potential future upgrade.

5. **Be honest about what doesn't work at retail scale.** If a strategy or approach requires institutional infrastructure, say so and explain why. False hope is worse than no hope.

6. **Cite actual papers with dates.** "Studies show" is not acceptable. Provide author, year, title, and the specific finding being referenced. If the evidence is pre-2018, note that explicitly and assess whether it's likely still valid.

---

## Deliverable

A structured report (ideally 15-25 pages equivalent) covering all 5 research areas with the specified output formats. The report should end with:

1. **Executive summary:** Is an intraday desk feasible for a solo operator on consumer hardware? If yes, what's the most promising path? If partially, what's the minimum viable version?

2. **Architecture decisions to make NOW** (in Phase 1) that would keep the intraday door open vs accidentally close it. For example: should we be storing 1-minute bars now even though we don't trade on them yet?

3. **Estimated timeline and cost** to go from current state to a paper-trading intraday desk, broken into discrete milestones.

4. **Kill criteria:** What findings would indicate intraday is NOT feasible at our scale, and we should focus on the other desks instead?

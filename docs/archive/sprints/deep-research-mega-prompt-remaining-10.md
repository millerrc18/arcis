# Halcyon Lab — Combined Deep Research Brief (10 Topics)

I'm the solo founder of Halcyon Lab — an autonomous AI-powered equity trading system. S&P 100 universe, pullback-in-strong-trend strategy executed via Alpaca bracket orders. Locally fine-tuned Qwen3 8B model (Q8_0 GGUF, 8.7GB) via Ollama on RTX 3060 12GB, Windows 11. React dashboard on Render (halcyonlab.app). ~25 open positions, ~$100K paper + $100 live. Phase 1 (bootcamp), targeting 50-trade gate. 55 research documents, 1,064 tests, 141 Python files. Monthly cost ~$64. I work full-time at a defense contractor and operate Halcyon autonomously during market hours.

**Stack:** Python 3.12, FastAPI, SQLite (storage), DuckDB (analytics), APScheduler, Telegram notifications, 12 overnight data collectors, AI Council (5-agent Modified Delphi), Traffic Light regime system (VIX + 200-DMA + credit spread z-score), PEAD earnings enrichment, Implementation Shortfall tracking.

**Planned trajectory:** Phase 1 → 50-trade gate → Phase 2 (mean reversion strategy #2, universe expansion to ~325 stocks, Polygon.io data) → Phase 3 (evolved PEAD strategy #3, FinBERT NLP, options data collection) → Fund formation at sufficient track record + AUM.

I need comprehensive research on the following 10 topics. For each, provide: academic citations with effect sizes and replication status, concrete implementation recommendations with exact numbers, and code examples where applicable. Prioritize actionable findings over theoretical surveys. Every recommendation should be calibrated for a solo operator on consumer hardware.

---

## TOPIC 1: Market Microstructure of S&P 100 Stocks for Retail Algorithmic Trading

I trade S&P 100 stocks with 1-15 day holding periods via Alpaca bracket orders (market or limit-at-ask). I need to understand the microstructure landscape I'm operating in.

**Questions:**
1. What is the typical bid-ask spread for S&P 100 stocks in 2024-2026? How much does it vary by market cap quintile, time of day, and volatility regime?
2. At what position size does a retail trader start to experience market impact on S&P 100 stocks? For $1K-$10K individual positions?
3. Optimal execution timing: is there a best time of day for pullback entries? Academic evidence on intraday return patterns for large-cap US equities.
4. How do Alpaca's paper trading fills differ from live fills? The paper environment fills at infinite liquidity with ~50× latency difference. How should I discount paper trading results?
5. Market-on-open vs limit-at-ask vs VWAP for a system making 2-5 trades per day on S&P 100 stocks — which execution method minimizes implementation shortfall?
6. What is the actual slippage budget I should use for backtesting S&P 100 pullback trades? Published estimates from practitioners.

---

## TOPIC 2: Fund Formation Roadmap — From Solo Trader to Registered Investment Adviser

I plan to scale from solo trading to managing external capital. Current path: Wyoming LLC → incubator → fund. Break-even estimated ~$2M AUM. Capacity ceiling $500M-$1B+.

**Questions:**
1. Complete legal pathway: sole proprietor → LLC → LP/LLC fund → registered investment adviser (RIA). At what AUM does each transition make sense? Legal costs at each stage?
2. Track record requirements: how long and what format does a track record need to be for institutional allocators? Does paper trading count? When does the "official" track record start?
3. SEC registration thresholds: when do I need to register as an RIA? State vs federal registration. Exempt reporting adviser status.
4. Operational requirements for a fund: administrator, auditor, prime broker, legal counsel. Minimum viable versions for <$5M AUM.
5. Fee structures: 2/20 vs 1/10 vs flat fee for a quantitative strategy. What are institutional allocators looking for in 2026?
6. Insurance requirements: E&O, D&O, cyber. Costs for a solo-operated algorithmic fund.
7. Marketing restrictions: what can and can't I say about returns? Performance advertising rules. Use of AI/ML terminology.
8. Capital raising: realistic timeline from launch to $2M AUM for a solo quant with a verifiable track record. Channels: HNW, family offices, seeders, emerging manager platforms.

---

## TOPIC 3: SEC Enforcement Trends in AI-Powered Trading (2025-2026)

**Questions:**
1. Recent SEC AI Task Force cases and guidance. "AI-washing" enforcement actions. What claims about "AI-powered" returns cross legal lines?
2. FINRA rules applying to automated trading systems at retail scale. Do I need any registrations or filings for an autonomous system trading my own capital?
3. Algorithmic trading specific regulations: do any SEC or FINRA rules require disclosure, testing, or supervision of autonomous trading algorithms at the retail level?
4. Data privacy requirements: am I exposed to any risk by collecting SEC EDGAR filings, Finnhub data, and FRED macro data for algorithmic analysis?
5. "Inadvertent investment adviser" risk: at what point does sharing my system's signals (even informally) create regulatory exposure?
6. Patent landscape: are there patent risks in the LLM-for-trading space? Any recent filings I should be aware of?

---

## TOPIC 4: SQLite Performance at Scale and Migration Planning

My primary database is SQLite (ai_research_desk.sqlite3) with 35+ tables, WAL mode. DuckDB planned for analytics.

**Questions:**
1. SQLite WAL mode limits: maximum practical database size, maximum concurrent connections, row count per table where query performance degrades. At what scale do I need to worry?
2. My options_chains table will grow ~500K rows/year. At what row count does SQLite start struggling with this table? Query optimization strategies.
3. SELECT * queries without LIMIT in several places — impact on large tables? Which queries should I fix first?
4. Vacuuming and maintenance: optimal schedule for a database with continuous writes (13 scans/day, 12 overnight collectors). Auto-vacuum vs manual VACUUM?
5. Backup strategies during active writes: is copying the WAL file sufficient? Or do I need sqlite3_backup API?
6. PostgreSQL migration: what triggers should indicate it's time to migrate from SQLite to Postgres? Is Render Postgres the right target?
7. Data archival: old scan_metrics, recommendations, macro_snapshots accumulate forever. Archive strategy that preserves queryability for research but keeps the main DB fast?
8. FTS5 for text search across training examples and recommendations — worth implementing for my scale?

---

## TOPIC 5: Windows-Specific Reliability for 24/7 Autonomous Trading

My system runs 24/7 on Windows 11 with automated market-hours scanning and overnight data collection.

**Questions:**
1. Preventing Windows Update forced restarts: Group Policy settings, registry keys, and Windows Update for Business configurations that are actually reliable in 2025-2026.
2. NVIDIA driver management: should I pin a specific driver version? How to prevent auto-updates that could break CUDA/Ollama? Driver rollback procedures.
3. Ollama reliability on Windows: known VRAM leak issues, crash patterns, auto-restart strategies. Is there a watchdog pattern for keeping Ollama alive?
4. Python long-running process management: NSSM vs Windows Service vs Task Scheduler for a process that must survive reboots and run indefinitely. Which is most reliable for a Python trading system?
5. Sleep/hibernation prevention: reliable methods beyond powercfg. Does a Python script calling `SetThreadExecutionState` work? Registry overrides?
6. VRAM monitoring: how to detect when Ollama's VRAM usage grows unexpectedly and auto-restart before OOM? Windows-compatible monitoring tools.
7. Disk space monitoring: automated alerts when disk space drops below thresholds. Log rotation for halcyon.log.
8. Network reliability: detecting internet outages programmatically, switching to cellular backup, automatic reconnection.
9. UPS integration: can Windows signal a graceful shutdown when UPS battery drops below threshold? Integration with the trading system's kill switch.

---

## TOPIC 6: Render Deployment Optimization for Trading Dashboards

halcyonlab.app runs on Render (Starter plan). FastAPI backend, React frontend, Postgres for synced data.

**Questions:**
1. Render Starter plan behavior: cold starts, spin-down after inactivity, response time characteristics. How to prevent cold starts for a dashboard I check multiple times per day?
2. Postgres connection pooling on Render: is PgBouncer needed at my scale? Connection limit on Starter Postgres?
3. Sync optimization: currently polling SQLite → Postgres periodically. Is LISTEN/NOTIFY or change data capture practical? Or is polling every 5 minutes sufficient?
4. Static site deployment for the React frontend: can I use Render Static Site (free) for the frontend and keep only the API on the paid plan?
5. API response caching: which endpoints benefit from caching? How to implement with FastAPI.
6. WebSocket support on Render: can I implement real-time dashboard updates? Or is polling the only practical option?
7. Cost optimization: am I on the right plan? Could I use the free tier for anything?
8. SSL and security: any additional security configuration needed for a financial application dashboard?

---

## TOPIC 7: Automated Backtest Overfitting Detection Beyond Deflated Sharpe Ratio

I plan to validate Strategy #2 (mean reversion) and Strategy #3 (evolved PEAD) before deployment.

**Questions:**
1. CPCV (Combinatorial Purged Cross-Validation, López de Prado 2018): complete implementation for overlapping holding periods. How to handle my 1-15 day holds? Exact Python implementation with purging and embargo periods.
2. White's Reality Check: implementation for strategy selection from a candidate set. How many strategy variants am I implicitly testing when I tune 5 parameters?
3. Hansen's Superior Predictive Ability (SPA) test: when does this add value over White's Reality Check?
4. Minimum Backtest Length (Bailey & López de Prado): exact formula for my expected Sharpe ratios (0.7-1.0). How many months of data do I need for statistical significance?
5. Probability of Backtest Overfitting (PBO): implementation with a finite set of strategy configurations. How to estimate the probability that my in-sample Sharpe is illusory.
6. Haircut Sharpe ratio: how to compute for my specific setup (3 strategies, ~10 tunable parameters each, S&P 100 universe).
7. Synthetic data testing: generating realistic equity return series with known properties (regime switches, volatility clustering, fat tails) to test whether my strategies find edge in random data.

---

## TOPIC 8: Bayesian Methods for Small-Sample Trading Strategy Evaluation

With ~50 closed trades approaching, I need the most statistically rigorous evaluation framework possible.

**Questions:**
1. Bayesian Sharpe ratio estimation: how to incorporate informative priors from my 55 research documents (academic Sharpe ratios for pullback, mean reversion, PEAD strategies). Exact PyMC or NumPyro implementation.
2. Beta-Binomial model for win rate: more appropriate than frequentist confidence intervals with small N. Implementation and interpretation.
3. Bayesian regime detection: posterior probability of being in each regime (bull/bear/transition) given observed returns. Comparison to our Traffic Light system.
4. Bayesian strategy comparison: Bayes factors for comparing pullback vs mean reversion performance. When can I confidently say one strategy is better than another?
5. Sequential testing for phase gates: instead of waiting for exactly 50 trades, can I do sequential Bayesian testing that gives me a decision sooner if evidence is strong?
6. Prior elicitation: how to formally extract priors from my research library. The academic literature gives me expected Sharpe ratios, win rates, and holding periods for each strategy type. How to encode these as informative priors?
7. PyMC vs Stan vs NumPyro: which is best for financial applications on Windows with CUDA? Installation and practical comparison.

---

## TOPIC 9: Cognitive Biases in Algorithmic Trading System Design

I'm a solo operator making decisions about my own trading system. I need to understand how cognitive biases affect system design decisions specifically.

**Questions:**
1. Anchoring to backtest results: how does anchoring bias affect parameter selection? Documented cases where quants anchored to in-sample performance and failed out-of-sample.
2. Sunk cost with failing strategies: at what point should I abandon a strategy vs give it more time? Decision framework that accounts for sunk cost bias.
3. Overconfidence from early wins: if my first 20 trades are profitable, how much should I update my beliefs? The Bayesian answer vs the human tendency.
4. Recency bias in parameter tuning: tendency to weight recent performance too heavily when adjusting parameters. How to build guardrails.
5. "Broken system vs bad regime" confusion: the hardest problem. My strategy underperforms for 3 months — is the edge gone, or is it a regime the strategy wasn't designed for? Decision framework.
6. Automation bias: trusting the AI's output too much. How to maintain healthy skepticism about LLM-generated trade commentary.
7. Pre-commitment devices: specific techniques for binding future-self to current decisions. Decision journals, parameter freeze periods, pre-registered analysis plans.
8. What rules should I write NOW to constrain my future biased self? Specific policies for parameter changes, strategy abandonment, capital allocation changes.

---

## TOPIC 10: Competitive Intelligence — AI Trading Systems in 2026

I need to understand the competitive landscape for AI-powered trading systems.

**Questions:**
1. Open-source LLM trading projects on GitHub: most starred/active projects, their architectures, any published live results. Trading-R1, FinRL, Fin-o1 — current status in March 2026.
2. AI-powered hedge funds launched 2024-2026: which survived? What strategies? AUM growth trajectories?
3. Solo quant operator trajectories: documented cases of solo operators who scaled from personal capital to fund management. What did their paths look like? Common failure points?
4. Retail algorithmic trading platform AI integrations: has Alpaca, Interactive Brokers, or any major retail platform integrated LLM-based analysis? Does this commoditize my edge?
5. Institutional LLM adoption: any public information about Citadel, Two Sigma, DE Shaw, or other major quant firms using LLMs for trading? How does this affect the alpha landscape?
6. Failure post-mortems: Quantopian shut down. Other algo trading platforms/funds that failed. Why? What are the survivor characteristics?
7. Patent landscape: are there patents on LLM-based trading that could be enforced? Any litigation trends?
8. Moat analysis: given the competitive landscape, what is Halcyon Lab's realistic moat? Is it the data asset, the fine-tuned model, the autonomous execution, the multi-strategy architecture, or something else?

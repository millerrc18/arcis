# Halcyon Lab — Scaling Plan Through December 31, 2026

*From $1,000 paper trading to a self-sustaining AI research desk*
*Baseline: March 2026 — Milestone 1 complete, RTX 3060 12GB, S&P 100 universe*

---

## The governing principle: scale nothing faster than your evidence

Every scaling decision in this plan is gated by demonstrated performance, not calendar dates. Hardware gets upgraded only when the current hardware is provably the bottleneck. Data subscriptions get added only when the free tier is provably insufficient. Capital gets increased only when the system has a statistically meaningful track record. The single most dangerous failure mode for Halcyon Lab is not under-investing — it's over-investing ahead of validation, which creates psychological pressure to force trades and skip quality gates to justify the spend.

The plan is organized into four phases, each with explicit entry criteria. You don't advance to the next phase until the current phase's exit conditions are met. Calendar estimates are provided for planning purposes, but the gates are performance-based, not time-based.

---

## Current baseline inventory

Before planning what to buy, here's what you're working with today:

**Hardware**: RTX 3060 12GB, desktop PC (assumed ~32GB RAM, ~500GB-1TB NVMe). Running Windows 11.

**Software stack**: Python, SQLite, Alpaca paper trading, vectorbt, Ollama (Qwen3 8B), Unsloth/QLoRA, SMTP email delivery.

**Data sources**: yfinance (free, OHLCV), Claude API Haiku 4.5 (~$0.07/day for training data generation).

**Monthly operating cost**: ~$2/month (Claude API) + $0/month (free data tier) + electricity.

**Trading capital**: $1,000 (paper). $0 live.

---

## Phase 1 — Prove the system works (Now through ~June 2026)

### What this phase is about

Complete the build through Milestone 2 (first real packet from real data), run the 30-day bootcamp, and generate enough shadow trading data to know whether the system produces actionable, profitable signals. No new hardware. No paid data. No live capital. Pure validation on what you already have.

### Entry criteria
- Milestone 1 complete (done)

### Exit criteria (all must be met)
- Bootcamp complete (30 days of shadow trading data)
- Minimum 50 closed shadow trades with full postmortem data
- Shadow Sharpe ratio > 0.5 (annualized, on paper trades)
- Win rate > 45% with positive expectancy
- At least one successful model retrain cycle completed end-to-end
- LLM packet quality rated by you as "would act on this" for >60% of packets

### Hardware purchases: $0

The RTX 3060 12GB is sufficient for everything in this phase. You're running Qwen3 8B inference during market hours (light load, ~10-15 seconds per packet) and training overnight/weekends. The 12GB VRAM handles both fine. This is not the time to buy a GPU — you need to prove the system produces signal before investing in faster signal production.

### Data subscriptions: $0/month

yfinance provides adequate daily OHLCV data for the S&P 100. The free tiers of Finnhub (60 calls/min), Alpha Vantage (500 calls/day), and FMP (250 calls/day) are sufficient for supplementary data during bootcamp. SEC EDGAR is free and unlimited (10 req/sec with User-Agent header). FRED API is free (120 req/min) for macro data.

### Storage needs: No action needed

Rough estimate of data generated during bootcamp: daily OHLCV for 100 tickers × 30 days is trivial (< 1 MB). Training examples at 500 synthetic + ~50 real outcomes × ~2KB each = ~1 MB. SQLite journal with 50 trades, packets, postmortems = < 50 MB. Model checkpoints (GGUF files ~6GB each, keep 3 versions) = ~18 GB. Total new storage: < 20 GB. Your existing drive handles this without thinking about it.

### Software milestones
- Complete SMTP email delivery
- True S&P 100 universe ingestion
- Daily OHLCV data pipeline
- Feature engine (trend, RS, pullback, ATR)
- Deterministic ranking and qualification
- Real packet generation with LLM
- Journal logging to SQLite
- Shadow trading via Alpaca paper
- 30-day bootcamp execution

### Monthly cost: ~$2-5
- Claude API for training data generation: ~$2/month
- Electricity for overnight GPU training: ~$3/month
- Everything else: $0

### Risk to watch for
The temptation to skip bootcamp or cut it short because "it's just paper trading." Don't. The 30-day bootcamp is the most important data collection period in the entire project. Every shortcut here propagates downstream into flawed training data, miscalibrated thresholds, and false confidence.

---

## Phase 2 — First live capital + first hardware upgrade (~July–September 2026)

### What this phase is about

The system has proven it generates positive expectancy on paper. Now you put small real money behind it, add the first paid data source for reliability, and make the GPU upgrade that's been the obvious bottleneck since day one.

### Entry criteria
- All Phase 1 exit criteria met
- Shadow trading track record of 50+ closed trades with positive expectancy

### Exit criteria
- 30+ live trades executed (you acting on packets)
- Live trade results within 1 standard deviation of shadow performance
- RTX 3090 installed and validated (14B model running, training times halved)
- At least 2 model retraining cycles on real outcome data completed
- Training dataset grown to 1,000+ examples (synthetic + real outcomes)

### Hardware purchase: RTX 3090 24GB (~$700-900 used)

This is the single highest-ROI upgrade for the entire system. The used RTX 3090 market is currently in the $600-1,000 range on eBay, with the sweet spot around $700-800 for a well-maintained card from a reputable seller.

**What it unlocks:**
- Qwen 2.5 14B runs comfortably for inference (vs. barely fitting on the 3060)
- Fine-tuning the 14B model with batch_size=2 and seq_len=2048 (vs. batch=1, seq_len=1024)
- 8B model trains with LoRA rank 64, batch_size=4, seq_len=4096 — dramatically better gradient estimates
- Overnight training runs finish 40-60% faster
- Headroom to experiment with Qwen3 30B-A3B MoE (~18.6 GB, currently impossible)

**What to check before buying:**
- Your PSU must handle 350W TDP. If your current PSU is under 750W, budget $80-120 for a quality 850W unit (e.g., Corsair RM850x). A 1000W PSU gives more headroom and is recommended if you're buying new.
- Your case must fit a 3-slot, 313mm card. Measure clearance.
- Check that your motherboard has a PCIe x16 slot (it almost certainly does if you're running a 3060).

**Budget line item**: ~$700-900 for the GPU + $0-120 for PSU if needed. Call it $800-1,000 total.

**What NOT to buy**: An RTX 4070 Ti Super (16GB, ~$800 new — not enough VRAM improvement to justify the cost). An RTX 4090 (24GB but ~$2,500+ used — same VRAM as the 3090 at 3x the price, the extra compute speed doesn't matter for your workload). An RTX 5080 (16GB, $1,000+ — again, VRAM is your bottleneck, not raw compute).

### Data subscription: Polygon.io Stocks Starter — $29/month

yfinance is adequate for backtesting but unreliable for a production daily pipeline. It rate-limits aggressively, has occasional data gaps, and returns inconsistent results under load. Polygon's Starter plan ($29/month, or ~$23/month billed annually) provides unlimited API calls, 5 years of historical data, 15-minute delayed quotes, and WebSocket support. This replaces yfinance as your primary price data source and gives you a reliable foundation.

Why not the free tier? Polygon's free tier caps you at 5 calls/minute and 2 years of history — too restrictive for computing features across 100 tickers with adequate lookback periods.

Why not the $79 Developer tier? You don't need tick data or 10 years of history yet. The Starter plan covers daily OHLCV and minute aggregates, which is all your feature engine requires. Upgrade later if needed.

### Storage: No action needed yet

Your training dataset will grow to ~1,000 examples (~2-5 MB). Model versions will accumulate (budget ~6-9 GB per GGUF checkpoint, keep 5 versions = ~45 GB). Journal data grows modestly. Total incremental: < 60 GB. Still well within any modern NVMe's capacity.

### Capital deployment: $1,000 live (your existing stake)

Start executing real trades with your original $1,000 allocation. Max 2 positions, 1% risk per trade ($10 max loss per position). This is not about making money — it's about validating that live execution matches shadow performance. Track slippage, fill quality, and the psychological difference between paper and live execution.

**Do not add capital in this phase.** The $1,000 is a calibration instrument, not an investment. If it goes to $0, you've spent $1,000 to learn the system doesn't work yet, which is valuable information.

### Monthly cost: ~$35-40
- Polygon.io Starter: $29/month
- Claude API: ~$2-5/month
- Electricity: ~$5/month

### Risk to watch for
Confirmation bias after going live. The system will produce losses. Some packets will be wrong. If you find yourself rationalizing every loss or tweaking thresholds after each losing trade, stop trading and return to shadow-only mode. The point of this phase is to observe, not to optimize in real-time.

---

## Phase 3 — Scale what's working (~October–November 2026)

### What this phase is about

You now have 3+ months of live trading data alongside shadow data. The model has been retrained multiple times on real outcomes. You know which setups work and which don't. This phase is about responsibly increasing capital, enriching the data pipeline, and hardening the system for reliability.

### Entry criteria
- 30+ live trades with positive expectancy confirmed
- Live performance within reasonable range of shadow performance
- At least 3 model retraining cycles completed with measurable improvement
- Training dataset at 2,000+ examples
- Confidence that the edge is real, not a hot streak

### Exit criteria
- Capital grown to $2,500-5,000 (through combination of profits and additional allocation)
- Training dataset at 3,000-5,000 examples
- Multi-source data pipeline operational (price + fundamentals + news)
- System running unattended for 2+ weeks without manual intervention
- Backup and recovery procedures tested

### Hardware: RAM upgrade if needed — $60-100

If you're running 32GB, you're fine. If you're at 16GB, upgrade to 32GB (DDR4 2x16GB kit ~$60-80, DDR5 ~$80-120, though prices are elevated due to AI-driven NAND/DRAM shortages). 32GB is sufficient for Ollama inference + Python pipeline + OS overhead. 64GB is only worth it if you want to experiment with CPU offloading for 30B+ models, which isn't on the critical path.

### Storage: 2TB NVMe — $150-250

By this point, your storage footprint is growing meaningfully. Model checkpoint history (keeping 10+ versions for rollback = ~60-90 GB), SEC EDGAR filings for the S&P 100 (10-K, 10-Q, 8-K filings = several GB), earnings transcripts, training dataset snapshots, and backtest results all add up. SSD prices are currently elevated due to NAND shortages (2TB NVMe drives running $150-250 for PCIe Gen4, up from ~$100 in late 2024). A 2TB drive gives comfortable headroom.

**If you already have 2TB or more**, skip this. If you're on a 500GB or 1TB drive, this is worth doing now before storage becomes an operational annoyance.

### Data subscriptions: Add FMP Starter — $22/month (annual billing)

FMP's Starter plan adds fundamental data that your feature engine needs for the next level of sophistication: quarterly financial statements (income, balance sheet, cash flow), analyst estimates, earnings calendars, insider trading data, and financial news. This is the single cheapest path to adding fundamental signals alongside your existing technical setup.

Combined with Polygon (price data) and the free tiers of Finnhub (earnings transcripts, analyst recommendations, congressional trades) and FRED (macro data), you now have a multi-source data stack that covers ~80% of what institutional desks use.

### Data enrichment: SEC EDGAR pipeline — $0

Build the automated SEC filing retrieval pipeline. The EDGAR full-text API at data.sec.gov requires no API key, just a User-Agent header with your email. Pull 10-K, 10-Q, and 8-K filings for S&P 100 constituents. Parse with EDGAR-CRAWLER (open source) into structured JSON. This feeds your training pipeline with fundamental context that makes trade commentary dramatically more substantive.

### Capital scaling: $2,500-5,000

If Phase 2 produced a positive track record across 30+ live trades, scale capital in steps. The specific amount depends on what you're comfortable allocating, but the system is designed for $1,000 starting capital with 1% risk per trade. At $5,000, that's $50 max risk per position — still very conservative, still 2 max positions.

**Scale rule**: Never more than double capital in a single step. $1,000 → $2,500 → $5,000. Each step requires 20+ trades at the new level before increasing again.

### Reliability hardening

This is the phase where you stop babysitting the system and start trusting it to run unattended:

**UPS (uninterruptible power supply)**: $80-150 for a 1000VA/600W unit (e.g., CyberPower CP1000PFCLCD). Protects against power outages during overnight training runs that could corrupt model files or the SQLite database. Not glamorous, but a corrupted mid-training checkpoint is a miserable debugging experience.

**Automated backups**: Set up a nightly cron job that backs up your SQLite database, settings, and the latest model checkpoint to a separate drive or cloud storage. GitHub already tracks your code, but your data and models are the irreplaceable assets. Budget $5/month for 100GB of Backblaze B2 or similar cold storage.

**Monitoring**: Simple systemd service or cron-based watchdog that alerts you (via the existing SMTP pipeline) if the scan loop hasn't run in 2 hours, if Ollama isn't responding, or if disk space drops below 50GB.

### Monthly cost: ~$65-80
- Polygon.io Starter: $29/month
- FMP Starter: $22/month
- Claude API: ~$5/month
- Cloud backup: $5/month
- Electricity: ~$5-10/month

### Risk to watch for
Scope creep. With faster hardware, more data, and real capital at work, the temptation to expand the universe beyond S&P 100, add options, or build a dashboard intensifies. Resist. Every hour spent on a dashboard is an hour not spent improving training data quality. The charter says S&P 100, pullback-in-strong-trend setups, max 2 positions. Stay there until the system is profitable enough to justify expansion.

---

## Phase 4 — Optimize and compound (~December 2026)

### What this phase is about

The system has been running live for 3-5 months. You have real P&L data. The model has gone through multiple retraining cycles on real outcomes. This phase is about optimizing what works, beginning to build the competitive moat described in the training data strategies document, and setting yourself up for the 2027 iteration.

### Entry criteria
- 3+ months of live trading with positive expectancy
- Training dataset at 3,000+ examples including real outcomes
- System running reliably with minimal manual intervention
- Clear understanding of which setups are profitable and which aren't

### Exit criteria (for the December 31, 2026 checkpoint)
- Documented track record: total trades, win rate, expectancy, Sharpe ratio, max drawdown
- Model version history showing measurable improvement over time
- Written assessment: what's working, what's not, what to change for 2027
- Decision on whether to continue scaling or pivot the approach

### Hardware: No new purchases

The RTX 3090 handles everything needed through year-end. If the system is profitable and you're planning aggressive 2027 scaling, you might start researching dual-GPU setups or a dedicated training server, but don't buy anything until the 2027 plan is written.

### Data: Consider upgrading Polygon to Developer ($79/month)

Only if you're finding that 5 years of historical data isn't enough for backtesting or that you need tick-level data for more precise entry/exit timing. Otherwise, stay on Starter. The $50/month difference funds a lot of Claude API calls for training data generation.

### Advanced training techniques

With 3,000+ real examples, you can now implement the advanced training strategies from the project's training data document:

**DPO alignment**: Generate 2,000+ preference pairs from your existing packet history — pair a good trade thesis (one where the model identified the right setup and the trade worked) with a weaker one (similar setup, worse reasoning or wrong conclusion). This teaches the model to prefer higher-quality analytical reasoning.

**GRPO reinforcement**: If Unsloth's GRPO support is mature enough, run GRPO with volatility-adjusted outcome rewards. This is the technique that Fin-o1 used to outperform GPT-o1 on financial reasoning benchmarks.

**Regime-specific LoRA adapters**: If you've observed that the system performs differently in trending vs. range-bound markets, train separate LoRA adapters for each regime (~50-200MB each). Hot-swap based on a simple regime classifier. This is the "poor man's MoE" concept from the training strategies document.

### Capital: Determined by track record

If the system has been consistently profitable: consider scaling to $10,000. If it's been breakeven: stay at current levels and focus on model improvement. If it's been losing: stop live trading, return to shadow-only, and diagnose what's wrong before the year ends.

**The December 31 checkpoint is about honest assessment, not about hitting a capital target.**

### Monthly cost: ~$65-130
- Polygon.io Starter or Developer: $29-79/month
- FMP Starter: $22/month
- Claude API: $5-10/month (higher if generating DPO pairs)
- Cloud backup: $5/month
- Electricity: ~$5-10/month

---

## Cumulative investment summary

| Category | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Total by Dec 31 |
|----------|---------|---------|---------|---------|-----------------|
| GPU | $0 | $700-900 | $0 | $0 | $700-900 |
| PSU (if needed) | $0 | $0-120 | $0 | $0 | $0-120 |
| RAM (if needed) | $0 | $0 | $60-100 | $0 | $0-100 |
| Storage (if needed) | $0 | $0 | $150-250 | $0 | $0-250 |
| UPS | $0 | $0 | $80-150 | $0 | $80-150 |
| **Hardware subtotal** | **$0** | **$700-1,020** | **$290-500** | **$0** | **$780-1,520** |
| Data subscriptions (cumulative monthly) | $0 | $29 | $51 | $51-79 | — |
| Cloud backup (monthly) | $0 | $0 | $5 | $5 | — |
| Claude API (monthly) | $2-5 | $2-5 | $5 | $5-10 | — |
| **Monthly opex** | **$2-5** | **$31-34** | **$61-75** | **$61-94** | — |
| **Cumulative opex (through phase end)** | **~$15** | **~$120** | **~$200** | **~$280** | **~$600-700** |
| **Total all-in by Dec 31** | — | — | — | — | **~$1,400-2,200** |

Trading capital is excluded from this table because it's not an expense — it's working capital that (ideally) grows.

---

## What you explicitly do NOT need by December 31, 2026

It's worth being specific about what's out of scope, because these are the things that feel like they should be next but would be premature:

**A second GPU or dedicated training server.** The RTX 3090 handles both inference and training, just not simultaneously. Your schedule already separates them (inference during market hours, training off-hours). A second GPU only makes sense when you need to train while simultaneously serving inference during market hours, which requires either much higher trade volume or a larger model that takes many hours to train.

**A cloud GPU instance.** At your current training frequency (weekly or biweekly retraining on < 10,000 examples), a local RTX 3090 is dramatically cheaper than cloud GPU time. A Lambda Cloud A100 runs $1.10/hour — your 6-hour weekend training run costs $6.60 in cloud vs. ~$0.50 in electricity locally. The breakeven favors local for years.

**A database upgrade from SQLite.** SQLite handles millions of rows, supports concurrent reads, and requires zero administration. Your S&P 100 universe with 15-day trade timeout generates maybe 500-2,000 trades per year. PostgreSQL or similar adds complexity with zero benefit at this scale. Revisit only if you expand to a universe of 500+ tickers with intraday data storage needs.

**A web dashboard.** The CLI and email pipeline are your interface. A dashboard consumes development time that should go toward training data quality and model improvement. If you want visibility, a weekly automated report email covers it.

**Live options trading, margin, or multi-asset expansion.** The charter explicitly excludes these. The entire system is designed around single-stock long-only equity positions with fixed risk. Adding complexity to the trading strategy before the base case is proven is how research projects die.

**Expanding beyond S&P 100.** The universe is intentionally constrained to the most liquid, well-covered stocks with the most available data. Expanding to S&P 500 or small caps introduces data quality issues, liquidity risk, and much harder-to-model price dynamics. The S&P 100 universe is a feature, not a limitation.

**An LLC or business entity.** Not until there's meaningful P&L to protect and tax-optimize. Forming an entity ahead of profitability creates administrative overhead and annual filing costs with no upside.

---

## Decision tree for unplanned situations

**The system is profitable and you want to scale faster**: Increase capital allocation in 2x steps (per the scaling rule), but don't skip hardware or data phases. The bottleneck is almost always training data quality, not hardware speed or capital size.

**The system is losing money**: Stop live trading immediately. Return to shadow-only. Analyze whether the losses are from bad setups being recommended (model problem), good setups with bad execution (process problem), or a market regime that doesn't suit pullback strategies (environment problem). Do not add capital to a losing system.

**A data source goes down or becomes unreliable**: This is why you maintain free-tier fallbacks. yfinance remains a backup for Polygon. FMP free tier (250 calls/day) covers basic fundamentals in a pinch. Build your pipeline with graceful degradation — if a source fails, the system should skip that data enrichment and continue with what it has, flagging the gap in the packet.

**Your RTX 3060 dies before you buy the 3090**: Buy the 3090 immediately rather than replacing the 3060. The cost difference is $300-400 and you were going to buy it anyway.

**SSD prices keep rising**: If 2TB NVMe drives hit $300+, consider a large HDD ($50-80 for 4TB) for cold storage of model checkpoints and historical data, keeping only active data on NVMe. Alternatively, lean harder on cloud backup (Backblaze B2 at $0.005/GB/month = $5/month for 1TB).

**A dramatically better model architecture is released**: Evaluate whether it fits in 24GB VRAM. If yes, test it in shadow mode for 2 weeks before touching your production model. If it requires 48GB+, ignore it — your competitive advantage is training data quality on a good-enough architecture, not chasing the frontier model.

---

## The December 31, 2026 checkpoint

On December 31, sit down and answer these questions honestly:

1. **Is the system profitable?** Total P&L across all live trades, net of commissions and data costs.
2. **Is the edge stable?** Is monthly expectancy consistently positive, or is the total P&L driven by a few big winners?
3. **Is the model improving?** Do newer model versions produce better trade outcomes than older ones?
4. **Is the training data flywheel working?** Are real outcome examples producing measurably better model performance than synthetic-only training?
5. **What's the Sharpe ratio?** Below 0.5 = the strategy may not have a real edge. 0.5-1.0 = promising but needs work. Above 1.0 = strong foundation to scale.
6. **What would you do differently?** This becomes the foundation of the 2027 plan.

If the answers are positive, the 2027 plan involves scaling capital, potentially expanding the universe, and investing in the advanced training techniques (GRPO, RAFT, regime-specific adapters) that turn a working system into a compounding one. If the answers are negative, the 2027 plan involves diagnosing what's broken before spending another dollar.

Either way, you'll have 9 months of data, a proven pipeline, and a clear picture of what Halcyon Lab actually is versus what you hoped it would be. That clarity is worth more than any piece of hardware.

---

*Halcyon Lab — Quality over quantity, evidence over ambition*

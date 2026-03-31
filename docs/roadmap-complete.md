# Arcis — Complete Roadmap (Research-Informed)
## Updated March 27, 2026

> Every gate is performance-based, not time-based. Quarters are estimates; actual timelines depend on trade accumulation and gate metrics. Sources cited for every decision.

---

## Phase 1 — Bootcamp (CURRENT)
**Capital:** $100K paper + $100 live (Alpaca)
**Monthly cost:** ~$64 (Render $14, Claude API ~$50)
**Timeline estimate:** Apr–Jun 2026
**Objective:** Prove the system has an edge. Accumulate 50+ closed trades.

### Items
**Strategy & Execution:**
- [x] Pullback-in-uptrend strategy on S&P 100 (~103 tickers)
- [x] Mechanical bracket orders (1-2 ATR stop, 2-3 ATR target, 15-day timeout)
- [x] Dual execution: paper + live with separate risk params
- [x] Fractional share support for $100 live account
- [x] Risk governor (8 hard limits) + bootcamp overrides
- [x] Setup classifier (6 types: pullback, breakout, momentum, mean_reversion, range_bound, breakdown)
- [x] Signal zoo logging all setup types every scan
- [ ] Thorp-style graduated drawdown reduction *(Risk research: Ed Thorp protocol)*
- [ ] LLM output validation layer *(Risk research: prevent hallucination-driven trades)*
- [ ] Technical-fundamental divergence scoring *(SEC EDGAR research: "most novel feature")*

**AI & Training:**
- [x] Qwen3 8B fine-tuned via QLoRA (halcyon-v1, 978 examples)
- [x] Self-blinding training pipeline (architectural, not instructional)
- [x] 3-stage curriculum (structure → evidence → decision)
- [x] AI Council (5 agents, Modified Delphi, Claude Sonnet)
- [x] Quality pipeline + LLM-as-judge rubric
- [x] Leakage detector (TF-IDF balanced accuracy >65% = alarm)
- [x] Quality drift monitoring (distinct-2, self-BLEU)
- [x] Between-scan scoring (Ollama, already loaded in VRAM)
- [ ] Training data format cleanup (fix 62% template fallback root cause)
- [ ] Curriculum stage assignment based on data richness
- [ ] Regime context backfilled into 704 historical examples
- [ ] PASS example generation (teach model when NOT to trade) *(Perplexity: "reduces over-trading")*
- [ ] DPO pair auto-generation trigger *(Training research: Trading-R1 Sharpe 2.72)*

**Data Infrastructure:**
- [x] 12 overnight data collectors (options, VIX, CBOE, FRED 33 series, trends, earnings, EDGAR, insider, short interest, Fed comms, analyst estimates)
- [x] 7-source data enrichment (technicals, fundamentals, insider, macro, news, regime, sector)
- [ ] Research intelligence collector (#13: arXiv, SSRN, HuggingFace, Reddit, GitHub, AI blogs, SEC/FINRA)
- [ ] SEC EDGAR NLP features (L-M dictionary sentiment + cautionary phrases) *(SEC research: CPU-only, milliseconds)*
- [ ] XBRL fundamental snapshots from companyfacts.zip *(SEC research: replaces hundreds of API calls)*
- [ ] Slippage tracking (signal vs fill price on every trade) *(Risk research: essential for concordance testing)*

**Dashboard & Operations:**
- [x] halcyonlab.app live (Render, Arcis brand, 13 pages)
- [x] Telegram notifications (22/27 types wired)
- [x] PWA installable
- [x] Cloud auth (Bearer token, localStorage 7-day)
- [x] Render sync (17 tables, every 2 min)
- [ ] Cloud API completion (19 GET endpoints + 12 POST stubs)
- [ ] Dashboard 2.0 (market overview, position monitor, earnings calendar, macro page, etc.)
- [ ] Telegram admin commands (/pull, /logs, /gpu, /restart)
- [ ] Comprehensive observability (scan funnel, LLM stats, feature timing, activity log)
- [ ] Architecture visualizations (roadmap timeline, scan pipeline, compute schedule)

**Validation:**
- [ ] Statistical validation framework (PSR, DSR, bootstrap Sharpe CIs, MinTRL) *(Walk-forward research: Lo 2002, Bailey & López de Prado 2014)*
- [ ] Random-entry benchmark (1000 simulations, same exit rules) *(Walk-forward research: "single most informative test")*
- [ ] 50-trade gate evaluation script (automated PASS/FAIL) *(Walk-forward research: 6 metrics)*
- [ ] Monthly performance report generator *(Walk-forward research: GIPS-principled from day 1)*
- [ ] CUSUM/SPRT performance change detection *(Walk-forward research: López de Prado AFML Ch.17)*

**Infrastructure:**
- [ ] SQLite WAL mode + automated daily backups *(Risk research: 50% of hedge fund failures are operational)*
- [ ] Auto-create missing tables on watch loop startup
- [ ] Unified `train-pipeline` CLI command

### Gate Metrics *(Walk-forward research: "lenient screening, not verdict")*
| Metric | 🟢 PASS | 🟡 WATCH | 🔴 FAIL |
|--------|---------|----------|---------|
| Win rate (with 2:1 R:R) | ≥ 45% | 38–44% | < 38% |
| Profit factor | ≥ 1.3 | 1.1–1.3 | < 1.1 |
| Expectancy per trade | ≥ +0.20R | +0.05R to +0.20R | ≤ +0.05R |
| Max drawdown | ≤ 12% | 12–18% | > 18% |
| Per-trade Sharpe | ≥ 0.15 | 0.05–0.15 | < 0.05 |
| Net P&L | Clearly positive | Slightly positive | Negative |

**Decision:** 4+ GREEN with 0 RED → proceed. Mixed → extend to 75 trades. Any RED → root cause. 2+ RED → fundamental revision.

---

## Phase 2 — Micro Live + LLC Formation
**Capital:** $100 → $1,000 live (Alpaca via LLC)
**Monthly cost:** ~$125 (Render $14, Polygon $29, Claude API ~$50, LLC $5, CPA $30)
**Timeline estimate:** Jul–Sep 2026
**Objective:** Validate edge with real money. Form legal entity. Hit 100+ live trades.

### Items
**Legal & Tax:** *(LLC research: Wyoming LLC + Section 475 MTM)*
- [ ] Form Wyoming LLC online ($100 + $60/yr annual report)
- [ ] Engage registered agent ($25-125/yr; Wyoming Registered Agent Services or Rocky Mountain)
- [ ] Apply for EIN (free, instant at irs.gov)
- [ ] Draft operating agreement (specify algorithmic trading, API execution, disregarded entity)
- [ ] Open business bank account (Mercury or Relay, $0/mo)
- [ ] Open Alpaca LLC brokerage account (may require $30K minimum — verify)
- [ ] File Section 475(f) MTM election within 75 days of formation
- [ ] Begin time-log documentation for trader tax status (target 75%+ market days active)
- [ ] Review defense contractor employment agreement for outside business disclosure
- [ ] Engage CPA specializing in trader taxation ($500-2K first year)

**Strategy Expansion:**
- [ ] Expand universe from ~103 to ~325 stocks *(Universe research: optimal filtered S&P 500)*
- [ ] Begin breakout signal zoo accumulation (passive logging during every scan) *(Breakout research: 3-6 month data build)*
- [ ] Paper-to-live concordance testing (KS test, mean ΔR, confidence intervals) *(Walk-forward research)*
- [ ] Scale live account $100 → $1,000 at Gate 1 metrics

**Data & Market Access:**
- [ ] Add Polygon.io Starter ($29/mo), demote yfinance *(Data infrastructure audit: more reliable, real-time)*
- [ ] Add SEC EDGAR full pipeline: FinBERT section-level sentiment (110M params, ~440MB VRAM) *(SEC EDGAR research: 88.2% accuracy vs 62.1% for L-M dictionary)*
- [ ] Filing diff: cosine similarity between consecutive filings (TF-IDF vectors) *(SEC EDGAR research: "Lazy Prices" methodology adapted)*
- [ ] Add Unusual Whales passive options data collection ($50/mo) *(Options research: start Phase 2, build before Phase 3)*
- [ ] Interactive Brokers paper account (active, for Phase 3 readiness)

**Risk Management:** *(Risk research: Phase 2 priorities)*
- [ ] Parametric VaR with Ledoit-Wolf shrinkage covariance (daily portfolio risk number)
- [ ] Correlation-adjusted position sizing (sliding scale: <0.3=100%, 0.3-0.5=75%, 0.5-0.7=50%, >0.7=25%)
- [ ] HHI concentration monitoring (target <0.04, alert >0.06)
- [ ] Historical stress testing — 7 scenarios nightly (2008 GFC, 2015 China, 2018 Q4, 2020 COVID, 2022 bear, 2024 yen unwind, 2025 Liberation Day)
- [ ] Component VaR per position (risk attribution by position)
- [ ] Monte Carlo VaR (10K simulations, ~1-2 seconds for 50 assets)
- [ ] CVaR (Expected Shortfall) alongside all VaR measures *(Risk research: Basel III replaced VaR with 97.5% ES)*
- [ ] Dead man's switch (separate watchdog process on Raspberry Pi or $5/mo cloud VM)
- [ ] Bootstrap VaR on trade history (once 50+ trades)

**Training Data Growth:** *(Perplexity playbook: target 3,000-3,500 examples by end of Phase 2)*
- [ ] Cap synthetic corpus at ~2,500 (replace low-quality, don't grow)
- [ ] DPO pair generation from live trade outcomes (~$15 API)
- [ ] Quality-score all examples with Claude API
- [ ] Regime-diverse examples targeting underrepresented periods
- [ ] PASS/timeout examples at scale (every rejected setup = PASS example)

**Operations:**
- [ ] Research Analyst desk: second Alpaca paper account, relaxed thresholds, `--config` flag *(Multi-desk architecture)*
- [ ] Quarterly estimated tax payments if needed (September 15, January 15)
- [ ] Cellular internet failover via USB 4G/5G modem *(Risk research: ~$400-600/yr)*

### Gate Metrics *(Walk-forward research: 100-trade checkpoint)*
| Metric | 🟢 PASS | 🟡 WATCH | 🔴 FAIL |
|--------|---------|----------|---------|
| Win rate | ≥ 43% | 38–42% | < 38% |
| Profit factor | ≥ 1.4 | 1.15–1.4 | < 1.15 |
| Expectancy per trade | ≥ +0.25R | +0.10R to +0.25R | ≤ +0.10R |
| Max drawdown | ≤ 15% | 15–22% | > 22% |
| Annualized Sharpe | ≥ 1.0 | 0.5–1.0 | < 0.5 |
| PSR(0) | ≥ 90% | 75–90% | < 75% |
| Calmar ratio | ≥ 1.0 | 0.5–1.0 | < 0.5 |
| Paper-live concordance | Mean ΔR not significantly negative | Marginal | Significant negative bias |

**Decision:** 6+ GREEN → proceed. Mixed → extend to 150 trades. Any RED → root cause.
**Capital gate:** Scale $100→$1,000 requires: 100+ live trades, PSR >90%, DD <15%, no severe paper-live divergence.

---

## Phase 3 — Growth + Second Strategy
**Capital:** $1,000 → $5,000 live
**Monthly cost:** ~$155 (Render $14, Polygon $29, Claude API ~$50, Unusual Whales $50, LLC $5, misc $7)
**Timeline estimate:** Oct 2026 – Mar 2027
**Objective:** Scale capital. Launch breakout strategy on paper. Hit 200+ trades for edge confirmation.

### Items
**Breakout Strategy:** *(Breakout research: 9-12 month timeline, BB squeeze + volume confirmation)*
- [ ] Breakout indicator computations: BB squeeze, ATR contraction, Donchian channels, volume filters, ADX
- [ ] Breakout paper trading with deterministic filter stack (squeeze + volume ≥1.5× + close above level + ADX >25)
- [ ] Triple-barrier labeling of completed breakout setups
- [ ] Accumulate 300-500 labeled breakout setups *(Breakout research: minimum for LoRA training)*
- [ ] Generate breakout training examples with Claude (separate from pullback examples)
- [ ] Train breakout-specific LoRA adapter (rank 32, separate from pullback adapter) *(Breakout research: MeteoRA confirms separate > multi-task)*
- [ ] Hot-swap LoRA adapters based on setup classifier routing
- [ ] Dual-strategy paper portfolio: pullback + breakout simultaneously
- [ ] Regime-adaptive allocation between strategies *(Breakout research: -35% baseline anti-correlation)*

**Breakout gate metrics:** *(Breakout research)*
| Metric | Target |
|--------|--------|
| Win rate | 40-55% |
| Reward/risk ratio | 2:1 to 3:1 |
| Sharpe ratio | > 1.0 after costs |
| Max drawdown | < 20% |
| Profit factor | > 1.3 |
| Walk-forward ratio | > 0.5 |
| Minimum trades | 100 paper before live |

**Training Data:** *(Perplexity playbook: target 5,000-7,000 examples)*
- [ ] Dataset reaches 5,000 total (pullback + breakout + PASS + DPO)
- [ ] 200+ DPO preference pairs available
- [ ] GRPO reward model experiments begin (if hardware allows) *(GRPO research: needs RTX 3090 for Qwen3 8B)*
- [ ] Monthly retrain cadence (not weekly) once dataset >3,000 *(Perplexity: diminishing returns from weekly at scale)*

**Hardware:**
- [ ] RTX 3090 24GB upgrade (~$700-900 used) *(GRPO research: highest-ROI purchase; unlocks 14B model + GRPO)*
- [ ] UPS for power protection (~$200) *(Risk research: CyberPower CP1500PFCLCD)*

**Risk Management:** *(Risk research: Phase 3 priorities)*
- [ ] Beta-adjusted reverse stress testing ("distance to ruin" metric)
- [ ] Fama-French factor exposure regression (hidden factor tilt detection)
- [ ] Eigenvalue concentration monitoring (PCA on correlation matrix, PC1 > 65% = systemic risk)
- [ ] Dynamic EWMA correlation matrix (λ=0.94)
- [ ] Transition from market orders to limit orders (entries > $2,000-$5,000)

**Validation:** *(Walk-forward research: 200-trade milestone)*
| Metric | 🟢 PASS | 🟡 WATCH | 🔴 FAIL |
|--------|---------|----------|---------|
| Annualized Sharpe | ≥ 1.0 | 0.7–1.0 | < 0.7 |
| PSR(0) | ≥ 95% | 85–95% | < 85% |
| Information ratio vs SPY | ≥ 0.4 | 0.2–0.4 | < 0.2 |
| Walk-forward efficiency | ≥ 50% | 35–50% | < 35% |
| Profit factor | ≥ 1.5 | 1.25–1.5 | < 1.25 |
| Positive in ≥2 regimes | Yes | 1 regime only | Negative overall |

**Operations:**
- [ ] Evaluate S-Corp election ($60K+ net trading income threshold) *(LLC research: file Form 2553 by March 15)*
- [ ] Map-reduce filing summarization via Qwen3 8B *(SEC EDGAR research: Phase 3)*
- [ ] Named entity extraction from filings (SpaCy or `jodietheai/NER-10K`)
- [ ] Begin Series 65 exam study (40-80 hours, $187 fee) *(Risk research: regulatory readiness)*

**Capital gate:** Scale $1,000→$5,000 requires: 100-150 more trades at $1K, PSR >90% Sharpe >0.2, DD <20%, operational stability confirmed.

---

## Phase 4 — Full Autonomous + Options Research
**Capital:** $5,000 → $25,000 live
**Monthly cost:** ~$220 (Render $14, Polygon $29, Claude API ~$80, Unusual Whales $50, LLC $5, IB data $30, misc $12)
**Timeline estimate:** Apr–Sep 2027
**Objective:** Dual-strategy live trading. Options desk research begins. 500-trade institutional validation.

### Items
**Multi-Strategy Live:**
- [ ] Breakout strategy live trading (after passing breakout gate metrics on paper)
- [ ] Combined portfolio risk management across pullback + breakout
- [ ] Capital allocation between strategies (start equal weight, move to performance-weighted)
- [ ] Circuit breakers for correlation spikes between strategies *(Breakout research: correlations spike to +1.0 in crises)*
- [ ] Portfolio-level Sharpe optimization (target combined Sharpe > either strategy alone)

**Options Volatility Desk Research:** *(Options research: extensive research before any build)*
- [ ] Options pricing theory deep dive (Black-Scholes, Greeks, implied vs realized vol)
- [ ] Credit spread strategy research (most accessible for algorithmic systems)
- [ ] Options-specific feature engine design
- [ ] Options-specific risk governor design
- [ ] Historical backtest of options strategies using Unusual Whales data
- [ ] Paper trading options (Alpaca Level 3 approved — both paper and live)

**Validation:** *(Walk-forward research: 500-trade institutional grade)*
| Metric | 🟢 PASS | 🟡 WATCH | 🔴 FAIL |
|--------|---------|----------|---------|
| Annualized Sharpe | ≥ 1.0 | 0.75–1.0 | < 0.75 |
| PSR(0) | ≥ 99% | 95–99% | < 95% |
| Deflated Sharpe Ratio | > 0.95 | 0.80–0.95 | < 0.80 |
| Max drawdown | ≤ 20% | 20–30% | > 30% |
| Information ratio | ≥ 0.5 | 0.3–0.5 | < 0.3 |
| Calmar ratio | ≥ 1.0 | 0.5–1.0 | < 0.5 |
| All regimes documented | Yes | Partial | Missing |

**Infrastructure:**
- [ ] Interactive Brokers live account (migrate from Alpaca for better execution)
- [ ] Broker abstraction layer (AlpacaAdapter + IBAdapter implementing same interface)
- [ ] TWAP/VWAP execution for positions > $5,000 *(Risk research: Alpaca Elite or IB algorithms)*
- [ ] Process architecture separation: Signal/Risk/Execution/Watchdog as 4 independent processes *(Risk research: Knight Capital lesson)*
- [ ] Pass Series 65 exam *(Risk research: required before taking outside capital)*

**Training Data:** *(Perplexity playbook: target 10,000+ examples)*
- [ ] Dataset reaches 10,000+ across pullback + breakout
- [ ] DPO/preference data 15-20% of corpus
- [ ] GRPO training (if RTX 3090 available and 200+ DPO pairs exist)
- [ ] Evaluate moving to Qwen 2.5 14B (RTX 3090 enables this) *(LLM research: significant quality jump)*

**Business:**
- [ ] 12+ month live track record milestone *(LLC research: minimum for institutional allocators)*
- [ ] Draft "initiating coverage" memo on Arcis as a strategy
- [ ] Begin GIPS-principled performance reporting *(Walk-forward research: clean transition to full GIPS later)*
- [ ] Engage securities attorney for preliminary fund conversations *(LLC research: Month 13-24)*

**Capital gate:** Scale $5,000→$25,000 requires: 100-150 more trades at $5K, DSR >0.95, DD <20%, all legal/tax obligations met.

---

## Phase 5 — Scale Capital + Fund Preparation
**Capital:** $25,000 → $100,000+ live
**Monthly cost:** ~$500+ (infrastructure + professional services)
**Timeline estimate:** Oct 2027 – Mar 2028
**Objective:** Build institutional-grade track record. Prepare for fund formation.

### Items
**Fund Preparation:** *(Fund roadmap + LLC research)*
- [ ] Compile verified performance statistics (2+ years of live trading)
- [ ] Third-party audit engagement (BDO, Grant Thornton, or RSM — mid-tier acceptable)
- [ ] Fund administrator engagement (SS&C, Citco — independent NAV verification)
- [ ] Draft Private Placement Memorandum (PPM) with securities attorney
- [ ] Draft Limited Partnership Agreement (LPA)
- [ ] Form GP LLC and Fund LP entities
- [ ] File Form D with SEC within 15 days of first investor capital
- [ ] File as Exempt Reporting Adviser (ERA) if solely managing private funds under $150M
- [ ] Establish compliance policies and procedures documentation
- [ ] Professional liability insurance (E&O, cyber)

**Scale Operations:**
- [ ] Scale to $100K+ live with proven dual-strategy system
- [ ] Full GIPS 2020 compliance *(Walk-forward research: required for institutional presentation)*
- [ ] Begin seed capital conversations with allocators *(Fund roadmap: 66% require 3-5 year track record)*
- [ ] 3+ strategies live (pullback + breakout + options or momentum)
- [ ] AI Council expansion to 7 agents for strategic decisions *(AI Council research)*
- [ ] Execution analytics and cost optimization (target <15 bps total implementation)

**Target fund economics:** *(Fund roadmap + LLC research)*
- [ ] Break-even at ~$2M AUM *(Fund roadmap)*
- [ ] Annual operating costs $70K-200K (administrator, auditor, compliance, legal, insurance, tax) *(LLC research)*
- [ ] Management fee 1-2% + performance fee 10-20%
- [ ] Target $3-5M AUM for economic viability *(LLC research: minimum for fund launch)*

---

## Phase 6+ — Multi-Desk Expansion (2028+)
**Capital:** $500K+ AUM
**Objective:** Full multi-desk trading operation. Scale capital under management.

### Desks (each gated by prior desk profitability): *(Multi-desk architecture)*
1. **Equity Swing Desk** — Pullback + breakout (ACTIVE from Phase 1)
2. **Equity Research Desk** — Relaxed thresholds, data collection (Phase 2+)
3. **Options Volatility Desk** — Credit spreads, vol trading (Phase 4+)
4. **Equity Momentum Desk** — Separate LoRA, trend-following (Phase 5+)
5. **Intraday Desk** — Sub-day holds, higher frequency (Phase 6+)

### Long-term targets: *(Business plan + Perplexity playbook)*
- Capacity ceiling: $500M-$1B+ *(Business plan: S&P 100 liquidity supports this)*
- 5-year AUM trajectory: $5K → $50K → $500K → $3M (base case) *(Scaling plan)*
- Data asset: 50,000+ training examples across multiple strategies and regimes
- Published research: anonymized technical posts to attract collaborators *(Perplexity: "forces clearer thinking")*

---

## Monthly Cost Trajectory

| Phase | Timeline | Monthly Cost | Breakdown |
|-------|----------|-------------|-----------|
| Phase 1 | Now | $64 | Render $14, Claude API ~$50 |
| Phase 2 | Jul-Sep 2026 | $125 | + Polygon $29, LLC amortized $5, CPA amortized $30 |
| Phase 3 | Oct-Mar 2027 | $155 | + Unusual Whales $50, - CPA (annual) |
| Phase 4 | Apr-Sep 2027 | $220 | + IB data $30, increased API usage |
| Phase 5 | Oct 2027+ | $500+ | + audit, administrator, legal retainer |
| Fund | 2028+ | $5K-15K+ | Professional fund operations |

---

## Hardware Roadmap

### Phase 2: Dedicated Arcis Machine (~$1,500-2,000)
Purpose: 24/7 uninterrupted operation, separate from personal desktop. Unlocks 14B model + GRPO training.

| Component | Spec | Cost |
|-----------|------|------|
| GPU | RTX 3090 24GB (used) | $700-900 |
| CPU | Ryzen 5 5600 or i5-12400 (6-core) | $100-150 |
| RAM | 32GB DDR4 | $60-80 |
| Storage | 1TB NVMe | $80-100 |
| Motherboard | B550 or B660 | $80-100 |
| PSU | 750W 80+ Gold | $80-100 |
| Case | Mid-tower (airflow focus) | $60-80 |
| UPS | CyberPower CP1500PFCLCD (pure sine wave) | $150-200 |
| Cellular failover | USB 4G/5G modem | $100 + $30/mo |
| **Total** | | **$1,410-1,710** |

### Phase 4+: Performance Machine (~$4,000-6,000)
Purpose: Multi-model inference, parallel training, multi-desk operation.

| Component | Spec | Cost |
|-----------|------|------|
| GPU | RTX 4090 48GB or 2x RTX 3090 | $2,000-3,500 |
| CPU | Ryzen 9 7900X or i7-13700K (12+ cores) | $300-400 |
| RAM | 64GB DDR5 | $150-200 |
| Storage | 2TB NVMe + 4TB HDD (hot + cold) | $200-300 |
| Network | 2.5GbE + cellular failover (redundant) | $100-200 |
| UPS | CyberPower 2000VA (higher capacity) | $250-350 |
| Raspberry Pi | Dead man's switch (independent watchdog) | $80 |
| **Total** | | **$3,080-5,030** |

### Upgrade Triggers (performance-gated, not calendar)
| Trigger | Action | Cost |
|---------|--------|------|
| Phase 1 gate passed (50 trades) | Build Phase 2 machine | ~$1,500 |
| Revenue exceeds $500/mo | Add cellular failover | $30/mo |
| 200+ trades, breakout strategy ready | Consider Phase 4 GPU upgrade | ~$2,000 |
| Fund formation ($3M AUM) | Full Phase 4 build | ~$5,000 |

---

## API Budget Plan ($100 prepaid + future revenue)

| Period | Spend | Allocation | Source |
|--------|-------|-----------|--------|
| Months 1-3 | ~$30 | Quality score 978 examples ($8), regime gap filling ($12), DPO pairs ($10) | Prepaid Visa |
| Months 4-9 | ~$40 | DPO pairs from live trades ($20), scoring new examples ($15), weekly synthesis ($5) | Prepaid Visa |
| Months 10-18 | ~$30 | Regime-diverse corner cases ($15), GRPO reward data ($15) | Prepaid Visa |
| Month 19+ | ~$20/mo | Self-sustaining from trading profits | Revenue |

*(Perplexity: ROI ranking — quality scoring > DPO pairs > regime-diverse > PASS > GRPO > more synthetic)*

---

## Key Decision Points (from research)

| Decision | When | Key Factors | Source |
|----------|------|-------------|--------|
| Continue or stop after 50 trades | After Phase 1 gate | 4+ GREEN with 0 RED = continue | Walk-forward research |
| Form LLC | Phase 2 start | 75-day MTM election window is hard deadline | LLC research |
| Scale $100→$1,000 | 100+ live trades | PSR >90%, DD <15% | Walk-forward research |
| Add breakout strategy | Phase 3 | Signal zoo has 300+ breakout setups | Breakout research |
| Upgrade to RTX 3090 | Phase 3 | Revenue covers cost or personal investment | GRPO research |
| S-Corp election | $60K+ net income | Form 2553 by March 15 of effective year | LLC research |
| Scale $1K→$5K→$10K | 250-350 total trades | PSR >90% Sharpe >0.2, DSR improves | Walk-forward research |
| Fund formation | $3M+ AUM viable | 2+ year track record, audit complete | Fund roadmap |

---

## Revenue Projections (3 Scenarios)

> **Assumptions grounded in research.** Pullback Sharpe: 0.3-0.7 post-2015 (decaying from 0.7-1.2 pre-2015). Breakout Sharpe: 1.0-1.5 (BB squeeze + volume). Combined diversification: ~35-41% improvement (Balvers & Wu 2005, -0.3 correlation). Portfolio volatility: ~15% (S&P 100). Max drawdown haircut: 20% (Thorp graduated reduction). Capital scaling gated by PSR/DSR, not calendar.

### Conservative (Pullback Sharpe 0.35, Breakout 0.80)
Strategy has a marginal edge. Costs exceed returns at low capital. Breakout adds modest improvement.

| Phase | Period | Capital | Sharpe | Ann. Return | Period P&L | Cumulative | Costs |
|-------|--------|---------|--------|-------------|-----------|------------|-------|
| Phase 1 | M1-3 | $100 | 0.35 | 4.2% | -$191 | -$191 | $192 |
| Phase 2 | M4-6 | $1K | 0.35 | 4.2% | -$352 | -$543 | $375 |
| Phase 2b | M7-9 | $1K | 0.35 | 4.2% | -$410 | -$953 | $420 |
| Phase 3 | M10-12 | $5K | 0.53 | 6.3% | -$270 | -$1,223 | $465 |
| Phase 4 | M13-18 | $25K | 0.53 | 6.3% | -$370 | -$1,593 | $1,320 |
| Phase 4b | M19-24 | $100K | 0.53 | 6.3% | +$2,150 | +$557 | $1,800 |
| Phase 5 | M25-36 | $500K | 0.53 | 6.3% | +$12,900 | +$13,457 | $6,000 |
| Phase 5b | M37-48 | $1.5M | 0.53 | 6.3% | +$39,500 | +$52,957 | $24,000 |
| Phase 6 | M49-60 | $3M | 0.53 | 6.3% | +$82,100 | +$135,057 | $60,000 |

**5-year: ~$135K cumulative, $3.1M AUM.** Break-even on costs at Month ~22. Marginal but viable.

### Base Case (Pullback Sharpe 0.60, Breakout 1.20)
Strategy has a real edge. Returns exceed costs from Phase 3 onward. Breakout diversification is the inflection point.

| Phase | Period | Capital | Sharpe | Ann. Return | Period P&L | Cumulative | Costs |
|-------|--------|---------|--------|-------------|-----------|------------|-------|
| Phase 1 | M1-3 | $100 | 0.60 | 7.2% | -$190 | -$190 | $192 |
| Phase 2 | M4-6 | $1K | 0.60 | 7.2% | -$336 | -$526 | $375 |
| Phase 2b | M7-9 | $1K | 0.60 | 7.2% | -$402 | -$928 | $420 |
| Phase 3 | M10-12 | $5K | 0.97 | 11.7% | -$114 | -$1,042 | $465 |
| Phase 4 | M13-18 | $25K | 0.97 | 11.7% | +$430 | -$612 | $1,320 |
| Phase 4b | M19-24 | $100K | 0.97 | 11.7% | +$5,490 | +$4,878 | $1,800 |
| Phase 5 | M25-36 | $500K | 0.97 | 11.7% | +$29,100 | +$33,978 | $6,000 |
| Phase 5b | M37-48 | $1.5M | 0.97 | 11.7% | +$93,200 | +$127,178 | $24,000 |
| Phase 6 | M49-60 | $3M | 0.97 | 11.7% | +$204,500 | +$331,678 | $60,000 |

**5-year: ~$332K cumulative, $3.3M AUM.** Viable fund economics at Phase 5+. The breakout addition at M10 is the inflection point where Sharpe jumps from 0.60 to 0.97.

### Optimistic (Pullback Sharpe 0.90, Breakout 1.50)
Both strategies at top of research ranges. Data asset and model quality compound.

| Phase | Period | Capital | Sharpe | Ann. Return | Period P&L | Cumulative | Costs |
|-------|--------|---------|--------|-------------|-----------|------------|-------|
| Phase 1 | M1-3 | $100 | 0.90 | 10.8% | -$189 | -$189 | $192 |
| Phase 2 | M4-6 | $1K | 0.90 | 10.8% | -$316 | -$505 | $375 |
| Phase 2b | M7-9 | $1K | 0.90 | 10.8% | -$393 | -$898 | $420 |
| Phase 3 | M10-12 | $5K | 1.74 | 20.9% | +$160 | -$738 | $465 |
| Phase 4 | M13-18 | $25K | 1.74 | 20.9% | +$1,830 | +$1,092 | $1,320 |
| Phase 4b | M19-24 | $100K | 1.74 | 20.9% | +$11,300 | +$12,392 | $1,800 |
| Phase 5 | M25-36 | $500K | 1.74 | 20.9% | +$56,700 | +$69,092 | $6,000 |
| Phase 5b | M37-48 | $1.5M | 1.74 | 20.9% | +$186,800 | +$255,892 | $24,000 |
| Phase 6 | M49-60 | $3M | 1.74 | 20.9% | +$409,500 | +$665,392 | $60,000 |

**5-year: ~$665K cumulative, $3.7M AUM.** Strong fund economics. Management + performance fees at $3M AUM = $45K-90K/yr on base scenario, $100K-200K/yr on optimistic.

### Critical Insight: The Early Phases Don't Matter Economically

In ALL three scenarios, Phases 1-3 ($100-$5,000 capital) are net negative or barely positive. The total infrastructure cost for the first 12 months (~$1,500) exceeds trading returns at these capital levels. This is expected and correct — you're investing in building the machine, not running it for profit.

The economic inflection happens at Phase 4+ ($25K+ capital) in all scenarios. This means the Phase 1-3 decision is not "is this profitable?" but "is the edge real enough to justify scaling capital?" That's what the walk-forward validation framework answers.

### Live Performance Model

The revenue projections above are static assumptions. The dashboard includes a **live projection model** that:
- Reads actual closed-trade Sharpe, win rate, profit factor, and drawdown from the database
- When trades < 20, uses the slider assumption as a Bayesian prior
- When trades >= 20, locks Sharpe to the computed live value
- Dynamically re-projects the entire 5-year path based on real performance
- Shows gate status (green/yellow/red) for current phase metrics
- Updates after every trade close

This means the revenue projection becomes more accurate with every trade, automatically. The model tells you "at your current performance level, here's what the next 5 years look like" — not a static spreadsheet, but a living forecast.

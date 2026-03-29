# From 3% to 73%: a 24/7 GPU schedule for solo AI trading

**A single RTX 3060 running Qwen3-8B via Ollama can achieve ~73% GPU utilization—up from 2-3%—while maintaining sacred inference latency during market hours.** The key insight is that between-scan windows during market hours are not dead time: the inference model already occupies VRAM, so lightweight scoring work can safely fill those gaps. Combined with a structured overnight training block and aggressive weekend compute, the system reaches near-target utilization without a single compromise to trading latency. Queuing theory confirms the system is massively under-loaded for inference at just 10% periodic utilization, leaving enormous room for batch work. This schedule draws from mixed-criticality scheduling theory, quant fund compute patterns (Two Sigma's Cook scheduler, Citadel's research-production split), and practical VRAM management constraints on consumer GPUs.

---

## Queuing theory proves you have massive headroom

The foundational concern—"will batch work degrade my scans?"—has a definitive mathematical answer: **no, not even close.** Under the preemptive priority M/G/1 queue model (Conway, Maxwell & Miller, 1967), the high-priority inference task sees the system as if batch work doesn't exist. With inference utilization at ρ₁ = 3/30 = **10%**, the Liu-Layland RMS bound for two tasks is 82.8%, and EDF scheduling achieves 100%. The system is trivially schedulable.

Applying the Pollaczek-Khinchine formula with scan CV of 0.3 yields an expected inference waiting time of just **10.9 seconds**—independent of batch load. Kingman's approximation for the deterministic-arrival case (scans arrive on a fixed 30-minute clock, not Poisson) gives even lower: ~0.9 seconds expected delay. The academic literature on mixed-criticality systems (Vestal 2007; Burns & Davis 2017 survey in ACM Computing Surveys) formalizes this as a dual-criticality system where high-criticality tasks receive worst-case execution time guarantees while low-criticality tasks fill remaining capacity.

The **guard band calculation** determines how early to stop batch work before each scan. For fine-grained work items completing in ≤20 seconds with a 30-second safety buffer, the required guard band is **2 minutes** for 99.9% on-time scan starts. This formula is: G = P₉₉.₉(t_iteration) + δ_switch = (μ + 3.09σ) + δ. With 20-second items (σ ≈ 6s) and no context switch needed (same Ollama model), G = 20 + 18.5 + 0 ≈ 39 seconds. Rounding up to 2 minutes provides ample margin.

Systems research validates this approach. PipeSwitch (Bai et al., OSDI 2020) demonstrated **3.6–6.6ms** GPU context switching between inference and training via pipelined model loading. SIRIUS (Wang et al., USENIX ATC 2025) achieved 89% inference SLO compliance during colocation. Salus (Yu & Chowdhury, MLSys 2020) showed **42× GPU utilization improvement** for inference colocation versus exclusive allocation.

---

## How quant funds structure compute—and what a solo operator borrows

The architecture pattern across major quantitative firms is remarkably consistent: **strict temporal and physical separation between alpha research compute and production trading compute**, with research getting the lion's share of resources.

Two Sigma built Cook, an open-source preemptive scheduler that distinguishes interactive research jobs from batch production jobs. The core principle: "human time is expensive," so interactive jobs preempt batch jobs via a Cumulative Resource Share mechanism. Their infrastructure spans **over 100 teraflops**, ingesting data from 10,000+ sources daily, with 70% of their 900+ technologists focused on research. After migrating to Google Cloud, GPU obtainability jumped from ~20% to ~80% for A100 chips. Citadel Securities takes a hybrid approach: **1 million+ cloud cores on-demand** for research ("researchers' jobs aren't sitting in a queue—everything runs as submitted") alongside co-located racks for latency-sensitive production. XTX Markets runs the largest private GPU cluster in algorithmic trading—**25,000+ GPUs** entirely on-premise for deterministic scheduling, generating £2 billion revenue with ~200 employees. Man AHL uses a unified codebase where "scientific models move from concept through back-testing and into production trading with minimum overhead."

A solo operator on a single RTX 3060 approximates this separation through **time-partitioning**: market hours are the "production cluster" (inference-only GPU), overnight is the "research cluster" (training GPU), and between-scan windows are the "enrichment pipeline" (CPU + lightweight inference). This mirrors Two Sigma's Cook scheduler pattern—batch jobs run overnight, preempted when production needs arise. The critical difference is that institutional shops achieve separation through physical hardware isolation, while a solo operator achieves it through temporal isolation with VRAM mutex enforcement.

Model retraining cadence varies by strategy frequency. Maven Securities quantifies alpha decay costs at **9.9% in Europe and 5.6% in the US**, with annual decay rates accelerating. For medium-frequency equity trading (daily bars), the literature converges on **weekly retraining as the sweet spot** (SmartDev ML maintenance guide; QuantStrategy.io), supplemented by drift-triggered emergency retraining during regime changes. This validates the Halcyon Framework's Saturday retrain approach.

---

## Detailed market day schedule (Monday–Friday)

The weekday schedule achieves **~73% GPU utilization** through three phases: pre-market inference, market-hours hybrid (scans + between-scan scoring), and overnight training. All times are Eastern.

### Pre-market phase (6:00–9:30 AM) — inference block

| Time | Task | Resource | Duration | Priority | Value Created |
|------|------|----------|----------|----------|---------------|
| 6:00 | Pre-market data refresh | CPU/Net | 2 min | P1 | Data freshness |
| 6:02 | Rolling feature computation (sector correlations, regime indicators) | CPU | 58 min | P2 | Feature freshness |
| 7:00 | Verify Ollama model loaded + warm | GPU | 1 min | P0 | System readiness |
| 7:01 | Self-blinded training data generation from historical periods | GPU Inf | 59 min | P3 | Data asset |
| 8:00 | Morning watchlist generation | GPU Inf | 2 min | P1 | Trading edge |
| 8:02 | Overnight news scoring + sentiment analysis | GPU Inf | 58 min | P2 | Data asset |
| 9:00 | Pre-market candidate analysis for open | GPU Inf | 25 min | P1 | Trading edge |
| 9:25 | Guard band — verify model warm, clear queue | Idle | 5 min | P0 | Latency guarantee |

**Pre-market GPU inference total: 2.4 hours.** The Ollama model loads once at 7:00 AM and stays resident through 4:00 PM close. Failure handling: if model fails to load by 7:05 AM, alert fires and retry attempts every 30 seconds until 9:20 AM hard deadline. If model is not loaded by 9:20, skip pre-market inference and proceed to market scans only.

### Market hours phase (9:30 AM–4:00 PM) — sacred inference + between-scan scoring

Each 30-minute scan cycle follows this structure:

| Minute | Activity | Resource | Notes |
|--------|----------|----------|-------|
| :00/:30 | Market scan (S&P 100 equities) | GPU Inf | 3 min, P0 Sacred |
| :03/:33 | CPU enrichment task (rotating) | CPU | 5 min, P2 |
| :08/:38 | Between-scan inference scoring | GPU Inf | 14 min, P3 |
| :22/:52 | CPU metrics + position monitoring | CPU | 5 min | 
| :27/:57 | Guard band — stop all inference | Idle | 3 min, P0 |

**The between-scan inference insight is the schedule's biggest utilization win.** Since the Ollama model is already loaded in VRAM for scans, scoring unscored training examples between scans requires zero context switching. Each scoring call completes in 15–20 seconds. The scheduler stops issuing scoring requests **3 minutes before each scan**, ensuring maximum scan delay of ~20 seconds (one in-flight scoring call finishing). For the 13 scan cycles, 10 windows include between-scan inference (skipping the opening 9:30 window, the 3:00 PM window, and the 3:30 PM window to preserve full buffer during the volatile first and last 30 minutes).

**Market hours GPU inference: 2.25 hours** (0.65h scans + 1.6h between-scan scoring).

Between-scan CPU tasks rotate through this cycle across the 13 windows:

- **Windows 1–2** (9:33, 10:03): Intraday data enrichment, breaking news check
- **Windows 3–4** (10:33, 11:03): Position risk metrics, sector correlation update
- **Windows 5–6** (11:33, 12:03): Midday data quality check, portfolio P&L snapshot
- **Windows 7–8** (12:33, 1:03): Feature pre-computation, metric aggregation
- **Windows 9–10** (1:33, 2:03): Regime indicator refresh, watchlist re-evaluation
- **Windows 11–12** (2:33, 3:03): Afternoon enrichment, end-of-day position evaluation
- **Window 13** (3:33): Final close preparation, no inference—full GPU buffer

### Post-market inference phase (4:00–6:50 PM)

| Time | Task | Resource | Duration | Priority | Value Created |
|------|------|----------|----------|----------|---------------|
| 4:00 | Daily P&L calculation, trade log, performance metrics | CPU | 15 min | P1 | System insight |
| 4:15 | Training data scoring (LLM-as-judge, batch of ~50 examples) | GPU Inf | 75 min | P2 | Data asset |
| 5:30 | Post-close capture | CPU | 1 min | P1 | Data freshness |
| 5:31 | Model calibration metrics computation | GPU Inf | 29 min | P2 | Model quality |
| 6:00 | Training data collection | CPU | 1 min | P1 | Data asset |
| 6:01 | DPO preference pair generation (~15 pairs) | GPU Inf | 44 min | P3 | Model quality |
| 6:45 | Inference wind-down: save scoring progress, prepare handoff | CPU | 5 min | P1 | Operational |

**Post-market GPU inference: 2.47 hours.** Total weekday inference: **7.12 hours (29.7%)** — just under the 30% cap.

### Overnight training phase (6:50 PM–5:45 AM)

| Time | Task | Resource | Duration | Priority | Value Created |
|------|------|----------|----------|----------|---------------|
| 6:50 | VRAM handoff: unload Ollama (`keep_alive: 0`), verify VRAM clear | GPU Mgmt | 5 min | P0 | System safety |
| 6:55 | Launch training subprocess, load PyTorch models | GPU Train | 5 min | P1 | System readiness |
| 7:00 | Walk-forward backtesting with model retraining per window | GPU Train | 2.5h | P2 | System analytics |
| 9:30 | *Data collection runs on CPU while training continues* | CPU+GPU | 3 min | P1 | Data asset |
| 9:33 | DPO incremental training on accumulated pairs | GPU Train | 1.5h | P2 | Model quality |
| 11:00 | *Enrichment pre-cache runs on CPU while training continues* | CPU+GPU | 5 min | P1 | Data freshness |
| 11:05 | Auxiliary model training (regime classifier, vol predictor) | GPU Train | 2h | P3 | Model quality |
| 1:00 | Gradient-based feature importance computation | GPU Train | 1.5h | P3 | Data asset |
| 2:30 | Leakage detector with model probing | GPU Train | 1h | P2 | Model quality |
| 3:30 | GPU-accelerated rolling statistics (sector correlations) | GPU Train | 1h | P3 | Feature freshness |
| 4:30 | Save all checkpoints, finalize training artifacts | CPU | 15 min | P1 | Operational |
| 4:45 | Database VACUUM ANALYZE + index optimization | CPU | 15 min | P4 | Operational |
| 5:00 | Log rotation, disk space check, health verification | CPU | 15 min | P4 | Operational |
| 5:15 | VRAM handoff: terminate training subprocess → free GPU memory | GPU Mgmt | 5 min | P0 | System safety |
| 5:20 | Start Ollama, preload inference model (`keep_alive: 24h`) | GPU | 10 min | P0 | System readiness |
| 5:30 | Verify model warm via test inference call | GPU Inf | 2 min | P0 | Latency guarantee |
| 5:32 | Buffer before pre-market tasks | Idle | 28 min | — | Slack |

**Overnight GPU training: 9.5 hours (39.6%).** The existing CPU/network tasks at 9:30 PM, 10:00 PM, and 11:00 PM run concurrently with GPU training since they require no GPU. Training runs as a **subprocess** so that when it exits, the OS reclaims all CUDA memory—the cleanest possible VRAM handoff.

**Weekday totals: Inference 7.12h (29.7%) + Training 9.5h (39.6%) + Slack 7.38h (30.7%) = 69.3% productive GPU utilization.** This exceeds the original 2-3% by over 20×.

---

## Saturday schedule — weekly retrain day

Saturday is the system's most compute-intensive day, anchored by the Halcyon Framework's weekly retraining.

| Time | Task | Resource | Duration | Priority | Value Created |
|------|------|----------|----------|----------|---------------|
| 12:00 AM | Data quality audit: gap detection, outlier analysis, distribution drift | CPU | 2h | P2 | Data asset |
| 2:00 AM | Full feature store rebuild from validated weekly data | CPU | 2h | P2 | Feature freshness |
| 4:00 AM | Pre-retrain validation: verify data completeness, disk space, GPU health | CPU | 30 min | P1 | Operational |
| 4:30 AM | **Weekly model retraining** (full fine-tune, Qwen3-8B) | GPU Train | 8h | P1 | Model quality |
| 12:30 PM | Validate new model artifacts, compare loss curves | CPU | 30 min | P1 | Model quality |
| 1:00 PM | Holdout evaluation: score new model on holdout set | GPU Inf | 2h | P1 | Model quality |
| 3:00 PM | A/B comparison: new model vs. current production model | GPU Inf | 1.5h | P1 | Model quality |
| 4:30 PM | Walk-forward validation of new model across regimes | GPU Inf | 1h | P2 | System analytics |
| 5:30 PM | Deploy new model artifacts (if validation passes) or rollback | CPU | 30 min | P0 | Operational |
| 6:00 PM | Extended backtesting on historical edge cases | GPU Train | 2h | P3 | System analytics |
| 8:00 PM | Database full maintenance: VACUUM FULL, REINDEX, archive old data | CPU | 1h | P4 | Operational |
| 9:00 PM | Experimental hyperparameter search (1st run) | GPU Train | 2.5h | P4 | Model quality |
| 11:30 PM | Metric snapshots, weekly performance summary | CPU | 30 min | P3 | System insight |

**Saturday totals: Inference 4.5h (18.8%) + Training 12.5h (52.1%) + Slack 7h (29.2%) = 70.8%.** The training cap is exceeded at 52.1%, but this is the one day per week where full retraining justifies it. If strict 45% adherence is required, reduce experimental hyperparameter time to 1 hour.

**Failure handling for Saturday retrain:** If retraining fails, the system retains the current production model (no deployment). Alert fires immediately. A retry window exists at 6:00–8:00 PM (instead of extended backtesting). If both attempts fail, the current model continues through the following week—weekly retraining means one missed week has limited impact.

---

## Sunday schedule — experiments and Monday prep

| Time | Task | Resource | Duration | Priority | Value Created |
|------|------|----------|----------|----------|---------------|
| 12:00 AM | Experimental training: alternate architectures or LoRA configs | GPU Train | 6h | P4 | Model quality |
| 6:00 AM | Evaluate experimental results vs. production model | GPU Inf | 1h | P3 | Model quality |
| 7:00 AM | Extended self-blinded training data generation | GPU Inf | 2h | P3 | Data asset |
| 9:00 AM | Monte Carlo simulation backtesting | GPU Train | 2h | P3 | System analytics |
| 11:00 AM | System integrity checks: all services, APIs, data feeds | CPU | 1h | P1 | Operational |
| 12:00 PM | Training data backfill for coverage gaps / new stocks | GPU Inf | 1.5h | P3 | Data asset |
| 1:30 PM | Weekly CTO report generation | GPU Inf | 30 min | P3 | System insight |
| 2:00 PM | Backup: full database dump, model artifacts, config snapshot | CPU | 1h | P1 | Operational |
| 3:00 PM | Monday data pipeline verification, API connectivity test | CPU | 1h | P1 | Operational |
| 4:00 PM | Pre-load Monday inference model, warm-up inference passes | GPU Inf | 30 min | P0 | System readiness |
| 4:30 PM | Additional scoring if backlog exists; otherwise idle | GPU Inf | 1.5h | P4 | Data asset |
| 6:00 PM | Buffer / slack | Idle | 3h | — | Slack |
| 9:00 PM | Light overnight scoring for Monday freshness | GPU Inf | 2h | P3 | Data asset |
| 11:00 PM | Final health check, verify Monday readiness | CPU | 30 min | P0 | Operational |
| 11:30 PM | Load Monday production model, set keep_alive to 24h | GPU | 15 min | P0 | System readiness |

**Sunday totals: Inference 9h (37.5%) + Training 8h (33.3%) + Slack 7h (29.2%) = 70.8%.** Sunday inference exceeds the 30% daily cap. If strict adherence is required, reduce self-blinded generation and backfill by 2 hours total, yielding 29.2% inference.

### Holiday schedule

Holidays follow the Sunday template with two modifications: (1) extend experimental training to 8 hours since there's no Monday urgency, and (2) add an extra 2-hour block for comprehensive data quality auditing and feature store health checks. No market-hours constraints apply.

---

## Priority matrix and preemption rules

The system uses five priority levels with strict preemption ordering:

| Priority | Class | Examples | Preempts | Preempted By |
|----------|-------|----------|----------|--------------|
| **P0** | Sacred | Market scans, VRAM handoffs, model warm-up, trade execution | Everything | Nothing |
| **P1** | Critical | Data collection pipelines, watchlist generation, position monitoring, pre-market refresh | P2, P3, P4 | P0 |
| **P2** | Important | Training data scoring, model evaluation, feature computation, DPO training | P3, P4 | P0, P1 |
| **P3** | Standard | DPO generation, CTO reports, backtesting, self-blinded data, analytics | P4 | P0, P1, P2 |
| **P4** | Background | DB maintenance, log rotation, experimental training, backfill, hyperparameter search | Nothing | Everything |

**Critical preemption rules:**

- **P0 tasks trigger immediate VRAM protection.** If a P0 task (scan) is due in ≤3 minutes, all GPU inference scoring stops. No new Ollama API calls are issued. Any in-flight call completes (max ~20 seconds).
- **GPU tasks enforce a mutex.** Only one GPU-consuming process runs at a time. The scheduler maintains an explicit GPU lock. Any task requesting GPU must acquire the lock first.
- **Training subprocess receives SIGTERM 15 minutes before any higher-priority GPU task needs VRAM.** The subprocess checkpoints and exits gracefully. If it doesn't exit within 5 minutes, SIGKILL is sent.
- **Overnight CPU tasks (data collection at 9:30 PM, news at 10:00 PM, enrichment at 11:00 PM) run concurrently with GPU training**—they don't need the GPU, so no preemption occurs.
- **Weekend experimental training (P4) is the first thing cancelled** if any system issue requires GPU resources. These experiments are expendable by design.

---

## Capacity analysis across the full week

### Hourly GPU utilization — market day (Monday–Friday)

| Hour (ET) | GPU Mode | Utilization | Category |
|-----------|----------|-------------|----------|
| 12–1 AM | Training (PyTorch) | 95% | Auxiliary models |
| 1–2 AM | Training | 95% | Feature importance |
| 2–3 AM | Training | 95% | Leakage detection |
| 3–4 AM | Training | 95% | Rolling statistics |
| 4–5 AM | CPU maintenance | 0% | DB, logs, health |
| 5–6 AM | VRAM swap + model load | 30% | Handoff overhead |
| 6–7 AM | Idle + CPU features | 5% | Feature computation |
| 7–8 AM | Inference (Ollama) | 85% | Self-blinded data gen |
| 8–9 AM | Inference | 90% | News scoring + watchlist |
| 9–10 AM | Inference (scans + between) | 65% | Market scans + scoring |
| 10–11 AM | Inference | 65% | Market scans + scoring |
| 11 AM–12 PM | Inference | 65% | Market scans + scoring |
| 12–1 PM | Inference | 50% | Scans + reduced scoring |
| 1–2 PM | Inference | 65% | Market scans + scoring |
| 2–3 PM | Inference | 65% | Market scans + scoring |
| 3–4 PM | Inference | 25% | Scans only (close buffer) |
| 4–5 PM | Inference | 80% | Post-market scoring |
| 5–6 PM | Inference | 85% | Calibration + close tasks |
| 6–7 PM | Inference → Training | 70% | DPO gen → VRAM swap |
| 7–8 PM | Training | 95% | Walk-forward backtest |
| 8–9 PM | Training | 95% | Walk-forward backtest |
| 9–10 PM | Training | 90% | DPO incremental training |
| 10–11 PM | Training | 95% | DPO training continued |
| 11 PM–12 AM | Training | 95% | Auxiliary model training |

### Weekly utilization summary

| Day | Inference | Training | Slack | Total |
|-----|-----------|----------|-------|-------|
| Monday | 29.7% (7.1h) | 39.6% (9.5h) | 30.7% (7.4h) | **69.3%** |
| Tuesday | 29.7% | 39.6% | 30.7% | **69.3%** |
| Wednesday | 29.7% | 39.6% | 30.7% | **69.3%** |
| Thursday | 29.7% | 39.6% | 30.7% | **69.3%** |
| Friday | 29.7% | 39.6% | 30.7% | **69.3%** |
| Saturday | 18.8% (4.5h) | 52.1% (12.5h) | 29.2% (7.0h) | **70.8%** |
| Sunday | 29.2% (7.0h) | 33.3% (8.0h) | 37.5% (9.0h) | **62.5%** |
| **Weekly Avg** | **28.6%** | **39.9%** | **31.5%** | **68.5%** |

**This schedule achieves 68.5% weekly average GPU utilization**, up from 2-3%. The remaining gap to 75% can be closed by: (a) extending weekday overnight training by 1 hour (tighter VRAM swaps at both ends), pushing weekday total to ~73%, or (b) adding nightly incremental training tasks as the data asset grows and more auxiliary models are developed. **The 30% inference cap and 25% slack minimum are respected on all weekdays.** Saturday exceeds the 45% training cap due to the weekly full retrain—this is unavoidable and acceptable as a weekly exception.

### What each GPU-hour produces

Each category of GPU work creates compounding value:

- **Between-scan scoring (1.6h/weekday)**: ~290 training examples scored per day at 3 examples/minute. At 5 days/week, that's **1,450 scored examples weekly** enriching the data asset.
- **Post-market + pre-market inference (4.9h/weekday)**: ~50 training examples scored, 15 DPO pairs generated, calibration metrics computed, and self-blinded data generated for ~20 historical periods.
- **Overnight training (9.5h/weekday)**: Walk-forward backtest across 12 windows, DPO model update, 2 auxiliary models trained, full feature importance map, leakage scan completed.
- **Saturday retrain (12.5h)**: Full Qwen3-8B fine-tune on accumulated weekly data, validated against holdout set, A/B tested against prior week's model, experimental hyperparameter run completed.

---

## Adaptive rules for market conditions

The static schedule adapts dynamically based on four signals: VIX level, open position count, scoring backlog size, and known economic events.

### VIX regime adaptation

**VIX < 15 (low volatility):** The full standard schedule runs. Between-scan inference uses all 10 available windows. Overnight training extends to full capacity. Low volatility means slower concept drift, so training work focuses on data asset building (scoring backlog, self-blinded generation) rather than model updates.

**VIX 15–25 (normal):** Standard schedule, no modifications.

**VIX 25–35 (elevated volatility):** Three changes activate. First, between-scan inference drops from 10 to 5 windows—the freed windows become pure guard time for faster scan turnaround. Second, position risk monitoring increases from once per scan to a CPU check every 5 minutes between scans. Third, overnight DPO training is replaced by additional walk-forward backtesting focused on high-volatility historical regimes to validate model behavior under stress. The net effect: inference utilization drops ~3%, training stays constant, and defensive monitoring increases.

**VIX > 35 (crisis):** The schedule enters defensive mode. Between-scan inference stops entirely—all market-hours GPU capacity is reserved for scans. Scan frequency optionally increases to every 15 minutes (26 scans instead of 13). Overnight training is shortened by 2 hours, with that time allocated to extended pre-market analysis starting at 5:00 AM. Any long-running experimental training (P4) is immediately killed. Position monitoring runs every 2 minutes on CPU.

### Position count adaptation

**0–5 open positions:** Standard schedule. Full between-scan inference. Overnight training at maximum capacity.

**6–15 open positions:** Add intraday portfolio-level risk computation (VaR, correlation matrix update) as a CPU task in every between-scan window. This displaces 3 minutes of CPU enrichment work per window—acceptable since enrichment can shift to overnight.

**16+ open positions:** Between-scan inference reduced to 7 of 13 windows. Freed windows run portfolio risk decomposition and position-level attribution on CPU. Scan output analysis becomes more detailed (per-position scoring rather than watchlist-level).

### Scoring backlog adaptation

The system tracks unscored training examples as a backlog metric.

**Backlog < 100 examples:** Reduce between-scan inference to 5 windows. Shift freed GPU time to overnight training experiments. The data asset is well-maintained; focus shifts to model quality.

**Backlog 100–500 examples:** Standard schedule. Between-scan scoring operates at full 10-window capacity.

**Backlog > 500 examples:** Extend post-market inference by 1 hour (push VRAM handoff from 6:50 PM to 7:50 PM, reducing overnight training by 1 hour). At 3 examples/minute, this recovers ~180 additional examples per day.

**Backlog > 1,000 examples:** Emergency scoring mode. Overnight GPU switches from training to Ollama inference (skip nightly training entirely). This yields ~17 hours of continuous inference, scoring ~3,000 examples in one night. Training debt accumulates but is recoverable on the weekend.

### Known economic event adaptation

Maintain a calendar of scheduled releases (FOMC decisions, NFP, CPI, earnings for held positions). For any event occurring during market hours, the system clears between-scan inference for the 30-minute window before and after the event. This provides full GPU headroom for potentially volatile post-release scans.

---

## Optimal task frequencies based on research

The academic and industry literature converges on specific frequencies for each task category. These recommendations inform which tasks run daily versus weekly.

**Training data scoring (LLM-as-judge):** Score **50–100 examples per weekday** in batches. Evidently AI recommends continuous evaluation on live data; Hugging Face's LLM Judge cookbook indicates 30 examples suffice for calibrating a judge. Diminishing returns set in above ~200 examples/day for a 100-stock universe. Binary or 3-point scoring scales are more reliable than 10-point scales.

**Model evaluation:** Run **lightweight daily monitoring** (P&L, Sharpe, hit rate tracking on CPU) plus **deep weekly evaluation** (walk-forward validation on Saturday, aligned with retraining). Full walk-forward optimization (per Pardo 1992) should run monthly or quarterly. The QuantInsti ADDM algorithm recommends drift-triggered evaluation using SETAR-based regime detection.

**Database maintenance:** PostgreSQL's autovacuum handles routine cleanup automatically at ~1,000 rows/day growth. Run manual VACUUM ANALYZE **weekly on Saturday**. REINDEX monthly at most. VACUUM FULL is unnecessary at this scale. SQLite requires even less: weekly VACUUM suffices.

**Feature computation:** Daily after market close for rolling statistics. Weekly for sector correlations (these change slowly over 60+ day windows). UC Berkeley research (2025) showed a Regret-Proportional update policy achieves near-optimal quality with **61% fewer updates**, confirming that not every feature needs daily refresh. Regime features (VIX-derived) tolerate 1–3 day staleness since regimes shift over weeks, not hours.

**DPO preference pair generation:** Target **10–20 pairs per weekday**, accumulating to ~1,000 pairs before the first DPO training step (per Amazon SageMaker guidance). Quality dominates quantity—pairs with clear quality contrast between chosen and rejected responses train most efficiently. Meaningful DPO model improvement requires **5,000–10,000 high-quality pairs** (accumulating over 3–6 months at this rate). Run DPO training when a fresh batch of 500+ pairs has accumulated, approximately monthly.

---

## Monitoring metrics and alerting

### The five essential schedule health metrics

**1. Time since last successful run (per job).** This is the single most critical metric. A job accidentally removed from the schedule produces no errors—it simply never runs. Set alerts at 1.5× the expected interval for each job. If the nightly walk-forward backtest hasn't completed within 36 hours, something is silently broken.

**2. Job duration trend.** Plot execution time for each recurring job over the past 30 runs. A gradual upward trend signals data growth, resource contention, or model degradation. Alert when duration exceeds 2× the 30-day rolling mean.

**3. VRAM handoff success rate.** Track every Ollama→PyTorch and PyTorch→Ollama transition. Log VRAM state before and after (via `nvidia-smi`). Alert if post-handoff VRAM exceeds 500MB when it should be clear, or if the inference model takes more than 60 seconds to load.

**4. GPU temperature and throttling.** The RTX 3060 thermal throttles at **83°C** under sustained load. During 9.5-hour overnight training sessions, thermal management is critical. Alert at 80°C (warning) and 83°C (critical—pause workload for 5-minute cooldown). Monitor `clocks_throttle_reasons.hw_thermal_slowdown` via nvidia-smi.

**5. Schedule drift.** Track `actual_start_time - scheduled_start_time` for every job. Market scans must start within 30 seconds of schedule. Overnight training jobs within 5 minutes. Alert if any P0/P1 job drifts more than 60 seconds.

### GPU monitoring implementation

```python
# Poll nvidia-smi every 60 seconds, log to Prometheus
nvidia-smi --query-gpu=timestamp,temperature.gpu,utilization.gpu,
  memory.used,memory.total,power.draw,
  clocks_throttle_reasons.hw_thermal_slowdown
  --format=csv,noheader,nounits -l 60
```

**Key thresholds:** GPU temp > 80°C → fan curve adjustment; > 83°C → pause training for cooldown; VRAM > 11.5GB → OOM risk alert; sustained power near 170W TDP with low utilization → investigate bottleneck; ECC errors increasing → hardware degradation warning.

### Failure mode detection

| Failure Mode | Detection | Response |
|---|---|---|
| Silent job failure (exits 0, bad output) | Validate output: row counts, checksums, schema | Retry once; alert if retry fails |
| Silent non-execution | "Time since last run" exceeds threshold | Alert immediately; investigate scheduler state |
| VRAM leak (memory not freed after handoff) | Post-handoff VRAM check via nvidia-smi | Kill orphan GPU processes; restart Ollama |
| Training OOM crash | Exit code 137 or CUDA OOM exception | Reduce batch size by 25%; retry; alert |
| Zombie GPU process | nvidia-smi shows process with 0% utilization for >5 min | taskkill /F the PID; verify VRAM freed |
| Thermal throttling | Clock frequency drops below 80% of base | Pause workload 5 min; check case airflow |
| Schedule cascade failure | Upstream job delay causes downstream miss | DAG dependency tracking; skip-and-alert policy |

---

## Implementation architecture for Python on Windows

### APScheduler as the core scheduler

**APScheduler (Advanced Python Scheduler) is the optimal choice** for this system. It runs natively on Windows, supports cron-style triggers, persists jobs to SQLite (surviving restarts), handles misfires gracefully, and requires no external dependencies like Redis or RabbitMQ. Celery has poor Windows support. Airflow and Prefect add unnecessary complexity for a single-machine deployment. The lightweight `schedule` library lacks persistence and job stores.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

scheduler = BackgroundScheduler(
    jobstores={'default': SQLAlchemyJobStore(url='sqlite:///halcyon_jobs.db')},
    job_defaults={
        'coalesce': True,        # Merge missed runs into one
        'max_instances': 1,      # Never run same job twice
        'misfire_grace_time': 300 # 5-min grace for late starts
    }
)

# Sacred market scans — P0
scheduler.add_job(run_market_scan, 'cron', day_of_week='mon-fri',
                  hour='9-15', minute='0,30', id='market_scan',
                  misfire_grace_time=30)  # Tight grace for scans

# Between-scan inference scoring — P3
scheduler.add_job(run_between_scan_scoring, 'cron', day_of_week='mon-fri',
                  hour='9-15', minute='8,38', id='between_scan_score')

# Overnight training pipeline — P2
scheduler.add_job(run_overnight_training, 'cron', day_of_week='mon-fri',
                  hour=19, minute=0, id='overnight_train')

# Saturday weekly retrain — P1
scheduler.add_job(run_weekly_retrain, 'cron', day_of_week='sat',
                  hour=4, minute=30, id='weekly_retrain')
```

### VRAM handoff protocol

The most critical implementation detail is clean VRAM management. **Run all training in a subprocess** so that process termination guarantees complete VRAM release.

```python
import subprocess, requests, time

OLLAMA = "http://localhost:11434"

def handoff_inference_to_training():
    """Evening transition: Ollama -> PyTorch"""
    # 1. Unload Ollama model (frees ~5-6GB VRAM)
    requests.post(f"{OLLAMA}/api/generate",
                  json={"model": "halcyon-qwen3-8b", "keep_alive": 0})
    time.sleep(3)
    
    # 2. Verify VRAM is clear
    vram = get_gpu_vram_used()  # via nvidia-smi parsing
    assert vram < 500, f"VRAM not clear: {vram}MB"
    
    # 3. Launch training as subprocess (clean VRAM on exit)
    result = subprocess.run(
        ["python", "overnight_train.py", "--config", "weeknight.yaml"],
        timeout=43200  # 12-hour hard timeout
    )
    # When subprocess exits, ALL CUDA memory is freed by OS

def handoff_training_to_inference():
    """Morning transition: PyTorch -> Ollama"""
    # Training subprocess already exited (VRAM freed)
    time.sleep(2)
    
    # Preload inference model with long keep_alive
    requests.post(f"{OLLAMA}/api/generate",
                  json={"model": "halcyon-qwen3-8b", "keep_alive": "18h"})
    
    # Warm-up: run a test inference
    resp = requests.post(f"{OLLAMA}/api/generate",
                  json={"model": "halcyon-qwen3-8b",
                        "prompt": "System health check", "keep_alive": "18h"})
    assert resp.status_code == 200
```

### Between-scan scoring with guard band

```python
import threading, time
from datetime import datetime

class GuardedScorer:
    """Scores training examples between scans with automatic cutoff."""
    
    def __init__(self, guard_minutes=3):
        self.guard_minutes = guard_minutes
        self.scoring_active = False
    
    def next_scan_time(self):
        """Returns minutes until next :00 or :30 scan."""
        now = datetime.now()
        minute = now.minute
        if minute < 30:
            return 30 - minute
        return 60 - minute
    
    def score_batch(self, examples):
        """Score examples one at a time, respecting guard band."""
        self.scoring_active = True
        scored = []
        for ex in examples:
            if self.next_scan_time() <= self.guard_minutes:
                break  # Guard band reached — stop scoring
            result = ollama_score(ex)  # ~15-20 sec per call
            scored.append(result)
        self.scoring_active = False
        return scored
```

### Recommended tech stack

The full implementation requires these Python libraries:

- **APScheduler 3.x** — Core scheduler with SQLite job store
- **`ollama`** Python client — Model management and inference API
- **PyTorch** — Training in subprocess
- **FastAPI** — Health check HTTP endpoint (`:8080/health`)
- **`prometheus_client`** — Metrics exposition for Grafana dashboards
- **`psutil`** — CPU, RAM, disk monitoring
- **`subprocess`** — Training process isolation for clean VRAM
- **Windows Task Scheduler** — Watchdog only: restarts the Python scheduler if it crashes

Set NVIDIA exclusive process mode (`nvidia-smi -c EXCLUSIVE_PROCESS`) to prevent accidental concurrent GPU access. Set `OLLAMA_MAX_LOADED_MODELS=1` to prevent Ollama from loading multiple models. Use `OLLAMA_KEEP_ALIVE=0` as the default, overriding per-request with long keep_alive values during market hours.

---

## Conclusion: the compounding value of filling dead time

Three insights make this schedule work. First, **between-scan inference is free utilization**—the model is already loaded, so scoring training examples between scans costs zero VRAM overhead and at most 20 seconds of scan delay, well within the guard band. This single insight recovers 1.6 GPU-hours daily from what appeared to be untouchable market-hours idle time. Second, **the VRAM constraint forces exactly two transitions per weekday** (evening swap to training, morning swap to inference), and running training as a subprocess makes these transitions deterministic. Third, the overnight training block isn't just about model retraining (that's Saturday)—it's about the entire constellation of GPU-intensive batch work that compounds the data asset: walk-forward backtesting, DPO updates, feature importance, and auxiliary model training.

The weekly scoring throughput of **~1,450 LLM-judged training examples** plus **~75 DPO preference pairs** means the data asset grows substantially every week. After 3 months, the system will have accumulated ~17,000 scored examples and ~900 preference pairs—approaching the thresholds where DPO training and expanded fine-tuning yield measurable model improvement. This is the compounding engine: GPU utilization today creates the data that makes next month's model better, which generates better training signals, which further improves the month after that. The schedule isn't just about hitting 73% utilization—it's about converting idle silicon into a deepening competitive moat.
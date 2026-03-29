# The Halcyon Framework: compute, value, and moat for a solo AI trading system

**An AI trading system's long-term value is determined less by its Sharpe ratio than by the compounding speed of its data flywheel and the strategic slack built into its compute architecture.** This report synthesizes queuing theory, SRE principles, venture capital valuation frameworks, and operations research to deliver a practical operating framework for Halcyon Lab — a Python/React system running Qwen3 8B on an RTX 3060 12GB around the clock. The core finding: target **75% sustained GPU utilization** (not higher), retrain models **weekly** (not nightly), and measure system health across five dimensions with phase-dependent weights. These recommendations are grounded in Kingman's queuing formula, Google's SRE error budget methodology, Toyota's production system philosophy, and empirical evidence from quantitative trading firms.

---

## Why 75% utilization is the magic number

Queuing theory provides the mathematical foundation for why maximizing GPU utilization destroys the very performance it aims to optimize. **Kingman's formula** — W_q ≈ (ρ/(1−ρ)) × ((c_a² + c_s²)/2) × τ — predicts that average wait time grows hyperbolically as utilization (ρ) approaches 1.0. The practical impact is stark:

| GPU Utilization | Wait Time Multiplier | System Behavior |
|:-:|:-:|:--|
| 50% | 1× | Comfortable headroom |
| 70% | 2.3× | Optimal operating point |
| 80% | 4× | Acceptable for batch-only |
| 90% | 9× | Inference latency degrades visibly |
| 95% | 19× | Effectively unusable for real-time work |

The multiplier column represents wait time as a factor of raw service time. At **70% utilization, inference latency stays near 50ms; at 90%, it balloons to 500ms** — enough for API timeouts and missed trading windows. The variability term (c_a² + c_s²)/2 amplifies everything: mixed workloads with bursty inference requests and variable-length training batches push the "elbow" of the hockey stick curve earlier, toward lower utilizations. For mixed real-time + batch workloads on a single GPU, multiple converging sources place the sweet spot at 70–75%: the University of Wisconsin CS 547 curriculum teaches 70% as the practical ceiling, AWS Compute Optimizer's "Balanced" preset targets 70% CPU with 30% headroom, and the **Liu-Layland real-time scheduling bound** mathematically proves that CPU utilization must stay below 69.3% to guarantee deadline compliance across many concurrent tasks.

**Priority queuing changes the calculus favorably but doesn't eliminate it.** With preemptive priority scheduling — where trading inference always interrupts training batches — the high-priority inference class sees only its own utilization (ρ₁), behaving as if training doesn't exist. If inference consumes 30% of GPU capacity, its effective wait time is just 1.43× service time regardless of total utilization. Training sees total utilization. This means inference at ≤30%, training at ≤45%, and 25% reserved as strategic slack yields **75% total utilization** with excellent inference latency and tolerable training throughput. The critical caveat from queuing literature: prioritize no more than 20–30% of total work, or the non-priority jobs face near-infinite wait times.

---

## Strategic slack is not wasted capacity

Every high-performing production system deliberately underutilizes its resources. **Toyota's production system schedules 10 hours of work into 12-hour shifts**, leaving two hours for preventive maintenance and problem-solving — roughly 83% planned utilization with built-in slack. While competitors ran three shifts to maximize throughput, Toyota ran two shifts and outperformed them on quality, adaptability, and long-term output. The insight from Factory Physics (Hopp & Spearman): variability must be buffered by inventory, capacity, or time. Toyota chose the capacity buffer, and it worked.

Tom DeMarco's *Slack* (2001) formalized this for knowledge work: organizations optimized for 100% efficiency lose their ability to respond to change, with a **minimum 15% task-switching penalty** when workers are kept at full utilization. Scrum teams routinely plan at 75–85% of historical velocity, reserving 10–20% for unplanned interrupts. Google's 20% time — which produced AdSense (now ~25% of Google's revenue) — demonstrated that reserving capacity for experimentation generates outsized returns, though in practice only about 10% of engineers consistently used it.

For Halcyon Lab on an RTX 3060, the recommended allocation is:

| Component | GPU Compute | VRAM | Rationale |
|:--|:-:|:-:|:--|
| Trading inference | ≤30% | 4–5 GB | Latency-critical; sees M/M/1 queue at ρ=0.30 |
| Batch training | ≤45% | 6–7 GB | Low-priority, preemptible by inference |
| Strategic slack | ≥25% | 1–2 GB | Burst absorption, thermal headroom, experimentation |

The 25% slack serves five functions: absorbing inference bursts during market volatility, preventing thermal throttling (which increases service time variability and per Kingman's formula amplifies queue times), providing capacity for ad-hoc analysis and model experimentation, buffering against VRAM fragmentation in the tight 12GB envelope, and enabling fast recovery from training failures without impacting live trading.

---

## How quant firms solve "always trading, always learning"

Every major quantitative firm physically separates live trading infrastructure from research compute — a pattern that holds from Renaissance Technologies' 50,000-core on-premises cluster to Citadel Securities' hybrid architecture. The **Citadel Securities–Google Cloud case study** is the most revealing first-party source: research workloads were migrated to Google Cloud for elastic scaling while trading infrastructure remains co-located at exchanges on dedicated hardware. The rationale was explicit — "the timing and volumes of research could fluctuate greatly" while trading demands are predictable.

Renaissance Technologies, operating roughly **150,000–300,000 trades daily** with a system that's right on only about 50.75% of trades, derives its edge not from any single model but from **iteration speed**. Peter Brown identified "infrastructure" as one of RenTec's five core principles. The original 5% management fee was literally sized to cover the $800K compute budget for a $16M fund. Two Sigma's engineering organization reveals the pattern through its team structure: separate Trading Engineers, Platform Engineers, Data Engineers, and Reliability Engineers — with dedicated reliability teams for mission-critical trading systems.

**For a solo operator, the institutional pattern adapts to time-slicing.** Market hours (9:30 AM–4:00 PM ET) should reserve the GPU for lightweight quantized inference. Off-hours and weekends get full GPU allocation for training, backtesting, and hyperparameter sweeps. This mirrors how even large firms batch heavy compute outside trading hours. The QuantRocket principle applies: "Use a dedicated machine for live trading, not the same machine you use for research. Every time you load a large dataset or run a CPU-intensive analysis, you jeopardize live trading." On a single RTX 3060, Docker container isolation and cron-scheduled training jobs approximate the physical separation that institutions achieve with separate server farms.

The SRE literature reinforces this with specific targets. Google's SRE framework defines error budgets as 100% minus the SLO target — a 99.9% SLO allows 43 minutes of downtime per month. For a solo-operator system with no redundancy and no on-call team, a realistic target is **99.5% SLO (~3.65 hours/month)**, accommodating weekly maintenance windows, GPU restarts, and occasional crashes. AWS recommends N+2 provisioning for enterprise systems; on consumer hardware, the equivalent is keeping utilization low enough that thermal events and driver crashes don't cascade into trading outages.

---

## Weekly retraining beats nightly retraining at 90% lower cost

The intuition that more frequent retraining produces better models is empirically wrong for most financial applications. A 2025 study on retraining frequency (arXiv 2505.00356) found that **periodic retraining produces equal or better forecasting performance compared to continuous retraining** — while reducing compute costs by approximately 90%. The mechanism: adding data in small daily increments rarely changes model behavior; meaningful signal accumulates over weeks, not days.

For financial markets specifically, concept drift occurs across four modes — sudden (crashes), gradual (secular trends), incremental (regime shifts), and recurring (seasonal patterns) — but the dominant timescales are weekly to monthly. A rolling-window approach with approximately **441 observations (~7 fiscal quarters)** is standard in financial ML research. The Harvard/MIT study (Vela et al., 2022, *Nature Scientific Reports*) found that **91% of ML models degrade over time**, with some showing "explosive degradation" — performing well for extended periods before suddenly collapsing. This argues for scheduled retraining with drift-triggered emergency retraining, not continuous retraining.

On the RTX 3060 running Qwen3 8B, the practical constraint is binding: full-precision fine-tuning requires ~60GB VRAM (impossible on 12GB). **QLoRA (4-bit quantization + LoRA adapters)** is the only viable approach, training 4–16M adapter parameters rather than the full 8.2B. A practical nightly session with ~1,000 examples and 3 epochs takes **2–8 hours**, consuming the GPU entirely and blocking inference. The recommended schedule: **weekly retraining on weekends** (Saturday overnight), with event-triggered emergency retraining when drift detection (population stability index, KS-test, or performance degradation >5%) signals a regime change. This preserves 6 of 7 nights for strategic slack, experimentation, and ad-hoc analysis — the 25% capacity buffer that Toyota, DeMarco, and Agile methodology all converge on recommending.

The continual learning literature (Kirkpatrick et al., 2017, PNAS) offers Elastic Weight Consolidation as a technique to prevent catastrophic forgetting during retraining — constraining important parameters to stay close to their old values using the Fisher Information Matrix. For financial models where old regimes can recur (the 2020 crash pattern resembling 2008), this is particularly relevant: the model must adapt to new regimes while remembering that historical patterns may return.

---

## Five dimensions of system value and how they interact

Synthesizing the Balanced Scorecard (Kaplan & Norton), Infonomics (Laney), platform economics (Parker & Van Alstyne), and intangible asset valuation (Damodaran, Lev), Halcyon Lab's value decomposes into five measurable dimensions:

**Dimension 1 — Trading Performance.** The lagging indicator that validates everything else. Measured by Sharpe ratio, maximum drawdown, win rate, and cumulative P&L. This is what VCs and acquirers ultimately care about, but it's the *output* of the other four dimensions, not an independent input. A Sharpe above 1.0 is good; above 2.0 is institutional-grade. Renaissance's Medallion Fund operates above 6.0, but at an entirely different scale.

**Dimension 2 — Model Quality.** The engine that converts data into tradeable signals. Measured by cross-validation scores, prediction calibration, rubric evaluation scores, and model decay rate (how quickly performance degrades without retraining). Andrew Ng's data-centric AI research shows that **data quality engineering consistently outperforms model architecture innovation by ~3%** — suggesting this dimension is more dependent on Dimension 3 than commonly assumed.

**Dimension 3 — Data Asset.** The most durable competitive advantage and the dimension most undervalued in early stages. Doug Laney's Infonomics framework provides six valuation methods; the most relevant for Halcyon are Economic Value (incremental alpha attributable to proprietary data vs. public alternatives) and Cost Value (what it would cost a competitor to replicate the temporal coverage). Companies treating data as an asset achieve **2–3x higher market-to-book ratios**. Financial training data appreciates with time — a 20-year dataset covering multiple regime changes is exponentially more valuable than a 2-year dataset, and this advantage compounds irreversibly with each year of operation.

**Dimension 4 — Business Potential.** The monetization surface area beyond direct trading returns. Newsletter subscribers, signal marketplace revenue, and SaaS API access each represent distinct value streams. Stratechery demonstrates the ceiling: Ben Thompson generates **$5M+ annually** as a solo operator with ~40,000 paid subscribers at $12/month. Financial data APIs (Polygon.io at $199/month, Alpha Vantage at $49.99/month) show the pricing power of curated data. The retention hierarchy from newsletter research is decisive: **reliability > analysis quality > prediction accuracy**. Morning Brew's $75M exit was built on consistent daily delivery and brand voice, not stock picks.

**Dimension 5 — Competitive Moat.** The meta-dimension measuring how defensible all other dimensions are. Andrei Hagiu's research (HBR 2020, RAND Journal 2023) identifies seven factors determining data moat durability — and warns that **data moats are usually overestimated**. The critical factors: whether the learning curve plateaus quickly (if so, competitors reach "good enough" with modest data), how fast data depreciates relative to learning speed, and whether insights can be imitated without the underlying data. Financial AI has structural moat advantages: temporal coverage is irreplaceable, real P&L labels are verified by markets, and rare tail events (crashes, liquidity crises) serve as high-value edge cases that Hagiu identifies as a key factor sustaining data advantages.

### How dimensions compound and conflict

Not all dimension pairs reinforce each other. The interaction map:

**Compounding pairs** (investing in one improves the other):
- **Data Asset × Model Quality**: More diverse, higher-quality data directly improves model calibration and robustness — this is the core AI flywheel. Each cycle (data → model → predictions → outcomes → labeled data) widens the gap vs. competitors.
- **Trading Performance × Data Asset**: Live trading generates verified outcome labels that backtested systems cannot produce. Every executed trade enriches the training dataset with ground-truth P&L data.
- **Model Quality × Business Potential**: Better models produce more accurate newsletter content and higher-quality API signals, driving subscriber retention and pricing power.
- **Competitive Moat × Data Asset**: Temporal coverage compounds irreversibly — each year of operation deepens the moat, and this is the one advantage that money alone cannot buy faster.

**Conflicting pairs** (optimizing one degrades the other):
- **Trading Performance × Model Quality (short-term)**: Aggressive retraining to chase recent performance can destroy model robustness through overfitting. The stability-plasticity tradeoff from continual learning literature applies directly.
- **Business Potential × Competitive Moat**: Publishing signals via newsletters or APIs reveals proprietary information, potentially enabling replication. Hagiu's seventh factor — "imitability of insights" — warns that even without the underlying data, the resulting improvements can be reverse-engineered.
- **Trading Performance × Business Potential (at scale)**: Strategy capacity constraints mean that publishing alpha-generating signals to subscribers eventually degrades those signals through crowded trades.

**There is no single "master metric"** — and attempting to create one introduces the compensation effect that plagues ESG scores, where poor performance in one dimension is masked by strength in another. Instead, the composite score should use a geometric mean (as the UN's Human Development Index switched to in 2010) to prevent full substitutability.

---

## A computable weekly system health score

Drawing on the Altman Z-Score's discriminant analysis approach, FICO's outcome-calibrated weighting, and HDI's geometric mean aggregation, the proposed **Halcyon System Health Score (HSHS)** is:

**HSHS = (P^w₁ × M^w₂ × D^w₃ × F^w₄ × C^w₅) ^ (1/(w₁+w₂+w₃+w₄+w₅))**

Where each component is normalized to a 0.01–1.0 scale:

- **P (Performance)** = 0.6 × norm(Sharpe) + 0.4 × norm(1/MaxDrawdown)
- **M (Model Quality)** = 0.4 × norm(RubricScore) + 0.3 × norm(CalibrationAccuracy) + 0.3 × norm(1/DecayRate)
- **D (Data Advantage)** = 0.3 × norm(ProprietaryDataPct) + 0.3 × norm(log(DataVolume)) + 0.2 × norm(DataFreshness) + 0.2 × norm(SignalDimensions)
- **F (Flywheel Velocity)** = 0.5 × norm(1/FeedbackCycleTime) + 0.5 × norm(WeeklyDataGrowthRate)
- **C (Competitive Defensibility)** = 0.4 × norm(TimeToReplicate) + 0.3 × norm(IntegrationDepth) + 0.3 × norm(UniqueSignalCount)

**Phase-dependent weights shift as the system matures:**

| Dimension | Months 1–6 | Months 7–18 | Months 18+ |
|:--|:-:|:-:|:-:|
| Performance (w₁) | 0.10 | 0.20 | 0.30 |
| Model Quality (w₂) | 0.25 | 0.20 | 0.15 |
| Data Advantage (w₃) | **0.35** | **0.25** | 0.20 |
| Flywheel Velocity (w₄) | 0.15 | 0.20 | 0.10 |
| Defensibility (w₅) | 0.15 | 0.15 | **0.25** |

The rationale: in the first six months, **data accumulation is the dominant activity** — the system is building temporal coverage and establishing the flywheel. Performance data is too sparse for statistical significance (a meaningful Sharpe requires ~2 years of daily returns). By months 7–18, the system has enough data to validate model quality and begin monetization. Beyond 18 months, defensibility becomes paramount because competitors have had time to observe and attempt replication.

**Leading vs. lagging indicators should be tracked separately.** The leading sub-score (Data Volume growth rate, Model convergence metrics, Feature importance stability, Feedback loop cycle time, New signal dimensions explored) predicts future HSHS movement. The lagging sub-score (Sharpe ratio, Cumulative P&L, Subscriber retention, Max drawdown) confirms whether the leading indicators are translating into real value. In the first six months, leading indicators should receive **80% of management attention** — the lagging indicators simply don't have enough data to be statistically meaningful.

---

## Measuring moat depth in practice

Quantifying competitive moats requires treating "replication difficulty" as a measurable engineering quantity rather than a qualitative judgment. Four metrics, computable monthly:

**Time-to-replicate (TTR)** estimates how long a well-funded competitor would need to reproduce the system's current capability. For Halcyon Lab's data moat, this equals the temporal span of proprietary training data: if the system has 18 months of live-traded, outcome-labeled data across 500 securities, no amount of capital can compress that to less than 18 months. Model architecture can be replicated in weeks; curated data pipelines in months; temporal coverage never.

**Proprietary data ratio** measures what percentage of total training data is unavailable through commercial data vendors. The VC consensus is clear: acquirers pay a **5–10x valuation premium** for systems with genuine data moats versus equivalent systems using only public data. Opagio's 2026 framework ranks data moats as the most durable moat type, with model moats offering only 12–36 months of advantage before competitors close the gap.

**Signal orthogonality** counts independent (uncorrelated) signal dimensions using eigenvalue analysis of the correlation matrix. More eigenvalues above 1.0 indicate more independent information sources. Higher dimensional signal spaces are combinatorially harder to replicate — a system synthesizing 15 independent signal dimensions requires a competitor to independently discover and integrate all 15.

**Feedback loop cycle time** measures the duration from prediction to outcome observation to model update. Faster cycles compound the data advantage: if Halcyon's flywheel completes a full cycle weekly while a competitor's takes monthly, the gap widens by approximately 4× per quarter. Tesla's autonomous driving data flywheel — collecting billions of driving frames through normal product usage — demonstrates how embedded feedback loops create compounding advantages that scale with usage.

---

## Conclusion: the operating playbook

The evidence converges on a clear operating framework for Halcyon Lab. **Keep GPU utilization at 75%**, with inference capped at 30%, training at 45%, and 25% reserved as strategic slack — this keeps the system on the flat portion of Kingman's latency curve while preserving the experimentation capacity that Toyota, Google, and DeMarco all identify as essential for continuous improvement. **Retrain weekly, not nightly**, saving 90% of compute costs with equal or better model performance, and trigger emergency retraining only when drift detection signals regime change. **Measure system health across five dimensions** using a geometric-mean composite score with phase-dependent weights that shift from data accumulation (months 1–6) to defensibility (months 18+). **Separate leading from lagging indicators** and allocate 80% of early-stage attention to the leading sub-score, since Sharpe ratios need years of data to reach statistical significance.

The single most underappreciated insight from this research: **the data asset — not the model, not the returns — is the most valuable component** of an AI trading system. Hagiu's seven-factor framework suggests financial AI has structural advantages in data moat durability (irreplaceable temporal coverage, market-verified labels, high-value tail events). Every week the system operates, it accumulates an asset no competitor can buy. The utilization framework, the retraining schedule, and the health score all serve one strategic purpose: keeping the flywheel spinning reliably while the data moat deepens.
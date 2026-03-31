# Arcis — Milestones

## Completed Milestones

### M1 — Foundation
- Repo structure, docs, blueprint, config, SQLite journal, CLI skeleton

### M2 — Research Core
- S&P 100 universe, yfinance ingestion, feature engine (20+ indicators)

### M3 — Trade Packets
- Ranking engine, packet templates, email delivery

### M4 — LLM Integration
- Ollama/Qwen inference, LLM packet writer, system prompts

### M5 — Shadow Trading
- Alpaca paper trading, bracket orders, trade lifecycle management

### M6 — Data Enrichment
- SEC EDGAR fundamentals, Finnhub insiders/news, FRED macro data, multi-source prompt

### M7 — Training Pipeline v1
- Historical backfill, Claude training data generation, Unsloth fine-tuning, auto-rollback

### M8 — Review System
- Human review workflow, scorecards, postmortem generation, bootcamp reports

### M9 — Risk & Governance
- Risk governor (8 checks), kill switch, daily/weekly auditor, CTO report

### M10 — Advanced Training
- Holdout validation, A/B model evaluation, learned confidence, feature importance

### M11 — Quality Pipeline
- News enrichment, three-stage curriculum, LLM-as-judge quality scoring, DPO preference pairs, contrastive training data, dataset validation

### M12 — Dashboard v1
- React/Vite/Tailwind dashboard, WebSocket live updates, CTO Report page, error handling

### M13 — Self-Blinding Pipeline
- Self-blinding training data generation (Claude never sees outcomes)
- Process-first quality rubric with behavioral anchors (6 dimensions)
- Outcome leakage detector with balanced accuracy for class imbalance
- XML-tagged output format (<why_now>, <analysis>, <metadata>)
- Re-run backfill: 976 self-blinded examples

### M14 — halcyon-v1 Training
- Scored 976 examples with process-first rubric
- Leakage check: MARGINAL (60.2% balanced accuracy — feature-level, not leakage)
- Trained halcyon-v1: Qwen3 8B fine-tuned on 790 examples via PEFT + TRL 0.24
- GGUF export (Q8_0) and Ollama registration

### M15 — Dashboard v2
- Fund metrics (Sortino, Calmar, VaR, batting avg, skewness) on CTO Report
- MetricTrend component with selectable metrics and date ranges
- API cost tracking (per-call logging, by-purpose breakdown, daily chart)
- WebSocket hook with auto-reconnect
- Auto-refresh on all pages (Dashboard 60s, Ledger 30s, Training 60s)
- Action buttons (scan, CTO report, collect training, train pipeline, score)
- Live activity feed with color-coded events
- Config restart warning banner
- 13 research documents on Docs page with category grouping

### M16 — 24/7 Operations
- Overnight schedule: post-close capture, training collection, news ingestion, enrichment pre-cache, pre-market refresh
- Unified train-pipeline command (score → leakage → classify → train)
- `--overnight` flag for watch loop

### M17 — Data Collection Pipeline
- Options chain snapshots (EOD, full universe via yfinance)
- Options derived metrics (IV rank, put/call ratios, IV skew, unusual activity)
- VIX term structure (VIX, VIX9D, VIX3M, VIX1Y + ratios)
- CBOE put/call ratios
- Expanded FRED macro (14 series including GSCPI, yield curve, credit spreads)
- Google Trends attention signal (batched rotation)
- 9:30 PM overnight slot + manual CLI command

### M18 — Research & Strategy
- 13 research documents completed (training, strategy, business, options)
- Business model pivot: investing returns → fund management
- Universe expansion decision: S&P 100 → ~325 stocks (Phase 2)
- Options trading strategy designed (credit spreads, iron condors, LLM as volatility analyst)
- 5-phase roadmap with fund-grade gate metrics
- Comprehensive codebase audit (100 files, 15,556 lines)

### M19 — Tech Debt Cleanup (CC Sprint)
- Fixed default equity fallback in risk governor ($5K → config)
- Auto-switch to active model version in LLM client
- Consolidated dual WebSocket connections into shared context
- Silent except-pass → logger.debug across 9 locations
- Unused imports removed, print → logger across 13 modules
- Fixed metric_history days filter bug, resource leak, margin label
- 16 issues fixed (11 known + 5 new), 257 tests passing

### M20 — 24/7 Compute Scheduler
- GuardedScorer: between-scan inference scoring (~420 examples/day, 3-min guard band)
- VRAMManager: evening/morning VRAM handoffs with nvidia-smi monitoring, subprocess isolation
- OvernightPipeline: 7-task pipeline (holdout, DPO, feature importance, leakage, rolling stats, DB maintenance, health)
- PreMarketPipeline: rolling features, training gen, news scoring, candidate pre-analysis
- Schedule metrics table with API endpoint
- 86 new tests (363 total passing)
- GPU utilization target: 2-3% → 73%

### M21 — Telegram Notifications + Earnings Calendar
- Telegram Bot API integration: trade opens/closes, earnings warnings, overnight summary, system events
- Earnings calendar scraper with overnight integration (step 7/7)
- Cached earnings lookup for fast scan-time access
- 5 new FRED credit/financial conditions series (BBB spread, NFCI, stress index, claims, breakeven)
- Market event calendar CSV (422 events, 2020-2027)
- 19 research documents on dashboard (regime timeline, company profiles, compute schedule, API comparison)

### M22 — Mega Sprint (Cloud + Council + Telegram + Docs)
- Render cloud deployment: Blueprint (render.yaml), Postgres schema, local→cloud sync, cloud-only FastAPI app
- AI Council system: 5-agent Modified Delphi protocol (Risk Officer, Alpha Strategist, Data Scientist, Regime Analyst, Devil's Advocate), 3-round deliberation, SQLite persistence, dashboard integration
- Setup classifier: rule-based classification (pullback, breakout, momentum, mean_reversion, range_bound, breakdown) with confidence scoring
- Expanded Telegram bot: /council command (on-demand council sessions), setup_type in trade notifications, interactive command handler with 10 commands
- Dashboard v3: Council page, Deployment page, roadmap enhancements
- Deployment guide (docs/deployment.md) with step-by-step Render instructions
- Documentation updates across AGENTS.md, architecture.md, milestones

## Upcoming

### M23 — Phase 2 Preparation
- Universe expansion to ~325 stocks
- GICS sector conditioning feature
- Polygon.io integration
- Wyoming LLC formation + Section 475 MTM election
- IB account + adapter

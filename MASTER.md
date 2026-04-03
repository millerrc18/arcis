# MASTER.md — Arcis Consolidated Reference

> Single document consolidating SYSTEM_STATE.md, AGENTS.md, conventions.md,
> sprint-checklist.md, and schema-governance.md. Inverted pyramid: critical
> information first. Target: ~800-1,000 lines / ~5K tokens.
>
> **Canonical source for:** system identity, current state, architecture,
> schema, strategy decisions, phase gates, frameworks, revenue, conventions,
> principles, sprint queue, and brand.

---

## 1. System Identity

**Name:** Arcis (Adaptive Regime Classification & Intelligence Systems)
**License:** BSL 1.1 (source-visible, no commercial use until 2030)
**Release:** v0.1.0
**Repository:** github.com/millerrc18/halcyon-lab
**Dashboard:** halcyonlab.app (Render static + Python API)

**Purpose:** Autonomous AI trading system that scans, analyzes, and executes
equity trades. Combines systematic technical scoring with LLM-generated
institutional-quality commentary, multi-source data enrichment, Alpaca bracket
orders, an 8-check risk governor with kill switch, and a self-improving
training pipeline with quality gates.

**Core Principle:** Training data quality is the #1 competitive advantage.
Never sacrifice quality for speed.

**Business Model:** Investing returns, not newsletter. Scale by growing capital
under management. Family LP structure planned for external capital.

**Long-term Goal:** Quantitatively be the best AI autonomous trading platform
with an unbeatable technological moat.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, SQLite (raw sqlite3, no ORM)
- Frontend: React 19, Tailwind 4, Vite 8, TanStack Query
- LLM: Ollama local (halcyon-v1.0.0, Qwen3 8B fine-tuned, Q8_0 GGUF 8.7GB)
- Training: PEFT + TRL 0.24 + BitsAndBytes on RTX 3060 12GB
- Trading: Alpaca paper + live API (bracket orders, GTC)
- Deployment: Render (static frontend + Python API + Postgres read-replica)
- Config: YAML (`config/settings.*.yaml`) + `.env` for secrets

---

## 2. Current State -- Volatile

> **This section is updated after every sprint.** Run `scripts/verify_docs.py`
> to check for drift against live system counts.

### Key Metrics

| Metric | Value |
|---|---|
| Phase | 1 (Bootcamp) -- paper $100K + $100 live via Alpaca |
| Closed trades | 13 (12W / 1L, 92% WR, $860 total P&L) |
| Open positions | 25 |
| Model | halcyon-v1.0.0 (Qwen3 8B, Q8_0 GGUF) |
| Training data | 976 examples, scored, 20 unique tickers |
| Tests | 1,301 functions across 101+ test files |
| Python files | 194 |
| Dashboard pages | 18 |
| Research docs | 60 |
| Schema tables | 49 (registry) |
| GitHub issues | 17 open |
| Monthly cost | ~$64 (Render $7 + Ollama free + Claude API ~$50 + domain $7) |
| Hardware | RTX 3060 12GB, Windows 11, Z690, 24/7 operation |
| HSHS health score | 85.33 |
| Universe | S&P 100 (expanding to ~325 in Phase 2) |

### Deployed Components

| Component | Status |
|---|---|
| Watch loop (scan + monitor) | LIVE -- 13 scans/day, overnight mode |
| Traffic Light | LIVE -- bootcamp floor 0.5 |
| Risk governor | LIVE -- 8 checks |
| Council v2 (5 agents) | LIVE -- failure sends Telegram alert |
| Build Score KPI | LIVE -- 6-component geometric mean |
| Between-scan quality scoring | LIVE -- GuardedScorer Ollama, 972/972 scored |
| Command queue + config overrides | LIVE -- pull-based, 10 command types |
| 12 overnight collectors | RUNNING |
| Telegram | LIVE -- 32 functions, gated behind trade_id |
| Intra-day reconciliation | LIVE -- every 15 min during market hours |
| Dashboard (Arcis) | LIVE -- 16 pages, dark/light toggle |
| Schema registry | LIVE -- 46 tables, single source of truth |
| Render sync | LIVE -- 40/46 tables synced to Postgres |
| Automated guardrails | LIVE -- test_repo_structure.py |
| CI on PRs | LIVE -- tests + guardrails + frontend build |
| PEAD enrichment (5 signals) | DEPLOYED |
| Implementation Shortfall | DEPLOYED |

### Open GitHub Issues

| # | Priority | Title |
|---|---|---|
| #147 | P2 | No exponential backoff on network failures in enrichment |
| #132 | P2 | Fallback to settings.example.yaml with placeholder keys |
| #112 | P2 | VRAM not freed after training -- GPU memory leak |
| #106 | P2 | Kill switch not atomic, no staleness check |
| #82 | P3 | Silent exception swallowing in council/context.py |

### Known Blockers

- Database on OneDrive path risks WAL corruption (incident #181); move to
  local path or exclude `*.sqlite3*` from sync
- UPS not yet purchased (CyberPower CP1500PFCLCD, ~$220)
- LLM conviction parsing broken: 143/145 return None, all trades use default=5
  (#183)

### Sprint History

| Sprint | PR | Key Deliverable |
|---|---|---|
| 4A (Codex) | #73 | Arcis rebrand, Palette H, v0.1.0 |
| 4B (CC) | #75 | Build Score, dashboard hero, .env wiring |
| 4C (CC) | #76 | Command queue, config overrides, Logs page |
| 4D (Codex) | #74 | Module registry, 138 docstrings, conventions.md |
| 4E (CC) | #77 | DB migration, Traffic Light, scan recording, README |
| 5 (CC) | #78 | Dashboard polish (8 pages redesigned) |
| 6 partial | #88 | .env secret migration (10 modules, 11 tests) |
| CC deep audit | -- | 71 issues filed (#100-#169), health 6.5/10 |
| 7 (CC) | #172 | Reliability: crash handler, GTC brackets, heartbeat, sync mutex (18 issues) |
| Reconciliation | #171 | Daily postclose paper trade reconciliation vs Alpaca |
| 8 (CC) | #173 | Comprehensive cleanup: 63 issues closed |
| Analytics migration | #174 | Cloud endpoints read Postgres |
| Dashboard redesign | #175 | Shadow/Live Ledger redesign, CTO period selector |
| Log audit | #176 | Double logging fix, idempotent ALTER TABLEs, DNS retry |
| Data integrity | #177 | Reconciliation actual_exit_time fix, paper auto-close |
| Schema registry | #189 | 46 tables in registry, all DDL removed, CI guardrails |
| Mega Sprint | #178 | Intra-day recon, exit_failed recovery, React Flow, sidebar sections |

---

## 3. Architecture Overview

### System Flow

```
Universe (S&P 100)
  -> Data Ingestion (yfinance OHLCV)
  -> Feature Engine (technicals, regime, sector, earnings)
  -> Data Enrichment (fundamentals, insiders, news, macro)
  -> Ranking & Qualification (score 0-100)
  -> Risk Governor (8 checks + kill switch)
  -> LLM Packet Writer (Ollama/halcyon-v1 -> prose commentary)
  -> Shadow Execution (Alpaca bracket orders)
  -> Training Loop (self-blinding -> scoring -> leakage check
     -> curriculum SFT -> holdout -> A/B eval)
  -> Data Collection (12 collectors overnight)
```

### Component Table

| Layer | Components |
|---|---|
| 4 Orchestration | watch.py, main.py |
| 3 Services | scan_service.py, council/engine.py, *_service.py |
| 2 Domain | executor.py, governor.py, traffic_light.py, features/*, ranker.py |
| 1 Infrastructure | alpaca_adapter.py, telegram.py, render_sync.py, llm/client.py |

**Rule:** Imports only go DOWN. Never import from a higher layer.

### Execution & Risk

- **Bracket Orders:** Entry + stop-loss + take-profit via Alpaca paper trading
- **Risk Governor:** 8 checks (emergency halt, daily loss, position size, max
  positions, sector concentration, correlation, volatility halt, duplicate)
- **Kill Switch:** `halt-trading` command or dashboard button halts all new
  positions immediately
- **Intra-day Reconciliation:** Every 15 min during market hours, resolves
  exit_failed/exit_pending trades
- **Post-close Reconciliation:** 8-point confidence check at 4:30 PM

### Scope

**In scope:** S&P 100 (expanding to ~325), long-only equity swing trades
(2-15 day holds), systematic scoring + LLM commentary + bracket execution,
self-improving training pipeline, risk management with safety rails, passive
options/volatility data collection.

**Out of scope (current phase):** Options trading (passive collection only),
short selling, high-frequency / intraday trading, live trading with real money.

### Data Sources

**Enrichment (7 -- used in every scan):**
1. Technical Data -- price, volume, MAs, RSI, ATR, trend, relative strength
2. Market Regime -- SPY trend, volatility, breadth, drawdown classification
3. Sector Context -- sector relative strength rank, sector average score
4. Fundamental Snapshot -- SEC EDGAR: revenue, margins, PE, growth rates
5. Insider Activity -- Finnhub: buy/sell transactions, sentiment
6. Recent News -- Finnhub: headlines, simple sentiment scoring
7. Macro Context -- FRED: Fed Funds, yield curve, unemployment, CPI, GDP + 9 expanded series

**Collection (12 -- overnight pipeline):**
1. Options Chains -- full EOD via yfinance (strikes, IV, Greeks, OI)
2. Options Metrics -- IV rank, put/call ratios, IV skew, unusual activity
3. VIX Term Structure -- VIX, VIX9D, VIX3M, VIX1Y + contango/backwardation
4. CBOE Ratios -- equity, index, total put/call ratios
5. FRED Macro (34+ series) -- housing, employment, trade, consumer, financial
6. Google Trends -- 8 sentiment terms (crash, recession, inflation, etc.)
7. Earnings Calendar -- next earnings date, imminent report flagging
8. SEC EDGAR Filings -- 10-K, 10-Q, 8-K with parsed sections
9. Insider Transactions -- Form 4 via Finnhub (nightly)
10. Short Interest -- FINRA via Finnhub (biweekly)
11. Fed Communications -- FOMC statements, minutes, Beige Book, speeches
12. Analyst Estimates -- consensus recs + price targets via Finnhub

### Infrastructure

| Service | Purpose |
|---|---|
| Alpaca Markets API | Paper + live trading execution |
| Ollama | Local LLM inference (halcyon-v1) |
| Anthropic Claude (Haiku 4.5) | Training data generation, quality scoring |
| Finnhub API | Insider, news, short interest, analyst estimates |
| FRED API | 34+ macroeconomic series |
| SEC EDGAR | Fundamental data (free, 10 req/sec) |
| yfinance | OHLCV + options chains |
| Telegram Bot API | Real-time push notifications (32 functions) |
| Render | Cloud hosting: static frontend + FastAPI + Postgres |

### Configuration

**Two files, clear separation:**
- `config/settings.yaml` -- ALL non-secret config (committed). Thresholds,
  intervals, feature flags, model names.
- `.env` -- ALL secrets (gitignored). API keys, tokens, passwords.

**Key YAML sections:** `bootcamp.*`, `shadow_trading.*`, `risk.*`, `llm.*`,
`scheduler.*`, `automation.*`, `training.*`, `data_enrichment.*`, `council.*`

**Secrets in .env:** `ALPACA_API_KEY`, `ALPACA_API_SECRET`,
`ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY`, `ANTHROPIC_API_KEY`,
`FINNHUB_API_KEY`, `FRED_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`EMAIL_PASSWORD`, `DATABASE_URL`

### Claude Code Automations

**MCP Servers (4):** alpaca (trading API), context7 (live docs), github
(issues/PRs), sqlite (direct DB queries)

**Hooks (6):** auto-lint Python (ruff on edit), auto-lint JSX (eslint on edit),
schema DDL warning, block .env edits, block lock file edits,
post-merge validation (schema + docs drift on `git merge`/`git pull`)

**Skills (7):**

| Skill | Invoke | Purpose |
|---|---|---|
| gen-test | `/gen-test src/module.py` | Generate pytest files matching project conventions |
| post-close-check | `/post-close-check` | Alpaca vs local ledger reconciliation |
| config-check | `/config-check [--fix]` | Detect config drift between example and local |
| market-monitor | `/market-monitor 5m` | Recurring reconciliation on interval |
| arcis-status | `/arcis-status` | Compact system status snapshot (phase, positions, equity, training, audit) |
| retrain-check | `/retrain-check` | 8-point preflight gate before GPU training |
| visual-check | `/visual-check` | Screenshot all 18 dashboard pages via Playwright |

**Agents (6):**

| Agent | Purpose | When to Use |
|---|---|---|
| security-reviewer | Credential exposure, SQL injection, risk governor bypass | Before merging PRs touching risk/api/.env code |
| test-runner | Full pytest suite, failure grouping, CI guardian check (1105 min) | After code changes, before commits |
| migration-checker | Schema change idempotency, cross-script sync, backwards compat | When columns or tables are added/modified |
| drift-detector | Schema drift, config drift, doc staleness, data staleness, orphaned positions | Start of every coding session |
| data-integrity-checker | FK integrity, orphaned records, data quality across 49 tables | After recovery, before releases |
| api-documenter | Route inventory, frontend-backend consistency, auth gaps | After adding/changing API endpoints |

**Plugins (11 relevant):** commit-commands, code-simplifier, ralph-loop,
telegram, claude-md-management, claude-code-setup, skill-creator,
frontend-design, feature-dev, pr-review-toolkit, security-guidance

---

## 4. Schema Summary

All 46 tables are defined in `src/schema/registry.py` -- the single source of
truth for both SQLite and Postgres. The registry was created after ~12 hours
were lost to bugs caused by 6+ files independently defining the same tables
with subtly different column names. Now a single `TableDef` dataclass defines
each table and generates DDL for both SQLite and Postgres.

**Architecture:**
```
src/schema/registry.py          <- THE source of truth (46 TableDefs)
    +-- src/schema/sqlite.py     <- Generates CREATE TABLE for SQLite
    +-- src/schema/postgres.py   <- Generates CREATE TABLE for Postgres
    +-- src/schema/validator.py  <- Compares live DB against registry
    +-- src/schema/sync_config.py <- Generates SYNC_TABLES config
    +-- src/journal/store.py     <- initialize_database() reads from registry
    +-- scripts/render_migrate.py <- Reads from registry (no manual DDL)
    +-- src/sync/render_sync.py  <- SYNC_TABLES generated from registry
```

### Trading Core (3)

| Table | Purpose |
|---|---|
| `recommendations` | LLM-generated trade recommendations with full context and outcomes |
| `shadow_trades` | Paper trades tracked from entry to exit with execution quality |
| `validation_results` | Preflight validation check results |

### Training Pipeline (8)

| Table | Purpose |
|---|---|
| `model_versions` | Tracked model versions with training stats and holdout scores |
| `training_examples` | Curated instruction/output pairs for LLM fine-tuning |
| `model_evaluations` | A/B comparisons between current and candidate models |
| `audit_reports` | Periodic audit reports on model and system health |
| `metric_snapshots` | Daily snapshots of key system metrics |
| `api_costs` | LLM API usage and cost tracking |
| `preference_pairs` | DPO preference pairs for RLHF-style training |
| `canary_evaluations` | Canary eval runs to detect model quality degradation |

### Council (6)

| Table | Purpose |
|---|---|
| `council_sessions` | Multi-agent council deliberation sessions |
| `council_votes` | Individual agent votes within council sessions |
| `council_calibrations` | Agent prediction calibration tracking |
| `council_debug_log` | Raw LLM request/response debug traces for council agents |
| `council_parameter_log` | Council-adjusted parameter changes with attribution windows |
| `council_parameter_state` | Current state of council-adjustable parameters |

### Data Collection (12)

| Table | Purpose |
|---|---|
| `edgar_filings` | SEC EDGAR filings with full text and sentiment analysis |
| `insider_transactions` | Insider buying/selling transactions from Finnhub |
| `short_interest` | Short interest data with days-to-cover and float percentage |
| `fed_communications` | Federal Reserve speeches, minutes, and press conferences |
| `analyst_estimates` | Analyst consensus estimates, price targets, and earnings surprises |
| `options_chains` | Options chain snapshots with Greeks and volume data |
| `options_metrics` | Derived options metrics: IV rank, put/call ratios, unusual activity |
| `cboe_ratios` | CBOE equity/index put-call ratios |
| `google_trends` | Google Trends search interest for tracked tickers |
| `vix_term_structure` | VIX term structure snapshots across tenors |
| `macro_snapshots` | FRED macroeconomic series snapshots |
| `earnings_calendar` | Upcoming earnings dates for universe tickers |

### Research (3)

| Table | Purpose |
|---|---|
| `research_papers` | Academic/industry papers with relevance scoring |
| `research_digests` | Weekly research digest summaries |
| `research_docs` | Uploaded research documents and reference materials |

### Signals (2)

| Table | Purpose |
|---|---|
| `setup_signals` | Technical setup signal detections with forward returns |
| `traffic_light_state` | Market regime traffic light state machine |

### Evaluation & Metrics (4)

| Table | Purpose |
|---|---|
| `scan_metrics` | Per-scan pipeline metrics and throughput counters |
| `schedule_metrics` | Daily schedule execution metrics |
| `quality_drift_metrics` | Training quality drift detection metrics per cycle |
| `build_score_history` | Daily composite build score with component breakdowns |

### Infrastructure (6)

| Table | Purpose |
|---|---|
| `activity_log` | System-wide event log for all notable actions |
| `log_entries` | Structured log entries with source and severity |
| `sync_state` | Last sync timestamp per table for incremental sync |
| `command_results` | Results of remotely-issued commands |
| `config_overrides` | Dashboard-pushed configuration overrides |
| `pending_commands` | Remote commands queued for local execution |

### User Data (1)

| Table | Purpose |
|---|---|
| `user_notes` | User-created notes with tags and pin support |

### Trading Internals (1)

| Table | Purpose |
|---|---|
| `bracket_health` | Bracket order health checks for open positions |

---

## 5. Strategy Decisions (24 confirmed)

1. Strategy #1 = Pullback-in-uptrend (LIVE)
2. Strategy #2 = Mean Reversion / Connors RSI(2) -- PAPER-TRADING NOW
3. Strategy #3 = Evolved PEAD (Phase 3)
4. RL = Dr. GRPO (at 100 trades)
5. Breakout = pullback feature, not separate strategy
6. Traffic Light RED=0.1 safety override (bootcamp floor 0.5)
7. Volatility-adaptive sizing deferred to Phase 2
8. Event calendar = 0-10 continuous scoring
9. Equal-weight until 200+ trades/strategy
10. Tax strategy (475f/TTS) tabled
11. Holding periods: pullback 7d, MR 5d, PEAD 10d
12. Council: portfolio-level only Phase 1
13. Council: hardcoded thresholds
14. Council: alert 8wk, auto-tighten 12wk, restore 4wk
15. Council: holistic + per-agent value tracking
16. Council: daily + weekly, monthly after 3 months
17. Alpha attribution: parallel ranker-only shadow portfolio (second Alpaca paper account)
18. Mechanical bracket exits optimal through 200 trades, then phased LLM management
19. Options moved to Phase 2 at $15-25K (vertical spreads only, was $50K)
20. Collective2 account: open immediately for independently verified track record
21. Training data: expand from 7 to 11 XML sections with random source subsetting
22. Scanning: 4-tier multi-cadence (15min position / 30min price / 60min sentiment / daily fundamentals)
23. Outcome-conditioned training prompts: 3-5x data yield per closed trade
24. 8 new outcome metadata columns in shadow_trades via schema registry

---

## 6. Phase Gates

| Gate | Requirements | Current | Status |
|---|---|---|---|
| Phase 1 -> 2 | 50 closed, WR>=45%, Sharpe>=0.15, PF>=1.3, DD<=12%, alpha attribution running (>=50 paired trades), stress test (2008/2020/2022), >=100 MR paper trades | 13 closed, 92% WR, 0 paired, 0 MR paper | 26% |
| Phase 2 -> 3 | 100 closed + Strategy #2 live + RTX 3090 + options paper at $15-25K | 0 | Not started |
| GRPO | 100+ closed trades | 0 | Blocked on data |
| Fund formation | Track record + $2M AUM + Collective2 24-month verified | N/A | Year 3+ |

### Model Roadmap

| Phase | GPU | Model | Status |
|---|---|---|---|
| 1 (now) | RTX 3060 12GB | Qwen3 8B (Q8_0) | ACTIVE |
| 2 | RTX 3090 24GB | Qwen 2.5 14B or Qwen3 14B | After 50-trade gate |
| 3+ | RTX 3090 + multi-LoRA | Strategy-specific 14B adapters | After 100 trades |
| Stretch | Second 3090 or RTX 5090 | Qwen3 30B-A3B MoE | If 14B ceiling hit |

GRPO training: RunPod A100 cloud ($14/mo), not local hardware.

---

## 7. Frameworks

### GPU Utilization Framework

**Target:** Phase into 40-70% utilization across all time blocks (was 4.4%).

| Time Block | Current | Target | Activities |
|---|---|---|---|
| Market hours (9:30-4:00) | 4.4% | 30-40% | Inference + alpha backtest + nightly eval warmup |
| Post-close (4:00-7:00) | ~5% | 40-60% | Stress testing + Monte Carlo + outcome-conditioned training gen |
| Overnight (7:00-5:15) | ~10% | 50-70% | Continuous eval + parameter backtesting + scenario gen |
| Weekend | Training only | 70-80% | Full retrain + exhaustive backtest + stress test suite |

### Exit Management Framework

| Phase | Trades | Strategy | Key Additions |
|---|---|---|---|
| 1 (now) | 13-50 | Pure mechanical brackets | Fix live stop to 2.0x ATR, MFE/MAE logging |
| 2 | 50-200 | Mechanical + rule-based | Time-based stop tightening (2.0x->1.5x by day 5), signal exit |
| 3 | 200-500 | Evaluate LLM pilot | Thesis invalidation detection on days 5-7 only |
| 4 | 500+ | Full active if validated | Separate exit-specialist LoRA, daily conviction updates past day 3 |

### Scanning Cadence Framework (4-tier)

| Tier | Interval | Purpose |
|---|---|---|
| Position monitoring | 15 min | Check open positions, bracket health, stop proximity |
| Price scanning | 30 min | Full universe scan for new setups |
| Sentiment refresh | 60 min | News scoring, social signals |
| Fundamentals | Daily | EDGAR, macro, analyst estimates |

### 24/7 Compute Schedule

**Target: 73% GPU utilization** (inference <=30%, training <=45%, slack >=25%)

| Time (ET) | Task | GPU Mode |
|---|---|---|
| 5:15 AM | Morning VRAM handoff (training -> Ollama) | Transition |
| 5:30 AM | Post-close capture (MFE/MAE update, regime logging) | Inference |
| 6:00 AM | Pre-market refresh + rolling feature computation | CPU + Inference |
| 7:00 AM | Self-blinded training data generation (historical) | Inference |
| 8:00 AM | Morning watchlist | Inference |
| 8:02 AM | Overnight news scoring + sentiment analysis | Inference |
| 9:00 AM | Pre-market candidate analysis | Inference |
| 9:25 AM | Guard band -- verify model warm | Idle |
| 9:30 AM-4:00 PM | Market scans (every 30 min) + between-scan scoring | Inference |
| 4:00 PM | EOD recap + daily P&L | CPU + Inference |
| 4:15 PM | Training data scoring (LLM-as-judge, ~50 examples) | Inference |
| 5:30 PM | Post-close capture | CPU |
| 6:00 PM | Training data collection from closed trades | CPU |
| 6:45 PM | Preference pair generation / RL prep | Inference |
| 6:50 PM | Evening VRAM handoff (Ollama -> training subprocess) | Transition |
| 7:00 PM | Walk-forward backtesting | Training |
| 9:30 PM | Data collection (12 collectors) | CPU (concurrent) |
| 10:00 PM | News ingestion (full universe) | CPU (concurrent) |
| 11:00 PM | Enrichment pre-cache | CPU (concurrent) |
| 11:05 PM | Auxiliary model training (regime classifier) | Training |
| 1:00 AM | Feature importance computation | Training |
| 2:30 AM | Leakage detector with model probing | Training |
| 4:30 AM | DB maintenance, health checks, backups | CPU |

### Training Data Framework

| Element | Detail |
|---|---|
| Self-blinding | Claude generates commentary WITHOUT seeing outcomes (2-stage pipeline) |
| Quality scoring | LLM-as-judge scores 6 dimensions, blind to trade outcome |
| Leakage detection | Balanced accuracy classifier verifies pipeline integrity |
| Curriculum | Easy/medium/hard difficulty -> 3-stage curriculum with decreasing LR |
| SFT training | 3-stage curriculum (PEFT + TRL 0.24) |
| GRPO (future) | Preference exports retained, Dr. GRPO planned post-SFT |
| Holdout | 15% chronological holdout with 5-day temporal gap |
| A/B eval | New model runs alongside current model |
| Auto-rollback | Performance regression triggers automatic rollback |
| Data expansion | 7->11 XML sections, random source subsetting, outcome-conditioned prompts (3-5x yield) |

---

## 8. Revenue & Business

| Month | Stream | Milestone |
|---|---|---|
| 0 (now) | Personal trading + capital injections ($1K/mo) | Start |
| 3 | Open Collective2 account (~$99/mo) | Track record clock starts |
| 6 | Phase 1 gate -> go live ($5-10K) | Verifiable live returns |
| 12 | Signal marketplace ($200-$1K/mo) + RIA outreach | First external revenue |
| 18 | Wyoming LLC + Section 475(f) | Legal entity |
| 24 | Fund formation at $1-2M AUM | Management + performance fees |
| 36 | Fund self-sustaining at $2M+ AUM (1.5%+17.5%) | Day job optional |

**Entity path:** Arcis -> Arcis Capital Management, LLC -> Arcis Labs
**SEC language:** "AI-informed", "systematic", "research-driven"

### Future Desks (gated by performance)

Each desk launches only after the previous desk is profitable.

1. **Equity Research Desk** (Phase 2) -- same model, lower thresholds, separate paper account
2. **Options Volatility Desk** (Phase 3-4) -- separate LoRA, credit spreads + iron condors
3. **Equity Momentum Desk** (Phase 5) -- separate LoRA, Russell 1000, breakout/trend
4. **Intraday Desk** (Phase 6+) -- separate model, 1-min bars, VWAP reversion
5. Event-Driven, Macro/Rates, Crypto (scoped, not scheduled)

---

## 9. Conventions & Rules

### Module Docstring Format (mandatory for src/)

```python
"""Module name -- one-line description.

Called by: caller1.py, caller2.py
Calls: callee1.py, callee2.py
Owns tables: table1, table2
Config keys: section.key1, section.key2
Tests: tests/test_module.py
"""
```

Use `none` for empty fields. Entry points: `Called by: none (entry point)`.

### Adding Features / Collectors / Endpoints / Pages

**Feature/Signal:**
1. Create `src/features/{name}.py` with standard docstring
2. Wire into `src/services/scan_service.py`
3. Add test at `tests/test_{name}.py` (minimum 5 tests)
4. Update AGENTS.md module registry

**Data Collector:**
1. Create `src/data_collection/{name}_collector.py`
2. Add table to schema registry (NOT inline CREATE TABLE)
3. Wire into `src/scheduler/watch.py` overnight schedule
4. Add test; update AGENTS.md

**API Endpoint:**
1. Local: `src/api/routes/{module}.py`, register in `src/api/app.py`
2. Cloud: `src/api/cloud_routes/{module}.py`, register in `src/api/cloud_app.py`
3. Add frontend call in `frontend/src/api.js`
4. Add test

**Dashboard Page:**
1. Create `frontend/src/pages/{PageName}.jsx`
2. Add route in `App.jsx`, nav entry in `Layout.jsx`
3. Use `var(--arcis-*)` palette; `financial-data` class for monospace
4. Directional arrows mandatory: green up-arrow / red down-arrow

### Schema Rules (MANDATORY)

- All 46 tables defined in `src/schema/registry.py` -- THE single source of truth
- NEVER write `CREATE TABLE` or `ALTER TABLE` outside `src/schema/registry.py`
- CI guardrails: `test_no_create_table_in_source`, `test_no_alter_table_in_source`
- To add a table: add `TableDef` to registry -> `validate-schema --fix` -> `render_migrate.py`
- To add a column: add `ColumnDef` to table -> `validate-schema --fix` -> `render_migrate.py`
- Before any PR touching DB: run `python -m src.main validate-schema`

### File Size Guardrails

- Max 400 lines per file -- enforced by `tests/test_repo_structure.py`
- Max 60 lines per function -- enforced by `tests/test_repo_structure.py`
- Existing violations grandfathered in `config/known_violations.json` (warn-only)
- New violations fail CI

### Testing Conventions

- Minimum 5 tests per module for new modules
- Use `tmp_path` fixtures for file/DB operations -- never write to repo paths
- Use real SQLite over mocks -- our tests are integration tests
- CI enforces minimum of 1,105 tests (guardian)
- Mock all external APIs in tests (Alpaca, Finnhub, yfinance, FRED, Ollama)
- Test file naming: `tests/test_{module_name}.py`

### Sprint Checklist (after every sprint)

**Required always:**
- [ ] SYSTEM_STATE.md -- update header, sprint table, counts
- [ ] CHANGELOG.md -- add sprint entry with date and feature list

**If applicable:**
- [ ] AGENTS.md -- only if governance/scope/architecture changed (NOT counts)
- [ ] config/settings.example.yaml -- if new config keys added
- [ ] scripts/render_migrate.py -- if new Postgres tables/columns added

**Verification commands:**
```bash
python scripts/verify_docs.py      # Compares actual counts to docs
python -m pytest tests/ -x -q      # Tests must pass
cd frontend && npm run build       # Frontend must build
```

**Anti-patterns:**
- Never duplicate counts in multiple files -- SYSTEM_STATE.md only
- Never add a config key without adding to `settings.example.yaml`
- Never add a DB table without adding to schema registry

### Commit / PR Conventions

- Branch from `main`
- PR titles: imperative mood, concise
- Squash merge preferred for feature branches
- Run `python -m pytest tests/ -x -q` before pushing

### Config Access Pattern

```python
from src.config import load_config
cfg = load_config()
value = cfg.get("section", {}).get("key", default)
```

Config in `config/settings.yaml` (committed). Secrets in `.env` (gitignored).
`load_dotenv()` at startup; modules check `os.environ.get()` first, fall back
to YAML.

---

## 10. Key Principles

1. **Training data quality is sacred** -- never sacrifice for speed
2. **Risk governor is sacred** -- never bypass or weaken without explicit approval
3. **Test count must not drop** -- CI minimum 1,105; currently 1,228+
4. **Mock all external APIs** -- no network calls from pytest
5. **Schema registry is the single source of truth** -- no DDL outside `src/schema/`
6. **Test baseline before changes** -- run pytest at session start, count must
   not decrease after changes
7. **Never commit secrets** -- `.env`, `config/settings.local.yaml`, `.mcp.json`
   are gitignored
8. **LLM role evolves** -- Phase 1 = commentary engine (doesn't gate paper
   trades); Phase 2+ = decision-maker with conviction gating
9. **One machine, all desks** -- multi-LoRA serving via llama-server
10. **Lockdown discipline** -- Mon-Fri the system trades autonomously; only
    intervene for Telegram CRITICAL, VIX >40, or system offline

### Governance Hierarchy

1. **AGENTS.md** -- purpose, scope, and constraints
2. **Charter** -- operational rules and risk limits
3. **Blueprint** -- technical architecture (`docs/architecture.md`)
4. **Code** -- implementation

### Lockdown Plan (active)

| Cadence | Action |
|---|---|
| Daily (Mon-Fri) | System trades autonomously. Don't touch it. |
| After close (optional) | `python scripts/post_close_check.py` -- 8-point confidence check |
| Saturday | Weekly retrain IF >=10 new closed trades |
| Sunday | `python scripts/weekly_review.py` -> paste to Claude -> audit |

**Only intervene for:** Telegram CRITICAL (bracket failure, kill switch),
VIX >40, system offline.

**Key scripts:**
- `post_close_check.py` -- daily confidence (scans, TL, positions, council,
  scoring, collectors, errors, sync)
- `weekly_review.py` -- 7-section review with data inventory + week-over-week
  deltas
- `diagnose_leakage.py` -- TF-IDF leakage investigation (run before any
  retrain)

---

## 11. Sprint Queue

| Priority | Sprint | Status |
|---|---|---|
| 1 | Schema Registry | DONE -- 46 tables, all DDL removed, guardrails |
| 2 | React Flow interactive diagrams | DONE -- Architecture + DB Schema pages |
| A | Dashboard polish + documentation consolidation | DONE -- PR #203 |
| 3 | Fix critical bugs (#182, #183, #184) | QUEUED |
| 4 | Alpha attribution experiment | DONE -- PR #203, attribution_trades table + dashboard |
| 5 | Mean reversion paper-trading | DONE -- PR #203, RSI(2) scanner + strategy exits |
| 6 | Multi-cadence scanning (4-tier) | DONE -- PR #203, 4 extracted modules + staleness |
| 7 | Outcome metadata + conditioned training | DONE -- PR #203, 3-5x data yield |
| 8 | Historical stress testing | DONE -- PR #203, 2008/2020/2022 scenarios |
| 9 | Repo reorganization | Backlog |
| 10 | architecture.md refresh | Backlog |

### Phase 2 Hardware (~$1,300)

**Trigger:** Phase 1 gate passed (50 closed trades) OR database corruption
recurrence.

- RTX 3090 24GB (~$700) -- 14B model, GRPO, multi-LoRA
- Ryzen 5 5600 / i5-12400 (~$120)
- 32GB DDR4 (~$60), 1TB NVMe (~$70), mATX + 750W PSU (~$120)
- UPS CyberPower CP1500PFCLCD (~$220)
- Ubuntu Server 24.04 headless, PostgreSQL 16 local primary
- Render Postgres becomes cloud read-replica
- SSH from Windows for management + Claude Code sessions
- Eliminates: OneDrive corruption, SQLite concurrency, power loss, GPU
  contention, Windows sleep interruptions, VRAM handoff complexity

### Infrastructure TODO (non-sprint)

- Move repo off OneDrive (root cause of incident #181)
- Add `*.sqlite3*` to `.gitignore` (WAL/SHM tracked in git compounds issues)
- Startup integrity check (`PRAGMA integrity_check` + Telegram alert)
- Startup row count sanity check (shadow_trades drops to 0 -> abort)
- Automated daily SQLite backup (copy to `backups/`, keep 7 days)
- Rename GitHub repo `halcyon-lab` -> `arcis`
- GitHub Pro ($4/mo) for branch protection
- Domain: arcis.app or arciscapital.com
- Wyoming LLC formation (July 2026 target)
- Logo SVG cleanup (Fiverr $50-100)
- `start.ps1` — one-command startup script (activate venv, git pull, validate-schema, watch)
- Dedicated server: `systemd` service for watch loop (replaces PowerShell startup on Ubuntu headless)

---

## 12. Reference Pointers

| Topic | Location |
|---|---|
| Full CLI reference | `docs/cli-reference.md` |
| Roadmap (6 phases) | `docs/roadmap.md` or dashboard Roadmap page |
| Research library | Dashboard Docs page |
| Schema DDL | `src/schema/registry.py` |
| Schema validation | `python -m src.main validate-schema [--fix]` |
| Postgres migration | `python scripts/render_migrate.py` |
| Config structure | `config/settings.example.yaml` |
| Sprint template | `docs/sprints/TEMPLATE.md` |
| Module registry | AGENTS.md (138 entries) |
| Bug history (schema) | `docs/schema-governance.md` |
| Deep research synthesis | `docs/research/deep-research/SYNTHESIS-framework-update-roadmap-changes.md` |
| Governance hierarchy | AGENTS.md > Charter > Blueprint > Code |
| Hook/skill config | `.claude/settings.json`, `.claude/skills/` |
| Subagent config | `.claude/agents/` |
| Known file-size violations | `config/known_violations.json` |

### Common Commands

```bash
# Startup / restart
git pull origin main
python -m src.main validate-schema --fix
python -m src.main watch                    # Standard watch loop
python -m src.main watch --email-mode digest --overnight

# Testing
python -m pytest tests/ -v
python -m pytest tests/ -x -q              # Quick pre-push check

# Operations
python -m src.main preflight
python -m src.main scan --verbose --dry-run
python -m src.main shadow-status
python -m src.main training-status
python scripts/post_close_check.py

# Schema
python -m src.main validate-schema          # Check drift
python -m src.main validate-schema --fix    # Auto-fix
python scripts/render_migrate.py            # Sync Postgres

# Frontend
cd frontend && npm run dev

# Lint
python -m ruff check src/ tests/ --fix
python -m ruff format src/ tests/
```

### Dashboard Pages (16)

Dashboard, Packets, Shadow Ledger, Live Ledger, Training, Council, Health,
Validation, CTO Report, Settings, Roadmap, Docs, Notes, Logs, Architecture,
DB Schema.

### CLI Commands (52)

- **Core (8):** init-db, demo-packet, send-test-email, send-test-telegram, ingest, scan, morning-watchlist, eod-recap
- **Shadow (4):** shadow-status, shadow-history, shadow-close, shadow-account
- **Live (4):** live-status, live-history, live-close, reconcile-live
- **Review (6):** review, mark-executed, review-scorecard, review-bootcamp, postmortems, postmortem
- **Training Data (5):** training-status, training-history, training-report, bootstrap-training, backfill-training
- **Training Quality (5):** classify-training-data, score-training-data, validate-training-data, generate-contrastive, generate-preferences
- **Training Exec (2):** train, train-pipeline
- **Evaluation (10):** cto-report, evaluate-holdout, model-evaluation-status, promote-model, feature-importance, backtest, compare-models, check-leakage, performance-report, evaluate-gate
- **Operations (8):** collect-data, fetch-earnings, halt-trading, resume-trading, preflight, council, watch, dashboard

---

## 13. Brand

| Element | Value |
|---|---|
| Name | Arcis (Adaptive Regime Classification & Intelligence Systems) |
| Palette | H (Electric Focus) -- `#050507` + `#3B82F6` |
| Typography | Inter + JetBrains Mono |
| Voice | 65% academic / 35% tech startup |
| CSS | `var(--arcis-*)` custom properties; never hardcode colors |
| Financial data | `<span class="financial-data">` for monospace rendering |
| Arrows | Mandatory: green up-arrow (positive) / red down-arrow (negative) |

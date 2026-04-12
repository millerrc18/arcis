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
**Release:** v0.17.0 (IB integration complete across 7 sprints, dashboard overhaul across 4 sprints, capital-velocity instrumentation, council advisory-only guardrail, 703-row regime-diverse backfill, 12 pre-v0.17 hotfixes)
**Repository:** github.com/millerrc18/halcyon-lab
**Dashboard:** halcyonlab.app (Render static + Python API)

**Purpose:** Autonomous AI trading system that scans, analyzes, and executes
equity trades. Combines systematic technical scoring with LLM-generated
institutional-quality commentary, multi-source data enrichment, broker-abstracted
order execution (Alpaca + Interactive Brokers), an 8-check risk governor with
kill switch, and a self-improving training pipeline with quality gates.

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
- Trading: Alpaca paper + live API (bracket orders, GTC); IB Gateway via
  ib_async (broker abstraction, config-driven: `live_trading.broker`)
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
| Closed trades | 18 verified (77 quarantined from April 10 cascade) |
| Open positions | ~2 (verify with shadow-status) |
| Model | halcyon-v1.0.0 (Qwen3 8B, Q8_0 GGUF); v2.0.0 retrain in progress |
| Training data | 1,722 examples (1,019 + 703 regime-diverse backfill) |
| Tests | 1,734 tests across 140 test files |
| Python files | 219 |
| Dashboard pages | 24 |
| Research docs | 91 |
| Sprint docs | 43 |
| Schema tables | 53 (registry), 44+ synced to Postgres |
| GitHub issues | 0 open |
| Monthly cost | ~$64 (Render $14 + Ollama free + Claude API ~$50 + domain $7) |
| Hardware | RTX 3060 12GB, Windows 11, Z690, 24/7 operation |

### Deployed Components

| Component | Status |
|---|---|
| Watch loop (scan + monitor) | LIVE -- 13 scans/day, overnight mode |
| Traffic Light | LIVE -- bootcamp floor 0.5 |
| Risk governor | LIVE -- 8 checks |
| Council v2 (5 agents) | LIVE -- failure sends Telegram alert |
| Build Score KPI | LIVE -- 6-component geometric mean |
| Between-scan quality scoring | LIVE -- GuardedScorer Ollama |
| Command queue + config overrides | LIVE -- pull-based |
| 12 overnight collectors | RUNNING |
| Broker abstraction (IB + Alpaca) | READY -- config-driven, IB activation gated on validation |
| Telegram | LIVE -- 56 functions, gated behind trade_id |
| Intra-day reconciliation | LIVE -- every 15 min during market hours |
| Dashboard (Arcis) | LIVE -- 24 pages (adds Broker Comparison, Velocity), dark/light toggle, mobile-responsive sidebar |
| Simulation engine | LIVE -- 13 regimes, Monte Carlo, traffic light validation, regime selector |
| Schema registry | LIVE -- 53 tables, single source of truth |
| Render sync | LIVE -- 44/51 tables synced to Postgres |
| Halcyon-audit plugin | LIVE -- 8 domain agents, /audit command |
| Automated guardrails | LIVE -- test_repo_structure.py |
| CI on PRs | LIVE -- tests + guardrails + frontend build |
| PEAD enrichment (5 signals) | DEPLOYED |
| Implementation Shortfall | DEPLOYED |

### Open GitHub Issues

0 open as of 2026-04-12:
- All 14 issues (#302-#304, #325-#335) closed in production sweep sprint (v0.15.1-v0.15.3)
- 8 dashboard data integrity fixes shipped in v0.16.0
- 12 hotfixes (v0.16.1-v0.16.12): execution safety, quarantine, LLM quality, type coercion, Postgres drift, council weights, training pipeline, Ollama resilience, trading safety + security
- v0.17.0 bundles IB integration (7 sprints) + dashboard overhaul (4 sprints) + 703 regime-diverse backfill + capital velocity instrumentation

### Known Blockers

- Database on OneDrive path risks WAL corruption (incident #181); move to
  local path or exclude `*.sqlite3*` from sync
- UPS not yet purchased (CyberPower CP1500PFCLCD, ~$220)

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
| Schema registry | #189 | 50 tables in registry, all DDL removed, CI guardrails |
| Mega Sprint | #178 | Intra-day recon, exit_failed recovery, React Flow, sidebar sections |
| pnl_dollars fix | #200 | Cast pnl_dollars to float before comparison |
| Reliability | #201 | Exit cancel race, VRAM handoff hardening, sync reconnection |
| Local API parity | #202 | 22 missing routes added to local FastAPI |
| Sprints A-7 | #203 | Dashboard, attribution, MR, multi-cadence, training, stress testing |
| Sprint gaps + RCCA | #204 | 6 sprint gaps closed, 8 RCCA bugs fixed, audit plugin |
| Stress test fix | #205 | yfinance warnings, BRK.B failure |
| Bug bash v0.11.0 | #206 | Conviction parsing, Finnhub security, tech debt |
| IB broker abstraction (IB-1) | -- | v0.14.0, Alpaca + IB dual-broker, config-driven |
| IB structural fixes (IB-2) | -- | Exception taxonomy, connect/disconnect pattern, permId tracking |
| IB shadow dashboard (IB-3) | -- | Cloud API routes + dashboard page for IB shadow mode comparison analytics |
| IB dual-execution routing (IB-4) | -- | Score-based paper broker selection, routing threshold |
| IB production hardening (IB-5) | -- | Reconnect backoff, bracket verification, outsideRth, OcaType 3 |
| IB paper trading activation (IB-6) | -- | Validation script, daily_ib_health table, Gateway status card, digest section |
| IB integration validation (IB-7) | -- | 16 integration tests, ib-smoke-test.md 6-phase checklist |
| Dashboard DB-1 (data integrity, 9 tasks) | -- | Quarantine sync to Postgres, model version Ollama fallback, flywheel-velocity cycle-anchor, council.auto_apply_parameters guardrail |
| Dashboard DB-2a (bug fixes, 10 tasks) | -- | Packets prompt leakage strip, current_price on live ledger, OpenPositionCard, ledger merge + broker filter, Strategy win/loss overlay, StressTest latest-only, Monitoring crash |
| Dashboard DB-2b (features, 7 tasks) | -- | Broker Comparison page rebrand + Trading-nav move, CTO by_broker breakdown, Logs export-errors + stale-commands, IB research docs in Docs index, outcome_counts wired, per-collector log isolation |
| Dashboard DB-3 (polish, 8 tasks) | -- | Architecture IB Gateway + broker_router nodes, Simulation regime selector, StressTest +4 scenarios, IB Settings section (unblocked), Capital Velocity dashboard placeholder |
| Dashboard DB-FINAL (cleanup, 8 tasks) | -- | time_to_mfe instrumentation + 3 tests, attribution logger warning-level + defensive _parse_price + integration tests, mobile sidebar + status-bar hide, ReactFlow non-draggable + MiniMap removed, 15 data-testid attributes, docs refresh |
| Production sweep (3 phases) | -- | v0.15.1-3, 14 bugs fixed (bracket guard, recon, conviction, type safety) |
| Consolidated sprint (5 sprints) | -- | Attribution wiring, simulation promotion, MR integration, Sprint 5 refactor |
| Sprint 5 refactor | -- | watch.py 3403→1968 (42%), telegram.py 1563→786 (50%), 3 new modules |
| Dashboard hotfix (8 tasks) | -- | v0.16.0, targets_hit filter, fund metrics, market_regime, NEE upsert, version |
| Telegram notification fix | -- | scan_service opens + reconcile closes (69% of trades were silent) |
| Trade rectification | -- | v0.16.1-v0.16.2, execution safety hardening (12 fixes), typed exceptions, order verification |
| Data quarantine | -- | 77 compromised records flagged, 18 verified trades preserved, COALESCE filter |
| LLM quality + type coercion | -- | v0.16.3-v0.16.4, repeat_penalty 1.15, pre-parser validation, _coerce_to_schema() |
| Postgres drift + council weights | -- | v0.16.5-v0.16.6, auto-fix schema drift at startup, council session_id join fix |
| Training pipeline + Ollama | -- | v0.16.7-v0.16.8, em-dash SyntaxError, GGUF fallback, circuit breaker + auto-restart |
| Root cause gaps + P2 batch | -- | v0.16.9-v0.16.10, research feeds, CBOE scraper, buying power race |
| Test regressions + security | -- | v0.16.11-v0.16.12, buying power mock, training gate, SQL injection fixes, error sanitization |
| Manual backfill pipeline | -- | Export/import scripts, regime sampler, FRED macro enrichment |
| Roadmap + MASTER.md updates | -- | Post-quarantine metrics, FINSABER findings, exit framework update |
| Audit rectification | #210 | CORS, DDL, test mocking, error handling |
| Hardening | #211 | 5 remaining issues (#188, #187, #147, #132, #106) |
| Postgres sync + CI | #212 | Pkey collision fix, 9 CI guardrails, dependabot |
| Stats + column fix | #236 | Stats endpoint cascading failure, invalid column |
| Watch loop scheduling | #237 | elif chain, safe_run, backoff, failures |
| Collector reliability | #238 | Config errors, partial failures, data bugs |
| Render sync safety | #240 | Health monitoring, atomic latest_only |
| Startup command | #241 | Single-command system validation + launch |
| Production sync | #246 | 4 production sync/logging bugs |
| IB integration | v0.14.0 | Broker abstraction + IB adapter (ib_async) |
| Log audit + HSHS fix | v0.14.1 | 14 production issues, IB validation-first strategy |
| Hotfix merge sprint | v0.14.2 | 6 critical bugs (#307-312), codex telegram fix (#299-301), 9 Dependabot PRs, 5 branch cleanup |
| IB shadow dashboard | -- | Cloud API routes + dashboard page for IB shadow mode comparison analytics |

---

## 3. Architecture Overview

![System architecture](docs/diagrams/svg/01-system-architecture.svg)

![Multi-cadence scanning](docs/diagrams/svg/04-multi-cadence-scanning.svg)

> See also: [Broker abstraction](docs/diagrams/svg/02-broker-abstraction.svg), [Data enrichment](docs/diagrams/svg/06-data-enrichment-stack.svg), [Watch loop 24hr](docs/diagrams/svg/09-watch-loop-24hr.svg), [Trade lifecycle](docs/diagrams/svg/11-trade-lifecycle.svg)

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
| 4 Orchestration | watch.py, main.py, scheduler/universe_scanner.py, scheduler/overnight.py |
| 3 Services | scan_service.py, council/engine.py, *_service.py, attribution/logger.py |
| 2 Domain | executor.py, governor.py, traffic_light.py, features/*, ranker.py |
| 1 Infrastructure | alpaca_adapter.py, trading/broker_interface.py, trading/ib_broker.py, trading/alpaca_broker.py, trading/broker_factory.py, trading/ib_status.py, telegram.py, render_sync.py, llm/client.py |

**IB operational tooling:** `scripts/validate_ib_gateway.py` (pre-activation paper-account smoke test, refuses port 4001), `scripts/validate_ib_integration.py` (post-scan data completeness across shadow_trades, ib_shadow_log, daily_ib_health), `docs/operations/ib-smoke-test.md` (6-phase manual validation checklist).

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
short selling, high-frequency / intraday trading. Live trading infrastructure
is ready (broker abstraction supports Alpaca + IB), but IB activation is gated
on validation milestones (see Strategy Decision #25).

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
| Alpaca Markets API | Paper + live trading execution (default broker) |
| IB Gateway (ib_async) | Live trading via Interactive Brokers (config-driven alternative) |
| Ollama | Local LLM inference (halcyon-v1) |
| Anthropic Claude (Haiku 4.5) | Training data generation, quality scoring |
| Finnhub API | Insider, news, short interest, analyst estimates |
| FRED API | 34+ macroeconomic series |
| SEC EDGAR | Fundamental data (free, 10 req/sec) |
| yfinance | OHLCV + options chains |
| Telegram Bot API | Real-time push notifications (36 functions) |
| Render | Cloud hosting: static frontend + FastAPI + Postgres |

### Configuration

**Two files, clear separation:**
- `config/settings.yaml` -- ALL non-secret config (committed). Thresholds,
  intervals, feature flags, model names.
- `.env` -- ALL secrets (gitignored). API keys, tokens, passwords.

**Key YAML sections:** `bootcamp.*`, `shadow_trading.*`, `live_trading.*`,
`risk.*`, `llm.*`, `scheduler.*`, `automation.*`, `training.*`,
`data_enrichment.*`, `council.*`

**Secrets in .env:** `ALPACA_API_KEY`, `ALPACA_API_SECRET`,
`ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY`, `ANTHROPIC_API_KEY`,
`FINNHUB_API_KEY`, `FRED_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`EMAIL_PASSWORD`, `DATABASE_URL`

### Claude Code Automations

**MCP Servers (4):** alpaca (trading API), context7 (live docs), github
(issues/PRs), sqlite (direct DB queries)

**Hooks (7):** auto-lint Python (ruff on edit), auto-lint JSX (eslint on edit),
schema DDL warning, block .env edits, block lock file edits,
post-merge validation on `git merge`, post-merge validation on `git pull`

**Skills (8):**

| Skill | Invoke | Purpose |
|---|---|---|
| gen-test | `/gen-test src/module.py` | Generate pytest files matching project conventions |
| post-close-check | `/post-close-check` | Alpaca vs local ledger reconciliation |
| config-check | `/config-check [--fix]` | Detect config drift between example and local |
| market-monitor | `/market-monitor 5m` | Recurring reconciliation on interval |
| arcis-status | `/arcis-status` | Compact system status snapshot (phase, positions, equity, training, audit) |
| retrain-check | `/retrain-check` | 8-point preflight gate before GPU training |
| visual-check | `/visual-check` | Screenshot all 18 dashboard pages via Playwright |
| audit | `/audit [domains] [--quick] [--schedule]` | Comprehensive 8-domain repo audit with GH issue filing |

**Agents (27):**

| Agent | Purpose | When to Use |
|---|---|---|
| security-reviewer | Credential exposure, SQL injection, risk governor bypass | Before merging PRs touching risk/api/.env code |
| test-runner | Full pytest suite, failure grouping, CI guardian check (1339 min) | After code changes, before commits |
| migration-checker | Schema change idempotency, cross-script sync, backwards compat | When columns or tables are added/modified |
| drift-detector | Schema drift, config drift, doc staleness, data staleness, orphaned positions | Start of every coding session |
| data-integrity-checker | FK integrity, orphaned records, data quality across 50 tables | After recovery, before releases |
| api-documenter | Route inventory, frontend-backend consistency, auth gaps | After adding/changing API endpoints |
| trading-safety-auditor | Silent failures, risk governor bypass, broker/journal truth | Part of `/audit` -- trading domain |
| code-quality-auditor | Oversized functions/files, god objects, dead code, duplication | Part of `/audit` -- quality domain |
| schema-integrity-auditor | Schema drift, DDL violations, FK integrity, orphans | Part of `/audit` -- schema domain |
| test-coverage-auditor | Test count, coverage gaps, slow tests, mock quality | Part of `/audit` -- test domain |
| compliance-auditor | CLAUDE.md rules, MASTER.md architecture, naming conventions | Part of `/audit` -- compliance domain |
| comment-doc-auditor | MASTER.md drift, stale comments, README accuracy | Part of `/audit` -- docs domain |
| security-auditor | Credentials, SQL injection, API auth, CORS, dependencies | Part of `/audit` -- security domain |
| architecture-auditor | Layer violations, circular imports, module coupling | Part of `/audit` -- architecture domain |
| audit-synthesizer | Dedup, root cause clustering, verification, quality gate | Part of `/audit` -- synthesis phase |
| council-arbiter | Final decision authority in multi-agent council deliberation | Council v2 sessions |
| council-contrarian | Devil's advocate position in council deliberation | Council v2 sessions |
| council-practitioner | Practical trading experience perspective | Council v2 sessions |
| council-skeptic | Risk-focused skeptical analysis in council | Council v2 sessions |
| council-synthesizer | Synthesize council agent votes into final recommendation | Council v2 sessions |
| research-planner | Plan multi-step research strategy | Deep research sessions |
| research-searcher | Execute web/academic searches for research | Deep research sessions |
| research-contrarian | Challenge research findings and assumptions | Deep research sessions |
| research-lateral | Cross-domain lateral thinking for research | Deep research sessions |
| research-refiner | Refine and improve research outputs | Deep research sessions |
| research-synthesizer | Synthesize research findings into actionable conclusions | Deep research sessions |
| research-tracer | Trace citations and verify research sources | Deep research sessions |

**Plugins (12 relevant):** commit-commands, code-simplifier, ralph-loop,
telegram, claude-md-management, claude-code-setup, skill-creator,
frontend-design, feature-dev, pr-review-toolkit, security-guidance,
**halcyon-audit** (8-domain repo audit with GH issue filing, see
`docs/guides/audit-plugin.md`)

---

## 4. Schema Summary

All 53 tables are defined in `src/schema/registry.py` -- the single source of
truth for both SQLite and Postgres. The registry was created after ~12 hours
were lost to bugs caused by 6+ files independently defining the same tables
with subtly different column names. Now a single `TableDef` dataclass defines
each table and generates DDL for both SQLite and Postgres.

**Architecture:**
```
src/schema/registry.py          <- THE source of truth (53 TableDefs)
    +-- src/schema/sqlite.py     <- Generates CREATE TABLE for SQLite
    +-- src/schema/postgres.py   <- Generates CREATE TABLE for Postgres
    +-- src/schema/validator.py  <- Compares live DB against registry
    +-- src/schema/sync_config.py <- Generates SYNC_TABLES config
    +-- src/journal/store.py     <- initialize_database() reads from registry
    +-- scripts/render_migrate.py <- Reads from registry (no manual DDL)
    +-- src/sync/render_sync.py  <- SYNC_TABLES generated from registry
```

### Trading Core (5)

| Table | Purpose |
|---|---|
| `recommendations` | LLM-generated trade recommendations with full context and outcomes |
| `shadow_trades` | Paper + live trades tracked entry→exit with execution quality. IB columns: `broker` (alpaca/ib), `ib_child_order_ids`, `ib_perm_id`, `broker_order_id`. Velocity columns: `time_to_mfe_days`, `mfe_timestamp` |
| `validation_results` | Preflight validation check results |
| `attribution_trades` | Paired LLM vs ranker-only trade attribution for alpha measurement — syncs to Postgres so the cloud dashboard can see pairs |
| `daily_ib_health` | IB Gateway 30-day health rollup: uptime %, trade count, error count, reconnect count (30-day gate: >95% market-hours uptime) |

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

### Evaluation & Metrics (6)

| Table | Purpose |
|---|---|
| `scan_metrics` | Per-scan pipeline metrics and throughput counters |
| `schedule_metrics` | Daily schedule execution metrics |
| `quality_drift_metrics` | Training quality drift detection metrics per cycle |
| `build_score_history` | Daily composite build score with component breakdowns |
| `stress_test_results` | Historical stress test results for crisis period backtesting |
| `simulation_results` | Full-regime simulation engine results — 13 scenarios with MC and TL validation |

### Infrastructure (7)

| Table | Purpose |
|---|---|
| `activity_log` | System-wide event log for all notable actions |
| `log_entries` | Structured log entries with source and severity |
| `sync_state` | Last sync timestamp per table for incremental sync |
| `command_results` | Results of remotely-issued commands |
| `config_overrides` | Dashboard-pushed configuration overrides |
| `pending_commands` | Remote commands queued for local execution |
| `data_freshness` | Per-ticker per-source staleness tracking for multi-cadence scanning |

### User Data (1)

| Table | Purpose |
|---|---|
| `user_notes` | User-created notes with tags and pin support |

### Trading Internals (1)

| Table | Purpose |
|---|---|
| `bracket_health` | Bracket order health checks for open positions |

---

## 5. Strategy Decisions (32 confirmed)

1. Strategy #1 = Pullback-in-uptrend (LIVE)
2. Strategy #2 = Mean Reversion / Connors RSI(2) -- PAPER-TRADING NOW. NOTE: Deep research (Scaling Levers) finds MR is the WORST diversifier for pullback (rho=0.35-0.50, shared "buy the dip" logic). Breakout/momentum (rho=0.10-0.25) should be evaluated as primary second LIVE strategy. MR remains valuable for Phase 1 data volume.
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
18. Mechanical bracket exits permanently — FINSABER (KDD 2026) confirms LLM timing fails even at GPT-4 scale. LLM provides post-trade commentary only, never exit execution
19. Options moved to Phase 2 at $25K. ORDER: covered calls at target strike first (133% EV improvement per trade, minimal complexity), THEN vertical spreads. Cash-secured puts require $15-25K collateral per S&P 100 name.
20. Collective2 account: open immediately for independently verified track record
21. Training data: expand from 7 to 11 XML sections with random source subsetting
22. Scanning: 4-tier multi-cadence (15min position / 30min price / 60min sentiment / daily fundamentals)
23. Outcome-conditioned training prompts: 3-5x data yield per closed trade
24. 8 new outcome metadata columns in shadow_trades via schema registry
25. IB activation gated on validation: broker abstraction ready (v0.14.0), but live IB trading delayed until 60+ trades with rolling Sharpe >1.0, 30-day Gateway stability test, GIPS verifier consultation, and market data classification confirmed. Deep research finding: sub-scale accounts ($5-10K) create GIPS composite construction traps. Validation-first, not infrastructure-first.
26. Scaling levers research (deep research April 2026): salary injection dominates below $80K (4.5x terminal wealth at $1K/mo). Risk per trade decreases with account size: 2% at $5-100K, 1.5% at $100-500K, 1.25% at $500K-1M, 1.0% at $1M+. Leverage sequence: none below $25K, 1.25-1.5x at $25-100K, portfolio margin at $110K+ on IB. Holding period optimization (10->5-7 days) is highest-impact operational lever for capital velocity. MES futures for Section 1256 tax at $100K+. Ruin probability <0.001% at current parameters.
27. IB connect/disconnect per-action pattern (Sprint IB-2). Open an IB Gateway socket, perform one order or reconciliation, close it. Long-lived sockets cause `TooManyOrders` on overnight reconnect and silent state drift on Gateway restart. Matching pattern documented in `docs/research/ib-async-event-patterns.md`.
28. `outsideRth=True` mandatory on all live orders (Sprint IB-5). Without it, limit-price brackets sitting at stops can be cancelled by IB's RTH-only default when a Gateway reconnect lands outside 9:30–4:00. Every order submitted via `IBBroker.submit_order` sets this unconditionally.
29. OcaType 3 (Reduce-Size) for IB bracket groups (Sprint IB-5). OcaType 1 cancels the surviving child if any sibling fills partially; OcaType 2 does nothing; OcaType 3 reduces the sibling's size in lock-step. This matches Alpaca's bracket semantics and avoids orphaned take-profit or stop orders after a partial fill.
30. permId tracking for cross-session IB order lookups (Sprint IB-2). `orderId` resets on Gateway restart; `permId` survives. Every IB trade row stores `ib_perm_id` alongside the transient `orderId` so reconciliation after a 2AM Gateway restart can still find its own orders.
31. 20% performance buffer on IB paper before live activation (Sprint IB-6). Gate `live_trading.broker: ib` in config on: >95% Gateway uptime over 30 market days, and 60+ paper trades with IB-through Sharpe ≥ 0.2 below the Alpaca baseline. Accepts a small expected edge haircut to stay clear of the validation-first rule (SD#25).
32. Capital velocity — select faster, don't exit faster (docs/research/capital-velocity-optimization.md). Shortening the average hold reduces capital lockup (`sqrt(N)` Sharpe scaling), but tightening stops or timeouts systematically cuts winners short. The correct lever is entry selection: when multiple candidates compete for limited slots, prefer the setup most likely to resolve quickly. Exit mechanics stay mechanical (SD#18). `time_to_mfe_days` + `mfe_timestamp` instrumented on `shadow_trades`; full velocity analysis + `velocity_score` gated on 50 closed trades.

---

## 6. Phase Gates

![Phase gates](docs/diagrams/svg/13-phase-gates.svg)

![Hardware scaling](docs/diagrams/svg/10-hardware-scaling.svg)

| Gate | Requirements | Current | Status |
|---|---|---|---|
| Phase 1 -> 2 | 50 closed, WR>=45%, Sharpe>=0.15, PF>=1.3, DD<=12%, alpha attribution running (>=50 paired trades), stress test (2008/2020/2022), >=100 MR paper trades | 18 closed, attribution + MR accumulating | 36% |
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

![Risk governor](docs/diagrams/svg/05-risk-governor.svg)

![AI council](docs/diagrams/svg/08-ai-council.svg)

> See also: [Training pipeline](docs/diagrams/svg/12-training-pipeline.svg)

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
| 1 (now) | 18-50 | Pure mechanical brackets | Fixed stop at 2.0x ATR, fixed target. Log MFE/MAE. No discretion. FINSABER: LLM timing fails even at GPT-4 scale. |
| 2 | 50-200 | Mechanical + rule-based | Time-based stop tightening (2.0x->1.5x by day 5). Signal exit: close > 5-day SMA. Still fully mechanical — no LLM input. |
| 3 | 200-500 | Mechanical thesis rules | Pre-specified thesis invalidation conditions at entry (mechanical, not LLM-driven). A/B test ATR-trailing vs fixed brackets. LLM post-trade commentary only. |
| 4 | 500+ | Validated mechanical exits | Deploy whichever mechanical exit rules won in walk-forward analysis. LLM commentary on exit quality for training data. No LLM exit execution — permanently excluded per FINSABER. |

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

![Flywheel moat](docs/diagrams/svg/03-flywheel-moat.svg)

![Revenue path](docs/diagrams/svg/07-revenue-path.svg)

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

- All 51 tables defined in `src/schema/registry.py` -- THE single source of truth
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
- CI enforces minimum of 1,339 tests (guardian)
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
3. **Test count must not drop** -- CI minimum 1,339; currently 1,630
4. **Mock all external APIs** -- no network calls from pytest
5. **Schema registry is the single source of truth** -- no DDL outside `src/schema/`
6. **Test baseline before changes** -- run pytest at session start, count must
   not decrease after changes
7. **Never commit secrets** -- `.env`, `config/settings.local.yaml`, `.mcp.json`
   are gitignored
8. **LLM role is bounded** -- Commentary engine only. Never controls exits,
   sizing, or risk governor. Conviction soft multiplier only after 300+
   calibrated trades (FINSABER: even GPT-4 fails at timing decisions)
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
| Sunday 9:00 PM | Stress test (3 crisis scenarios) + Simulation engine (13 regimes + MC) |
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
| 1 | Schema Registry | DONE -- 51 tables, all DDL removed, guardrails |
| 2 | React Flow interactive diagrams | DONE -- Architecture + DB Schema pages |
| A | Dashboard polish + documentation consolidation | DONE -- PR #203 |
| 3 | Alpha attribution experiment | DONE -- PR #203, pipeline wired in Sprint 2, accumulating pairs |
| 4 | Mean reversion paper-trading | DONE -- PR #203 + Sprint 4 (end-to-end: scan → LLM → execute → exit) |
| 5 | Multi-cadence scanning (4-tier) | DONE -- PR #203, 4 extracted modules + staleness |
| 6 | Outcome metadata + conditioned training | DONE -- PR #203, 3-5x data yield |
| 7 | Historical stress testing | DONE -- PR #203, 2008/2020/2022 scenarios |
| 8 | Bug bash + conviction parsing (#183) | DONE -- v0.11.0, all issues closed |
| 9 | IB integration (broker abstraction) | DONE -- v0.14.0, IB activation gated (SD#25) |
| 10 | Codebase documentation (inline comments) | DONE -- WHY-focused comments across 200+ files |
| 11 | Gap analysis rectification | DONE -- 23 issues in 3 tiers |
| 12 | Log audit | DONE -- v0.14.1, 14 production issues fixed |
| 13 | Production sweep (14 bugs, 3 phases) | DONE -- v0.15.1-3, all 14 GH issues closed |
| 14 | Attribution pipeline wiring | DONE -- log_attribution_before/after_llm in scan_service |
| 15 | Simulation engine promotion | DONE -- src/simulation/engine.py (546 lines) |
| 16 | MR integration (end-to-end) | DONE -- mr_scan_service.py, watch.py line 1273 |
| 17 | Codebase refactor (Sprint 5) | DONE -- watch.py 42% reduction, telegram.py 50% reduction |
| 18 | Dashboard data integrity (8 tasks) | DONE -- v0.16.0, 5 root causes fixed |
| 18a | Dashboard data integrity (DB-1, 9 tasks) | IN PROGRESS on fix/dashboard-data-integrity -- quarantine sync to Postgres, model version fallback + backfill, dynamic version header, DB Schema live counts, Settings display fixes, Flywheel Velocity cycle-anchored, council advisory-only flag |
| 19 | Telegram notification gaps | DONE -- scan_service opens + reconcile closes |
| -- | Strategy dashboard enhancement (7 sections) | QUEUED -- spec at docs/decisions/strategy-dashboard-spec.md |
| -- | Risk scaling tiers implementation | QUEUED -- spec at docs/decisions/risk-scaling-tiers-spec.md |
| 20 | Manual backfill pipeline | DONE -- export/import scripts, regime sampler, FRED macro enrichment |
| -- | Saturday model retrain (halcyon-v2.0.0) | QUEUED -- champion-challenger, first flywheel cycle |
| -- | Bracket calibration analysis | QUEUED -- MFE analysis on 69% stale exits |
| -- | iOS app (Capacitor) | Backlog -- native wrapper for dashboard |
| -- | Repo reorganization | Backlog |

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
python -m src.main startup                    # Validates + launches (recommended)
python -m src.main startup --check-only       # Validate only, don't launch
python -m src.main watch --email-mode digest --overnight  # Direct watch (skips validation)

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

### Dashboard Pages (22)

Dashboard, Packets, Shadow Ledger, Live Ledger, Training, Council, Health,
Validation, CTO Report, Settings, Roadmap, Docs, Notes, Logs, Architecture,
DB Schema, Attribution, Stress Test, Simulation, Model Performance, Monitoring,
Strategy.

### CLI Commands (58)

- **Core (8):** init-db, demo-packet, send-test-email, send-test-telegram, ingest, scan, morning-watchlist, eod-recap
- **Shadow (4):** shadow-status, shadow-history, shadow-close, shadow-account
- **Live (4):** live-status, live-history, live-close, reconcile-live
- **Review (6):** review, mark-executed, review-scorecard, review-bootcamp, postmortems, postmortem
- **Training Data (5):** training-status, training-history, training-report, bootstrap-training, backfill-training
- **Training Quality (5):** classify-training-data, score-training-data, validate-training-data, generate-contrastive, generate-preferences
- **Training Exec (2):** train, train-pipeline
- **Evaluation (10):** cto-report, evaluate-holdout, model-evaluation-status, promote-model, feature-importance, backtest, compare-models, check-leakage, performance-report, evaluate-gate
- **Operations (14):** startup, collect-data, fetch-earnings, halt-trading, resume-trading, cancel-all-pending, preflight, config-fix, config-diff, council, watch, dashboard, validate-system, validate-schema

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

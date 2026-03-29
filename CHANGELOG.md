# Changelog

## 2026-03-29 — Sprint 1: Stabilize

### Council v2 Tests
- Rewrote test suite for v2 protocol (53 tests covering agents, protocol, engine, value_tracker)
- Deleted v1 test files (`test_council_agents.py`) and v1 backups (`*_v1_backup.py`)

### Render Sync
- Added 5 new tables to sync: `traffic_light_state`, `council_calibrations`, `council_debug_log`, `council_parameter_log`, `council_parameter_state`
- Added v2 columns to `council_sessions` and `council_votes` in render_migrate.py

### Audit Quick-Fixes
- #30: `system.py` bare `except:` → `except Exception as e: logger.warning()`
- #31: `websocket.py` `broadcast_sync()` bare except → logged warning
- #32: `cloud_app.py` `activity_feed` type annotation fixed (`str = None` → `str | None = None`)
- #33: Deleted v1 backup files (agents, engine, protocol)
- #37: Deleted dead code `_fetch_recent_filings()` in edgar_collector.py

### Strategy-Specific Timeouts
- Pullback: 7 days (was 15), mean_reversion: 5, pead: 10, default: 10
- Per-strategy timeout lookup in executor.py
- `strategy_type` column added to shadow_trades

### Scripts & Tooling
- `scripts/verify_counts.py` — validates AGENTS.md counts against code
- `scripts/schema_report.py` — generates `docs/schema.md` from SQLite

### Counts
- 144 Python files, 72 test files, 1088 tests, 73 research docs
- All tests pass, frontend builds clean

---

## 2026-03-28 — Reliability Sprint + Research-Informed Features

### Critical Safety Fixes
- Risk governor REJECTS trades on exception (was: approve anyway)
- Drawdown returns 15% conservative estimate on error (was: 0%)
- `train-pipeline` CLI runs full 5-step pipeline (was: empty stub)
- LLM validator REJECTS trades on exception (was: continue)
- Bracket order checks child/leg statuses (was: parent only)

### Wiring & Integration
- `data_integrity.py` → scan pipeline (feature validation pre-ranking)
- `canary.py` → trainer (post-retrain evaluation gate)
- `metrics.py` → CTO report (shared calculations)
- All 12 Telegram notifications wired into watch.py
- 44+ bare `except: pass` → logged at WARNING+
- `overnight.py` consolidated (deleted), `broker.py` deleted

### New Features
- **Traffic Light regime:** VIX(20/30) + 200-DMA(3%) + credit spread(0.5σ/1.5σ) → sizing multiplier. 5-day persistence filter.
- **PEAD enrichment:** 5 earnings signals in pullback prompt (conditional on proximity ≤30 days)
- **Implementation Shortfall:** Signal price capture, IS computation on fill, rolling 20-trade alert
- **HSHS live:** 5-dimension health score from database, wired into CTO report + council + API
- **System validator:** 50+ checks, Validation dashboard page
- Independent live trade monitoring (source_filter parameter)

### Research & Architecture
- 6 new research documents (35 total), all strategy decisions confirmed
- Master blueprint v2, Halcyon Framework v2 updated
- Council redesign architecture finalized (vote-first, value tracking)
- 24 deep research prompts generated

---

## 2026-03-27 — Test Gap Closure (Priority 1 — Critical Money Path)

### New Test Files (6)
- **test_statistics.py** (56 tests) — All 11 statistical functions: Sharpe, PSR, bootstrap CI, profit factor, max drawdown, Sortino, Calmar, win rate test, expectancy test, MinTRL
- **test_gate_evaluator.py** (32 tests) — Gate decision logic (PROCEED/EXTEND/REVISION/ROOT CAUSE), metric thresholds, statistical outputs, format_gate_report, boundary conditions
- **test_change_detector.py** (12 tests) — CUSUM symmetric filter, threshold sensitivity, drift detection, performance drift with real SQLite
- **test_llm_validator.py** (18 tests) — All 6 validation checks: ticker universe, entry price deviation, stop below entry, stop distance bounds, position size cap, conviction range
- **test_filing_nlp.py** (17 tests) — Loughran-McDonald sentiment scoring, cautionary phrase detection, filing delta computation, tech-fundamental divergence
- **test_broker.py** (11 tests) — Broker abstraction, AlpacaAdapter methods, factory function, abstract interface

### Full Test Gap Closure (Priority 2-3)
- **test_backtester.py** (7 tests) — Walk-forward backtest with mocked market data, compare_models winner selection
- **test_services.py** (39 tests) — All 7 service modules: scan, shadow, system, training, review, recap, watchlist
- **test_docs_collector.py** (12 tests) — File scanning, title extraction, category assignment, table population
- **test_data_integrity.py** (21 tests) — Feature validation, trade entry validation, universe validation
- **test_activity_logger.py** (8 tests) — Activity log insertion, metadata, missing table handling
- **test_packet_builders.py** (16 tests) — Template packet builder, watchlist builder, EOD recap builder
- **test_llm_writers.py** (10 tests) — Postmortem writer, watchlist narrative generator
- **test_local_api_routes.py** (24 tests) — Packets, training, scan, review route endpoints
- **test_websocket.py** (7 tests) — ConnectionManager connect/disconnect/broadcast

### Coverage Impact
- Tests: 1,035 (up from 657 baseline, +378 new tests)
- All critical money-path, service layer, utility, and API route modules now tested
- Test files: 69 (up from 52)

---

## 2026-03-27 — Dashboard Hardening + Email Digests

### Error Visibility (Part A)
- Every `except Exception` block in cloud_app.py now has `logger.error()` with endpoint name and exc_info
- Every error response now includes an `"error"` key with the exception message
- New `/api/diagnostics` endpoint tests all 23 dashboard tables and reports pass/fail per table

### Test Coverage (Part B)
- Added 29 new cloud API tests covering all previously untested endpoints
- Coverage: activity feed, live trades/summary, council session detail, health score dimensions, settings, market overview, data asset growth, journal, signal zoo, macro dashboard, research papers/digest, training quality, scan metrics, projections, diagnostics, reconcile, CTO report shape
- Total cloud API tests: 67 (up from 38)

### Email Digests (Part C)
- New `src/email/digest_builder.py` — 4 fund-manager-style digests: pre-market (7:30), midday (12:00), EOD (4:15), evening (8:00)
- New `email_mode: digest` — sends exactly 4 emails per day at configured times
- Digest schedule wired into watch.py main tick loop with daily flag resets
- Per-trade and per-scan emails suppressed in digest mode
- Risk alerts still send immediately regardless of mode
- 15 new tests for all 4 digest builders (empty DB, populated, format)

### Telegram (Part D)
- Trade open/close and risk alerts remain immediate
- Per-scan email spam suppressed in digest mode (Telegram notifications unchanged)

---

## 2026-03-27 — Live Trade Reconciliation

### New Features
- **`reconcile-live` CLI Command** — Detects orphaned Alpaca positions (on broker but not in DB) and stale DB records (in DB but not on broker); backfills or marks closed with `--dry-run` option
- **Live Ledger Reconcile Button** — Disabled button with tooltip showing CLI command for local execution

### Fixes
- **Fractional Shares** — `get_live_positions()`, `get_all_positions()`, `get_position()` in alpaca_adapter now use `float(qty)` instead of `int(qty)` to support fractional share positions

### Backend
- New `POST /api/live/reconcile` endpoint (returns cloud_mode error — local CLI only)
- New `src/shadow_trading/reconcile.py` module with `reconcile_live_trades()` function

### Tests
- 5 new tests: dry-run safety, orphan backfill, stale marking, no-discrepancy, paper-trade isolation

---

## 2026-03-27 — Dashboard Polish Sprint

### New Features
- **Research Docs on Cloud** — 35+ markdown docs served via `research_docs` Postgres table with category sidebar and search
- **Council Session Detail View** — Expandable session rows with full agent vote cards, vote distribution chart, dissent highlighting
- **Activity Feed Cloud Polling** — Polling fallback for cloud mode (60s) with event-type icons
- **Live Trade Ledger** — New page for $100 Alpaca live account with equity curve, open/closed tables, header metrics
- **Shadow Ledger Enhancements** — Metrics strip (equity, PF, DD), expandable trade detail rows, 4 viz tabs (equity curve, distribution, sector heatmap, calendar)
- **Hardware Roadmap** — Phase 2 and Phase 4 build specs with costs and unlock descriptions
- **Monthly Cost Timeline** — Visual bar chart of per-phase monthly costs

### Fixes
- **Audit Banner** — Parses raw JSON/code fences from audit summary, shows clean text
- **Shadow Equity** — Uses `shadow/account` endpoint (starting_capital + closed_pnl) instead of potentially wrong `alpaca_equity`
- **KPI Thresholds** — Sharpe/Win Rate show with >= 2 trades (was >= 5)
- **Confidence Calibration** — Shows "< X/50 trades" instead of "--"
- **Rubric Score** — Shows "Not scored yet" with tooltip instead of "n/a"
- **Health Score Dimensions** — All 5 dimensions (Performance, Model Quality, Data Asset, Flywheel, Defensibility) now computed from real data with metric breakdowns
- **Review Tab Removed** — Replaced with Live Ledger in sidebar navigation

### Backend
- 8 new cloud API endpoints: `/api/council/session/{id}`, `/api/activity/feed`, `/api/live/trades`, `/api/live/summary`, `/api/settings` (GET/POST), updated `/api/docs`, `/api/health/score`
- `research_docs` table added to sync pipeline
- Research synthesis wired to Sunday 6 PM schedule
- Daily metric snapshots at 4 PM EOD (not just Saturday)
- Nightly Telegram notification for new research papers

### Components
- New `Tooltip.jsx` — Hover tooltip with 300ms delay
- New `LiveLedger.jsx` — Full live trading ledger page
- Updated `ActivityFeed.jsx` — Cloud polling fallback + event icons
- Updated `Council.jsx` — Expandable session rows
- Updated `ShadowLedger.jsx` — Enhanced with viz tabs + trade expansion

### Roadmap
- Updated to 6 phases (added Phase 6 — Multi-Desk Expansion)
- Phase costs updated: $64 → $125 → $155 → $220 → $500+
- Hardware roadmap section added

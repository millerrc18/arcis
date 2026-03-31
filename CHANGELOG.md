# Changelog

## [Unreleased] - 2026-03-31

### Sprint 6: Data Pipeline Visibility

#### API Wiring (Task 1)
- Added: `getDataCollectionStats`, `getTrainingHistory`, `getScanMetrics` methods to frontend api.js

#### Data Collectors Grid (Task 2)
- Added: 12-card collector grid on Training page with freshness indicators (green/yellow/red)
- Added: row counts, relative dates ("2h ago", "yesterday"), and ticker coverage per collector
- Added: responsive grid (3 cols desktop, 2 tablet, 1 mobile)

#### Training Pipeline Status (Task 3)
- Added: pipeline status section on Training page with active model card and status badge
- Added: format compliance display (XML vs plain_text counts)
- Added: leakage test indicator with OK/Marginal/Leaking thresholds
- Added: quadrant distribution 2x2 grid (good/bad process x good/bad outcome)

#### Model History (Task 4)
- Added: model history timeline on Health page with version, status badge, example count, holdout score
- Added: graceful single-model state ("First model — no comparisons yet")

#### Scan Metrics Trend (Task 5)
- Added: scan metrics section on Dashboard with today's summary (scans, packets, LLM success rate)
- Added: 7-day trend sparkline using Recharts LineChart
- Added: LLM success rate color coding (green >90%, yellow 70-90%, red <70%)

#### Card Contrast Fix (Task 6)
- Added: `.arcis-card` CSS class in index.css (elevated bg, border, shadow, hover state)
- Changed: all card elements across Dashboard, Health, Training, Settings, CTOReport to use `.arcis-card`
- Changed: MetricCard component migrated from inline styles to `.arcis-card`
- Changed: Dashboard cards migrated from `--slate-*` to `--arcis-*` design tokens
- Added: light mode shadow variant for `.arcis-card`

#### .env Secret Migration (Task 7)
- Added: `os.environ.get()` with YAML fallback to 10 modules (telegram, claude_client, 3 Finnhub collectors, macro collector, email notifier, insiders enrichment, news enrichment)
- Added: `TELEGRAM_CHAT_ID` to `.env.example`
- Added: `tests/test_env_secrets.py` with 11 tests covering env precedence, YAML fallback, missing keys, and placeholder detection
- Pattern: `.env` (via `load_dotenv`) takes precedence; YAML config is backward-compatible fallback

#### Documentation (Task 8)
- Updated: CHANGELOG.md with Sprint 6 entry
- Updated: AGENTS.md counts
- Verified: test baseline maintained, frontend builds successfully

---

### Sprint 5: Dashboard Polish & UX

#### Shadow Ledger (Task 1)
- Added: summary row (total positions, unrealized P&L, avg days held)
- Added: P&L values with colorblind-accessible arrows (▲/▼) + `financial-data` class
- Added: alternating row shading via `var(--arcis-bg-elevated)`
- Added: mobile-responsive columns (hide IS bps, strategy on <768px)
- Added: default sort by P&L% descending (best performers at top)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Validation Page (Task 2)
- Added: `validate-system` command to executor (command queue integration)
- Added: error state display when watch loop offline
- Enhanced: fallback from direct API to command queue for validation runs

#### Training Page (Task 3)
- Added: hero section with large total examples count, weekly count, avg quality
- Added: outcome distribution horizontal stacked bar (WIN/LOSS/TIMEOUT/PASS)
- Added: v2 spec targets vs actual comparison grid
- Added: source breakdown bar chart (historical_backfill, blinded_win, etc.)
- Added: ticker coverage progress bar and regime coverage display
- Added: recent examples table (last 10 with ticker, source, outcome, quality, date)
- Added: graceful handling when outcome_type data pending migration

#### CTO Report (Task 4)
- Added: Phase 1 gate progress bar (X/50 trades)
- Added: minimum-data notices ("Requires N+ closed trades" instead of N/A)
- Added: early win rate callout (100% on <10 trades note)
- Changed: fund metrics only shown when 20+ trades available
- Changed: confidence calibration section shows data requirements when <10 trades

#### Docs Page (Task 5)
- Added: sticky mobile back button ("← Back to documents") always visible on mobile
- Added: two-column desktop layout (300px sidebar + content viewer)
- Added: single-column mobile navigation (list → detail → back)
- Added: document viewer max-width 720px for comfortable reading
- Added: file icon indicators and sidebar card styling

#### Notes Page (Task 6)
- Added: tag filter pills at top for quick category filtering
- Added: pinned-first + reverse chronological default sort
- Added: relative date formatting (e.g., "2h ago", "Mar 15")
- Added: empty state with icon ("No notes yet — add your first note above")
- Changed: textarea placeholder to "Add a note..." for cleaner UX

#### Logs Page (Task 7)
- Added: expandable log rows (click to show details_json as formatted JSON)
- Added: "Run Command" dropdown with common commands (scan, council, collect-data, validate)
- Added: command auto-refresh at 10s (faster than logs at 30s)
- Added: empty state messages for both logs and commands
- Added: CRITICAL level background highlighting (red tint)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Settings Page (Task 8)
- Added: section icons (Settings2, Shield, Brain, Clock) from lucide-react
- Added: setting descriptions below each label
- Added: "Saved ✓" animation feedback on setting changes
- Added: reset confirmation dialog (two-step: click → confirm)
- Added: system health items in card-style background tiles
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Backend
- Added: `validate-system` command handler in executor.py
- Test count: 1,110 (unchanged)

### Sprint 4E: Post-Review Cleanup & Production Hardening

#### Database Schema
- Added: `strategy_type` column to shadow_trades (DEFAULT 'pullback')
- Added: `outcome_type` and `regime` columns to training_examples
- Added: `level` column to activity_log (DEFAULT 'INFO')
- Added: `build_score_history` CREATE TABLE to create_missing_tables.py
- Added: scripts/migrate_production_db.py (safe, idempotent migration)
- Backfilled: outcome_type on 969/972 training examples from trade outcomes

#### Watch Loop Fixes
- Fixed: Traffic Light now computed during watch loop scans (was only in scan_service)
- Fixed: VIX read from vix_term_structure DB table instead of relying on vix_proxy feature
- Fixed: scan_metrics now recorded for every scan cycle (success, empty, or failed)
- Fixed: Council failure sends Telegram notification (was silent on error)

#### Robustness
- Fixed: weekly_review.py checks column existence via PRAGMA before querying
- Added: schema health section to weekly review (expected vs actual columns)
- Updated: README.md rewritten for Arcis (75 lines, private-repo focused)

#### Tests
- Added: tests/test_db_migration.py (4 tests: idempotent, adds columns, preserves data, creates tables)
- Added: test_vix_30_6_produces_red_vix_component in test_traffic_light.py
- Test count: 1,105 -> 1,110

### Sprint 4C: Dashboard as Control Plane

#### Command Queue System
- Added: pull-based command queue pattern (pending_commands, command_results, config_overrides, log_entries tables)
- Added: bidirectional sync — cloud pulls commands to local, local pushes results to cloud
- Added: command executor with 10 command types (scan, council, collect-data, halt-trading, etc.)
- Added: 5-minute command expiry, 10/min rate limiting, 10KB result truncation
- Added: DBLogHandler that writes WARNING+ to log_entries table (last 500 entries)

#### Config Override System
- Added: dashboard-editable settings with whitelisted keys only
- Added: config overrides merge with YAML defaults (overrides win for whitelisted keys)
- Added: blocked prefixes for API keys, DB paths, and secrets (never editable remotely)
- Added: "Reset to YAML" to clear all dashboard overrides

#### Cloud API Overhaul
- Changed: all stub action endpoints now submit commands via queue instead of returning "must be done locally"
- Added: POST /api/commands/submit, GET /api/commands/{id}/status, GET /api/commands/recent
- Added: GET /api/logs/recent with level and source filtering
- Added: DELETE /api/settings/overrides to clear all overrides
- Changed: POST /api/settings now submits config_change commands via queue

#### Frontend
- Added: editable Settings page with toggle/number inputs and source badges (yaml default vs dashboard override)
- Added: Logs page with filterable log table and recent commands history
- Added: command pending indicator on Dashboard (blue pulsing badge)
- Added: 14th dashboard page (Logs) to navigation

#### Documentation
- Added: ADR 012 — Pull-based command queue architecture decision
- Updated: AGENTS.md counts (169 Python files, 77 test files, 40 DB tables, 55 API routes)
- Added: 15 tests in test_command_queue.py (submission, expiry, whitelist, rate limiting, round-trip)

## [Unreleased] - 2026-03-27/29

### Weekend Mega Sprint (4 sprints: Stabilize + Hotfix + Build + Document)

#### Critical Safety Fixes
- Fixed: safety checks fail closed on errors, not open (#42)
- Fixed: journal closes after broker confirmation, not before (#41)
- Fixed: LLM validator accepts the real `TradePacket` schema (#40)
- Fixed: paper trades are logged as `failed` on submission failure instead of phantom opens (#46)
- Fixed: `/shadow/close` now requires broker exit semantics for Alpaca-backed trades (#45)
- Fixed: council data gatherers query the correct live column names (#44)
- Fixed: Telegram trade notifications use the real packet fields and source labels (#48)
- Fixed: kill-switch tests and training-ingestion tests now run deterministically against the hardened runtime behavior

#### New Features
- Added: event calendar 0-10 continuous risk scoring with sizing multipliers and Telegram alerts
- Added: bracket order health monitor with intraday, pre-market, and post-close verification
- Added: optional GBNF grammar enforcement path for XML commentary generation
- Added: data quality ingestion gates with duplicate detection and batch halt alerts
- Added: Notes page plus cloud CRUD API for pinned, tagged operator notes
- Added: Council.jsx v2 with new agent identities, consensus labels, strategic prompt input, and parameter adjustment history
- Added: HSHS radar chart and live phase-weight display on the Health page

#### Infrastructure
- Added: `scripts/verify_counts.py` for AGENTS.md count verification
- Added: `scripts/schema_report.py` for canonical SQLite schema reporting
- Added: `scripts/generate_dependency_graph.py` and generated `docs/dependency-graph.md`
- Added: `scripts/render_architecture_doc.py` to regenerate the architecture inventory from live code
- Added: strategy-specific pullback timeout support (15 -> 7 days)
- Added: Render sync coverage for the new notes data path
- Added: `bracket_health` and `user_notes` tables to the working schema
- Fixed: SQLite connection handling in earnings enrichment (#52)
- Fixed: kill-switch path handling so safety remains configurable without leaking ambient state into tests (#47)
- Removed: stale council v1 compatibility wrappers from active code paths

#### Documentation
- Added: 11 architecture decision records under `docs/decisions/`
- Rewrote: `docs/architecture.md` from the live module, route, and schema inventories
- Rewrote: `docs/roadmap.md` to consolidate the confirmed March 28-29, 2026 decisions
- Added: `docs/observation-log-template.md` for the Monday-through-Sunday operating rhythm
- Updated: Framework v2.1 research integration notes for risk budgeting, EDGAR fundamentals, operating cadence, and fund-path deferrals
- Documented: council prompt caching was evaluated and intentionally not enabled because the current agent prompts do not share a reusable long prefix

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

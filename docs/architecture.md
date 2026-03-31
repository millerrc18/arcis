# Architecture

## System Overview
Arcis is an autonomous equity trading system for the S&P 100 that combines deterministic technical ranking, event-aware risk overlays, LLM-generated trade commentary, bracket-order execution through Alpaca, and a self-improving training loop. The live runtime is centered on the watch loop and scan service: market data and enrichment flow into feature computation, regime and event risk size the opportunity set, the ranker surfaces candidates, the packet writer produces structured commentary, the governor enforces hard limits, and the executor journals and manages trades end to end.

## Module Inventory
### `./`
- `src/__init__.py`: Package marker for src.
- `src/config.py`: Configuration loader for the Systematic Equity Research.
- `src/data_integrity.py`: Data integrity assertions for critical data boundaries.
- `src/log_config.py`: Logging configuration for the Arcis system.
- `src/main.py`: Arcis CLI bootstrap and parser wiring.
- `src/models.py`: Backward-compatible schema re-exports for packet construction and older imports.
- `src/schemas.py`: Pydantic models for the Arcis system.

### `api/`
- `src/api/__init__.py`: Package marker for api.
- `src/api/app.py`: FastAPI application for the Arcis dashboard.
- `src/api/cloud_app.py`: Stripped-down read-only FastAPI for Render cloud deployment.
- `src/api/websocket.py`: WebSocket live update manager for the dashboard.

### `api/routes/`
- `src/api/routes/__init__.py`: Package marker for routes.
- `src/api/routes/actions.py`: Action endpoints for triggering system operations from the dashboard.
- `src/api/routes/docs.py`: Documentation API routes.
- `src/api/routes/packets.py`: Packets API routes.
- `src/api/routes/review.py`: Review API routes.
- `src/api/routes/scan.py`: Scan API routes.
- `src/api/routes/shadow.py`: Shadow trading API routes.
- `src/api/routes/system.py`: System API routes.
- `src/api/routes/training.py`: Training API routes.

### `cli/`
- `src/cli/__init__.py`: Package marker for cli.
- `src/cli/commands.py`: CLI command implementations for Arcis.

### `council/`
- `src/council/__init__.py`: Package marker for council.
- `src/council/agents.py`: AI Council agent definitions - vote-first protocol.
- `src/council/engine.py`: Council Engine v2 - vote-first Modified Delphi sessions.
- `src/council/protocol.py`: Council protocol - vote-first Modified Delphi.
- `src/council/value_tracker.py`: Council value tracking - counterfactual P&L computation.

### `data_collection/`
- `src/data_collection/__init__.py`: Package marker for data_collection.
- `src/data_collection/analyst_collector.py`: Analyst estimates and price target collector via Finnhub.
- `src/data_collection/cboe_collector.py`: CBOE Put/Call ratio collector.
- `src/data_collection/docs_collector.py`: Collect markdown documentation files into research_docs SQLite table for cloud sync.
- `src/data_collection/edgar_collector.py`: SEC EDGAR filing collector.
- `src/data_collection/fed_collector.py`: FOMC & Fed communications collector.
- `src/data_collection/insider_collector.py`: SEC insider transactions collector via Finnhub.
- `src/data_collection/macro_collector.py`: Expanded FRED macro indicator collector.
- `src/data_collection/options_collector.py`: EOD options chain snapshot collector via yfinance.
- `src/data_collection/options_metrics.py`: Derived per-ticker options metrics computed from raw chain snapshots.
- `src/data_collection/research_collector.py`: Research intelligence collector - discovers and scores papers/posts nightly.
- `src/data_collection/research_synthesizer.py`: Weekly research intelligence synthesis via Claude API.
- `src/data_collection/short_interest_collector.py`: FINRA short interest collector via Finnhub.
- `src/data_collection/trends_collector.py`: Google Trends market-wide sentiment collector.
- `src/data_collection/vix_collector.py`: VIX term structure snapshot collector.

### `data_enrichment/`
- `src/data_enrichment/__init__.py`: Package marker for data_enrichment.
- `src/data_enrichment/earnings_signals.py`: PEAD (Post-Earnings Announcement Drift) enrichment signals.
- `src/data_enrichment/enricher.py`: Data enrichment orchestrator.
- `src/data_enrichment/fundamentals.py`: SEC EDGAR fundamental data fetcher using XBRL API.
- `src/data_enrichment/insiders.py`: Insider trading data fetcher.
- `src/data_enrichment/macro.py`: Macroeconomic context from FRED API.
- `src/data_enrichment/news.py`: News data fetcher using Finnhub Company News API.

### `data_ingestion/`
- `src/data_ingestion/__init__.py`: Package marker for data_ingestion.
- `src/data_ingestion/market_data.py`: Market data ingestion via yfinance.

### `email/`
- `src/email/__init__.py`: Package marker for email.
- `src/email/digest_builder.py`: Build fund-manager-style email digests for Arcis.
- `src/email/notifier.py`: SMTP email notifier for the Systematic Equity Research.

### `evaluation/`
- `src/evaluation/__init__.py`: Package marker for evaluation.
- `src/evaluation/auditor.py`: Daily and weekly auditor agent for risk monitoring.
- `src/evaluation/backtester.py`: Walk-forward model backtesting framework.
- `src/evaluation/change_detector.py`: CUSUM (Cumulative Sum) performance change detection.
- `src/evaluation/cto_report.py`: CTO performance report generator.
- `src/evaluation/feature_importance.py`: Feature importance tracking with trend detection.
- `src/evaluation/gate_evaluator.py`: 50-trade gate evaluation for Phase 1 -> Phase 2 decision.
- `src/evaluation/hshs.py`: Arcis System Health Score (HSHS) computation.
- `src/evaluation/hshs_live.py`: Live HSHS computation from database state.
- `src/evaluation/metrics.py`: Lightweight evaluation metrics helpers used by reporting and tests.
- `src/evaluation/postmortem.py`: Assistant postmortem generation for closed shadow trades.
- `src/evaluation/scorecard.py`: Weekly and bootcamp scorecard generation.
- `src/evaluation/statistics.py`: Statistical validation functions for the walk-forward framework.
- `src/evaluation/system_validator.py`: System validation engine for Arcis.

### `features/`
- `src/features/__init__.py`: Package marker for features.
- `src/features/earnings.py`: Earnings date lookup and event-risk classification.
- `src/features/engine.py`: Feature engine for pullback-in-trend setup analysis.
- `src/features/event_proximity.py`: Market event proximity features (FOMC, CPI, NFP, GDP).
- `src/features/event_risk_score.py`: Event calendar risk scoring - continuous 0-10 additive system.
- `src/features/filing_nlp.py`: SEC filing NLP feature extraction.
- `src/features/regime.py`: Market regime indicators: SPY trend, volatility, breadth, RSI, sector context.
- `src/features/setup_classifier.py`: Rule-based setup type classifier for equity trades.
- `src/features/traffic_light.py`: Traffic Light regime overlay - controls position sizing.

### `journal/`
- `src/journal/__init__.py`: Package marker for journal.
- `src/journal/store.py`: SQLite journal storage for recommendations and shadow trades.

### `llm/`
- `src/llm/__init__.py`: Package marker for llm.
- `src/llm/client.py`: Ollama LLM client with graceful fallback.
- `src/llm/grammar_client.py`: Grammar-constrained LLM client using llama-cpp-python with GBNF.
- `src/llm/packet_writer.py`: LLM-enhanced trade packet writer with template fallback.
- `src/llm/postmortem_writer.py`: LLM-enhanced postmortem writer with template fallback.
- `src/llm/prompts.py`: System prompts for LLM-enhanced output.
- `src/llm/validator.py`: LLM output validation layer.
- `src/llm/watchlist_writer.py`: LLM-enhanced morning watchlist narrative writer.

### `logging/`
- `src/logging/__init__.py`: Package marker for logging.
- `src/logging/activity.py`: Persistent activity logging for the Arcis system.

### `notifications/`
- `src/notifications/__init__.py`: Package marker for notifications.
- `src/notifications/telegram.py`: Telegram notification client for Arcis.

### `packets/`
- `src/packets/__init__.py`: Package marker for packets.
- `src/packets/eod_recap.py`: End-of-day recap email formatter.
- `src/packets/template.py`: Template packet builder and demo renderer for non-LLM packet generation.
- `src/packets/watchlist.py`: Morning watchlist email formatter.

### `ranking/`
- `src/ranking/__init__.py`: Package marker for ranking.
- `src/ranking/ranker.py`: Deterministic ranking and qualification for trade candidates.

### `risk/`
- `src/risk/__init__.py`: Package marker for risk.
- `src/risk/governor.py`: Risk governor - hard limits enforced before every trade.

### `scheduler/`
- `src/scheduler/__init__.py`: Package marker for scheduler.
- `src/scheduler/metrics.py`: Schedule metrics tracking for the 24/7 compute scheduler.
- `src/scheduler/premarket.py`: Pre-market inference tasks that run after Ollama is loaded but before market opens.
- `src/scheduler/scorer.py`: Between-scan inference scoring using the already-loaded Ollama model.
- `src/scheduler/vram_manager.py`: VRAM transition management between Ollama inference and PyTorch training.
- `src/scheduler/watch.py`: Watch loop for automated daily cadence.

### `services/`
- `src/services/__init__.py`: Package marker for services.
- `src/services/recap_service.py`: EOD recap service.
- `src/services/review_service.py`: Review and evaluation service.
- `src/services/scan_service.py`: Scan pipeline service.
- `src/services/shadow_service.py`: Shadow trading service.
- `src/services/system_service.py`: System service for preflight checks and config management.
- `src/services/training_service.py`: Training pipeline service.
- `src/services/watchlist_service.py`: Morning watchlist service.

### `shadow_trading/`
- `src/shadow_trading/__init__.py`: Package marker for shadow_trading.
- `src/shadow_trading/alpaca_adapter.py`: Alpaca paper trading adapter with safety guardrails.
- `src/shadow_trading/bracket_monitor.py`: Bracket order health monitoring - verifies stop/target legs are active.
- `src/shadow_trading/executor.py`: Shadow trade execution flow: entry and exit monitoring.
- `src/shadow_trading/ledger.py`: Shadow trading ledger - re-exports from executor for backwards compatibility.
- `src/shadow_trading/metrics.py`: Shadow ledger performance metrics.
- `src/shadow_trading/models.py`: Shadow trade data model.
- `src/shadow_trading/reconcile.py`: Reconcile Alpaca live positions with shadow_trades database.

### `strategy/`
- `src/strategy/__init__.py`: Package marker for strategy.
- `src/strategy/canary.py`: Canary rules-based scoring - a simple baseline to compare against the LLM.

### `sync/`
- `src/sync/__init__.py`: Package marker for sync.
- `src/sync/render_sync.py`: Background sync thread that pushes local SQLite data to Render Postgres.

### `training/`
- `src/training/__init__.py`: Package marker for training.
- `src/training/ab_evaluation.py`: A/B shadow model evaluation with promotion logic.
- `src/training/backfill.py`: Historical backfill orchestrator for high-quality training data generation.
- `src/training/bootstrap.py`: Synthetic training data bootstrapping via Claude API.
- `src/training/canary.py`: Canary monitoring for detecting model quality degradation.
- `src/training/claude_client.py`: Claude API client for generating training data.
- `src/training/curriculum.py`: Three-stage curriculum training with difficulty classification and contrastive pairs.
- `src/training/data_collector.py`: Training data collection from closed trades using the self-blinding pipeline.
- `src/training/dpo_pipeline.py`: DPO preference pair generation and export pipeline.
- `src/training/historical_data.py`: Historical data fetcher with point-in-time slicing for backfill engine.
- `src/training/historical_scanner.py`: Historical scanner with outcome tracking and training example generation.
- `src/training/ingestion_gate.py`: Training data ingestion validation - prevents format contamination.
- `src/training/leakage_detector.py`: Outcome leakage detector for training data quality assurance.
- `src/training/quality_drift.py`: Quality drift metrics for monitoring model output degradation.
- `src/training/quality_filter.py`: LLM-as-Judge quality scoring for training examples.
- `src/training/report.py`: Training progress report generator.
- `src/training/trainer.py`: Fine-tuning orchestrator with Unsloth and auto-rollback.
- `src/training/validation.py`: Training dataset validation and quality checks.
- `src/training/versioning.py`: Model versioning and performance tracking for the training pipeline.

### `universe/`
- `src/universe/__init__.py`: Package marker for universe.
- `src/universe/company_names.py`: Static company name lookup for S&P 100 tickers.
- `src/universe/sectors.py`: GICS sector mapping for S&P 100 constituents.
- `src/universe/sp100.py`: S&P 100 (OEX) constituent universe.

### `utils/`
- `src/utils/__init__.py`: Package marker for utils.
- `src/utils/activity_logger.py`: Structured activity logger for dashboard display and observability.

## API Endpoints
### `src/api/cloud_app.py`
- `GET /healthz`: Unauthenticated health check for Render.
- `GET /api/diagnostics`: Test every DB table the dashboard needs. Returns pass/fail per table.
- `GET /api/auth`: Verify auth token without touching the database.
- `GET /api/status`: System status overview from cloud data.
- `GET /api/shadow/open`: Open shadow trades.
- `GET /api/shadow/closed`: Closed shadow trades for the last N days.
- `GET /api/shadow/metrics`: Computed metrics from closed trades.
- `GET /api/packets`: Recent recommendations / trade packets.
- `GET /api/training/status`: Training pipeline status from cloud data.
- `GET /api/training/versions`: All model versions.
- `GET /api/metrics/history`: Metric snapshots for trending charts.
- `GET /api/schedule-metrics`: Compute schedule metrics.
- `GET /api/earnings`: Upcoming earnings from the earnings calendar.
- `GET /api/audit/latest`: Most recent daily audit report.
- `GET /api/docs`: Documentation listing from research_docs table.
- `GET /api/docs/{doc_id}`: Individual doc content from research_docs table.
- `GET /api/health/hshs`: Compute and return the live Arcis System Health Score.
- `GET /api/build-score`: Build Score composite KPI stub for the dashboard.
- `GET /api/traffic-light/current`: Current Traffic Light regime stub for the dashboard.
- `GET /api/notes`: List all notes for the Notes page.
- `POST /api/notes`: Create a new note.
- `PUT /api/notes/{note_id}`: Update a note in place.
- `DELETE /api/notes/{note_id}`: Delete a note.
- `GET /api/council/latest`: Latest council session with votes.
- `GET /api/council/history`: Council session history.
- `GET /api/council/session/{session_id}`: Get full council session details including all agent votes.
- `GET /api/activity/feed`: Get recent activity log entries.
- `POST /api/council/strategic`: Cloud deployment cannot run strategic council sessions directly.
- `GET /api/config`: Return system config for the Settings page. Cloud mode: static config.
- `GET /api/halt-status`: Trading halt status. Cloud mode: always report not halted.
- `GET /api/costs`: API cost summary from api_costs table.
- `GET /api/health/score`: HSHS health score. All 5 dimensions computed from cloud data.
- `GET /api/live/trades`: Get all live trades (source='live' in shadow_trades).
- `GET /api/live/summary`: Live account summary metrics.
- `GET /api/settings`: Return current config values (safe subset only).
- `POST /api/settings`: Update config values. Cloud mode: not available.
- `POST /api/live/reconcile`: Trigger live trade reconciliation. Must be run locally.
- `GET /api/shadow/account`: Shadow trading account summary.
- `GET /api/cto-report`: Generate CTO report from cloud data.
- `GET /api/scan/latest`: Latest scan results.
- `GET /api/review/pending`: Trades pending review.
- `GET /api/review/scorecard`: Review scorecard.
- `GET /api/review/postmortems`: Recent postmortems.
- `GET /api/audit/history`: Audit report history.
- `GET /api/training/report`: Training pipeline report.
- `GET /api/metric-history`: Alias for metrics/history - some frontend pages use this path.
- `POST /api/actions/scan`: action scan.
- `POST /api/actions/cto-report`: action cto report.
- `POST /api/actions/collect-training`: action collect training.
- `POST /api/actions/train-pipeline`: action train pipeline.
- `POST /api/actions/score`: action score.
- `POST /api/actions/council`: action council.
- `POST /api/halt-trading`: halt trading.
- `POST /api/resume-trading`: resume trading.
- `POST /api/training/train`: action train.
- `POST /api/training/bootstrap`: action bootstrap.
- `POST /api/training/rollback`: action rollback.
- `POST /api/shadow/close/{ticker}`: action close trade.
- `GET /api/market/overview`: Market overview - VIX, regime, macro summary.
- `GET /api/data-asset/growth`: Data asset growth over time.
- `GET /api/journal`: Trade journal - closed trades with recommendation context.
- `GET /api/signal-zoo`: Signal zoo - setup signals with optional filters.
- `GET /api/macro/dashboard`: Macro dashboard - latest values for each FRED series.
- `GET /api/research/papers`: Recent research papers.
- `GET /api/research/digest`: Latest weekly research digest.
- `GET /api/training/quality`: Training data quality stats.
- `GET /api/scan/metrics`: Latest scan pipeline metrics.
- `GET /api/projections/live`: Live performance metrics for the revenue projection model.

### `src/api/routes/actions.py`
- `POST /collect-data`: Run the full data collection pipeline in the background.
- `POST /scan`: Run a market scan in the background.
- `POST /cto-report`: Generate a fresh CTO report in the background.
- `POST /collect-training`: Collect training data from closed trades.
- `POST /train-pipeline`: Run the full training pipeline (score -> leakage -> classify -> train).
- `POST /score`: Score unscored training examples.

### `src/api/routes/docs.py`
- `GET /docs`: list docs.
- `GET /docs/{doc_id}`: get doc.

### `src/api/routes/packets.py`
- `GET /packets`: list packets.
- `GET /packets/{recommendation_id}`: get packet.

### `src/api/routes/review.py`
- `GET /review/pending`: pending reviews.
- `GET /review/scorecard`: scorecard.
- `GET /review/postmortems`: postmortems.
- `GET /review/postmortem/{recommendation_id}`: postmortem detail.
- `GET /review/{recommendation_id}`: review detail.
- `POST /review/{recommendation_id}`: submit review endpoint.
- `POST /review/mark-executed/{ticker}`: mark executed endpoint.

### `src/api/routes/scan.py`
- `POST /scan`: trigger scan.
- `GET /scan/latest`: get latest scan.
- `POST /morning-watchlist`: morning watchlist.
- `POST /eod-recap`: eod recap.

### `src/api/routes/shadow.py`
- `GET /shadow/open`: open trades.
- `GET /shadow/closed`: closed trades.
- `GET /shadow/account`: account.
- `GET /shadow/metrics`: metrics.
- `POST /shadow/close/{ticker}`: close trade.

### `src/api/routes/system.py`
- `GET /status`: status.
- `GET /preflight`: preflight.
- `GET /config`: get config.
- `GET /cto-report`: cto report.
- `GET /costs`: api costs.
- `POST /halt-trading`: Emergency halt - stops all new trade entry immediately.
- `POST /resume-trading`: Resume trading after a halt.
- `GET /halt-status`: Check if trading is halted.
- `GET /audit/latest`: Get the most recent daily audit report.
- `GET /audit/history`: Get audit reports for the last N days.
- `GET /metric-history`: Get rolling metric snapshots computed from closed trade history.
- `GET /data-collection-stats`: Return summary stats for all data collection tables.
- `GET /earnings`: Return upcoming earnings dates for the S&P 100 universe.
- `GET /activity-log`: Return recent activity log entries.
- `GET /schedule-metrics`: Return compute schedule metrics for dashboard display.
- `PUT /config`: update config.
- `GET /system/validation`: Run system validation checks. Cached for 5 minutes unless fresh=True.

### `src/api/routes/training.py`
- `GET /training/status`: training status.
- `GET /training/versions`: training versions.
- `GET /training/report`: training report.
- `POST /training/bootstrap`: bootstrap.
- `POST /training/train`: train.
- `POST /training/rollback`: rollback.

## Data Flow
1. Universe loading starts with `src/universe/sp100.py`, then `src/data_ingestion/market_data.py` and `src/features/engine.py` build the technical feature set.
2. Enrichment layers add fundamentals, insiders, news, macro context, and PEAD-style earnings signals via `src/data_enrichment/`.
3. `src/features/traffic_light.py` computes the regime overlay, and `src/features/event_risk_score.py` adds the 0-10 continuous calendar risk score plus sizing multiplier.
4. `src/ranking/ranker.py` filters and sorts the candidate set, while `src/services/scan_service.py` coordinates alerts, feature packaging, and packet generation.
5. `src/llm/packet_writer.py` writes XML commentary through Ollama by default, with optional GBNF-constrained generation through `src/llm/grammar_client.py`.
6. `src/risk/governor.py` applies hard portfolio rules, combining traffic-light and event-risk sizing with daily-loss, concentration, volatility, and duplicate-position checks.
7. `src/shadow_trading/executor.py` submits or simulates orders, journals outcomes through `src/journal/store.py`, and maintains bracket-backed open-position management.
8. `src/scheduler/watch.py` orchestrates the day: scans, premarket workflows, bracket monitoring, council sessions, overnight collection, scoring, reporting, and retraining triggers.

## Council Flow
1. `src/council/agents.py` gathers five analytical lenses: Tactical, Strategic, Red Team, Innovation, and Macro.
2. `src/council/protocol.py` runs independent Round 1 votes first, aggregates conviction-weighted outputs, and only escalates to Round 2 when consensus is weak.
3. `src/council/engine.py` persists sessions, votes, debug traces, parameter adjustments, and calibration records into the council tables.
4. `src/council/value_tracker.py` records counterfactual value attribution so the council can earn or lose authority based on realized outcomes.
5. The dashboard surfaces this through `frontend/src/pages/Council.jsx`, including vote cards, consensus labels, strategic prompts, and parameter-adjustment history.

## New Since Last Update
- Traffic Light regime overlay and live state tracking.
- PEAD enrichment features and earnings/event-aware risk handling.
- Implementation shortfall and council value-tracking infrastructure.
- HSHS live scoring and dashboard radar visualization.
- Council v2 vote-first protocol and updated Council dashboard page.
- Event calendar risk scoring with Telegram alerts and multiplicative sizing.
- Bracket health monitoring across intraday, premarket, and post-close checks.
- Optional GBNF grammar enforcement path for XML commentary generation.
- Training data ingestion gates with duplicate detection and compliance halts.
- Notes CRUD API and cloud dashboard Notes page.

## Deleted or Retired Runtime Modules
- `src/scheduler/overnight.py`: retired in favor of the consolidated `src/scheduler/watch.py` loop.
- `src/shadow_trading/broker.py`: no longer active in the runtime path.
- `*_backup.py` council v1 files: retained only as archival references and excluded from active imports, tests, and route generation.

## Database Schema
The following report is generated directly from `python scripts/schema_report.py` against the working SQLite database.

# Schema Report

- Database: `C:\Users\mille\OneDrive\04 - Projects\halcyon-lab\halcyon-lab\ai_research_desk.sqlite3`
- Generated: `2026-03-29T15:21:05.386682+00:00`
- Objects: `40`

## Table: `activity_log`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `event_type` | `TEXT` | 0 | `` | 0 |
| `detail` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |

Indexes:
- None

## Table: `analyst_estimates`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `date` | `TEXT` | 1 | `` | 0 |
| `consensus_buy` | `INTEGER` | 0 | `` | 0 |
| `consensus_hold` | `INTEGER` | 0 | `` | 0 |
| `consensus_sell` | `INTEGER` | 0 | `` | 0 |
| `consensus_strong_buy` | `INTEGER` | 0 | `` | 0 |
| `consensus_strong_sell` | `INTEGER` | 0 | `` | 0 |
| `price_target_high` | `REAL` | 0 | `` | 0 |
| `price_target_low` | `REAL` | 0 | `` | 0 |
| `price_target_mean` | `REAL` | 0 | `` | 0 |
| `price_target_median` | `REAL` | 0 | `` | 0 |
| `num_analysts` | `INTEGER` | 0 | `` | 0 |
| `source` | `TEXT` | 0 | `'finnhub'` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_analyst_ticker_date` (NON-UNIQUE, c): `ticker`, `date`
- `sqlite_autoindex_analyst_estimates_1` (UNIQUE, u): `ticker`, `date`, `source`

## Table: `api_costs`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `cost_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `model` | `TEXT` | 1 | `` | 0 |
| `purpose` | `TEXT` | 1 | `` | 0 |
| `input_tokens` | `INTEGER` | 1 | `` | 0 |
| `output_tokens` | `INTEGER` | 1 | `` | 0 |
| `cost_dollars` | `REAL` | 1 | `` | 0 |

Indexes:
- `idx_api_costs_purpose` (NON-UNIQUE, c): `purpose`
- `idx_api_costs_created_at` (NON-UNIQUE, c): `created_at`
- `sqlite_autoindex_api_costs_1` (UNIQUE, pk): `cost_id`

## Table: `audit_reports`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `audit_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `audit_date` | `TEXT` | 1 | `` | 0 |
| `overall_assessment` | `TEXT` | 1 | `` | 0 |
| `summary` | `TEXT` | 0 | `` | 0 |
| `flags` | `TEXT` | 0 | `` | 0 |
| `metrics_to_watch` | `TEXT` | 0 | `` | 0 |
| `model_health` | `TEXT` | 0 | `` | 0 |
| `full_report` | `TEXT` | 0 | `` | 0 |

Indexes:
- `sqlite_autoindex_audit_reports_1` (UNIQUE, pk): `audit_id`

## Table: `bracket_health`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `check_id` | `TEXT` | 0 | `` | 1 |
| `trade_id` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `stop_leg_status` | `TEXT` | 0 | `` | 0 |
| `target_leg_status` | `TEXT` | 0 | `` | 0 |
| `bracket_intact` | `INTEGER` | 0 | `1` | 0 |
| `action_taken` | `TEXT` | 0 | `` | 0 |
| `checked_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `sqlite_autoindex_bracket_health_1` (UNIQUE, pk): `check_id`

## Table: `canary_evaluations`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `model_version` | `TEXT` | 0 | `` | 0 |
| `perplexity` | `REAL` | 0 | `` | 0 |
| `distinct_2` | `REAL` | 0 | `` | 0 |
| `verdict` | `TEXT` | 0 | `` | 0 |
| `details` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |

Indexes:
- None

## Table: `cboe_ratios`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `collected_date` | `TEXT` | 1 | `` | 0 |
| `equity_pc_ratio` | `REAL` | 0 | `` | 0 |
| `index_pc_ratio` | `REAL` | 0 | `` | 0 |
| `total_pc_ratio` | `REAL` | 0 | `` | 0 |
| `equity_pc_vs_20d_avg` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_cboe_ratios_date` (NON-UNIQUE, c): `collected_date`

## Table: `council_calibrations`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `calibration_id` | `TEXT` | 0 | `` | 1 |
| `session_id` | `TEXT` | 1 | `` | 0 |
| `agent_name` | `TEXT` | 0 | `` | 0 |
| `prediction` | `TEXT` | 1 | `` | 0 |
| `prediction_confidence` | `REAL` | 1 | `` | 0 |
| `verification_date` | `TEXT` | 1 | `` | 0 |
| `actual_outcome` | `TEXT` | 0 | `` | 0 |
| `correct` | `INTEGER` | 0 | `` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_council_calibrations_session` (NON-UNIQUE, c): `session_id`
- `sqlite_autoindex_council_calibrations_1` (UNIQUE, pk): `calibration_id`

## Table: `council_debug_log`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `debug_id` | `TEXT` | 0 | `` | 1 |
| `session_id` | `TEXT` | 1 | `` | 0 |
| `agent_name` | `TEXT` | 1 | `` | 0 |
| `round` | `INTEGER` | 1 | `` | 0 |
| `system_prompt_hash` | `TEXT` | 0 | `` | 0 |
| `user_message` | `TEXT` | 0 | `` | 0 |
| `raw_response` | `TEXT` | 0 | `` | 0 |
| `parsed_successfully` | `INTEGER` | 0 | `0` | 0 |
| `parse_error` | `TEXT` | 0 | `` | 0 |
| `latency_ms` | `INTEGER` | 0 | `` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_council_debug_session` (NON-UNIQUE, c): `session_id`
- `sqlite_autoindex_council_debug_log_1` (UNIQUE, pk): `debug_id`

## Table: `council_parameter_log`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `log_id` | `TEXT` | 0 | `` | 1 |
| `session_id` | `TEXT` | 1 | `` | 0 |
| `agent_name` | `TEXT` | 0 | `` | 0 |
| `parameter_name` | `TEXT` | 1 | `` | 0 |
| `default_value` | `REAL` | 1 | `` | 0 |
| `council_value` | `REAL` | 1 | `` | 0 |
| `applied_value` | `REAL` | 1 | `` | 0 |
| `rate_limited` | `INTEGER` | 0 | `0` | 0 |
| `attribution_start` | `TEXT` | 1 | `` | 0 |
| `attribution_end` | `TEXT` | 0 | `` | 0 |
| `trades_during_window` | `INTEGER` | 0 | `0` | 0 |
| `pnl_during_window` | `REAL` | 0 | `` | 0 |
| `counterfactual_pnl` | `REAL` | 0 | `` | 0 |
| `value_added_dollars` | `REAL` | 0 | `` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_param_log_window` (NON-UNIQUE, c): `attribution_start`, `attribution_end`
- `idx_param_log_session` (NON-UNIQUE, c): `session_id`
- `sqlite_autoindex_council_parameter_log_1` (UNIQUE, pk): `log_id`

## Table: `council_parameter_state`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `parameter_name` | `TEXT` | 0 | `` | 1 |
| `current_value` | `REAL` | 1 | `` | 0 |
| `default_value` | `REAL` | 1 | `` | 0 |
| `last_session_id` | `TEXT` | 0 | `` | 0 |
| `last_updated` | `TEXT` | 1 | `` | 0 |

Indexes:
- `sqlite_autoindex_council_parameter_state_1` (UNIQUE, pk): `parameter_name`

## Table: `council_sessions`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `session_id` | `TEXT` | 0 | `` | 1 |
| `session_type` | `TEXT` | 1 | `` | 0 |
| `trigger_reason` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `consensus` | `TEXT` | 0 | `` | 0 |
| `confidence_weighted_score` | `REAL` | 0 | `` | 0 |
| `is_contested` | `INTEGER` | 0 | `0` | 0 |
| `total_cost` | `REAL` | 0 | `` | 0 |
| `rounds_completed` | `INTEGER` | 0 | `0` | 0 |
| `result_json` | `TEXT` | 0 | `` | 0 |

Indexes:
- `idx_council_sessions_created` (NON-UNIQUE, c): `created_at`
- `sqlite_autoindex_council_sessions_1` (UNIQUE, pk): `session_id`

## Table: `council_votes`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `vote_id` | `TEXT` | 0 | `` | 1 |
| `session_id` | `TEXT` | 1 | `` | 0 |
| `agent_name` | `TEXT` | 1 | `` | 0 |
| `round` | `INTEGER` | 1 | `` | 0 |
| `position` | `TEXT` | 0 | `` | 0 |
| `confidence` | `INTEGER` | 0 | `` | 0 |
| `recommendation` | `TEXT` | 0 | `` | 0 |
| `key_data_points` | `TEXT` | 0 | `` | 0 |
| `risk_flags` | `TEXT` | 0 | `` | 0 |
| `vote` | `TEXT` | 0 | `` | 0 |
| `is_devils_advocate` | `INTEGER` | 0 | `0` | 0 |
| `direction` | `TEXT` | 0 | `` | 0 |
| `confidence_float` | `REAL` | 0 | `` | 0 |
| `assessment_json` | `TEXT` | 0 | `` | 0 |

Indexes:
- `idx_council_votes_session` (NON-UNIQUE, c): `session_id`
- `sqlite_autoindex_council_votes_1` (UNIQUE, pk): `vote_id`

## Table: `earnings_calendar`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `earnings_date` | `TEXT` | 1 | `` | 0 |
| `earnings_time` | `TEXT` | 0 | `` | 0 |
| `confirmed` | `INTEGER` | 0 | `0` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_earnings_ticker_date` (UNIQUE, c): `ticker`, `earnings_date`
- `idx_earnings_date` (NON-UNIQUE, c): `earnings_date`
- `idx_earnings_ticker` (NON-UNIQUE, c): `ticker`

## Table: `edgar_filings`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `cik` | `TEXT` | 1 | `` | 0 |
| `form_type` | `TEXT` | 1 | `` | 0 |
| `filing_date` | `TEXT` | 1 | `` | 0 |
| `accession_number` | `TEXT` | 1 | `` | 0 |
| `filing_url` | `TEXT` | 0 | `` | 0 |
| `description` | `TEXT` | 0 | `` | 0 |
| `full_text` | `TEXT` | 0 | `` | 0 |
| `sections_json` | `TEXT` | 0 | `` | 0 |
| `word_count` | `INTEGER` | 0 | `` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `sentiment_polarity` | `REAL` | 0 | `` | 0 |
| `sentiment_negative_count` | `INTEGER` | 0 | `` | 0 |
| `sentiment_uncertainty_count` | `INTEGER` | 0 | `` | 0 |
| `cautionary_phrases` | `TEXT` | 0 | `` | 0 |
| `sentiment_delta_polarity` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_edgar_ticker_date` (NON-UNIQUE, c): `ticker`, `filing_date`
- `sqlite_autoindex_edgar_filings_1` (UNIQUE, u): `accession_number`

## Table: `fed_communications`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `comm_type` | `TEXT` | 1 | `` | 0 |
| `title` | `TEXT` | 0 | `` | 0 |
| `date` | `TEXT` | 1 | `` | 0 |
| `speaker` | `TEXT` | 0 | `` | 0 |
| `url` | `TEXT` | 0 | `` | 0 |
| `full_text` | `TEXT` | 0 | `` | 0 |
| `word_count` | `INTEGER` | 0 | `` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_fed_comm_type_date` (NON-UNIQUE, c): `comm_type`, `date`
- `sqlite_autoindex_fed_communications_1` (UNIQUE, u): `comm_type`, `date`, `title`

## Table: `google_trends`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `collected_date` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `search_interest` | `REAL` | 0 | `` | 0 |
| `interest_vs_90d_avg` | `REAL` | 0 | `` | 0 |
| `spike_flag` | `INTEGER` | 0 | `` | 0 |

Indexes:
- `idx_google_trends_ticker_date` (NON-UNIQUE, c): `ticker`, `collected_date`

## Table: `insider_transactions`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `insider_name` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 0 | `` | 0 |
| `transaction_type` | `TEXT` | 0 | `` | 0 |
| `transaction_date` | `TEXT` | 0 | `` | 0 |
| `filing_date` | `TEXT` | 0 | `` | 0 |
| `shares` | `REAL` | 0 | `` | 0 |
| `price` | `REAL` | 0 | `` | 0 |
| `value` | `REAL` | 0 | `` | 0 |
| `shares_after` | `REAL` | 0 | `` | 0 |
| `source` | `TEXT` | 0 | `'finnhub'` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_insider_ticker_date` (NON-UNIQUE, c): `ticker`, `filing_date`

## Table: `macro_snapshots`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `collected_date` | `TEXT` | 1 | `` | 0 |
| `series_id` | `TEXT` | 1 | `` | 0 |
| `series_name` | `TEXT` | 1 | `` | 0 |
| `value` | `REAL` | 0 | `` | 0 |
| `previous_value` | `REAL` | 0 | `` | 0 |
| `change_pct` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_macro_snapshots_series` (NON-UNIQUE, c): `series_id`, `collected_date`
- `idx_macro_snapshots_date` (NON-UNIQUE, c): `collected_date`

## Table: `metric_snapshots`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `snapshot_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `snapshot_date` | `TEXT` | 1 | `` | 0 |
| `metrics_json` | `TEXT` | 1 | `` | 0 |

Indexes:
- `idx_metric_snapshots_date` (NON-UNIQUE, c): `snapshot_date`
- `sqlite_autoindex_metric_snapshots_1` (UNIQUE, pk): `snapshot_id`

## Table: `model_evaluations`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `evaluation_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `recommendation_id` | `TEXT` | 0 | `` | 0 |
| `ticker` | `TEXT` | 0 | `` | 0 |
| `input_text` | `TEXT` | 1 | `` | 0 |
| `current_model` | `TEXT` | 1 | `` | 0 |
| `current_output` | `TEXT` | 0 | `` | 0 |
| `current_score` | `REAL` | 0 | `` | 0 |
| `new_model` | `TEXT` | 1 | `` | 0 |
| `new_output` | `TEXT` | 0 | `` | 0 |
| `new_score` | `REAL` | 0 | `` | 0 |
| `winner` | `TEXT` | 0 | `` | 0 |
| `score_delta` | `REAL` | 0 | `` | 0 |

Indexes:
- `sqlite_autoindex_model_evaluations_1` (UNIQUE, pk): `evaluation_id`

## Table: `model_versions`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `version_id` | `TEXT` | 0 | `` | 1 |
| `version_name` | `TEXT` | 1 | `` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `training_examples_count` | `INTEGER` | 0 | `` | 0 |
| `synthetic_examples_count` | `INTEGER` | 0 | `` | 0 |
| `outcome_examples_count` | `INTEGER` | 0 | `` | 0 |
| `model_file_path` | `TEXT` | 0 | `` | 0 |
| `status` | `TEXT` | 1 | `'active'` | 0 |
| `notes` | `TEXT` | 0 | `` | 0 |
| `holdout_score` | `REAL` | 0 | `` | 0 |
| `holdout_details` | `TEXT` | 0 | `` | 0 |

Indexes:
- `idx_model_versions_status` (NON-UNIQUE, c): `status`
- `sqlite_autoindex_model_versions_1` (UNIQUE, pk): `version_id`

## Table: `options_chains`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `expiration` | `TEXT` | 1 | `` | 0 |
| `strike` | `REAL` | 1 | `` | 0 |
| `option_type` | `TEXT` | 1 | `` | 0 |
| `bid` | `REAL` | 0 | `` | 0 |
| `ask` | `REAL` | 0 | `` | 0 |
| `last_price` | `REAL` | 0 | `` | 0 |
| `volume` | `INTEGER` | 0 | `` | 0 |
| `open_interest` | `INTEGER` | 0 | `` | 0 |
| `implied_volatility` | `REAL` | 0 | `` | 0 |
| `delta` | `REAL` | 0 | `` | 0 |
| `gamma` | `REAL` | 0 | `` | 0 |
| `theta` | `REAL` | 0 | `` | 0 |
| `vega` | `REAL` | 0 | `` | 0 |
| `in_the_money` | `INTEGER` | 0 | `` | 0 |
| `underlying_price` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_options_chains_expiration` (NON-UNIQUE, c): `ticker`, `expiration`
- `idx_options_chains_collected` (NON-UNIQUE, c): `collected_at`
- `idx_options_chains_ticker_date` (NON-UNIQUE, c): `ticker`, `collected_at`

## Table: `options_metrics`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `collected_date` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `iv_rank` | `REAL` | 0 | `` | 0 |
| `iv_percentile` | `REAL` | 0 | `` | 0 |
| `put_call_volume_ratio` | `REAL` | 0 | `` | 0 |
| `put_call_oi_ratio` | `REAL` | 0 | `` | 0 |
| `atm_iv_30d` | `REAL` | 0 | `` | 0 |
| `iv_skew` | `REAL` | 0 | `` | 0 |
| `unusual_volume_flag` | `INTEGER` | 0 | `` | 0 |
| `max_unusual_volume_ratio` | `REAL` | 0 | `` | 0 |
| `total_call_volume` | `INTEGER` | 0 | `` | 0 |
| `total_put_volume` | `INTEGER` | 0 | `` | 0 |
| `total_call_oi` | `INTEGER` | 0 | `` | 0 |
| `total_put_oi` | `INTEGER` | 0 | `` | 0 |

Indexes:
- `idx_options_metrics_date` (NON-UNIQUE, c): `collected_date`
- `idx_options_metrics_ticker_date` (NON-UNIQUE, c): `ticker`, `collected_date`

## Table: `quality_drift_metrics`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `metric_date` | `TEXT` | 0 | `` | 0 |
| `avg_score` | `REAL` | 0 | `` | 0 |
| `score_std` | `REAL` | 0 | `` | 0 |
| `pass_rate` | `REAL` | 0 | `` | 0 |
| `template_fallback_rate` | `REAL` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |

Indexes:
- None

## Table: `recommendations`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `recommendation_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `company_name` | `TEXT` | 0 | `` | 0 |
| `mode` | `TEXT` | 0 | `` | 0 |
| `setup_type` | `TEXT` | 0 | `` | 0 |
| `priority_score` | `REAL` | 0 | `` | 0 |
| `confidence_score` | `REAL` | 0 | `` | 0 |
| `packet_type` | `TEXT` | 0 | `` | 0 |
| `price_at_recommendation` | `REAL` | 0 | `` | 0 |
| `market_regime` | `TEXT` | 0 | `` | 0 |
| `sector_context` | `TEXT` | 0 | `` | 0 |
| `trend_state` | `TEXT` | 0 | `` | 0 |
| `relative_strength_state` | `TEXT` | 0 | `` | 0 |
| `pullback_depth_pct` | `REAL` | 0 | `` | 0 |
| `atr` | `REAL` | 0 | `` | 0 |
| `volume_state` | `TEXT` | 0 | `` | 0 |
| `recommendation` | `TEXT` | 0 | `` | 0 |
| `thesis_text` | `TEXT` | 0 | `` | 0 |
| `entry_zone` | `TEXT` | 0 | `` | 0 |
| `stop_level` | `TEXT` | 0 | `` | 0 |
| `target_1` | `TEXT` | 0 | `` | 0 |
| `target_2` | `TEXT` | 0 | `` | 0 |
| `expected_hold_period` | `TEXT` | 0 | `` | 0 |
| `position_size_dollars` | `REAL` | 0 | `` | 0 |
| `position_size_pct` | `REAL` | 0 | `` | 0 |
| `estimated_dollar_risk` | `REAL` | 0 | `` | 0 |
| `reasons_to_trade` | `TEXT` | 0 | `` | 0 |
| `reasons_to_pass` | `TEXT` | 0 | `` | 0 |
| `earnings_date` | `TEXT` | 0 | `` | 0 |
| `event_risk_flag` | `TEXT` | 0 | `` | 0 |
| `hold_window_overlaps_earnings` | `INTEGER` | 0 | `` | 0 |
| `event_risk_warning_text` | `TEXT` | 0 | `` | 0 |
| `conservative_sizing_applied` | `INTEGER` | 0 | `` | 0 |
| `packet_sent` | `INTEGER` | 0 | `` | 0 |
| `packet_sent_at` | `TEXT` | 0 | `` | 0 |
| `ryan_approved` | `INTEGER` | 0 | `` | 0 |
| `ryan_executed` | `INTEGER` | 0 | `` | 0 |
| `ryan_notes` | `TEXT` | 0 | `` | 0 |
| `shadow_entry_price` | `REAL` | 0 | `` | 0 |
| `shadow_entry_time` | `TEXT` | 0 | `` | 0 |
| `shadow_exit_price` | `REAL` | 0 | `` | 0 |
| `shadow_exit_time` | `TEXT` | 0 | `` | 0 |
| `shadow_pnl_dollars` | `REAL` | 0 | `` | 0 |
| `shadow_pnl_pct` | `REAL` | 0 | `` | 0 |
| `max_favorable_excursion` | `REAL` | 0 | `` | 0 |
| `max_adverse_excursion` | `REAL` | 0 | `` | 0 |
| `shadow_duration_days` | `REAL` | 0 | `` | 0 |
| `thesis_success` | `INTEGER` | 0 | `` | 0 |
| `assistant_postmortem` | `TEXT` | 0 | `` | 0 |
| `lesson_tag` | `TEXT` | 0 | `` | 0 |
| `user_grade` | `TEXT` | 0 | `` | 0 |
| `repeatable_setup` | `INTEGER` | 0 | `` | 0 |
| `model_version` | `TEXT` | 0 | `` | 0 |
| `enriched_prompt` | `TEXT` | 0 | `` | 0 |
| `llm_conviction` | `INTEGER` | 0 | `` | 0 |
| `llm_conviction_reason` | `TEXT` | 0 | `` | 0 |

Indexes:
- `idx_recommendations_created_at` (NON-UNIQUE, c): `created_at`
- `idx_recommendations_ticker` (NON-UNIQUE, c): `ticker`
- `sqlite_autoindex_recommendations_1` (UNIQUE, pk): `recommendation_id`

## Table: `research_digests`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `week_start` | `TEXT` | 1 | `` | 0 |
| `week_end` | `TEXT` | 1 | `` | 0 |
| `papers_reviewed` | `INTEGER` | 0 | `` | 0 |
| `actionable_count` | `INTEGER` | 0 | `` | 0 |
| `digest_text` | `TEXT` | 0 | `` | 0 |
| `threats` | `TEXT` | 0 | `` | 0 |
| `opportunities` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- None

## Table: `research_docs`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `TEXT` | 0 | `` | 1 |
| `filename` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 0 | `` | 0 |
| `category` | `TEXT` | 0 | `` | 0 |
| `content` | `TEXT` | 0 | `` | 0 |
| `size_kb` | `REAL` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |

Indexes:
- `sqlite_autoindex_research_docs_1` (UNIQUE, pk): `id`

## Table: `research_papers`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `source` | `TEXT` | 1 | `` | 0 |
| `external_id` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 1 | `` | 0 |
| `authors` | `TEXT` | 0 | `` | 0 |
| `abstract` | `TEXT` | 0 | `` | 0 |
| `url` | `TEXT` | 1 | `` | 0 |
| `published_date` | `TEXT` | 0 | `` | 0 |
| `categories` | `TEXT` | 0 | `` | 0 |
| `relevance_score` | `REAL` | 0 | `` | 0 |
| `relevance_reason` | `TEXT` | 0 | `` | 0 |
| `full_text` | `TEXT` | 0 | `` | 0 |
| `actionable` | `INTEGER` | 0 | `0` | 0 |
| `action_taken` | `TEXT` | 0 | `` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `sqlite_autoindex_research_papers_1` (UNIQUE, u): `external_id`

## Table: `scan_metrics`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `scan_number` | `INTEGER` | 0 | `` | 0 |
| `scan_time` | `TEXT` | 0 | `` | 0 |
| `universe_count` | `INTEGER` | 0 | `` | 0 |
| `features_count` | `INTEGER` | 0 | `` | 0 |
| `scored_count` | `INTEGER` | 0 | `` | 0 |
| `packet_worthy` | `INTEGER` | 0 | `` | 0 |
| `risk_passed` | `INTEGER` | 0 | `` | 0 |
| `paper_traded` | `INTEGER` | 0 | `` | 0 |
| `live_traded` | `INTEGER` | 0 | `` | 0 |
| `llm_success` | `INTEGER` | 0 | `` | 0 |
| `llm_total` | `INTEGER` | 0 | `` | 0 |
| `llm_fallback` | `INTEGER` | 0 | `` | 0 |
| `avg_conviction` | `REAL` | 0 | `` | 0 |
| `duration_seconds` | `REAL` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |

Indexes:
- None

## Table: `schedule_metrics`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `metric_date` | `TEXT` | 0 | `` | 0 |
| `metric_name` | `TEXT` | 0 | `` | 0 |
| `metric_value` | `REAL` | 0 | `` | 0 |
| `details` | `TEXT` | 0 | `` | 0 |

Indexes:
- None

## Table: `setup_signals`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `signal_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `date` | `TEXT` | 1 | `` | 0 |
| `setup_type` | `TEXT` | 1 | `` | 0 |
| `confidence` | `REAL` | 0 | `` | 0 |
| `theoretical_entry` | `REAL` | 0 | `` | 0 |
| `theoretical_stop` | `REAL` | 0 | `` | 0 |
| `theoretical_target` | `REAL` | 0 | `` | 0 |
| `regime` | `TEXT` | 0 | `` | 0 |
| `adx` | `REAL` | 0 | `` | 0 |
| `atr_ratio` | `REAL` | 0 | `` | 0 |
| `rsi` | `REAL` | 0 | `` | 0 |
| `volume_profile` | `TEXT` | 0 | `` | 0 |
| `actual_return_1d` | `REAL` | 0 | `` | 0 |
| `actual_return_5d` | `REAL` | 0 | `` | 0 |
| `actual_return_10d` | `REAL` | 0 | `` | 0 |
| `actual_return_20d` | `REAL` | 0 | `` | 0 |
| `was_traded` | `INTEGER` | 0 | `0` | 0 |

Indexes:
- `sqlite_autoindex_setup_signals_1` (UNIQUE, pk): `signal_id`

## Table: `shadow_trades`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `trade_id` | `TEXT` | 0 | `` | 1 |
| `recommendation_id` | `TEXT` | 0 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `direction` | `TEXT` | 0 | `'long'` | 0 |
| `status` | `TEXT` | 0 | `'pending'` | 0 |
| `entry_price` | `REAL` | 0 | `` | 0 |
| `stop_price` | `REAL` | 0 | `` | 0 |
| `target_1` | `REAL` | 0 | `` | 0 |
| `target_2` | `REAL` | 0 | `` | 0 |
| `planned_shares` | `INTEGER` | 0 | `` | 0 |
| `planned_allocation` | `REAL` | 0 | `` | 0 |
| `actual_entry_price` | `REAL` | 0 | `` | 0 |
| `actual_entry_time` | `TEXT` | 0 | `` | 0 |
| `actual_exit_price` | `REAL` | 0 | `` | 0 |
| `actual_exit_time` | `TEXT` | 0 | `` | 0 |
| `exit_reason` | `TEXT` | 0 | `` | 0 |
| `pnl_dollars` | `REAL` | 0 | `` | 0 |
| `pnl_pct` | `REAL` | 0 | `` | 0 |
| `max_favorable_excursion` | `REAL` | 0 | `` | 0 |
| `max_adverse_excursion` | `REAL` | 0 | `` | 0 |
| `duration_days` | `INTEGER` | 0 | `` | 0 |
| `earnings_adjacent` | `INTEGER` | 0 | `0` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `updated_at` | `TEXT` | 1 | `` | 0 |
| `alpaca_order_id` | `TEXT` | 0 | `` | 0 |
| `order_type` | `TEXT` | 0 | `` | 0 |
| `source` | `TEXT` | 0 | `'paper'` | 0 |
| `signal_entry_price` | `REAL` | 0 | `` | 0 |
| `fill_entry_price` | `REAL` | 0 | `` | 0 |
| `entry_slippage_bps` | `REAL` | 0 | `` | 0 |
| `signal_exit_price` | `REAL` | 0 | `` | 0 |
| `fill_exit_price` | `REAL` | 0 | `` | 0 |
| `exit_slippage_bps` | `REAL` | 0 | `` | 0 |
| `signal_price` | `REAL` | 0 | `` | 0 |
| `implementation_shortfall_bps` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_shadow_trades_status_exit` (NON-UNIQUE, c): `status`, `actual_exit_time`
- `idx_shadow_trades_created_at` (NON-UNIQUE, c): `created_at`
- `idx_shadow_trades_recommendation_id` (NON-UNIQUE, c): `recommendation_id`
- `idx_shadow_trades_ticker` (NON-UNIQUE, c): `ticker`
- `idx_shadow_trades_status` (NON-UNIQUE, c): `status`
- `sqlite_autoindex_shadow_trades_1` (UNIQUE, pk): `trade_id`

## Table: `short_interest`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `settlement_date` | `TEXT` | 0 | `` | 0 |
| `short_interest` | `INTEGER` | 0 | `` | 0 |
| `avg_daily_volume` | `INTEGER` | 0 | `` | 0 |
| `days_to_cover` | `REAL` | 0 | `` | 0 |
| `short_pct_float` | `REAL` | 0 | `` | 0 |
| `source` | `TEXT` | 0 | `` | 0 |
| `collected_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- None

## Table: `sync_state`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `table_name` | `TEXT` | 0 | `` | 1 |
| `last_synced_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `sqlite_autoindex_sync_state_1` (UNIQUE, pk): `table_name`

## Table: `traffic_light_state`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `current_regime` | `TEXT` | 1 | `'GREEN'` | 0 |
| `pending_regime` | `TEXT` | 0 | `` | 0 |
| `pending_count` | `INTEGER` | 0 | `0` | 0 |
| `last_vix_score` | `INTEGER` | 0 | `0` | 0 |
| `last_trend_score` | `INTEGER` | 0 | `0` | 0 |
| `last_credit_score` | `INTEGER` | 0 | `0` | 0 |
| `last_total_score` | `INTEGER` | 0 | `0` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |

Indexes:
- None

## Table: `training_examples`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `example_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `source` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 0 | `` | 0 |
| `recommendation_id` | `TEXT` | 0 | `` | 0 |
| `feature_snapshot` | `TEXT` | 0 | `` | 0 |
| `trade_outcome` | `TEXT` | 0 | `` | 0 |
| `instruction` | `TEXT` | 1 | `` | 0 |
| `input_text` | `TEXT` | 1 | `` | 0 |
| `output_text` | `TEXT` | 1 | `` | 0 |
| `quality_score` | `REAL` | 0 | `` | 0 |
| `difficulty` | `TEXT` | 0 | `` | 0 |
| `curriculum_stage` | `TEXT` | 0 | `` | 0 |
| `quality_score_auto` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_training_examples_recommendation_id` (NON-UNIQUE, c): `recommendation_id`
- `idx_training_examples_created_at` (NON-UNIQUE, c): `created_at`
- `idx_training_examples_ticker` (NON-UNIQUE, c): `ticker`
- `idx_training_examples_source` (NON-UNIQUE, c): `source`
- `sqlite_autoindex_training_examples_1` (UNIQUE, pk): `example_id`

## Table: `user_notes`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `note_id` | `TEXT` | 0 | `` | 1 |
| `title` | `TEXT` | 1 | `` | 0 |
| `content` | `TEXT` | 0 | `''` | 0 |
| `tags` | `TEXT` | 0 | `'[]'` | 0 |
| `pinned` | `INTEGER` | 0 | `0` | 0 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `updated_at` | `TEXT` | 1 | `` | 0 |

Indexes:
- `sqlite_autoindex_user_notes_1` (UNIQUE, pk): `note_id`

## Table: `validation_results`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `result_id` | `TEXT` | 0 | `` | 1 |
| `created_at` | `TEXT` | 1 | `` | 0 |
| `overall_status` | `TEXT` | 1 | `` | 0 |
| `checks_passed` | `INTEGER` | 1 | `` | 0 |
| `checks_failed` | `INTEGER` | 1 | `` | 0 |
| `checks_warning` | `INTEGER` | 1 | `` | 0 |
| `results_json` | `TEXT` | 1 | `` | 0 |

Indexes:
- `sqlite_autoindex_validation_results_1` (UNIQUE, pk): `result_id`

## Table: `vix_term_structure`

| Column | Type | Not Null | Default | PK |
|---|---|---:|---|---:|
| `id` | `INTEGER` | 0 | `` | 1 |
| `collected_at` | `TEXT` | 1 | `` | 0 |
| `collected_date` | `TEXT` | 1 | `` | 0 |
| `vix` | `REAL` | 0 | `` | 0 |
| `vix9d` | `REAL` | 0 | `` | 0 |
| `vix3m` | `REAL` | 0 | `` | 0 |
| `vix1y` | `REAL` | 0 | `` | 0 |
| `term_structure_slope` | `REAL` | 0 | `` | 0 |
| `near_term_ratio` | `REAL` | 0 | `` | 0 |

Indexes:
- `idx_vix_ts_date` (NON-UNIQUE, c): `collected_date`


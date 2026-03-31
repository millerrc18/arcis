<!-- Counts verified 2026-03-30: 138 src modules (registered), 77 test files, 1045 tests, 53 CLI commands, 13 dashboard pages, 59 research docs. Guardrails: 15 oversized files, 127 oversized functions, 0 missing docstrings, 11 missing migrate tables (all grandfathered). -->

# AGENTS.md — Halcyon Lab Governance Document

## Purpose

Halcyon Lab is an autonomous AI trading system that scans, analyzes, and executes equity trades. It combines systematic technical scoring with LLM-generated institutional-quality trade commentary, multi-source data enrichment, bracket orders via Alpaca, a risk governor with kill switch, and a self-improving training pipeline with quality gates.

**Core Principle:** Training data quality is our #1 competitive advantage. Never sacrifice quality for speed.

**Business Model:** Investing returns, not newsletter. Scale by growing capital under management. Family LP structure planned for external capital.

**Long-term Goal:** Quantitatively be the best AI autonomous trading platform with an unbeatable technological moat.

## Current System State

The system is live in **bootcamp mode** — shadow paper trading on Alpaca with halcyon-v1 (fine-tuned Qwen3 8B). Full data enrichment, bracket orders, risk governor, daily/weekly auditor, validation holdout, A/B model evaluation, learned confidence, walk-forward backtesting, 24/7 compute scheduler (73% GPU target), comprehensive data collection pipeline, Telegram push notifications, and a 13-page web dashboard (including Notes, Council, Health, Live Ledger, and System Validation).

**Active Model:** halcyon-v1 (Qwen3 8B fine-tuned on 790 examples via QLoRA)
**Training Data:** 976 self-blinded examples, scored with process-first rubric
**Universe:** S&P 100 (expanding to ~325 stocks in Phase 2)

---

## Module Registry

138 modules across 26 directories (+ root). Each entry lists purpose, call graph edges, owned tables, config keys, and test coverage.

### src/api/

#### src/api/app.py
- **Purpose:** FastAPI application for the Halcyon Lab dashboard.
- **Called by:** none (entry point)
- **Calls:** api.routes, api.websocket, journal.store, log_config
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/cloud_app.py
- **Purpose:** Stripped-down read-only FastAPI for Render cloud deployment.
- **Called by:** none (entry point)
- **Calls:** api.cloud_routes.analytics, api.cloud_routes.core, api.cloud_routes.council, api.cloud_routes.notes, api.cloud_routes.trades, api.cloud_routes.training, sync.render_sync
- **Owns tables:** user_notes
- **Config keys:** none
- **Tests:** tests/test_cloud_app.py, tests/test_cloud_auth.py

#### src/api/websocket.py
- **Purpose:** WebSocket live update manager for the dashboard.
- **Called by:** api.app, api.routes.actions, scheduler.watch
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_websocket.py

### src/api/cloud_routes/

#### src/api/cloud_routes/analytics.py
- **Purpose:** Cloud analytics routes and helpers for HSHS and CTO reporting.
- **Called by:** api.cloud_app
- **Calls:** evaluation.hshs_live
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/cloud_routes/core.py
- **Purpose:** Cloud core routes for auth, status, config, and actions.
- **Called by:** api.cloud_app
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/cloud_routes/council.py
- **Purpose:** Cloud council and activity routes for session review pages.
- **Called by:** api.cloud_app
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/cloud_routes/notes.py
- **Purpose:** Cloud notes routes and payload models for the Notes dashboard.
- **Called by:** api.cloud_app
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/cloud_routes/trades.py
- **Purpose:** Cloud trade and market routes for packets, journals, and ledgers.
- **Called by:** api.cloud_app
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/cloud_routes/training.py
- **Purpose:** Cloud research, training, and data-surface routes.
- **Called by:** api.cloud_app
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

### src/api/routes/

#### src/api/routes/actions.py
- **Purpose:** Action endpoints for triggering system operations from the dashboard.
- **Called by:** api.app
- **Calls:** api.websocket, config, data_collection.cboe_collector, data_collection.macro_collector, data_collection.options_collector, data_collection.options_metrics, data_collection.trends_collector, data_collection.vix_collector, evaluation.cto_report, services.scan_service, training.curriculum, training.data_collector, training.leakage_detector, training.quality_filter, training.trainer, universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/routes/docs.py
- **Purpose:** Documentation API routes.
- **Called by:** api.app
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/routes/packets.py
- **Purpose:** Packets API routes.
- **Called by:** api.app
- **Calls:** journal.store
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_local_api_routes.py

#### src/api/routes/review.py
- **Purpose:** Review API routes.
- **Called by:** api.app
- **Calls:** services.review_service
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_local_api_routes.py

#### src/api/routes/scan.py
- **Purpose:** Scan API routes.
- **Called by:** api.app
- **Calls:** config, services.recap_service, services.scan_service, services.watchlist_service
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_local_api_routes.py

#### src/api/routes/shadow.py
- **Purpose:** Shadow trading API routes.
- **Called by:** api.app
- **Calls:** config, journal.store, services.shadow_service, shadow_trading.executor
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/routes/system.py
- **Purpose:** System API routes.
- **Called by:** api.app
- **Calls:** config, evaluation.cto_report, evaluation.system_validator, journal.store, logging.activity, risk.governor, scheduler.metrics, services.system_service, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/api/routes/training.py
- **Purpose:** Training API routes.
- **Called by:** api.app
- **Calls:** services.training_service
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_local_api_routes.py

### src/cli/

#### src/cli/commands.py
- **Purpose:** CLI command implementations for Halcyon Lab.
- **Called by:** main
- **Calls:** config, council.engine, data_collection.cboe_collector, data_collection.macro_collector, data_collection.options_collector, data_collection.options_metrics, data_collection.trends_collector, data_collection.vix_collector, data_ingestion.market_data, email.notifier, evaluation.backtester, evaluation.cto_report, evaluation.feature_importance, evaluation.gate_evaluator, evaluation.system_validator, journal.store, notifications.telegram, packets.template, risk.governor, scheduler.watch, services.recap_service, services.review_service, services.scan_service, services.shadow_service, services.system_service, services.training_service, services.watchlist_service, shadow_trading.alpaca_adapter, shadow_trading.executor, shadow_trading.reconcile, training.ab_evaluation, training.backfill, training.bootstrap, training.curriculum, training.dpo_pipeline, training.leakage_detector, training.quality_filter, training.trainer, training.validation, training.versioning, universe.sp100
- **Owns tables:** none
- **Config keys:** enabled, live_trading, shadow_trading, starting_capital
- **Tests:** none

### src/council/

#### src/council/agent_data.py
- **Purpose:** Council agent data gathering from repo-native tables.
- **Called by:** council.agents
- **Calls:** evaluation.hshs_live
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/agents.py
- **Purpose:** AI Council agent registry and public exports.
- **Called by:** council.context, council.protocol
- **Calls:** council.agent_data, council.prompts
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_council.py

#### src/council/aggregation.py
- **Purpose:** Council vote aggregation and backward-compat tallies.
- **Called by:** council.protocol
- **Calls:** council.constants
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/constants.py
- **Purpose:** Council protocol constants and thresholds.
- **Called by:** council.aggregation, council.engine, council.parsing, council.protocol, council.rate_limiter, council.value_tracker
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/context.py
- **Purpose:** Shared council context assembly from current repo schemas.
- **Called by:** council.protocol
- **Calls:** council.agents, evaluation.hshs_live
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/engine.py
- **Purpose:** Council Engine v2 -- vote-first Modified Delphi sessions.
- **Called by:** cli.commands, notifications.telegram, scheduler.watch
- **Calls:** council.constants, council.protocol, council.value_tracker
- **Owns tables:** council_sessions, council_votes, council_calibrations, council_debug_log
- **Config keys:** none
- **Tests:** tests/test_council.py

#### src/council/parsing.py
- **Purpose:** Council response parsing and normalization.
- **Called by:** council.protocol
- **Calls:** council.constants
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/prompts.py
- **Purpose:** Council agent system prompts and names.
- **Called by:** council.agents
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/protocol.py
- **Purpose:** Council protocol orchestration for vote-first sessions.
- **Called by:** council.engine
- **Calls:** council.agents, council.aggregation, council.constants, council.context, council.parsing, council.rate_limiter, training.claude_client
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_council.py

#### src/council/rate_limiter.py
- **Purpose:** Council parameter rate-limiting logic.
- **Called by:** council.protocol
- **Calls:** council.constants
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/council/value_tracker.py
- **Purpose:** Council value tracking -- counterfactual P&L computation.
- **Called by:** council.engine
- **Calls:** council.constants
- **Owns tables:** council_parameter_log, council_parameter_state
- **Config keys:** none
- **Tests:** none

### src/data_collection/

#### src/data_collection/analyst_collector.py
- **Purpose:** Analyst estimates and price target collector via Finnhub.
- **Called by:** scheduler.watch
- **Calls:** config
- **Owns tables:** analyst_estimates
- **Config keys:** data_enrichment
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/cboe_collector.py
- **Purpose:** CBOE Put/Call ratio collector.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch
- **Calls:** none
- **Owns tables:** cboe_ratios
- **Config keys:** none
- **Tests:** none

#### src/data_collection/docs_collector.py
- **Purpose:** Collect markdown documentation files into research_docs SQLite table for cloud sync.
- **Called by:** scheduler.watch
- **Calls:** none
- **Owns tables:** research_docs
- **Config keys:** none
- **Tests:** tests/test_docs_collector.py

#### src/data_collection/edgar_collector.py
- **Purpose:** SEC EDGAR filing collector.
- **Called by:** scheduler.watch
- **Calls:** features.filing_nlp
- **Owns tables:** edgar_filings
- **Config keys:** none
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/fed_collector.py
- **Purpose:** FOMC & Fed communications collector.
- **Called by:** scheduler.watch
- **Calls:** none
- **Owns tables:** fed_communications
- **Config keys:** none
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/insider_collector.py
- **Purpose:** SEC insider transactions collector via Finnhub.
- **Called by:** scheduler.watch
- **Calls:** config
- **Owns tables:** insider_transactions
- **Config keys:** data_enrichment
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/macro_collector.py
- **Purpose:** Expanded FRED macro indicator collector.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch
- **Calls:** config
- **Owns tables:** macro_snapshots
- **Config keys:** data_enrichment, fred, fred_api_key
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/options_collector.py
- **Purpose:** EOD options chain snapshot collector via yfinance.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch
- **Calls:** universe.sp100
- **Owns tables:** options_chains
- **Config keys:** none
- **Tests:** none

#### src/data_collection/options_metrics.py
- **Purpose:** Derived per-ticker options metrics computed from raw chain snapshots.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch
- **Calls:** none
- **Owns tables:** options_metrics
- **Config keys:** none
- **Tests:** none

#### src/data_collection/research_collector.py
- **Purpose:** Research intelligence collector -- discovers and scores papers/posts nightly.
- **Called by:** scheduler.watch
- **Calls:** data_collection.research_sources, llm.client
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/data_collection/research_sources.py
- **Purpose:** Research source crawlers for nightly paper collection.
- **Called by:** data_collection.research_collector
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/data_collection/research_synthesizer.py
- **Purpose:** Weekly research intelligence synthesis via Claude API.
- **Called by:** scheduler.watch
- **Calls:** notifications.telegram
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/data_collection/short_interest_collector.py
- **Purpose:** FINRA short interest collector via Finnhub.
- **Called by:** scheduler.watch
- **Calls:** config
- **Owns tables:** short_interest
- **Config keys:** data_enrichment
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/trends_collector.py
- **Purpose:** Google Trends market-wide sentiment collector.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch
- **Calls:** none
- **Owns tables:** google_trends
- **Config keys:** none
- **Tests:** tests/test_data_collectors.py

#### src/data_collection/vix_collector.py
- **Purpose:** VIX term structure snapshot collector.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch
- **Calls:** none
- **Owns tables:** vix_term_structure
- **Config keys:** none
- **Tests:** none

### src/data_enrichment/

#### src/data_enrichment/earnings_signals.py
- **Purpose:** PEAD (Post-Earnings Announcement Drift) enrichment signals.
- **Called by:** data_enrichment.enricher
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_earnings_signals.py

#### src/data_enrichment/enricher.py
- **Purpose:** Data enrichment orchestrator.
- **Called by:** scheduler.watch, services.scan_service
- **Calls:** data_enrichment.earnings_signals, data_enrichment.fundamentals, data_enrichment.insiders, data_enrichment.macro, data_enrichment.news
- **Owns tables:** none
- **Config keys:** cache_hours, data_enrichment, enabled, finnhub_api_key, fred_api_key, insider_lookback_days
- **Tests:** tests/test_enrichment.py

#### src/data_enrichment/fundamentals.py
- **Purpose:** SEC EDGAR fundamental data fetcher using XBRL API.
- **Called by:** data_enrichment.enricher
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_enrichment.py

#### src/data_enrichment/insiders.py
- **Purpose:** Insider trading data fetcher.
- **Called by:** data_enrichment.enricher
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_enrichment.py

#### src/data_enrichment/macro.py
- **Purpose:** Macroeconomic context from FRED API.
- **Called by:** data_enrichment.enricher
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_enrichment.py

#### src/data_enrichment/news.py
- **Purpose:** News data fetcher using Finnhub Company News API.
- **Called by:** data_enrichment.enricher, scheduler.premarket, scheduler.watch, training.historical_scanner
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_news.py

### src/data_ingestion/

#### src/data_ingestion/market_data.py
- **Purpose:** Market data ingestion via yfinance.
- **Called by:** cli.commands, evaluation.backtester, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, shadow_trading.executor, training.bootstrap
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_ingestion.py

### src/email/

#### src/email/digest_builder.py
- **Purpose:** Build fund-manager-style email digests for Halcyon Lab.
- **Called by:** scheduler.watch
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_digest_builder.py

#### src/email/notifier.py
- **Purpose:** SMTP email notifier for the AI Research Desk.
- **Called by:** cli.commands, evaluation.auditor, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service
- **Calls:** config
- **Owns tables:** none
- **Config keys:** cc_addresses, email, from_address, password, smtp_port, smtp_server, to_address, use_tls, username
- **Tests:** none

### src/evaluation/

#### src/evaluation/auditor.py
- **Purpose:** Daily and weekly auditor agent for risk monitoring.
- **Called by:** scheduler.watch
- **Calls:** config, email.notifier, evaluation.cto_report, risk.governor, training.claude_client, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_auditor.py

#### src/evaluation/backtester.py
- **Purpose:** Walk-forward model backtesting framework.
- **Called by:** cli.commands
- **Calls:** config, data_ingestion.market_data, features.engine, packets.template, ranking.ranker, shadow_trading.executor, training.backfill, universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_backtester.py

#### src/evaluation/change_detector.py
- **Purpose:** CUSUM (Cumulative Sum) performance change detection.
- **Called by:** scheduler.watch
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_change_detector.py

#### src/evaluation/cto_report.py
- **Purpose:** CTO performance report generator.
- **Called by:** api.routes.actions, api.routes.system, cli.commands, evaluation.auditor, scheduler.watch
- **Calls:** config, evaluation.feature_importance, evaluation.hshs_live, evaluation.metrics, journal.store, training.leakage_detector, training.validation, training.versioning, universe.sectors
- **Owns tables:** none
- **Config keys:** bootcamp, enabled, phase, risk
- **Tests:** tests/test_confidence.py, tests/test_cto_report.py

#### src/evaluation/feature_importance.py
- **Purpose:** Feature importance tracking with trend detection.
- **Called by:** cli.commands, evaluation.cto_report
- **Calls:** journal.store
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_feature_importance.py

#### src/evaluation/gate_evaluator.py
- **Purpose:** 50-trade gate evaluation for Phase 1 -> Phase 2 decision.
- **Called by:** cli.commands
- **Calls:** evaluation.statistics
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_gate_evaluator.py

#### src/evaluation/hshs.py
- **Purpose:** Halcyon System Health Score (HSHS) computation.
- **Called by:** evaluation.hshs_live
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_hshs.py

#### src/evaluation/hshs_live.py
- **Purpose:** Live HSHS computation from database state.
- **Called by:** api.cloud_routes.analytics, council.agent_data, council.context, evaluation.cto_report
- **Calls:** evaluation.hshs
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_hshs_live.py

#### src/evaluation/metrics.py
- **Purpose:** Trade performance metric helpers (expectancy, win rate).
- **Called by:** evaluation.cto_report, shadow_trading.metrics
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_metrics.py

#### src/evaluation/postmortem.py
- **Purpose:** Assistant postmortem generation for closed shadow trades.
- **Called by:** shadow_trading.executor
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_postmortem.py

#### src/evaluation/scorecard.py
- **Purpose:** Weekly and bootcamp scorecard generation.
- **Called by:** services.review_service
- **Calls:** journal.store, shadow_trading.metrics
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_scorecard.py

#### src/evaluation/statistics.py
- **Purpose:** Statistical validation functions for the walk-forward framework.
- **Called by:** evaluation.gate_evaluator
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_statistics.py

#### src/evaluation/system_validator.py
- **Purpose:** System validation engine for Halcyon Lab.
- **Called by:** api.routes.system, cli.commands, scheduler.watch
- **Calls:** config, risk.governor, shadow_trading.alpaca_adapter
- **Owns tables:** validation_results
- **Config keys:** alpaca, anthropic_api_key, api_key, api_secret, base_url, bot_token, chat_id, data_enrichment, database_url, email, enabled, finnhub_api_key, fred_api_key, live_trading, llm, max_positions, model, render, risk, risk_governor, secret_key, shadow_trading, smtp_server, telegram, timeout_days, training
- **Tests:** tests/test_system_validator.py

### src/features/

#### src/features/earnings.py
- **Purpose:** Earnings date lookup and event-risk classification.
- **Called by:** features.engine
- **Calls:** universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_earnings.py

#### src/features/engine.py
- **Purpose:** Feature engine for pullback-in-trend setup analysis.
- **Called by:** evaluation.backtester, features.regime, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.bootstrap, training.historical_scanner
- **Calls:** features.earnings, features.event_proximity, features.regime, features.setup_classifier, universe.sectors
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_features.py

#### src/features/event_proximity.py
- **Purpose:** Market event proximity features (FOMC, CPI, NFP, GDP).
- **Called by:** features.engine
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_event_proximity.py

#### src/features/event_risk_score.py
- **Purpose:** Event calendar risk scoring -- continuous 0-10 additive system.
- **Called by:** services.scan_service
- **Calls:** none
- **Owns tables:** none
- **Config keys:** block_threshold, sizing_floor
- **Tests:** tests/test_event_risk_score.py

#### src/features/filing_nlp.py
- **Purpose:** SEC filing NLP feature extraction.
- **Called by:** data_collection.edgar_collector
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_filing_nlp.py

#### src/features/regime.py
- **Purpose:** Market regime indicators: SPY trend, volatility, breadth, RSI, sector context.
- **Called by:** features.engine, ranking.ranker, scheduler.watch, training.historical_scanner
- **Calls:** features.engine, universe.sectors
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_regime.py

#### src/features/setup_classifier.py
- **Purpose:** Rule-based setup type classifier for equity trades.
- **Called by:** features.engine
- **Calls:** none
- **Owns tables:** setup_signals
- **Config keys:** none
- **Tests:** tests/test_setup_classifier.py

#### src/features/traffic_light.py
- **Purpose:** Traffic Light regime overlay -- controls position sizing.
- **Called by:** services.scan_service
- **Calls:** none
- **Owns tables:** traffic_light_state
- **Config keys:** none
- **Tests:** tests/test_traffic_light.py

### src/journal/

#### src/journal/store.py
- **Purpose:** SQLite journal storage for recommendations and shadow trades.
- **Called by:** api.app, api.routes.packets, api.routes.shadow, api.routes.system, cli.commands, evaluation.cto_report, evaluation.feature_importance, evaluation.scorecard, main, packets.eod_recap, risk.governor, scheduler.watch, services.recap_service, services.review_service, services.scan_service, services.shadow_service, shadow_trading.executor, shadow_trading.reconcile, training.versioning
- **Calls:** models
- **Owns tables:** recommendations, shadow_trades, validation_results
- **Config keys:** none
- **Tests:** tests/test_change_detector.py, tests/test_digest_builder.py, tests/test_gate_evaluator.py, tests/test_live_trading.py, tests/test_reconcile.py, tests/test_review.py, tests/test_scorecard.py

### src/llm/

#### src/llm/client.py
- **Purpose:** Ollama LLM client with graceful fallback.
- **Called by:** data_collection.research_collector, llm.packet_writer, llm.postmortem_writer, llm.watchlist_writer, scheduler.premarket, scheduler.scorer, scheduler.vram_manager, scheduler.watch, services.system_service, training.ab_evaluation, training.dpo_pipeline, training.trainer
- **Calls:** config, training.versioning
- **Owns tables:** none
- **Config keys:** base_url, enabled, llm, max_tokens, model, temperature, timeout_seconds
- **Tests:** tests/test_llm_client.py

#### src/llm/grammar_client.py
- **Purpose:** Grammar-constrained LLM client using llama-cpp-python with GBNF.
- **Called by:** llm.packet_writer
- **Calls:** config, training.versioning
- **Owns tables:** none
- **Config keys:** base_url, grammar_context_window, grammar_file, grammar_model_path, llm, model, model_file_path
- **Tests:** tests/test_grammar_client.py

#### src/llm/packet_writer.py
- **Purpose:** LLM-enhanced trade packet writer with template fallback.
- **Called by:** scheduler.watch, services.scan_service
- **Calls:** llm.client, llm.grammar_client, llm.prompts, models, strategy.canary, universe.company_names
- **Owns tables:** none
- **Config keys:** enabled, llm, max_tokens, temperature, use_grammar_enforcement
- **Tests:** tests/test_confidence.py, tests/test_grammar_client.py, tests/test_xml_format.py

#### src/llm/postmortem_writer.py
- **Purpose:** LLM-enhanced postmortem writer with template fallback.
- **Called by:** shadow_trading.executor
- **Calls:** config, llm.client, llm.prompts
- **Owns tables:** none
- **Config keys:** enabled, llm
- **Tests:** tests/test_llm_writers.py

#### src/llm/prompts.py
- **Purpose:** System prompts for LLM-enhanced output.
- **Called by:** llm.packet_writer, llm.postmortem_writer, llm.watchlist_writer, training.ab_evaluation, training.backfill, training.bootstrap, training.data_collector, training.historical_scanner
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_self_blinding.py

#### src/llm/validator.py
- **Purpose:** LLM output validation layer.
- **Called by:** shadow_trading.executor
- **Calls:** universe.sp100
- **Owns tables:** none
- **Config keys:** risk
- **Tests:** tests/test_llm_validator.py

#### src/llm/watchlist_writer.py
- **Purpose:** LLM-enhanced morning watchlist narrative writer.
- **Called by:** scheduler.watch, services.watchlist_service
- **Calls:** llm.client, llm.prompts
- **Owns tables:** none
- **Config keys:** enabled, llm
- **Tests:** tests/test_llm_writers.py

### src/logging/

#### src/logging/activity.py
- **Purpose:** Persistent activity logging for the Halcyon Lab system.
- **Called by:** api.routes.system, notifications.telegram, scheduler.watch
- **Calls:** none
- **Owns tables:** activity_log
- **Config keys:** none
- **Tests:** tests/test_activity_log.py

### src/notifications/

#### src/notifications/telegram.py
- **Purpose:** Telegram notification client for Halcyon Lab.
- **Called by:** cli.commands, data_collection.research_synthesizer, scheduler.watch, services.scan_service, shadow_trading.bracket_monitor, shadow_trading.executor, training.canary, training.ingestion_gate
- **Calls:** config, council.engine, logging.activity, training.versioning
- **Owns tables:** none
- **Config keys:** bot_token, chat_id, enabled, telegram
- **Tests:** tests/test_action_reminders.py, tests/test_expanded_notifications.py, tests/test_live_trading.py, tests/test_system_validator.py

### src/packets/

#### src/packets/eod_recap.py
- **Purpose:** End-of-day recap email formatter.
- **Called by:** scheduler.watch, services.recap_service
- **Calls:** config, journal.store, shadow_trading.executor, universe.company_names
- **Owns tables:** none
- **Config keys:** shadow_trading
- **Tests:** tests/test_packet_builders.py

#### src/packets/template.py
- **Purpose:** Build a real TradePacket from computed features and config.
- **Called by:** cli.commands, evaluation.backtester, scheduler.watch, services.scan_service
- **Calls:** models, universe.company_names
- **Owns tables:** none
- **Config keys:** planned_risk_pct_max, risk, starting_capital
- **Tests:** tests/test_packet_builders.py

#### src/packets/watchlist.py
- **Purpose:** Morning watchlist email formatter.
- **Called by:** scheduler.watch, services.watchlist_service
- **Calls:** universe.company_names
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_packet_builders.py

### src/ranking/

#### src/ranking/ranker.py
- **Purpose:** Deterministic ranking and qualification for trade candidates.
- **Called by:** evaluation.backtester, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.historical_scanner
- **Calls:** config, features.regime
- **Owns tables:** none
- **Config keys:** bootcamp, enabled, packet_worthy_threshold, qualification_threshold, ranking, regime_adaptive, watchlist_threshold
- **Tests:** tests/test_ranking.py, tests/test_regime.py

### src/risk/

#### src/risk/governor.py
- **Purpose:** Risk governor -- hard limits enforced before every trade.
- **Called by:** api.routes.system, cli.commands, evaluation.auditor, evaluation.system_validator, services.system_service, shadow_trading.executor
- **Calls:** config, journal.store, shadow_trading.alpaca_adapter, shadow_trading.executor, universe.sectors
- **Owns tables:** none
- **Config keys:** bootcamp, enabled, max_correlated, max_daily_loss_pct, max_open_positions, max_position_pct, max_sector_pct, risk, risk_governor, vol_halt_pct
- **Tests:** tests/test_auditor.py, tests/test_risk_governor.py

### src/scheduler/

#### src/scheduler/metrics.py
- **Purpose:** Schedule metrics tracking for the 24/7 compute scheduler.
- **Called by:** api.routes.system
- **Calls:** none
- **Owns tables:** schedule_metrics
- **Config keys:** none
- **Tests:** none

#### src/scheduler/premarket.py
- **Purpose:** Pre-market inference tasks that run after Ollama is loaded but before market opens.
- **Called by:** scheduler.watch
- **Calls:** config, data_enrichment.news, data_ingestion.market_data, features.engine, llm.client, ranking.ranker, training.versioning, universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_premarket.py

#### src/scheduler/scorer.py
- **Purpose:** Between-scan inference scoring using the already-loaded Ollama model.
- **Called by:** scheduler.watch
- **Calls:** llm.client, training.quality_filter, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_scorer.py

#### src/scheduler/vram_manager.py
- **Purpose:** VRAM transition management between Ollama inference and PyTorch training.
- **Called by:** scheduler.watch
- **Calls:** config, llm.client, training.versioning
- **Owns tables:** none
- **Config keys:** llm
- **Tests:** tests/test_vram_manager.py

#### src/scheduler/watch.py
- **Purpose:** Watch loop for automated daily cadence.
- **Called by:** cli.commands
- **Calls:** api.websocket, config, council.engine, data_collection.analyst_collector, data_collection.cboe_collector, data_collection.docs_collector, data_collection.edgar_collector, data_collection.fed_collector, data_collection.insider_collector, data_collection.macro_collector, data_collection.options_collector, data_collection.options_metrics, data_collection.research_collector, data_collection.research_synthesizer, data_collection.short_interest_collector, data_collection.trends_collector, data_collection.vix_collector, data_enrichment.enricher, data_enrichment.news, data_ingestion.market_data, email.digest_builder, email.notifier, evaluation.auditor, evaluation.change_detector, evaluation.cto_report, evaluation.system_validator, features.engine, features.regime, journal.store, llm.client, llm.packet_writer, llm.watchlist_writer, logging.activity, notifications.telegram, packets.eod_recap, packets.template, packets.watchlist, ranking.ranker, scheduler.premarket, scheduler.scorer, scheduler.vram_manager, shadow_trading.bracket_monitor, shadow_trading.executor, sync.render_sync, training.data_collector, training.leakage_detector, training.report, training.trainer, training.versioning, universe.sp100, utils.activity_logger
- **Owns tables:** activity_log, analyst_estimates, api_costs, canary_evaluations, council_calibrations, council_sessions, council_votes, edgar_filings, fed_communications, insider_transactions, quality_drift_metrics, research_digests, research_docs, research_papers, scan_metrics, schedule_metrics, setup_signals, short_interest, traffic_light_state, training_examples, user_notes
- **Config keys:** automation, bootcamp, email, email_mode, enabled, eod, eod_recap_hour_et, evening, live_trading, llm, market_close_hour_et, market_open_hour_et, market_open_minute_et, max_packets_per_scan, midday, morning_watchlist_hour_et, phase, premarket, risk, scan_interval_minutes, shadow_trading, training
- **Tests:** none

### src/services/

#### src/services/recap_service.py
- **Purpose:** EOD recap service.
- **Called by:** api.routes.scan, cli.commands
- **Calls:** data_ingestion.market_data, email.notifier, features.engine, journal.store, packets.eod_recap, ranking.ranker, universe.sp100
- **Owns tables:** none
- **Config keys:** shadow_trading
- **Tests:** tests/test_services.py

#### src/services/review_service.py
- **Purpose:** Review and evaluation service.
- **Called by:** api.routes.review, cli.commands
- **Calls:** evaluation.scorecard, journal.store
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_services.py

#### src/services/scan_service.py
- **Purpose:** Scan pipeline service.
- **Called by:** api.routes.actions, api.routes.scan, cli.commands
- **Calls:** data_enrichment.enricher, data_ingestion.market_data, data_integrity, email.notifier, features.engine, features.event_risk_score, features.traffic_light, journal.store, llm.packet_writer, notifications.telegram, packets.template, ranking.ranker, shadow_trading.executor, training.versioning, universe.company_names, universe.sp100
- **Owns tables:** none
- **Config keys:** enabled, event_risk, shadow_trading
- **Tests:** tests/test_services.py

#### src/services/shadow_service.py
- **Purpose:** Shadow trading service.
- **Called by:** api.routes.shadow, cli.commands
- **Calls:** journal.store, shadow_trading.alpaca_adapter, shadow_trading.executor, shadow_trading.metrics
- **Owns tables:** none
- **Config keys:** shadow_trading
- **Tests:** tests/test_services.py

#### src/services/system_service.py
- **Purpose:** System service for preflight checks and config management.
- **Called by:** api.routes.system, cli.commands
- **Calls:** llm.client, risk.governor, training.versioning
- **Owns tables:** none
- **Config keys:** alpaca, api_key, api_secret, base_url, bootcamp, bot_token, chat_id, email, enabled, live_trading, llm, model, password, phase, shadow_trading, smtp_server, telegram, training, username
- **Tests:** tests/test_services.py

#### src/services/training_service.py
- **Purpose:** Training pipeline service.
- **Called by:** api.routes.training, cli.commands
- **Calls:** training.bootstrap, training.report, training.trainer, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_services.py

#### src/services/watchlist_service.py
- **Purpose:** Morning watchlist service.
- **Called by:** api.routes.scan, cli.commands
- **Calls:** data_ingestion.market_data, email.notifier, features.engine, llm.watchlist_writer, packets.watchlist, ranking.ranker, universe.company_names, universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_services.py

### src/shadow_trading/

#### src/shadow_trading/alpaca_adapter.py
- **Purpose:** Alpaca paper trading adapter with safety guardrails.
- **Called by:** cli.commands, evaluation.system_validator, risk.governor, services.shadow_service, shadow_trading.bracket_monitor, shadow_trading.executor, shadow_trading.reconcile
- **Calls:** config
- **Owns tables:** none
- **Config keys:** alpaca, api_key, api_secret, base_url, default_order_type, enabled, live_trading, max_open_positions, max_positions, secret_key, shadow_trading, starting_capital, timeout_days
- **Tests:** tests/test_bracket_orders.py, tests/test_live_trading.py

#### src/shadow_trading/bracket_monitor.py
- **Purpose:** Bracket order health monitoring -- verifies stop/target legs are active.
- **Called by:** scheduler.watch
- **Calls:** notifications.telegram, shadow_trading.alpaca_adapter
- **Owns tables:** bracket_health
- **Config keys:** none
- **Tests:** tests/test_bracket_monitor.py

#### src/shadow_trading/executor.py
- **Purpose:** Shadow trade execution flow: entry and exit monitoring.
- **Called by:** api.routes.shadow, cli.commands, evaluation.backtester, packets.eod_recap, risk.governor, scheduler.watch, services.scan_service, services.shadow_service, shadow_trading.ledger
- **Calls:** config, data_ingestion.market_data, evaluation.postmortem, journal.store, llm.postmortem_writer, llm.validator, models, notifications.telegram, risk.governor, shadow_trading.alpaca_adapter, shadow_trading.models, utils.activity_logger
- **Owns tables:** none
- **Config keys:** bootcamp, enabled, live_trading, max_open_positions, max_positions, max_price, min_score, risk, shadow_trading, starting_capital, timeout_days
- **Tests:** tests/test_expanded_notifications.py, tests/test_live_trading.py

#### src/shadow_trading/ledger.py
- **Purpose:** Shadow trading ledger -- re-exports from executor for backwards compatibility.
- **Called by:** none
- **Calls:** shadow_trading.executor
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/shadow_trading/metrics.py
- **Purpose:** Shadow ledger performance metrics.
- **Called by:** evaluation.scorecard, services.shadow_service
- **Calls:** evaluation.metrics
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_shadow_metrics.py

#### src/shadow_trading/models.py
- **Purpose:** Shadow trade data model.
- **Called by:** shadow_trading.executor
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/shadow_trading/reconcile.py
- **Purpose:** Reconcile Alpaca live positions with shadow_trades database.
- **Called by:** cli.commands
- **Calls:** journal.store, shadow_trading.alpaca_adapter
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_reconcile.py

### src/strategy/

#### src/strategy/canary.py
- **Purpose:** Canary rules-based scoring -- a simple baseline to compare against the LLM.
- **Called by:** llm.packet_writer
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

### src/sync/

#### src/sync/render_sync.py
- **Purpose:** Background sync thread that pushes local SQLite data to Render Postgres.
- **Called by:** api.cloud_app, scheduler.watch
- **Calls:** none
- **Owns tables:** sync_state
- **Config keys:** database_url, enabled, mode, pk, render, sync_interval_seconds, time_col
- **Tests:** tests/test_data_collectors.py, tests/test_render_sync.py

### src/training/

#### src/training/ab_evaluation.py
- **Purpose:** A/B shadow model evaluation with promotion logic.
- **Called by:** cli.commands
- **Calls:** config, llm.client, llm.prompts, training.claude_client, training.versioning
- **Owns tables:** none
- **Config keys:** llm
- **Tests:** tests/test_ab_evaluation.py, tests/test_leakage_detector.py

#### src/training/backfill.py
- **Purpose:** Historical backfill orchestrator for high-quality training data generation.
- **Called by:** cli.commands, evaluation.backtester
- **Calls:** llm.prompts, training.claude_client, training.historical_data, training.historical_scanner, training.ingestion_gate, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_backfill.py, tests/test_leakage_detector.py

#### src/training/bootstrap.py
- **Purpose:** Synthetic training data bootstrapping via Claude API.
- **Called by:** cli.commands, services.training_service
- **Calls:** config, data_ingestion.market_data, features.engine, llm.prompts, training.claude_client, training.ingestion_gate, training.versioning, universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_leakage_detector.py, tests/test_training_data.py

#### src/training/canary.py
- **Purpose:** Canary monitoring for detecting model quality degradation.
- **Called by:** training.trainer
- **Calls:** notifications.telegram, training.claude_client, training.quality_drift
- **Owns tables:** canary_evaluations
- **Config keys:** none
- **Tests:** tests/test_canary.py, tests/test_leakage_detector.py

#### src/training/claude_client.py
- **Purpose:** Claude API client for generating training data.
- **Called by:** council.protocol, evaluation.auditor, training.ab_evaluation, training.backfill, training.bootstrap, training.canary, training.curriculum, training.data_collector, training.quality_filter, training.trainer
- **Calls:** config, training.versioning
- **Owns tables:** none
- **Config keys:** anthropic_api_key, api, training
- **Tests:** tests/test_leakage_detector.py

#### src/training/curriculum.py
- **Purpose:** Three-stage curriculum training with difficulty classification and contrastive pairs.
- **Called by:** api.routes.actions, cli.commands, training.trainer
- **Calls:** training.claude_client, training.ingestion_gate, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_curriculum.py, tests/test_leakage_detector.py

#### src/training/data_collector.py
- **Purpose:** Training data collection from closed trades using the self-blinding pipeline.
- **Called by:** api.routes.actions, scheduler.watch
- **Calls:** config, llm.prompts, training.claude_client, training.ingestion_gate, training.versioning
- **Owns tables:** none
- **Config keys:** enabled, training
- **Tests:** tests/test_leakage_detector.py, tests/test_self_blinding.py

#### src/training/dpo_pipeline.py
- **Purpose:** DPO preference pair generation and export pipeline.
- **Called by:** cli.commands, training.trainer
- **Calls:** llm.client, training.quality_filter, training.versioning
- **Owns tables:** preference_pairs
- **Config keys:** none
- **Tests:** tests/test_dpo_pipeline.py, tests/test_leakage_detector.py

#### src/training/historical_data.py
- **Purpose:** Historical data fetcher with point-in-time slicing for backfill engine.
- **Called by:** training.backfill, training.historical_scanner
- **Calls:** universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_backfill.py, tests/test_leakage_detector.py

#### src/training/historical_scanner.py
- **Purpose:** Historical scanner with outcome tracking and training example generation.
- **Called by:** training.backfill
- **Calls:** config, data_enrichment.news, features.engine, features.regime, llm.prompts, ranking.ranker, training.historical_data, universe.company_names
- **Owns tables:** none
- **Config keys:** data_enrichment, finnhub_api_key, include_news_in_backfill
- **Tests:** tests/test_backfill.py, tests/test_leakage_detector.py

#### src/training/ingestion_gate.py
- **Purpose:** Training data ingestion validation -- prevents format contamination.
- **Called by:** training.backfill, training.bootstrap, training.curriculum, training.data_collector
- **Calls:** notifications.telegram
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_ingestion_gate.py, tests/test_leakage_detector.py

#### src/training/leakage_detector.py
- **Purpose:** Outcome leakage detector for training data quality assurance.
- **Called by:** api.routes.actions, cli.commands, evaluation.cto_report, scheduler.watch
- **Calls:** universe.company_names, universe.sp100
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_leakage_detector.py

#### src/training/quality_drift.py
- **Purpose:** Quality drift metrics for monitoring model output degradation.
- **Called by:** training.canary
- **Calls:** none
- **Owns tables:** quality_drift_metrics
- **Config keys:** none
- **Tests:** tests/test_leakage_detector.py, tests/test_quality_drift.py

#### src/training/quality_filter.py
- **Purpose:** LLM-as-Judge quality scoring for training examples.
- **Called by:** api.routes.actions, cli.commands, scheduler.scorer, training.dpo_pipeline
- **Calls:** training.claude_client, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_leakage_detector.py, tests/test_quality_filter.py, tests/test_quality_rubric.py

#### src/training/report.py
- **Purpose:** Training progress report generator.
- **Called by:** scheduler.watch, services.training_service
- **Calls:** training.trainer, training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_leakage_detector.py

#### src/training/trainer.py
- **Purpose:** Fine-tuning orchestrator with Unsloth and auto-rollback.
- **Called by:** api.routes.actions, cli.commands, scheduler.watch, services.training_service, training.report
- **Calls:** config, llm.client, training.canary, training.claude_client, training.curriculum, training.dpo_pipeline, training.versioning
- **Owns tables:** none
- **Config keys:** auto_rollback_expectancy_drop, auto_rollback_winrate_drop, auto_train_min_examples, auto_train_threshold, auto_train_time_days, enabled, training
- **Tests:** tests/test_holdout.py, tests/test_leakage_detector.py, tests/test_trainer.py, tests/test_training_data.py

#### src/training/validation.py
- **Purpose:** Training dataset validation and quality checks.
- **Called by:** cli.commands, evaluation.cto_report
- **Calls:** training.versioning
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_leakage_detector.py, tests/test_validation.py

#### src/training/versioning.py
- **Purpose:** Model versioning and performance tracking for the training pipeline.
- **Called by:** api.routes.system, cli.commands, evaluation.auditor, evaluation.cto_report, llm.client, llm.grammar_client, notifications.telegram, scheduler.premarket, scheduler.scorer, scheduler.vram_manager, scheduler.watch, services.scan_service, services.system_service, services.training_service, training.ab_evaluation, training.backfill, training.bootstrap, training.claude_client, training.curriculum, training.data_collector, training.dpo_pipeline, training.quality_filter, training.report, training.trainer, training.validation
- **Calls:** journal.store
- **Owns tables:** api_costs, audit_reports, metric_snapshots, model_evaluations, model_versions, training_examples
- **Config keys:** none
- **Tests:** tests/test_ab_evaluation.py, tests/test_auditor.py, tests/test_dpo_pipeline.py, tests/test_holdout.py, tests/test_leakage_detector.py, tests/test_premarket.py, tests/test_scorer.py, tests/test_trainer.py, tests/test_training_data.py, tests/test_validation.py, tests/test_versioning.py

### src/universe/

#### src/universe/company_names.py
- **Purpose:** Static company name lookup for S&P 100 tickers.
- **Called by:** llm.packet_writer, packets.eod_recap, packets.template, packets.watchlist, services.scan_service, services.watchlist_service, training.historical_scanner, training.leakage_detector
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/universe/sectors.py
- **Purpose:** GICS sector mapping for S&P 100 constituents.
- **Called by:** evaluation.cto_report, features.engine, features.regime, risk.governor
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_regime.py

#### src/universe/sp100.py
- **Purpose:** S&P 100 (OEX) constituent universe.
- **Called by:** api.routes.actions, cli.commands, data_collection.options_collector, evaluation.backtester, features.earnings, llm.validator, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.bootstrap, training.historical_data, training.leakage_detector
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_regime.py, tests/test_universe.py

### src/utils/

#### src/utils/activity_logger.py
- **Purpose:** Structured activity logger for dashboard display and observability.
- **Called by:** scheduler.watch, shadow_trading.executor
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_activity_logger.py

### Root src/ files

#### src/config.py
- **Purpose:** Configuration loader for the AI Research Desk.
- **Called by:** api.routes.actions, api.routes.scan, api.routes.shadow, api.routes.system, cli.commands, data_collection.analyst_collector, data_collection.insider_collector, data_collection.macro_collector, data_collection.short_interest_collector, email.notifier, evaluation.auditor, evaluation.backtester, evaluation.cto_report, evaluation.system_validator, llm.client, llm.grammar_client, llm.postmortem_writer, main, notifications.telegram, packets.eod_recap, ranking.ranker, risk.governor, scheduler.premarket, scheduler.vram_manager, scheduler.watch, shadow_trading.alpaca_adapter, shadow_trading.executor, training.ab_evaluation, training.bootstrap, training.claude_client, training.data_collector, training.historical_scanner, training.trainer
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/data_integrity.py
- **Purpose:** Data integrity assertions for critical data boundaries.
- **Called by:** services.scan_service
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_data_integrity.py

#### src/log_config.py
- **Purpose:** Logging configuration for the Halcyon Lab system.
- **Called by:** api.app, main
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

#### src/main.py
- **Purpose:** Halcyon Lab CLI bootstrap and parser wiring.
- **Called by:** none (entry point)
- **Calls:** cli.commands, config, journal.store, log_config
- **Owns tables:** none
- **Config keys:** file, level, logging
- **Tests:** tests/test_live_trading.py, tests/test_main_refactor.py

#### src/models.py
- **Purpose:** Backward compatibility re-exports for TradePacket and PositionSizing.
- **Called by:** journal.store, llm.packet_writer, packets.template, shadow_trading.executor
- **Calls:** schemas
- **Owns tables:** none
- **Config keys:** none
- **Tests:** tests/test_grammar_client.py

#### src/schemas.py
- **Purpose:** Pydantic models for the Halcyon Lab system.
- **Called by:** models
- **Calls:** none
- **Owns tables:** none
- **Config keys:** none
- **Tests:** none

---

## Dependency Hierarchy

Imports only go DOWN. No module may import from a higher layer.

```
Layer 4: Orchestration
    watch.py, main.py

Layer 3: Services
    scan_service.py, council/engine.py, recap_service.py,
    review_service.py, shadow_service.py, training_service.py,
    watchlist_service.py, system_service.py

Layer 2: Domain
    executor.py, governor.py, traffic_light.py, features/engine.py,
    ranker.py, trainer.py, enricher.py

Layer 1: Infrastructure
    alpaca_adapter.py, telegram.py, render_sync.py, llm/client.py,
    config.py, journal/store.py
```

---

## Where New Things Go

| I need to... | Put it in... | Wire it into... |
|---|---|---|
| Add a feature/signal | `src/features/` | `scan_service.py` |
| Add a data collector | `src/data_collection/` | `watch.py` scheduler |
| Add an API endpoint | `src/api/cloud_routes/` | `cloud_app.py` router + `api.js` |
| Add a dashboard page | `frontend/src/pages/` | `App.jsx` routes + `Layout.jsx` nav |
| Add a DB table | `scripts/create_missing_tables.py` + `render_migrate.py` | `render_sync.py` |
| Add a notification | `src/notifications/telegram.py` | caller module |
| Add a CLI command | `src/cli/commands.py` | `main.py` subparser |
| Add a test | `tests/test_{module}.py` | auto-discovered |

---

## Data Sources (7+ enrichment, 12 collection)

### Enrichment (used in every scan)

1. **Technical Data** — Price, volume, moving averages, RSI, ATR, trend state, relative strength
2. **Market Regime** — SPY trend, volatility, breadth, drawdown, regime classification
3. **Sector Context** — Sector relative strength rank, sector average score
4. **Fundamental Snapshot** — SEC EDGAR: revenue, margins, PE, growth rates
5. **Insider Activity** — Finnhub: buy/sell transactions, sentiment classification
6. **Recent News** — Finnhub Company News: headlines, simple sentiment scoring
7. **Macro Context** — FRED: Fed Funds rate, yield curve, unemployment, CPI, GDP + 9 expanded series

### Data Collection (overnight pipeline — 12 collectors, irreplaceable daily snapshots)

1. **Options Chains** — Full EOD chain snapshots via yfinance (strikes, IV, Greeks, OI)
2. **Options Metrics** — Derived signals: IV rank, put/call ratios, IV skew, unusual activity
3. **VIX Term Structure** — VIX, VIX9D, VIX3M, VIX1Y + contango/backwardation classification
4. **CBOE Ratios** — Equity, index, and total put/call ratios
5. **FRED Macro (34+ series)** — Housing, employment, trade, consumer, financial conditions, plus original core
6. **Google Trends (market-wide)** — 8 sentiment terms: crash, recession, inflation, rates, bubble, correction
7. **Earnings Calendar** — Next earnings date for every ticker, flagging imminent reports
8. **SEC EDGAR Filings** — 10-K, 10-Q, 8-K filings with parsed sections (free, 10 req/sec)
9. **Insider Transactions** — Form 4 buy/sell data via Finnhub (nightly)
10. **Short Interest** — FINRA short interest snapshots via Finnhub (biweekly)
11. **Fed Communications** — FOMC statements, minutes, Beige Book, speeches (scraped from federalreserve.gov)
12. **Analyst Estimates** — Consensus recommendations + price targets via Finnhub (batched 20/night)

## Execution

- **Bracket Orders**: Entry + stop-loss + take-profit via Alpaca paper trading
- **Risk Governor**: 8 checks (emergency halt, daily loss, position size, max positions, sector concentration, correlation, volatility halt, duplicate check)
- **Kill Switch**: `halt-trading` command or dashboard button halts all new positions immediately

## Training Pipeline

1. **Self-Blinding Generation**: Claude generates commentary WITHOUT seeing outcomes (2-stage pipeline)
2. **Process-First Quality Scoring**: LLM-as-judge scores 6 dimensions, blind to trade outcome
3. **Outcome Leakage Detection**: Balanced accuracy classifier verifies pipeline integrity
4. **Curriculum Classification**: Easy/medium/hard difficulty → 3-stage curriculum
5. **SFT Training**: Three-stage curriculum with decreasing learning rates (PEFT + TRL 0.24)
6. **Preference Pair Generation / RL Prep**: Preference exports retained, but the planned post-SFT refinement path is Dr. GRPO rather than DPO
7. **Holdout Validation**: 15% chronological holdout with 5-day temporal gap
8. **A/B Shadow Evaluation**: New model runs alongside current model
9. **Auto-Rollback**: Performance regression triggers automatic rollback

## 24/7 Compute Schedule

**Target: 73% GPU utilization** (inference ≤30%, training ≤45%, slack ≥25%)

| Time (ET)       | Task                                                         | GPU Mode         |
| --------------- | ------------------------------------------------------------ | ---------------- |
| 5:15 AM         | Morning VRAM handoff (training → Ollama)                     | Transition       |
| 5:30 AM         | Post-close capture (MFE/MAE update, regime logging)          | Inference        |
| 6:00 AM         | Pre-market refresh + rolling feature computation             | CPU + Inference  |
| 7:00 AM         | Self-blinded training data generation (historical)           | Inference        |
| 8:00 AM         | Morning watchlist                                            | Inference        |
| 8:02 AM         | Overnight news scoring + sentiment analysis                  | Inference        |
| 9:00 AM         | Pre-market candidate analysis                                | Inference        |
| 9:25 AM         | Guard band — verify model warm                               | Idle             |
| 9:30 AM–4:00 PM | Market scans (every 30 min) + between-scan scoring           | Inference        |
| 4:00 PM         | EOD recap + daily P&L                                        | CPU + Inference  |
| 4:15 PM         | Training data scoring (LLM-as-judge, ~50 examples)           | Inference        |
| 5:30 PM         | Post-close capture                                           | CPU              |
| 6:00 PM         | Training data collection from closed trades                  | CPU              |
| 6:45 PM         | Preference pair generation / RL prep                         | Inference        |
| 6:50 PM         | Evening VRAM handoff (Ollama → training subprocess)          | Transition       |
| 7:00 PM         | Walk-forward backtesting                                     | Training         |
| 9:30 PM         | Data collection (12 collectors: options, VIX, FRED 34+, trends, CBOE, earnings, EDGAR, insider, short interest, Fed, analyst) | CPU (concurrent) |
| 10:00 PM        | News ingestion (full universe)                               | CPU (concurrent) |
| 11:00 PM        | Enrichment pre-cache                                         | CPU (concurrent) |
| 11:05 PM        | Auxiliary model training (regime classifier)                 | Training         |
| 1:00 AM         | Feature importance computation                               | Training         |
| 2:30 AM         | Leakage detector with model probing                          | Training         |
| 4:30 AM         | DB maintenance, health checks, backups                       | CPU              |

## Dashboard Pages (13)

- **Dashboard** — KPIs, cumulative P&L, open trades, action buttons, live activity feed
- **Packets** — Trade recommendations with expandable analysis
- **Shadow Ledger** — Open/closed trades with account summary
- **Live Ledger** — Live-trading account summary and history
- **Training** — Pipeline status, version history, action buttons
- **Council** — Vote-first sessions, agent votes, and parameter adjustments
- **Health** — HSHS composite score, radar chart, and live phase weights
- **Validation** — System validation checks and reliability signals
- **CTO Report** — Performance analytics, fund metrics, metric trends
- **Settings** — Configuration, API costs, data collection stats, system health
- **Roadmap** — 6-phase plan with confirmed decision tracking
- **Docs** — 59 research documents plus core governance docs
- **Notes** — Operator notes with pinning, tags, and autosave editing

## CLI Commands (53)

See docs/cli-reference.md for full documentation with options and descriptions.

### Core Pipeline (8)

`init-db`, `demo-packet`, `send-test-email`, `send-test-telegram`, `ingest`, `scan`, `morning-watchlist`, `eod-recap`

### Shadow Trading (4)

`shadow-status`, `shadow-history`, `shadow-close`, `shadow-account`

### Live Trading (4)

`live-status`, `live-history`, `live-close`, `reconcile-live`

### Review & Analysis (6)

`review`, `mark-executed`, `review-scorecard`, `review-bootcamp`, `postmortems`, `postmortem`

### Training — Data (5)

`training-status`, `training-history`, `training-report`, `bootstrap-training`, `backfill-training`

### Training — Quality (5)

`classify-training-data`, `score-training-data`, `validate-training-data`, `generate-contrastive`, `generate-preferences`

### Training — Execution (2)

`train [--force|--rollback|--export]`, `train-pipeline [--force]`

### Evaluation (10)

`cto-report`, `evaluate-holdout`, `model-evaluation-status`, `promote-model`, `feature-importance`, `backtest`, `compare-models`, `check-leakage`, `performance-report`, `evaluate-gate`

### Operations (8)

`collect-data`, `fetch-earnings`, `halt-trading`, `resume-trading`, `preflight`, `council`, `watch [--overnight]`, `dashboard`

## Scope

### In Scope

- S&P 100 universe (expanding to ~325 stocks), long-only equity swing trades (2-15 day holds)
- Systematic scoring + LLM commentary + bracket execution
- Self-improving training pipeline with quality gates
- Risk management with automated safety rails
- Passive options/volatility data collection

### Out of Scope (Current Phase)

- Options trading (passive data collection only — Options Volatility Desk in Phase 3-4)
- Short selling
- High-frequency / intraday trading (Intraday Desk is Phase 6+)
- Live trading with real money (Phase 2)

### Future Desks (Gated by Performance)

Each desk launches only after the previous desk is profitable. See docs/roadmap.md for full specifications.

- **Equity Research Desk** (Phase 2) — Same model, lower thresholds (score >= 30), separate paper account, training data volume
- **Options Volatility Desk** (Phase 3-4) — Separate LoRA adapter, credit spreads + iron condors, 15-check non-linear risk governor
- **Equity Momentum Desk** (Phase 5) — Separate LoRA adapter, Russell 1000, breakout/trend-following (LOW correlation with Swing)
- **Intraday Desk** (Phase 6+) — Separate model entirely, 1-min bars, VWAP reversion, requires dedicated GPU + real-time data
- **Future:** Event-Driven Desk, Macro/Rates Desk, Crypto Desk

## Governance Hierarchy

1. **AGENTS.md** — This document. Defines purpose, scope, and constraints
2. **Charter** — Operational rules and risk limits
3. **Blueprint** — Technical architecture (see docs/architecture.md)
4. **Code** — Implementation

## Technology Stack

- **Python 3.12+** — Core runtime
- **FastAPI + Uvicorn** — Dashboard API server
- **React 18 + Vite + Tailwind CSS** — Frontend dashboard
- **SQLite** — Journal, training data, model versions, data collection
- **yfinance** — Market data ingestion + options chains
- **Ollama + halcyon-v1 (Qwen3-8B fine-tuned)** — Local LLM inference
- **PEFT + TRL 0.24 + BitsAndBytes** — Fine-tuning on RTX 3060 12GB
- **Anthropic Claude API (Haiku 4.5)** — Training data generation, quality scoring
- **Alpaca Markets API** — Paper trading execution
- **Finnhub API** — Insider activity, company news
- **FRED API** — Macroeconomic indicators (34+ series)
- **SEC EDGAR** — Fundamental data
- **Telegram Bot API** — Real-time push notifications

## Research Library (59 documents)

See the dashboard Docs page for the complete research library covering:

- Training methodology (formats, rubric, self-blinding, degradation prevention, gaps/innovation, GRPO)
- Strategy (alternative data, Halcyon Framework, optimal universe size, options trading)
- Business (fund path/regulatory/tax, scaling plan)
- Model selection (Qwen3 8B guide)

## Roadmap

See the dashboard Roadmap page or docs/roadmap.md for the 6-phase development plan:

1. **Bootcamp** (current) — Equity Swing Desk, paper $100K, prove edge
2. **Micro Live** — Swing Desk live ($500-$1K) + Research Desk (paper, training data volume)
3. **Growth** — Options Volatility Desk (paper), sector/regime LoRA adapters
4. **Full Autonomous** — Options Desk live ($2-5K), investor-ready track record
5. **Scale Capital** — Equity Momentum Desk, Russell 1000, family LP
6. **Future** — Intraday Desk, event-driven, macro, crypto (scoped, not scheduled)

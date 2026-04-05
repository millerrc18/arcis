# Arcis Repository Directory

> **Auto-generated** by `scripts/generate_directory.py` — run after every sprint.
> Last updated: 2026-04-04

## Quick Stats

| Metric | Count |
|---|---|
| Python source files | 202 |
| Test files | 113 |
| Dashboard pages | 18 |
| Research documents | 79 |
| Schema tables | 49 |

## Directory Tree

```
arcis/
├── config/  ← YAML settings, known violations, guardrail baselines
│   ├── daily_repo_audit_baseline.json
│   ├── known_schema_violations.json
│   ├── known_violations.json
│   ├── settings.example.yaml
│   └── trade_commentary.gbnf
├── data/  ← Runtime data (gitignored) + reference data
│   └── reference/
│       ├── canary_set.jsonl
│       ├── market_event_calendar.csv
│       ├── sector_profiles.json
│       ├── sp_composition_changes.csv
│       └── warmup_prompt.txt
├── docs/  ← Research, sprints, architecture, decisions, guides
│   ├── archive/  ← Archived docs (49 old sprints, audits, governance)
│   │   ├── audits/
│   │   ├── governance/
│   │   ├── misc/
│   │   ├── quality/
│   │   ├── reference/
│   │   ├── sprints/
│   │   ├── audit_comprehensive_2026-03-28.md
│   │   ├── audit_report.md
│   │   ├── compute_schedule_implementation.md
│   │   ├── mega_sprint_report.md
│   │   ├── observation-log-template.md
│   │   ├── README.md
│   │   ├── roadmap-additions-2026-03-28.md
│   │   └── system-state-2026-03-27.md
│   ├── audits/
│   │   ├── runtime/
│   │   ├── audit-2026-04-04.md
│   │   └── log-audit-2026-04-04.md
│   ├── blueprint/  ← Original project blueprint
│   │   └── version1_blueprint.md
│   ├── charter/  ← Project charter (.docx)
│   │   └── AI_Research_Desk_Project_Charter.docx
│   ├── decisions/  ← Architecture Decision Records (ADRs, 12 decisions)
│   │   ├── 001-strategy-2-mean-reversion.md
│   │   ├── 002-strategy-3-evolved-pead.md
│   │   ├── 003-rl-method-dr-grpo.md
│   │   ├── 004-traffic-light-regime-overlay.md
│   │   ├── 005-council-vote-first-protocol.md
│   │   ├── 006-holding-period-optimization.md
│   │   ├── 007-event-calendar-risk-scoring.md
│   │   ├── 008-xml-gbnf-grammar-enforcement.md
│   │   ├── 009-volatility-adaptive-phase-2.md
│   │   ├── 010-risk-budgeting-equal-weight.md
│   │   ├── 011-tax-strategy-tabled.md
│   │   └── 012-command-queue-architecture.md
│   ├── diagrams/  ← 14 SVG architecture diagrams (light/dark mode)
│   │   └── svg/
│   ├── guides/  ← Setup guides (email, audit plugin, daily audit)
│   │   ├── audit-plugin.md
│   │   ├── daily-repo-audit.md
│   │   └── email_setup.md
│   ├── issues/
│   │   └── 2026-04-03-log-audit-rcca.md
│   ├── journal/
│   │   └── journal_schema_v1.md
│   ├── milestones/
│   │   └── mvp_milestones.md
│   ├── packet_templates/
│   │   └── trade_packet_v1.md
│   ├── research/  ← 79 research documents covering all system domains
│   │   ├── deep-research/  ← Deep research results (highest authority)
│   │   ├── AI-Powered_Options_Trading__From_First_Principles_to_Production_Architecture.md
│   │   ├── AI_Agent_Repo_Structure_Specification.md
│   │   ├── AI_Council_Multi-Agent_Deliberation_Architecture.md
│   │   ├── AI_Council_Redesign__5-Agent_Strategic_Brain.md
│   │   ├── AI_Council_Redesign_v2__Architecture_and_Implementation.md
│   │   ├── Algorithmic_Trader_Tax_Strategy__TTS_and_475f_Election.md
│   │   ├── Algorithmic_Trader_Tax_Strategy_TTS_475f.md
│   │   ├── Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md
│   │   ├── Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md
│   │   ├── Alternative_Data_Signals_for_Large-Cap_Short-Horizon_Trading__A_Cost-Benefit_Analysis_for_the_Halcyon_Lab_Stack.md
│   │   ├── ARCIS_RESEARCH_FRAMEWORK.md
│   │   ├── Best_Local_LLM_for_Financial_Analysis_on_RTX_3060__Qwen_Model_Selection_and_Fine-Tuning_Guide.md
│   │   ├── Brand_Identity_System__AI_Trading_Platform.pdf
│   │   ├── Build_Score_Specification__Composite_KPI.md
│   │   ├── Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md
│   │   ├── Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md
│   │   ├── Competitive_Benchmarking_Report.md
│   │   ├── Complete_Research_Agenda__Validation_to_Scale.md
│   │   ├── Complete_Research_Agenda__Validation_to_Scale_v2.md
│   │   ├── Comprehensive_Research_Compendium__10_Domains_for_Autonomous_AI_Trading.md
│   │   ├── Data_Infrastructure_Audit_Per_Desk_Collection_Requirements.md
│   │   ├── deep-research-ib-best-practices.md
│   │   ├── Disaster_Recovery_for_Solo_Algorithmic_Trading.md
│   │   ├── Event_Calendar_Integration_for_SP100_Pullback_Trading.md
│   │   ├── Feature_Importance_Monitoring_for_Fine-Tuned_Trading_LLMs.md
│   │   ├── Financial_NLP_FinBERT_Deployment_on_Consumer_Hardware.md
│   │   ├── Fine-Tuning_Qwen3_8B_RTX_3060_March_2026_Guide.md
│   │   ├── From_Solo_AI_Trader_to_Fund_Manager__A_Complete_Operational_Roadmap.md
│   │   ├── Fund_Formation_Roadmap__Solo_Trader_to_Registered_Fund.md
│   │   ├── Gold-Standard_Rubric_for_Scoring_Equity_Trade_Commentary__Process-Driven_LLM_Evaluation_Framework.md
│   │   ├── GRPO_for_Financial_LLMs_on_Consumer_Hardware__Practical_Implementation_and_Reward_Design.md
│   │   ├── Halcyon_Lab__AI-Powered_Equity_Research_Investor-Ready_Business_Plan.md
│   │   ├── Halcyon_Lab_Business_Plan_Operating_Manual.docx
│   │   ├── Halcyon_Lab_Complete_Brand_Identity_System.md
│   │   ├── Halcyon_Lab_Scaling_Plan_Through_2026.md
│   │   ├── Halcyon_v2_Training_Dataset_Specification.pdf
│   │   ├── Hardware_Deployment_Strategy__Multi-Desk_GPU_Roadmap.pdf
│   │   ├── IB_Best_Practices_for_Autonomous_AI_Trading.md
│   │   ├── LLM_Conviction_Score_Calibration_for_Trading.md
│   │   ├── Market_Data_APIs_Comprehensive_Comparison_2026.md
│   │   ├── Market_Event_Calendar_Dataset_2020-2027.md
│   │   ├── Multi-LoRA_Serving_on_Consumer_GPUs.md
│   │   ├── Multi-Strategy_Pattern_Classification_for_Equity_Trading.md
│   │   ├── Numerical_Hallucination_Prevention_in_Small_Financial_LMs.md
│   │   ├── Optimal_24x7_GPU_Schedule_for_Solo_AI_Trading.md
│   │   ├── Optimal_Holding_Periods_for_Halcyon_Lab_Three_Equity_Strategies.md
│   │   ├── Optimal_Trading_Universe_Size__S&P_500_Filtered_to_325_Stocks.md
│   │   ├── Optimal_Training_Formats_for_Fine-Tuning_Equity_Trade_Commentary_Models.md
│   │   ├── Options_Trading_Education_Plan_for_System_Builders.md
│   │   ├── PEAD_for_SP100__The_Drift_Evolved.md
│   │   ├── Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining__Data_Accumulation__Golden_Ratio_Mixing__and_Champion-Challenger_Evaluation.md
│   │   ├── Prompt_Engineering_for_Outcome-Conditioned_Training_Data_Generation__Self-Blinding_Pipelines_and_Reverse_Reasoning_Distillation.md
│   │   ├── Quantitative_Regime_Detection_for_Halcyon_Lab.md
│   │   ├── Qwen3_8B_Numerical_Tokenization_and_Financial_Reasoning.md
│   │   ├── REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md
│   │   ├── Risk_Budgeting_for_3-Strategy_Equity_System.md
│   │   ├── S_P_100_Pullback_Trading_Profiles__Complete_Constituent_Database.pdf
│   │   ├── Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md
│   │   ├── SEC_EDGAR_XBRL_Comparable_Financial_Database.md
│   │   ├── SP100_Current_Market_Assessment_2026-03-25.pdf
│   │   ├── SP100_Pullback_Trading_Profiles.md
│   │   ├── Strategy_2_Selection__Mean_Reversion_Wins.md
│   │   ├── The_Halcyon_Framework__Compute__Value__and_Moat_for_a_Solo_AI_Trading_System.md
│   │   ├── The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md
│   │   ├── Training_Data_Strategies_That_Give_Small_Financial_LLMs_a_Real_Edge.md
│   │   ├── U_S__Equity_Market_Regime_Timeline_2015-2026__Pullback_Trading_Model_Training_Data_and_Regime_Classification.pdf
│   │   ├── US_Equity_Market_Regime_Timeline_2015-2026.md
│   │   ├── Volatility-Adaptive_Position_Management_for_Pullback_Trading.md
│   │   ├── Walk-Forward_Backtesting_Protocol_for_Small-Sample_Strategies.md
│   │   └── XML_Compliance_via_GBNF_Grammar_Enforcement.md
│   ├── sprints/  ← Sprint prompts and implementation plans
│   │   ├── arcis-master-implementation-plan.md
│   │   ├── cc-docs-refresh-april.md
│   │   ├── implementation-plan-sprints-3-7.md
│   │   ├── sprint-bug-bash-cleanup.md
│   │   ├── sprint-codebase-comments.md
│   │   ├── sprint-dashboard-polish.md
│   │   ├── sprint-gap-rectification.md
│   │   ├── sprint-ib-integration.md
│   │   ├── sprint-ios-capacitor.md
│   │   ├── sprint-log-audit-hotfix.md
│   │   ├── sprint-mega-dashboard-docs.md
│   │   ├── sprint-react-flow-ui-polish.md
│   │   ├── sprint-research-framework.md
│   │   ├── sprint-schema-registry.md
│   │   ├── sprint-startup-rectification.md
│   │   ├── task-diagrams-integration.md
│   │   └── TEMPLATE.md
│   ├── superpowers/  ← Implementation plans and design specs (auto-generated by CC)
│   │   ├── plans/  ← (5 files) Task implementation plans
│   │   └── specs/  ← (5 files) Design specifications
│   ├── architecture.svg
│   ├── cli-reference.md
│   ├── dashboard-data-map.md
│   ├── deployment.md
│   ├── logo-dark.svg
│   ├── logo-light.svg
│   ├── telegram-commands.md
│   └── training-guide.md
├── frontend/  ← React 19 dashboard (Vite 8, Tailwind 4, 18 pages)
│   ├── public/  ← Static assets (icons, manifest, service worker)
│   │   ├── architecture-letter.html
│   │   ├── architecture.html
│   │   ├── blueprint.html
│   │   ├── favicon.svg
│   │   ├── icon-192.png
│   │   ├── icon-512.png
│   │   ├── icons.svg
│   │   ├── manifest.json
│   │   └── sw.js
│   ├── src/  ← React source code
│   │   ├── assets/
│   │   ├── components/  ← Shared UI components
│   │   ├── contexts/
│   │   ├── hooks/
│   │   ├── pages/  ← 18 dashboard pages
│   │   ├── utils/
│   │   ├── api.js
│   │   ├── App.jsx
│   │   ├── config.js
│   │   ├── index.css
│   │   └── main.jsx
│   ├── eslint.config.js
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   ├── README.md
│   └── vite.config.js
├── logs/  ← Runtime logs (gitignored)
├── scripts/  ← Utility scripts (audit, stress test, migration, verification)
│   ├── alpha_attribution_backtest.py  ← Attribution backtest on historical data
│   ├── assign_curriculum_stages.py
│   ├── bootstrap_repo.md
│   ├── build_event_calendar.py
│   ├── check_config.py
│   ├── clean_training_data.py
│   ├── create_missing_tables.py
│   ├── daily_repo_audit.py  ← Automated CI audit (GitHub Actions)
│   ├── diagnose_leakage.py
│   ├── dump_config.py
│   ├── export_chatgpt_inputs.py
│   ├── fetch_earnings_calendar.py
│   ├── fix_training_format.py
│   ├── generate_dependency_graph.py
│   ├── generate_directory.py
│   ├── generate_schema_docs.py
│   ├── import_chatgpt_outputs.py
│   ├── mark_failed_trades.py
│   ├── migrate_production_db.py
│   ├── overnight_train.py
│   ├── post_close_check.py
│   ├── recover_from_postgres.py
│   ├── register_model_v1.py
│   ├── render_architecture_doc.py
│   ├── render_init_db.py
│   ├── render_migrate.py  ← Postgres schema migration from registry
│   ├── schema_report.py
│   ├── scrape_sp_changes.py
│   ├── statusline.py
│   ├── stress_test.py  ← Historical stress testing (2008/2020/2022)
│   ├── sync_daily_repo_audit_issues.py
│   ├── validate_4e.py
│   ├── validate_training_format.py
│   ├── verify_counts.py
│   ├── verify_docs.py  ← Documentation count drift checker
│   ├── weekly_review.bat
│   └── weekly_review.py
├── src/  ← Python backend — 30 modules, 202 files
│   ├── api/  ← (25 files) FastAPI routes (local + cloud), 120+ endpoints
│   │   ├── cloud_routes/  ← (6 files) Render cloud API routes
│   │   ├── routes/  ← (14 files) Local API routes
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── cloud_app.py
│   │   └── websocket.py
│   ├── attribution/  ← (1 files) Alpha attribution — LLM vs ranker-only comparison
│   │   ├── __init__.py
│   │   └── logger.py
│   ├── cli/  ← (1 files) CLI commands (scan, watch, shadow-status, etc.)
│   │   ├── __init__.py
│   │   └── commands.py
│   ├── commands/  ← (1 files) Command queue executor (11 command types)
│   │   ├── __init__.py
│   │   └── executor.py
│   ├── config/  ← (1 files) YAML config loader + environment detection
│   │   ├── __init__.py
│   │   └── overrides.py
│   ├── council/  ← (11 files) 5-agent AI Council — Modified Delphi protocol
│   │   ├── __init__.py
│   │   ├── agent_data.py
│   │   ├── agents.py
│   │   ├── aggregation.py
│   │   ├── constants.py
│   │   ├── context.py
│   │   ├── engine.py
│   │   ├── parsing.py
│   │   ├── prompts.py
│   │   ├── protocol.py
│   │   ├── rate_limiter.py
│   │   └── value_tracker.py
│   ├── data_collection/  ← (17 files) 12 overnight collectors (options, VIX, FRED, EDGAR, etc.)
│   │   ├── __init__.py
│   │   ├── analyst_collector.py
│   │   ├── cboe_collector.py
│   │   ├── docs_collector.py
│   │   ├── edgar_collector.py
│   │   ├── errors.py
│   │   ├── fed_collector.py
│   │   ├── insider_collector.py
│   │   ├── macro_collector.py
│   │   ├── options_collector.py
│   │   ├── options_metrics.py
│   │   ├── research_collector.py
│   │   ├── research_sources.py
│   │   ├── research_synthesizer.py
│   │   ├── retention.py
│   │   ├── short_interest_collector.py
│   │   ├── trends_collector.py
│   │   └── vix_collector.py
│   ├── data_enrichment/  ← (7 files) 7-dimension feature enrichment (Finnhub, news, insider)
│   │   ├── __init__.py
│   │   ├── earnings_signals.py
│   │   ├── enricher.py
│   │   ├── fundamentals.py
│   │   ├── insiders.py
│   │   ├── macro.py
│   │   ├── news.py
│   │   └── staleness.py
│   ├── data_ingestion/  ← (1 files) Market data fetching (yfinance, Alpaca)
│   │   ├── __init__.py
│   │   └── market_data.py
│   ├── email/  ← (2 files) SMTP email sender (digest, full-stream modes)
│   │   ├── __init__.py
│   │   ├── digest_builder.py
│   │   └── notifier.py
│   ├── evaluation/  ← (14 files) Build score, HSHS health, backtester, system validator
│   │   ├── __init__.py
│   │   ├── auditor.py
│   │   ├── backtester.py
│   │   ├── build_score.py
│   │   ├── change_detector.py
│   │   ├── cto_report.py
│   │   ├── feature_importance.py
│   │   ├── gate_evaluator.py
│   │   ├── hshs.py
│   │   ├── hshs_live.py
│   │   ├── metrics.py
│   │   ├── postmortem.py
│   │   ├── scorecard.py
│   │   ├── statistics.py
│   │   └── system_validator.py
│   ├── features/  ← (10 files) Feature engine (regime, setup classifier, indicators, MR)
│   │   ├── __init__.py
│   │   ├── earnings.py
│   │   ├── engine.py
│   │   ├── event_proximity.py
│   │   ├── event_risk_score.py
│   │   ├── filing_nlp.py
│   │   ├── indicators.py
│   │   ├── mean_reversion.py
│   │   ├── regime.py
│   │   ├── setup_classifier.py
│   │   └── traffic_light.py
│   ├── journal/  ← (1 files) Trade journal — SQLite CRUD for shadow_trades
│   │   ├── __init__.py
│   │   └── store.py
│   ├── llm/  ← (7 files) Ollama client, packet writer, conviction parser, validator
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── grammar_client.py
│   │   ├── packet_writer.py
│   │   ├── postmortem_writer.py
│   │   ├── prompts.py
│   │   ├── validator.py
│   │   └── watchlist_writer.py
│   ├── logging/  ← (1 files) Structured logging configuration
│   │   ├── __init__.py
│   │   └── activity.py
│   ├── notifications/  ← (1 files) Telegram bot (32 notification functions)
│   │   ├── __init__.py
│   │   └── telegram.py
│   ├── packets/  ← (3 files) Trade packet builder + renderer + EOD recap
│   │   ├── __init__.py
│   │   ├── eod_recap.py
│   │   ├── template.py
│   │   └── watchlist.py
│   ├── ranking/  ← (1 files) Deterministic ranker (score 0-100)
│   │   ├── __init__.py
│   │   └── ranker.py
│   ├── risk/  ← (1 files) Risk governor (8 hard checks + kill switch)
│   │   ├── __init__.py
│   │   └── governor.py
│   ├── scheduler/  ← (10 files) Watch loop + 4-tier multi-cadence scanners
│   │   ├── __init__.py
│   │   ├── fundamentals_refresh.py
│   │   ├── holidays.py
│   │   ├── metrics.py
│   │   ├── position_monitor.py
│   │   ├── premarket.py
│   │   ├── scorer.py
│   │   ├── sentiment_scanner.py
│   │   ├── universe_scanner.py
│   │   ├── vram_manager.py
│   │   └── watch.py
│   ├── schema/  ← (5 files) Schema registry (49 tables) + validator + Postgres sync
│   │   ├── __init__.py
│   │   ├── postgres.py
│   │   ├── registry.py
│   │   ├── sqlite.py
│   │   ├── sync_config.py
│   │   └── validator.py
│   ├── services/  ← (7 files) Business logic services (scan, shadow, system)
│   │   ├── __init__.py
│   │   ├── recap_service.py
│   │   ├── review_service.py
│   │   ├── scan_service.py
│   │   ├── shadow_service.py
│   │   ├── system_service.py
│   │   ├── training_service.py
│   │   └── watchlist_service.py
│   ├── shadow_trading/  ← (7 files) Trade execution (Alpaca adapter, bracket orders, reconcile)
│   │   ├── __init__.py
│   │   ├── alpaca_adapter.py
│   │   ├── bracket_monitor.py
│   │   ├── executor.py
│   │   ├── ledger.py
│   │   ├── metrics.py
│   │   ├── models.py
│   │   └── reconcile.py
│   ├── strategy/  ← (1 files) Strategy configuration and dispatching
│   │   ├── __init__.py
│   │   └── canary.py
│   ├── sync/  ← (1 files) Render Postgres sync (incremental, per-table reconnect)
│   │   ├── __init__.py
│   │   └── render_sync.py
│   ├── trading/  ← (4 files) Multi-broker abstraction (Alpaca + IB live trading)
│   │   ├── __init__.py
│   │   ├── alpaca_broker.py
│   │   ├── broker_factory.py
│   │   ├── broker_interface.py
│   │   └── ib_broker.py
│   ├── training/  ← (19 files) Training pipeline (data collector, versioning, backfill, leakage)
│   │   ├── __init__.py
│   │   ├── ab_evaluation.py
│   │   ├── backfill.py
│   │   ├── bootstrap.py
│   │   ├── canary.py
│   │   ├── claude_client.py
│   │   ├── curriculum.py
│   │   ├── data_collector.py
│   │   ├── dpo_pipeline.py
│   │   ├── historical_data.py
│   │   ├── historical_scanner.py
│   │   ├── ingestion_gate.py
│   │   ├── leakage_detector.py
│   │   ├── outcome_prompts.py
│   │   ├── quality_drift.py
│   │   ├── quality_filter.py
│   │   ├── report.py
│   │   ├── trainer.py
│   │   ├── validation.py
│   │   └── versioning.py
│   ├── universe/  ← (3 files) S&P 100 universe management
│   │   ├── __init__.py
│   │   ├── company_names.py
│   │   ├── sectors.py
│   │   └── sp100.py
│   ├── utils/  ← (3 files) Activity logger, helpers
│   │   ├── __init__.py
│   │   ├── activity_logger.py
│   │   ├── db.py
│   │   └── retry.py
│   ├── __init__.py
│   ├── config_overrides.py
│   ├── data_integrity.py
│   ├── log_config.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   └── startup.py
├── tests/  ← Test suite — 1,425 functions across 113 files
│   ├── conftest.py
│   ├── test_ab_evaluation.py
│   ├── test_action_reminders.py
│   ├── test_activity_log.py
│   ├── test_activity_logger.py
│   ├── test_attribution.py
│   ├── test_auditor.py
│   ├── test_backfill.py
│   ├── test_backtester.py
│   ├── test_bracket_monitor.py
│   ├── test_bracket_orders.py
│   ├── test_bracket_safety.py
│   ├── test_broker_interface.py
│   ├── test_buying_power_check.py
│   ├── test_canary.py
│   ├── test_change_detector.py
│   ├── test_cloud_analytics.py
│   ├── test_cloud_app.py
│   ├── test_cloud_auth.py
│   ├── test_command_queue.py
│   ├── test_confidence.py
│   ├── test_config_tech_debt.py
│   ├── test_config_validation.py
│   ├── test_council.py
│   ├── test_council_aggregation.py
│   ├── test_council_subsystems.py
│   ├── test_cto_report.py
│   ├── test_curriculum.py
│   ├── test_data_collectors.py
│   ├── test_data_integrity.py
│   ├── test_data_pipeline_robustness.py
│   ├── test_db_migration.py
│   ├── test_db_util.py
│   ├── test_digest_builder.py
│   ├── test_docs_collector.py
│   ├── test_dpo_pipeline.py
│   ├── test_earnings.py
│   ├── test_earnings_signals.py
│   ├── test_enricher_import.py
│   ├── test_enrichment.py
│   ├── test_env_secrets.py
│   ├── test_event_proximity.py
│   ├── test_event_risk_score.py
│   ├── test_executor_import.py
│   ├── test_expanded_notifications.py
│   ├── test_feature_importance.py
│   ├── test_features.py
│   ├── test_filing_nlp.py
│   ├── test_gate_evaluator.py
│   ├── test_grammar_client.py
│   ├── test_holdout.py
│   ├── test_hshs.py
│   ├── test_hshs_live.py
│   ├── test_ingestion.py
│   ├── test_ingestion_gate.py
│   ├── test_kill_switch.py
│   ├── test_leakage_detector.py
│   ├── test_live_trading.py
│   ├── test_llm_client.py
│   ├── test_llm_pipeline_hardening.py
│   ├── test_llm_validator.py
│   ├── test_llm_writers.py
│   ├── test_local_api_routes.py
│   ├── test_local_routes.py
│   ├── test_main_refactor.py
│   ├── test_metrics.py
│   ├── test_news.py
│   ├── test_packet_builders.py
│   ├── test_packet_writer_import.py
│   ├── test_postmortem.py
│   ├── test_premarket.py
│   ├── test_quality_drift.py
│   ├── test_quality_filter.py
│   ├── test_quality_rubric.py
│   ├── test_ranking.py
│   ├── test_recap_service.py
│   ├── test_reconcile.py
│   ├── test_reconcile_backfill.py
│   ├── test_regime.py
│   ├── test_render_sync.py
│   ├── test_repo_structure.py
│   ├── test_retry.py
│   ├── test_review.py
│   ├── test_risk_governor.py
│   ├── test_scan_service.py
│   ├── test_schema.py
│   ├── test_schema_generators.py
│   ├── test_scorecard.py
│   ├── test_scorer.py
│   ├── test_self_blinding.py
│   ├── test_services.py
│   ├── test_setup_classifier.py
│   ├── test_shadow_metrics.py
│   ├── test_shadow_service.py
│   ├── test_startup.py
│   ├── test_statistics.py
│   ├── test_system_service.py
│   ├── test_system_validator.py
│   ├── test_trading_logic_fixes.py
│   ├── test_traffic_light.py
│   ├── test_trainer.py
│   ├── test_training_data.py
│   ├── test_training_pipeline_safety.py
│   ├── test_universe.py
│   ├── test_validation.py
│   ├── test_versioning.py
│   ├── test_vram_manager.py
│   ├── test_watch_bootstrap.py
│   ├── test_watch_import.py
│   ├── test_watch_resilience.py
│   ├── test_watchlist_service.py
│   ├── test_websocket.py
│   └── test_xml_format.py
├── CHANGELOG.md  ← Detailed change log (all PRs)
├── CLAUDE.md  ← CC agent instructions — rules, schema, startup sequence
├── DIRECTORY.md  ← This file — repository directory map
├── LICENSE  ← BSL 1.1 — source-visible, Apache 2.0 in 2030
├── MASTER.md  ← Single source of truth — system state, architecture, decisions
├── pyrightconfig.json  ← Python type-checking config
├── README.md  ← Public-facing project overview
├── RELEASES.md  ← Version history and release process
├── render.yaml  ← Render deployment configuration
├── requirements-cloud.txt  ← Render cloud deployment deps
├── requirements-training.txt  ← Training-specific deps (PEFT, TRL, BitsAndBytes)
└── requirements.txt  ← Core Python dependencies
```

## Key Files (start here)

| File | Purpose |
|---|---|
| `MASTER.md` | **Read this first.** System state, architecture, all 24 strategy decisions, phase gates. |
| `CLAUDE.md` | Agent instructions — mandatory rules for CC sprints. |
| `RELEASES.md` | Version history, release process, path to v1.0.0. |
| `src/schema/registry.py` | Single source of truth for all 49 database tables. |
| `src/startup.py` | Startup validation checks — tiered config/schema/env/connectivity/services checks. |
| `src/scheduler/watch.py` | The main loop — scans, monitors, collects, trains. |
| `config/settings.example.yaml` | All configuration keys with descriptions. |
| `docs/sprints/` | Sprint prompts ready to fire in CC. |

## Module Map (src/)

Each module has a standard 5-field docstring header:
```
Called by: ...
Calls: ...
Owns tables: ...
Config keys: ...
Tests: ...
```

Use `grep -n "Called by:" src/**/*.py` to trace the dependency graph.

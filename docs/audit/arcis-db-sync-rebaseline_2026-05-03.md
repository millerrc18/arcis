# SQLite <-> Postgres Sync Rebaseline Report

**Generated:** 2026-05-03T09:06:43-04:00
**SQLite:** `C:\arcis\data\ai_research_desk.sqlite3`
**Postgres:** `dpg-d72kjk8gjchc7386lsqg-a.virginia-postgres.render.com/halcyon_zjdk`
**Registry tables:** 69 total / 60 synced / 9 local-only

## Missing Tables

| Category | Tables |
| --- | --- |
| Synced registry missing in SQLite | None |
| Synced registry missing in Postgres | None |
| SQLite tables not in registry | sqlite_sequence |
| Postgres tables not in registry | None |

## Missing Columns

_None._

## Type Mismatches

_None._

## PK / Conflict Target Mismatches

_None._

## Local-Only Tables

| Category | Tables |
| --- | --- |
| Registry local-only present in SQLite | bracket_health, config_overrides, daily_ib_health, data_freshness, model_evaluations, operator_view_state, preference_pairs, sync_state, system_metrics |
| Registry local-only present in Postgres | config_overrides, sync_state |
| Registry local-only missing in SQLite | None |
| SQLite-only unregistered | sqlite_sequence |

## Sync Smoke

This section comes from one live `run_sync_cycle()` invocation after the read-only tri-diff.

| Metric | Value |
| --- | --- |
| Smoke scope | full sync table set |
| Tables considered | activity_log, analyst_estimates, api_costs, audit_reports, backtest_results, backtest_trades, broker_exceptions, build_score_history, canary_evaluations, cboe_ratios, command_results, correlation_matrices, council_calibrations, council_parameter_log, council_parameter_state, council_sessions, diagnostic_runs, earnings_calendar, edgar_filings, factor_loadings, fed_communications, google_trends, ib_shadow_log, insider_transactions, log_entries, macro_snapshots, metric_snapshots, minute_bars, model_versions, options_chains, options_metrics, pending_commands, preflight_runs, quality_drift_metrics, recommendations, research_digests, research_docs, research_papers, scan_metrics, schedule_metrics, setup_signals, short_interest, simulation_results, sp100_historical_constituents, strategy_promotion_events, strategy_registry, stress_test_results, traffic_light_state, training_examples, trials_registry, user_notes, validation_results, vix_term_structure, walkforward_results, walkforward_trades, council_debug_log, council_votes, diagnostic_run_plots, attribution_trades, shadow_trades |
| First failing table | in_flight |
| First error | in_flight: Sync already in progress on host 'SWIFT-PC'. Use force=True to override if the row is known stale. |
| Errors | 1 |
| Tables synced | 0 |
| Tables with row activity | None |
| create_all_tables added | None |
| ensure_columns added | None |

### Per-Table Errors

| Error |
| --- |
| in_flight: Sync already in progress on host 'SWIFT-PC'. Use force=True to override if the row is known stale. |

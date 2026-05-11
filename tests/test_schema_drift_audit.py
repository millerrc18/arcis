"""Regression locks for schema NULL-constraint drift between registry / SQLite / PG.

Sprint SP5 §J Cutover Rectification T3.

These tests are STATIC — they validate the registry's ColumnDef declarations
without hitting a live database. The live drift-detection output is captured in
docs/audits/2026-05-11-cutover-rectification/drift-audit-results.md.

Background:
    The Phase 3-revised one-database cutover crashed at 20:37:44Z with:
        null value in column "setup_type" of relation "setup_signals"
        violates not-null constraint
    SQLite tolerated NULL setup_type for years (no enforcement); PG enforces the
    NOT NULL constraint emitted by the DDL generator from the registry's
    nullable=False. The fix: set nullable=True on setup_signals.setup_type to
    match the actual write path (setup_classifier.classify_setup returns None
    when no rule matches, and the INSERT does NOT guard against this).

Confirmed known drifts from scripts/audit_schema_drift.py:
    setup_signals.setup_type  — registry=nullable=False, sqlite=nullable=True
                                 Root cause: write path passes None legitimately.
                                 Resolution: registry -> nullable=True.
    shadow_trades.quarantined — registry=nullable=False (with default='0'),
                                 sqlite=nullable=True (DDL migration backfill
                                 didn't add NOT NULL constraint to SQLite).
                                 Resolution: NOT in scope (has default, not
                                 a write-path None issue; filed as follow-up).
    shadow_trades.instrumentation_version — same class as quarantined.
                                 Resolution: NOT in scope (has default).

See also: src/features/setup_classifier.py:30 comment + line 263 INSERT.
"""

from src.schema.registry import TABLES

# ---------------------------------------------------------------------------
# Required-input allowlist: NOT-NULL columns that MUST be supplied by callers
# (no default, not primary_key) — enforced by test_schema_registry_consistency.
#
# This allowlist represents columns whose nullable=False + default=None is
# INTENTIONAL and VERIFIED: every write path guarantees a non-null value.
#
# Format: frozenset of "table.column" strings.
# ---------------------------------------------------------------------------
_REQUIRED_INPUT_ALLOWLIST: frozenset[str] = frozenset(
    [
        # recommendations
        "recommendations.recommendation_id",
        "recommendations.created_at",
        "recommendations.ticker",
        # shadow_trades
        "shadow_trades.trade_id",
        "shadow_trades.created_at",
        "shadow_trades.ticker",
        "shadow_trades.updated_at",
        # ib_shadow_log
        "ib_shadow_log.log_id",
        "ib_shadow_log.trade_id",
        "ib_shadow_log.event_type",
        "ib_shadow_log.created_at",
        "ib_shadow_log.ticker",
        # daily_ib_health
        "daily_ib_health.date",
        # validation_results
        "validation_results.result_id",
        "validation_results.created_at",
        "validation_results.overall_status",
        "validation_results.checks_passed",
        "validation_results.checks_failed",
        "validation_results.checks_warning",
        "validation_results.results_json",
        # model_versions
        "model_versions.version_id",
        "model_versions.version_name",
        "model_versions.created_at",
        # training_examples
        "training_examples.example_id",
        "training_examples.created_at",
        "training_examples.source",
        "training_examples.instruction",
        "training_examples.input_text",
        "training_examples.output_text",
        # model_evaluations
        "model_evaluations.evaluation_id",
        "model_evaluations.created_at",
        "model_evaluations.input_text",
        "model_evaluations.current_model",
        "model_evaluations.new_model",
        # audit_reports
        "audit_reports.audit_id",
        "audit_reports.created_at",
        "audit_reports.audit_date",
        "audit_reports.audit_type",
        "audit_reports.overall_assessment",
        # metric_snapshots
        "metric_snapshots.snapshot_id",
        "metric_snapshots.created_at",
        "metric_snapshots.metric_name",
        "metric_snapshots.metric_value",
        "metric_snapshots.snapshot_date",
        "metric_snapshots.metrics_json",
        # api_costs
        "api_costs.cost_id",
        "api_costs.created_at",
        "api_costs.provider",
        "api_costs.model",
        "api_costs.input_tokens",
        "api_costs.output_tokens",
        "api_costs.cost_usd",
        "api_costs.purpose",
        "api_costs.cost_dollars",
        # preference_pairs
        "preference_pairs.pair_id",
        "preference_pairs.created_at",
        "preference_pairs.prompt",
        "preference_pairs.chosen",
        "preference_pairs.rejected",
        "preference_pairs.input_text",
        "preference_pairs.chosen_output",
        "preference_pairs.rejected_output",
        # canary_evaluations
        "canary_evaluations.eval_id",
        "canary_evaluations.created_at",
        "canary_evaluations.model_version",
        # council_sessions
        "council_sessions.session_id",
        "council_sessions.created_at",
        "council_sessions.ticker",
        # council_votes
        "council_votes.vote_id",
        "council_votes.session_id",
        "council_votes.agent_name",
        "council_votes.created_at",
        "council_votes.round",
        # council_calibrations
        "council_calibrations.calibration_id",
        "council_calibrations.created_at",
        "council_calibrations.agent_name",
        "council_calibrations.calibration_type",
        "council_calibrations.n_decisions",
        "council_calibrations.accuracy",
        "council_calibrations.brier_score",
        "council_calibrations.session_id",
        "council_calibrations.prediction",
        "council_calibrations.prediction_confidence",
        "council_calibrations.verification_date",
        # council_debug_log
        "council_debug_log.log_id",
        "council_debug_log.created_at",
        "council_debug_log.session_id",
        "council_debug_log.event_type",
        "council_debug_log.summary",
        "council_debug_log.agent_name",
        "council_debug_log.round",
        # council_parameter_log
        "council_parameter_log.log_id",
        "council_parameter_log.created_at",
        "council_parameter_log.parameter_name",
        "council_parameter_log.old_value",
        "council_parameter_log.new_value",
        "council_parameter_log.updated_by",
        "council_parameter_log.reason",
        "council_parameter_log.session_id",
        "council_parameter_log.default_value",
        "council_parameter_log.council_value",
        "council_parameter_log.applied_value",
        "council_parameter_log.attribution_start",
        # council_parameter_state
        "council_parameter_state.parameter_name",
        "council_parameter_state.current_value",
        "council_parameter_state.updated_at",
        "council_parameter_state.updated_by",
        "council_parameter_state.default_value",
        "council_parameter_state.last_updated",
        # edgar_filings
        "edgar_filings.id",
        "edgar_filings.accession_number",
        "edgar_filings.ticker",
        "edgar_filings.filing_type",
        "edgar_filings.filed_at",
        "edgar_filings.created_at",
        "edgar_filings.processed_at",
        "edgar_filings.cik",
        "edgar_filings.form_type",
        "edgar_filings.filing_date",
        "edgar_filings.collected_at",
        # insider_transactions
        "insider_transactions.transaction_id",
        "insider_transactions.ticker",
        "insider_transactions.filed_at",
        "insider_transactions.collected_at",
        # short_interest
        "short_interest.id",
        "short_interest.ticker",
        "short_interest.date",
        "short_interest.created_at",
        "short_interest.settlement_date",
        "short_interest.collected_at",
        # fed_communications
        "fed_communications.doc_id",
        "fed_communications.published_at",
        "fed_communications.doc_type",
        "fed_communications.created_at",
        "fed_communications.comm_type",
        "fed_communications.date",
        "fed_communications.collected_at",
        # analyst_estimates
        "analyst_estimates.estimate_id",
        "analyst_estimates.ticker",
        "analyst_estimates.created_at",
        "analyst_estimates.provider",
        "analyst_estimates.date",
        "analyst_estimates.collected_at",
        # options_chains
        "options_chains.chain_id",
        "options_chains.ticker",
        "options_chains.expiry",
        "options_chains.strike",
        "options_chains.option_type",
        "options_chains.created_at",
        "options_chains.collected_at",
        "options_chains.expiration",
        # options_metrics
        "options_metrics.metric_id",
        "options_metrics.ticker",
        "options_metrics.created_at",
        "options_metrics.metric_type",
        "options_metrics.collected_at",
        "options_metrics.collected_date",
        # cboe_ratios
        "cboe_ratios.date",
        "cboe_ratios.created_at",
        "cboe_ratios.put_call_ratio",
        "cboe_ratios.collected_at",
        "cboe_ratios.collected_date",
        # google_trends
        "google_trends.trend_id",
        "google_trends.ticker",
        "google_trends.date",
        "google_trends.created_at",
        "google_trends.collected_at",
        "google_trends.collected_date",
        # vix_term_structure
        "vix_term_structure.snapshot_id",
        "vix_term_structure.created_at",
        "vix_term_structure.spot_vix",
        "vix_term_structure.collected_at",
        "vix_term_structure.collected_date",
        # macro_snapshots
        "macro_snapshots.snapshot_id",
        "macro_snapshots.created_at",
        "macro_snapshots.snapshot_date",
        "macro_snapshots.source",
        "macro_snapshots.metric_name",
        "macro_snapshots.collected_at",
        "macro_snapshots.collected_date",
        "macro_snapshots.series_id",
        "macro_snapshots.series_name",
        # earnings_calendar
        "earnings_calendar.ticker",
        "earnings_calendar.earnings_date",
        "earnings_calendar.created_at",
        "earnings_calendar.updated_at",
        "earnings_calendar.collected_at",
        # research_papers
        "research_papers.paper_id",
        "research_papers.created_at",
        "research_papers.title",
        "research_papers.source",
        "research_papers.relevance_score",
        "research_papers.url",
        "research_papers.collected_at",
        # research_digests
        "research_digests.digest_id",
        "research_digests.created_at",
        "research_digests.digest_date",
        "research_digests.digest_type",
        "research_digests.week_start",
        "research_digests.week_end",
        # research_docs
        "research_docs.id",
        "research_docs.filename",
        "research_docs.title",
        "research_docs.content",
        "research_docs.size_kb",
        "research_docs.updated_at",
        # setup_signals — 4 core fields (setup_type is NOW nullable=True per T3 fix)
        "setup_signals.signal_id",
        "setup_signals.created_at",
        "setup_signals.ticker",
        "setup_signals.date",
        # traffic_light_state
        "traffic_light_state.id",
        # scan_metrics
        "scan_metrics.scan_id",
        # schedule_metrics
        "schedule_metrics.task_name",
        "schedule_metrics.last_run_at",
        "schedule_metrics.last_result",
        "schedule_metrics.metric_date",
        "schedule_metrics.metric_name",
        # quality_drift_metrics
        "quality_drift_metrics.run_id",
        "quality_drift_metrics.run_at",
        "quality_drift_metrics.created_at",
        # activity_log
        "activity_log.created_at",
        "activity_log.action",
        "activity_log.details",
        "activity_log.event_type",
        # log_entries
        "log_entries.log_id",
        "log_entries.created_at",
        "log_entries.level",
        "log_entries.logger",
        "log_entries.message",
        "log_entries.log_level",
        "log_entries.source",
        # command_results
        "command_results.result_id",
        "command_results.command",
        "command_results.created_at",
        "command_results.status",
        "command_results.command_id",
        # config_overrides
        "config_overrides.setting_key",
        "config_overrides.setting_value",
        "config_overrides.updated_at",
        # pending_commands
        "pending_commands.command_id",
        "pending_commands.command",
        "pending_commands.created_at",
        "pending_commands.status",
        "pending_commands.created_by",
        "pending_commands.command_type",
        "pending_commands.command_name",
        # diagnostic_runs
        "diagnostic_runs.run_id",
        "diagnostic_runs.created_at",
        "diagnostic_runs.run_type",
        "diagnostic_runs.status",
        "diagnostic_runs.triggered_by",
        "diagnostic_runs.completed_at",
        "diagnostic_runs.diagnostic_type",
        "diagnostic_runs.updated_at",
        # diagnostic_run_plots
        "diagnostic_run_plots.plot_id",
        "diagnostic_run_plots.run_id",
        "diagnostic_run_plots.plot_type",
        "diagnostic_run_plots.created_at",
        "diagnostic_run_plots.plot_data",
        "diagnostic_run_plots.filename",
        "diagnostic_run_plots.content_b64",
        # user_notes
        "user_notes.note_id",
        "user_notes.created_at",
        "user_notes.title",
        "user_notes.content",
        "user_notes.updated_at",
        # bracket_health
        "bracket_health.check_id",
        "bracket_health.trade_id",
        "bracket_health.ticker",
        "bracket_health.checked_at",
        # attribution_trades
        "attribution_trades.trade_id",
        "attribution_trades.created_at",
        "attribution_trades.ticker",
        # data_freshness
        "data_freshness.table_name",
        "data_freshness.last_updated",
        "data_freshness.row_count",
        "data_freshness.updated_at",
        "data_freshness.last_fetched_at",
        "data_freshness.created_at",
        # stress_test_results
        "stress_test_results.result_id",
        "stress_test_results.created_at",
        "stress_test_results.scenario_name",
        "stress_test_results.scenario",
        # simulation_results
        "simulation_results.result_id",
        "simulation_results.created_at",
        "simulation_results.regime",
        "simulation_results.sharpe_ratio",
        "simulation_results.total_return",
        "simulation_results.max_drawdown",
        "simulation_results.win_rate",
        "simulation_results.run_id",
        "simulation_results.scenario",
        "simulation_results.regime_label",
        "simulation_results.start_date",
        "simulation_results.end_date",
        # minute_bars
        "minute_bars.ticker",
        "minute_bars.ts",
        # backtest_results
        "backtest_results.result_id",
        "backtest_results.created_at",
        "backtest_results.strategy_id",
        "backtest_results.start_date",
        "backtest_results.end_date",
        "backtest_results.sharpe_ratio",
        "backtest_results.total_return",
        "backtest_results.spec_version",
        "backtest_results.spec_hash",
        # backtest_trades
        "backtest_trades.trade_id",
        "backtest_trades.result_id",
        "backtest_trades.ticker",
        "backtest_trades.entry_date",
        # strategy_registry
        "strategy_registry.strategy_id",
        "strategy_registry.created_at",
        "strategy_registry.name",
        "strategy_registry.version",
        "strategy_registry.status",
        "strategy_registry.spec_hash",
        "strategy_registry.spec_json",
        "strategy_registry.display_name",
        "strategy_registry.spec_source",
        "strategy_registry.current_status",
        "strategy_registry.current_spec_hash",
        "strategy_registry.last_status_change",
        # strategy_promotion_events
        "strategy_promotion_events.event_id",
        "strategy_promotion_events.created_at",
        "strategy_promotion_events.strategy_id",
        "strategy_promotion_events.from_status",
        "strategy_promotion_events.to_status",
        "strategy_promotion_events.triggered_by",
        "strategy_promotion_events.timestamp",
        # trials_registry
        "trials_registry.trial_id",
        "trials_registry.created_at",
        "trials_registry.strategy_id",
        "trials_registry.status",
        "trials_registry.spec_hash",
        # correlation_matrices
        "correlation_matrices.matrix_id",
        "correlation_matrices.created_at",
        "correlation_matrices.as_of_date",
        "correlation_matrices.universe",
        "correlation_matrices.matrix_json",
        # factor_loadings
        "factor_loadings.loading_id",
        "factor_loadings.created_at",
        "factor_loadings.as_of_date",
        "factor_loadings.ticker",
        # operator_view_state
        "operator_view_state.view_key",
        "operator_view_state.updated_at",
        # walkforward_results
        "walkforward_results.result_id",
        "walkforward_results.created_at",
        "walkforward_results.strategy_id",
        "walkforward_results.fold_start",
        "walkforward_results.fold_end",
        "walkforward_results.sharpe_ratio",
        "walkforward_results.total_return",
        "walkforward_results.spec_hash",
        "walkforward_results.outcome_state",
        "walkforward_results.n_windows",
        # walkforward_trades
        "walkforward_trades.trade_id",
        "walkforward_trades.result_id",
        "walkforward_trades.ticker",
        "walkforward_trades.entry_date",
        "walkforward_trades.exit_date",
        "walkforward_trades.run_id",
        "walkforward_trades.window_index",
        # sp100_historical_constituents
        "sp100_historical_constituents.ticker",
        "sp100_historical_constituents.as_of_date",
        # broker_exceptions
        "broker_exceptions.exception_id",
        "broker_exceptions.trade_id",
        "broker_exceptions.ticker",
        "broker_exceptions.created_at",
        "broker_exceptions.exception_type",
        "broker_exceptions.broker",
        "broker_exceptions.order_id",
        "broker_exceptions.resolved",
        "broker_exceptions.resolution",
        "broker_exceptions.operation",
        "broker_exceptions.timestamp",
        "broker_exceptions.exception_class",
        "broker_exceptions.exception_message",
        "broker_exceptions.recoverable",
        # preflight_runs
        "preflight_runs.run_id",
        "preflight_runs.run_type",
        "preflight_runs.status",
        "preflight_runs.overall_status",
        "preflight_runs.checks_passed",
        "preflight_runs.checks_failed",
        "preflight_runs.created_at",
        "preflight_runs.last_run_at",
        # live_prices
        "live_prices.ticker",
        "live_prices.price",
        "live_prices.as_of",
        "live_prices.source",
        # notifications_sent
        "notifications_sent.notification_id",
        "notifications_sent.created_at",
        "notifications_sent.channel",
        "notifications_sent.event_type",
        "notifications_sent.status",
        "notifications_sent.recipient",
        "notifications_sent.sent_at",
        # notifications_dedup
        "notifications_dedup.dedup_key",
        "notifications_dedup.created_at",
        "notifications_dedup.expires_at",
        "notifications_dedup.event_type",
        "notifications_dedup.sent_at",
        # system_metrics
        "system_metrics.metric_id",
        # build_score_history
        "build_score_history.score_id",
        # sp100_historical_constituents (already listed)
    ]
)


class TestSetupSignalsSetupTypeNullableInRegistry:
    """Regression lock: setup_signals.setup_type must be nullable in the registry.

    Root cause of Phase 3-revised cutover crash (2026-05-11T20:37:44Z):
        null value in column "setup_type" of relation "setup_signals"
        violates not-null constraint

    The write path in src/features/setup_classifier.py:_log_setup_signal() passes
    classification["setup_type"] directly — which is None when no rule matches
    (documented in setup_classifier.py:30). SQLite tolerated this; PG enforced the
    NOT NULL constraint emitted by the registry's nullable=False. Resolution: set
    nullable=True in the registry to match the actual write semantics.
    """

    def test_setup_signals_setup_type_nullable_in_registry(self):
        table = TABLES["setup_signals"]
        col = next(c for c in table.columns if c.name == "setup_type")
        assert col.nullable is True, (
            f"setup_signals.setup_type must be nullable=True in registry. "
            f"Got nullable={col.nullable}. "
            f"Root cause: setup_classifier.classify_setup() returns None when no "
            f"rule matches and the INSERT does not guard against this. "
            f"Setting nullable=False causes PG to reject the INSERT. "
            f"Fix: ColumnDef('setup_type', 'TEXT') — nullable defaults to True."
        )

    def test_setup_signals_table_exists_in_registry(self):
        assert "setup_signals" in TABLES, "setup_signals table must exist in TABLES registry"

    def test_setup_signals_primary_key_unchanged(self):
        table = TABLES["setup_signals"]
        assert table.primary_key == "signal_id", (
            f"setup_signals.primary_key must remain 'signal_id', got {table.primary_key!r}"
        )

    def test_setup_signals_required_columns_still_not_null(self):
        table = TABLES["setup_signals"]
        col_map = {c.name: c for c in table.columns}
        for required_col in ("signal_id", "created_at", "ticker", "date"):
            col = col_map.get(required_col)
            assert col is not None, f"setup_signals.{required_col} must exist"
            assert col.nullable is False, (
                f"setup_signals.{required_col} must remain NOT NULL (nullable=False). "
                f"Got nullable={col.nullable}."
            )


class TestSchemaRegistryConsistency:
    """Ensures every NOT-NULL column without a default is in the documented
    required-input allowlist.

    This catches future additions of NOT-NULL columns that don't have defaults
    and aren't explicitly listed as required inputs — the class of error that
    caused the cutover crash (registry says NOT NULL, write path passes None).
    """

    def test_all_not_null_no_default_columns_are_documented(self):
        undocumented = []
        for tname, tdef in TABLES.items():
            pk_cols = (
                [tdef.primary_key]
                if isinstance(tdef.primary_key, str)
                else list(tdef.primary_key)
            )
            for col in tdef.columns:
                if col.nullable is True:
                    continue
                if col.default is not None:
                    continue
                if col.name in pk_cols:
                    continue
                key = f"{tname}.{col.name}"
                if key not in _REQUIRED_INPUT_ALLOWLIST:
                    undocumented.append(key)

        assert not undocumented, (
            f"Found {len(undocumented)} NOT-NULL columns without defaults that are "
            f"NOT in _REQUIRED_INPUT_ALLOWLIST:\n"
            + "\n".join(f"  {k}" for k in undocumented)
            + "\n\nFor each: either (a) make the column nullable=True if the write "
            f"path can pass None, or (b) add a default, or (c) add to "
            f"_REQUIRED_INPUT_ALLOWLIST if every write path is verified to supply "
            f"a non-null value."
        )

    def test_no_known_drift_columns_violating_not_null(self):
        """setup_signals.setup_type was the known drift. Confirm it's now nullable."""
        table = TABLES["setup_signals"]
        col = next(c for c in table.columns if c.name == "setup_type")
        assert col.nullable is True, (
            "setup_signals.setup_type MUST be nullable=True after T3 fix."
        )

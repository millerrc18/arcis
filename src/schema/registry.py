"""Schema Registry — Single source of truth for all database tables.

Every table, column, index, and foreign key is defined here.
No other file in the codebase should contain CREATE TABLE statements.

WHY a single registry: Before this existed, CREATE TABLE statements were
scattered across 15+ files, leading to schema drift between SQLite and
Postgres (#181), missing columns, and inconsistent sync configs. CI tests
(test_no_create_table_in_source, test_no_alter_table_in_source) enforce
that DDL only appears in this file and src/schema/.

To add a new table:
    1. Add the TableDef to TABLES below
    2. Run: python -m src.main validate-schema --fix
    3. Run: python scripts/render_migrate.py
    4. Commit all three: registry.py + any generated migrations

To add a column to an existing table:
    1. Add the ColumnDef to the table's columns list
    2. Run: python -m src.main validate-schema --fix
    3. Run: python scripts/render_migrate.py
    4. Commit all three

NEVER create tables via raw SQL in any other file.
NEVER add columns via ALTER TABLE in any other file.

Called by: src.schema.validator, src.schema.sqlite, src.schema.postgres, scripts/render_migrate.py
Calls: none (data definitions only)
Owns tables: all 46 tables
Config keys: none
Tests: tests/test_schema.py, tests/test_repo_structure.py
"""

from dataclasses import dataclass, field


@dataclass
class ColumnDef:
    name: str
    type: str  # TEXT, REAL, INTEGER, BLOB
    nullable: bool = True
    default: str | None = None
    description: str = ""


@dataclass
class IndexDef:
    name: str
    columns: list[str]
    unique: bool = False


@dataclass
class ForeignKeyDef:
    column: str
    references_table: str
    references_column: str


@dataclass
class TableDef:
    name: str
    description: str
    columns: list[ColumnDef]
    primary_key: str | list[str]
    indexes: list[IndexDef] = field(default_factory=list)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    # Sync configuration for render_sync.py (SQLite -> Render Postgres)
    sync_to_postgres: bool = True  # Whether this table syncs to the cloud dashboard
    sync_mode: str = "incremental"  # incremental: new rows only | full: replace all | latest_only: most recent per group
    sync_time_column: str | None = "created_at"  # Column used for incremental cursor
    sync_pk: str | None = None  # Defaults to primary_key if None
    # Fix for #185: sync_conflict_col overrides ON CONFLICT target for tables
    # where the PK is an autoincrement INTEGER but uniqueness is on another column
    # (e.g., edgar_filings uses accession_number for dedup, not the integer id).
    sync_conflict_col: str | None = None


TABLES: dict[str, TableDef] = {}


def _register(table: TableDef) -> None:
    """Register a table definition."""
    TABLES[table.name] = table


# ---------------------------------------------------------------------------
# Trading Core (3 tables)
# ---------------------------------------------------------------------------

# recommendations: The primary record of every LLM-generated trade idea.
# Written by: packet_writer, scan_service. Read by: executor, eod_recap, dashboard.
# Contains both the original recommendation AND the shadow trade outcome
# (shadow_entry_price through lesson_tag) for end-to-end tracking.
_register(TableDef(
    name="recommendations",
    description="LLM-generated trade recommendations with full context and outcomes",
    columns=[
        ColumnDef("recommendation_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("company_name", "TEXT"),
        ColumnDef("mode", "TEXT"),
        ColumnDef("setup_type", "TEXT"),
        ColumnDef("priority_score", "REAL"),
        ColumnDef("confidence_score", "REAL"),
        ColumnDef("packet_type", "TEXT"),
        ColumnDef("price_at_recommendation", "REAL"),
        ColumnDef("market_regime", "TEXT"),
        ColumnDef("sector_context", "TEXT"),
        ColumnDef("trend_state", "TEXT"),
        ColumnDef("relative_strength_state", "TEXT"),
        ColumnDef("pullback_depth_pct", "REAL"),
        ColumnDef("atr", "REAL"),
        ColumnDef("volume_state", "TEXT"),
        ColumnDef("recommendation", "TEXT"),
        ColumnDef("thesis_text", "TEXT"),
        ColumnDef("entry_zone", "TEXT"),
        ColumnDef("stop_level", "TEXT"),
        ColumnDef("target_1", "TEXT"),
        ColumnDef("target_2", "TEXT"),
        ColumnDef("expected_hold_period", "TEXT"),
        ColumnDef("position_size_dollars", "REAL"),
        ColumnDef("position_size_pct", "REAL"),
        ColumnDef("estimated_dollar_risk", "REAL"),
        ColumnDef("reasons_to_trade", "TEXT"),
        ColumnDef("reasons_to_pass", "TEXT"),
        ColumnDef("earnings_date", "TEXT"),
        ColumnDef("event_risk_flag", "TEXT"),
        ColumnDef("hold_window_overlaps_earnings", "INTEGER"),
        ColumnDef("event_risk_warning_text", "TEXT"),
        ColumnDef("conservative_sizing_applied", "INTEGER"),
        ColumnDef("packet_sent", "INTEGER"),
        ColumnDef("packet_sent_at", "TEXT"),
        ColumnDef("ryan_approved", "INTEGER"),
        ColumnDef("ryan_executed", "INTEGER"),
        ColumnDef("ryan_notes", "TEXT"),
        ColumnDef("shadow_entry_price", "REAL"),
        ColumnDef("shadow_entry_time", "TEXT"),
        ColumnDef("shadow_exit_price", "REAL"),
        ColumnDef("shadow_exit_time", "TEXT"),
        ColumnDef("shadow_pnl_dollars", "REAL"),
        ColumnDef("shadow_pnl_pct", "REAL"),
        ColumnDef("max_favorable_excursion", "REAL"),
        ColumnDef("max_adverse_excursion", "REAL"),
        ColumnDef("shadow_duration_days", "REAL"),
        ColumnDef("thesis_success", "INTEGER"),
        ColumnDef("assistant_postmortem", "TEXT"),
        ColumnDef("lesson_tag", "TEXT"),
        ColumnDef("user_grade", "TEXT"),
        ColumnDef("repeatable_setup", "INTEGER"),
        ColumnDef("model_version", "TEXT"),
        ColumnDef("enriched_prompt", "TEXT"),
        ColumnDef("llm_conviction", "INTEGER"),
        ColumnDef("llm_conviction_reason", "TEXT"),
    ],
    primary_key="recommendation_id",
    indexes=[
        IndexDef("idx_recommendations_ticker", ["ticker"]),
        IndexDef("idx_recommendations_created_at", ["created_at"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="recommendation_id",
))

# shadow_trades: Every paper and live trade from entry to exit.
# Written by: executor.open_shadow_trade, executor.open_live_trade.
# Updated by: executor.check_and_manage_open_trades, reconcile.
# The "source" column distinguishes paper vs live trades.
_register(TableDef(
    name="shadow_trades",
    description="Paper/shadow trades tracked from entry to exit with execution quality",
    columns=[
        ColumnDef("trade_id", "TEXT", nullable=False),
        ColumnDef("recommendation_id", "TEXT"),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("direction", "TEXT", default="long"),
        ColumnDef("status", "TEXT", default="pending"),
        ColumnDef("entry_price", "REAL"),
        ColumnDef("stop_price", "REAL"),
        ColumnDef("target_1", "REAL"),
        ColumnDef("target_2", "REAL"),
        # REAL (not INTEGER): Alpaca fractional shares. INTEGER would silently
        # truncate e.g. 0.30 → 0 on reconcile, then the positive-shares guard
        # in journal.store would reject the row.
        ColumnDef("planned_shares", "REAL"),
        ColumnDef("planned_allocation", "REAL"),
        ColumnDef("actual_entry_price", "REAL"),
        ColumnDef("actual_entry_time", "TEXT"),
        ColumnDef("actual_exit_price", "REAL"),
        ColumnDef("actual_exit_time", "TEXT"),
        ColumnDef("exit_reason", "TEXT"),
        ColumnDef("pnl_dollars", "REAL"),
        ColumnDef("pnl_pct", "REAL"),
        ColumnDef("max_favorable_excursion", "REAL"),
        ColumnDef("max_adverse_excursion", "REAL"),
        ColumnDef("duration_days", "INTEGER"),
        ColumnDef("earnings_adjacent", "INTEGER", default="0"),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("updated_at", "TEXT", nullable=False),
        ColumnDef("alpaca_order_id", "TEXT"),
        ColumnDef("exit_order_id", "TEXT"),
        ColumnDef("order_type", "TEXT"),
        ColumnDef("timeout_days", "INTEGER", default="15"),
        ColumnDef("source", "TEXT", default="paper"),
        ColumnDef("broker", "TEXT", default="alpaca",
                  description="Broker that executed the trade (alpaca or ib). "
                  "Used by reconciler to check the correct broker's positions."),
        ColumnDef("ib_child_order_ids", "TEXT",
                  description="JSON list of IB child order IDs [take_profit, stop_loss] "
                  "for bracket health monitoring. NULL for Alpaca trades. "
                  "PermIds also available via ib_perm_id for cross-session tracking."),
        ColumnDef("ib_perm_id", "TEXT",
                  description="IB permanent order ID for cross-session tracking. "
                  "Unlike orderId, permId survives Gateway restarts."),
        ColumnDef("broker_order_id", "TEXT",
                  description="Alias for alpaca_order_id — stores order ID from whichever "
                  "broker executed. Future migration: move all references from "
                  "alpaca_order_id to broker_order_id and deprecate the original."),
        ColumnDef("setup_type", "TEXT"),
        ColumnDef("setup_confidence", "REAL"),
        ColumnDef("signal_entry_price", "REAL"),
        ColumnDef("fill_entry_price", "REAL"),
        ColumnDef("entry_slippage_bps", "REAL"),
        ColumnDef("signal_exit_price", "REAL"),
        ColumnDef("fill_exit_price", "REAL"),
        ColumnDef("exit_slippage_bps", "REAL"),
        ColumnDef("signal_price", "REAL"),
        ColumnDef("fill_price", "REAL"),
        ColumnDef("implementation_shortfall_bps", "REAL"),
        ColumnDef("strategy_type", "TEXT", default="pullback"),
        # REAL (not INTEGER): matches planned_shares — Alpaca fractional support.
        ColumnDef("actual_shares", "REAL"),
        ColumnDef("exit_retry_count", "INTEGER", default="0"),
        # Strategy Decision #24: Outcome metadata for regime-conditional analysis.
        # These columns capture market context at entry/exit so we can answer
        # "does the system perform better in low-vol regimes?" and similar questions.
        ColumnDef("regime_at_entry", "TEXT", description="Market regime at trade entry"),
        ColumnDef("regime_at_exit", "TEXT", description="Market regime at trade exit"),
        ColumnDef("vix_at_entry", "REAL", description="VIX level at trade entry"),
        ColumnDef("vix_at_exit", "REAL", description="VIX level at trade exit"),
        ColumnDef("time_to_target_days", "INTEGER", description="Days to reach target (NULL if not reached)"),
        # drawdown_from_mfe: How much the trade gave back from its best point.
        # Measured in basis points. High values suggest exits are too late.
        ColumnDef("drawdown_from_mfe", "REAL", description="Drawdown from MFE at exit (bps)"),
        ColumnDef("concurrent_positions", "INTEGER", description="Number of open positions at entry"),
        ColumnDef("ranking_at_entry", "INTEGER", description="Ranker rank (1=best) at entry"),
        ColumnDef("quarantined", "INTEGER", default="0", description="1 = compromised record from April 10 cascade, excluded from analytics"),
        # Capital-velocity instrumentation (DB-FINAL Task 1 / Strategy Decision #32).
        # time_to_mfe_days updates each monitoring cycle when MFE hits a new high,
        # letting the velocity analysis distinguish "winners peaked day 3" from
        # "winners peaked day 7" — the single most important velocity datapoint.
        ColumnDef("time_to_mfe_days", "INTEGER",
                  description="Days from entry to max favorable excursion peak. "
                  "Updated each monitoring cycle when MFE increases."),
        ColumnDef("mfe_timestamp", "TEXT",
                  description="ISO timestamp when MFE last increased (peak P&L moment)."),
    ],
    primary_key="trade_id",
    indexes=[
        IndexDef("idx_shadow_trades_status", ["status"]),
        IndexDef("idx_shadow_trades_ticker", ["ticker"]),
        IndexDef("idx_shadow_trades_recommendation_id", ["recommendation_id"]),
        IndexDef("idx_shadow_trades_created_at", ["created_at"]),
        IndexDef("idx_shadow_trades_status_exit", ["status", "actual_exit_time"]),
    ],
    foreign_keys=[
        ForeignKeyDef("recommendation_id", "recommendations", "recommendation_id"),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="updated_at",
    sync_pk="trade_id",
))

# ib_shadow_log: Shadow log of IB validation results for each Alpaca trade.
# Written by: trading.ib_shadow.IBShadowLogger
# Read by: dashboard (IB readiness analysis), cloud API (ib-shadow routes)
# Synced to Postgres for cloud dashboard access.
_register(TableDef(
    name="ib_shadow_log",
    description="Shadow log of what IB would have traded alongside Alpaca actuals",
    columns=[
        ColumnDef("shadow_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("trade_id", "TEXT"),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("action", "TEXT"),
        ColumnDef("quantity", "INTEGER"),
        ColumnDef("entry_price", "REAL"),
        ColumnDef("stop_price", "REAL"),
        ColumnDef("target_price", "REAL"),
        ColumnDef("ib_connected", "INTEGER", default="0"),
        ColumnDef("ib_contract_valid", "INTEGER", default="0"),
        ColumnDef("ib_buying_power", "REAL"),
        ColumnDef("ib_would_accept", "INTEGER", default="0"),
        ColumnDef("ib_order_params", "TEXT"),
        ColumnDef("ib_error", "TEXT"),
        ColumnDef("alpaca_order_id", "TEXT"),
        ColumnDef("alpaca_fill_price", "REAL"),
    ],
    primary_key="shadow_id",
    indexes=[
        IndexDef("idx_ib_shadow_created_at", ["created_at"]),
        IndexDef("idx_ib_shadow_trade_id", ["trade_id"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="shadow_id",
))

# daily_ib_health: Daily IB Gateway health metrics for 30-day stability gate.
# Written by: scripts/validate_ib_gateway.py, future ib_health_monitor
# Read by: dashboard (IB readiness page), operator review
# Local-only — not synced to cloud (contains infra metrics, not trading data).
_register(TableDef(
    name="daily_ib_health",
    description="Daily IB Gateway health metrics for 30-day stability gate",
    columns=[
        ColumnDef("date", "TEXT", nullable=False),
        ColumnDef("uptime_pct", "REAL"),
        ColumnDef("trade_count", "INTEGER", default="0"),
        ColumnDef("error_count", "INTEGER", default="0"),
        ColumnDef("reconnect_count", "INTEGER", default="0"),
        ColumnDef("gateway_version", "TEXT"),
        ColumnDef("market_hours_connected_min", "INTEGER"),
        ColumnDef("market_hours_expected_min", "INTEGER"),
        ColumnDef("notes", "TEXT"),
    ],
    primary_key="date",
    sync_to_postgres=False,
))

# validation_results: Output from `preflight` and daily validation (4:30 PM).
# Written by: system_validator. Read by: dashboard, startup command.
_register(TableDef(
    name="validation_results",
    description="Preflight validation check results",
    columns=[
        ColumnDef("result_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("overall_status", "TEXT", nullable=False),
        ColumnDef("checks_passed", "INTEGER", nullable=False),
        ColumnDef("checks_failed", "INTEGER", nullable=False),
        ColumnDef("checks_warning", "INTEGER", nullable=False),
        ColumnDef("results_json", "TEXT", nullable=False),
    ],
    primary_key="result_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="result_id",
))

# ---------------------------------------------------------------------------
# Training Pipeline (8 tables)
# These tables track the full fine-tuning lifecycle: training data curation,
# model versioning, A/B evaluation, and quality drift detection.
# ---------------------------------------------------------------------------

# model_versions: Each fine-tuned model checkpoint (halcyon-v1, v2, etc.).
# Written by: trainer.run_fine_tune. Read by: versioning, dashboard.
_register(TableDef(
    name="model_versions",
    description="Tracked model versions with training stats and holdout scores",
    columns=[
        ColumnDef("version_id", "TEXT", nullable=False),
        ColumnDef("version_name", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("training_examples_count", "INTEGER"),
        ColumnDef("synthetic_examples_count", "INTEGER"),
        ColumnDef("outcome_examples_count", "INTEGER"),
        ColumnDef("model_file_path", "TEXT"),
        ColumnDef("status", "TEXT", nullable=False, default="active"),
        ColumnDef("notes", "TEXT"),
        ColumnDef("holdout_score", "REAL"),
        ColumnDef("holdout_details", "TEXT"),
    ],
    primary_key="version_id",
    sync_to_postgres=True,
    sync_mode="full",
    sync_time_column=None,
    sync_pk="version_id",
))

# training_examples: The core training dataset. Each row is one instruction/output
# pair for Qwen3 fine-tuning. Sources: real trades (outcome_win/loss), synthetic
# generation, manual curation. Quality scored by GuardedScorer during market hours.
# Written by: data_collector, synthetic_generator. Read by: trainer, scorer.
_register(TableDef(
    name="training_examples",
    description="Curated instruction/output pairs for LLM fine-tuning",
    columns=[
        ColumnDef("example_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("source", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT"),
        ColumnDef("recommendation_id", "TEXT"),
        ColumnDef("feature_snapshot", "TEXT"),
        ColumnDef("trade_outcome", "TEXT"),
        ColumnDef("instruction", "TEXT", nullable=False),
        ColumnDef("input_text", "TEXT", nullable=False),
        ColumnDef("output_text", "TEXT", nullable=False),
        ColumnDef("quality_score", "REAL"),
        ColumnDef("difficulty", "TEXT"),
        ColumnDef("curriculum_stage", "TEXT"),
        ColumnDef("quality_score_auto", "REAL"),
        # updated_at: set by GuardedScorer when quality_score_auto is rewritten
        # between-scans. Distinct from created_at which is immutable per example.
        ColumnDef("updated_at", "TEXT"),
        ColumnDef("outcome_type", "TEXT"),
        ColumnDef("regime", "TEXT"),
        # 8-dimension rubric scores (1-5 each) per Gold-Standard Rubric doc.
        # Written by LLM-as-judge rubric scorer. composite_score is the weighted average.
        ColumnDef("temporal_honesty", "REAL"),
        ColumnDef("evidence_integration", "REAL"),
        ColumnDef("risk_specificity", "REAL"),
        ColumnDef("uncertainty_calibration", "REAL"),
        ColumnDef("structural_compliance", "REAL"),
        ColumnDef("analytical_depth", "REAL"),
        ColumnDef("source_coverage", "REAL"),
        ColumnDef("actionability", "REAL"),
        ColumnDef("composite_score", "REAL"),
    ],
    primary_key="example_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="example_id",
))

# model_evaluations: Champion-challenger A/B test results.
# Written by: evaluator. Read by: trainer (to decide promotion). Not synced to Postgres.
_register(TableDef(
    name="model_evaluations",
    description="A/B comparisons between current and candidate models",
    columns=[
        ColumnDef("evaluation_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("recommendation_id", "TEXT"),
        ColumnDef("ticker", "TEXT"),
        ColumnDef("input_text", "TEXT", nullable=False),
        ColumnDef("current_model", "TEXT", nullable=False),
        ColumnDef("current_output", "TEXT"),
        ColumnDef("current_score", "REAL"),
        ColumnDef("new_model", "TEXT", nullable=False),
        ColumnDef("new_output", "TEXT"),
        ColumnDef("new_score", "REAL"),
        ColumnDef("winner", "TEXT"),
        ColumnDef("score_delta", "REAL"),
    ],
    primary_key="evaluation_id",
    sync_to_postgres=False,
))

# audit_reports: Daily (4:15 PM) and weekly (Saturday) audit results.
# Written by: auditor.run_daily_audit. Read by: dashboard, watch loop banner.
_register(TableDef(
    name="audit_reports",
    description="Periodic audit reports on model and system health",
    columns=[
        ColumnDef("audit_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("audit_date", "TEXT", nullable=False),
        ColumnDef("overall_assessment", "TEXT", nullable=False),
        ColumnDef("summary", "TEXT"),
        ColumnDef("flags", "TEXT"),
        ColumnDef("metrics_to_watch", "TEXT"),
        ColumnDef("model_health", "TEXT"),
        ColumnDef("full_report", "TEXT"),
    ],
    primary_key="audit_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="audit_id",
))

_register(TableDef(
    name="metric_snapshots",
    description="Daily snapshots of key system metrics",
    columns=[
        ColumnDef("snapshot_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("snapshot_date", "TEXT", nullable=False),
        ColumnDef("metrics_json", "TEXT", nullable=False),
    ],
    primary_key="snapshot_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="snapshot_id",
))

# api_costs: Token-level cost tracking for Ollama/external LLM calls.
# Written by: llm.client. Read by: dashboard cost analysis.
_register(TableDef(
    name="api_costs",
    description="LLM API usage and cost tracking",
    columns=[
        ColumnDef("cost_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("model", "TEXT", nullable=False),
        ColumnDef("purpose", "TEXT", nullable=False),
        ColumnDef("input_tokens", "INTEGER", nullable=False),
        ColumnDef("output_tokens", "INTEGER", nullable=False),
        ColumnDef("cost_dollars", "REAL", nullable=False,
                   description="Legacy: was 'estimated_cost' in some modules"),
    ],
    primary_key="cost_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="cost_id",
))

# preference_pairs: DPO (Direct Preference Optimization) training data.
# Written by: preference generator. Not synced — local training only.
_register(TableDef(
    name="preference_pairs",
    description="DPO preference pairs for RLHF-style training",
    columns=[
        ColumnDef("pair_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT"),
        ColumnDef("scan_date", "TEXT"),
        ColumnDef("input_text", "TEXT", nullable=False),
        ColumnDef("chosen_output", "TEXT", nullable=False),
        ColumnDef("rejected_output", "TEXT", nullable=False),
        ColumnDef("chosen_source", "TEXT"),
        ColumnDef("rejected_source", "TEXT"),
        ColumnDef("quality_delta", "REAL"),
        ColumnDef("notes", "TEXT"),
    ],
    primary_key="pair_id",
    sync_to_postgres=False,
))

# canary_evaluations: Runs after each training cycle to detect quality degradation.
# If distinct_1/distinct_2 drop or self_bleu rises, the model may be mode-collapsing.
# Written by: canary_eval. Read by: auditor, dashboard.
_register(TableDef(
    name="canary_evaluations",
    description="Canary eval runs to detect model quality degradation",
    columns=[
        ColumnDef("eval_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("model_version", "TEXT", nullable=False),
        ColumnDef("avg_score", "REAL"),
        ColumnDef("score_delta_pct", "REAL"),
        ColumnDef("distinct_1", "REAL"),
        ColumnDef("distinct_2", "REAL"),
        ColumnDef("self_bleu", "REAL"),
        ColumnDef("vocab_size", "INTEGER"),
        ColumnDef("degradation_detected", "INTEGER", default="0"),
        ColumnDef("details", "TEXT"),
    ],
    primary_key="eval_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="eval_id",
))

# ---------------------------------------------------------------------------
# Council (6 tables)
# Multi-agent deliberation system where specialized LLM agents (momentum,
# macro, risk, contrarian) vote on market regime and trade qualification.
# Runs daily at 8:30 AM before the first scan.
# ---------------------------------------------------------------------------

# council_sessions: One row per daily council session with consensus and cost.
# Written by: council.engine. Read by: dashboard, pre-market brief.
_register(TableDef(
    name="council_sessions",
    description="Multi-agent council deliberation sessions",
    columns=[
        ColumnDef("session_id", "TEXT", nullable=False),
        ColumnDef("session_type", "TEXT", nullable=False, default="daily"),
        ColumnDef("trigger_reason", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("consensus", "TEXT"),
        ColumnDef("confidence_weighted_score", "REAL"),
        ColumnDef("is_contested", "INTEGER", default="0"),
        ColumnDef("total_cost", "REAL"),
        ColumnDef("rounds_completed", "INTEGER", default="0"),
        ColumnDef("result_json", "TEXT"),
    ],
    primary_key="session_id",
    indexes=[
        IndexDef("idx_council_sessions_created", ["created_at"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="session_id",
))

_register(TableDef(
    name="council_votes",
    description="Individual agent votes within council sessions",
    columns=[
        ColumnDef("vote_id", "TEXT", nullable=False),
        ColumnDef("session_id", "TEXT", nullable=False),
        ColumnDef("agent_name", "TEXT", nullable=False),
        ColumnDef("round", "INTEGER", nullable=False),
        ColumnDef("position", "TEXT"),
        ColumnDef("confidence", "INTEGER"),
        ColumnDef("recommendation", "TEXT"),
        ColumnDef("key_data_points", "TEXT"),
        ColumnDef("risk_flags", "TEXT"),
        ColumnDef("vote", "TEXT"),
        ColumnDef("is_devils_advocate", "INTEGER", default="0"),
        ColumnDef("direction", "TEXT"),
        ColumnDef("confidence_float", "REAL"),
        ColumnDef("assessment_json", "TEXT"),
    ],
    primary_key="vote_id",
    indexes=[
        IndexDef("idx_council_votes_session", ["session_id"]),
    ],
    foreign_keys=[
        ForeignKeyDef("session_id", "council_sessions", "session_id"),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column=None,
    sync_pk="vote_id",
))

_register(TableDef(
    name="council_calibrations",
    description="Agent prediction calibration tracking",
    columns=[
        ColumnDef("calibration_id", "TEXT", nullable=False),
        ColumnDef("session_id", "TEXT", nullable=False),
        ColumnDef("agent_name", "TEXT", nullable=False),
        ColumnDef("prediction", "TEXT", nullable=False),
        ColumnDef("prediction_confidence", "REAL", nullable=False),
        ColumnDef("verification_date", "TEXT", nullable=False),
        ColumnDef("actual_outcome", "TEXT"),
        ColumnDef("correct", "INTEGER"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="calibration_id",
    indexes=[
        IndexDef("idx_council_calibrations_session", ["session_id"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="calibration_id",
))

_register(TableDef(
    name="council_debug_log",
    description="Raw LLM request/response debug traces for council agents",
    columns=[
        ColumnDef("debug_id", "TEXT", nullable=False),
        ColumnDef("session_id", "TEXT", nullable=False),
        ColumnDef("agent_name", "TEXT", nullable=False),
        ColumnDef("round", "INTEGER", nullable=False),
        ColumnDef("system_prompt_hash", "TEXT"),
        ColumnDef("user_message", "TEXT"),
        ColumnDef("raw_response", "TEXT"),
        ColumnDef("parsed_successfully", "INTEGER", default="0"),
        ColumnDef("parse_error", "TEXT"),
        ColumnDef("latency_ms", "INTEGER"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="debug_id",
    indexes=[
        IndexDef("idx_council_debug_session", ["session_id"]),
    ],
    foreign_keys=[
        ForeignKeyDef("session_id", "council_sessions", "session_id"),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="debug_id",
))

# council_parameter_log: Tracks when the council adjusts risk parameters
# (e.g., position size multiplier) with before/after values and an attribution
# window to measure whether the adjustment helped or hurt performance.
_register(TableDef(
    name="council_parameter_log",
    description="Council-adjusted parameter changes with attribution windows",
    columns=[
        ColumnDef("log_id", "TEXT", nullable=False),
        ColumnDef("session_id", "TEXT", nullable=False),
        ColumnDef("agent_name", "TEXT"),
        ColumnDef("parameter_name", "TEXT", nullable=False),
        ColumnDef("default_value", "REAL", nullable=False),
        ColumnDef("council_value", "REAL", nullable=False),
        ColumnDef("applied_value", "REAL", nullable=False),
        ColumnDef("rate_limited", "INTEGER", default="0"),
        ColumnDef("attribution_start", "TEXT", nullable=False),
        ColumnDef("attribution_end", "TEXT"),
        ColumnDef("trades_during_window", "INTEGER", default="0"),
        ColumnDef("pnl_during_window", "REAL"),
        ColumnDef("counterfactual_pnl", "REAL"),
        ColumnDef("value_added_dollars", "REAL"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="log_id",
    indexes=[
        IndexDef("idx_param_log_session", ["session_id"]),
        IndexDef("idx_param_log_window", ["attribution_start", "attribution_end"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="log_id",
))

_register(TableDef(
    name="council_parameter_state",
    description="Current state of council-adjustable parameters",
    columns=[
        ColumnDef("parameter_name", "TEXT", nullable=False),
        ColumnDef("current_value", "REAL", nullable=False),
        ColumnDef("default_value", "REAL", nullable=False),
        ColumnDef("last_session_id", "TEXT"),
        ColumnDef("last_updated", "TEXT", nullable=False),
    ],
    primary_key="parameter_name",
    sync_to_postgres=True,
    sync_mode="full",
    sync_time_column=None,
    sync_pk="parameter_name",
))

# ---------------------------------------------------------------------------
# Data Collection (12 tables)
# Written by overnight collectors (9:30 PM daily). Each table has its own
# collector module in src/data_collection/. Sync modes vary:
#   - "incremental": new rows sync to Postgres on each cycle
#   - "latest_only": only most recent data syncs (saves Postgres storage)
# ---------------------------------------------------------------------------

# edgar_filings: 10-K, 10-Q, 8-K filings from SEC EDGAR with NLP sentiment.
# sync_conflict_col: accession_number is the natural unique key, not the integer PK.
# Fix for #185: Without this, Postgres UPSERT used the autoincrement id,
# causing duplicate key errors on re-sync.
_register(TableDef(
    name="edgar_filings",
    description="SEC EDGAR filings with full text and sentiment analysis",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("cik", "TEXT", nullable=False),
        ColumnDef("form_type", "TEXT", nullable=False),
        ColumnDef("filing_date", "TEXT", nullable=False),
        ColumnDef("accession_number", "TEXT", nullable=False),
        ColumnDef("filing_url", "TEXT"),
        ColumnDef("description", "TEXT"),
        ColumnDef("full_text", "TEXT"),
        ColumnDef("sections_json", "TEXT"),
        ColumnDef("word_count", "INTEGER"),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("sentiment_polarity", "REAL"),
        ColumnDef("sentiment_negative_count", "INTEGER"),
        ColumnDef("sentiment_uncertainty_count", "INTEGER"),
        ColumnDef("cautionary_phrases", "TEXT"),
        ColumnDef("sentiment_delta_polarity", "REAL"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_edgar_ticker_date", ["ticker", "filing_date"]),
        IndexDef("idx_edgar_accession", ["accession_number"], unique=True),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
    sync_conflict_col="accession_number",
))

_register(TableDef(
    name="insider_transactions",
    description="Insider buying/selling transactions from Finnhub",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("insider_name", "TEXT"),
        ColumnDef("title", "TEXT"),
        ColumnDef("transaction_type", "TEXT"),
        ColumnDef("transaction_date", "TEXT"),
        ColumnDef("filing_date", "TEXT"),
        ColumnDef("shares", "REAL"),
        ColumnDef("price", "REAL"),
        ColumnDef("value", "REAL"),
        ColumnDef("shares_after", "REAL"),
        ColumnDef("ownership_type", "TEXT"),
        ColumnDef("source", "TEXT", default="finnhub"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_insider_ticker_date", ["ticker", "filing_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
))

_register(TableDef(
    name="short_interest",
    description="Short interest data with days-to-cover and float percentage",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("settlement_date", "TEXT", nullable=False),
        ColumnDef("short_interest", "REAL"),
        ColumnDef("avg_daily_volume", "REAL"),
        ColumnDef("days_to_cover", "REAL"),
        ColumnDef("short_pct_float", "REAL"),
        ColumnDef("source", "TEXT", default="finnhub"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_short_interest_ticker_date", ["ticker", "settlement_date"]),
        IndexDef("idx_short_interest_unique", ["ticker", "settlement_date"],
                 unique=True),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
))

_register(TableDef(
    name="fed_communications",
    description="Federal Reserve speeches, minutes, and press conferences",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("comm_type", "TEXT", nullable=False),
        ColumnDef("title", "TEXT"),
        ColumnDef("date", "TEXT", nullable=False),
        ColumnDef("speaker", "TEXT"),
        ColumnDef("url", "TEXT"),
        ColumnDef("full_text", "TEXT"),
        ColumnDef("word_count", "INTEGER"),
        ColumnDef("sentiment", "TEXT"),
        ColumnDef("key_phrases", "TEXT"),
        ColumnDef("source", "TEXT"),
        ColumnDef("event_type", "TEXT"),
        ColumnDef("event_date", "TEXT"),
        ColumnDef("summary", "TEXT"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_fed_comm_type_date", ["comm_type", "date"]),
        IndexDef("idx_fed_unique", ["comm_type", "date", "title"], unique=True),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
))

_register(TableDef(
    name="analyst_estimates",
    description="Analyst consensus estimates, price targets, and earnings surprises",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("date", "TEXT", nullable=False),
        ColumnDef("consensus_buy", "INTEGER"),
        ColumnDef("consensus_hold", "INTEGER"),
        ColumnDef("consensus_sell", "INTEGER"),
        ColumnDef("consensus_strong_buy", "INTEGER"),
        ColumnDef("consensus_strong_sell", "INTEGER"),
        ColumnDef("price_target_high", "REAL"),
        ColumnDef("price_target_low", "REAL"),
        ColumnDef("price_target_mean", "REAL"),
        ColumnDef("price_target_median", "REAL"),
        ColumnDef("num_analysts", "INTEGER"),
        ColumnDef("metric", "TEXT"),
        ColumnDef("period", "TEXT"),
        ColumnDef("estimate", "REAL"),
        ColumnDef("actual", "REAL"),
        ColumnDef("surprise", "REAL"),
        ColumnDef("surprise_pct", "REAL"),
        ColumnDef("source", "TEXT", default="finnhub"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_analyst_ticker_date", ["ticker", "date"]),
        IndexDef("idx_analyst_unique", ["ticker", "date", "source"], unique=True),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
))

_register(TableDef(
    name="options_chains",
    description="Options chain snapshots with Greeks and volume data",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("expiration", "TEXT", nullable=False),
        ColumnDef("strike", "REAL", nullable=False),
        ColumnDef("option_type", "TEXT", nullable=False),
        ColumnDef("bid", "REAL"),
        ColumnDef("ask", "REAL"),
        ColumnDef("last_price", "REAL"),
        ColumnDef("volume", "INTEGER"),
        ColumnDef("open_interest", "INTEGER"),
        ColumnDef("implied_volatility", "REAL"),
        ColumnDef("delta", "REAL"),
        ColumnDef("gamma", "REAL"),
        ColumnDef("theta", "REAL"),
        ColumnDef("vega", "REAL"),
        ColumnDef("in_the_money", "INTEGER"),
        ColumnDef("underlying_price", "REAL"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_options_chains_ticker_date", ["ticker", "collected_at"]),
        IndexDef("idx_options_chains_collected", ["collected_at"]),
        IndexDef("idx_options_chains_expiration", ["ticker", "expiration"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",
    sync_time_column="collected_at",
    sync_pk="id",
))

_register(TableDef(
    name="options_metrics",
    description="Derived options metrics: IV rank, put/call ratios, unusual activity",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("collected_date", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("iv_rank", "REAL"),
        ColumnDef("iv_percentile", "REAL"),
        ColumnDef("put_call_volume_ratio", "REAL"),
        ColumnDef("put_call_oi_ratio", "REAL"),
        ColumnDef("atm_iv_30d", "REAL"),
        ColumnDef("iv_skew", "REAL"),
        ColumnDef("unusual_volume_flag", "INTEGER"),
        ColumnDef("max_unusual_volume_ratio", "REAL"),
        ColumnDef("total_call_volume", "INTEGER"),
        ColumnDef("total_put_volume", "INTEGER"),
        ColumnDef("total_call_oi", "INTEGER"),
        ColumnDef("total_put_oi", "INTEGER"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_options_metrics_ticker_date", ["ticker", "collected_date"]),
        IndexDef("idx_options_metrics_date", ["collected_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",
    sync_time_column="collected_date",
    sync_pk="id",
))

_register(TableDef(
    name="cboe_ratios",
    description="CBOE equity/index put-call ratios",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("collected_date", "TEXT", nullable=False),
        ColumnDef("equity_pc_ratio", "REAL"),
        ColumnDef("index_pc_ratio", "REAL"),
        ColumnDef("total_pc_ratio", "REAL"),
        ColumnDef("equity_pc_vs_20d_avg", "REAL"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_cboe_ratios_date", ["collected_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",
    sync_time_column="collected_date",
    sync_pk="id",
))

_register(TableDef(
    name="google_trends",
    description="Google Trends search interest for tracked tickers",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("collected_date", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("search_interest", "REAL"),
        ColumnDef("interest_vs_90d_avg", "REAL"),
        ColumnDef("spike_flag", "INTEGER"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_google_trends_ticker_date", ["ticker", "collected_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",
    sync_time_column="collected_date",
    sync_pk="id",
))

# vix_term_structure: VIX spot + 9d/3m/1y tenors for regime classification.
# term_structure_slope and near_term_ratio drive the traffic light state machine.
# Written by: vix_collector. Read by: regime classifier, pre-market brief.
_register(TableDef(
    name="vix_term_structure",
    description="VIX term structure snapshots across tenors",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("collected_date", "TEXT", nullable=False),
        ColumnDef("vix", "REAL"),
        ColumnDef("vix9d", "REAL"),
        ColumnDef("vix3m", "REAL"),
        ColumnDef("vix1y", "REAL"),
        ColumnDef("term_structure_slope", "REAL"),
        ColumnDef("near_term_ratio", "REAL"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_vix_ts_date", ["collected_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",
    sync_time_column="collected_date",
    sync_pk="id",
))

_register(TableDef(
    name="macro_snapshots",
    description="FRED macroeconomic series snapshots",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),
        ColumnDef("collected_date", "TEXT", nullable=False),
        ColumnDef("series_id", "TEXT", nullable=False),
        ColumnDef("series_name", "TEXT", nullable=False),
        ColumnDef("value", "REAL"),
        ColumnDef("previous_value", "REAL"),
        ColumnDef("change_pct", "REAL"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_macro_snapshots_date", ["collected_date"]),
        IndexDef("idx_macro_snapshots_series", ["series_id", "collected_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",
    sync_time_column="collected_date",
    sync_pk="id",
    # #332: Add conflict key to prevent duplicate key errors on re-sync
    sync_conflict_col="series_id",
))

_register(TableDef(
    name="earnings_calendar",
    description="Upcoming earnings dates for universe tickers",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("earnings_date", "TEXT", nullable=False),
        ColumnDef("earnings_time", "TEXT"),
        ColumnDef("confirmed", "INTEGER", default="0"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
))

# ---------------------------------------------------------------------------
# Research (3 tables)
# ---------------------------------------------------------------------------

_register(TableDef(
    name="research_papers",
    description="Academic and industry research papers with relevance scoring",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("source", "TEXT", nullable=False),
        ColumnDef("external_id", "TEXT"),
        ColumnDef("title", "TEXT", nullable=False),
        ColumnDef("authors", "TEXT"),
        ColumnDef("abstract", "TEXT"),
        ColumnDef("url", "TEXT", nullable=False),
        ColumnDef("published_date", "TEXT"),
        ColumnDef("categories", "TEXT"),
        ColumnDef("relevance_score", "REAL"),
        ColumnDef("relevance_reason", "TEXT"),
        ColumnDef("full_text", "TEXT"),
        ColumnDef("actionable", "INTEGER", default="0"),
        ColumnDef("action_taken", "TEXT"),
        ColumnDef("collected_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="collected_at",
    sync_pk="id",
))

_register(TableDef(
    name="research_digests",
    description="Weekly research digest summaries",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("week_start", "TEXT", nullable=False),
        ColumnDef("week_end", "TEXT", nullable=False),
        ColumnDef("papers_reviewed", "INTEGER"),
        ColumnDef("actionable_count", "INTEGER"),
        ColumnDef("digest_text", "TEXT"),
        ColumnDef("threats", "TEXT"),
        ColumnDef("opportunities", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="id",
))

_register(TableDef(
    name="research_docs",
    description="Uploaded research documents and reference materials",
    columns=[
        ColumnDef("id", "TEXT", nullable=False),
        ColumnDef("filename", "TEXT", nullable=False),
        ColumnDef("title", "TEXT", nullable=False),
        ColumnDef("category", "TEXT", nullable=False, default="Uncategorized"),
        ColumnDef("content", "TEXT", nullable=False),
        ColumnDef("size_kb", "REAL", nullable=False, default="0"),
        ColumnDef("updated_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="updated_at",
    sync_pk="id",
))

# ---------------------------------------------------------------------------
# Signals (2 tables)
# ---------------------------------------------------------------------------

# setup_signals: Every technical setup detected by the signal zoo, whether
# traded or not. Forward returns (1d/5d/10d/20d) are backfilled for
# signal-level performance analysis. This is the "signal zoo" asset.
_register(TableDef(
    name="setup_signals",
    description="Technical setup signal detections with forward returns",
    columns=[
        ColumnDef("signal_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("date", "TEXT", nullable=False),
        ColumnDef("setup_type", "TEXT", nullable=False),
        ColumnDef("confidence", "REAL"),
        ColumnDef("theoretical_entry", "REAL"),
        ColumnDef("theoretical_stop", "REAL"),
        ColumnDef("theoretical_target", "REAL"),
        ColumnDef("regime", "TEXT"),
        ColumnDef("adx", "REAL"),
        ColumnDef("atr_ratio", "REAL"),
        ColumnDef("rsi", "REAL"),
        ColumnDef("volume_profile", "TEXT"),
        ColumnDef("actual_return_1d", "REAL"),
        ColumnDef("actual_return_5d", "REAL"),
        ColumnDef("actual_return_10d", "REAL"),
        ColumnDef("actual_return_20d", "REAL"),
        ColumnDef("was_traded", "INTEGER", default="0"),
    ],
    primary_key="signal_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="signal_id",
))

# traffic_light_state: Singleton row (id=1) holding the current market regime.
# Uses a state machine with confirmation counts to prevent whipsawing between
# GREEN/YELLOW/RED. Written by: regime classifier. Read by: risk governor.
_register(TableDef(
    name="traffic_light_state",
    description="Market regime traffic light state machine",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("current_regime", "TEXT", nullable=False, default="GREEN"),
        ColumnDef("pending_regime", "TEXT"),
        ColumnDef("pending_count", "INTEGER", default="0"),
        ColumnDef("last_vix_score", "INTEGER", default="0"),
        ColumnDef("last_trend_score", "INTEGER", default="0"),
        ColumnDef("last_credit_score", "INTEGER", default="0"),
        ColumnDef("last_total_score", "INTEGER", default="0"),
        ColumnDef("updated_at", "TEXT"),
        ColumnDef("last_transition_at", "TEXT"),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="full",
    sync_time_column=None,
    sync_pk="id",
))

# ---------------------------------------------------------------------------
# Evaluation & Metrics (4 tables)
# ---------------------------------------------------------------------------

# scan_metrics: One row per scan cycle. Tracks the full pipeline funnel:
# universe_count -> features_count -> scored_count -> packet_worthy -> risk_passed -> traded.
# Written by: watch._record_scan_metrics. Read by: dashboard, EOD report.
_register(TableDef(
    name="scan_metrics",
    description="Per-scan pipeline metrics and throughput counters",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("scan_number", "INTEGER"),
        ColumnDef("scan_time", "TEXT"),
        ColumnDef("universe_count", "INTEGER"),
        ColumnDef("features_count", "INTEGER"),
        ColumnDef("scored_count", "INTEGER"),
        ColumnDef("packet_worthy", "INTEGER"),
        ColumnDef("risk_passed", "INTEGER"),
        ColumnDef("paper_traded", "INTEGER"),
        ColumnDef("live_traded", "INTEGER"),
        ColumnDef("llm_success", "INTEGER"),
        ColumnDef("llm_total", "INTEGER"),
        ColumnDef("llm_fallback", "INTEGER"),
        ColumnDef("avg_conviction", "REAL"),
        ColumnDef("duration_seconds", "REAL"),
        ColumnDef("created_at", "TEXT"),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="id",
))

_register(TableDef(
    name="schedule_metrics",
    description="Daily schedule execution metrics",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("metric_date", "TEXT", nullable=False),
        ColumnDef("metric_name", "TEXT", nullable=False),
        ColumnDef("metric_value", "REAL"),
        ColumnDef("details", "TEXT"),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="metric_date",
    sync_pk="id",
))

_register(TableDef(
    name="quality_drift_metrics",
    description="Training quality drift detection metrics per cycle",
    columns=[
        ColumnDef("metric_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("cycle_number", "INTEGER"),
        ColumnDef("model_version", "TEXT"),
        ColumnDef("distinct_1", "REAL"),
        ColumnDef("distinct_2", "REAL"),
        ColumnDef("self_bleu", "REAL"),
        ColumnDef("vocab_size", "INTEGER"),
        ColumnDef("avg_length", "REAL"),
        ColumnDef("degradation_flag", "INTEGER", default="0"),
        ColumnDef("details", "TEXT"),
    ],
    primary_key="metric_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="metric_id",
))

# build_score_history: Daily composite score (0-100) measuring overall system
# maturity across 6 dimensions: gate velocity, health, data assets, model quality,
# research velocity, reliability. Persisted at 4:45 PM daily.
_register(TableDef(
    name="build_score_history",
    description="Daily composite build score with component breakdowns",
    columns=[
        ColumnDef("score_id", "TEXT", nullable=False),
        ColumnDef("score_date", "TEXT"),
        ColumnDef("build_score", "REAL"),
        ColumnDef("gate_velocity", "REAL"),
        ColumnDef("system_health", "REAL"),
        ColumnDef("data_asset_value", "REAL"),
        ColumnDef("model_quality", "REAL"),
        ColumnDef("research_velocity", "REAL"),
        ColumnDef("reliability", "REAL"),
        ColumnDef("decay_applied", "INTEGER", default="0"),
        ColumnDef("components_json", "TEXT"),
        ColumnDef("created_at", "TEXT"),
    ],
    primary_key="score_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="score_id",
))

# ---------------------------------------------------------------------------
# Infrastructure (6 tables)
# ---------------------------------------------------------------------------

# activity_log: High-level event log (not debug-level). Events like "trade_opened",
# "overnight_task", "dd_alert_5". Written by: activity_logger throughout codebase.
_register(TableDef(
    name="activity_log",
    description="System-wide event log for all notable actions",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("event_type", "TEXT", nullable=False),
        ColumnDef("detail", "TEXT"),
        ColumnDef("level", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="id",
))

# log_entries: WARNING+ log messages from DBLogHandler in watch.py.
# Powers the dashboard's live log viewer. Pruned to 500 entries max.
_register(TableDef(
    name="log_entries",
    description="Structured log entries with source and severity",
    columns=[
        ColumnDef("log_id", "TEXT", nullable=False),
        ColumnDef("log_level", "TEXT", nullable=False),
        ColumnDef("source", "TEXT", nullable=False),
        ColumnDef("message", "TEXT", nullable=False),
        ColumnDef("details_json", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="log_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="log_id",
))

# sync_state: Cursor tracking for render_sync. One row per table with the
# last_synced_at timestamp. NOT synced to Postgres (that would be circular).
_register(TableDef(
    name="sync_state",
    description="Tracks last sync timestamp per table for incremental sync",
    columns=[
        ColumnDef("table_name", "TEXT", nullable=False),
        ColumnDef("last_synced_at", "TEXT", nullable=False),
    ],
    primary_key="table_name",
    sync_to_postgres=False,
))

_register(TableDef(
    name="command_results",
    description="Results of remotely-issued commands",
    columns=[
        ColumnDef("result_id", "TEXT", nullable=False),
        ColumnDef("command_id", "TEXT", nullable=False),
        ColumnDef("status", "TEXT", nullable=False),
        ColumnDef("result_json", "TEXT", default="{}"),
        ColumnDef("error_message", "TEXT"),
        ColumnDef("execution_ms", "INTEGER"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="result_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="result_id",
))

_register(TableDef(
    name="config_overrides",
    description="Dashboard-pushed configuration overrides (pulled from cloud)",
    columns=[
        ColumnDef("setting_key", "TEXT", nullable=False),
        ColumnDef("setting_value", "TEXT", nullable=False),
        ColumnDef("previous_value", "TEXT"),
        ColumnDef("updated_at", "TEXT", nullable=False),
        ColumnDef("updated_by", "TEXT", default="dashboard"),
    ],
    primary_key="setting_key",
    sync_to_postgres=False,
))

# pending_commands: Remote command queue. Dashboard pushes commands to Postgres,
# render_sync pulls them to SQLite, watch loop's command executor runs them.
# NOT synced to Postgres (commands flow Postgres -> SQLite, not the reverse).
_register(TableDef(
    name="pending_commands",
    description="Remote commands queued for local execution (pulled from cloud)",
    columns=[
        ColumnDef("command_id", "TEXT", nullable=False),
        ColumnDef("command_type", "TEXT", nullable=False),
        ColumnDef("command_name", "TEXT", nullable=False),
        ColumnDef("payload_json", "TEXT", default="{}"),
        ColumnDef("status", "TEXT", nullable=False, default="pending"),
        ColumnDef("priority", "INTEGER", default="0"),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("claimed_at", "TEXT"),
        ColumnDef("expires_at", "TEXT"),
        ColumnDef("created_by", "TEXT", default="dashboard"),
    ],
    primary_key="command_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
))

# ---------------------------------------------------------------------------
# User Data (1 table)
# ---------------------------------------------------------------------------

_register(TableDef(
    name="user_notes",
    description="User-created notes with tags and pin support",
    columns=[
        ColumnDef("note_id", "TEXT", nullable=False),
        ColumnDef("title", "TEXT", nullable=False),
        ColumnDef("content", "TEXT", default=""),
        ColumnDef("tags", "TEXT", default="[]"),
        ColumnDef("pinned", "INTEGER", default="0"),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("updated_at", "TEXT", nullable=False),
    ],
    primary_key="note_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="updated_at",
    sync_pk="note_id",
))

# ---------------------------------------------------------------------------
# Trading Internals (1 table)
# ---------------------------------------------------------------------------

# bracket_health: Audit trail for bracket order integrity checks.
# Runs pre-market, intraday (every 5 min), and post-close to verify
# that stop-loss and take-profit legs are still active on Alpaca.
# NOT synced to Postgres — local diagnostics only.
_register(TableDef(
    name="bracket_health",
    description="Bracket order health checks for open positions",
    columns=[
        ColumnDef("check_id", "TEXT", nullable=False),
        ColumnDef("trade_id", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("stop_leg_status", "TEXT"),
        ColumnDef("target_leg_status", "TEXT"),
        ColumnDef("bracket_intact", "INTEGER", default="1"),
        ColumnDef("action_taken", "TEXT"),
        ColumnDef("checked_at", "TEXT", nullable=False),
    ],
    primary_key="check_id",
    sync_to_postgres=False,
))

# ---------------------------------------------------------------------------
# Alpha Attribution (Sprint 3)
# Measures whether the LLM adds value beyond the quantitative ranker.
# For each trade, we track both the actual (LLM-influenced) outcome and a
# counterfactual (ranker-only) outcome to compute the LLM's alpha.
# ---------------------------------------------------------------------------

# attribution_trades: Paired comparison of LLM-influenced vs ranker-only outcomes.
# Written by: attribution.logger. Resolved at 4:30 PM daily.
_register(TableDef(
    name="attribution_trades",
    description="Paired LLM vs ranker-only trade attribution for alpha measurement",
    columns=[
        ColumnDef("attribution_id", "TEXT", nullable=False),
        ColumnDef("recommendation_id", "TEXT"),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("scan_timestamp", "TEXT"),
        ColumnDef("ranker_score", "REAL"),
        ColumnDef("llm_conviction", "INTEGER"),
        ColumnDef("llm_action", "TEXT"),
        ColumnDef("ranker_only_entry", "REAL"),
        ColumnDef("ranker_only_stop", "REAL"),
        ColumnDef("ranker_only_target", "REAL"),
        ColumnDef("ranker_only_outcome", "TEXT"),
        ColumnDef("ranker_only_pnl_pct", "REAL"),
        ColumnDef("llm_portfolio_outcome", "TEXT"),
        ColumnDef("llm_portfolio_pnl_pct", "REAL"),
        ColumnDef("pair_type", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="attribution_id",
    indexes=[
        IndexDef("idx_attribution_ticker", ["ticker"]),
        IndexDef("idx_attribution_created", ["created_at"]),
        IndexDef("idx_attribution_pair_type", ["pair_type"]),
    ],
    foreign_keys=[
        ForeignKeyDef("recommendation_id", "recommendations", "recommendation_id"),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
))

# ---------------------------------------------------------------------------
# Data Freshness (Sprint 5)
# Strategy Decision #22: 4-tier multi-cadence scanning requires knowing when
# each data source was last fetched for each ticker, so stale data can be
# re-fetched at the appropriate cadence without redundant API calls.
# ---------------------------------------------------------------------------

# data_freshness: Composite PK (source, ticker). NOT synced — local optimization only.
_register(TableDef(
    name="data_freshness",
    description="Per-ticker per-source staleness tracking for multi-cadence scanning",
    columns=[
        ColumnDef("source", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("last_fetched_at", "TEXT", nullable=False),
        ColumnDef("status", "TEXT", default="acceptable"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key=["source", "ticker"],
    indexes=[
        IndexDef("idx_freshness_source", ["source"]),
        IndexDef("idx_freshness_ticker", ["ticker"]),
    ],
    sync_to_postgres=False,
))

# ---------------------------------------------------------------------------
# Stress Testing (Sprint 7)
# Backtests the current model against 3 crisis periods (COVID crash, 2022 bear,
# 2023 banking crisis). Runs weekly on Sunday 9 PM and after model version changes.
# ---------------------------------------------------------------------------

# stress_test_results: One row per scenario per run. model_version links to
# the model that was tested, so regressions are detectable across versions.
_register(TableDef(
    name="stress_test_results",
    description="Historical stress test results for crisis period backtesting",
    columns=[
        ColumnDef("result_id", "TEXT", nullable=False),
        ColumnDef("scenario", "TEXT", nullable=False),
        ColumnDef("start_date", "TEXT"),
        ColumnDef("end_date", "TEXT"),
        ColumnDef("total_trades", "INTEGER"),
        ColumnDef("win_rate", "REAL"),
        ColumnDef("total_pnl_pct", "REAL"),
        ColumnDef("max_drawdown_pct", "REAL"),
        ColumnDef("max_drawdown_duration_days", "INTEGER"),
        ColumnDef("calmar_ratio", "REAL"),
        ColumnDef("monthly_returns_json", "TEXT"),
        ColumnDef("regime_breakdown_json", "TEXT"),
        ColumnDef("equity_curve_json", "TEXT"),
        ColumnDef("model_version", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="result_id",
    indexes=[
        IndexDef("idx_stress_scenario", ["scenario"]),
        IndexDef("idx_stress_created", ["created_at"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
))

# ---------------------------------------------------------------------------
# SIMULATION ENGINE
# Full-regime backtesting across 13 market scenarios (10 pure + 3 transitions).
# Weekly Sunday 9:30 PM run + post-retrain regression checks. Stores heatmap
# data, Monte Carlo confidence intervals, and traffic light validation.
# ---------------------------------------------------------------------------

_register(TableDef(
    name="simulation_results",
    description="Full-regime simulation engine results — 13 scenarios with MC and TL validation",
    columns=[
        ColumnDef("result_id", "TEXT", nullable=False),
        ColumnDef("run_id", "TEXT", nullable=False),
        ColumnDef("scenario", "TEXT", nullable=False),
        ColumnDef("regime_label", "TEXT", nullable=False),
        ColumnDef("start_date", "TEXT", nullable=False),
        ColumnDef("end_date", "TEXT", nullable=False),
        ColumnDef("total_trades", "INTEGER"),
        ColumnDef("wins", "INTEGER"),
        ColumnDef("losses", "INTEGER"),
        ColumnDef("timeouts", "INTEGER"),
        ColumnDef("win_rate", "REAL"),
        ColumnDef("profit_factor", "REAL"),
        ColumnDef("total_pnl_pct", "REAL"),
        ColumnDef("gross_pnl_pct", "REAL"),
        ColumnDef("net_pnl_pct", "REAL"),
        ColumnDef("max_drawdown_pct", "REAL"),
        ColumnDef("sharpe_ratio", "REAL"),
        ColumnDef("calmar_ratio", "REAL"),
        ColumnDef("benchmark_pnl_pct", "REAL"),
        ColumnDef("excess_return_pct", "REAL"),
        ColumnDef("transaction_cost_bps", "REAL"),
        ColumnDef("mc_median_dd", "REAL"),
        ColumnDef("mc_p95_dd", "REAL"),
        ColumnDef("mc_p5_equity", "REAL"),
        ColumnDef("mc_p95_equity", "REAL"),
        ColumnDef("mc_probability_of_ruin", "REAL"),
        ColumnDef("mc_n_simulations", "INTEGER"),
        ColumnDef("tl_expected", "TEXT"),
        ColumnDef("tl_actual_majority", "TEXT"),
        ColumnDef("tl_correct", "INTEGER"),
        ColumnDef("monthly_returns_json", "TEXT"),
        ColumnDef("equity_curve_json", "TEXT"),
        ColumnDef("regime_breakdown_json", "TEXT"),
        ColumnDef("model_version", "TEXT"),
        ColumnDef("config_json", "TEXT"),
        ColumnDef("verdict", "TEXT"),
        ColumnDef("statistical_confidence", "TEXT"),
        ColumnDef("survivorship_bias", "INTEGER", default="1"),
        ColumnDef("random_seed", "INTEGER"),
        ColumnDef("git_commit", "TEXT"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="result_id",
    indexes=[
        IndexDef("idx_sim_scenario", ["scenario"]),
        IndexDef("idx_sim_run_id", ["run_id"]),
        IndexDef("idx_sim_created", ["created_at"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
))

# ---------------------------------------------------------------------------
# SYSTEM MONITORING
# GPU/CPU/RAM/disk/Ollama health snapshots collected every ~5 minutes by the
# watch loop. Stored locally for the monitoring dashboard.
# ---------------------------------------------------------------------------

_register(TableDef(
    name="system_metrics",
    description="System utilization snapshots (GPU, CPU, RAM, disk, Ollama)",
    columns=[
        ColumnDef("snapshot_id", "TEXT", nullable=False),
        ColumnDef("timestamp", "TEXT", description="ISO timestamp ET"),
        ColumnDef("gpu_util_pct", "REAL"),
        ColumnDef("gpu_vram_used_mb", "REAL"),
        ColumnDef("gpu_vram_total_mb", "REAL"),
        ColumnDef("gpu_temp_c", "REAL"),
        ColumnDef("gpu_power_w", "REAL"),
        ColumnDef("cpu_pct", "REAL"),
        ColumnDef("ram_used_mb", "REAL"),
        ColumnDef("ram_total_mb", "REAL"),
        ColumnDef("disk_used_gb", "REAL"),
        ColumnDef("disk_total_gb", "REAL"),
        ColumnDef("ollama_status", "TEXT", description="running, stopped, error"),
        ColumnDef("ollama_model", "TEXT"),
        ColumnDef("python_rss_mb", "REAL", description="Current process RSS"),
    ],
    primary_key="snapshot_id",
    indexes=[
        IndexDef("idx_sysmetrics_ts", ["timestamp"]),
    ],
    sync_to_postgres=False,
    sync_mode="incremental",
    sync_time_column="timestamp",
))

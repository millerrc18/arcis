"""Schema Registry — Single source of truth for all database tables.

Every table, column, index, and foreign key is defined here.
No other file in the codebase should contain CREATE TABLE statements.

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
    sync_to_postgres: bool = True
    sync_mode: str = "incremental"  # incremental, full, latest_only
    sync_time_column: str | None = "created_at"
    sync_pk: str | None = None  # Defaults to primary_key if None
    sync_conflict_col: str | None = None  # Override ON CONFLICT target (e.g., UNIQUE columns)


TABLES: dict[str, TableDef] = {}


def _register(table: TableDef) -> None:
    """Register a table definition."""
    TABLES[table.name] = table


# ---------------------------------------------------------------------------
# Trading Core (3 tables)
# ---------------------------------------------------------------------------

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
        ColumnDef("planned_shares", "INTEGER"),
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
        ColumnDef("order_type", "TEXT"),
        ColumnDef("timeout_days", "INTEGER", default="15"),
        ColumnDef("source", "TEXT", default="paper"),
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
        ColumnDef("actual_shares", "INTEGER"),
        ColumnDef("exit_retry_count", "INTEGER", default="0"),
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
# ---------------------------------------------------------------------------

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
        ColumnDef("outcome_type", "TEXT"),
        ColumnDef("regime", "TEXT"),
    ],
    primary_key="example_id",
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="example_id",
))

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
# ---------------------------------------------------------------------------

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
# ---------------------------------------------------------------------------

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
    sync_to_postgres=False,
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

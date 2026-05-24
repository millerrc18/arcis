"""Tests for the schema registry.

Tests are organized into:
1. Basic registry tests — data model works
2. Completeness tests — all expected tables are registered
3. Consistency tests — FK references valid, sync config correct
4. Guardrail tests — no CREATE TABLE / ALTER TABLE outside src/schema/
"""

import json
import os
from pathlib import Path

import pytest

from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef, _register


# ── Basic registry tests ─────────────────────────────────────────

def test_tables_dict_exists():
    assert isinstance(TABLES, dict)


def test_register_adds_table():
    table = TableDef(
        name="_test_table",
        description="Test",
        columns=[ColumnDef("id", "INTEGER", nullable=False)],
        primary_key="id",
    )
    _register(table)
    assert "_test_table" in TABLES
    del TABLES["_test_table"]


# ── Completeness tests ───────────────────────────────────────────

EXPECTED_TABLE_COUNT = 72


def test_registry_has_all_tables():
    """Registry must define at least the expected number of tables.

    Floor lineage: 40 (pre-Sprint-0, wildly stale) -> 68 (current, Sprint-0
    Wave 1e SCHEMA-FLOOR fix). Bump this whenever the registry grows; the
    floor is a regression guard, not a moving target.
    """
    assert len(TABLES) >= EXPECTED_TABLE_COUNT, (
        f"Registry has {len(TABLES)} tables, expected >= {EXPECTED_TABLE_COUNT}. "
        f"Missing tables need to be added to src/schema/registry.py"
    )


EXPECTED_TABLES = {
    # Trading Core
    "shadow_trades", "recommendations", "validation_results",
    "broker_exceptions",
    # Training Pipeline
    "model_versions", "training_examples", "model_evaluations",
    "audit_reports", "metric_snapshots", "api_costs",
    "preference_pairs", "canary_evaluations",
    # Council
    "council_sessions", "council_votes", "council_calibrations",
    "council_debug_log", "council_parameter_log", "council_parameter_state",
    # Data Collection
    "edgar_filings", "insider_transactions", "short_interest",
    "fed_communications", "analyst_estimates", "options_chains",
    "options_metrics", "cboe_ratios", "google_trends",
    "vix_term_structure", "macro_snapshots", "earnings_calendar",
    "minute_bars",
    # Research
    "research_papers", "research_digests", "research_docs",
    # Signals
    "setup_signals", "traffic_light_state",
    # Evaluation & Metrics
    "scan_metrics", "schedule_metrics", "quality_drift_metrics",
    "build_score_history", "system_metrics",
    # Backtest / Walk-forward / Stress / Attribution
    "backtest_results", "backtest_trades",
    "walkforward_results", "walkforward_trades",
    "attribution_trades", "simulation_results", "stress_test_results",
    # Strategy lifecycle
    "strategy_registry", "strategy_promotion_events", "trials_registry",
    # Risk / Factor analytics
    "correlation_matrices", "factor_loadings",
    # Universe (point-in-time)
    "sp100_historical_constituents",
    # Operator state
    "operator_view_state",
    # Health / Freshness
    "data_freshness", "daily_ib_health", "ib_shadow_log",
    # Infrastructure
    "activity_log", "log_entries",
    "command_results", "config_overrides", "pending_commands",
    # User Data
    "user_notes",
    # Dashboard / cloud state
    "preflight_runs",
    # Live runtime
    "live_prices",
    # Trading Internals
    "bracket_health",
    # Diagnostics
    "diagnostic_runs", "diagnostic_run_plots",
    # Notifications (Sprint 4 T14)
    "notifications_sent", "notifications_dedup",
    # Notification digest queue (T11 Wave D D2)
    "notifications_digest_queue",
    # Platform events forensic trail (T2 Wave C #96)
    "platform_events",
    # Sprint 5 Wave C7b — plan-gated Finnhub paid-tier sinks (T21, T22, T23)
    "institutional_holdings", "filings_sentiment", "press_releases",
    # v0.36.13 — FINRA daily short-volume (replaces defunct Finnhub short_interest)
    "short_volume_daily",
    # v0.36.38 — dead-weight Finnhub collectors (T1 foundation: registry + wiring)
    "company_executives", "stock_financials", "price_targets",
}


# ── Diagnostic tables (v0.25.0) ──────────────────────────────────


def test_diagnostic_runs_in_registry():
    """diagnostic_runs must be registered with correct columns and sync config."""
    assert "diagnostic_runs" in TABLES
    td = TABLES["diagnostic_runs"]
    names = [c.name for c in td.columns]
    for expected in [
        "run_id", "diagnostic_type", "status", "trigger_source", "triggered_by",
        "cohort_n", "started_at", "completed_at", "exit_code", "report_markdown",
        "summary_json", "stderr_tail", "payload_json", "created_at", "updated_at",
    ]:
        assert expected in names, f"Missing column: {expected}"
    assert td.primary_key == "run_id"
    assert td.sync_to_postgres is True
    assert td.sync_mode == "incremental"
    assert td.sync_time_column == "updated_at"


def test_diagnostic_run_plots_in_registry():
    """diagnostic_run_plots sibling table must be registered."""
    assert "diagnostic_run_plots" in TABLES
    td = TABLES["diagnostic_run_plots"]
    names = [c.name for c in td.columns]
    for expected in [
        "plot_id", "run_id", "filename", "content_b64", "sort_order", "created_at",
    ]:
        assert expected in names
    assert td.primary_key == "plot_id"
    assert td.sync_to_postgres is True


# ── Training-examples quarantine columns (v0.26.0 — training v1-audit) ──

def test_training_examples_has_quarantine_columns():
    """quarantined + quarantine_reason must exist on training_examples.

    Sprint v0.26.0 (training data v1-audit) depends on these columns to
    flag contaminated rows without deleting them. Regression guard.
    """
    assert "training_examples" in TABLES
    td = TABLES["training_examples"]
    names = [c.name for c in td.columns]
    assert "quarantined" in names, "training_examples missing quarantined column"
    assert "quarantine_reason" in names, (
        "training_examples missing quarantine_reason column"
    )
    q = next(c for c in td.columns if c.name == "quarantined")
    assert q.type == "INTEGER"
    assert q.default == "0"
    qr = next(c for c in td.columns if c.name == "quarantine_reason")
    assert qr.type == "TEXT"


def test_diagnostic_type_description_includes_training_audit():
    """diagnostic_type description must enumerate 'training_audit' for R8.

    The column itself is unconstrained TEXT; the description is the
    single source of truth for what values are valid.
    """
    td = TABLES["diagnostic_runs"]
    dt = next(c for c in td.columns if c.name == "diagnostic_type")
    assert "training_audit" in (dt.description or ""), (
        f"diagnostic_type.description must list 'training_audit'; got: {dt.description!r}"
    )


def test_strategy_promotion_events_triggered_by_documents_all_sentinels():
    """triggered_by description must enumerate all four valid sentinel values.

    The column is unconstrained TEXT; the description is the single source
    of truth for the sentinel set used by the methodology gate wiring sprint
    (docs/audits/2026-05-05-methodology-gate-wiring/plan.md, T1).
    """
    td = TABLES["strategy_promotion_events"]
    col = next(c for c in td.columns if c.name == "triggered_by")
    description = col.description or ""
    for sentinel in ("'manual'", "'auto_gate'", "'gate_proposal'", "'operator_confirm'"):
        assert sentinel in description, (
            f"triggered_by.description must list {sentinel}; got: {description!r}"
        )


def test_all_expected_tables_present():
    """Every known table must be in the registry."""
    missing = EXPECTED_TABLES - set(TABLES.keys())
    assert not missing, f"Missing from registry: {missing}"


def test_expected_tables_matches_registry_exactly():
    """EXPECTED_TABLES must equal the set of registered table names — exactly.

    Sprint 0 Wave 1e SCHEMA-FLOOR regression guard. Originally
    EXPECTED_TABLES held 48 of 68 registered tables — `test_all_expected_tables_present`
    only checks one direction (whitelist subset of registry), so 20 new
    registry additions slipped in without triggering a whitelist update.

    This test forces both directions: any new table added to the registry
    MUST also be added to EXPECTED_TABLES (or this test fails CI). Likewise,
    removing a table from the registry without removing it from
    EXPECTED_TABLES will fail. Result: every schema change must update the
    whitelist deliberately, so the floor cannot drift again.
    """
    expected = EXPECTED_TABLES
    registered = {t.name for t in TABLES.values()}
    assert expected == registered, (
        f"EXPECTED_TABLES != registry.\n"
        f"Missing from registry (in whitelist but not registered): "
        f"{sorted(expected - registered)}\n"
        f"Missing from whitelist (registered but not in whitelist): "
        f"{sorted(registered - expected)}\n"
        f"If you added/removed a table in src/schema/registry.py, update "
        f"EXPECTED_TABLES in tests/test_schema.py to match."
    )


# ── Consistency tests ────────────────────────────────────────────

def test_every_foreign_key_references_valid_table():
    """Every ForeignKeyDef must reference a table that exists in TABLES."""
    for name, table in TABLES.items():
        for fk in table.foreign_keys:
            assert fk.references_table in TABLES, (
                f"{name}.{fk.column} references {fk.references_table} "
                f"which is not in TABLES"
            )


def test_every_sync_table_has_time_column():
    """Tables with incremental/latest_only sync must have a valid time column."""
    # council_votes syncs via FK (session_id) — no time column needed
    FK_SYNCED = {"council_votes"}

    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        if table.sync_mode in ("incremental", "latest_only") and name not in FK_SYNCED:
            assert table.sync_time_column, (
                f"{name} has sync_mode={table.sync_mode} but no sync_time_column"
            )
            col_names = [c.name for c in table.columns]
            assert table.sync_time_column in col_names, (
                f"{name}.sync_time_column={table.sync_time_column} "
                f"not in columns: {col_names}"
            )


def test_every_table_has_primary_key_in_columns():
    """The declared primary_key must exist in the columns list."""
    for name, table in TABLES.items():
        pks = (
            [table.primary_key]
            if isinstance(table.primary_key, str)
            else table.primary_key
        )
        col_names = [c.name for c in table.columns]
        for pk in pks:
            assert pk in col_names, (
                f"{name}: primary_key '{pk}' not found in columns"
            )


def test_no_duplicate_column_names():
    """No table should have duplicate column names."""
    for name, table in TABLES.items():
        col_names = [c.name for c in table.columns]
        dupes = [n for n in col_names if col_names.count(n) > 1]
        assert not dupes, f"{name} has duplicate columns: {set(dupes)}"


# ── Guardrail tests (CI enforcement) ────────────────────────────

def _load_allowed_files(key: str) -> set[str]:
    """Load allowed file paths from known_schema_violations.json."""
    known_path = Path("config/known_schema_violations.json")
    if not known_path.exists():
        return set()
    data = json.loads(known_path.read_text())
    return {entry["file"].replace("\\", "/") for entry in data.get(key, [])}


def test_no_create_table_in_source():
    """Scan src/ (except src/schema/) for CREATE TABLE — fail if found.

    This is the primary guardrail test. It prevents schema drift by
    blocking any CREATE TABLE statement outside the schema registry.
    Files listed in config/known_schema_violations.json are exempted
    during the migration period.
    """
    allowed = _load_allowed_files("allowed_create_table")

    violations = []
    for root, dirs, files in os.walk("src"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "schema")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f).replace("\\", "/")
                if path in allowed:
                    continue
                with open(os.path.join(root, f), errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if "CREATE TABLE" in line and not line.strip().startswith("#"):
                            violations.append(f"{path}:{i}")
    assert violations == [], (
        f"CREATE TABLE found outside schema/: {violations}\n"
        f"Add tables to src/schema/registry.py instead, or add to "
        f"config/known_schema_violations.json if migration is pending."
    )


def test_no_alter_table_in_source():
    """Same guardrail for ALTER TABLE statements."""
    allowed = _load_allowed_files("allowed_alter_table")

    violations = []
    for root, dirs, files in os.walk("src"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "schema")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f).replace("\\", "/")
                if path in allowed:
                    continue
                with open(os.path.join(root, f), errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if "ALTER TABLE" in line and not line.strip().startswith("#"):
                            violations.append(f"{path}:{i}")
    assert violations == [], (
        f"ALTER TABLE found outside schema/: {violations}\n"
        f"Add columns to src/schema/registry.py instead."
    )


# ── Stats query validation ─────────────────────────────────��────

def test_stats_queries_reference_valid_columns():
    """Ensure data-collection-stats queries only reference columns that exist in the schema."""
    import re
    from src.api.routes.system import _DATA_COLLECTION_QUERIES

    col_pattern = re.compile(
        r"(?:COUNT\s*\(\s*DISTINCT\s+|MAX\s*\(\s*|MIN\s*\(\s*|AVG\s*\(\s*)"
        r"(\w+)\s*\)",
        re.IGNORECASE,
    )

    errors = []
    for table_name, sql in _DATA_COLLECTION_QUERIES.items():
        if table_name not in TABLES:
            errors.append(f"{table_name}: not in schema registry")
            continue
        schema_cols = {c.name for c in TABLES[table_name].columns}
        referenced = col_pattern.findall(sql)
        for col in referenced:
            if col == "*":
                continue
            if col not in schema_cols:
                errors.append(f"{table_name}: query references '{col}' but schema has {sorted(schema_cols)}")

    assert errors == [], "Stats queries reference non-existent columns:\n" + "\n".join(errors)


# ── #673 — sync_state in-flight detection columns ────────────────

def test_sync_state_has_inflight_columns():
    """sync_state removed in Phase 3-revised (render_sync.py deprecated in T7).

    Sprint C.6 (#673): the in-flight columns were verified when sync_state
    existed. This test is superseded by test_sync_state_not_in_registry.
    """
    assert "sync_state" not in TABLES, (
        "sync_state was removed from registry in Phase 3-revised — "
        "render_sync.py is deleted in Task T7 as part of the one-DB cutover"
    )


def test_sync_state_not_synced_to_postgres():
    """sync_state removed in Phase 3-revised (render_sync.py deprecated in T7)."""
    assert "sync_state" not in TABLES, (
        "sync_state was removed from registry in Phase 3-revised — "
        "render_sync.py is deleted in Task T7 as part of the one-DB cutover"
    )


# ── #674 — 17-column prod-registry reconciliation ────────────────

def test_canary_evaluations_has_verdict_perplexity():
    """canary_evaluations must have verdict and perplexity.

    Sprint C.6 (#674): these columns are queried by cloud_routes/analytics.py
    and evaluation/system_validator.py in production.
    """
    assert "canary_evaluations" in TABLES
    td = TABLES["canary_evaluations"]
    names = [c.name for c in td.columns]
    assert "verdict" in names, "canary_evaluations missing verdict column"
    assert "perplexity" in names, "canary_evaluations missing perplexity column"
    verdict = next(c for c in td.columns if c.name == "verdict")
    assert verdict.type == "TEXT"
    perplexity = next(c for c in td.columns if c.name == "perplexity")
    assert perplexity.type == "REAL"


def test_quality_drift_metrics_has_reconciled_columns():
    """quality_drift_metrics must have metric_date, avg_score, pass_rate, id.

    Sprint C.6 (#674): system_validator.py queries metric_date, avg_score,
    pass_rate — these columns exist in prod but not the registry.
    """
    assert "quality_drift_metrics" in TABLES
    td = TABLES["quality_drift_metrics"]
    names = [c.name for c in td.columns]
    for col in ("metric_date", "avg_score", "pass_rate", "score_std", "template_fallback_rate"):
        assert col in names, f"quality_drift_metrics missing {col}"
    avg_score = next(c for c in td.columns if c.name == "avg_score")
    assert avg_score.type == "REAL"
    pass_rate = next(c for c in td.columns if c.name == "pass_rate")
    assert pass_rate.type == "REAL"
    metric_date = next(c for c in td.columns if c.name == "metric_date")
    assert metric_date.type == "TEXT"


def test_recommendations_has_setup_confidence():
    """recommendations must have setup_confidence.

    Sprint C.6 (#674): prod DB has this column; features/engine_helpers.py
    and scheduler/universe_scanner.py write it. Not yet in registry.
    """
    assert "recommendations" in TABLES
    td = TABLES["recommendations"]
    names = [c.name for c in td.columns]
    assert "setup_confidence" in names, "recommendations missing setup_confidence"
    sc = next(c for c in td.columns if c.name == "setup_confidence")
    assert sc.type == "REAL"


def test_setup_signals_has_features_json_and_scan_date():
    """setup_signals must have features_json and scan_date.

    Sprint C.6 (#674): cloud_routes/trades.py calls parse_json_fields(row,
    ['features_json']) — expects the column to exist.
    """
    assert "setup_signals" in TABLES
    td = TABLES["setup_signals"]
    names = [c.name for c in td.columns]
    assert "features_json" in names, "setup_signals missing features_json"
    assert "scan_date" in names, "setup_signals missing scan_date"
    fj = next(c for c in td.columns if c.name == "features_json")
    assert fj.type == "TEXT"


def test_training_examples_has_reconciled_columns():
    """training_examples must have outcome, regime_label, trade_date, model_version.

    Sprint C.6 (#674): cloud_routes/training.py queries outcome; analytics.py
    queries regime_label — live code paths depend on these columns.
    """
    assert "training_examples" in TABLES
    td = TABLES["training_examples"]
    names = [c.name for c in td.columns]
    for col in ("outcome", "regime_label", "trade_date", "model_version"):
        assert col in names, f"training_examples missing {col}"
    outcome = next(c for c in td.columns if c.name == "outcome")
    assert outcome.type == "TEXT"
    regime_label = next(c for c in td.columns if c.name == "regime_label")
    assert regime_label.type == "TEXT"


def test_api_costs_has_estimated_cost():
    """api_costs must have estimated_cost.

    Sprint C.6 (#674): cloud_routes/core.py queries
    COALESCE(cost_dollars, estimated_cost, 0) — must exist in registry.
    """
    assert "api_costs" in TABLES
    td = TABLES["api_costs"]
    names = [c.name for c in td.columns]
    assert "estimated_cost" in names, "api_costs missing estimated_cost"
    ec = next(c for c in td.columns if c.name == "estimated_cost")
    assert ec.type == "REAL"


# ── #73 — sync_reconcile field ────────────────────────────────────

def test_sync_reconcile_field_default_is_false():
    """A fresh TableDef without explicit sync_reconcile yields False (#73)."""
    td = TableDef(
        name="_test_reconcile_default",
        description="Test",
        columns=[ColumnDef("id", "TEXT", nullable=False)],
        primary_key="id",
    )
    assert td.sync_reconcile is False


_MUST_BE_TRUE = {
    "recommendations",
    "shadow_trades",
    "diagnostic_runs",
    "attribution_trades",
    "stress_test_results",
    "simulation_results",
    "minute_bars",
    "walkforward_results",
    "walkforward_trades",
    "research_docs",
    "setup_signals",
    "build_score_history",
    "log_entries",
    "command_results",
    "training_examples",
    "validation_results",
    "audit_reports",
    "metric_snapshots",
    "api_costs",
    "council_sessions",
    "council_votes",
    "council_calibrations",
    "council_debug_log",
    "council_parameter_log",
}


def test_sync_reconcile_true_for_today_reconciled_tables():
    """Each of the 24 tables reconciled today must have sync_reconcile=True (#73)."""
    for name in _MUST_BE_TRUE:
        assert name in TABLES, f"{name} not in registry"
        assert TABLES[name].sync_reconcile is True, (
            f"TABLES['{name}'].sync_reconcile should be True"
        )


def test_sync_reconcile_false_for_bidirectional_full_latest_only():
    """Skipped/ineligible tables must have sync_reconcile=False (#73)."""
    for name in (
        "pending_commands",
        "config_overrides",
        "user_notes",
        "model_versions",
        "options_chains",
        "scan_metrics",
        "activity_log",
    ):
        assert name in TABLES, f"{name} not in registry"
        assert TABLES[name].sync_reconcile is False, (
            f"TABLES['{name}'].sync_reconcile should be False"
        )


# ── #798 — scan_metrics UNIQUE constraint ─────────────────────────

def test_scan_metrics_has_unique_index_on_created_at():
    """scan_metrics must have a UNIQUE index on created_at.

    scan_number resets across sessions/days, so (scan_number, scan_time)
    cannot be the global uniqueness key for retained history. created_at is
    the stable per-row identity used by sync ordering and cloud dedupe.
    """
    assert "scan_metrics" in TABLES
    td = TABLES["scan_metrics"]
    unique_indexes = [
        idx for idx in td.indexes
        if idx.unique and idx.columns == ["created_at"]
    ]
    assert unique_indexes, (
        "scan_metrics must have a UNIQUE index covering created_at. "
        "Add IndexDef('idx_scan_metrics_unique', ['created_at'], unique=True) "
        "to the scan_metrics TableDef in src/schema/registry.py"
    )


# ── Sprint 4 T14 — notifications_sent + notifications_dedup ──────

def test_notifications_sent_in_TABLES():
    """notifications_sent must be registered in TABLES (Sprint 4 T14)."""
    assert "notifications_sent" in TABLES, (
        "notifications_sent not in registry — add TableDef to src/schema/registry.py"
    )


def test_notifications_sent_columns_match_spec():
    """notifications_sent must have all 8 spec columns with correct types and nullability."""
    assert "notifications_sent" in TABLES
    td = TABLES["notifications_sent"]
    col_map = {c.name: c for c in td.columns}

    assert "id" in col_map, "notifications_sent missing id column"
    assert col_map["id"].type == "INTEGER"

    assert "event_type" in col_map, "notifications_sent missing event_type column"
    assert col_map["event_type"].type == "TEXT"
    assert col_map["event_type"].nullable is False

    assert "channel" in col_map, "notifications_sent missing channel column"
    assert col_map["channel"].type == "TEXT"
    assert col_map["channel"].nullable is False

    assert "recipient" in col_map, "notifications_sent missing recipient column"
    assert col_map["recipient"].nullable is True

    assert "sent_at" in col_map, "notifications_sent missing sent_at column"
    assert col_map["sent_at"].type == "TEXT"
    assert col_map["sent_at"].nullable is False

    assert "status" in col_map, "notifications_sent missing status column"
    assert col_map["status"].type == "TEXT"
    assert col_map["status"].nullable is False

    assert "retry_count" in col_map, "notifications_sent missing retry_count column"
    assert col_map["retry_count"].type == "INTEGER"
    assert col_map["retry_count"].nullable is False
    assert col_map["retry_count"].default == "0", (
        f"retry_count default should be '0', got {col_map['retry_count'].default!r}"
    )

    assert "error_msg" in col_map, "notifications_sent missing error_msg column"
    assert col_map["error_msg"].nullable is True


def test_notifications_sent_index_registered():
    """notifications_sent must have (event_type, sent_at DESC) index registered."""
    assert "notifications_sent" in TABLES
    td = TABLES["notifications_sent"]
    event_recent_indexes = [
        idx for idx in td.indexes
        if "event_type" in idx.columns and any("sent_at" in c for c in idx.columns)
    ]
    assert event_recent_indexes, (
        "notifications_sent missing index on (event_type, sent_at DESC). "
        "Add IndexDef with columns=['event_type', 'sent_at DESC'] to registry."
    )


def test_notifications_dedup_in_TABLES():
    """notifications_dedup must be registered in TABLES (Sprint 4 T14)."""
    assert "notifications_dedup" in TABLES, (
        "notifications_dedup not in registry — add TableDef to src/schema/registry.py"
    )


def test_notifications_dedup_unique_event_dedup_key():
    """notifications_dedup must have UNIQUE constraint on (event_type, dedup_key)."""
    assert "notifications_dedup" in TABLES
    td = TABLES["notifications_dedup"]
    col_names = [c.name for c in td.columns]
    assert "event_type" in col_names, "notifications_dedup missing event_type column"
    assert "dedup_key" in col_names, "notifications_dedup missing dedup_key column"
    assert "sent_at" in col_names, "notifications_dedup missing sent_at column"
    unique_indexes = [
        idx for idx in td.indexes
        if idx.unique and "event_type" in idx.columns and "dedup_key" in idx.columns
    ]
    assert unique_indexes, (
        "notifications_dedup must have a UNIQUE index on (event_type, dedup_key). "
        "Add IndexDef with unique=True and columns=['event_type', 'dedup_key']."
    )


def test_notifications_dedup_sync_conflict_col_matches_composite_unique():
    """SP5 §J5/§J6 Phase 0 T0.7: notifications_dedup.sync_conflict_col must be
    'event_type, dedup_key' so engine_aware_upsert targets the composite unique
    constraint (the natural conflict target) instead of the autoincrement PK `id`.
    Prerequisite for the platform_events.py:96 migration in T1.7.
    """
    assert "notifications_dedup" in TABLES
    td = TABLES["notifications_dedup"]
    assert td.sync_conflict_col == "event_type, dedup_key", (
        "notifications_dedup.sync_conflict_col must be 'event_type, dedup_key' "
        f"(got {td.sync_conflict_col!r}). PK `id` is autoincrement; uniqueness is "
        "enforced via the composite index — that's the natural ON CONFLICT target."
    )


def test_sync_to_postgres_flipped_for_one_db_cutover():
    """Phase 3-revised: 8 previously-local-only tables now sync to PG."""
    from src.schema.registry import TABLES
    flipped_tables = [
        "daily_ib_health", "model_evaluations", "preference_pairs",
        "config_overrides", "bracket_health", "data_freshness",
        "system_metrics", "operator_view_state",
    ]
    for tname in flipped_tables:
        assert tname in TABLES, f"{tname} missing from registry"
        assert TABLES[tname].sync_to_postgres is True, f"{tname} should sync to PG post-Phase-3-revised"


def test_sync_state_not_in_registry():
    """Phase 3-revised: sync_state removed alongside render_sync.py deprecation."""
    from src.schema.registry import TABLES
    assert "sync_state" not in TABLES, (
        "sync_state should be removed from registry — render_sync.py is being "
        "deleted in Task T7 as part of the one-DB cutover"
    )


# ── T2 Wave C #56 + #96 — strategy_id FK + platform_events ──────────────────

def test_shadow_trades_strategy_id_column_present():
    """strategy_id column must be present on shadow_trades with nullable=True (T2/#56)."""
    from src.schema.registry import TABLES
    assert "shadow_trades" in TABLES
    td = TABLES["shadow_trades"]
    col_names = [c.name for c in td.columns]
    assert "strategy_id" in col_names, "shadow_trades missing strategy_id column"
    col = next(c for c in td.columns if c.name == "strategy_id")
    assert col.type == "TEXT", f"strategy_id type should be TEXT, got {col.type}"
    assert col.nullable is True, "strategy_id should be nullable=True"


def test_platform_events_table_present_with_all_columns():
    """platform_events table must be present with all 6 required columns (T2/#96)."""
    from src.schema.registry import TABLES
    assert "platform_events" in TABLES, "platform_events table missing from registry"
    td = TABLES["platform_events"]
    col_names = [c.name for c in td.columns]
    for required in ("id", "event_type", "severity", "payload_json", "source", "created_at"):
        assert required in col_names, f"platform_events missing column: {required}"
    id_col = next(c for c in td.columns if c.name == "id")
    assert id_col.type == "INTEGER"
    assert id_col.autoincrement is True
    event_type_col = next(c for c in td.columns if c.name == "event_type")
    assert event_type_col.nullable is False
    severity_col = next(c for c in td.columns if c.name == "severity")
    assert severity_col.nullable is False
    source_col = next(c for c in td.columns if c.name == "source")
    assert source_col.nullable is False


def test_platform_events_created_at_is_timestamp():
    """platform_events.created_at must be TIMESTAMP per spec §3.1c (T2/#96 fix-up)."""
    from src.schema.registry import TABLES
    td = TABLES["platform_events"]
    created_at_col = next(c for c in td.columns if c.name == "created_at")
    assert created_at_col.type == "TIMESTAMP", (
        f"created_at should be TIMESTAMP per spec §3.1c, got {created_at_col.type!r}"
    )


def test_platform_events_has_proper_indexes():
    """platform_events must have exactly 2 spec-aligned indexes (T2/#96 fix-up).

    Spec §3.1c (design.md lines 206-209) specifies:
      idx_platform_events_created_at on [created_at]
      idx_platform_events_event_type on [event_type]
    No severity index. No composite index.
    """
    from src.schema.registry import TABLES
    td = TABLES["platform_events"]
    index_names = [idx.name for idx in td.indexes]
    assert "idx_platform_events_created_at" in index_names, (
        "Missing idx_platform_events_created_at (spec §3.1c)"
    )
    assert "idx_platform_events_event_type" in index_names, (
        "Missing idx_platform_events_event_type (spec §3.1c)"
    )
    assert "idx_platform_events_type_created" not in index_names, (
        "Composite idx_platform_events_type_created must not exist (not in spec §3.1c)"
    )
    assert "idx_platform_events_severity" not in index_names, (
        "idx_platform_events_severity must not exist (not in spec §3.1c)"
    )
    assert len(td.indexes) == 2, (
        f"platform_events must have exactly 2 indexes per spec §3.1c, got {len(td.indexes)}"
    )


def test_shadow_trades_strategy_id_fk_db_enforcement():
    """FK constraint on strategy_id must reject nonexistent strategy_id at DB layer (T2/#56).

    Uses an in-memory SQLite DB built from the registry schema. The IntegrityError
    fires immediately at INSERT time (immediate FK enforcement). Deferred-mode
    testing (PRAGMA defer_foreign_keys = ON + error at COMMIT) requires the FK
    constraint itself to carry DEFERRABLE INITIALLY DEFERRED — tracked in #107
    against src/schema/sqlite.py.
    """
    import sqlite3
    from src.schema.sqlite import generate_create_sql
    from src.schema.registry import TABLES
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    for table_name in ("recommendations", "strategy_registry", "shadow_trades"):
        sql = generate_create_sql(TABLES[table_name])
        for stmt in sql.split(";\n"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, status, created_at, updated_at, strategy_id) "
            "VALUES ('t1','AAPL','open','2026-01-01','2026-01-01','nonexistent_strategy')"
        )
        conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "path_name,patch_target,env_database_url",
    [
        ("sqlite", "get_closed_shadow_trades", None),
        ("postgres", "_fetch_closed_trades_from_postgres", "postgresql://fake@localhost/x"),
    ],
)
def test_fetch_closed_trades_filters_by_strategy_id(
    monkeypatch, path_name, patch_target, env_database_url
):
    """_fetch_closed_trades(strategy_id='X') returns only trades for strategy X (T2/#56).

    Parametrized over both dispatch paths of _fetch_closed_trades:
      - sqlite branch (DATABASE_URL unset): calls get_closed_shadow_trades
      - postgres branch (DATABASE_URL set): calls _fetch_closed_trades_from_postgres
    Each variant patches the corresponding function (not the other) so mock-
    target drift in either branch surfaces as a real-PG call against missing
    fixtures rather than a silent vacuous pass (the v0.36.60 / #92 follow-up
    finding; the original test patched only get_closed_shadow_trades and was
    vacuous whenever DATABASE_URL was set, the operator's runtime env).
    """
    from unittest.mock import patch
    from src.api.cloud_routes.kpis_compute import _fetch_closed_trades

    if env_database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", env_database_url)

    rows_x = [
        {"trade_id": "t1", "ticker": "AAPL", "status": "closed",
         "strategy_id": "strategy_X", "actual_exit_time": "2026-01-02",
         "quarantined": 0, "exit_reason": "target_1"},
    ]
    rows_y = [
        {"trade_id": "t2", "ticker": "MSFT", "status": "closed",
         "strategy_id": "strategy_Y", "actual_exit_time": "2026-01-02",
         "quarantined": 0, "exit_reason": "target_1"},
    ]
    all_rows = rows_x + rows_y

    with patch(f"src.api.cloud_routes.kpis_compute.{patch_target}",
               return_value=all_rows):
        result = _fetch_closed_trades(strategy_id="strategy_X")
    assert len(result) == 1, f"path={path_name}: expected 1 row, got {len(result)}"
    assert result[0]["strategy_id"] == "strategy_X", (
        f"path={path_name}: expected strategy_X, got {result[0]['strategy_id']}"
    )


@pytest.mark.parametrize(
    "path_name,patch_target,env_database_url",
    [
        ("sqlite", "get_closed_shadow_trades", None),
        ("postgres", "_fetch_closed_trades_from_postgres", "postgresql://fake@localhost/x"),
    ],
)
def test_fetch_closed_trades_strategy_id_none_returns_all(
    monkeypatch, path_name, patch_target, env_database_url
):
    """_fetch_closed_trades(strategy_id=None) returns all trades — backward compat (T2/#56).

    Same parametrization as the strategy_id-filter test above; locks both
    dispatch branches against mock-target drift.
    """
    from unittest.mock import patch
    from src.api.cloud_routes.kpis_compute import _fetch_closed_trades

    if env_database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", env_database_url)

    all_rows = [
        {"trade_id": "t1", "ticker": "AAPL", "status": "closed",
         "strategy_id": "strategy_X", "actual_exit_time": "2026-01-02",
         "quarantined": 0, "exit_reason": "target_1"},
        {"trade_id": "t2", "ticker": "MSFT", "status": "closed",
         "strategy_id": "strategy_Y", "actual_exit_time": "2026-01-02",
         "quarantined": 0, "exit_reason": "target_1"},
    ]

    with patch(f"src.api.cloud_routes.kpis_compute.{patch_target}",
               return_value=all_rows):
        result = _fetch_closed_trades(strategy_id=None)
    assert len(result) == 2, f"path={path_name}: expected 2 rows, got {len(result)}"


def test_render_migrate_fk_emits_not_valid():
    """render_migrate.py FK constraint SQL for strategy_id must include NOT VALID (T2/Decision-24)."""
    from src.schema.postgres import generate_fk_constraint_sql
    from src.schema.registry import TABLES, ForeignKeyDef
    td = TABLES["shadow_trades"]
    fk = next(
        fk for fk in td.foreign_keys
        if fk.column == "strategy_id"
    )
    sql = generate_fk_constraint_sql("shadow_trades", fk)
    assert "NOT VALID" in sql, (
        f"FK constraint SQL must include NOT VALID per Decision 24; got: {sql!r}"
    )


# ── Sprint 6 Wave B T4 — walkforward_results v2 outcome fields ────

def test_walkforward_results_has_excess_sharpe_min_used_column():
    """walkforward_results must have excess_sharpe_min_used as REAL nullable.

    Sprint 6 Wave B T4 (SP-WF-004): records the excess_sharpe_min config
    threshold used for the run. Nullable when raw-Sharpe threshold only.
    """
    assert "walkforward_results" in TABLES
    td = TABLES["walkforward_results"]
    names = [c.name for c in td.columns]
    assert "excess_sharpe_min_used" in names, (
        "walkforward_results missing excess_sharpe_min_used column"
    )
    col = next(c for c in td.columns if c.name == "excess_sharpe_min_used")
    assert col.type == "REAL", (
        f"excess_sharpe_min_used must be REAL, got {col.type!r}"
    )
    assert col.nullable is True, (
        "excess_sharpe_min_used must be nullable"
    )


def test_walkforward_results_has_gate_version_column():
    """walkforward_results must have gate_version as TEXT with default 'v1'.

    Sprint 6 Wave B T4: records the walk-forward framework version that
    ran the gate. Default 'v1' matches existing runs.
    """
    assert "walkforward_results" in TABLES
    td = TABLES["walkforward_results"]
    names = [c.name for c in td.columns]
    assert "gate_version" in names, (
        "walkforward_results missing gate_version column"
    )
    col = next(c for c in td.columns if c.name == "gate_version")
    assert col.type == "TEXT", (
        f"gate_version must be TEXT, got {col.type!r}"
    )
    assert col.default == "v1", (
        f"gate_version must default to 'v1', got {col.default!r}"
    )


def test_walkforward_results_has_derived_from_backtest_id_column():
    """walkforward_results must have derived_from_backtest_id as TEXT nullable.

    Sprint 6 Wave B T4 Feasibility v1.1 patch (SP-WF-016): required by
    T13 reconciler SQL + falsifiability query 1. Records the
    backtest_results.id that auto-fire used to spawn this run.
    Nullable for manual/CLI invocations.
    """
    assert "walkforward_results" in TABLES
    td = TABLES["walkforward_results"]
    names = [c.name for c in td.columns]
    assert "derived_from_backtest_id" in names, (
        "walkforward_results missing derived_from_backtest_id column"
    )
    col = next(c for c in td.columns if c.name == "derived_from_backtest_id")
    assert col.type == "TEXT", (
        f"derived_from_backtest_id must be TEXT, got {col.type!r}"
    )
    assert col.nullable is True, (
        "derived_from_backtest_id must be nullable"
    )

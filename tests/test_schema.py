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

EXPECTED_TABLE_COUNT = 68


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
    "activity_log", "log_entries", "sync_state",
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
    """sync_state must have in_flight_since and completed_at for quiescence detection.

    Sprint C.6 (#673): extends the 2-column sync_state table with in-flight
    tracking so external scripts can detect whether a sync cycle is running
    without needing to inspect the threading.Lock internals.
    """
    assert "sync_state" in TABLES
    td = TABLES["sync_state"]
    names = [c.name for c in td.columns]
    assert "in_flight_since" in names, "sync_state missing in_flight_since column"
    assert "completed_at" in names, "sync_state missing completed_at column"
    assert "status" in names, "sync_state missing status column"
    in_flight = next(c for c in td.columns if c.name == "in_flight_since")
    assert in_flight.type == "TEXT"
    completed = next(c for c in td.columns if c.name == "completed_at")
    assert completed.type == "TEXT"
    status_col = next(c for c in td.columns if c.name == "status")
    assert status_col.type == "TEXT"
    assert status_col.default == "idle"


def test_sync_state_not_synced_to_postgres():
    """sync_state must NOT sync to Postgres (that would be circular)."""
    assert "sync_state" in TABLES
    td = TABLES["sync_state"]
    assert td.sync_to_postgres is False, (
        "sync_state must not sync to Postgres — that would be circular"
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

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

EXPECTED_TABLE_COUNT = 40


def test_registry_has_all_tables():
    """Registry must define at least the expected number of tables."""
    assert len(TABLES) >= EXPECTED_TABLE_COUNT, (
        f"Registry has {len(TABLES)} tables, expected >= {EXPECTED_TABLE_COUNT}. "
        f"Missing tables need to be added to src/schema/registry.py"
    )


EXPECTED_TABLES = {
    # Trading Core
    "shadow_trades", "recommendations", "validation_results",
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
    # Research
    "research_papers", "research_digests", "research_docs",
    # Signals
    "setup_signals", "traffic_light_state",
    # Evaluation & Metrics
    "scan_metrics", "schedule_metrics", "quality_drift_metrics",
    "build_score_history",
    # Infrastructure
    "activity_log", "log_entries", "sync_state",
    "command_results", "config_overrides", "pending_commands",
    # User Data
    "user_notes",
    # Trading Internals
    "bracket_health",
}


def test_all_expected_tables_present():
    """Every known table must be in the registry."""
    missing = EXPECTED_TABLES - set(TABLES.keys())
    assert not missing, f"Missing from registry: {missing}"


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

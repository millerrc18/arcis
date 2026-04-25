"""Tests for broker_exceptions table registration in schema registry.

Verifies that the broker_exceptions TableDef is present with the required
13 columns and the broker/timestamp composite index per B2 design.
"""

import pytest
from src.schema.registry import TABLES


def test_broker_exceptions_table_registered():
    """broker_exceptions must be present in the schema registry."""
    assert "broker_exceptions" in TABLES, (
        "broker_exceptions not found in TABLES — did you forget to _register() it?"
    )


def test_broker_exceptions_column_count():
    """broker_exceptions must have exactly 13 columns per B2 design."""
    tdef = TABLES["broker_exceptions"]
    col_names = [c.name for c in tdef.columns]
    assert len(col_names) == 13, f"Expected 13 columns, got {len(col_names)}: {col_names}"


def test_broker_exceptions_required_columns():
    """All 13 B2-spec columns must be present with correct names."""
    tdef = TABLES["broker_exceptions"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id", "ticker", "operation", "broker", "timestamp",
        "exception_class", "exception_message", "traceback",
        "recoverable", "created_at", "correlation_id",
        "retry_count", "outcome",
    }
    missing = required - col_names
    assert not missing, f"Missing columns: {missing}"


def test_broker_exceptions_nullable_constraints():
    """NOT-NULL and nullable columns match the B2 spec."""
    tdef = TABLES["broker_exceptions"]
    col_map = {c.name: c for c in tdef.columns}

    not_null_cols = ["id", "ticker", "operation", "broker", "timestamp",
                     "exception_class", "exception_message", "recoverable", "created_at"]
    nullable_cols = ["traceback", "correlation_id", "retry_count", "outcome"]

    for name in not_null_cols:
        assert not col_map[name].nullable, f"Column '{name}' should be NOT NULL"

    for name in nullable_cols:
        assert col_map[name].nullable, f"Column '{name}' should be nullable"


def test_broker_exceptions_id_autoincrement():
    """id column must be INTEGER with autoincrement=True."""
    tdef = TABLES["broker_exceptions"]
    col_map = {c.name: c for c in tdef.columns}
    id_col = col_map["id"]
    assert id_col.type == "INTEGER"
    assert id_col.autoincrement is True


def test_broker_exceptions_primary_key():
    """Primary key must be 'id'."""
    tdef = TABLES["broker_exceptions"]
    assert tdef.primary_key == "id"


def test_broker_exceptions_broker_timestamp_index():
    """Must have composite index on (broker, timestamp) per B2 design."""
    tdef = TABLES["broker_exceptions"]
    idx_names = {idx.name for idx in tdef.indexes}
    # Accept either naming convention used in the design doc
    expected = {"idx_broker_exceptions_broker_ts", "idx_broker_exceptions_broker_time"}
    found = idx_names & expected
    assert found, (
        f"Expected a broker/timestamp index (one of {expected}), "
        f"got indexes: {idx_names}"
    )
    # Verify the index covers [broker, timestamp]
    matching = [idx for idx in tdef.indexes if idx.name in expected]
    assert matching
    idx = matching[0]
    assert "broker" in idx.columns
    assert "timestamp" in idx.columns

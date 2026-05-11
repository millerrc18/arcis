"""Tests for `_resolve_conflict_target` in src/utils/db.py.

Sprint 5 §J5/§J6 Phase 0 T0.3 — extract the conflict-target resolution helper
from scripts/sqlite_to_pg_migrate.py:50-53 into src/utils/db.py.

Precedence:
    1. TABLES[name].sync_conflict_col (comma-split, stripped) — if set
    2. TABLES[name].primary_key — string returns [pk], list returns list(pk)
    3. ValueError if table name unknown
"""

from unittest.mock import patch

import pytest

from src.schema.registry import ColumnDef, TableDef
from src.utils.db import _resolve_conflict_target


def _make_table(name, primary_key, sync_conflict_col=None):
    """Build a minimal TableDef for isolated tests."""
    return TableDef(
        name=name,
        description="test",
        columns=[ColumnDef("id", "TEXT", nullable=False)],
        primary_key=primary_key,
        sync_conflict_col=sync_conflict_col,
    )


def test_resolve_conflict_target_sync_conflict_col_single():
    """A table with sync_conflict_col=single column → single-element list."""
    fake_tables = {
        "edgar_filings": _make_table(
            "edgar_filings",
            primary_key="id",
            sync_conflict_col="accession_number",
        ),
    }
    with patch("src.utils.db.TABLES", fake_tables):
        result = _resolve_conflict_target("edgar_filings")
    assert result == ["accession_number"]


def test_resolve_conflict_target_string_primary_key():
    """A table without sync_conflict_col but with string PK → single-element list."""
    fake_tables = {
        "recommendations": _make_table(
            "recommendations",
            primary_key="recommendation_id",
            sync_conflict_col=None,
        ),
    }
    with patch("src.utils.db.TABLES", fake_tables):
        result = _resolve_conflict_target("recommendations")
    assert result == ["recommendation_id"]


def test_resolve_conflict_target_list_primary_key():
    """A table without sync_conflict_col but with composite PK → returns list as-is."""
    fake_tables = {
        "minute_bars": _make_table(
            "minute_bars",
            primary_key=["ticker", "timestamp"],
            sync_conflict_col=None,
        ),
    }
    with patch("src.utils.db.TABLES", fake_tables):
        result = _resolve_conflict_target("minute_bars")
    assert result == ["ticker", "timestamp"]


def test_resolve_conflict_target_unknown_table_raises():
    """Unknown table name raises ValueError with the table name in the message."""
    fake_tables = {}
    with patch("src.utils.db.TABLES", fake_tables):
        with pytest.raises(ValueError) as exc_info:
            _resolve_conflict_target("nonexistent_table")
    assert "nonexistent_table" in str(exc_info.value)


def test_resolve_conflict_target_sync_conflict_col_strips_whitespace():
    """sync_conflict_col with surrounding whitespace on each comma-split part is stripped."""
    fake_tables = {
        "events_dedup": _make_table(
            "events_dedup",
            primary_key="id",
            sync_conflict_col="event_type, dedup_key ",
        ),
    }
    with patch("src.utils.db.TABLES", fake_tables):
        result = _resolve_conflict_target("events_dedup")
    assert result == ["event_type", "dedup_key"]

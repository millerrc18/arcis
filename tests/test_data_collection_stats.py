"""Tests for /data-collection-stats endpoint helpers (P0 PG-cutover fix).

Root cause: after PG cutover, sqlite3.Row / psycopg2 RealDictRow wrappers
return empty mappings for un-aliased aggregate columns (e.g. COUNT(*) has
no column name). Positional access row[0] still works on SQLite but blows
up with IndexError on PG wrappers. Solution: add explicit AS aliases to
every SELECT and switch _build_table_stats() to named access row.get().

Tests:
  (1) _build_table_stats({})         -> zero defaults (empty mapping)
  (2) _build_table_stats(full row)   -> correctly typed dict
  (3) parametrize 12 query keys      -> each SQL has three required aliases
"""
import re
import pytest

from src.api.routes.system import _DATA_COLLECTION_QUERIES, _build_table_stats


# ── (1) Empty mapping → zero defaults ───────────────────────────────────────

def test_build_table_stats_empty_mapping_returns_zero_defaults():
    result = _build_table_stats({})
    assert result == {"total_records": 0, "latest_collection": None, "coverage_count": 0}


# ── (2) Full named row → correctly typed dict ────────────────────────────────

def test_build_table_stats_full_row_returns_correct_values():
    row = {
        "total_records": 5,
        "latest_collection": "2026-05-14T12:34:56",
        "coverage_count": 3,
    }
    result = _build_table_stats(row)
    assert result["total_records"] == 5
    assert result["latest_collection"] == "2026-05-14"
    assert result["coverage_count"] == 3


def test_build_table_stats_none_total_records_yields_zero_coverage():
    row = {
        "total_records": 0,
        "latest_collection": "2026-05-14",
        "coverage_count": 7,
    }
    result = _build_table_stats(row)
    assert result["total_records"] == 0
    assert result["latest_collection"] is None
    assert result["coverage_count"] == 0


def test_build_table_stats_null_collection_stays_none():
    row = {
        "total_records": 10,
        "latest_collection": None,
        "coverage_count": 5,
    }
    result = _build_table_stats(row)
    assert result["total_records"] == 10
    assert result["latest_collection"] is None
    assert result["coverage_count"] == 5


# ── (3) All 12 query keys contain three required aliases ─────────────────────

_REQUIRED_ALIASES = [
    r"\bAS\s+total_records\b",
    r"\bAS\s+latest_collection\b",
    r"\bAS\s+coverage_count\b",
]


@pytest.mark.parametrize("table_name", list(_DATA_COLLECTION_QUERIES.keys()))
def test_query_has_all_three_aliases(table_name):
    sql = _DATA_COLLECTION_QUERIES[table_name]
    for alias_pattern in _REQUIRED_ALIASES:
        assert re.search(alias_pattern, sql, re.IGNORECASE), (
            f"Query for '{table_name}' is missing alias matching {alias_pattern!r}.\n"
            f"SQL: {sql}"
        )

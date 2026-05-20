"""Tests for src/data_collection/company_executive_collector.py.

Sprint v0.36.38 T2: plan-gated company executive collector.

Three tests per task spec:
  1. plan=fundamental-1 -> API call made + rows written + UPSERT idempotent
  2. plan=free -> NO API call (assert_not_called) and collector returns None
  3. Schema discipline (company_executives table + columns + unique index)
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db():
    """SQLite tmp database with the company_executives table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["company_executives"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


# ---------------------------------------------------------------------------
# Test 1: plan=fundamental-1 -> API call + rows written + UPSERT idempotent
# ---------------------------------------------------------------------------


def test_plan_fundamental_1_makes_api_call_and_writes_rows(sqlite_db, monkeypatch):
    """plan=fundamental-1: gate is open, API is called, rows land in
    company_executives, and a repeat call upserts (no duplicate rows)."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.company_executive_collector import (
        collect_company_executives,
    )

    mock_payload = {
        "executive": [
            {
                "name": "Tim Cook",
                "position": "CEO",
                "age": 62,
                "since": "2011-08-24",
                "compensation": 99420322,
                "currency": "USD",
            },
            {
                "name": "Luca Maestri",
                "position": "CFO",
                "age": 60,
                "since": "2014-05-06",
                "compensation": 27013691,
                "currency": "USD",
            },
        ],
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.company_executive_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.company_executive_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call: API hit + rows written.
        result1 = collect_company_executives("AAPL", config=config, db_path=sqlite_db)
        assert result1 is not None
        assert mock_get.called, "Expected Finnhub API call when plan=fundamental-1"
        assert result1["ticker"] == "AAPL"
        assert result1["executives_stored"] == 2

        # Second call: same executives -> UPSERT idempotent (no duplicate rows).
        result2 = collect_company_executives("AAPL", config=config, db_path=sqlite_db)
        assert result2 is not None

    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, name, position FROM company_executives "
            "WHERE ticker = ? ORDER BY name",
            ("AAPL",),
        ).fetchall()
    assert len(rows) == 2, "Expected exactly 2 rows after two collect calls (UPSERT)"
    names = {r["name"] for r in rows}
    assert "Tim Cook" in names
    assert "Luca Maestri" in names


# ---------------------------------------------------------------------------
# Test 1b: edge cases — empty list → None, executive missing name → skipped
# ---------------------------------------------------------------------------


def test_empty_executive_list_returns_none(sqlite_db, monkeypatch):
    """Empty executive list -> returns None and writes nothing."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.company_executive_collector import (
        collect_company_executives,
    )

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.company_executive_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.company_executive_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"executive": [], "symbol": "AAPL"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = collect_company_executives("AAPL", config=config, db_path=sqlite_db)

    assert result is None

    with sqlite3.connect(sqlite_db) as verify:
        count = verify.execute(
            "SELECT COUNT(*) FROM company_executives WHERE ticker = ?", ("AAPL",)
        ).fetchone()[0]
    assert count == 0, "No rows should be written for empty executive list"


def test_executive_missing_name_is_skipped(sqlite_db, monkeypatch):
    """Executive with no name is skipped; named executives are still written."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.company_executive_collector import (
        collect_company_executives,
    )

    mock_payload = {
        "executive": [
            {"name": "Tim Cook", "position": "CEO", "age": 62, "since": "2011-08-24",
             "compensation": 99420322, "currency": "USD"},
            {"name": None, "position": "Unknown", "age": None, "since": None,
             "compensation": None, "currency": None},
            {"position": "Also Unknown", "age": None, "since": None,
             "compensation": None, "currency": None},
        ],
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.company_executive_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.company_executive_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = collect_company_executives("AAPL", config=config, db_path=sqlite_db)

    assert result is not None
    assert result["executives_stored"] == 1

    with sqlite3.connect(sqlite_db) as verify:
        rows = verify.execute(
            "SELECT name FROM company_executives WHERE ticker = ?", ("AAPL",)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Tim Cook"


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns None and never touches
    requests.get (the Finnhub client)."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.company_executive_collector import (
        collect_company_executives,
    )

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.company_executive_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.company_executive_collector.requests.get"
    ) as mock_get:
        result = collect_company_executives("AAPL", config=config, db_path=sqlite_db)

    assert result is None, "plan=free must return None"
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: schema discipline — company_executives table + columns + index
# ---------------------------------------------------------------------------


def test_schema_company_executives_table_columns_and_index():
    """Schema discipline: registry has company_executives with the
    expected columns + unique index per task spec."""
    from src.schema.registry import TABLES

    assert "company_executives" in TABLES, (
        "company_executives TableDef must be registered"
    )

    tdef = TABLES["company_executives"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id",
        "ticker",
        "name",
        "position",
        "age",
        "since",
        "compensation",
        "currency",
        "retrieved_at",
        "source",
    }
    missing = required - col_names
    assert not missing, f"company_executives missing columns: {missing}"

    # Unique index on (ticker, name, position)
    index_columns = {tuple(idx.columns) for idx in tdef.indexes}
    assert ("ticker", "name", "position") in index_columns, (
        "company_executives missing (ticker, name, position) unique index"
    )

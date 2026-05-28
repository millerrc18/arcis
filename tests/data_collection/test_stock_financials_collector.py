"""Tests for src/data_collection/stock_financials_collector.py.

Sprint v0.36.38 (T3): plan-gated stock_financials collector.

Three tests per spec:
  1. plan=fundamental-1 -> API call made + row written + UPSERT idempotent
  2. plan=free -> NO API call (mock fully) and collector returns None
  3. Schema discipline (stock_financials table + columns + UNIQUE index)
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
    """SQLite tmp database with the stock_financials table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["stock_financials"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


# ---------------------------------------------------------------------------
# Test 1: plan=fundamental-1 -> API call + row written + UPSERT idempotent
# ---------------------------------------------------------------------------


def test_plan_fundamental_1_makes_api_call_and_writes_row(sqlite_db, monkeypatch):
    """plan=fundamental-1: gate is open, API is called, row lands in
    stock_financials with mapped values, and a repeat call upserts
    (no duplicate rows)."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.stock_financials_collector import (
        collect_stock_financials,
    )

    mock_payload = {
        "metric": {
            "peTTM": 28.5,
            "pbAnnual": 12.0,
            "roeTTM": 1.4,
            "marketCapitalization": 2900000.0,
        },
        "metricType": "all",
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.stock_financials_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.stock_financials_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call: API hit + row written.
        result1 = collect_stock_financials("AAPL", config=config, db_path=sqlite_db)
        assert result1 is not None
        assert mock_get.called, "Expected Finnhub API call when plan=fundamental-1"
        from src.data_collection.result import CollectorResult

        assert isinstance(result1, CollectorResult)
        assert result1.status == "ok"
        assert result1.primary_count == 1
        assert result1.collector_name == "stock_financials"

        # Second call: same as_of_date -> UPSERT idempotent (no duplicate row).
        result2 = collect_stock_financials("AAPL", config=config, db_path=sqlite_db)
        assert result2 is not None
        assert isinstance(result2, CollectorResult)
        assert result2.status == "ok"

    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, pe_ratio, pb_ratio, roe, market_cap "
            "FROM stock_financials WHERE ticker = ?",
            ("AAPL",),
        ).fetchall()
    assert len(rows) == 1, "Expected exactly one row after two collect calls (UPSERT)"
    assert rows[0]["ticker"] == "AAPL"
    assert abs(rows[0]["pe_ratio"] - 28.5) < 1e-6
    assert abs(rows[0]["pb_ratio"] - 12.0) < 1e-6
    assert abs(rows[0]["roe"] - 1.4) < 1e-6
    # marketCapitalization float -> int without overflow
    assert rows[0]["market_cap"] == 2900000


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns None and never touches
    requests.get (the Finnhub client). This is the spec-mandated NO-OP
    that prevents 403s from a free-tier key."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.stock_financials_collector import (
        collect_stock_financials,
    )

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.stock_financials_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.stock_financials_collector.requests.get"
    ) as mock_get:
        result = collect_stock_financials("AAPL", config=config, db_path=sqlite_db)

    assert result is None, "plan=free must return None"
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: schema discipline — stock_financials table + columns + index
# ---------------------------------------------------------------------------


def test_schema_stock_financials_table_columns_and_index():
    """Schema discipline: registry has stock_financials with the
    expected columns + UNIQUE (ticker, as_of_date) index."""
    from src.schema.registry import TABLES

    assert "stock_financials" in TABLES, (
        "stock_financials TableDef must be registered"
    )

    tdef = TABLES["stock_financials"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id",
        "ticker",
        "as_of_date",
        "pe_ratio",
        "pb_ratio",
        "ps_ratio",
        "ev_ebitda",
        "roe",
        "roa",
        "gross_margin",
        "net_margin",
        "debt_to_equity",
        "current_ratio",
        "dividend_yield",
        "market_cap",
        "week52_high",
        "week52_low",
        "retrieved_at",
        "source",
    }
    missing = required - col_names
    assert not missing, f"stock_financials missing columns: {missing}"

    # UNIQUE index on (ticker, as_of_date)
    unique_indexes = [idx for idx in tdef.indexes if idx.unique]
    unique_cols = {tuple(idx.columns) for idx in unique_indexes}
    assert ("ticker", "as_of_date") in unique_cols, (
        "stock_financials missing UNIQUE (ticker, as_of_date) index"
    )

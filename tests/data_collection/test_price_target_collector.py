"""Tests for src/data_collection/price_target_collector.py.

Sprint v0.36.38 T4: plan-gated price target collector.

Four tests per spec:
  1. plan=fundamental-1 -> API call made + row written + UPSERT idempotent
  2. plan=free -> NO API call (mock the Finnhub client; assert_not_called)
                  and collector returns None
  3. Schema discipline (price_targets table + columns + UNIQUE index)
  4. Edge: empty {} payload -> returns None, no row written
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
    """SQLite tmp database with the price_targets table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["price_targets"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


# ---------------------------------------------------------------------------
# Test 1: plan=fundamental-1 -> API call + row written + UPSERT idempotent
# ---------------------------------------------------------------------------


def test_gate_open_makes_api_call_and_writes_row(sqlite_db, monkeypatch):
    """gate OPEN (capability entitled): API is called, row lands in
    price_targets, and a repeat call upserts (no duplicate rows).

    PR-D T23 reconciliation: price_target was removed from the fundamental-1
    feature matrix in v0.36.43 (per-endpoint 403 — see finnhub_plan), so a
    real ``plan=fundamental-1`` gate is CLOSED. To exercise the API-open body
    we patch ``finnhub_plan_supports`` True (simulating a future entitling
    plan). On success the collector returns a healthy CollectorResult with
    primary_count 1 (one row written); the float target VALUES persist to the
    price_targets table (semantic narrowing — they cannot live in dict[str,int]
    metadata)."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.price_target_collector import collect_price_targets
    from src.data_collection.result import CollectorResult

    mock_payload = {
        "targetHigh": 210,
        "targetLow": 150,
        "targetMean": 185,
        "targetMedian": 188,
        "lastUpdated": "2026-05-19",
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.price_target_collector.finnhub_plan_supports",
        return_value=True,
    ), patch(
        "src.data_collection.price_target_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.price_target_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call: API hit + row written.
        result1 = collect_price_targets("AAPL", config=config, db_path=sqlite_db)
        assert isinstance(result1, CollectorResult)
        assert result1.is_healthy
        assert mock_get.called, "Expected Finnhub API call when gate is open"
        assert result1.primary_count == 1

        # Second call: same as_of_date -> UPSERT idempotent (no duplicate row).
        result2 = collect_price_targets("AAPL", config=config, db_path=sqlite_db)
        assert isinstance(result2, CollectorResult)
        assert result2.is_healthy

    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, target_mean, target_high FROM price_targets "
            "WHERE ticker = ?",
            ("AAPL",),
        ).fetchall()
    assert len(rows) == 1, "Expected exactly one row after two collect calls (UPSERT)"
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["target_mean"] == 185
    assert rows[0]["target_high"] == 210


def test_plan_fundamental_1_gated_off_no_api_call(sqlite_db, monkeypatch):
    """plan=fundamental-1: price_target is gated OFF as of v0.36.43 (the live
    feature matrix removed it after a per-endpoint 403). The collector returns
    a healthy CollectorResult with count 0 + metadata {'gated': 1} and makes
    NO API call — no row is written."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.price_target_collector import collect_price_targets
    from src.data_collection.result import CollectorResult

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.price_target_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.price_target_collector.requests.get"
    ) as mock_get:
        result = collect_price_targets("AAPL", config=config, db_path=sqlite_db)

    assert isinstance(result, CollectorResult)
    assert result.is_healthy
    assert result.primary_count == 0
    assert result.metadata.get("gated") == 1
    mock_get.assert_not_called()

    with sqlite3.connect(sqlite_db) as verify:
        count = verify.execute(
            "SELECT COUNT(*) FROM price_targets WHERE ticker = ?", ("AAPL",)
        ).fetchone()[0]
    assert count == 0, "No row should be written when price_target is gated off"


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns None and never touches
    requests.get (the Finnhub client)."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.price_target_collector import collect_price_targets
    from src.data_collection.result import CollectorResult

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.price_target_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.price_target_collector.requests.get"
    ) as mock_get:
        result = collect_price_targets("AAPL", config=config, db_path=sqlite_db)

    # Gate-closed -> healthy CollectorResult, count 0, metadata {'gated': 1}
    # (no API call). Preserves the old "no data" consumer semantics.
    assert isinstance(result, CollectorResult)
    assert result.is_healthy
    assert result.primary_count == 0
    assert result.metadata.get("gated") == 1
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: schema discipline — price_targets table + columns + UNIQUE index
# ---------------------------------------------------------------------------


def test_schema_price_targets_table_columns_and_index():
    """Schema discipline: registry has price_targets with the expected
    columns + UNIQUE (ticker, as_of_date) index."""
    from src.schema.registry import TABLES

    assert "price_targets" in TABLES, "price_targets TableDef must be registered"

    tdef = TABLES["price_targets"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id",
        "ticker",
        "as_of_date",
        "target_high",
        "target_low",
        "target_mean",
        "target_median",
        "last_updated",
        "retrieved_at",
        "source",
    }
    missing = required - col_names
    assert not missing, f"price_targets missing columns: {missing}"

    # UNIQUE index on (ticker, as_of_date)
    unique_index_columns = {
        tuple(idx.columns) for idx in tdef.indexes if idx.unique
    }
    assert ("ticker", "as_of_date") in unique_index_columns, (
        "price_targets missing UNIQUE (ticker, as_of_date) index"
    )


# ---------------------------------------------------------------------------
# Test 4: edge — empty {} payload -> returns None, no row written
# ---------------------------------------------------------------------------


def test_empty_payload_returns_healthy_count_zero_no_row_written(sqlite_db, monkeypatch):
    """Empty {} payload from Finnhub (uncovered ticker, gate open) -> healthy
    CollectorResult with count 0, no row written to price_targets.

    Gate is patched open so the empty-payload body branch (not the live
    gated-off path) is exercised."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.price_target_collector import collect_price_targets
    from src.data_collection.result import CollectorResult

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.price_target_collector.finnhub_plan_supports",
        return_value=True,
    ), patch(
        "src.data_collection.price_target_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.price_target_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = collect_price_targets("AAPL", config=config, db_path=sqlite_db)

    assert isinstance(result, CollectorResult)
    assert result.is_healthy
    assert result.primary_count == 0

    with sqlite3.connect(sqlite_db) as verify:
        count = verify.execute(
            "SELECT COUNT(*) FROM price_targets WHERE ticker = ?", ("AAPL",)
        ).fetchone()[0]
    assert count == 0, "No row should be written for empty payload"

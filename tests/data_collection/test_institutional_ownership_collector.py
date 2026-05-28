"""Tests for src/data_collection/institutional_ownership_collector.py.

Sprint 5 Wave C7b.1 (T21): plan-gated institutional ownership collector +
INSTITUTIONAL FLOW packet section.

Five tests per spec section 4.10:
  1. plan=fundamental-1 -> API call made + row written + UPSERT idempotent
  2. plan=free -> NO API call (mock the Finnhub client; assert_not_called)
                  and collector returns None
  3. Schema discipline (institutional_holdings table + columns + index)
  4. Packet section renders when plan supports + data present
  5. Packet section completely absent when plan=free (Decision 30)
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
    """SQLite tmp database with the institutional_holdings table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["institutional_holdings"])
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
    institutional_holdings, and a repeat call upserts (no duplicate rows)."""
    # FINNHUB_PLAN env override outranks config dict; set explicitly so tests
    # are hermetic regardless of operator .env (which sets fundamental-1).
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.institutional_ownership_collector import (
        collect_institutional_ownership,
    )
    from src.data_collection.result import CollectorResult

    mock_payload = {
        "ownership": [
            {
                "name": "Vanguard",
                "share": 100000,
                "change": 5000,
                "filingDate": "2026-05-01",
            },
            {
                "name": "BlackRock",
                "share": 80000,
                "change": -2000,
                "filingDate": "2026-05-01",
            },
        ],
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.institutional_ownership_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.institutional_ownership_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call: API hit + row written.
        result1 = collect_institutional_ownership("AAPL", config=config, db_path=sqlite_db)
        assert isinstance(result1, CollectorResult)
        assert result1.is_healthy
        # 2 holders aggregated into the snapshot row.
        assert result1.primary_count == 2
        assert result1.metadata["total_shares"] == 180000
        assert mock_get.called, "Expected Finnhub API call when plan=fundamental-1"

        # Second call: same as_of_date -> UPSERT idempotent (no duplicate row).
        result2 = collect_institutional_ownership("AAPL", config=config, db_path=sqlite_db)
        assert isinstance(result2, CollectorResult)
        assert result2.is_healthy

    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, num_holders, total_shares FROM institutional_holdings "
            "WHERE ticker = ?",
            ("AAPL",),
        ).fetchall()
    assert len(rows) == 1, "Expected exactly one row after two collect calls (UPSERT)"
    assert rows[0]["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns None and never touches
    requests.get (the Finnhub client). This is the spec-mandated NO-OP
    that prevents 403s from a free-tier key."""
    # FINNHUB_PLAN env outranks config dict; force 'free' here so the test
    # is hermetic regardless of operator .env (which sets fundamental-1).
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.institutional_ownership_collector import (
        collect_institutional_ownership,
    )
    from src.data_collection.result import CollectorResult

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.institutional_ownership_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.institutional_ownership_collector.requests.get"
    ) as mock_get:
        result = collect_institutional_ownership("AAPL", config=config, db_path=sqlite_db)

    # Gate-closed -> healthy CollectorResult, count 0, metadata {'gated': 1}
    # (no API call). Preserves the old "no data" consumer semantics.
    assert isinstance(result, CollectorResult)
    assert result.is_healthy
    assert result.primary_count == 0
    assert result.metadata.get("gated") == 1
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: schema discipline — institutional_holdings table + columns + index
# ---------------------------------------------------------------------------


def test_schema_institutional_holdings_table_columns_and_index():
    """Schema discipline: registry has institutional_holdings with the
    expected columns + index per spec section 3.1c."""
    from src.schema.registry import TABLES

    assert "institutional_holdings" in TABLES, (
        "institutional_holdings TableDef must be registered"
    )

    tdef = TABLES["institutional_holdings"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id",
        "ticker",
        "as_of_date",
        "total_shares",
        "num_holders",
        "top_5_holders_pct",
        "qoq_delta_pct",
        "retrieved_at",
        "source",
    }
    missing = required - col_names
    assert not missing, f"institutional_holdings missing columns: {missing}"

    # Index on (ticker, as_of_date)
    index_columns = {tuple(idx.columns) for idx in tdef.indexes}
    assert ("ticker", "as_of_date") in index_columns, (
        "institutional_holdings missing (ticker, as_of_date) index"
    )


# ---------------------------------------------------------------------------
# Test 4: packet section renders when plan supports + data present
# ---------------------------------------------------------------------------


def test_packet_section_renders_when_plan_supports_and_data_present():
    """plan=fundamental-1 + institutional_* feature fields present -> the
    INSTITUTIONAL FLOW section appears in the prompt with the data values."""
    from src.llm.packet_writer import _build_feature_prompt

    features = {
        "current_price": 150.0,
        "trend_state": "uptrend",
        "sma50_slope": "positive",
        "sma200_slope": "positive",
        "price_vs_sma50_pct": 5.0,
        "price_vs_sma200_pct": 10.0,
        "relative_strength_state": "strong",
        "rs_vs_spy_1m": 2.0,
        "rs_vs_spy_3m": 4.0,
        "rs_vs_spy_6m": 7.0,
        "pullback_depth_pct": 3.0,
        "atr_14": 2.5,
        "atr_pct": 1.5,
        "volume_ratio_20d": 1.2,
        "dist_to_sma20_pct": 1.0,
        # INSTITUTIONAL FLOW (Tier-2 C7b.1) — plan supports + data present.
        "_institutional_plan_supports": True,
        "institutional_total_shares": 142_300_000,
        "institutional_num_holders": 1847,
        "institutional_top5_pct": 32.1,
        "institutional_qoq_delta_pct": 2.3,
        "institutional_data_age_days": 5,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== INSTITUTIONAL FLOW ===" in prompt, (
        "INSTITUTIONAL FLOW section should render when plan supports + data present"
    )
    # Spot-check rendered values.
    assert "1847" in prompt or "1,847" in prompt
    assert "32.1" in prompt


# ---------------------------------------------------------------------------
# Test 5: packet section completely absent when plan does not support
# ---------------------------------------------------------------------------


def test_packet_section_absent_when_plan_does_not_support():
    """plan=free / plan-not-supported -> INSTITUTIONAL FLOW section MUST be
    completely absent from the prompt (Decision 30 — not rendered with
    placeholder text). The enricher signals this via
    `_institutional_plan_supports` False/absent in the feature dict."""
    from src.llm.packet_writer import _build_feature_prompt

    features = {
        "current_price": 150.0,
        "trend_state": "uptrend",
        "sma50_slope": "positive",
        "sma200_slope": "positive",
        "price_vs_sma50_pct": 5.0,
        "price_vs_sma200_pct": 10.0,
        "relative_strength_state": "strong",
        "rs_vs_spy_1m": 2.0,
        "rs_vs_spy_3m": 4.0,
        "rs_vs_spy_6m": 7.0,
        "pullback_depth_pct": 3.0,
        "atr_14": 2.5,
        "atr_pct": 1.5,
        "volume_ratio_20d": 1.2,
        "dist_to_sma20_pct": 1.0,
        # Plan does NOT support institutional_ownership.
        "_institutional_plan_supports": False,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    # NOTE: the literal string "INSTITUTIONAL FLOW" appears in the T24
    # DATA CONTEXT header's omitted-sections list; the section header
    # (=== INSTITUTIONAL FLOW ===) is what must be absent here.
    assert "=== INSTITUTIONAL FLOW ===" not in prompt, (
        "INSTITUTIONAL FLOW section header MUST be absent when plan does "
        "not support institutional_ownership (Decision 30)"
    )

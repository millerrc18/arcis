"""Tests for src/data_collection/filings_sentiment_collector.py.

Sprint 5 Wave C7b.2 (T22): plan-gated filings_sentiment collector +
MATERIAL EVENTS packet section seed (filings_sentiment sub-block).

Five tests per spec section 4.11:
  1. plan=fundamental-1 -> API call made + row written + UPSERT idempotent
  2. plan=free -> NO API call (mock the Finnhub client; assert_not_called)
                  and collector returns None
  3. Schema discipline (filings_sentiment table + columns + index)
  4. Packet sub-block renders when plan supports + data present
  5. Packet sub-block omits when plan does not support
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
    """SQLite tmp database with the filings_sentiment table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["filings_sentiment"])
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
    filings_sentiment, and a repeat call upserts (no duplicate rows)."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.filings_sentiment_collector import (
        collect_filings_sentiment,
    )

    mock_payload = {
        "sentiment": [
            {
                "type": "10-K",
                "filedDate": "2026-05-01 10:00:00",
                "sentiment": {"score": 0.42},
            },
            {
                "type": "10-Q",
                "filedDate": "2026-04-15 10:00:00",
                "sentiment": {"score": -0.1},
            },
        ],
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.filings_sentiment_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.filings_sentiment_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call: API hit + rows written.
        result1 = collect_filings_sentiment("AAPL", config=config, db_path=sqlite_db)
        assert result1 is not None
        assert mock_get.called, "Expected Finnhub API call when plan=fundamental-1"

        # Second call: same (ticker, filing_type, filed_at) -> UPSERT idempotent.
        result2 = collect_filings_sentiment("AAPL", config=config, db_path=sqlite_db)
        assert result2 is not None

    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, filing_type, sentiment_score FROM filings_sentiment "
            "WHERE ticker = ?",
            ("AAPL",),
        ).fetchall()
    assert len(rows) == 2, (
        f"Expected exactly 2 rows after two collect calls (UPSERT); got {len(rows)}"
    )
    types = sorted(r["filing_type"] for r in rows)
    assert types == ["10-K", "10-Q"]


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns None and never touches
    requests.get (the Finnhub client). This is the spec-mandated NO-OP
    that prevents 403s from a free-tier key."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.filings_sentiment_collector import (
        collect_filings_sentiment,
    )

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.filings_sentiment_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.filings_sentiment_collector.requests.get"
    ) as mock_get:
        result = collect_filings_sentiment("AAPL", config=config, db_path=sqlite_db)

    assert result is None, "plan=free must return None"
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: schema discipline — filings_sentiment table + columns + index
# ---------------------------------------------------------------------------


def test_schema_filings_sentiment_table_columns_and_index():
    """Schema discipline: registry has filings_sentiment with the
    expected columns + index per spec section 3.1c."""
    from src.schema.registry import TABLES

    assert "filings_sentiment" in TABLES, (
        "filings_sentiment TableDef must be registered"
    )

    tdef = TABLES["filings_sentiment"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id",
        "ticker",
        "filing_type",
        "filed_at",
        "sentiment_score",
        "sentiment_label",
        "retrieved_at",
    }
    missing = required - col_names
    assert not missing, f"filings_sentiment missing columns: {missing}"

    # Index on (ticker, filed_at)
    index_columns = {tuple(idx.columns) for idx in tdef.indexes}
    assert ("ticker", "filed_at") in index_columns, (
        "filings_sentiment missing (ticker, filed_at) index"
    )


# ---------------------------------------------------------------------------
# Test 4: packet sub-block renders when plan supports + data present
# ---------------------------------------------------------------------------


def test_packet_subblock_renders_when_plan_supports_and_data_present():
    """plan=fundamental-1 + filing_sentiment_* feature fields present -> the
    MATERIAL EVENTS section appears in the prompt with the filings_sentiment
    sub-block populated."""
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
        # MATERIAL EVENTS / filings_sentiment (T22) — plan supports + data present.
        "_filings_sentiment_plan_supports": True,
        "filing_sentiment_score": 0.42,
        "filing_sentiment_label": "positive",
        "latest_filing_type": "10-K",
        "latest_filing_age_days": 7,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== MATERIAL EVENTS ===" in prompt, (
        "MATERIAL EVENTS section should render when filings_sentiment plan "
        "supports + data present"
    )
    # Spot-check rendered values.
    assert "10-K" in prompt
    assert "0.42" in prompt or "+0.42" in prompt
    assert "positive" in prompt


# ---------------------------------------------------------------------------
# Test 5: packet sub-block omits when plan does not support
# ---------------------------------------------------------------------------


def test_packet_subblock_omits_when_plan_does_not_support():
    """plan=free / plan-not-supported -> MATERIAL EVENTS section MUST be
    completely absent from the prompt when filings_sentiment is the only
    sub-block and it's plan-gated off (T22 seed; T23 will add the second
    sub-block, after which the composition rule applies independently)."""
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
        # Plan does NOT support filings_sentiment.
        "_filings_sentiment_plan_supports": False,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    # NOTE: the literal string "MATERIAL EVENTS" appears in the T24
    # DATA CONTEXT header's omitted-sections list; the section header
    # (=== MATERIAL EVENTS ===) is what must be absent here.
    assert "=== MATERIAL EVENTS ===" not in prompt, (
        "MATERIAL EVENTS section header MUST be absent when no sub-blocks "
        "have plan-support (Decision 30, T22 composition rule)"
    )

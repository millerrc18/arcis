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


def test_plan_fundamental_1_is_gated_off_after_v0_36_25(sqlite_db, monkeypatch):
    """v0.36.25 (2026-05-19): filings_sentiment was removed from
    `_FEATURE_MATRIX["fundamental-1"]` because the Finnhub
    `/stock/filings-sentiment` endpoint returns body `{}` (no data) for
    every ticker. Until a working endpoint is confirmed with Finnhub
    support, plan-gating it off stops wasted API quota.

    This test pins the gated-off behavior: even on the paid plan, the
    collector returns a healthy gated CollectorResult (PR-D T21b: count 0,
    metadata {'gated': 1}) without making an API call.
    """
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.filings_sentiment_collector import (
        collect_filings_sentiment,
    )
    from src.data_collection.result import CollectorResult

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.filings_sentiment_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.filings_sentiment_collector.requests.get"
    ) as mock_get:
        result = collect_filings_sentiment("AAPL", config=config, db_path=sqlite_db)
        assert isinstance(result, CollectorResult), (
            "filings_sentiment must return a CollectorResult (PR-D T21b)."
        )
        assert result.is_healthy, "gate-closed is not an error — must be healthy"
        assert result.primary_count == 0, "gate-closed run wrote zero rows"
        assert result.metadata.get("gated") == 1, (
            "gate-closed must flag metadata {'gated': 1} so it is "
            "distinguishable from a healthy-but-empty run — it is plan-gated "
            "off after v0.36.25 because /stock/filings-sentiment returns `{}`."
        )
        assert not mock_get.called, (
            "filings_sentiment must NOT call Finnhub — the plan-gate filter "
            "should short-circuit before any HTTP request is attempted. "
            "If this test fails, check `_FEATURE_MATRIX['fundamental-1']` "
            "in src/data_enrichment/finnhub_plan.py."
        )


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns a healthy gated
    CollectorResult (PR-D T21b) and never touches requests.get (the Finnhub
    client). This is the spec-mandated NO-OP that prevents 403s from a
    free-tier key."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.filings_sentiment_collector import (
        collect_filings_sentiment,
    )
    from src.data_collection.result import CollectorResult

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.filings_sentiment_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.filings_sentiment_collector.requests.get"
    ) as mock_get:
        result = collect_filings_sentiment("AAPL", config=config, db_path=sqlite_db)

    assert isinstance(result, CollectorResult), "plan=free must return a CollectorResult"
    assert result.is_healthy and result.primary_count == 0
    assert result.metadata.get("gated") == 1, "plan=free is gate-closed"
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


# ---------------------------------------------------------------------------
# Test 6-8: CollectorResult return-shape (PR-D T21b)
# ---------------------------------------------------------------------------


def _open_plan_config():
    return {"data_enrichment": {"finnhub_plan": "fundamental-1"}}


def test_returns_ok_collector_result_with_rows_written(sqlite_db, monkeypatch):
    """Gate open + filings returned -> ok CollectorResult, count == rows."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection import filings_sentiment_collector as mod
    from src.data_collection.result import CollectorResult

    filings = [
        {"type": "10-K", "filedDate": "2024-11-01", "sentiment": {"score": 0.5}},
        {"type": "8-K", "filedDate": "2024-11-02", "sentiment": {"score": -0.3}},
    ]
    with patch.object(mod, "finnhub_plan_supports", return_value=True), \
         patch.object(mod, "_get_finnhub_key", return_value="test-key"), \
         patch.object(mod, "_fetch_finnhub_filings_sentiment", return_value=filings):
        result = mod.collect_filings_sentiment(
            "AAPL", config=_open_plan_config(), db_path=sqlite_db
        )

    assert isinstance(result, CollectorResult)
    assert result.status == "ok"
    assert result.primary_count == 2
    assert result.is_healthy


def test_returns_ok_zero_when_response_empty(sqlite_db, monkeypatch):
    """Gate open + empty list -> ok CollectorResult, count 0 (NOT failed)."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection import filings_sentiment_collector as mod
    from src.data_collection.result import CollectorResult

    with patch.object(mod, "finnhub_plan_supports", return_value=True), \
         patch.object(mod, "_get_finnhub_key", return_value="test-key"), \
         patch.object(mod, "_fetch_finnhub_filings_sentiment", return_value=[]):
        result = mod.collect_filings_sentiment(
            "AAPL", config=_open_plan_config(), db_path=sqlite_db
        )

    assert isinstance(result, CollectorResult)
    assert result.status == "ok"
    assert result.primary_count == 0
    assert result.is_healthy
    assert result.metadata.get("gated") is None, (
        "empty-response is NOT gated — only the plan-gate path sets gated=1"
    )


def test_returns_failed_when_fetch_fails(sqlite_db, monkeypatch):
    """Gate open + fetch returns None (API failure) -> failed CollectorResult."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection import filings_sentiment_collector as mod
    from src.data_collection.result import CollectorResult

    with patch.object(mod, "finnhub_plan_supports", return_value=True), \
         patch.object(mod, "_get_finnhub_key", return_value="test-key"), \
         patch.object(mod, "_fetch_finnhub_filings_sentiment", return_value=None):
        result = mod.collect_filings_sentiment(
            "AAPL", config=_open_plan_config(), db_path=sqlite_db
        )

    assert isinstance(result, CollectorResult)
    assert result.status == "failed"
    assert not result.is_healthy

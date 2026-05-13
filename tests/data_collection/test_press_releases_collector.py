"""Tests for src/data_collection/press_releases_collector.py.

Sprint 5 Wave C7b.3 (T23): plan-gated press_releases collector +
MATERIAL EVENTS packet section press_releases sub-block.

Six tests per spec section 4.12:
  1. plan=fundamental-1 -> API call made + row written + UPSERT idempotent
  2. plan=free          -> NO API call (mock the Finnhub client; assert_not_called)
                           and collector returns None
  3. Schema discipline (press_releases table + columns + index)
  4. Packet sub-block renders when plan supports + data present
  5. Packet sub-block omits when plan does not support
  6. MATERIAL EVENTS section integration — only press_releases supported
     (filings_sentiment NOT supported): section renders with only the
     press-releases sub-block. (Composition rule cross-check.)
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
    """SQLite tmp database with the press_releases table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["press_releases"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


# ---------------------------------------------------------------------------
# Test 1: plan=fundamental-1 -> API call + row written + UPSERT idempotent
# ---------------------------------------------------------------------------


def test_plan_fundamental_1_makes_api_call_and_writes_row(sqlite_db, monkeypatch):
    """plan=fundamental-1: gate is open, API is called, rows land in
    press_releases, and a repeat call upserts (no duplicate rows)."""
    monkeypatch.setenv("FINNHUB_PLAN", "fundamental-1")
    from src.data_collection.press_releases_collector import (
        collect_press_releases,
    )

    mock_payload = {
        "majorDevelopment": [
            {
                "headline": "Apple announces record Q4 revenue",
                "datetime": "2026-05-08 13:00:00",
                "url": "https://example.com/pr1",
                "description": "Apple set a new revenue record.",
            },
            {
                "headline": "Apple unveils new AI product line",
                "datetime": "2026-05-01 13:00:00",
                "url": "https://example.com/pr2",
                "description": "New AI product line announced.",
            },
        ],
        "symbol": "AAPL",
    }

    config = {"data_enrichment": {"finnhub_plan": "fundamental-1"}}

    with patch(
        "src.data_collection.press_releases_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.press_releases_collector.requests.get"
    ) as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call: API hit + rows written.
        result1 = collect_press_releases("AAPL", config=config, db_path=sqlite_db)
        assert result1 is not None
        assert mock_get.called, "Expected Finnhub API call when plan=fundamental-1"

        # Second call: same (ticker, headline, released_at) -> UPSERT idempotent.
        result2 = collect_press_releases("AAPL", config=config, db_path=sqlite_db)
        assert result2 is not None

    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, headline, released_at FROM press_releases "
            "WHERE ticker = ?",
            ("AAPL",),
        ).fetchall()
    assert len(rows) == 2, (
        f"Expected exactly 2 rows after two collect calls (UPSERT); got {len(rows)}"
    )
    headlines = sorted(r["headline"] for r in rows)
    assert "Apple announces record Q4 revenue" in headlines
    assert "Apple unveils new AI product line" in headlines


# ---------------------------------------------------------------------------
# Test 2: plan=free -> no API call + collector returns None
# ---------------------------------------------------------------------------


def test_plan_free_no_api_call(sqlite_db, monkeypatch):
    """plan=free: gate is closed; collector returns None and never touches
    requests.get (the Finnhub client). NO-OP that prevents 403s from a
    free-tier key (Decision 30)."""
    monkeypatch.setenv("FINNHUB_PLAN", "free")
    from src.data_collection.press_releases_collector import (
        collect_press_releases,
    )

    config = {"data_enrichment": {"finnhub_plan": "free"}}

    with patch(
        "src.data_collection.press_releases_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.press_releases_collector.requests.get"
    ) as mock_get:
        result = collect_press_releases("AAPL", config=config, db_path=sqlite_db)

    assert result is None, "plan=free must return None"
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: schema discipline — press_releases table + columns + index
# ---------------------------------------------------------------------------


def test_schema_press_releases_table_columns_and_index():
    """Schema discipline: registry has press_releases with the
    expected columns + index per spec section 3.1c."""
    from src.schema.registry import TABLES

    assert "press_releases" in TABLES, (
        "press_releases TableDef must be registered"
    )

    tdef = TABLES["press_releases"]
    col_names = {c.name for c in tdef.columns}
    required = {
        "id",
        "ticker",
        "headline",
        "released_at",
        "retrieved_at",
    }
    missing = required - col_names
    assert not missing, f"press_releases missing columns: {missing}"

    # Index on (ticker, released_at)
    index_columns = {tuple(idx.columns) for idx in tdef.indexes}
    assert ("ticker", "released_at") in index_columns, (
        "press_releases missing (ticker, released_at) index"
    )


# ---------------------------------------------------------------------------
# Test 4: packet sub-block renders when plan supports + data present
# ---------------------------------------------------------------------------


def test_packet_subblock_renders_when_plan_supports_and_data_present():
    """plan=fundamental-1 + press_release_* feature fields present -> the
    MATERIAL EVENTS section appears in the prompt with the press_releases
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
        # MATERIAL EVENTS / press_releases (T23) — plan supports + data present.
        "_press_releases_plan_supports": True,
        "press_release_count_7d": 3,
        "latest_press_release_headline": "Apple announces record Q4 revenue",
        "latest_press_release_age_days": 2,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== MATERIAL EVENTS ===" in prompt, (
        "MATERIAL EVENTS section should render when press_releases plan "
        "supports + data present"
    )
    # Spot-check rendered values.
    assert "Apple announces record Q4 revenue" in prompt
    assert "3" in prompt  # count
    assert "2 day" in prompt  # age


# ---------------------------------------------------------------------------
# Test 5: packet sub-block omits when plan does not support
# ---------------------------------------------------------------------------


def test_packet_subblock_omits_when_plan_does_not_support():
    """plan=free / plan-not-supported -> press_releases sub-block must NOT
    contribute content. When it's the ONLY sub-block in MATERIAL EVENTS that
    might render, the entire section is absent."""
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
        # Neither sub-block plan-supported.
        "_press_releases_plan_supports": False,
        "_filings_sentiment_plan_supports": False,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    assert "MATERIAL EVENTS" not in prompt, (
        "MATERIAL EVENTS section MUST be absent when no sub-blocks have "
        "plan-support (Decision 30, composition rule)"
    )


# ---------------------------------------------------------------------------
# Test 6: MATERIAL EVENTS section integration — only press_releases supported
# ---------------------------------------------------------------------------


def test_material_events_renders_with_only_press_releases_subblock():
    """Composition rule cross-check: when ONLY press_releases is supported
    (filings_sentiment NOT supported), the MATERIAL EVENTS section MUST
    render with only the press-releases sub-block — no leftover blank line
    from the absent filings_sentiment sub-block, no header without body."""
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
        # press_releases supports + data present; filings_sentiment plan-gated off.
        "_press_releases_plan_supports": True,
        "press_release_count_7d": 1,
        "latest_press_release_headline": "Apple unveils new AI product line",
        "latest_press_release_age_days": 1,
        "_filings_sentiment_plan_supports": False,
    }
    prompt = _build_feature_prompt(features, "AAPL")
    assert "=== MATERIAL EVENTS ===" in prompt, (
        "MATERIAL EVENTS section MUST render when at least one sub-block "
        "(press_releases) has content"
    )
    assert "Apple unveils new AI product line" in prompt
    # filings_sentiment fields should not appear (sub-block absent).
    assert "Filing sentiment" not in prompt
    assert "Latest filing:" not in prompt

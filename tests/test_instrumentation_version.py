"""Tests for instrumentation_version schema, backfill SQL, and filter_to_version.

Track 1.5 / B5 — pass 2 foundation.

Three test groups:
  T1 — Backfill SQL correctness: quarantined->v0, pre-Apr-9->v1, Apr-9-to-merge->v2, after->v3
  T2 — New trade opens with instrumentation_version stamped at value from constant
  T3 — filter_to_version subsets by min_version correctly

All DB fixtures use in-memory SQLite; no writes to prod DB.
"""
from __future__ import annotations

import sqlite3

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BACKFILL_MERGE_DATE = "2026-04-26"  # synthetic merge date for tests

BACKFILL_SQL = f"""
UPDATE shadow_trades
SET instrumentation_version = CASE
    WHEN COALESCE(quarantined, 0) = 1       THEN 0
    WHEN actual_entry_time < '2026-04-09'   THEN 1
    WHEN actual_entry_time < '{BACKFILL_MERGE_DATE}' THEN 2
    ELSE 3
END
WHERE instrumentation_version IS NULL;
"""


def _make_db() -> sqlite3.Connection:
    """Create an in-memory shadow_trades table with the columns needed for backfill."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            quarantined INTEGER DEFAULT 0,
            actual_entry_time TEXT,
            instrumentation_version INTEGER,
            llm_timeout_days INTEGER,
            timeout_days INTEGER DEFAULT 15
        )
    """)
    return conn


# ---------------------------------------------------------------------------
# T1 — Backfill correctness
# ---------------------------------------------------------------------------

def test_backfill_quarantined_row_gets_version_0():
    """quarantined=1 row → version 0, regardless of actual_entry_time."""
    conn = _make_db()
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, quarantined, actual_entry_time) VALUES (?, ?, ?)",
        ("row-A", 1, "2026-04-05T09:30:00"),
    )
    conn.execute(BACKFILL_SQL)
    row = conn.execute(
        "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 'row-A'"
    ).fetchone()
    assert row["instrumentation_version"] == 0


def test_backfill_pre_apr9_row_gets_version_1():
    """Non-quarantined row with actual_entry_time < 2026-04-09 → version 1."""
    conn = _make_db()
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, quarantined, actual_entry_time) VALUES (?, ?, ?)",
        ("row-B", 0, "2026-04-07T10:00:00"),
    )
    conn.execute(BACKFILL_SQL)
    row = conn.execute(
        "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 'row-B'"
    ).fetchone()
    assert row["instrumentation_version"] == 1


def test_backfill_apr9_to_merge_row_gets_version_2():
    """Non-quarantined row with actual_entry_time in [2026-04-09, merge_date) → version 2."""
    conn = _make_db()
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, quarantined, actual_entry_time) VALUES (?, ?, ?)",
        ("row-C", 0, "2026-04-12T14:30:00"),
    )
    conn.execute(BACKFILL_SQL)
    row = conn.execute(
        "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 'row-C'"
    ).fetchone()
    assert row["instrumentation_version"] == 2


def test_backfill_post_merge_row_gets_version_3():
    """Non-quarantined row with actual_entry_time >= merge_date → version 3."""
    conn = _make_db()
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, quarantined, actual_entry_time) VALUES (?, ?, ?)",
        ("row-D", 0, "2026-04-26T09:30:00"),
    )
    conn.execute(BACKFILL_SQL)
    row = conn.execute(
        "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 'row-D'"
    ).fetchone()
    assert row["instrumentation_version"] == 3


def test_backfill_null_entry_time_gets_version_3():
    """actual_entry_time=NULL with quarantined=0 falls into ELSE 3 branch.

    Decision: NULL entry time means the trade was inserted by a post-Track-1.5
    writer (DEFAULT 3 path). Belt-and-braces backfill assigns v3.
    """
    conn = _make_db()
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, quarantined, actual_entry_time) VALUES (?, ?, ?)",
        ("row-E", 0, None),
    )
    conn.execute(BACKFILL_SQL)
    row = conn.execute(
        "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 'row-E'"
    ).fetchone()
    assert row["instrumentation_version"] == 3


def test_backfill_skips_already_stamped_rows():
    """Rows with instrumentation_version already set are NOT updated (WHERE IS NULL guard)."""
    conn = _make_db()
    conn.execute("""
        INSERT INTO shadow_trades (trade_id, quarantined, actual_entry_time, instrumentation_version)
        VALUES (?, ?, ?, ?)
    """, ("row-F", 0, "2026-04-07T10:00:00", 99))
    conn.execute(BACKFILL_SQL)
    row = conn.execute(
        "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 'row-F'"
    ).fetchone()
    assert row["instrumentation_version"] == 99  # unchanged


def test_backfill_zero_rows_is_noop():
    """Backfill against empty table updates 0 rows — no exception raised."""
    conn = _make_db()
    cursor = conn.execute(BACKFILL_SQL)
    assert cursor.rowcount == 0


# ---------------------------------------------------------------------------
# T2 — New trade open stamped with INSTRUMENTATION_VERSION_CURRENT
# ---------------------------------------------------------------------------

def test_executor_constant_is_3():
    """INSTRUMENTATION_VERSION_CURRENT == 3 — flipped by Round 4 of Pass 2 once
    B1 + B3 + B4 + B8 all landed. v3 means "post-Track-1.5: full instrumentation"
    (exit slippage + Key Risk + LLM-set timeout + reconciled exit_reason)."""
    from src.shadow_trading.executor import INSTRUMENTATION_VERSION_CURRENT
    assert INSTRUMENTATION_VERSION_CURRENT == 3


def test_executor_global_default_timeout_is_15():
    """GLOBAL_DEFAULT_TIMEOUT_DAYS must equal 15."""
    from src.shadow_trading.executor import GLOBAL_DEFAULT_TIMEOUT_DAYS
    assert GLOBAL_DEFAULT_TIMEOUT_DAYS == 15


# ---------------------------------------------------------------------------
# T3 — filter_to_version
# ---------------------------------------------------------------------------

def test_filter_to_version_default_returns_only_v3():
    """Default min_version=3: only v3 rows pass."""
    from src.analytics.instrumentation import filter_to_version

    trades = [
        {"trade_id": "a", "instrumentation_version": 0},
        {"trade_id": "b", "instrumentation_version": 1},
        {"trade_id": "c", "instrumentation_version": 2},
        {"trade_id": "d", "instrumentation_version": 3},
    ]
    result = filter_to_version(trades)
    assert len(result) == 1
    assert result[0]["trade_id"] == "d"


def test_filter_to_version_min2_returns_v2_and_v3():
    """min_version=2: v2 and v3 rows pass; v0 and v1 are excluded."""
    from src.analytics.instrumentation import filter_to_version

    trades = [
        {"trade_id": "a", "instrumentation_version": 0},
        {"trade_id": "b", "instrumentation_version": 1},
        {"trade_id": "c", "instrumentation_version": 2},
        {"trade_id": "d", "instrumentation_version": 3},
    ]
    result = filter_to_version(trades, min_version=2)
    ids = [r["trade_id"] for r in result]
    assert ids == ["c", "d"]


def test_filter_to_version_missing_key_treated_as_v0():
    """Row without instrumentation_version key is treated as version 0 — excluded."""
    from src.analytics.instrumentation import filter_to_version

    trades = [
        {"trade_id": "no-version"},
        {"trade_id": "has-version", "instrumentation_version": 3},
    ]
    result = filter_to_version(trades, min_version=3)
    assert len(result) == 1
    assert result[0]["trade_id"] == "has-version"


def test_filter_to_version_null_value_treated_as_v0():
    """Row with instrumentation_version=None is treated as version 0 — excluded."""
    from src.analytics.instrumentation import filter_to_version

    trades = [
        {"trade_id": "null-version", "instrumentation_version": None},
        {"trade_id": "v3", "instrumentation_version": 3},
    ]
    result = filter_to_version(trades, min_version=3)
    assert len(result) == 1
    assert result[0]["trade_id"] == "v3"


def test_filter_to_version_returns_list_for_list_input():
    """Input list-of-dicts → output list-of-dicts (not a generator or other type)."""
    from src.analytics.instrumentation import filter_to_version

    trades = [{"trade_id": "v3", "instrumentation_version": 3}]
    result = filter_to_version(trades)
    assert isinstance(result, list)


def test_filter_to_version_does_not_mutate_input():
    """filter_to_version must not modify the input list in-place."""
    from src.analytics.instrumentation import filter_to_version

    trades = [
        {"trade_id": "a", "instrumentation_version": 0},
        {"trade_id": "b", "instrumentation_version": 3},
    ]
    original_len = len(trades)
    filter_to_version(trades)
    assert len(trades) == original_len


def test_filter_to_version_dataframe_input():
    """DataFrame input → DataFrame output (filtered, same type). Skipped if pandas absent."""
    pd = pytest.importorskip("pandas")
    from src.analytics.instrumentation import filter_to_version

    df = pd.DataFrame([
        {"trade_id": "a", "instrumentation_version": 0},
        {"trade_id": "b", "instrumentation_version": 2},
        {"trade_id": "c", "instrumentation_version": 3},
    ])
    result = filter_to_version(df, min_version=3)
    assert hasattr(result, "iloc"), "Expected DataFrame output"
    assert len(result) == 1
    assert result.iloc[0]["trade_id"] == "c"

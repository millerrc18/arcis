"""Schema migration tests for Sprint 2 Task 8 — desk tag on shadow_trades.

Non-negotiable gate:
  test_existing_rows_backfill_desk_to_swing — all existing rows must
  land at desk='swing' after ensure_columns runs.
"""
import sqlite3

import pytest

from src.schema.registry import TABLES
from src.schema.sqlite import ensure_columns, generate_create_sql


def test_shadow_trades_has_desk_column():
    cols = {c.name for c in TABLES["shadow_trades"].columns}
    assert "desk" in cols


def test_shadow_trades_has_research_thesis_column():
    cols = {c.name for c in TABLES["shadow_trades"].columns}
    assert "research_thesis" in cols


def test_shadow_trades_has_strategy_spec_hash_column():
    cols = {c.name for c in TABLES["shadow_trades"].columns}
    assert "strategy_spec_hash" in cols


def test_desk_column_has_swing_default():
    """The default='swing' is what backfills all 85 existing rows."""
    desk_col = next(c for c in TABLES["shadow_trades"].columns if c.name == "desk")
    # The ColumnDef stores the default under some attribute — check both
    default = getattr(desk_col, "default", None) or getattr(desk_col, "default_value", None)
    assert default == "swing"


def test_desk_index_present():
    index_names = {i.name for i in TABLES["shadow_trades"].indexes}
    assert "idx_shadow_trades_desk" in index_names


def test_existing_rows_backfill_desk_to_swing(tmp_path):
    """Simulate the real migration scenario:
    1. Create a SQLite DB with the OLD shadow_trades schema (no desk column).
    2. Insert 3 rows.
    3. Run ensure_columns.
    4. Verify all 3 rows now have desk='swing'.
    """
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)

    # Create an OLD-schema shadow_trades table (pre-desk columns).
    # Use a minimal subset of columns that existed before this sprint.
    conn.executescript("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            entry_time TEXT
        );
        INSERT INTO shadow_trades (trade_id, ticker, entry_time) VALUES
            ('t1', 'AAPL', '2024-01-01'),
            ('t2', 'MSFT', '2024-01-02'),
            ('t3', 'GOOGL', '2024-01-03');
    """)
    conn.commit()
    conn.close()

    # Run the migration
    ensure_columns(str(db))

    # Verify desk is now populated
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT trade_id, desk FROM shadow_trades ORDER BY trade_id"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    for r in rows:
        assert r["desk"] == "swing", \
            f"row {r['trade_id']} has desk={r['desk']!r}, expected 'swing'"
    # Count nulls — must be zero
    conn = sqlite3.connect(db)
    null_count = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE desk IS NULL"
    ).fetchone()[0]
    conn.close()
    assert null_count == 0


def test_research_thesis_and_spec_hash_stay_null_on_existing_rows(tmp_path):
    """desk gets a DEFAULT so existing rows backfill. research_thesis
    and strategy_spec_hash have NO default (only research trades set
    them) — they must stay NULL on old rows."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL
        );
        INSERT INTO shadow_trades (trade_id, ticker) VALUES
            ('t1', 'AAPL');
    """)
    conn.commit()
    conn.close()

    ensure_columns(str(db))

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT research_thesis, strategy_spec_hash FROM shadow_trades "
        "WHERE trade_id = 't1'"
    ).fetchone()
    conn.close()
    assert row["research_thesis"] is None
    assert row["strategy_spec_hash"] is None

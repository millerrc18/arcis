"""PR-690 O7 — shadow_trades.quarantined NOT NULL migration tests.

Covers scripts/migrate_shadow_trades_quarantined_not_null_2026_04_26.py:
  (1) Backfill: rows with quarantined=NULL get set to 0
  (2) Rebuild: column ends up with NOT NULL constraint
  (3) Idempotency: re-run is a no-op (zero rows backfilled, no rebuild)
  (4) Mixed: rows with mixed NULL/0/1 are handled correctly
  (5) FK preservation: recommendations FK survives the rebuild
  (6) Index preservation: registered indexes survive the rebuild
  (7) Dry-run: --apply=False is read-only
  (8) BATCH_SIZE >=50 (per backfill memory pattern)
  (9) Bulk: rebuild succeeds with >BATCH_SIZE rows
"""

from __future__ import annotations

import os
import sys

import pytest

# Make the migration module importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.migrate_shadow_trades_quarantined_not_null_2026_04_26 import (  # noqa: E501
    BATCH_SIZE,
    backfill_null_quarantined,
    find_null_quarantined_trade_ids,
    is_quarantined_not_null,
    rebuild_shadow_trades_with_not_null,
    run_migration,
)
from src.schema.registry import TABLES
from src.utils.db import connect_db


# ---------------------------------------------------------------------------
# Fixtures: build a faithful pre-migration shadow_trades schema.
# ---------------------------------------------------------------------------

def _create_pre_migration_schema(db_path: str) -> None:
    """Create shadow_trades AS IT WAS BEFORE PR-690 O7 (quarantined nullable).

    We hand-build the CREATE TABLE so the constraint we are migrating away from
    actually exists at the start of the test. We also create the recommendations
    parent table so the registry FK is well-formed.
    """
    import sqlite3
    conn = sqlite3.connect(db_path)
    # Minimal recommendations parent — only needs the PK column for the FK.
    conn.execute(
        "CREATE TABLE recommendations (recommendation_id TEXT PRIMARY KEY)"
    )
    # Minimal strategy_registry parent — the rebuilt (registry-schema)
    # shadow_trades carries FOREIGN KEY (strategy_id) REFERENCES
    # strategy_registry(strategy_id), so the FK target must exist or the
    # post-rebuild INSERT fails on "no such table" before reaching the
    # quarantined NOT NULL check under test.
    conn.execute(
        "CREATE TABLE strategy_registry (strategy_id TEXT PRIMARY KEY)"
    )
    # Pre-migration shadow_trades — derived from the registry but with
    # quarantined nullable (DEFAULT 0 only).
    pre_columns = []
    for col in TABLES["shadow_trades"].columns:
        # Render columns as they were before O7. The only diff is that we
        # drop the NOT NULL constraint on quarantined.
        parts = [col.name, col.type]
        nullable = col.nullable
        if col.name == "quarantined":
            nullable = True  # the pre-migration shape
        if not nullable:
            parts.append("NOT NULL")
        if col.default is not None:
            parts.append(f"DEFAULT '{col.default}'")
        pre_columns.append(" ".join(parts))
    pre_columns.append("PRIMARY KEY (trade_id)")
    pre_columns.append(
        "FOREIGN KEY (recommendation_id) "
        "REFERENCES recommendations(recommendation_id)"
    )
    body = ",\n    ".join(pre_columns)
    conn.execute(f"CREATE TABLE shadow_trades (\n    {body}\n)")
    # Recreate indexes from the registry.
    for idx in TABLES["shadow_trades"].indexes:
        unique = "UNIQUE " if idx.unique else ""
        cols = ", ".join(idx.columns)
        conn.execute(
            f"CREATE {unique}INDEX {idx.name} ON shadow_trades({cols})"
        )
    conn.commit()
    conn.close()


def _seed_row(conn, trade_id: str, quarantined, ticker: str = "AAPL") -> None:
    """Insert a minimal valid shadow_trades row.

    `quarantined` may be None (to test backfill), 0, or 1.
    """
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, direction, status, created_at, updated_at, "
        "quarantined, instrumentation_version) "
        "VALUES (?, ?, 'long', 'open', '2026-04-26T10:00:00', "
        "'2026-04-26T10:00:00', ?, 3)",
        (trade_id, ticker, quarantined),
    )
    conn.commit()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "shadow_trades_pre_migration.db")
    _create_pre_migration_schema(db_path)
    return db_path


@pytest.fixture
def conn(db):
    c = connect_db(db)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Sanity: pre-migration schema actually has a nullable quarantined column.
# ---------------------------------------------------------------------------

def test_fixture_starts_nullable(conn):
    assert is_quarantined_not_null(conn) is False


# ---------------------------------------------------------------------------
# (1) Backfill: NULL → 0
# ---------------------------------------------------------------------------

def test_backfill_finds_null_rows(conn):
    _seed_row(conn, "t-null-1", None)
    _seed_row(conn, "t-null-2", None)
    _seed_row(conn, "t-zero", 0)
    _seed_row(conn, "t-one", 1)

    null_ids = find_null_quarantined_trade_ids(conn)
    assert sorted(null_ids) == ["t-null-1", "t-null-2"]


def test_backfill_sets_zero(conn):
    _seed_row(conn, "t-null-1", None)
    _seed_row(conn, "t-null-2", None)

    null_ids = find_null_quarantined_trade_ids(conn)
    n = backfill_null_quarantined(conn, null_ids)
    assert n == 2
    assert find_null_quarantined_trade_ids(conn) == []

    rows = conn.execute(
        "SELECT trade_id, quarantined FROM shadow_trades ORDER BY trade_id"
    ).fetchall()
    assert all(r["quarantined"] == 0 for r in rows)


def test_backfill_does_not_touch_existing_zero_or_one(conn):
    _seed_row(conn, "t-zero", 0)
    _seed_row(conn, "t-one", 1)
    _seed_row(conn, "t-null", None)

    null_ids = find_null_quarantined_trade_ids(conn)
    backfill_null_quarantined(conn, null_ids)

    rows = {
        r["trade_id"]: r["quarantined"]
        for r in conn.execute(
            "SELECT trade_id, quarantined FROM shadow_trades"
        ).fetchall()
    }
    assert rows == {"t-zero": 0, "t-one": 1, "t-null": 0}


# ---------------------------------------------------------------------------
# (2) Rebuild: column becomes NOT NULL
# ---------------------------------------------------------------------------

def test_rebuild_enforces_not_null(conn):
    _seed_row(conn, "t-zero", 0)
    rebuild_shadow_trades_with_not_null(conn)
    assert is_quarantined_not_null(conn) is True


def test_rebuild_preserves_data(conn):
    _seed_row(conn, "t-zero", 0)
    _seed_row(conn, "t-one", 1, ticker="MSFT")
    rebuild_shadow_trades_with_not_null(conn)

    rows = conn.execute(
        "SELECT trade_id, ticker, quarantined "
        "FROM shadow_trades ORDER BY trade_id"
    ).fetchall()
    by_id = {r["trade_id"]: dict(r) for r in rows}
    assert by_id["t-zero"]["quarantined"] == 0
    assert by_id["t-zero"]["ticker"] == "AAPL"
    assert by_id["t-one"]["quarantined"] == 1
    assert by_id["t-one"]["ticker"] == "MSFT"


def test_rebuild_preserves_indexes(conn):
    _seed_row(conn, "t-zero", 0)
    rebuild_shadow_trades_with_not_null(conn)

    idx_names = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='shadow_trades'"
        ).fetchall()
    }
    for idx in TABLES["shadow_trades"].indexes:
        assert idx.name in idx_names, (
            f"Index {idx.name} did not survive table rebuild"
        )


def test_rebuild_preserves_foreign_key(conn):
    _seed_row(conn, "t-zero", 0)
    rebuild_shadow_trades_with_not_null(conn)

    fks = conn.execute(
        "PRAGMA foreign_key_list(shadow_trades)"
    ).fetchall()
    fk_targets = [(r["from"], r["table"], r["to"]) for r in fks]
    assert ("recommendation_id", "recommendations", "recommendation_id") in fk_targets


def test_rebuild_inserts_reject_null(conn):
    """Post-migration, INSERTing NULL into quarantined must fail.

    The whole point of NOT NULL is to enforce this at the storage layer —
    a regression that re-allowed NULL would defeat the migration.
    """
    import sqlite3

    rebuild_shadow_trades_with_not_null(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, direction, status, created_at, updated_at, "
            "quarantined, instrumentation_version) "
            "VALUES (?, 'AAPL', 'long', 'open', '2026-04-26T10:00:00', "
            "'2026-04-26T10:00:00', NULL, 3)",
            ("t-bad-null",),
        )


# ---------------------------------------------------------------------------
# (3) End-to-end run_migration: backfill + rebuild
# ---------------------------------------------------------------------------

def test_run_migration_full_path(conn):
    _seed_row(conn, "t-null-1", None)
    _seed_row(conn, "t-null-2", None)
    _seed_row(conn, "t-zero", 0)

    result = run_migration(conn, apply=True)

    assert result["null_rows"] == 2
    assert result["already_not_null"] is False
    assert result["backfilled"] == 2
    assert result["rebuilt"] is True

    assert is_quarantined_not_null(conn) is True
    assert find_null_quarantined_trade_ids(conn) == []


def test_run_migration_idempotent(conn):
    """A second run after success must be a no-op."""
    _seed_row(conn, "t-null", None)
    run_migration(conn, apply=True)

    result_2 = run_migration(conn, apply=True)
    assert result_2["null_rows"] == 0
    assert result_2["already_not_null"] is True
    assert result_2["backfilled"] == 0
    assert result_2["rebuilt"] is False


def test_run_migration_dry_run(conn):
    _seed_row(conn, "t-null", None)
    result = run_migration(conn, apply=False)

    assert result["null_rows"] == 1
    assert result["already_not_null"] is False
    assert result["backfilled"] == 0  # dry-run must not write
    assert result["rebuilt"] is False

    # Confirm: no DDL or data change occurred.
    assert is_quarantined_not_null(conn) is False
    null_ids = find_null_quarantined_trade_ids(conn)
    assert null_ids == ["t-null"]


# ---------------------------------------------------------------------------
# (4-9) Edge cases.
# ---------------------------------------------------------------------------

def test_run_migration_empty_table(conn):
    """Zero rows + nullable column → backfill skipped, rebuild still runs."""
    result = run_migration(conn, apply=True)
    assert result["null_rows"] == 0
    assert result["backfilled"] == 0
    assert result["rebuilt"] is True
    assert is_quarantined_not_null(conn) is True


def test_run_migration_handles_bulk(conn):
    """>BATCH_SIZE NULL rows are all backfilled; rebuild succeeds."""
    n = BATCH_SIZE * 2 + 3
    for i in range(n):
        _seed_row(conn, f"t{i}", None)

    result = run_migration(conn, apply=True)
    assert result["null_rows"] == n
    assert result["backfilled"] == n
    assert result["rebuilt"] is True
    assert is_quarantined_not_null(conn) is True

    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM shadow_trades WHERE quarantined = 0"
    ).fetchone()
    assert rows["c"] == n


def test_batch_size_constant_at_least_50():
    """Per CLAUDE.md backfill memory pattern: >=50 rows per commit."""
    assert BATCH_SIZE >= 50


def test_already_migrated_db_short_circuits(conn):
    """If a DB already has NOT NULL + zero NULLs, run_migration is a no-op.

    Simulates the case where someone applied the migration once; subsequent
    re-runs (e.g. as part of a startup hook) must not attempt a rebuild.
    """
    rebuild_shadow_trades_with_not_null(conn)  # pre-condition: already migrated

    result = run_migration(conn, apply=True)
    assert result["already_not_null"] is True
    assert result["null_rows"] == 0
    assert result["backfilled"] == 0
    assert result["rebuilt"] is False


def test_rebuild_handles_mixed_quarantined_values(conn):
    """All three values (0, 1, NULL) must round-trip correctly via the rebuild."""
    _seed_row(conn, "t-zero", 0)
    _seed_row(conn, "t-one", 1)
    _seed_row(conn, "t-null", None)

    # First backfill, THEN rebuild — the rebuild itself rejects NULL inserts.
    null_ids = find_null_quarantined_trade_ids(conn)
    backfill_null_quarantined(conn, null_ids)
    rebuild_shadow_trades_with_not_null(conn)

    rows = {
        r["trade_id"]: r["quarantined"]
        for r in conn.execute(
            "SELECT trade_id, quarantined FROM shadow_trades"
        ).fetchall()
    }
    assert rows == {"t-zero": 0, "t-one": 1, "t-null": 0}

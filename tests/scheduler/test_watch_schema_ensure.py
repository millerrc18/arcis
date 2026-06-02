"""Hotfix 3 — WatchLoop._ensure_all_tables must self-heal the Postgres schema.

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: TEST_DATABASE_URL (5434 test PG only — NEVER prod 5433)
Tests: self

Verify-by-mutation regression test for the post-cutover PG-schema-drift class
(memory reference_pg_schema_no_autosync_post_cutover). Pre-fix, the watch
loop's startup schema-ensure called ONLY the SQLite path, so a dropped table
on the live PG (observed 2026-06-02: notifications_digest_queue +
notifications_sent absent → ~66s ERROR loop) was never re-created by the
running system. The fix makes _ensure_all_tables Postgres-aware: when a
postgres-scheme DATABASE_URL is configured it idempotently ensures the
registry schema on PG too.

The test DROPs a registry table on the 5434 test PG, runs the ensure with
DATABASE_URL pointed at 5434, and asserts the table is back. Reverting the
fix leaves the table dropped → the assertion fails (proving the test bites).

SAFETY: reads ONLY TEST_DATABASE_URL, asserts the DSN targets :5434, and
skips cleanly when TEST_DATABASE_URL is unset — never touches prod 5433.
"""
import os

import pytest

_DROPPED_TABLE = "notifications_digest_queue"


def _pg_table_exists(conn, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table_name,),
    )
    return cur.fetchone() is not None


def test_ensure_all_tables_selfheals_postgres_schema(tmp_path, monkeypatch):
    """A registry table dropped on the live PG is re-created by the startup ensure."""
    import psycopg2

    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; postgres self-heal test cannot run")
    # Prod-safety hard gate: refuse to run against anything but the 5434 test PG.
    assert ":5434" in test_database_url, (
        "refusing to run schema-drop test against a non-5434 DSN "
        "(would risk the production PG on :5433)"
    )

    from src.schema.postgres import create_all_tables as pg_create_all_tables
    from src.scheduler.watch import WatchLoop

    # Bootstrap the full registry schema on 5434 so the drop has something to drop.
    pg_create_all_tables(test_database_url, connect_timeout=5, lock_timeout_ms=10000)

    # Mutate: drop one registry table.
    conn = psycopg2.connect(test_database_url, connect_timeout=5)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_DROPPED_TABLE} CASCADE")
        assert not _pg_table_exists(conn, _DROPPED_TABLE), "drop did not take"

        # Route the ensure at the 5434 PG; keep the SQLite ensure on a temp file
        # (watch.DB_PATH is bound to the real prod sqlite at import) so the test
        # stays fully hermetic.
        monkeypatch.setenv("DATABASE_URL", test_database_url)
        monkeypatch.setattr(
            "src.scheduler.watch.DB_PATH", str(tmp_path / "hf3_selfheal.sqlite3")
        )
        # Neutralize side-channels the ensure touches on the happy path.
        monkeypatch.setattr(
            "src.data_collection.docs_collector.populate_research_docs",
            lambda *a, **k: {"inserted": 0},
        )
        monkeypatch.setattr(
            "src.notifications.telegram.send_telegram", lambda *a, **k: None
        )

        WatchLoop._ensure_all_tables()

        assert _pg_table_exists(conn, _DROPPED_TABLE), (
            f"{_DROPPED_TABLE} was not re-created on the PG by _ensure_all_tables "
            "— the Postgres-aware self-heal did not run"
        )
    finally:
        conn.close()

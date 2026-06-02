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
running system. The fix makes _ensure_all_tables Postgres-aware: when the
cutover gate is on AND a postgres-scheme DATABASE_URL is configured (mirroring
connect_db, db.py:621-623) it idempotently ensures the registry schema on PG too.

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
        # Match connect_db's routing: the PG self-heal runs only when BOTH the
        # cutover gate is on AND DATABASE_URL is postgres (db.py:621-623).
        monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
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


def test_ensure_all_tables_skips_non_owned_pg_tables_without_halting(tmp_path, monkeypatch, caplog):
    """#129 forward-fix: a 'must be owner' (psycopg2 InsufficientPrivilege) from the
    PG self-heal is EXPECTED under the #92 split-ownership schema and must be SKIPPED,
    never halt the watch loop.

    Verify-by-mutation: v0.36.81 let InsufficientPrivilege fall through to the fatal
    '[WATCH] SCHEMA CREATION FAILED ... cannot continue' → sys.exit(1) → crash loop
    (2026-06-02 pre-market incident). Removing the new try/except in _ensure_all_tables
    makes this test fail with SystemExit.

    Hermetic: the PG create_all_tables is mocked to raise BEFORE any connection, so no
    database is touched (the postgres-scheme DSN targets :5434, never prod :5433).
    """
    import logging
    import psycopg2
    from src.scheduler.watch import WatchLoop

    # Cutover gate ON + postgres DATABASE_URL → the PG self-heal branch executes.
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://halcyon_app:x@127.0.0.1:5434/halcyon")

    def _raise_must_be_owner(*a, **k):
        raise psycopg2.errors.InsufficientPrivilege("must be owner of table recommendations")

    # Patch the SOURCE module attr — _ensure_all_tables does a call-time
    # `from src.schema.postgres import create_all_tables`, so it binds the patch.
    monkeypatch.setattr("src.schema.postgres.create_all_tables", _raise_must_be_owner)
    # Keep the downstream SQLite ensure hermetic on a temp file (watch.DB_PATH is
    # bound to the real prod sqlite at import).
    monkeypatch.setattr("src.scheduler.watch.DB_PATH", str(tmp_path / "ownskip.sqlite3"))
    monkeypatch.setattr(
        "src.data_collection.docs_collector.populate_research_docs",
        lambda *a, **k: {"inserted": 0},
    )
    monkeypatch.setattr("src.notifications.telegram.send_telegram", lambda *a, **k: None)

    with caplog.at_level(logging.INFO):
        # Must NOT raise SystemExit. Pre-fix: InsufficientPrivilege → fatal → sys.exit(1).
        WatchLoop._ensure_all_tables()

    # The ownership error was skipped (not fatal) and logged as expected.
    assert any(
        "owned by another role skipped" in r.getMessage() for r in caplog.records
    ), "expected the 'skipped (expected)' skip log; ownership error was not handled as benign"

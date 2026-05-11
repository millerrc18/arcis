"""Tests for src/api/routes/system.update_settings engine-aware UPSERT migration.

Sprint 5 §J5/§J6 Phase 1 T1.11: replaces the INSERT OR REPLACE site at
src/api/routes/system.py:566 with engine_aware_upsert(conn, 'config_overrides',
row_dict, action='replace'). The parametrized test below exercises both SQLite
and PostgreSQL engines via the shared `parametrized_conn` fixture
(tests/conftest.py T0.9). The PG variant is SKIPPED when TEST_DATABASE_URL is
unset.

The config_overrides table uses primary_key='setting_key' (the dedup target),
classified as `in_place_update` in `_REPLACE_SEMANTICS` (T0.12 audit §5.3).

Module: tests.api.routes.test_system
Purpose: Verify that update_settings dedups via engine_aware_upsert and that
         the migration is locked in source (no literal INSERT OR REPLACE).
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3
from contextlib import contextmanager

import pytest


def _count_rows(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    if hasattr(row, "keys") and "c" in row.keys():
        return row["c"]
    return row[0]


def _select_setting(conn, key: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM config_overrides WHERE setting_key=?", (key,)
    )
    return cur.fetchone()


def test_update_settings_uses_engine_aware_upsert_on_both_engines(
    parametrized_conn, monkeypatch
):
    """T1.11: update_settings must dedup via engine_aware_upsert on both engines.

    Calls update_settings twice with the same key but different values and
    verifies the second call UPDATES the row rather than duplicating it. This
    exercises:
        - SQLite path: INSERT OR REPLACE (in_place_update semantic)
        - PG path: INSERT ... ON CONFLICT (setting_key) DO UPDATE SET ...
    """
    from src.api.routes import system as system_routes

    conn = parametrized_conn

    # config_overrides table is bootstrapped by parametrized_conn for SQLite
    # via init_test_db. On PG, pg_wrapper only creates sync_to_postgres tables;
    # config_overrides has sync_to_postgres=False, so we explicitly create it.
    if not isinstance(conn, sqlite3.Connection):
        from src.schema.postgres import generate_create_sql
        from src.schema.registry import TABLES
        cur = conn.cursor()
        cur.execute(generate_create_sql(TABLES["config_overrides"]))
        conn.commit()
        # Truncate to guarantee a clean slate (pg_wrapper drops tables that
        # IT created on teardown; tables created lazily inside a test must be
        # cleaned by the test itself).
        cur.execute("TRUNCATE TABLE config_overrides")
        conn.commit()

    # update_settings uses:
    #   with closing(connect_db(DB_PATH)) as conn:
    #       with conn:  # transaction commit on context exit
    #           engine_aware_upsert(conn, ...)
    #
    # Both `closing()` and `with conn:` would close the connection on exit
    # (PostgresConnectionWrapper.__exit__ closes; SQLite's __exit__ commits
    # without closing — but `closing()` always calls .close()).
    #
    # We replace BOTH:
    #   1. connect_db: returns the fixture conn directly. engine_aware_upsert
    #      dispatches on isinstance(conn, PostgresConnectionWrapper), so the
    #      raw fixture conn (sqlite3.Connection or PostgresConnectionWrapper)
    #      MUST be passed through unwrapped for the PG dispatch to fire.
    #   2. closing: replaced with a no-op contextmanager.
    # Then we patch the conn's __exit__ to commit-only (no close), so the
    # `with conn:` block still flushes the transaction without ending the
    # fixture's lifecycle.
    @contextmanager
    def _no_close(c):
        yield c

    monkeypatch.setattr(
        "src.api.routes.system.connect_db",
        lambda _path: conn,
    )
    monkeypatch.setattr("src.api.routes.system.closing", _no_close)

    # Patch the conn's __exit__ on the wrapper class so `with conn:` doesn't
    # close. For sqlite3.Connection, __exit__ commits on success and does NOT
    # close — so no patch needed. For PostgresConnectionWrapper, we override
    # __exit__ to commit-only.
    if not isinstance(conn, sqlite3.Connection):
        from src.utils.db import PostgresConnectionWrapper

        def _commit_no_close(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
            return False

        monkeypatch.setattr(
            PostgresConnectionWrapper, "__exit__", _commit_no_close
        )

    # First call — inserts the row
    result1 = system_routes.update_settings(
        {"key": "max_position_size", "value": 1000}
    )
    assert result1 == {"status": "saved", "key": "max_position_size"}, (
        f"first update_settings should report saved, got {result1}"
    )
    assert _count_rows(conn, "config_overrides") == 1, (
        "first update_settings should insert one row"
    )
    fetched = _select_setting(conn, "max_position_size")
    assert fetched is not None
    # setting_value is JSON-encoded by the route
    assert fetched["setting_value"] == "1000"

    # Second call with SAME key but different value — must UPDATE non-target
    # columns (setting_value, updated_at) in place, not duplicate the row.
    result2 = system_routes.update_settings(
        {"key": "max_position_size", "value": 2500}
    )
    assert result2 == {"status": "saved", "key": "max_position_size"}, (
        f"second update_settings should report saved, got {result2}"
    )
    assert _count_rows(conn, "config_overrides") == 1, (
        "second update_settings with same setting_key should REPLACE/UPDATE, "
        "not duplicate — engine_aware_upsert classifies config_overrides as "
        "in_place_update (T0.12 audit §5.3)"
    )
    updated = _select_setting(conn, "max_position_size")
    assert updated is not None
    assert updated["setting_value"] == "2500", (
        "setting_value should be updated to the new value"
    )
    # updated_at should be re-stamped (the route generates a fresh ISO
    # timestamp on every call).
    assert updated["updated_at"] is not None
    assert updated["updated_at"] != "", "updated_at must be re-stamped"


def test_update_settings_no_literal_insert_or_replace_in_source():
    """T1.11 lock-in: api/routes/system.py must not contain `INSERT OR REPLACE`.

    Pins the migration to engine_aware_upsert so a future refactor cannot
    silently regress to a literal SQLite-only statement. The wrapper is the
    only sanctioned upsert path post-T1.11 (Modified-A migration).
    """
    from pathlib import Path

    system_path = (
        Path(__file__).resolve().parents[3]
        / "src" / "api" / "routes" / "system.py"
    )
    source = system_path.read_text(encoding="utf-8")
    assert "INSERT OR REPLACE" not in source, (
        "src/api/routes/system.py must not contain literal `INSERT OR REPLACE` "
        "after T1.11 migration; use engine_aware_upsert(action='replace') "
        "via src.utils.db instead."
    )
    assert "INSERT OR IGNORE" not in source, (
        "src/api/routes/system.py must not contain literal `INSERT OR IGNORE` "
        "after T1.11 migration; use engine_aware_upsert(action='ignore') "
        "via src.utils.db instead."
    )

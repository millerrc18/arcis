"""Sprint 5 §J5/§J6 Phase 2 T2.9 — cross-engine days_held computation.

Called by: none (test suite)
Calls: src.council.agent_data.gather_tactical_data
Owns tables: none
Config keys: TEST_DATABASE_URL (optional — postgres variant skips when unset)
Tests: self

Verifies that the SQLite-only `julianday('now') - julianday(...)` arithmetic
at src/council/agent_data.py:91 has been replaced with a cross-engine path
(Python-side date arithmetic) by exercising `gather_tactical_data` against
BOTH SQLite and a live Postgres connection. The PG variant skips cleanly
when `TEST_DATABASE_URL` is unset so total test count stays stable across
environments.
"""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
import pytest

from src.council.agent_data import gather_tactical_data
from src.schema.postgres import generate_create_sql as pg_generate_create_sql
from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql as sqlite_generate_create_sql

ET = ZoneInfo("America/New_York")


def _seed_position(conn, *, days_ago: int, ticker: str = "AAPL", placeholder: str = "?"):
    """Insert a recommendation + open shadow_trade entered `days_ago` days ago."""
    now_iso = datetime.now(ET).isoformat()
    entry_time = (datetime.now(ET) - timedelta(days=days_ago)).isoformat()
    rec_id = str(uuid.uuid4())
    trade_id = str(uuid.uuid4())
    conn.execute(
        f"INSERT INTO recommendations (recommendation_id, created_at, ticker, sector_context) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
        (rec_id, now_iso, ticker, "Technology"),
    )
    conn.execute(
        f"INSERT INTO shadow_trades "
        f"(trade_id, recommendation_id, ticker, status, planned_allocation, "
        f"actual_entry_time, pnl_pct, pnl_dollars, created_at, updated_at) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, 'open', 10000, "
        f"{placeholder}, 1.5, 150.0, {placeholder}, {placeholder})",
        (trade_id, rec_id, ticker, entry_time, now_iso, now_iso),
    )


@pytest.fixture
def sqlite_db(tmp_path):
    """SQLite DB bootstrapped with all registry tables; yields db_path."""
    db_path = str(tmp_path / "agent_data_julianday.sqlite3")
    conn = sqlite3.connect(db_path)
    try:
        for tdef in TABLES.values():
            conn.executescript(sqlite_generate_create_sql(tdef))
        _seed_position(conn, days_ago=5)
        conn.commit()
    finally:
        conn.close()
    yield db_path


@pytest.fixture
def pg_db(tmp_path):
    """Postgres DB bootstrapped with required tables; yields db_path.

    Skips when TEST_DATABASE_URL is unset. Loads .env from the parent repo
    so the operator's PG creds are picked up automatically. Routes
    `connect_db()` to Postgres by setting `DATABASE_URL` for the test
    duration (restored on teardown).

    Yields a sqlite-style db_path sentinel; the caller passes `None`-equivalent
    behaviour by leaning on `DATABASE_URL` resolving to PG inside
    `connect_db()` when the agent_data callers omit db_path. Since
    `gather_tactical_data` accepts an explicit db_path that ALWAYS resolves
    to SQLite per `src.utils.db.connect_db` precedence, this fixture cannot
    use the same path-based interface — instead it monkey-patches the
    `connect_db` import in `agent_data` so calls inside the SUT resolve to
    the live PG connection wrapper.
    """
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        # Fall back to constructing from DOCKER_PG_PASSWORD per task brief:
        # postgresql://halcyon:$DOCKER_PG_PASSWORD@127.0.0.1:5433/halcyon
        try:
            from dotenv import dotenv_values
            env = dotenv_values("C:/arcis/halcyon-lab/.env")
            pg_password = env.get("DOCKER_PG_PASSWORD") or os.environ.get(
                "DOCKER_PG_PASSWORD"
            )
            if pg_password:
                test_database_url = (
                    f"postgresql://halcyon:{pg_password}@127.0.0.1:5433/halcyon"
                )
        except ImportError:
            pass
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; postgres variant cannot run")

    raw_conn = psycopg2.connect(
        test_database_url, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw_conn.autocommit = True
    created_tables: list[str] = []
    try:
        cur = raw_conn.cursor()
        # Tables `gather_tactical_data` queries — without all of them, the
        # SUT's earlier queries (vix, traffic_light, scan_metrics) hit an
        # UndefinedTable error which on PG aborts the implicit transaction
        # and causes the subsequent positions query (the one under test)
        # to fail with "current transaction is aborted".
        for table_name in (
            "vix_term_structure",
            "traffic_light_state",
            "scan_metrics",
            "recommendations",
            "shadow_trades",
        ):
            tdef = TABLES[table_name]
            cur.execute(pg_generate_create_sql(tdef))
            created_tables.append(tdef.name)
        # Clear any leftover data from prior runs (in dependency order)
        for table_name in ("shadow_trades", "recommendations"):
            cur.execute(f"DELETE FROM {table_name}")
        cur.close()
    except Exception:
        raw_conn.close()
        raise

    # Seed via the wrapper so the placeholder rewrite applies.
    from src.utils.db import PostgresConnectionWrapper

    wrapper = PostgresConnectionWrapper(raw_conn)
    raw_conn.autocommit = False
    try:
        _seed_position(wrapper, days_ago=5)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raw_conn.close()
        raise

    yield test_database_url, raw_conn, created_tables

    # Teardown: drop the tables we created.
    try:
        raw_conn.rollback()
    except Exception:
        pass
    try:
        raw_conn.autocommit = True
        cleanup_cur = raw_conn.cursor()
        for name in reversed(created_tables):
            try:
                cleanup_cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
            except Exception:
                pass
        cleanup_cur.close()
    finally:
        raw_conn.close()


def test_gather_tactical_data_days_held_sqlite(sqlite_db):
    """Days-held arithmetic works on SQLite (no julianday() SQL call in source)."""
    # Confirm no julianday( SQL function call is in the module source. Mentions
    # in docstrings/comments (referring to the historical pattern) are fine —
    # only the SQL function call must be removed (T2.9).
    import re
    import src.council.agent_data as agent_data_mod
    import inspect

    source = inspect.getsource(agent_data_mod)
    # SQL function-call form: `julianday(` adjacent to an opening paren.
    sql_matches = re.findall(r"julianday\s*\(", source)
    # Allow at most matches inside docstrings/comments; the matches we want
    # to forbid are the SQL ones. Tightest check: ensure no match occurs on a
    # source line that also contains common SQL keywords (SELECT/CAST/AS).
    forbidden = [
        line for line in source.splitlines()
        if re.search(r"julianday\s*\(", line)
        and re.search(r"\b(SELECT|CAST|AS\s+\w+|FROM)\b", line)
    ]
    assert not forbidden, (
        f"src/council/agent_data.py still contains julianday() in a SQL "
        f"context — must be replaced with cross-engine Python-side date "
        f"arithmetic (T2.9). Offending lines: {forbidden}"
    )

    result = gather_tactical_data(sqlite_db)
    assert isinstance(result, str)
    # The seeded position was opened 5 days ago — confirm the days printout
    # reflects that (allow ±1 for boundary crossing).
    assert "AAPL" in result
    assert ("(5d)" in result or "(4d)" in result or "(6d)" in result), (
        f"Expected ~5-day days_held in output; got: {result}"
    )


def test_gather_tactical_data_days_held_postgres(pg_db, monkeypatch):
    """Days-held arithmetic works on Postgres (no julianday() needed)."""
    test_database_url, _, _ = pg_db

    # Route the SUT's connect_db() at the PG database by setting DATABASE_URL
    # and calling gather_tactical_data WITHOUT db_path (so connect_db() picks
    # the PG branch in src/utils/db.py:441-446 precedence rules).
    monkeypatch.setenv("DATABASE_URL", test_database_url)

    # gather_tactical_data has signature `gather_tactical_data(db_path: str = DB_PATH)`,
    # which means we must override DB_PATH-style resolution. Because passing an
    # explicit `db_path` ALWAYS forces SQLite per connect_db() precedence, we
    # patch the module-level `connect_db` import to ignore the db_path argument
    # for this test only.
    from src.utils.db import connect_db as real_connect_db

    def pg_connect_db(db_path=None):
        # Ignore db_path; always return the PG wrapper via env-route.
        return real_connect_db()

    monkeypatch.setattr("src.council.agent_data.connect_db", pg_connect_db)

    result = gather_tactical_data(db_path="ignored-by-monkeypatch")
    assert isinstance(result, str)
    assert "AAPL" in result, f"Expected AAPL in PG output; got: {result}"
    assert ("(5d)" in result or "(4d)" in result or "(6d)" in result), (
        f"Expected ~5-day days_held in PG output; got: {result}"
    )

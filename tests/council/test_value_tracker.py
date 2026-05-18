"""Tests for src/council/value_tracker.py.

Module: tests.council.test_value_tracker
Purpose: Verify that `log_parameter_change()` correctly routes its
         `council_parameter_state` upsert through `engine_aware_upsert(...
         action='replace')` on both SQLite and Postgres engines.
Called by: pytest
Owns tables: none
Config keys: none

Sprint 5 §J5/§J6 Phase 1 T1.13: coverage for the engine_aware_upsert
migration of `log_parameter_change()` against `council_parameter_state`.

Test strategy mirrors T1.10 (`tests/evaluation/test_build_score.py`):
  * Dual-engine parametrized (`sqlite` + `postgres`) — PG variant skips
    cleanly when `TEST_DATABASE_URL` / `DATABASE_URL` is not a postgres://
    URL.
  * First call inserts the council_parameter_state row.
  * Second call with the same `parameter_name` (the PK) UPDATES the
    non-target columns (`current_value`, `default_value`,
    `last_session_id`, `last_updated`).
  * End-to-end mock test confirms `log_parameter_change()` routes its
    INSERT through `engine_aware_upsert` rather than a raw SQL string.
"""

import os
import sqlite3
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 1 T1.13 — log_parameter_change engine_aware_upsert dual-engine
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


def _build_sqlite_ddl(table_name):
    """Return the SQLite CREATE TABLE SQL for `table_name` from the registry."""
    from src.schema.registry import TABLES

    td = TABLES[table_name]
    cols = []
    for c in td.columns:
        nn = "" if c.nullable else " NOT NULL"
        cols.append(f"{c.name} {c.type}{nn}")
    pk = td.primary_key if isinstance(td.primary_key, list) else [td.primary_key]
    cols.append(f"PRIMARY KEY ({', '.join(pk)})")
    body = ",\n    ".join(cols)
    return f"CREATE TABLE {table_name} (\n    {body}\n);"


def _build_pg_ddl(table_name):
    """Return the Postgres CREATE TABLE SQL for `table_name` from the registry."""
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn():
    """Live psycopg2 wrapper. Skips if `TEST_DATABASE_URL` not set."""
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    wrapper = PostgresConnectionWrapper(raw)
    yield wrapper
    try:
        wrapper.rollback()
    except Exception:
        pass
    wrapper.close()


def _setup_council_parameter_state(conn):
    """Drop+recreate `council_parameter_state` on whichever engine `conn` is for."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS council_parameter_state CASCADE")
        cur.execute(_build_pg_ddl("council_parameter_state"))
        conn.commit()
    else:
        conn.execute("DROP TABLE IF EXISTS council_parameter_state")
        conn.execute(_build_sqlite_ddl("council_parameter_state"))
        conn.commit()


def _get_conn(request):
    """Return the conn fixture matching the parametrized engine."""
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn")
    elif engine == "postgres":
        return request.getfixturevalue("pg_conn")
    raise ValueError(f"unknown engine: {engine}")


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine(request):
    return _get_conn(request)


def _count_rows(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    return row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]


def _select_one(conn, table, where_col, where_val):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} WHERE {where_col}=?", (where_val,))
    return cur.fetchone()


class TestCouncilParameterStateEngineAwareUpsert:
    """T1.13: council_parameter_state.engine_aware_upsert dual-engine coverage."""

    def test_engine_aware_upsert_first_insert_lands_row(self, conn_engine):
        """T1.13 #1: first insert against council_parameter_state lands the row."""
        from src.utils.db import engine_aware_upsert

        conn = conn_engine
        _setup_council_parameter_state(conn)

        row = {
            "parameter_name": "position_sizing_multiplier",
            "current_value": 1.25,
            "default_value": 1.0,
            "last_session_id": "session-T1.13-001",
            "last_updated": "2026-05-11T10:00:00",
        }
        engine_aware_upsert(conn, "council_parameter_state", row, action="replace")
        conn.commit()

        assert _count_rows(conn, "council_parameter_state") == 1
        fetched = _select_one(
            conn, "council_parameter_state", "parameter_name",
            "position_sizing_multiplier",
        )
        assert fetched["current_value"] == 1.25
        assert fetched["default_value"] == 1.0
        assert fetched["last_session_id"] == "session-T1.13-001"
        assert fetched["last_updated"] == "2026-05-11T10:00:00"

    def test_engine_aware_upsert_replace_updates_existing_row(self, conn_engine):
        """T1.13 #2: re-upserting same parameter_name UPDATES non-target columns."""
        from src.utils.db import engine_aware_upsert

        conn = conn_engine
        _setup_council_parameter_state(conn)

        row1 = {
            "parameter_name": "position_sizing_multiplier",
            "current_value": 1.25,
            "default_value": 1.0,
            "last_session_id": "session-T1.13-100",
            "last_updated": "2026-05-11T10:00:00",
        }
        engine_aware_upsert(conn, "council_parameter_state", row1, action="replace")

        # Second insert with the same PK -> conflict -> UPDATE non-target cols.
        row2 = {
            "parameter_name": "position_sizing_multiplier",  # same PK
            "current_value": 0.75,  # updated
            "default_value": 1.0,
            "last_session_id": "session-T1.13-200",  # updated
            "last_updated": "2026-05-11T11:30:00",  # updated
        }
        engine_aware_upsert(conn, "council_parameter_state", row2, action="replace")
        conn.commit()

        assert _count_rows(conn, "council_parameter_state") == 1
        fetched = _select_one(
            conn, "council_parameter_state", "parameter_name",
            "position_sizing_multiplier",
        )
        assert fetched["current_value"] == 0.75
        assert fetched["last_session_id"] == "session-T1.13-200"
        assert fetched["last_updated"] == "2026-05-11T11:30:00"


class TestLogParameterChangeUsesEngineAwareUpsert:
    """T1.13: end-to-end test that log_parameter_change() routes through helper."""

    def test_log_parameter_change_calls_engine_aware_upsert(self, tmp_path):
        """log_parameter_change() must route the council_parameter_state INSERT
        through `engine_aware_upsert(conn, 'council_parameter_state', row,
        action='replace')`.
        """
        from tests.conftest import init_test_db

        db_path = str(tmp_path / "value_tracker_test.sqlite3")
        init_test_db(db_path)

        with mock.patch("src.council.value_tracker.engine_aware_upsert") as mocked:
            from src.council.value_tracker import log_parameter_change

            log_parameter_change(
                session_id="session-T1.13-e2e",
                parameter_name="position_sizing_multiplier",
                default_value=1.0,
                council_value=1.5,
                applied_value=1.25,
                rate_limited=False,
                agent_name="quant_researcher",
                db_path=db_path,
            )

            assert mocked.call_count == 1
            call_args = mocked.call_args
            # Positional args: conn, table_name, row_dict; kw or pos: action
            assert call_args.args[1] == "council_parameter_state"
            row_dict = call_args.args[2]
            assert row_dict["parameter_name"] == "position_sizing_multiplier"
            assert row_dict["current_value"] == 1.25
            assert row_dict["default_value"] == 1.0
            assert row_dict["last_session_id"] == "session-T1.13-e2e"
            assert "last_updated" in row_dict
            # action='replace' — may be positional or keyword
            action = call_args.kwargs.get("action")
            if action is None and len(call_args.args) >= 4:
                action = call_args.args[3]
            assert action == "replace"

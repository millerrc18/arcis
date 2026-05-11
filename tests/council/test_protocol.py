"""Tests for src/council/protocol.py.

Sprint 5 §J5/§J6 Phase 1 T1.8 — coverage for `_store_debug_log`, which is the
council `INSERT OR IGNORE` call site that T1.8 migrates to
`engine_aware_upsert(conn, 'council_debug_log', row_dict, action='ignore')`.

The dual-engine parametrized tests exercise both the SQLite and Postgres
dispatch paths (the latter skips cleanly when `TEST_DATABASE_URL` is unset).
The first call inserts a row; a second call with the same `debug_id` is a
no-op (ignored). Both engines must show exactly one row and the original
values preserved.
"""

import os
import sqlite3
import sys
import uuid

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
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
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set or not postgres://")

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


def _setup_table(conn, table_name):
    """Drop+recreate `table_name` on whichever engine `conn` is for."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cur.execute(_build_pg_ddl(table_name))
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(_build_sqlite_ddl(table_name))
        conn.commit()


def _get_conn(request):
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


def test_store_debug_log_first_call_inserts(conn_engine, monkeypatch):
    """T1.8 #1: `_store_debug_log` inserts a brand-new council_debug_log row."""
    from src.council import protocol as protocol_module

    conn = conn_engine
    _setup_table(conn, "council_debug_log")

    # Patch `connect_db` inside the protocol module so `_store_debug_log` uses
    # the parametrized test connection. The function opens with
    # `with connect_db(db_path) as conn:` — wrap our test conn so `with ...`
    # exits cleanly without closing the engine-specific real connection.
    class _ConnGuard:
        def __init__(self, c):
            self._c = c

        def __enter__(self):
            return self._c

        def __exit__(self, exc_type, exc_val, exc_tb):
            # Commit explicitly so PG visibility is consistent with the
            # `with` semantics in protocol.py.
            if exc_type is None:
                self._c.commit()
            return False

        def execute(self, *args, **kwargs):
            return self._c.execute(*args, **kwargs)

    monkeypatch.setattr(protocol_module, "connect_db", lambda _path: _ConnGuard(conn))

    session_id = str(uuid.uuid4())
    protocol_module._store_debug_log(
        session_id=session_id,
        agent_name="quant_researcher",
        round_num=1,
        system_prompt="You are a council agent.",
        user_prompt="Assess the market.",
        debug={"latency_ms": 123, "raw": "raw response"},
        assessment={"_parse_failed": False, "key_reasoning": "ok"},
        db_path=":unused:",
    )

    assert _count_rows(conn, "council_debug_log") == 1
    row = _select_one(conn, "council_debug_log", "session_id", session_id)
    assert row["agent_name"] == "quant_researcher"
    assert row["round"] == 1
    assert row["parsed_successfully"] == 1
    assert row["latency_ms"] == 123


def test_store_debug_log_duplicate_is_ignored(conn_engine, monkeypatch):
    """T1.8 #2: second insert with same debug_id is ignored — original wins."""
    from src.council import protocol as protocol_module

    conn = conn_engine
    _setup_table(conn, "council_debug_log")

    # First call: generate a known debug_id by patching uuid.uuid4 to return
    # the same UUID twice in a row — `_store_debug_log` uses uuid.uuid4()
    # inside its INSERT, so this is the only way to force a PK collision.
    fixed_debug_id = "11111111-1111-1111-1111-111111111111"

    class _ConnGuard:
        def __init__(self, c):
            self._c = c

        def __enter__(self):
            return self._c

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                self._c.commit()
            return False

        def execute(self, *args, **kwargs):
            return self._c.execute(*args, **kwargs)

    monkeypatch.setattr(protocol_module, "connect_db", lambda _path: _ConnGuard(conn))

    class _FakeUUID:
        def __init__(self, value):
            self._value = value

        def __str__(self):
            return self._value

    monkeypatch.setattr(protocol_module.uuid, "uuid4", lambda: _FakeUUID(fixed_debug_id))

    session_id = "session-A"
    protocol_module._store_debug_log(
        session_id=session_id,
        agent_name="quant_researcher",
        round_num=1,
        system_prompt="prompt v1",
        user_prompt="user v1",
        debug={"latency_ms": 100, "raw": "raw v1"},
        assessment={"_parse_failed": False, "key_reasoning": "first"},
        db_path=":unused:",
    )

    # Second call: same debug_id, different content → should be IGNORED.
    protocol_module._store_debug_log(
        session_id="session-B-IGNORED",
        agent_name="risk_manager",
        round_num=2,
        system_prompt="prompt v2",
        user_prompt="user v2",
        debug={"latency_ms": 999, "raw": "raw v2"},
        assessment={"_parse_failed": True, "key_reasoning": "second"},
        db_path=":unused:",
    )

    assert _count_rows(conn, "council_debug_log") == 1
    row = _select_one(conn, "council_debug_log", "debug_id", fixed_debug_id)
    # Original row preserved — none of v2's fields overwrote v1's.
    assert row["session_id"] == "session-A"
    assert row["agent_name"] == "quant_researcher"
    assert row["round"] == 1
    assert row["latency_ms"] == 100
    assert row["parsed_successfully"] == 1

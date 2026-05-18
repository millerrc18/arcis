"""Tests for src/data_enrichment/staleness.py — Sprint 5 §J5/§J6 Phase 1 T1.9.

Covers the engine_aware_upsert migration of `record_fetch`. Parametrized over
[sqlite, postgres] so the dual-engine semantics (`in_place_update` per T0.12
audit) are exercised end-to-end. PG variant skips cleanly when
`TEST_DATABASE_URL` is unset.

The data_freshness table uses a composite TEXT PK (source, ticker). The audit
(docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md §5.1)
classifies it `in_place_update` — no incoming FKs, no triggers, no rowid
readers — so ON CONFLICT DO UPDATE on PG is semantically equivalent to
INSERT OR REPLACE on SQLite. These tests assert both engines:

1. record_fetch inserts a fresh row when no conflict exists.
2. record_fetch updates `last_fetched_at`/`status`/`created_at` (the
   non-target columns) on a second call with the same (source, ticker)
   composite key, leaving exactly one row per (source, ticker).
"""

import os
import sqlite3

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


def _build_sqlite_ddl(table_name):
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
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


@pytest.fixture
def sqlite_conn(tmp_path):
    """File-backed SQLite connection so record_fetch's connect_db(path) works."""
    db_path = str(tmp_path / "test_staleness.db")
    conn = sqlite3.connect(db_path)
    conn.execute(_build_sqlite_ddl("data_freshness"))
    conn.commit()
    conn.close()
    yield db_path


@pytest.fixture
def pg_conn():
    """Live PG wrapper bootstrapped with data_freshness table."""
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    wrapper = PostgresConnectionWrapper(raw)
    cur = wrapper.cursor()
    cur.execute("DROP TABLE IF EXISTS data_freshness CASCADE")
    cur.execute(_build_pg_ddl("data_freshness"))
    wrapper.commit()
    yield wrapper
    try:
        cur2 = wrapper.cursor()
        cur2.execute("DROP TABLE IF EXISTS data_freshness CASCADE")
        wrapper.commit()
    except Exception:
        pass
    wrapper.close()


@pytest.fixture(params=["sqlite", "postgres"])
def engine_setup(request, monkeypatch):
    """Yields (engine, handle) for parametrized record_fetch calls.

    SQLite variant returns (engine='sqlite', handle=<sqlite_path>) —
    record_fetch is called with `db_path=<sqlite_path>` directly.

    Postgres variant returns (engine='postgres', handle=<pg_wrapper>) —
    `src.data_enrichment.staleness.connect_db` is monkeypatched to return
    the live PG wrapper regardless of how record_fetch passes its db_path
    arg. This is the cleanest way to exercise the PG SQL path for the new
    engine_aware_upsert call without changing record_fetch's signature
    (signature change is out of scope for T1.9 — see plan-phase-1.json).
    """
    if request.param == "sqlite":
        db_path = request.getfixturevalue("sqlite_conn")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        yield ("sqlite", db_path)
    elif request.param == "postgres":
        wrapper = request.getfixturevalue("pg_conn")
        # connect_db is used as a context manager (`with connect_db(...) as conn`)
        # so the patched callable must return an object that itself is a
        # context manager. `wrapper` already implements __enter__/__exit__
        # (see PostgresConnectionWrapper.__enter__) but its __exit__ commits
        # / closes — which would invalidate the wrapper for our later read.
        # Use a tiny shim that yields the wrapper without closing it.
        class _NoCloseCtx:
            def __init__(self, w):
                self._w = w

            def __enter__(self):
                return self._w

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    self._w.commit()
                else:
                    self._w.rollback()
                # Intentionally do NOT close — the test fixture owns the
                # lifecycle (so subsequent reads can use the same wrapper).
                return False

        monkeypatch.setattr(
            "src.data_enrichment.staleness.connect_db",
            lambda _path: _NoCloseCtx(wrapper),
        )
        yield ("postgres", wrapper)
    else:  # pragma: no cover
        raise ValueError(f"unknown engine param: {request.param!r}")


def _read_freshness(engine, handle, source, ticker):
    """Engine-aware single-row reader for assertions.

    SQLite path: opens a fresh sqlite3 connection at the db_path. Postgres
    path: uses the live PG wrapper.
    """
    if engine == "sqlite":
        conn = sqlite3.connect(handle)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM data_freshness WHERE source=? AND ticker=?",
                (source, ticker),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    else:
        cur = handle.cursor()
        cur.execute(
            "SELECT * FROM data_freshness WHERE source=? AND ticker=?",
            (source, ticker),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}


def _count_freshness(engine, handle):
    if engine == "sqlite":
        conn = sqlite3.connect(handle)
        try:
            return conn.execute("SELECT COUNT(*) FROM data_freshness").fetchone()[0]
        finally:
            conn.close()
    else:
        cur = handle.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM data_freshness")
        return cur.fetchone()["c"]


def test_record_fetch_inserts_new_row(engine_setup):
    """T1.9: record_fetch inserts a fresh row on first call (both engines)."""
    from src.data_enrichment.staleness import record_fetch

    engine, handle = engine_setup
    # PG path: db_path arg is ignored (connect_db is monkeypatched to the
    # PG wrapper). SQLite path: db_path is the tmp test database file.
    db_path = handle if engine == "sqlite" else "ignored-by-monkeypatch"

    record_fetch("price", "AAPL", db_path=db_path)

    assert _count_freshness(engine, handle) == 1
    row = _read_freshness(engine, handle, "price", "AAPL")
    assert row is not None
    assert row["source"] == "price"
    assert row["ticker"] == "AAPL"
    assert row["status"] == "acceptable"
    assert row["last_fetched_at"] is not None
    assert row["created_at"] is not None


def test_record_fetch_upserts_existing_row(engine_setup):
    """T1.9: second call with same (source, ticker) UPDATES non-target columns.

    `data_freshness` is `in_place_update` per T0.12 audit — composite PK
    on (source, ticker), no FK / trigger / rowid concerns. Second call
    must yield exactly one row whose `last_fetched_at` reflects the
    second call's timestamp (the non-target columns get refreshed).
    """
    import time

    from src.data_enrichment.staleness import record_fetch

    engine, handle = engine_setup
    db_path = handle if engine == "sqlite" else "ignored-by-monkeypatch"

    record_fetch("price", "AAPL", db_path=db_path)
    first = _read_freshness(engine, handle, "price", "AAPL")
    assert first is not None
    first_ts = first["last_fetched_at"]

    # Sleep enough that datetime.now() advances meaningfully (ISO timestamps
    # are microsecond-precision so this is conservative — 10ms suffices).
    time.sleep(0.05)
    record_fetch("price", "AAPL", db_path=db_path)

    assert _count_freshness(engine, handle) == 1, (
        "second record_fetch on same (source, ticker) must UPSERT, not duplicate"
    )
    second = _read_freshness(engine, handle, "price", "AAPL")
    assert second is not None
    assert second["last_fetched_at"] != first_ts, (
        f"last_fetched_at should be updated; first={first_ts!r} second={second['last_fetched_at']!r}"
    )

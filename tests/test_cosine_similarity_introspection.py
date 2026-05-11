"""Tests for _has_full_text_column engine-aware column introspection.

Sprint 5 §J5/§J6 Phase 2 T2.5 — replaces `PRAGMA table_info(edgar_filings)`
at src/platform/features/cosine_similarity.py:161 with the engine-aware
`engine_aware_column_info` helper from src/utils/db.py.

The contract for `_has_full_text_column`:

* Returns True when the `edgar_filings` table has a `full_text` column.
* Returns False when the `edgar_filings` table exists but has no
  `full_text` column (Sprint 3 test fixtures may omit it).
* Works against BOTH SQLite (production) and PostgreSQL (Render
  deployment) connections, dispatching via `engine_aware_column_info`.

Tests parametrize on `engine` ∈ {'sqlite', 'postgres'}. Postgres-engine
tests skip when `TEST_DATABASE_URL` is not set or not a `postgres://`
URL — same convention as test_db_engine_aware_introspection.py.
"""

import os
import sqlite3
import tempfile

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")
_PG_SKIP_REASON = "TEST_DATABASE_URL not set or not postgres://"


def _build_sqlite_fixture(with_full_text: bool):
    """Return (conn, cleanup_fn) for SQLite with edgar_filings table.

    The `with_full_text` flag controls whether the table is created with
    the `full_text` column or without it (mirroring test-fixture variability
    documented in `_has_full_text_column`'s docstring).
    """
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if with_full_text:
        conn.executescript(
            "CREATE TABLE edgar_filings ("
            "  id INTEGER PRIMARY KEY,"
            "  accession_number TEXT,"
            "  full_text TEXT,"
            "  sections_json TEXT"
            ")"
        )
    else:
        conn.executescript(
            "CREATE TABLE edgar_filings ("
            "  id INTEGER PRIMARY KEY,"
            "  accession_number TEXT,"
            "  sections_json TEXT"
            ")"
        )
    conn.commit()

    def cleanup():
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return conn, cleanup


def _build_pg_fixture(with_full_text: bool):
    """Return (wrapper, cleanup_fn) for PostgreSQL with edgar_filings table.

    Mirrors `_build_sqlite_fixture`. Drops/creates the table on a fresh
    connection so test isolation is guaranteed across runs.
    """
    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw.autocommit = True
    cur = raw.cursor()
    cur.execute("DROP TABLE IF EXISTS edgar_filings CASCADE")
    if with_full_text:
        cur.execute(
            "CREATE TABLE edgar_filings ("
            "  id SERIAL PRIMARY KEY,"
            "  accession_number TEXT,"
            "  full_text TEXT,"
            "  sections_json TEXT"
            ")"
        )
    else:
        cur.execute(
            "CREATE TABLE edgar_filings ("
            "  id SERIAL PRIMARY KEY,"
            "  accession_number TEXT,"
            "  sections_json TEXT"
            ")"
        )
    cur.close()
    raw.autocommit = False

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        try:
            raw.autocommit = True
            cur2 = raw.cursor()
            cur2.execute("DROP TABLE IF EXISTS edgar_filings CASCADE")
            cur2.close()
        except Exception:
            pass
        wrapper.close()

    return wrapper, cleanup


@pytest.fixture
def edgar_conn(request):
    """Parametrized fixture: engine + with_full_text combination.

    `request.param` is a tuple `(engine, with_full_text)`. The PG variant
    skips automatically when `TEST_DATABASE_URL` is unset.
    """
    engine, with_full_text = request.param
    if engine == "sqlite":
        conn, cleanup = _build_sqlite_fixture(with_full_text)
    elif engine == "postgres":
        if not _PG_AVAILABLE:
            pytest.skip(_PG_SKIP_REASON)
        conn, cleanup = _build_pg_fixture(with_full_text)
    else:
        raise ValueError(f"Unknown engine: {engine}")
    try:
        yield conn, with_full_text
    finally:
        cleanup()


@pytest.mark.parametrize(
    "edgar_conn",
    [
        ("sqlite", True),
        ("sqlite", False),
        ("postgres", True),
        ("postgres", False),
    ],
    indirect=True,
    ids=[
        "sqlite-with-full-text",
        "sqlite-without-full-text",
        "postgres-with-full-text",
        "postgres-without-full-text",
    ],
)
def test_has_full_text_column_dual_engine(edgar_conn):
    """_has_full_text_column dispatches through engine_aware_column_info.

    Asserts the function returns True iff the table has a `full_text`
    column on BOTH SQLite and PostgreSQL connections. The PG path proves
    the engine-aware migration is complete — calling `_has_full_text_column`
    with a `PostgresConnectionWrapper` must NOT raise the SQLite-only
    `PRAGMA table_info(...)` syntax error.
    """
    from src.platform.features.cosine_similarity import _has_full_text_column

    conn, with_full_text = edgar_conn
    result = _has_full_text_column(conn)
    assert result is with_full_text, (
        f"expected _has_full_text_column={with_full_text}, got {result}"
    )

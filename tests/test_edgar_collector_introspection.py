"""Tests for edgar_collector._ensure_nlp_columns engine-aware introspection.

Sprint 5 §J5/§J6 Phase 2 T2.1 — Modified-A migration.

`src/data_collection/edgar_collector.py:_ensure_nlp_columns` used to call
`PRAGMA table_info(edgar_filings)` directly, which only works on SQLite. The
T2.1 migration replaces the inline PRAGMA with
`src.utils.db.engine_aware_column_info(conn, 'edgar_filings')`, the engine-
agnostic helper introduced in Phase 0 T0.5.

This test is parametrized over `engine=['sqlite', 'postgres']`. The postgres
variant skips when `TEST_DATABASE_URL` is unset — same convention as
`tests/test_db_engine_aware_introspection.py`. The test exercises the
introspection helper through `_ensure_nlp_columns` end-to-end so it locks
the call-site contract (returns True when all 4 NLP columns are present in
the edgar_filings registry schema).
"""

import os
import sqlite3
import tempfile

import psycopg2
import psycopg2.extras
import pytest


# ---------------------------------------------------------------------------
# Postgres fixture detection — skip PG cases when no live cluster reachable.
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")
_PG_SKIP_REASON = "TEST_DATABASE_URL / DATABASE_URL not set or not postgres://"


# ---------------------------------------------------------------------------
# Per-engine fixture: build an edgar_filings table from the registry on the
# matching engine, then yield a connection the call site can consume.
# ---------------------------------------------------------------------------


def _build_sqlite_fixture():
    """Return (conn, cleanup_fn) for SQLite with edgar_filings from registry."""
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(generate_create_sql(TABLES["edgar_filings"]))
    conn.commit()

    def cleanup():
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return conn, cleanup


def _build_pg_fixture():
    """Return (conn, cleanup_fn) for Postgres with edgar_filings from registry."""
    from src.schema.registry import TABLES
    from src.schema.postgres import generate_create_sql
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    cur = raw.cursor()
    cur.execute("DROP TABLE IF EXISTS edgar_filings CASCADE")
    cur.execute(generate_create_sql(TABLES["edgar_filings"]))
    raw.commit()
    cur.close()

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        try:
            cur2 = raw.cursor()
            cur2.execute("DROP TABLE IF EXISTS edgar_filings CASCADE")
            raw.commit()
            cur2.close()
        except Exception:
            pass
        wrapper.close()

    return wrapper, cleanup


@pytest.fixture
def db_conn(request):
    """Parametrized fixture yielding either a SQLite or PG connection."""
    engine = request.param
    if engine == "sqlite":
        conn, cleanup = _build_sqlite_fixture()
    elif engine == "postgres":
        if not _PG_AVAILABLE:
            pytest.skip(_PG_SKIP_REASON)
        conn, cleanup = _build_pg_fixture()
    else:
        raise ValueError(f"Unknown engine: {engine}")
    try:
        yield conn
    finally:
        cleanup()


# ---------------------------------------------------------------------------
# T2.1 tests — _ensure_nlp_columns uses engine_aware_column_info.
# ---------------------------------------------------------------------------


class TestEnsureNlpColumns:
    """`_ensure_nlp_columns` must work on BOTH SQLite and PostgreSQL.

    Before T2.1 the function called PRAGMA table_info directly, which
    SQLite-only — the call crashed on PG with `syntax error at or near
    PRAGMA`. After T2.1, the call routes through `engine_aware_column_info`
    in `src/utils/db.py`, which dispatches by connection type.
    """

    @pytest.mark.parametrize(
        "db_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_returns_true_when_all_nlp_columns_present(self, db_conn):
        """All 4 NLP columns are part of the registry edgar_filings schema;
        the function must return True on both engines.

        The four columns the function checks for are:
            sentiment_polarity
            sentiment_negative_count
            sentiment_uncertainty_count
            cautionary_phrases

        All four are declared in `src/schema/registry.py` for edgar_filings,
        so the introspection helper must report them present on a freshly
        registry-built table.
        """
        from src.data_collection.edgar_collector import _ensure_nlp_columns

        assert _ensure_nlp_columns(db_conn) is True


# ---------------------------------------------------------------------------
# Regression lock — ensure the migration removed the SQLite-only PRAGMA call.
# ---------------------------------------------------------------------------


def test_edgar_collector_does_not_call_pragma_table_info_directly():
    """Regression lock for T2.1 — the PRAGMA call must not return.

    Before T2.1 there was a single `PRAGMA table_info(edgar_filings)` call
    inside `_ensure_nlp_columns`. Phase 2 replaces it with
    `engine_aware_column_info(conn, 'edgar_filings')`. This static check
    ensures no future caller silently re-introduces the engine-specific
    syntax that crashes on Postgres.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "data_collection" / "edgar_collector.py"
    contents = src.read_text(encoding="utf-8")
    assert "PRAGMA table_info" not in contents, (
        "src/data_collection/edgar_collector.py must not call PRAGMA table_info "
        "directly — use engine_aware_column_info() from src.utils.db instead "
        "(Sprint 5 §J5/§J6 Phase 2 T2.1)."
    )

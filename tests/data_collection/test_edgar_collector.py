"""Engine-aware UPSERT migration tests for edgar_collector.

Sprint 5 §J5/§J6 Phase 1 T1.4 — migrate the `INSERT OR IGNORE INTO
edgar_filings` at src/data_collection/edgar_collector.py:338 to call
`engine_aware_upsert(conn, 'edgar_filings', row_dict, action='ignore')`.

The wrapper resolves the conflict target via `_resolve_conflict_target`
(T0.3) which honors `sync_conflict_col='accession_number'` over the
integer primary key `id`. So a second insert of a row with the same
`accession_number` must be a no-op on BOTH engines.

Parametrized over [sqlite, postgres] via the `conn_engine` fixture
pattern from `tests/test_db_engine_aware_upsert.py`. PG tests skip
cleanly when `TEST_DATABASE_URL` / `DATABASE_URL` is unset.
"""

import os
import sqlite3

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_sqlite_ddl(table_name):
    """Return SQLite CREATE TABLE SQL for the registry-defined table."""
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


def _build_sqlite_indexes(table_name):
    """Return CREATE [UNIQUE] INDEX statements for the table's indexes.

    The UNIQUE index on `accession_number` is what makes `INSERT OR IGNORE`
    actually dedup — without it, SQLite would happily store duplicates with
    different autoincrement `id` values.
    """
    from src.schema.registry import TABLES

    td = TABLES[table_name]
    stmts = []
    for idx in td.indexes:
        unique = "UNIQUE " if idx.unique else ""
        cols = ", ".join(idx.columns)
        stmts.append(
            f"CREATE {unique}INDEX {idx.name} ON {table_name}({cols});"
        )
    return stmts


def _setup_table(conn, table_name):
    """Drop+recreate `table_name` (with indexes) on whichever engine `conn` is."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        from src.schema.postgres import (
            generate_create_indexes_sql,
            generate_create_table_sql,
        )
        from src.schema.registry import TABLES

        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cur.execute(generate_create_table_sql(TABLES[table_name]))
        idx_sql = generate_create_indexes_sql(TABLES[table_name])
        for stmt in idx_sql.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(_build_sqlite_ddl(table_name))
        for idx_sql in _build_sqlite_indexes(table_name):
            conn.execute(idx_sql)
        conn.commit()


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn():
    """Live psycopg2 wrapper. Skips if TEST_DATABASE_URL not set."""
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


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine(request):
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn")
    elif engine == "postgres":
        return request.getfixturevalue("pg_conn")
    raise ValueError(f"unknown engine: {engine}")


def _count_rows(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    if row is None:
        return 0
    try:
        return row["c"]
    except (KeyError, TypeError, IndexError):
        return row[0]


# ---------------------------------------------------------------------------
# Tests — migrated `INSERT OR IGNORE` honors accession_number dedup
# ---------------------------------------------------------------------------


def _make_filing_row(accession_number, ticker="AAPL"):
    """Build a row_dict matching the columns the collector writes at :338."""
    return {
        "ticker": ticker,
        "cik": "0000320193",
        "form_type": "10-K",
        "filing_date": "2026-05-11",
        "accession_number": accession_number,
        "filing_url": (
            "https://data.sec.gov/Archives/edgar/data/320193/"
            f"{accession_number.replace('-', '')}/"
        ),
        "description": "Annual report",
        "full_text": "(filing text)",
        "sections_json": None,
        "word_count": 12345,
        "collected_at": "2026-05-11T09:30:00-04:00",
    }


def test_edgar_filings_first_insert_lands(conn_engine):
    """T1.4 — engine_aware_upsert action='ignore' inserts a brand-new row."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "edgar_filings")

    row = _make_filing_row("0000320193-26-000001")
    engine_aware_upsert(conn, "edgar_filings", row, action="ignore")
    conn.commit()

    assert _count_rows(conn, "edgar_filings") == 1


def test_edgar_filings_duplicate_accession_ignored(conn_engine):
    """T1.4 — second insert with the same accession_number is a no-op.

    The conflict target is `accession_number` (registry sync_conflict_col),
    NOT the integer PK `id` — so attempting to re-insert the same filing
    with different field values (e.g., new collected_at) must NOT update
    or duplicate. SQLite: `INSERT OR IGNORE` honors the UNIQUE index.
    PG: `INSERT ... ON CONFLICT (accession_number) DO NOTHING`.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "edgar_filings")

    accession = "0000320193-26-000042"
    row1 = _make_filing_row(accession)
    engine_aware_upsert(conn, "edgar_filings", row1, action="ignore")
    conn.commit()

    # Same accession_number, different ticker + collected_at — should be ignored.
    row2 = _make_filing_row(accession, ticker="GOOG")
    row2["collected_at"] = "2026-05-12T09:30:00-04:00"
    engine_aware_upsert(conn, "edgar_filings", row2, action="ignore")
    conn.commit()

    assert _count_rows(conn, "edgar_filings") == 1

    # Confirm the FIRST insert's values are preserved (no UPDATE on conflict).
    cur = conn.cursor()
    cur.execute(
        "SELECT ticker, collected_at FROM edgar_filings WHERE accession_number = ?",
        (accession,),
    )
    row = cur.fetchone()
    assert row is not None
    try:
        ticker = row["ticker"]
        collected_at = row["collected_at"]
    except (KeyError, TypeError, IndexError):
        ticker = row[0]
        collected_at = row[1]
    assert ticker == "AAPL"
    assert collected_at == "2026-05-11T09:30:00-04:00"


def test_edgar_collector_uses_engine_aware_upsert():
    """T1.4 — the call site at :338 must dispatch through engine_aware_upsert.

    Static-check the source: the migrated module must NOT contain
    `INSERT OR IGNORE INTO edgar_filings` (the legacy literal) and MUST
    reference `engine_aware_upsert`. This locks in the migration so a
    future revert wouldn't pass silently if test_edgar_filings_*_ignored
    happened to be passing by coincidence on the sqlite branch.
    """
    from pathlib import Path

    src = Path(
        "src/data_collection/edgar_collector.py"
    ).read_text(encoding="utf-8")

    assert "INSERT OR IGNORE INTO edgar_filings" not in src, (
        "edgar_collector still contains the legacy INSERT OR IGNORE literal "
        "for edgar_filings — Phase 1 T1.4 migration must route through "
        "engine_aware_upsert(action='ignore') instead."
    )
    assert "engine_aware_upsert" in src, (
        "edgar_collector must import + call engine_aware_upsert for the "
        "Phase 1 T1.4 migration"
    )

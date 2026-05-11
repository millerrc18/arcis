"""Tests for point-in-time S&P 100 resolver (R3)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from src.schema.sqlite import create_all_tables
from src.platform.rigor.walkforward_universe import (
    HistoricalConstituentsError,
    load_constituents_from_csv,
    populate_constituents_table,
    resolve_universe_as_of,
    resolve_universe_size,
)

_CSV_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "reference" / "sp100_historical.csv"
)


@pytest.fixture
def populated_db(tmp_path):
    db = tmp_path / "wf_universe.sqlite3"
    create_all_tables(str(db))
    populate_constituents_table(str(db), _CSV_PATH)
    return str(db)


def test_csv_file_exists():
    assert _CSV_PATH.exists(), f"missing historical S&P 100 CSV at {_CSV_PATH}"


def test_csv_loader_returns_rows():
    rows = load_constituents_from_csv(_CSV_PATH)
    assert len(rows) >= 100, "expected >= 100 historical membership rows"


def test_csv_loader_raises_on_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    with pytest.raises(HistoricalConstituentsError, match="not found"):
        load_constituents_from_csv(missing)


def test_csv_loader_raises_on_bad_header(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("wrong,header\nAAPL,2020-01-01\n")
    with pytest.raises(HistoricalConstituentsError, match="header mismatch"):
        load_constituents_from_csv(bad)


def test_populate_is_idempotent(tmp_path):
    db = tmp_path / "wf_univ.sqlite3"
    create_all_tables(str(db))
    n1 = populate_constituents_table(str(db), _CSV_PATH)
    n2 = populate_constituents_table(str(db), _CSV_PATH)
    assert n1 == n2


def test_resolver_rejects_non_iso_date(populated_db):
    with pytest.raises(ValueError, match="ISO"):
        resolve_universe_as_of("not-a-date", populated_db)


def test_resolver_returns_nonempty_in_2020(populated_db):
    universe = resolve_universe_as_of("2020-01-15", populated_db)
    assert "AAPL" in universe
    assert "MSFT" in universe
    assert len(universe) >= 80


def test_resolver_excludes_post_removal(populated_db):
    """WBA was removed 2022-09-19 → 2023-01-01 universe should NOT contain WBA."""
    u_after = resolve_universe_as_of("2023-01-01", populated_db)
    assert "WBA" not in u_after
    # But before the removal it should be present.
    u_before = resolve_universe_as_of("2022-01-01", populated_db)
    assert "WBA" in u_before


def test_resolver_tsla_added_june_2020(populated_db):
    """TSLA added 2020-06-22 — must be absent on 2020-06-21, present on 2020-06-22."""
    u_pre = resolve_universe_as_of("2020-06-21", populated_db)
    u_post = resolve_universe_as_of("2020-06-22", populated_db)
    assert "TSLA" not in u_pre
    assert "TSLA" in u_post


def test_resolver_meta_rename_from_fb(populated_db):
    """FB renamed to META effective 2022-06-09. Before → FB in universe, META absent.
    After → META in universe, FB absent."""
    u_pre = resolve_universe_as_of("2022-06-08", populated_db)
    u_post = resolve_universe_as_of("2022-06-10", populated_db)
    assert "FB" in u_pre
    assert "META" not in u_pre
    assert "META" in u_post
    assert "FB" not in u_post


def test_resolver_utx_rtn_merger_into_rtx(populated_db):
    """2020-04-02: UTX and RTN separate members. 2020-04-03: merged to RTX."""
    u_pre = resolve_universe_as_of("2020-04-02", populated_db)
    u_post = resolve_universe_as_of("2020-04-03", populated_db)
    assert "UTX" in u_pre
    assert "RTN" in u_pre
    assert "RTX" not in u_pre
    assert "UTX" not in u_post
    assert "RTN" not in u_post
    assert "RTX" in u_post


def test_resolve_universe_size_matches_list_length(populated_db):
    count = resolve_universe_size("2021-06-01", populated_db)
    universe = resolve_universe_as_of("2021-06-01", populated_db)
    assert count == len(universe)


def test_resolver_empty_db_returns_empty(tmp_path):
    db = tmp_path / "empty.sqlite3"
    create_all_tables(str(db))
    assert resolve_universe_as_of("2022-01-01", str(db)) == []


def test_resolver_deduplicates_reentries(tmp_path):
    """A ticker with two add-events (removed then re-added) must appear once."""
    db = tmp_path / "readd.sqlite3"
    create_all_tables(str(db))
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO sp100_historical_constituents "
        "(ticker, added_date, removed_date) VALUES (?, ?, ?)",
        ("TEST", "2018-01-01", "2019-01-01"),
    )
    conn.execute(
        "INSERT INTO sp100_historical_constituents "
        "(ticker, added_date, removed_date) VALUES (?, ?, ?)",
        ("TEST", "2021-01-01", None),
    )
    conn.commit()
    conn.close()
    u = resolve_universe_as_of("2022-01-01", str(db))
    assert u.count("TEST") == 1


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 1 T1.15 — populate_constituents_table engine_aware_upsert
# ---------------------------------------------------------------------------
#
# Test strategy (per T1.15 brief):
#   * sp100_historical_constituents classified `in_place_update` per T0.12
#     audit §5.9. Composite TEXT PK `(ticker, added_date)` — readers query
#     date-range based.
#   * Parametrized across [sqlite, postgres] like
#     tests/evaluation/test_build_score.py — PG path skips cleanly when
#     TEST_DATABASE_URL / DATABASE_URL is not a postgres:// URL.
#   * First insert lands the row; second insert with same composite PK
#     UPDATES non-target columns (removed_date, company_name, reason).

TEST_PG_URL_UNIV = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE_UNIV = TEST_PG_URL_UNIV.startswith("postgres")


def _build_sqlite_ddl_univ(table_name):
    """Return SQLite CREATE TABLE SQL for one of the audited tables."""
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


def _build_pg_ddl_univ(table_name):
    """Return Postgres CREATE TABLE SQL for one of the audited tables."""
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


@pytest.fixture
def sqlite_conn_univ():
    """In-memory SQLite connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn_univ():
    """Live psycopg2 wrapper. Skips if TEST_DATABASE_URL not set."""
    if not _PG_AVAILABLE_UNIV:
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL_UNIV, cursor_factory=psycopg2.extras.RealDictCursor
    )
    wrapper = PostgresConnectionWrapper(raw)
    yield wrapper
    try:
        wrapper.rollback()
    except Exception:
        pass
    wrapper.close()


def _setup_constituents_table(conn):
    """Drop+recreate `sp100_historical_constituents` on the given engine."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS sp100_historical_constituents CASCADE")
        cur.execute(_build_pg_ddl_univ("sp100_historical_constituents"))
        conn.commit()
    else:
        conn.execute("DROP TABLE IF EXISTS sp100_historical_constituents")
        conn.execute(_build_sqlite_ddl_univ("sp100_historical_constituents"))
        conn.commit()


def _get_univ_conn(request):
    """Return the conn fixture matching the parametrized engine."""
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn_univ")
    elif engine == "postgres":
        return request.getfixturevalue("pg_conn_univ")
    raise ValueError(f"unknown engine: {engine}")


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine_univ(request):
    return _get_univ_conn(request)


def _count_rows_univ(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    return row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]


class TestSP100HistoricalConstituentsEngineAwareUpsert:
    """T1.15: sp100_historical_constituents.engine_aware_upsert dual-engine."""

    def test_first_insert_lands_row(self, conn_engine_univ):
        """T1.15 #5: first insert against sp100_historical_constituents lands.

        Composite PK (ticker, added_date) — the audit §5.9 classified this
        as `in_place_update` since readers are date-range based and there
        are no incoming FKs / triggers / rowid dependencies.
        """
        from src.utils.db import engine_aware_upsert

        conn = conn_engine_univ
        _setup_constituents_table(conn)

        row = {
            "ticker": "TEST_ABC",
            "added_date": "2020-06-22",
            "removed_date": None,
            "company_name": "Test ABC Inc",
            "reason": "addition",
        }
        engine_aware_upsert(
            conn, "sp100_historical_constituents", row, action="replace",
        )
        conn.commit()

        assert _count_rows_univ(conn, "sp100_historical_constituents") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM sp100_historical_constituents "
            "WHERE ticker=? AND added_date=?",
            ("TEST_ABC", "2020-06-22"),
        )
        fetched = cur.fetchone()
        assert fetched["company_name"] == "Test ABC Inc"
        assert fetched["removed_date"] is None
        assert fetched["reason"] == "addition"

    def test_replace_updates_existing_row(self, conn_engine_univ):
        """T1.15 #6: re-upserting same (ticker, added_date) UPDATES non-PK.

        Simulates re-loading the curated CSV after a correction
        (e.g., setting `removed_date` once a ticker is officially removed,
        updating the `company_name` after a rename).
        """
        from src.utils.db import engine_aware_upsert

        conn = conn_engine_univ
        _setup_constituents_table(conn)

        row1 = {
            "ticker": "TEST_XYZ",
            "added_date": "2018-01-01",
            "removed_date": None,
            "company_name": "Test XYZ Old Name",
            "reason": "addition",
        }
        engine_aware_upsert(
            conn, "sp100_historical_constituents", row1, action="replace",
        )

        # Second load — same composite PK, updated removed_date + name
        row2 = {
            "ticker": "TEST_XYZ",
            "added_date": "2018-01-01",
            "removed_date": "2023-12-31",
            "company_name": "Test XYZ Renamed",
            "reason": "renamed-and-removed",
        }
        engine_aware_upsert(
            conn, "sp100_historical_constituents", row2, action="replace",
        )
        conn.commit()

        assert _count_rows_univ(conn, "sp100_historical_constituents") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM sp100_historical_constituents "
            "WHERE ticker=? AND added_date=?",
            ("TEST_XYZ", "2018-01-01"),
        )
        fetched = cur.fetchone()
        assert fetched["removed_date"] == "2023-12-31"
        assert fetched["company_name"] == "Test XYZ Renamed"
        assert fetched["reason"] == "renamed-and-removed"


def test_populate_constituents_no_literal_insert_or_replace_in_source():
    """T1.15 lock-in: walkforward_universe.py must not contain `INSERT OR REPLACE`."""
    universe_path = (
        Path(__file__).resolve().parents[3]
        / "src" / "platform" / "rigor" / "walkforward_universe.py"
    )
    source = universe_path.read_text(encoding="utf-8")
    # Allow the docstring to mention the historical wording; ban literal SQL.
    sql_lines = [
        line for line in source.splitlines()
        if "INSERT OR REPLACE INTO" in line
    ]
    assert sql_lines == [], (
        "src/platform/rigor/walkforward_universe.py must not contain literal "
        "`INSERT OR REPLACE INTO` after T1.15 migration; use "
        "engine_aware_upsert(action='replace') via src.utils.db instead. "
        f"Found: {sql_lines}"
    )

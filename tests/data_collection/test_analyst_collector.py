"""Tests for analyst_collector engine_aware_upsert migration.

Sprint 5 §J5/§J6 Phase 1 T1.5 — verifies that the INSERT OR IGNORE at
src/data_collection/analyst_collector.py:153 has been routed through
`engine_aware_upsert(conn, 'analyst_estimates', row_dict, action='ignore')`
and that dedup behavior holds on BOTH SQLite and Postgres.

Conflict target for analyst_estimates: (ticker, date, source) — declared by
`sync_conflict_col` on the TableDef in src/schema/registry.py. The
UNIQUE INDEX `idx_analyst_unique` on (ticker, date, source) is what makes
the dedup actually fire on SQLite; on PG the same column triple is the
ON CONFLICT target.

The PG variant of the parametrized test skips cleanly when
`TEST_DATABASE_URL` is unset — see tests/conftest.py:`pg_wrapper` fixture.
"""

from __future__ import annotations

import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Helpers — DDL bootstrap (mirror tests/test_db_engine_aware_upsert.py pattern)
# ---------------------------------------------------------------------------


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


def _build_sqlite_indexes(table_name):
    """Return CREATE [UNIQUE] INDEX statements for the table's indexes."""
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


def _build_pg_ddl(table_name):
    """Return the Postgres CREATE TABLE SQL from the registry."""
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


def _build_pg_indexes(table_name):
    """Return CREATE INDEX statements for the PG side."""
    from src.schema.postgres import generate_create_indexes_sql
    from src.schema.registry import TABLES

    sql = generate_create_indexes_sql(TABLES[table_name])
    return [s + ";" for s in sql.split(";") if s.strip()]


def _setup_table(conn, table_name):
    """Drop+recreate `table_name` (with indexes) on whichever engine `conn` is for."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cur.execute(_build_pg_ddl(table_name))
        for idx_sql in _build_pg_indexes(table_name):
            cur.execute(idx_sql)
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(_build_sqlite_ddl(table_name))
        for idx_sql in _build_sqlite_indexes(table_name):
            conn.execute(idx_sql)
        conn.commit()


# ---------------------------------------------------------------------------
# Fixtures — sqlite conn + (optional) pg conn per-test
# ---------------------------------------------------------------------------


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
    import os

    test_pg_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL", ""
    )
    if not test_pg_url.startswith("postgres"):
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        test_pg_url, cursor_factory=psycopg2.extras.RealDictCursor
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
    """Engine-parametrized DB fixture."""
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
    return row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]


# ---------------------------------------------------------------------------
# Test — engine_aware_upsert(action='ignore') dedup on (ticker, date, source)
# ---------------------------------------------------------------------------


def test_analyst_estimates_upsert_ignore_dedup(conn_engine):
    """T1.5: first insert lands, duplicate (same ticker,date,source) is ignored.

    Mirrors the production call path at
    src/data_collection/analyst_collector.py:152 after the migration —
    `engine_aware_upsert(conn, 'analyst_estimates', row_dict, action='ignore')`.
    The conflict target (ticker, date, source) comes from sync_conflict_col on
    the TableDef.

    First insert: lands → row count = 1.
    Second insert with same (ticker, date, source) but different values:
    ignored → row count still 1, original values preserved.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "analyst_estimates")

    row1 = {
        "ticker": "AAPL",
        "date": "2026-05-11",
        "consensus_buy": 20,
        "consensus_hold": 5,
        "consensus_sell": 1,
        "consensus_strong_buy": 10,
        "consensus_strong_sell": 0,
        "price_target_high": 250.0,
        "price_target_low": 150.0,
        "price_target_mean": 200.0,
        "price_target_median": 195.0,
        "num_analysts": 36,
        "source": "finnhub",
        "collected_at": "2026-05-11T00:00:00",
    }
    engine_aware_upsert(conn, "analyst_estimates", row1, action="ignore")
    conn.commit()

    assert _count_rows(conn, "analyst_estimates") == 1

    # Duplicate target — same (ticker, date, source) — should be ignored.
    row2 = dict(row1)
    row2["consensus_buy"] = 99  # should NOT overwrite
    row2["num_analysts"] = 999
    row2["collected_at"] = "2026-05-11T02:00:00"
    engine_aware_upsert(conn, "analyst_estimates", row2, action="ignore")
    conn.commit()

    assert _count_rows(conn, "analyst_estimates") == 1
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM analyst_estimates WHERE ticker=? AND date=? AND source=?",
        ("AAPL", "2026-05-11", "finnhub"),
    )
    fetched = cur.fetchone()
    # action='ignore' preserves original values
    assert fetched["consensus_buy"] == 20
    assert fetched["num_analysts"] == 36
    assert fetched["collected_at"] == "2026-05-11T00:00:00"


# ---------------------------------------------------------------------------
# Test — production call site routes through engine_aware_upsert
# ---------------------------------------------------------------------------


def test_collect_analyst_estimates_uses_engine_aware_upsert(tmp_path, monkeypatch):
    """T1.5: production call path at analyst_collector.py:152 must call
    `engine_aware_upsert(conn, 'analyst_estimates', row_dict, action='ignore')`.

    Patches `engine_aware_upsert` in the collector module to record the call
    and asserts that:
      1. The helper was called exactly once (single ticker, single insert),
      2. The table name argument was 'analyst_estimates',
      3. The action kwarg was 'ignore',
      4. The row_dict contained all 14 columns the original INSERT supplied
         (ticker, date, 5 consensus_*, 4 price_target_*, num_analysts,
          source='finnhub', collected_at).
    """
    from unittest.mock import MagicMock, patch

    from tests.conftest import init_test_db

    db_path = str(tmp_path / "test_analyst.db")
    init_test_db(db_path, ["analyst_estimates"])

    rec_data = [{"buy": 20, "hold": 5, "sell": 1, "strongBuy": 10, "strongSell": 0}]
    pt_data = {
        "targetHigh": 250.0,
        "targetLow": 150.0,
        "targetMean": 200.0,
        "targetMedian": 195.0,
    }

    with patch(
        "src.data_collection.analyst_collector._get_finnhub_key", return_value="key"
    ), patch(
        "src.data_collection.analyst_collector.finnhub_plan_supports",
        return_value=True,
    ), patch(
        "src.data_collection.analyst_collector.requests.get"
    ) as mock_get, patch(
        "src.data_collection.analyst_collector.time.sleep"
    ), patch(
        "src.data_collection.analyst_collector.engine_aware_upsert"
    ) as mock_upsert:
        mock_resp_rec = MagicMock()
        mock_resp_rec.json.return_value = rec_data
        mock_resp_rec.raise_for_status.return_value = None

        mock_resp_pt = MagicMock()
        mock_resp_pt.status_code = 200
        mock_resp_pt.json.return_value = pt_data
        mock_resp_pt.raise_for_status.return_value = None

        mock_get.side_effect = [mock_resp_rec, mock_resp_pt]

        from src.data_collection.analyst_collector import collect_analyst_estimates
        result = collect_analyst_estimates(["AAPL"], batch_size=5, db_path=db_path)

    assert result["tickers_processed"] == 1
    assert result["estimates_stored"] == 1

    # engine_aware_upsert was called once with the right args
    assert mock_upsert.call_count == 1
    call_args = mock_upsert.call_args
    # positional: (conn, table_name, row_dict)
    assert call_args.args[1] == "analyst_estimates"
    row_dict = call_args.args[2]
    # Action kwarg
    assert call_args.kwargs.get("action") == "ignore"
    # Required columns present
    assert row_dict["ticker"] == "AAPL"
    assert row_dict["source"] == "finnhub"
    assert "date" in row_dict
    assert "collected_at" in row_dict
    assert row_dict["consensus_buy"] == 20
    assert row_dict["consensus_hold"] == 5
    assert row_dict["consensus_sell"] == 1
    assert row_dict["consensus_strong_buy"] == 10
    assert row_dict["consensus_strong_sell"] == 0
    assert row_dict["price_target_high"] == 250.0
    assert row_dict["price_target_low"] == 150.0
    assert row_dict["price_target_mean"] == 200.0
    assert row_dict["price_target_median"] == 195.0
    assert row_dict["num_analysts"] == 36  # 20+5+1+10+0

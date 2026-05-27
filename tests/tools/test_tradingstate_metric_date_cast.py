# Purpose: Regression test for #124b — metric_date text=date type mismatch in GPU_METRICS_PG.
# Called by: pytest tests/tools/test_tradingstate_metric_date_cast.py
# Calls: src.tools.tradingstate.core._pg_snapshot (via GPU_METRICS_PG query)
# Owns tables: none (creates + drops a temp table in real test PG at 127.0.0.1:5434)
# Tests: (this file is the test)
#
# Root cause: schedule_metrics.metric_date is stored as TEXT (writer uses
# date.today().isoformat()). GPU_METRICS_PG originally compared with CURRENT_DATE
# (a PG date). PostgreSQL has no implicit cast for text = date, yielding:
#   UndefinedFunction: operator does not exist: text = date
#
# Fix: cast the column — metric_date::date = CURRENT_DATE
#
# The existing test_tradingstate_integration.py::_ensure_tables() creates
# schedule_metrics with metric_date DATE (not TEXT), so the type mismatch was
# never caught there. This test explicitly uses metric_date TEXT to exercise
# the production schema.

from __future__ import annotations

import os
from datetime import date

import psycopg2
import psycopg2.extras
import pytest

_TEST_DSN = (
    os.environ.get("TEST_DATABASE_URL")
    or "host=127.0.0.1 port=5434 dbname=halcyon user=test password=test"
)

# Unique table name so this test doesn't collide with other fixtures.
_TEMP_TABLE = "schedule_metrics_text_date_fixture"


def _pg_conn():
    return psycopg2.connect(_TEST_DSN, connect_timeout=5)


def _build_text_date_query(table_name: str) -> str:
    """Return GPU_METRICS_PG-equivalent query against the given table name."""
    return f"""
SELECT metric_name, metric_value
FROM {table_name}
WHERE metric_date = CURRENT_DATE
"""


def _build_text_date_query_fixed(table_name: str) -> str:
    """Return the fixed query with metric_date::date cast."""
    return f"""
SELECT metric_name, metric_value
FROM {table_name}
WHERE metric_date::date = CURRENT_DATE
"""


@pytest.fixture(scope="function")
def text_metric_date_table():
    """Create a schedule_metrics-equivalent table with metric_date TEXT, yield table name, then drop."""
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        # DROP + CREATE to guarantee a clean slate across repeated test runs
        # (CREATE TABLE IF NOT EXISTS without DROP accumulates stale rows).
        # CASCADE drops any dependent views (e.g. schedule_metrics_text_view)
        # left behind if a prior run aborted mid-test.
        cur.execute(f"DROP TABLE IF EXISTS {_TEMP_TABLE} CASCADE")
        cur.execute(f"""
            CREATE TABLE {_TEMP_TABLE} (
                id SERIAL PRIMARY KEY,
                metric_date TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                details TEXT
            )
        """)
        # Insert a row for today using isoformat() — exactly as the writer does in
        # src/scheduler/metrics.py (datetime.now(ET).strftime("%Y-%m-%d")) and
        # src/tools/tradingstate/core.py (date.today().isoformat())
        today_str = date.today().isoformat()
        cur.execute(
            f"""INSERT INTO {_TEMP_TABLE} (metric_date, metric_name, metric_value)
               VALUES (%s, %s, %s)""",
            (today_str, "gpu_health_ollama_ok", 1.0),
        )
        cur.execute(
            f"""INSERT INTO {_TEMP_TABLE} (metric_date, metric_name, metric_value)
               VALUES (%s, %s, %s)""",
            (today_str, "gpu_health_training_ok", 0.0),
        )
        conn.commit()
        yield _TEMP_TABLE, conn
    finally:
        try:
            cur2 = conn.cursor()
            cur2.execute(f"DROP TABLE IF EXISTS {_TEMP_TABLE} CASCADE")
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


def test_metric_date_text_vs_date_literal_fails_without_cast(text_metric_date_table):
    """
    FAILING TEST (pre-fix): metric_date TEXT = CURRENT_DATE (date) raises
    psycopg2.errors.UndefinedFunction in PostgreSQL (no implicit text=date cast).

    This reproduces the exact production defect that causes:
      UndefinedFunction: operator does not exist: text = date

    Verify-by-mutation: if this test starts PASSING without the fix applied,
    the test fixture is wrong (metric_date column is not TEXT, or PG version
    has an implicit cast — investigate before accepting).
    """
    table_name, conn = text_metric_date_table
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    with pytest.raises(psycopg2.errors.UndefinedFunction):
        cur.execute(_build_text_date_query(table_name))
        cur.fetchall()

    conn.rollback()  # Reset connection after expected error


def test_metric_date_cast_to_date_returns_todays_rows(text_metric_date_table):
    """
    PASSING TEST (post-fix): metric_date::date = CURRENT_DATE correctly returns
    today's rows when metric_date is stored as TEXT in ISO format (YYYY-MM-DD).

    This verifies the fix: casting the text column to date before comparing
    avoids the UndefinedFunction error and returns the expected rows.
    """
    table_name, conn = text_metric_date_table
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(_build_text_date_query_fixed(table_name))
    rows = [dict(r) for r in cur.fetchall()]

    assert len(rows) == 2, (
        f"expected 2 rows for today ({date.today().isoformat()}), got {len(rows)}: {rows}"
    )
    metric_names = {r["metric_name"] for r in rows}
    assert "gpu_health_ollama_ok" in metric_names, (
        f"expected gpu_health_ollama_ok in results, got: {metric_names}"
    )
    assert "gpu_health_training_ok" in metric_names, (
        f"expected gpu_health_training_ok in results, got: {metric_names}"
    )


def test_gpu_metrics_pg_query_uses_cast_on_text_metric_date(text_metric_date_table):
    """
    End-to-end regression: the actual GPU_METRICS_PG constant (as used by
    _pg_snapshot) must work when schedule_metrics.metric_date is TEXT.

    Creates a view aliasing the TEXT-column fixture table as 'schedule_metrics'
    so we can run the real GPU_METRICS_PG query unmodified against the text schema.

    This is the definitive guard: if GPU_METRICS_PG is reverted to the unfixed
    form, this test reproduces the production UndefinedFunction error.
    """
    from src.tools.tradingstate.queries import GPU_METRICS_PG

    table_name, conn = text_metric_date_table
    view_name = "schedule_metrics_text_view"

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Create a view so GPU_METRICS_PG's "FROM schedule_metrics" hits our
        # text-column table without touching the real schedule_metrics table.
        cur.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM {table_name}")
        conn.commit()

        # Swap the table reference in GPU_METRICS_PG to our view
        query = GPU_METRICS_PG.replace("schedule_metrics", view_name)

        cur.execute(query)
        rows = [dict(r) for r in cur.fetchall()]

        assert len(rows) == 2, (
            f"GPU_METRICS_PG against TEXT metric_date must return today's rows, "
            f"got {len(rows)}: {rows}"
        )
        metric_names = {r["metric_name"] for r in rows}
        assert "gpu_health_ollama_ok" in metric_names
        assert "gpu_health_training_ok" in metric_names

    finally:
        try:
            cur2 = conn.cursor()
            cur2.execute(f"DROP VIEW IF EXISTS {view_name}")
            conn.commit()
        except Exception:
            conn.rollback()

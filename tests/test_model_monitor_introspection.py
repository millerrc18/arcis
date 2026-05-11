"""Tests for model_monitor's engine-aware column introspection.

Sprint 5 §J5/§J6 Phase 2 T2.4 — Modified-A migration: replaces the inline
`PRAGMA table_info(recommendations)` call at src/evaluation/model_monitor.py
with `engine_aware_column_info(conn, 'recommendations')` so the
`has_canary` probe in `get_model_performance()` works against both SQLite
and Postgres.

Parametrized across `engine = ['sqlite', 'postgres']`. The Postgres variant
skips when `TEST_DATABASE_URL` is unset (mirroring the
test_db_engine_aware_introspection.py convention).

The test fixture creates a `recommendations` table with a `canary_score`
column added at fixture scope (the live registry has no canary_score —
the column was introduced at runtime by an earlier PR). Real paired
canary trades are inserted so the `has_canary=True` branch's SELECT
must succeed and the resulting `canary_comparison` reports
`paired_trades > 0`.

Before T2.4 the call site's column probe is `PRAGMA table_info(recommendations)`:
* SQLite: works → `has_canary=True` → SELECT runs → paired_trades > 0
* Postgres: raises psycopg2.errors.SyntaxError → swallowed by
  `except Exception: pass` → `has_canary=False` → SELECT never runs →
  paired_trades == 0

So the test FAILS on PG before T2.4 and PASSES on PG after T2.4.
"""

import os
import sqlite3
import tempfile

import psycopg2
import psycopg2.extras
import pytest


# ---------------------------------------------------------------------------
# Postgres detection mirroring test_db_engine_aware_introspection.py
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")
_PG_SKIP_REASON = "TEST_DATABASE_URL / DATABASE_URL not set or not postgres://"


# Number of paired canary trades inserted into each fixture.
_PAIRED_TRADE_COUNT = 3


# ---------------------------------------------------------------------------
# Bootstrap helpers — add canary_score + insert real paired data so the
# has_canary=True branch's SELECT returns rows.
# ---------------------------------------------------------------------------


def _seed_canary_rows_sql(template):
    """Return (recommendations_insert_sql, shadow_trade_insert_sql) using
    parameter style `template` ("?" for SQLite, "%s" for PG)."""
    p = template
    rec_sql = (
        f"INSERT INTO recommendations "
        f"(recommendation_id, ticker, created_at, llm_conviction, canary_score) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})"
    )
    st_sql = (
        f"INSERT INTO shadow_trades "
        f"(trade_id, recommendation_id, ticker, status, pnl_dollars, pnl_pct, "
        f"exit_reason, duration_days, actual_exit_time, created_at, updated_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
    )
    return rec_sql, st_sql


def _canary_rows():
    """Yield three paired (recommendations_row, shadow_trades_row) tuples.

    Each pair has a non-null llm_conviction AND canary_score so the
    `has_canary=True` SELECT in get_model_performance() includes them.
    """
    rows = []
    for i in range(_PAIRED_TRADE_COUNT):
        rec_id = f"r{i}"
        rec = (rec_id, "AAPL", f"2026-03-{20 + i:02d}", 7, 5)
        st = (
            f"t{i}", rec_id, "AAPL", "closed", 100.0, 2.0,
            "target_1", 3, f"2026-03-{22 + i:02d}",
            f"2026-03-{20 + i:02d}", f"2026-03-{22 + i:02d}",
        )
        rows.append((rec, st))
    return rows


def _bootstrap_sqlite_with_canary():
    """SQLite: registry tables + canary_score column + paired data.

    Returns (db_path, cleanup_fn).
    """
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    try:
        for tname in ("model_versions", "recommendations", "shadow_trades"):
            conn.executescript(generate_create_sql(TABLES[tname]))
        conn.execute("ALTER TABLE recommendations ADD COLUMN canary_score INTEGER")
        rec_sql, st_sql = _seed_canary_rows_sql("?")
        for rec, st in _canary_rows():
            conn.execute(rec_sql, rec)
            conn.execute(st_sql, st)
        conn.commit()
    finally:
        conn.close()

    def cleanup():
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return db_path, cleanup


def _bootstrap_pg_with_canary():
    """PG: registry tables + canary_score column + paired data.

    Returns (pg_url, cleanup_fn). Cleanup drops the bootstrapped tables.
    """
    from src.schema.registry import TABLES
    from src.schema.postgres import generate_create_sql

    table_names = ("model_versions", "recommendations", "shadow_trades")
    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw.autocommit = True
    cur = raw.cursor()
    for tname in reversed(table_names):
        cur.execute(f"DROP TABLE IF EXISTS {tname} CASCADE")
    for tname in table_names:
        cur.execute(generate_create_sql(TABLES[tname]))
    cur.execute("ALTER TABLE recommendations ADD COLUMN canary_score INTEGER")
    rec_sql, st_sql = _seed_canary_rows_sql("%s")
    for rec, st in _canary_rows():
        cur.execute(rec_sql, rec)
        cur.execute(st_sql, st)
    cur.close()
    raw.close()

    def cleanup():
        try:
            c = psycopg2.connect(TEST_PG_URL)
            c.autocommit = True
            cc = c.cursor()
            for tname in reversed(table_names):
                try:
                    cc.execute(f"DROP TABLE IF EXISTS {tname} CASCADE")
                except Exception:
                    pass
            cc.close()
            c.close()
        except Exception:
            pass

    return TEST_PG_URL, cleanup


# ---------------------------------------------------------------------------
# Test: get_model_performance reads the canary column list via the
# engine-aware helper on both engines, and the canary SELECT branch runs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_get_model_performance_detects_canary_column_on_both_engines(
    engine, monkeypatch
):
    """T2.4 — `has_canary` is decided via engine_aware_column_info.

    The fixture adds `canary_score` to `recommendations` and inserts
    three paired (recommendations, shadow_trades) rows with non-null
    llm_conviction AND canary_score, so the `has_canary=True` SELECT
    in get_model_performance() must return rows.

    Before T2.4:
      - SQLite: PRAGMA table_info works → has_canary=True → 3 paired rows
      - Postgres: PRAGMA raises SyntaxError, swallowed by `except: pass` →
        has_canary=False → SELECT not run → paired_trades == 0
        (TEST FAILS on PG before migration)

    After T2.4:
      - Both engines: engine_aware_column_info returns the column list →
        has_canary=True → SELECT runs → paired_trades == 3.
        (TEST PASSES on both engines)
    """
    from src.evaluation.model_monitor import get_model_performance

    if engine == "sqlite":
        db_path, cleanup = _bootstrap_sqlite_with_canary()
        try:
            monkeypatch.delenv("DATABASE_URL", raising=False)
            result = get_model_performance(db_path=db_path)
        finally:
            cleanup()
    else:
        if not _PG_AVAILABLE:
            pytest.skip(_PG_SKIP_REASON)
        pg_url, cleanup = _bootstrap_pg_with_canary()
        try:
            monkeypatch.setenv("DATABASE_URL", pg_url)
            from src.utils.db import connect_db as real_connect_db

            def _pg_connect_db(_db_path=None):
                return real_connect_db()  # sentinel → uses DATABASE_URL

            monkeypatch.setattr(
                "src.evaluation.model_monitor.connect_db",
                _pg_connect_db,
            )
            result = get_model_performance(db_path="ignored-by-monkeypatch")
        finally:
            cleanup()

    # Contract assertions
    assert isinstance(result, dict)
    assert "canary_comparison" in result
    cc = result["canary_comparison"]
    # T2.4 contract: has_canary must be True on both engines, the SELECT
    # must run, and the three paired rows must be reflected in the result.
    assert cc["paired_trades"] == _PAIRED_TRADE_COUNT, (
        f"engine={engine}: expected paired_trades={_PAIRED_TRADE_COUNT} "
        f"after T2.4 (column detected → SELECT executed), got {cc!r}"
    )

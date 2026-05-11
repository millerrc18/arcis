"""Tests for build_score _compute_phase_progress() excluding reconciled_stale.

Module: tests.evaluation.test_build_score
Purpose: Verify that the 50-trade gate progress counter in build_score.py
         excludes reconciled_stale rows from the closed trade count.
Called by: pytest
Owns tables: none
Config keys: none

Sprint 5 §J5/§J6 Phase 1 T1.10: tests for the engine_aware_upsert migration
of `persist_build_score()` against `build_score_history`.
"""

import os
import sqlite3
import unittest.mock as mock

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


def _db_from_conn(conn: sqlite3.Connection, tmp_path_str: str) -> str:
    """Write in-memory DB to a temp file and return path."""
    db_path = os.path.join(tmp_path_str, "build_score_test.sqlite3")
    backup = sqlite3.connect(db_path)
    conn.backup(backup)
    backup.close()
    return db_path


class TestBuildScorePhaseProgress:
    """build_score.py:296 — 50-trade gate progress counter excludes reconciled_stale."""

    def test_filter_active_progress_counter_excludes_stale(self, tmp_path):
        """10 normal + 5 stale: progress counter = 10, NOT 15."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            )
            closed = cur.fetchone()[0] or 0
        assert closed == 12, f"Expected 12 (10+2), got {closed}"

    def test_sanity_progress_counter_normal_only(self, tmp_path):
        """10 normal + 0 stale: progress counter = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            )
            closed = cur.fetchone()[0] or 0
        assert closed == 10


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 1 T1.10 — persist_build_score engine_aware_upsert dual-engine
# ---------------------------------------------------------------------------
#
# Test strategy (per T1.10 brief):
#   * Use a DETERMINISTIC score_id (NOT fresh UUID per call) so the replace
#     path is actually exercised. The production code at
#     src/evaluation/build_score.py:persist_build_score() calls
#     `str(uuid.uuid4())` per invocation, which makes INSERT OR REPLACE dead
#     code (every call is functionally an INSERT — see T0.12 audit §6.1).
#     The latent UUID-per-call dedup bug is a separate Sprint 5 follow-up.
#   * Parametrized across [sqlite, postgres] like
#     tests/test_db_engine_aware_upsert.py — PG path skips cleanly when
#     TEST_DATABASE_URL / DATABASE_URL is not a postgres:// URL.
#   * First insert lands the row; second insert with the same PK UPDATES
#     non-target columns (build_score, gate_velocity, etc.). This proves the
#     `engine_aware_upsert(action='replace')` helper works correctly when the
#     dedup key is stable, independent of the latent UUID-per-call bug.

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


def _build_sqlite_ddl(table_name):
    """Return the SQLite CREATE TABLE SQL for one of the audited tables."""
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
    """Return the Postgres CREATE TABLE SQL for one of the audited tables."""
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
    """Live psycopg2 wrapper. Skips if TEST_DATABASE_URL not set."""
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


def _setup_build_score_history(conn):
    """Drop+recreate `build_score_history` on whichever engine `conn` is for."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS build_score_history CASCADE")
        cur.execute(_build_pg_ddl("build_score_history"))
        conn.commit()
    else:
        conn.execute("DROP TABLE IF EXISTS build_score_history")
        conn.execute(_build_sqlite_ddl("build_score_history"))
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


class TestBuildScoreEngineAwareUpsert:
    """T1.10: build_score_history.engine_aware_upsert dual-engine coverage."""

    def test_engine_aware_upsert_first_insert_lands_row(self, conn_engine):
        """T1.10 #1: first insert against build_score_history lands the row.

        Uses a deterministic score_id so the second-insert test below can
        actually exercise the REPLACE conflict path. Note: production code
        in src/evaluation/build_score.py:persist_build_score() passes a
        fresh str(uuid.uuid4()) per call so REPLACE never fires there — that
        is the dead-code latent bug documented in the T0.12 audit §6.1, out
        of scope for T1.10. This test pins the helper's correctness when the
        dedup key is stable.
        """
        from src.utils.db import engine_aware_upsert

        conn = conn_engine
        _setup_build_score_history(conn)

        row = {
            "score_id": "fixed-test-score-id-001",
            "score_date": "2026-05-11",
            "build_score": 75.5,
            "gate_velocity": 50.0,
            "system_health": 80.0,
            "data_asset_value": 70.0,
            "model_quality": 85.0,
            "research_velocity": 60.0,
            "reliability": 90.0,
            "decay_applied": 0,
            "components_json": "{}",
            "created_at": "2026-05-11T10:00:00",
        }
        engine_aware_upsert(conn, "build_score_history", row, action="replace")
        conn.commit()

        assert _count_rows(conn, "build_score_history") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM build_score_history WHERE score_id=?",
            ("fixed-test-score-id-001",),
        )
        fetched = cur.fetchone()
        assert fetched["build_score"] == 75.5
        assert fetched["gate_velocity"] == 50.0

    def test_engine_aware_upsert_replace_updates_existing_row(self, conn_engine):
        """T1.10 #2: re-upserting the same score_id UPDATES non-target columns.

        Production code uses fresh UUIDs so this path is dead in practice;
        this test proves the helper's correctness when the dedup key is
        stable (a future bugfix could route the writer through score_date
        instead of a fresh UUID, at which point this is the actual semantics).
        """
        from src.utils.db import engine_aware_upsert

        conn = conn_engine
        _setup_build_score_history(conn)

        row1 = {
            "score_id": "fixed-test-score-id-002",
            "score_date": "2026-05-11",
            "build_score": 60.0,
            "gate_velocity": 40.0,
            "system_health": 70.0,
            "data_asset_value": 65.0,
            "model_quality": 75.0,
            "research_velocity": 55.0,
            "reliability": 80.0,
            "decay_applied": 0,
            "components_json": "{}",
            "created_at": "2026-05-11T10:00:00",
        }
        engine_aware_upsert(conn, "build_score_history", row1, action="replace")

        row2 = {
            "score_id": "fixed-test-score-id-002",  # same PK -> conflict
            "score_date": "2026-05-11",
            "build_score": 88.8,  # updated value
            "gate_velocity": 95.0,  # updated value
            "system_health": 90.0,
            "data_asset_value": 85.0,
            "model_quality": 92.0,
            "research_velocity": 78.0,
            "reliability": 95.0,
            "decay_applied": 1,
            "components_json": '{"updated": true}',
            "created_at": "2026-05-11T11:00:00",
        }
        engine_aware_upsert(conn, "build_score_history", row2, action="replace")
        conn.commit()

        assert _count_rows(conn, "build_score_history") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM build_score_history WHERE score_id=?",
            ("fixed-test-score-id-002",),
        )
        fetched = cur.fetchone()
        assert fetched["build_score"] == 88.8
        assert fetched["gate_velocity"] == 95.0
        assert fetched["decay_applied"] == 1
        assert fetched["components_json"] == '{"updated": true}'
        assert fetched["created_at"] == "2026-05-11T11:00:00"


class TestPersistBuildScoreUsesEngineAwareUpsert:
    """T1.10: end-to-end test that persist_build_score() uses the helper."""

    def test_persist_build_score_calls_engine_aware_upsert(self, tmp_path):
        """persist_build_score() must route the INSERT through engine_aware_upsert.

        Verifies via patching that the migration replaced the raw INSERT OR
        REPLACE site at src/evaluation/build_score.py:persist_build_score()
        with `engine_aware_upsert(conn, 'build_score_history', row, 'replace')`.
        """
        from tests.conftest import init_test_db

        db_path = str(tmp_path / "persist_test.sqlite3")
        init_test_db(db_path)

        with mock.patch("src.evaluation.build_score.engine_aware_upsert") as mocked:
            from src.evaluation.build_score import persist_build_score

            persist_build_score(db_path=db_path)

            assert mocked.call_count == 1
            call_args = mocked.call_args
            # Positional args: conn, table_name, row_dict; kw or pos: action
            assert call_args.args[1] == "build_score_history"
            row_dict = call_args.args[2]
            assert "score_id" in row_dict
            assert "score_date" in row_dict
            assert "build_score" in row_dict
            # action='replace' — may be positional or keyword
            action = call_args.kwargs.get("action")
            if action is None and len(call_args.args) >= 4:
                action = call_args.args[3]
            assert action == "replace"

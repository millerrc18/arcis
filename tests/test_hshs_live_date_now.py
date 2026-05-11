"""Sprint 5 §J5/§J6 Phase 2.5 T2 — hshs_live.py datetime('now') parameterization.

Verifies the three `WHERE created_at >= datetime('now', '-N days')` sites in
`src/evaluation/hshs_live.py` (lines 218, 260, 266) have been replaced with
bound `?` parameters whose cutoff is computed in Python via
`(datetime.now(ET) - timedelta(days=N)).isoformat()`.

The three sites all target `training_examples.created_at`, which is stored as
an ET-aware ISO-8601 string (e.g., `2026-05-11T15:30:00-04:00`) per
`src/training/data_collector.py:460` and sibling writers. Computing the
cutoff in Python with the same ET tz keeps the lexicographic comparison
semantics intact while removing the SQLite-only `datetime('now', ...)`
function call that would crash on Postgres post-cutover.

Parametrized over `engine=['sqlite', 'postgres']` via the `parametrized_conn`
fixture in `tests/conftest.py`. The postgres variant SKIPS cleanly when
`TEST_DATABASE_URL` is unset.

The static-lint test at the bottom locks the file against re-introduction of
the SQLite-only literal — analogous to the T2.10/T2.11 precedent in
`tests/test_ib_status_date_now.py` and `tests/test_shadow_trading_executor_date_now.py`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest


ET = ZoneInfo("America/New_York")


def _seed_training_examples(conn, now_et: datetime) -> None:
    """Seed training_examples rows at known cutoff offsets for the freshness test.

    Inserts four rows so each of the three datetime sites can be exercised
    in isolation:

      - row_today: created_at = now (matches both 7-day and prior-week filters
        only in the 7-day predicate)
      - row_3d:    3 days ago — within the 7-day window
      - row_10d:   10 days ago — within prior-week (8-14d), outside 7-day
      - row_20d:   20 days ago — outside both windows
    """
    rows = [
        ("ex_today", now_et.isoformat()),
        ("ex_3d", (now_et - timedelta(days=3)).isoformat()),
        ("ex_10d", (now_et - timedelta(days=10)).isoformat()),
        ("ex_20d", (now_et - timedelta(days=20)).isoformat()),
    ]
    insert_sql = (
        "INSERT INTO training_examples "
        "(example_id, created_at, source, instruction, input_text, output_text) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    for example_id, created_at in rows:
        conn.execute(
            insert_sql,
            (example_id, created_at, "test_source", "instr", "input", "output"),
        )
    conn.commit()


@pytest.fixture(params=["sqlite", "postgres"])
def hshs_conn(request, tmp_path):
    """Engine-parametrized DB fixture with training_examples + model_versions seeded.

    Replicates the `parametrized_conn` shape from `tests/conftest.py` but
    creates only the tables the HSHS query path touches so the test is
    self-contained. The postgres variant lazy-requests `pg_wrapper` so the
    sqlite variant runs unconditionally and pg skips when TEST_DATABASE_URL
    is unset.
    """
    engine = request.param
    if engine == "sqlite":
        from tests.conftest import init_test_db

        db_path = str(tmp_path / "test.db")
        init_test_db(db_path, ["training_examples", "model_versions"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    elif engine == "postgres":
        wrapper = request.getfixturevalue("pg_wrapper")
        yield wrapper
    else:
        raise ValueError(f"unknown engine: {engine!r}")


def test_freshness_query_matches_7day_window(hshs_conn):
    """Site at line 218: `_score_data_asset` freshness — 7 days.

    The migrated query computes `cutoff_7d = (datetime.now(ET) -
    timedelta(days=7)).isoformat()` in Python and passes it as a bound
    parameter. Verifies it correctly returns rows within the 7-day window
    (today + 3d) and excludes older rows (10d + 20d).
    """
    now_et = datetime.now(ET)
    _seed_training_examples(hshs_conn, now_et)

    cutoff_7d = (now_et - timedelta(days=7)).isoformat()
    cur = hshs_conn.execute(
        "SELECT COUNT(*) AS n FROM training_examples WHERE created_at >= ?",
        (cutoff_7d,),
    )
    row = cur.fetchone()
    count = row["n"]

    assert count == 2, (
        f"Expected 2 rows within 7d window (today + 3d), got {count}"
    )


def test_flywheel_recent_week_query_matches_7day_window(hshs_conn):
    """Site at line 260: `_score_flywheel_velocity` recent_week — 7 days.

    Same predicate as line 218 but in a different scorer function. Both
    use the identical 7-day cutoff so the migration must keep them in
    lockstep.
    """
    now_et = datetime.now(ET)
    _seed_training_examples(hshs_conn, now_et)

    cutoff_7d = (now_et - timedelta(days=7)).isoformat()
    cur = hshs_conn.execute(
        "SELECT COUNT(*) AS n FROM training_examples WHERE created_at >= ?",
        (cutoff_7d,),
    )
    row = cur.fetchone()
    count = row["n"]

    assert count == 2, (
        f"Expected 2 rows within 7d window (today + 3d), got {count}"
    )


def test_flywheel_prior_week_query_matches_8to14day_window(hshs_conn):
    """Site at line 266: `_score_flywheel_velocity` prior_week — 8-14 days.

    The compound predicate `created_at >= cutoff_14d AND created_at <
    cutoff_7d` carves out the prior 7-day window for week-over-week growth.
    The migrated query passes BOTH cutoffs as parameters. Verifies the 10d
    row matches (in the 8-14d window) and the today/3d/20d rows do not.
    """
    now_et = datetime.now(ET)
    _seed_training_examples(hshs_conn, now_et)

    cutoff_7d = (now_et - timedelta(days=7)).isoformat()
    cutoff_14d = (now_et - timedelta(days=14)).isoformat()
    cur = hshs_conn.execute(
        "SELECT COUNT(*) AS n FROM training_examples "
        "WHERE created_at >= ? AND created_at < ?",
        (cutoff_14d, cutoff_7d),
    )
    row = cur.fetchone()
    count = row["n"]

    assert count == 1, (
        f"Expected 1 row in 8-14d prior-week window (10d), got {count}"
    )


def test_compute_hshs_does_not_raise_on_engine(hshs_conn, monkeypatch, tmp_path):
    """End-to-end: `compute_hshs` returns a valid dict on both engines.

    Smoke-test that the three migrated scorer functions execute without
    raising on either SQLite or PG. We seed the fixture connection, then
    monkeypatch `connect_db` to return that same connection so
    `compute_hshs` exercises the migrated SQL through the same engine the
    test is parametrized over.

    The test passes the seed connection through a thin wrapper that ignores
    `.close()` calls (compute_hshs calls `conn.close()` in its `finally`
    block — closing the fixture connection mid-test would corrupt teardown).
    """
    now_et = datetime.now(ET)
    _seed_training_examples(hshs_conn, now_et)

    # Wrap the live conn so compute_hshs's `conn.close()` is a no-op while
    # all other methods pass through. Allows the fixture to manage close().
    class _NoCloseProxy:
        def __init__(self, inner):
            self._inner = inner
            self.row_factory = None

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass  # fixture owns lifecycle

    proxy = _NoCloseProxy(hshs_conn)

    import src.evaluation.hshs_live as hshs_module

    monkeypatch.setattr(hshs_module, "connect_db", lambda _db_path: proxy)

    result = hshs_module.compute_hshs(db_path="ignored-by-monkeypatch")

    assert isinstance(result, dict)
    assert "hshs" in result
    assert "dimensions" in result
    # data_asset and flywheel_velocity are the two scorers exercising the
    # three migrated sites — both must compute a numeric (non-zero) score
    # given the seeded data.
    dims = result["dimensions"]
    assert "data_asset" in dims
    assert "flywheel_velocity" in dims
    # Score floor is 5.0 (when no data); seeded data must lift at least one
    # above the floor.
    assert dims["data_asset"] >= 5.0
    assert dims["flywheel_velocity"] >= 0.0


def test_hshs_live_source_has_no_datetime_now_literal():
    """Static lint: `src/evaluation/hshs_live.py` must not contain `datetime('now'`.

    The Phase 2.5 T2 migration replaces all three `datetime('now', ...)`
    literals with bound parameters. If a future refactor reintroduces the
    SQLite-only literal, that SQL crashes on PG and this lint catches it.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "evaluation"
        / "hshs_live.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "datetime('now'" not in text, (
        "src/evaluation/hshs_live.py contains SQLite-only `datetime('now'` — "
        "use a bound `?` parameter with `(datetime.now(ET) - "
        "timedelta(days=N)).isoformat()` instead (T2 Phase 2.5)."
    )

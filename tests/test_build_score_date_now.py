"""Sprint 5 §J5/§J6 Phase 2.5 T1 — build_score.py datetime('now') parameterization.

Verifies the 4 SQLite-only ``datetime('now', '-N days')`` literals in
``src/evaluation/build_score.py`` at lines 151, 163, 408, 432 have been
replaced with bound ``?`` parameters carrying a Python-computed cutoff
timestamp. Previously the SQL used SQLite's ``datetime('now', '-30 days')``
or ``datetime('now', '-90 days')`` time-shift; Postgres rejects this with
a syntax error (``function datetime(unknown, unknown) does not exist``).
The Phase 2.5 rewrite shifts cutoff computation to Python so the same SQL
works on both engines unchanged.

Parametrized over ``engine=['sqlite', 'postgres']`` via the
``parametrized_conn`` fixture in ``tests/conftest.py``. The postgres
variant SKIPS cleanly when ``TEST_DATABASE_URL`` is unset (operator
laptops, CI without a test PG instance).

The four sites are:
  - Line 151 (now ~155): ``_score_data_asset_value`` 30-day quality cutoff
  - Line 163 (now ~167): ``_score_data_asset_value`` 90-day freshness cutoff
  - Line 408 (now ~412): ``_build_data_detail`` 30-day quality cutoff
  - Line 432 (now ~436): ``_build_data_detail`` 90-day freshness cutoff

All four read ``training_examples.created_at``, which production writes
as ``datetime.now(ET).isoformat()`` (ET = America/New_York, per
``src/training/data_collector.py:460``). The migrated cutoffs must use
the same ET semantics so the ``>=`` comparison is consistent.
"""
from __future__ import annotations

import inspect
import pathlib
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest


ET = ZoneInfo("America/New_York")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_training_examples_for_cutoff(conn, days: int) -> tuple[int, str, str]:
    """Insert one fresh and one stale row keyed on the ``days`` cutoff.

    Returns (rows_inserted, fresh_created_at, stale_created_at).
    Fresh row uses ``now``; stale uses ``now - (days + 1) days`` so it
    falls strictly outside the cutoff window. ``example_id`` is uuid4 so
    repeated calls within the same test don't collide on the PK.
    """
    now = datetime.now(ET)
    fresh_at = now.isoformat()
    stale_at = (now - timedelta(days=days + 1)).isoformat()

    rows = [
        # (example_id, created_at, source, quality_score, regime, ticker, ...)
        (str(uuid.uuid4()), fresh_at, "outcome_win", 25.0, "strong_bull", "AAPL"),
        (str(uuid.uuid4()), stale_at, "outcome_win", 25.0, "strong_bull", "AAPL"),
    ]
    for row in rows:
        conn.execute(
            "INSERT INTO training_examples "
            "(example_id, created_at, source, quality_score, regime, ticker, "
            "instruction, input_text, output_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*row, "inst", "in", "out"),
        )
    conn.commit()
    return len(rows), fresh_at, stale_at


# ── Cross-engine functional tests for the 4 migrated sites ────────────────────


def test_data_asset_value_quality_30day_cutoff(parametrized_conn):
    """Line ~155 (was 151): 30-day quality cutoff filters out stale rows.

    AVG(quality_score) WHERE quality_score IS NOT NULL AND created_at >= ?
    bound to ``(datetime.now(ET) - timedelta(days=30)).isoformat()``.

    Seed: one fresh row (today) + one stale row (31 days ago). Assert the
    query returns only the fresh row by checking the AVG matches the
    fresh row's quality_score (the stale row would change the average if
    it were included).
    """
    conn = parametrized_conn
    _seed_training_examples_for_cutoff(conn, days=30)

    cutoff = (datetime.now(ET) - timedelta(days=30)).isoformat()
    # AS aliases so PG's RealDictCursor and SQLite's Row both expose named
    # access (the wrapper does not provide positional `[0]` access on PG).
    cur = conn.execute(
        "SELECT AVG(quality_score) AS avg_q FROM training_examples "
        "WHERE quality_score IS NOT NULL AND created_at >= ?",
        (cutoff,),
    )
    row = cur.fetchone()
    avg_q = row["avg_q"]
    assert avg_q is not None
    # Both rows have quality_score=25.0 so any inclusion error would still
    # produce 25.0; rely on count-of-included-rows to catch a bad cutoff.
    cur = conn.execute(
        "SELECT COUNT(*) AS n FROM training_examples "
        "WHERE quality_score IS NOT NULL AND created_at >= ?",
        (cutoff,),
    )
    matched = cur.fetchone()["n"]
    assert matched == 1, (
        f"Expected exactly 1 fresh row to match the 30-day cutoff, got {matched}"
    )


def test_data_asset_value_freshness_90day_cutoff(parametrized_conn):
    """Line ~167 (was 163): 90-day freshness cutoff filters out stale rows.

    COUNT(*) WHERE created_at >= (now - 90 days). Seed: fresh + 91-days-old.
    Assert only the fresh row is counted.
    """
    conn = parametrized_conn
    _seed_training_examples_for_cutoff(conn, days=90)

    cutoff = (datetime.now(ET) - timedelta(days=90)).isoformat()
    cur = conn.execute(
        "SELECT COUNT(*) AS n FROM training_examples WHERE created_at >= ?",
        (cutoff,),
    )
    matched = cur.fetchone()["n"]
    assert matched == 1, (
        f"Expected exactly 1 fresh row to match the 90-day cutoff, got {matched}"
    )


def test_compute_build_score_runs_against_both_engines(parametrized_conn):
    """Integration: ``_score_data_asset_value`` + ``_build_data_detail`` run
    successfully against both engines without raising SQLite syntax errors.

    This is the end-to-end regression check — if any of the 4 migrated
    sites still contained ``datetime('now', ...)``, the PG variant would
    raise ``psycopg2.errors.UndefinedFunction`` here.
    """
    from src.evaluation import build_score as bs

    # Seed: a few rows so the scorers have data to work with.
    _seed_training_examples_for_cutoff(parametrized_conn, days=30)
    _seed_training_examples_for_cutoff(parametrized_conn, days=90)

    # Both functions must execute end-to-end. Their return values are
    # validated by other tests; here we only assert they don't raise.
    quality_blended = bs._score_data_asset_value(parametrized_conn)
    assert isinstance(quality_blended, float)
    assert 0.0 <= quality_blended <= 100.0

    detail = bs._build_data_detail(parametrized_conn)
    assert isinstance(detail, dict)
    assert set(detail.keys()) == {"quality", "diversity", "freshness"}


# ── Static regression-lint guards ─────────────────────────────────────────────


def test_build_score_does_not_use_sqlite_datetime_now_function():
    """Static lint: build_score.py must not regress to SQLite's ``datetime('now')``.

    Sprint 5 §J5/§J6 Phase 2.5 T1 — the rewritten queries parameterize the
    cutoff timestamps so the SQL is engine-agnostic. If a future refactor
    reintroduces ``datetime('now')``, that SQL crashes on PG and this lint
    catches it before the post-cutover smoke does.
    """
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src" / "evaluation" / "build_score.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "datetime('now'" not in text, (
        "src/evaluation/build_score.py contains SQLite-only "
        "``datetime('now', ...)`` — use a bound ``?`` parameter with "
        "``(datetime.now(ET) - timedelta(days=N)).isoformat()`` instead "
        "(Sprint 5 §J5/§J6 Phase 2.5 T1)."
    )
    # Sibling-scan: also confirm no `date('now')` or `julianday(` regressions.
    assert "date('now'" not in text, (
        "src/evaluation/build_score.py contains SQLite-only ``date('now', ...)``"
    )
    assert "julianday(" not in text, (
        "src/evaluation/build_score.py contains SQLite-only ``julianday(``"
    )


def test_build_score_source_uses_python_cutoffs():
    """Static guard: the migrated cutoff pattern is present in build_score.py.

    Confirms the file uses ``datetime.now(ET) - timedelta(days=...)`` for
    cutoff computation (the established T2.9/T2.10/T2.11 pattern), so
    accidentally removing the migration in a future refactor would fail
    this check.
    """
    from src.evaluation import build_score as bs

    source = inspect.getsource(bs)
    # The migration pattern is well-established by Phase 2 — at least one
    # ``timedelta(days=30)`` and one ``timedelta(days=90)`` cutoff must be
    # present (matching the 30-day quality + 90-day freshness windows).
    assert "timedelta(days=30)" in source, (
        "build_score.py missing the 30-day Python cutoff — the "
        "datetime('now', '-30 days') sites should be replaced with "
        "(datetime.now(ET) - timedelta(days=30)).isoformat()"
    )
    assert "timedelta(days=90)" in source, (
        "build_score.py missing the 90-day Python cutoff — the "
        "datetime('now', '-90 days') sites should be replaced with "
        "(datetime.now(ET) - timedelta(days=90)).isoformat()"
    )

"""Sprint 5 §J5/§J6 Phase 2.5 T4 — cross-engine `WHERE created_at >= cutoff`.

Verifies that the SQLite-only `datetime('now', '-1 day')` literal at
``src/council/context.py:30`` has been replaced with a parameterized
cutoff computed in Python.

The migration target: the recommendations-count query in
``build_shared_context`` no longer embeds ``datetime('now', '-1 day')``
in the SQL — it passes ``(datetime.now(ET) - timedelta(days=1)).isoformat()``
as a bound parameter. The wrapper rewrites ``?`` → ``%s`` for psycopg2,
so the same SQL works on both engines.

Parametrized over [sqlite, postgres]. The Postgres variant skips cleanly
when ``TEST_DATABASE_URL`` is unset (operator laptops, CI without a test
PG instance).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest


ET = ZoneInfo("America/New_York")

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_PG_URL.startswith("postgres"):
    # Fall back to constructing from DOCKER_PG_PASSWORD per task brief:
    # postgresql://halcyon:$DOCKER_PG_PASSWORD@127.0.0.1:5433/halcyon
    try:
        from dotenv import dotenv_values

        env = dotenv_values("C:/arcis/halcyon-lab/.env")
        _pw = env.get("DOCKER_PG_PASSWORD") or os.environ.get(
            "DOCKER_PG_PASSWORD"
        )
        if _pw:
            TEST_PG_URL = (
                f"postgresql://halcyon:{_pw}@127.0.0.1:5433/halcyon"
            )
    except ImportError:
        pass
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


def _seed_recommendation(
    conn, *, rec_id: str, created_at: str, priority_score: float,
    placeholder: str = "?",
):
    """Insert a recommendation row with the given created_at + score."""
    conn.execute(
        f"INSERT INTO recommendations "
        f"(recommendation_id, created_at, ticker, priority_score) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
        (rec_id, created_at, "AAPL", priority_score),
    )


@pytest.fixture
def sqlite_db():
    """SQLite tmp database with `recommendations` provisioned + 2 rows seeded."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["recommendations"])

    conn = sqlite3.connect(path)
    try:
        now = datetime.now(ET)
        recent_iso = (now - timedelta(hours=6)).isoformat()  # within 1 day
        old_iso = (now - timedelta(days=5)).isoformat()     # outside 1 day
        _seed_recommendation(
            conn, rec_id=str(uuid.uuid4()), created_at=recent_iso,
            priority_score=80.0,
        )
        _seed_recommendation(
            conn, rec_id=str(uuid.uuid4()), created_at=old_iso,
            priority_score=20.0,
        )
        conn.commit()
    finally:
        conn.close()
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


@pytest.fixture
def pg_db():
    """Live PG connection bootstrapped with the tables build_shared_context queries.

    Skips when TEST_DATABASE_URL is unset (operator laptops, CI without
    docker PG). Cleans up created tables on teardown.
    """
    if not _PG_AVAILABLE:
        pytest.skip(
            "TEST_DATABASE_URL not set or not postgres://"
        )

    import psycopg2
    import psycopg2.extras

    from src.schema.postgres import generate_create_sql as pg_generate_create_sql
    from src.schema.registry import TABLES
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw.autocommit = True
    cur = raw.cursor()
    # Tables build_shared_context queries — without all of them, an earlier
    # query (vix, traffic_light) hits UndefinedTable and the PG implicit
    # transaction aborts, breaking the recommendations query under test.
    needed = (
        "recommendations",
        "shadow_trades",
        "traffic_light_state",
        "vix_term_structure",
    )
    for tname in needed:
        cur.execute(f"DROP TABLE IF EXISTS {tname} CASCADE")
        cur.execute(pg_generate_create_sql(TABLES[tname]))
    cur.close()

    raw.autocommit = False
    wrapper = PostgresConnectionWrapper(raw)
    try:
        now = datetime.now(ET)
        recent_iso = (now - timedelta(hours=6)).isoformat()
        old_iso = (now - timedelta(days=5)).isoformat()
        _seed_recommendation(
            wrapper, rec_id=str(uuid.uuid4()), created_at=recent_iso,
            priority_score=80.0,
        )
        _seed_recommendation(
            wrapper, rec_id=str(uuid.uuid4()), created_at=old_iso,
            priority_score=20.0,
        )
        raw.commit()
        yield wrapper
    finally:
        try:
            raw.rollback()
        except Exception:
            pass
        try:
            raw.autocommit = True
            cleanup = raw.cursor()
            for tname in reversed(needed):
                cleanup.execute(f"DROP TABLE IF EXISTS {tname} CASCADE")
            cleanup.close()
        except Exception:
            pass
        wrapper.close()


@pytest.fixture(params=["sqlite", "postgres"])
def shared_context_engine(request, monkeypatch):
    """Yields the shared-context output produced against each engine.

    For 'sqlite': calls `build_shared_context(db_path=sqlite_path)` directly
    — `connect_db` resolves to SQLite via the explicit-db_path precedence.

    For 'postgres': monkeypatches `connect_db` inside `src.council.agents`
    (where `_query_db` imports it) so the call inside the SUT resolves to
    the live PG wrapper regardless of the db_path argument the test passes.
    """
    from src.council import context as ctx_mod

    engine = request.param
    if engine == "sqlite":
        sqlite_path = request.getfixturevalue("sqlite_db")
        yield ctx_mod.build_shared_context(db_path=sqlite_path)
        return

    if engine == "postgres":
        wrapper = request.getfixturevalue("pg_db")

        def _patched_connect_db(db_path=None):
            return wrapper

        monkeypatch.setattr(
            "src.utils.db.connect_db", _patched_connect_db
        )
        # _query_db lives in src.council.agent_data; both context.py and
        # agents.py route through it. Patch its imported `connect_db`.
        monkeypatch.setattr(
            "src.council.agent_data.connect_db", _patched_connect_db
        )
        # context.py:69-79 calls sqlite3.connect(db_path) directly for the
        # traffic_light query — bypassing connect_db. Use a tmp path so the
        # side-effect SQLite file doesn't litter the repo root.
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(tmp_fd)
        try:
            yield ctx_mod.build_shared_context(db_path=tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except PermissionError:
                pass  # Windows file locking — cleaned up on next reboot
        return

    raise ValueError(f"unknown engine: {engine}")


def test_today_count_only_recent_row_matches(shared_context_engine):
    """T4: parameterized 1-day cutoff matches only the recent row on both engines.

    Two recommendations are seeded: one 6 hours ago (within window), one
    5 days ago (outside window). The migrated query in
    `build_shared_context` must count exactly 1 candidate with avg_score
    ~= 80.0.
    """
    output = shared_context_engine
    assert isinstance(output, str)
    # Recent-only count of 1, avg score ~80.0 → expected output substring:
    # "Today's scan: 1 candidates, avg score 80.0"
    assert "Today's scan: 1 candidates" in output, (
        f"Expected 1-candidate count in scan output; got: {output}"
    )
    assert "avg score 80.0" in output, (
        f"Expected avg score 80.0 in scan output; got: {output}"
    )


def test_context_source_has_no_sqlite_date_now_literal():
    """Static-analysis guard: confirm `datetime('now')` no longer appears in SQL.

    Mirrors the T2.9 precedent (test_council_agent_data_julianday.py): only
    flags occurrences in a SQL context (lines that also contain SQL
    keywords like SELECT/FROM/WHERE). Mentions in docstrings/comments
    referring to the historical pattern are fine — the AST scanner in
    tests/test_no_sqlite_isms_in_pg_safe_files.py enforces the
    higher-rigor execute()-argument check.
    """
    import inspect
    import re

    import src.council.context as ctx_mod

    source = inspect.getsource(ctx_mod)
    sql_kw_pat = re.compile(r"\b(SELECT|FROM|WHERE|GROUP|ORDER|HAVING)\b")

    forbidden = [
        line for line in source.splitlines()
        if (
            ("datetime('now'" in line or "date('now'" in line)
            and sql_kw_pat.search(line)
        )
    ]
    assert not forbidden, (
        "src/council/context.py still contains a SQLite-only date('now') / "
        "datetime('now') literal in a SQL context — Phase 2.5 T4 must "
        "replace it with a parameterized cutoff computed in Python. "
        f"Offending lines: {forbidden}"
    )

"""Sprint 5 §J5/§J6 Phase 2.5 T3 — cross-engine date('now') / datetime('now') migration.

Called by: pytest (Sprint 5 Phase 2.5)
Calls: src.council.agent_data.gather_risk_data, gather_macro_data
Owns tables: none
Config keys: TEST_DATABASE_URL (optional — postgres variant skips when unset)
Tests: self

Verifies that the SQLite-only `datetime('now', '-7 days')` and
`date('now', '-365 days')` calls at src/council/agent_data.py:272 (in
gather_risk_data) and :451 (in gather_macro_data) have been replaced
with cross-engine Python-side date arithmetic. Each test seeds two rows
— one fresh (inside the cutoff) and one stale (outside the cutoff) —
and asserts the SUT's downstream computation reflects ONLY the fresh
row (the SQL WHERE clause filtered correctly on both engines).

Sibling test to tests/test_council_agent_data_julianday.py (T2.9) which
covers the julianday() site at :91. Each test file is scoped to one
date-function family for focus.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
import pytest

from src.council.agent_data import gather_macro_data, gather_risk_data
from src.schema.postgres import generate_create_sql as pg_generate_create_sql
from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql as sqlite_generate_create_sql

ET = ZoneInfo("America/New_York")


def _seed_scan_metrics(conn, *, days_ago: int, llm_success: int, llm_total: int,
                       placeholder: str = "?"):
    """Insert a scan_metrics row whose created_at is `days_ago` from now (ET)."""
    created_at = (datetime.now(ET) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        f"INSERT INTO scan_metrics "
        f"(scan_number, scan_time, packet_worthy, llm_success, llm_total, "
        f"avg_conviction, created_at) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
        f"{placeholder}, {placeholder}, {placeholder})",
        (1, created_at, 5, llm_success, llm_total, 7.5, created_at),
    )


def _seed_macro_snapshot(conn, *, days_ago: int, value: float,
                        placeholder: str = "?"):
    """Insert a macro_snapshots row for HY OAS `days_ago` from now (ET)."""
    collected = (datetime.now(ET) - timedelta(days=days_ago))
    collected_at = collected.isoformat()
    collected_date = collected.date().isoformat()
    conn.execute(
        f"INSERT INTO macro_snapshots "
        f"(collected_at, collected_date, series_id, series_name, value) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
        f"{placeholder})",
        (collected_at, collected_date, "BAMLH0A0HYM2", "HY OAS", value),
    )


# ── SQLite fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sqlite_db_risk(tmp_path):
    """SQLite DB seeded for gather_risk_data 7-day fallback rate test.

    Inserts one FRESH (2 days ago) scan_metrics row and one STALE (10 days
    ago) row. If the WHERE clause filters correctly, only the fresh row is
    included in the 7-day aggregate; if the WHERE clause is broken or
    fires on PG and returns NO rows, the test catches it.
    """
    db_path = str(tmp_path / "agent_data_risk.sqlite3")
    conn = sqlite3.connect(db_path)
    try:
        for tdef in TABLES.values():
            conn.executescript(sqlite_generate_create_sql(tdef))
        # FRESH: 2 days ago, llm_total=10, llm_success=8 → fallback 20%.
        _seed_scan_metrics(conn, days_ago=2, llm_success=8, llm_total=10)
        # STALE: 10 days ago, llm_total=100, llm_success=0 → would be
        # fallback 100% if it leaked into the aggregate.
        _seed_scan_metrics(conn, days_ago=10, llm_success=0, llm_total=100)
        conn.commit()
    finally:
        conn.close()
    yield db_path


@pytest.fixture
def sqlite_db_macro(tmp_path):
    """SQLite DB seeded for gather_macro_data 365-day HY-OAS z-score test.

    Inserts one FRESH (10 days ago) HY OAS row plus one STALE (500 days
    ago) row with a wildly different value. The 365-day window should
    average ONLY the fresh row's value; the stale row would skew the
    average if the WHERE clause is broken.

    Also seeds a "latest" row at 1 day ago so the `ORDER BY collected_date
    DESC LIMIT 1` call in the SUT picks a known value for the z-score
    numerator.
    """
    db_path = str(tmp_path / "agent_data_macro.sqlite3")
    conn = sqlite3.connect(db_path)
    try:
        for tdef in TABLES.values():
            conn.executescript(sqlite_generate_create_sql(tdef))
        # LATEST: 1 day ago, value 4.0 — picked by the first SELECT.
        _seed_macro_snapshot(conn, days_ago=1, value=4.0)
        # FRESH: 10 days ago, value 4.0 — should be in the 365d average.
        _seed_macro_snapshot(conn, days_ago=10, value=4.0)
        # STALE: 500 days ago, value 99.0 — would massively skew z-score
        # if the 365d WHERE clause leaks.
        _seed_macro_snapshot(conn, days_ago=500, value=99.0)
        conn.commit()
    finally:
        conn.close()
    yield db_path


# ── Postgres fixtures ────────────────────────────────────────────────────────


def _resolve_test_database_url() -> str | None:
    """Return TEST_DATABASE_URL or construct from DOCKER_PG_PASSWORD per task brief."""
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if test_database_url:
        return test_database_url
    try:
        from dotenv import dotenv_values
        env = dotenv_values("C:/arcis/halcyon-lab/.env")
        pg_password = env.get("DOCKER_PG_PASSWORD") or os.environ.get("DOCKER_PG_PASSWORD")
        if pg_password:
            return f"postgresql://halcyon:{pg_password}@127.0.0.1:5433/halcyon"
    except ImportError:
        pass
    return None


@pytest.fixture
def pg_db_risk():
    """Postgres DB seeded for gather_risk_data; skips if TEST_DATABASE_URL unset.

    Same shape as sqlite_db_risk: one fresh row (2d) + one stale (10d).
    Bootstraps the union of tables `gather_risk_data` queries so partial
    schema doesn't abort the implicit transaction.
    """
    test_database_url = _resolve_test_database_url()
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; postgres variant cannot run")

    raw_conn = psycopg2.connect(
        test_database_url, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw_conn.autocommit = True
    created_tables: list[str] = []
    try:
        cur = raw_conn.cursor()
        # Tables `gather_risk_data` queries — keep partial-schema bug at bay.
        for table_name in (
            "scan_metrics",
            "shadow_trades",
            "recommendations",
        ):
            tdef = TABLES[table_name]
            cur.execute(pg_generate_create_sql(tdef))
            created_tables.append(tdef.name)
        for table_name in ("scan_metrics", "shadow_trades", "recommendations"):
            cur.execute(f"DELETE FROM {table_name}")
        cur.close()
    except Exception:
        raw_conn.close()
        raise

    from src.utils.db import PostgresConnectionWrapper

    wrapper = PostgresConnectionWrapper(raw_conn)
    raw_conn.autocommit = False
    try:
        _seed_scan_metrics(wrapper, days_ago=2, llm_success=8, llm_total=10)
        _seed_scan_metrics(wrapper, days_ago=10, llm_success=0, llm_total=100)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raw_conn.close()
        raise

    yield test_database_url, raw_conn, created_tables

    try:
        raw_conn.rollback()
    except Exception:
        pass
    try:
        raw_conn.autocommit = True
        cleanup_cur = raw_conn.cursor()
        for name in reversed(created_tables):
            try:
                cleanup_cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
            except Exception:
                pass
        cleanup_cur.close()
    finally:
        raw_conn.close()


@pytest.fixture
def pg_db_macro():
    """Postgres DB seeded for gather_macro_data; skips if TEST_DATABASE_URL unset."""
    test_database_url = _resolve_test_database_url()
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; postgres variant cannot run")

    raw_conn = psycopg2.connect(
        test_database_url, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw_conn.autocommit = True
    created_tables: list[str] = []
    try:
        cur = raw_conn.cursor()
        for table_name in (
            "macro_snapshots",
            "shadow_trades",
            "recommendations",
        ):
            tdef = TABLES[table_name]
            cur.execute(pg_generate_create_sql(tdef))
            created_tables.append(tdef.name)
        for table_name in ("macro_snapshots", "shadow_trades", "recommendations"):
            cur.execute(f"DELETE FROM {table_name}")
        cur.close()
    except Exception:
        raw_conn.close()
        raise

    from src.utils.db import PostgresConnectionWrapper

    wrapper = PostgresConnectionWrapper(raw_conn)
    raw_conn.autocommit = False
    try:
        _seed_macro_snapshot(wrapper, days_ago=1, value=4.0)
        _seed_macro_snapshot(wrapper, days_ago=10, value=4.0)
        _seed_macro_snapshot(wrapper, days_ago=500, value=99.0)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raw_conn.close()
        raise

    yield test_database_url, raw_conn, created_tables

    try:
        raw_conn.rollback()
    except Exception:
        pass
    try:
        raw_conn.autocommit = True
        cleanup_cur = raw_conn.cursor()
        for name in reversed(created_tables):
            try:
                cleanup_cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
            except Exception:
                pass
        cleanup_cur.close()
    finally:
        raw_conn.close()


# ── Source-level guard ───────────────────────────────────────────────────────


def test_no_sqlite_date_function_call_in_agent_data():
    """No `datetime('now'` / `date('now'` SQL function in agent_data source.

    Source-level guard mirroring T2.9's `julianday(` check. Mentions in
    docstrings/comments are allowed; only the SQL function call form is
    forbidden. Detects lines containing the fragment alongside any common
    SQL keyword (SELECT/FROM/WHERE/AND/AS/CAST).
    """
    import inspect
    import re

    import src.council.agent_data as agent_data_mod

    source = inspect.getsource(agent_data_mod)
    forbidden: list[str] = []
    for line in source.splitlines():
        if re.search(r"datetime\s*\(\s*['\"]now['\"]", line) or re.search(
            r"\bdate\s*\(\s*['\"]now['\"]", line
        ):
            if re.search(r"\b(SELECT|FROM|WHERE|AND|AS\s+\w+|CAST)\b", line):
                forbidden.append(line.strip())
    assert not forbidden, (
        "src/council/agent_data.py still contains SQLite-only date('now') / "
        "datetime('now') in a SQL context — must be replaced with cross-engine "
        "Python-side date arithmetic (Sprint 5 Phase 2.5 T3). Offending lines: "
        f"{forbidden}"
    )


# ── SQLite happy-path tests ──────────────────────────────────────────────────


def test_gather_risk_data_7day_fallback_sqlite(sqlite_db_risk):
    """7-day fallback aggregate excludes the 10-day-old stale row on SQLite."""
    result = gather_risk_data(sqlite_db_risk)
    assert isinstance(result, str)
    # FRESH row: llm_total=10, llm_success=8 → fallback rate (1 - 8/10)*100 = 20.0%.
    # If the stale row (100/0) leaks in, the aggregate becomes
    # (10 + 100 - 8 - 0) / (10 + 100) * 100 ≈ 92.7% which would not match "20.0%".
    assert "20.0%" in result, (
        f"Expected 7-day fallback rate of 20.0% from the fresh row alone, "
        f"got: {result}"
    )


def test_gather_macro_data_365d_zscore_sqlite(sqlite_db_macro):
    """HY OAS 365-day average excludes the 500-day-old stale row on SQLite."""
    result = gather_macro_data(sqlite_db_macro)
    assert isinstance(result, str)
    # Latest row value=4.0; 365d average over [latest=4, 10d=4] = 4.0.
    # z = (4.0 - 4.0) / max(0.1, abs(4.0 * 0.15)) = 0.0 → status "tight"
    # (z < 0 is tight, but our z is 0.0, so > 0 → "normal" if z < 1).
    # Per the SUT's literal: z<0 → tight, z<1 → normal. z=0.0 hits "normal".
    # If the 500d stale (99.0) leaks: avg ≈ (4 + 4 + 99) / 3 = 35.67,
    # z = (4 - 35.67) / max(0.1, 5.35) = -5.92 → "tight" (negative).
    assert "Credit: normal" in result, (
        f"Expected 'Credit: normal' from a tight z-score with fresh-row-only "
        f"average; if 500d stale row leaked z would be deeply negative → "
        f"'tight'. Got: {result}"
    )


# ── Postgres tests (skip if TEST_DATABASE_URL unset) ─────────────────────────


def test_gather_risk_data_7day_fallback_postgres(pg_db_risk, monkeypatch):
    """7-day fallback aggregate excludes the 10-day-old stale row on Postgres."""
    test_database_url, _, _ = pg_db_risk
    monkeypatch.setenv("DATABASE_URL", test_database_url)

    from src.utils.db import connect_db as real_connect_db

    def pg_connect_db(db_path=None):
        return real_connect_db()

    monkeypatch.setattr("src.council.agent_data.connect_db", pg_connect_db)

    result = gather_risk_data(db_path="ignored-by-monkeypatch")
    assert isinstance(result, str)
    assert "20.0%" in result, (
        f"Expected PG 7-day fallback rate of 20.0% from fresh row alone, "
        f"got: {result}"
    )


def test_gather_macro_data_365d_zscore_postgres(pg_db_macro, monkeypatch):
    """HY OAS 365-day average excludes the 500-day-old stale row on Postgres."""
    test_database_url, _, _ = pg_db_macro
    monkeypatch.setenv("DATABASE_URL", test_database_url)

    from src.utils.db import connect_db as real_connect_db

    def pg_connect_db(db_path=None):
        return real_connect_db()

    monkeypatch.setattr("src.council.agent_data.connect_db", pg_connect_db)

    result = gather_macro_data(db_path="ignored-by-monkeypatch")
    assert isinstance(result, str)
    assert "Credit: normal" in result, (
        f"Expected PG 'Credit: normal' from fresh-row-only 365d average; "
        f"got: {result}"
    )

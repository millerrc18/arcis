"""Sanity tests for pg_wrapper + parametrized_conn fixtures (Sprint 5 §J5/§J6 Phase 0 T0.9).

Verifies:
1. pg_wrapper returns a PostgresConnectionWrapper when TEST_DATABASE_URL is set;
   skips cleanly (not failed) when unset.
2. parametrized_conn exposes a `.execute('SELECT 1')` callable that returns the
   expected scalar result on both engines (SQLite + Postgres).

SAFETY: tests/conftest.py reads ONLY `TEST_DATABASE_URL`, never `DATABASE_URL`,
so the prod Render URL on the operator's .env can never be used here. When
TEST_DATABASE_URL is absent, the postgres parametrize variant is SKIPPED.
"""
from __future__ import annotations

import os

import pytest

from src.utils.db import PostgresConnectionWrapper


# -- Test 1: pg_wrapper -------------------------------------------------------

def test_pg_wrapper_returns_postgres_connection_wrapper(pg_wrapper):
    """pg_wrapper fixture yields a PostgresConnectionWrapper.

    Body executes only when TEST_DATABASE_URL is set; otherwise the fixture
    itself calls pytest.skip() and the test is reported as SKIPPED, not
    FAILED — total test count is stable across environments.
    """
    assert isinstance(pg_wrapper, PostgresConnectionWrapper), (
        f"pg_wrapper must yield PostgresConnectionWrapper, got {type(pg_wrapper).__name__}"
    )
    # Smoke-test: cursor + simple SELECT round-trip.
    cur = pg_wrapper.cursor()
    cur.execute("SELECT 1 AS one")
    row = cur.fetchone()
    assert row is not None, "expected one row from SELECT 1"
    # CompatRow supports both int and str access.
    assert row[0] == 1
    assert row["one"] == 1


# -- Test 2: parametrized_conn ------------------------------------------------

def test_parametrized_conn_execute_returns_one(parametrized_conn):
    """parametrized_conn yields a .execute() callable on both engines.

    Parametrized over engine=['sqlite', 'postgres']. The 'postgres' variant
    is SKIPPED when TEST_DATABASE_URL is unset (skip happens inside the
    pg_wrapper fixture body). Both engines must return 1 from SELECT 1.

    Uses named-column access (`row["one"]`) for cross-engine portability —
    sqlite3.Row + psycopg2.extras.RealDictCursor both support it; bare
    positional indexing diverges (RealDictRow has no integer key).
    """
    cur = parametrized_conn.execute("SELECT 1 AS one")
    row = cur.fetchone()
    assert row is not None, "expected one row from SELECT 1"
    assert row["one"] == 1

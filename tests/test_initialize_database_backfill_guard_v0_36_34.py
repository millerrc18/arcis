"""Regression-lock for v0.36.34 — initialize_database backfill must not crash startup.

Background
==========

`src/main.py:337` calls `initialize_database()` UNCONDITIONALLY, before the
subcommand dispatch (`args.func(args)`). So every `python -m src.main <cmd>`
invocation — including `startup`, which is what NSSM runs for the watch loop —
executes the journal init first.

`initialize_database` (src/journal/store.py) ensures the schema via the
SQLite-specific helpers (`src.schema.sqlite.create_all_tables` / `ensure_columns`),
then runs a best-effort data-migration:

    UPDATE shadow_trades SET actual_exit_time = COALESCE(updated_at, created_at)
    WHERE status = 'closed' AND actual_exit_time IS NULL

Under the PG cutover gate (ARCIS_PG_CUTOVER_ENABLED=1) `connect_db` reroutes
that UPDATE to Postgres — a backend whose schema this function never ensured
(it only ensured SQLite). The PG schema IS ensured, but by the `startup`
handler that runs AFTER line 337. So any moment PG transiently lacks the table
or the connection hiccups, the UNGUARDED UPDATE raises and crashes the entire
watch-loop launch.

2026-05-20 incident: one of two simultaneous 10:55:55 startup attempts crashed
with `psycopg2.errors.UndefinedTable: relation "shadow_trades" does not exist`.
NSSM's retry happened to succeed, so the loop recovered — but a restart that
doesn't get a lucky retry would stay down.

The fix
=======

The backfill is OPTIONAL (it only sets actual_exit_time for dashboard
visibility). Making startup DEPEND on it succeeding is the bug. v0.36.34 wraps
the UPDATE in a guard: a DB-layer failure logs a WARNING and continues, so a
non-critical backfill can never crash the watch loop.
"""
from __future__ import annotations

import logging
import sqlite3

import psycopg2
import pytest

import src.journal.store as store
import src.schema.sqlite as sqlite_schema


@pytest.fixture(autouse=True)
def _isolate_schema_helpers(monkeypatch, tmp_path):
    """Stub the SQLite schema helpers so these tests exercise only the backfill
    guard, and force the SQLite (non-cutover) routing default so the unit is
    hermetic regardless of the developer's shell env."""
    monkeypatch.setattr(sqlite_schema, "create_all_tables", lambda *a, **k: None)
    monkeypatch.setattr(sqlite_schema, "ensure_columns", lambda *a, **k: None)
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    # Never let a prior test's memoization skip the body.
    store._TABLES_INITIALIZED.clear()
    yield
    store._TABLES_INITIALIZED.clear()


class _RecordingConn:
    """Fake connect_db return value that records executed SQL."""

    def __init__(self):
        self.executed: list[str] = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        return self

    def commit(self):
        self.committed = True


class _BoomConn:
    """Fake connect_db return value whose backfill UPDATE raises, simulating the
    routed backend (PG under cutover) not having the table yet."""

    def __init__(self, exc):
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        raise self._exc

    def commit(self):  # pragma: no cover - never reached
        raise AssertionError("commit should not be reached after execute raises")


def test_backfill_failure_does_not_crash_startup(monkeypatch, tmp_path):
    """A sqlite-class failure on the backfill UPDATE must not propagate."""
    boom = _BoomConn(sqlite3.OperationalError("no such table: shadow_trades"))
    monkeypatch.setattr(store, "connect_db", lambda *a, **k: boom)

    db = str(tmp_path / "j.sqlite3")
    # Must NOT raise.
    store.initialize_database(db)
    # And it must record completion so it isn't retried forever in-process.
    assert db in store._TABLES_INITIALIZED


def test_backfill_tolerates_psycopg2_undefined_table(monkeypatch, tmp_path):
    """Locks the exact prod error class: psycopg2 UndefinedTable (42P01)."""
    undefined_table = psycopg2.errors.lookup("42P01")(
        'relation "shadow_trades" does not exist'
    )
    boom = _BoomConn(undefined_table)
    monkeypatch.setattr(store, "connect_db", lambda *a, **k: boom)

    db = str(tmp_path / "j.sqlite3")
    store.initialize_database(db)  # must not raise
    assert db in store._TABLES_INITIALIZED


def test_backfill_failure_logs_warning(monkeypatch, tmp_path, caplog):
    """The failure must be observable (WARNING), not silently swallowed."""
    boom = _BoomConn(sqlite3.OperationalError("no such table: shadow_trades"))
    monkeypatch.setattr(store, "connect_db", lambda *a, **k: boom)

    db = str(tmp_path / "j.sqlite3")
    with caplog.at_level(logging.WARNING, logger="src.journal.store"):
        store.initialize_database(db)

    assert any(
        record.levelno >= logging.WARNING and "shadow_trades" in record.getMessage().lower()
        or "backfill" in record.getMessage().lower()
        for record in caplog.records
    ), "backfill failure must emit a WARNING mentioning the skipped migration"


def test_backfill_runs_on_happy_path(monkeypatch, tmp_path):
    """When the connection is healthy, the backfill UPDATE is still executed and
    committed — the guard must not skip the migration on success."""
    rec = _RecordingConn()
    monkeypatch.setattr(store, "connect_db", lambda *a, **k: rec)

    db = str(tmp_path / "j.sqlite3")
    store.initialize_database(db)

    assert any("UPDATE shadow_trades" in sql for sql in rec.executed), (
        "the actual_exit_time backfill UPDATE must still run on the happy path"
    )
    assert rec.committed, "successful backfill must commit"
    assert db in store._TABLES_INITIALIZED


def test_backfill_update_is_guarded_in_source():
    """Structural lock: the UPDATE shadow_trades migration must sit inside a
    try/except within initialize_database, so a future edit can't un-guard it."""
    import ast
    import inspect

    src = inspect.getsource(store.initialize_database)
    tree = ast.parse(src.lstrip())

    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)

    def _contains_backfill(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if "UPDATE shadow_trades" in sub.value:
                    return True
        return False

    guarded = any(
        _contains_backfill(handler_parent)
        for handler_parent in ast.walk(func)
        if isinstance(handler_parent, ast.Try)
    )
    assert guarded, (
        "the 'UPDATE shadow_trades' backfill must be inside a try/except in "
        "initialize_database (v0.36.34) — an unguarded failure crashes startup"
    )

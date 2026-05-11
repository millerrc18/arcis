"""Tests for connect_db_with_pg_retry — Sprint 5 §J5/§J6 Phase 0 T0.11.

Covers M3 fix (Devil's Advocate critical): on PG exhaustion, write watchdog.txt
THEN sys.exit(1) so NSSM restarts the watch loop. The SystemExit propagates
past `except Exception` handlers in watch.py:1133, preventing the zombie-
watchdog mode where the loop keeps running without a configured DB.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg2
import pytest


def test_sqlite_path_is_identity_passthrough_no_retry(tmp_path, monkeypatch):
    """SQLite path (no DATABASE_URL or explicit db_path) must not call time.sleep.

    Identity passthrough to connect_db() — the retry helper should only engage
    on the PG path. SQLite paths are local file operations that don't need
    network-style retry.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = str(tmp_path / "test.sqlite3")

    sleep_calls = []

    def counting_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("time.sleep", counting_sleep)

    from src.utils.db import connect_db_with_pg_retry

    conn = connect_db_with_pg_retry(db_path=db_path)
    assert type(conn) is sqlite3.Connection
    assert sleep_calls == [], "SQLite path must not invoke time.sleep"
    conn.close()


def test_pg_path_retries_then_succeeds(monkeypatch):
    """PG path: psycopg2.connect raises OperationalError twice then succeeds.

    Asserts time.sleep called exactly 2 times (once after each failure, no
    sleep after the success). Final return is a PostgresConnectionWrapper.
    """
    from src.utils.db import PostgresConnectionWrapper

    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)

    sleep_calls = []

    def counting_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("time.sleep", counting_sleep)

    sentinel_conn = MagicMock(name="pg_raw_conn")
    attempts = {"n": 0}

    def flaky_connect(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise psycopg2.OperationalError("connection refused")
        return sentinel_conn

    with patch("psycopg2.connect", side_effect=flaky_connect):
        from src.utils.db import connect_db_with_pg_retry
        wrapper = connect_db_with_pg_retry(backoff_seconds=1)

    assert isinstance(wrapper, PostgresConnectionWrapper)
    assert attempts["n"] == 3, "expected 3 connect attempts (2 failures + 1 success)"
    assert sleep_calls == [1, 1], "expected sleep called after each of 2 failures"


def test_pg_exhaustion_writes_watchdog_file(tmp_path, monkeypatch):
    """5 OperationalError failures must write data/watchdog.txt with PG_CONNECT_FAIL.

    Path is derived from src.config.DB_PATH parent so the watchdog landmark
    sits next to the operator's data dir. NSSM service watcher reads this
    file to confirm a DB-induced restart vs an unrelated crash.
    """
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)

    # Point DB_PATH parent to tmp_path so watchdog.txt lands somewhere safe.
    fake_db_path = str(tmp_path / "ai_research_desk.sqlite3")
    monkeypatch.setattr("src.utils.db.DB_PATH", fake_db_path)

    # Avoid real 30s sleeps.
    monkeypatch.setattr("time.sleep", lambda s: None)

    def always_fail(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused")

    with patch("psycopg2.connect", side_effect=always_fail):
        from src.utils.db import connect_db_with_pg_retry
        with pytest.raises(SystemExit):
            connect_db_with_pg_retry(max_attempts=5, backoff_seconds=1)

    watchdog_file = tmp_path / "watchdog.txt"
    assert watchdog_file.exists(), "watchdog.txt must be written on exhaustion"
    content = watchdog_file.read_text(encoding="utf-8")
    assert "PG_CONNECT_FAIL" in content, (
        f"watchdog.txt must contain PG_CONNECT_FAIL marker; got: {content!r}"
    )


def test_pg_exhaustion_calls_sys_exit_1(tmp_path, monkeypatch):
    """M3: SystemExit(1) propagates past `except Exception` to trigger NSSM restart.

    The exit code MUST be 1 (NSSM only restarts on non-zero exit). Using
    SystemExit instead of raise lets the `except SystemExit: raise` guard
    in watch.py:1133 pass it through cleanly.
    """
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)

    fake_db_path = str(tmp_path / "ai_research_desk.sqlite3")
    monkeypatch.setattr("src.utils.db.DB_PATH", fake_db_path)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def always_fail(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused")

    with patch("psycopg2.connect", side_effect=always_fail):
        from src.utils.db import connect_db_with_pg_retry
        with pytest.raises(SystemExit) as exc_info:
            connect_db_with_pg_retry(max_attempts=5, backoff_seconds=1)

    assert exc_info.value.code == 1, (
        f"sys.exit must be called with code 1; got code={exc_info.value.code!r}"
    )


def test_pg_exhaustion_writes_watchdog_before_sys_exit(tmp_path, monkeypatch):
    """M3 ordering invariant: watchdog.txt exists EVEN AFTER SystemExit raises.

    If sys.exit(1) ran first (or in a finally block out of order), the file
    write would be skipped because SystemExit unwinds the stack. This test
    asserts the file is observable from outside the SystemExit context —
    meaning the write happened before sys.exit was invoked.
    """
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)

    fake_db_path = str(tmp_path / "ai_research_desk.sqlite3")
    monkeypatch.setattr("src.utils.db.DB_PATH", fake_db_path)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def always_fail(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused")

    watchdog_file = tmp_path / "watchdog.txt"
    assert not watchdog_file.exists(), "precondition: watchdog.txt must not exist"

    with patch("psycopg2.connect", side_effect=always_fail):
        from src.utils.db import connect_db_with_pg_retry
        try:
            connect_db_with_pg_retry(max_attempts=5, backoff_seconds=1)
        except SystemExit:
            pass

    # File must exist after SystemExit unwound — proves write happened before exit.
    assert watchdog_file.exists(), (
        "watchdog.txt must be written BEFORE sys.exit(1) is called"
    )
    content = watchdog_file.read_text(encoding="utf-8")
    assert "PG_CONNECT_FAIL" in content

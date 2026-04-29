"""Tests for GET /api/broker-exceptions/recent and /api/broker-exceptions/summary.

Called by: pytest (CI)
Calls: src.api.cloud_routes.broker_exceptions
Owns tables: none
Config keys: none
Tests: Track 1.5 / Round 8.C backend tests
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from src.api.cloud_routes.broker_exceptions import (
    _fetch_recent_exceptions,
    get_recent_exceptions,
    get_summary,
)


# #87 — clear DATABASE_URL so the route always takes the local SQLite path
# unless a test explicitly opts into Postgres routing via monkeypatch.setenv.
# Without this, tests inherit the operator's `.env` (which sets DATABASE_URL
# to the Render Postgres URL) and the route silently bypasses connect_db
# patches. See worktree env-drift gotcha in CLAUDE.md.
@pytest.fixture(autouse=True)
def _clear_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_row(
    id_=1,
    ticker="CVS",
    operation="place_order",
    broker="alpaca",
    timestamp=None,
    exception_class="ConnectionError",
    exception_message="timed out",
    traceback="...",
    recoverable=1,
    created_at=None,
    correlation_id=None,
    retry_count=0,
    outcome="persisted",
):
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    ca = created_at or ts
    return {
        "id": id_,
        "ticker": ticker,
        "operation": operation,
        "broker": broker,
        "timestamp": ts,
        "exception_class": exception_class,
        "exception_message": exception_message,
        "traceback": traceback,
        "recoverable": recoverable,
        "created_at": ca,
        "correlation_id": correlation_id,
        "retry_count": retry_count,
        "outcome": outcome,
    }


def _make_old_row(**kwargs):
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    defaults = dict(id_=99, timestamp=old_ts, created_at=old_ts)
    defaults.update(kwargs)
    return _make_row(**defaults)


def _in_memory_conn_with_rows(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE broker_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            operation TEXT NOT NULL,
            broker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            exception_class TEXT NOT NULL,
            exception_message TEXT NOT NULL,
            traceback TEXT,
            recoverable INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            correlation_id TEXT,
            retry_count INTEGER,
            outcome TEXT
        )
    """)
    for r in rows:
        conn.execute(
            """INSERT INTO broker_exceptions
               (id, ticker, operation, broker, timestamp, exception_class,
                exception_message, traceback, recoverable, created_at,
                correlation_id, retry_count, outcome)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["id"], r["ticker"], r["operation"], r["broker"],
                r["timestamp"], r["exception_class"], r["exception_message"],
                r["traceback"], r["recoverable"], r["created_at"],
                r["correlation_id"], r["retry_count"], r["outcome"],
            ),
        )
    conn.commit()
    return conn


# ── _fetch_recent_exceptions unit tests ──────────────────────────────────────

class TestFetchRecentExceptions:
    def test_returns_list_for_empty_db(self):
        conn = _in_memory_conn_with_rows([])
        result = _fetch_recent_exceptions(conn, limit=50, since_hours=24)
        assert isinstance(result, list)
        assert result == []

    def test_returns_recent_rows_within_window(self):
        recent = _make_row(id_=1)
        conn = _in_memory_conn_with_rows([recent])
        result = _fetch_recent_exceptions(conn, limit=50, since_hours=24)
        assert len(result) == 1
        assert result[0]["ticker"] == "CVS"

    def test_excludes_rows_outside_window(self):
        old = _make_old_row(id_=2)
        conn = _in_memory_conn_with_rows([old])
        result = _fetch_recent_exceptions(conn, limit=50, since_hours=24)
        assert result == []

    def test_respects_limit(self):
        rows = [_make_row(id_=i) for i in range(1, 11)]
        conn = _in_memory_conn_with_rows(rows)
        result = _fetch_recent_exceptions(conn, limit=5, since_hours=24)
        assert len(result) == 5

    def test_rows_are_dicts_with_required_keys(self):
        row = _make_row()
        conn = _in_memory_conn_with_rows([row])
        result = _fetch_recent_exceptions(conn, limit=50, since_hours=24)
        required = {
            "id", "ticker", "operation", "broker", "timestamp",
            "exception_class", "exception_message", "recoverable",
            "created_at", "outcome",
        }
        for key in required:
            assert key in result[0], f"Missing key: {key}"


# ── GET /recent endpoint shape tests ─────────────────────────────────────────

class TestGetRecentEndpoint:
    def _call(self, rows, limit=50, since_hours=24):
        conn = _in_memory_conn_with_rows(rows)
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=conn,
        ):
            return get_recent_exceptions(limit=limit, since_hours=since_hours)

    def test_returns_dict_with_rows_and_meta(self):
        result = self._call([])
        assert "rows" in result
        assert "count" in result
        assert "limit" in result
        assert "since_hours" in result

    def test_empty_db_returns_empty_rows(self):
        result = self._call([])
        assert result["rows"] == []
        assert result["count"] == 0

    def test_with_rows_count_matches(self):
        rows = [_make_row(id_=i) for i in range(1, 4)]
        result = self._call(rows)
        assert result["count"] == 3
        assert len(result["rows"]) == 3

    def test_limit_param_propagated(self):
        rows = [_make_row(id_=i) for i in range(1, 11)]
        result = self._call(rows, limit=3)
        assert result["limit"] == 3
        assert len(result["rows"]) <= 3

    def test_since_hours_param_propagated(self):
        result = self._call([], since_hours=48)
        assert result["since_hours"] == 48

    def test_old_rows_excluded_at_default_24h(self):
        old = _make_old_row()
        result = self._call([old])
        assert result["count"] == 0

    def test_row_dict_has_expected_fields(self):
        row = _make_row(outcome="alert_qty_mismatch")
        result = self._call([row])
        r = result["rows"][0]
        assert r["ticker"] == "CVS"
        assert r["outcome"] == "alert_qty_mismatch"


# ── GET /summary endpoint shape tests ────────────────────────────────────────

class TestGetSummaryEndpoint:
    def _call(self, rows):
        conn = _in_memory_conn_with_rows(rows)
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=conn,
        ):
            return get_summary()

    def test_returns_required_top_level_keys(self):
        result = self._call([])
        for key in ("total_24h", "total_7d", "alert_qty_mismatch_count",
                    "by_broker", "by_operation"):
            assert key in result, f"Missing key: {key}"

    def test_empty_db_all_counts_zero(self):
        result = self._call([])
        assert result["total_24h"] == 0
        assert result["total_7d"] == 0
        assert result["alert_qty_mismatch_count"] == 0
        assert result["by_broker"] == {}
        assert result["by_operation"] == {}

    def test_total_24h_counts_recent_only(self):
        recent = _make_row(id_=1)
        old = _make_old_row(id_=2)
        result = self._call([recent, old])
        assert result["total_24h"] == 1

    def test_total_7d_counts_within_7_days(self):
        recent = _make_row(id_=1)
        within_7d_ts = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
        within_7d = _make_row(id_=2, timestamp=within_7d_ts, created_at=within_7d_ts)
        beyond_7d_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        beyond_7d = _make_row(id_=3, timestamp=beyond_7d_ts, created_at=beyond_7d_ts)
        result = self._call([recent, within_7d, beyond_7d])
        assert result["total_7d"] == 2

    def test_alert_qty_mismatch_counted(self):
        alert_row = _make_row(id_=1, outcome="alert_qty_mismatch")
        normal_row = _make_row(id_=2, outcome="persisted")
        result = self._call([alert_row, normal_row])
        assert result["alert_qty_mismatch_count"] == 1

    def test_by_broker_groups_correctly(self):
        r1 = _make_row(id_=1, broker="alpaca")
        r2 = _make_row(id_=2, broker="alpaca")
        r3 = _make_row(id_=3, broker="ibkr")
        result = self._call([r1, r2, r3])
        assert result["by_broker"]["alpaca"] == 2
        assert result["by_broker"]["ibkr"] == 1

    def test_by_operation_groups_correctly(self):
        r1 = _make_row(id_=1, operation="place_order")
        r2 = _make_row(id_=2, operation="cancel_order")
        r3 = _make_row(id_=3, operation="place_order")
        result = self._call([r1, r2, r3])
        assert result["by_operation"]["place_order"] == 2
        assert result["by_operation"]["cancel_order"] == 1


# ── Connection-lifecycle regression tests (PR #690 B4) ───────────────────────
# These tests guard against the original B4 leak where get_recent_exceptions
# and get_summary opened conn = connect_db() but never closed it. With the
# closing(...) wrapper, conn.close() must be invoked exactly once per call,
# and crucially, even when the inner work raises.

class TestConnectionClosed:
    def _spy_conn(self, rows):
        """Build an in-memory conn with a spy attached to .close()."""
        real = _in_memory_conn_with_rows(rows)
        spy = MagicMock(wraps=real)
        # MagicMock(wraps=...) forwards attribute access to `real` but
        # records calls. close() is what we want to assert on.
        return spy, real

    def test_get_recent_closes_connection_on_success(self):
        spy, _real = self._spy_conn([_make_row(id_=1)])
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=spy,
        ):
            get_recent_exceptions(limit=50, since_hours=24)
        spy.close.assert_called_once()

    def test_get_recent_closes_connection_on_exception(self):
        """Even if _fetch_recent_exceptions raises, close() must still run."""
        spy, _real = self._spy_conn([])
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=spy,
        ), patch(
            "src.api.cloud_routes.broker_exceptions._fetch_recent_exceptions",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                get_recent_exceptions(limit=50, since_hours=24)
        spy.close.assert_called_once()

    def test_get_summary_closes_connection_on_success(self):
        spy, _real = self._spy_conn([])
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=spy,
        ):
            get_summary()
        spy.close.assert_called_once()

    def test_get_summary_closes_connection_on_exception(self):
        """If a query inside get_summary raises, conn.close() must still run."""
        spy, real = self._spy_conn([])
        # Force the first .execute() call to raise mid-aggregation.
        original_execute = real.execute

        def _raising_execute(sql, *args, **kwargs):
            if "by_broker" in sql or "GROUP BY broker" in sql:
                raise RuntimeError("query exploded")
            return original_execute(sql, *args, **kwargs)

        spy.execute.side_effect = _raising_execute
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=spy,
        ):
            with pytest.raises(RuntimeError, match="query exploded"):
                get_summary()
        spy.close.assert_called_once()

    def test_repeated_calls_do_not_leak_handles(self):
        """N invocations should produce N close() calls (one per request).

        Mirrors the dashboard's 60s auto-refresh — under the original bug the
        close count would lag the call count and file handles would leak.
        """
        rows = [_make_row(id_=1)]
        close_count = 0

        def _factory():
            nonlocal close_count
            real = _in_memory_conn_with_rows(rows)
            spy = MagicMock(wraps=real)
            original_close = real.close

            def _tracking_close():
                nonlocal close_count
                close_count += 1
                return original_close()

            spy.close.side_effect = _tracking_close
            return spy

        n_calls = 5
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            side_effect=lambda *a, **kw: _factory(),
        ):
            for _ in range(n_calls):
                get_recent_exceptions(limit=10, since_hours=24)
        assert close_count == n_calls, (
            f"Expected {n_calls} conn.close() calls, got {close_count} — "
            "connection leak regression."
        )


# ── Postgres-cloud routing tests (#87) ───────────────────────────────────────
# When DATABASE_URL is set (Render), the route MUST query Postgres via psycopg2
# instead of opening a SQLite connection. Without this, the cloud dashboard
# reads from an empty SQLite file on Render and shows stale/empty data even
# though the table is sync_to_postgres=True in the registry.

class TestPostgresRouting:
    """Tests asserting DATABASE_URL → psycopg2 path; no DATABASE_URL → SQLite."""

    def test_recent_uses_psycopg2_when_database_url_set(self, monkeypatch):
        """With DATABASE_URL set, the route opens a Postgres connection and
        does NOT call connect_db (SQLite). The SQL `?` placeholders must be
        rewritten to `%s` for the Postgres path."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@host/db")

        captured = {}

        class _FakeCursor:
            def __init__(self):
                self._rows = []

            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return []

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _FakeConn:
            def cursor(self, cursor_factory=None):
                captured["cursor_factory"] = cursor_factory
                return _FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        fake_psycopg2 = MagicMock()
        fake_psycopg2.connect.return_value = _FakeConn()
        fake_extras = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "psycopg2", fake_psycopg2)
        monkeypatch.setitem(__import__("sys").modules, "psycopg2.extras", fake_extras)

        sqlite_called = MagicMock()
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            side_effect=sqlite_called,
        ):
            result = get_recent_exceptions(limit=50, since_hours=24)
        sqlite_called.assert_not_called()
        fake_psycopg2.connect.assert_called_once_with("postgresql://fake:fake@host/db")
        # Placeholder rewrite: `?` -> `%s`
        assert "?" not in captured["sql"]
        assert "%s" in captured["sql"]
        assert result["rows"] == []
        assert result["count"] == 0

    def test_summary_uses_psycopg2_when_database_url_set(self, monkeypatch):
        """The /summary endpoint must also route to Postgres when DATABASE_URL
        is set. All four count queries should use psycopg2, not SQLite."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@host/db")

        executed_sqls: list[str] = []

        class _FakeCursor:
            def __init__(self):
                self._next_result = None

            def execute(self, sql, params):
                executed_sqls.append(sql)
                # COUNT(*) queries return a one-row, one-column result.
                # GROUP BY queries return a list with (key, count) tuples.
                lower = sql.lower()
                if "group by" in lower:
                    self._next_result = []
                else:
                    self._next_result = [{"count": 0}]

            def fetchall(self):
                return self._next_result or []

            def fetchone(self):
                rows = self._next_result or []
                return rows[0] if rows else None

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _FakeConn:
            def cursor(self, cursor_factory=None):
                return _FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        fake_psycopg2 = MagicMock()
        fake_psycopg2.connect.return_value = _FakeConn()
        fake_extras = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "psycopg2", fake_psycopg2)
        monkeypatch.setitem(__import__("sys").modules, "psycopg2.extras", fake_extras)

        sqlite_called = MagicMock()
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            side_effect=sqlite_called,
        ):
            result = get_summary()
        sqlite_called.assert_not_called()
        # All SQL placeholders rewritten
        for sql in executed_sqls:
            assert "?" not in sql, f"SQLite-style placeholder leaked: {sql}"
        assert result["total_24h"] == 0
        assert result["total_7d"] == 0
        assert result["alert_qty_mismatch_count"] == 0
        assert result["by_broker"] == {}
        assert result["by_operation"] == {}

    def test_recent_falls_back_to_sqlite_when_database_url_unset(self, monkeypatch):
        """Without DATABASE_URL, the route still uses SQLite via connect_db.
        Local-dev parity: the cloud route must keep working on the operator's
        machine where DATABASE_URL is unset."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        recent = _make_row(id_=1)
        conn = _in_memory_conn_with_rows([recent])
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=conn,
        ):
            result = get_recent_exceptions(limit=50, since_hours=24)
        assert result["count"] == 1
        assert result["rows"][0]["ticker"] == "CVS"

    def test_summary_falls_back_to_sqlite_when_database_url_unset(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        rows = [
            _make_row(id_=1, broker="alpaca"),
            _make_row(id_=2, broker="alpaca", outcome="alert_qty_mismatch"),
        ]
        conn = _in_memory_conn_with_rows(rows)
        with patch(
            "src.api.cloud_routes.broker_exceptions.connect_db",
            return_value=conn,
        ):
            result = get_summary()
        assert result["total_24h"] == 2
        assert result["alert_qty_mismatch_count"] == 1
        assert result["by_broker"] == {"alpaca": 2}

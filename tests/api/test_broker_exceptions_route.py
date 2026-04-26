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

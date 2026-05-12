"""Regression-lock for _check_row_counts cross-engine KeyError:0 fix (T1 / task #92).

watch.py:1178 used to do:
    count = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]

Against psycopg2's RealDictCursor (used by connect_db() on PG), `fetchone()`
returns a dict-like object. `dict_row[0]` is a key lookup → KeyError(0).

Fix: use cross-engine-safe access:
    row = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()
    count = row[0] if not isinstance(row, dict) else row['count']

This test exercises _check_row_counts with both a tuple mock (SQLite path) and a
dict mock (PG path) to assert no KeyError and correct count extraction.

Called by: pytest (Sprint 5 Wave A T1)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch


def _import_watch_loop():
    """Import WatchLoop from src.scheduler.watch.

    Import is deferred so that the test file can be collected without the
    full scheduler import chain running at module load time.
    """
    from src.scheduler.watch import WatchLoop
    return WatchLoop


# ── Row-result mocks ───────────────────────────────────────────────────────────


class _TupleRow:
    """Minimal sqlite3.Row-like mock (tuple-based positional access)."""

    def __init__(self, values):
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        raise KeyError(key)

    def __len__(self):
        return len(self._values)


class _DictRow(dict):
    """psycopg2 RealDictCursor row mock (string-keyed, int key raises KeyError)."""


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_check_row_counts_with_tuple_row_nonzero(caplog):
    """SQLite path: tuple row with count > 0 — no warning logged."""
    WatchLoop = _import_watch_loop()

    tuple_row = _TupleRow([42])

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = tuple_row

    with patch("src.scheduler.watch.connect_db", return_value=mock_conn):
        with caplog.at_level(logging.WARNING, logger="src.scheduler.watch"):
            WatchLoop._check_row_counts()

    # No warning about row count failure or empty shadow_trades
    assert not any(
        "Row count check failed" in r.message or "shadow_trades is empty" in r.message
        for r in caplog.records
    ), f"Unexpected warning with tuple row count=42: {[r.message for r in caplog.records]}"


def test_check_row_counts_with_tuple_row_zero(caplog):
    """SQLite path: tuple row with count = 0 — empty-table warning fires."""
    WatchLoop = _import_watch_loop()

    tuple_row = _TupleRow([0])

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = tuple_row

    # send_telegram is imported inline inside _check_row_counts; patch the
    # module it's imported from so the local import resolves to the mock.
    # send_telegram is imported inline; the outer except silences any exception
    # so we don't need to patch it — the warning fires before the telegram call.
    with patch("src.scheduler.watch.connect_db", return_value=mock_conn):
        with caplog.at_level(logging.WARNING, logger="src.scheduler.watch"):
            WatchLoop._check_row_counts()

    assert any(
        "shadow_trades is empty" in r.message for r in caplog.records
    ), f"Expected 'shadow_trades is empty' warning; got: {[r.message for r in caplog.records]}"


def test_check_row_counts_with_dict_row_nonzero(caplog):
    """PG path: dict row with count > 0 — no KeyError, no warning."""
    WatchLoop = _import_watch_loop()

    dict_row = _DictRow({"count": 17})

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = dict_row

    with patch("src.scheduler.watch.connect_db", return_value=mock_conn):
        with caplog.at_level(logging.WARNING, logger="src.scheduler.watch"):
            WatchLoop._check_row_counts()

    assert not any(
        "Row count check failed" in r.message or "shadow_trades is empty" in r.message
        for r in caplog.records
    ), (
        f"Unexpected warning with dict row count=17: {[r.message for r in caplog.records]}"
    )


def test_check_row_counts_with_dict_row_zero(caplog):
    """PG path: dict row with count = 0 — empty-table warning fires, no KeyError."""
    WatchLoop = _import_watch_loop()

    dict_row = _DictRow({"count": 0})

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = dict_row

    # send_telegram is imported inline inside an inner try/except that silences
    # all exceptions — no patching needed, the warning fires before that path.
    with patch("src.scheduler.watch.connect_db", return_value=mock_conn):
        with caplog.at_level(logging.WARNING, logger="src.scheduler.watch"):
            WatchLoop._check_row_counts()

    assert any(
        "shadow_trades is empty" in r.message for r in caplog.records
    ), f"Expected 'shadow_trades is empty' warning; got: {[r.message for r in caplog.records]}"

    assert not any(
        "Row count check failed" in r.message for r in caplog.records
    ), (
        f"KeyError still fires on dict row: {[r.message for r in caplog.records]}"
    )


def test_check_row_counts_dict_row_keyerror_0_before_fix():
    """Confirm that a plain dict[0] raises KeyError — the original bug.

    This test documents the failure mode. It asserts that a raw dict raises
    KeyError(0) when accessed via [0], which is what the pre-fix code did.
    """
    d = _DictRow({"count": 5})
    try:
        _ = d[0]
        raise AssertionError("Expected KeyError(0) but no exception raised")
    except KeyError as exc:
        assert exc.args[0] == 0, f"Expected KeyError(0), got KeyError({exc.args[0]!r})"

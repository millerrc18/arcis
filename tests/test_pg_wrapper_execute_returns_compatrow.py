"""Regression-lock: PostgresConnectionWrapper.execute() returns _RowFactoryCursor.

Sprint 5 Wave A+B closed the M4/2026-05-10 KeyError:0 bug class with:

1.  T1 — fixed the direct-symptom site at scheduler/watch.py
2.  T1ext — 82-site defensive-dispatch sweep across 14 files
3.  Wave A+B follow-up (PR #1059) — ``_scalar(row)`` helper +
    AST-based structural guardrail

This test locks the STRUCTURAL root-cause fix from #98: both
``PostgresConnectionWrapper.execute()`` and ``executemany()`` must wrap
their returned psycopg2 cursor in ``_RowFactoryCursor`` so that
``fetch*()`` methods produce ``CompatRow`` instances (supporting both
``row[0]`` and ``row['col']``) rather than raw psycopg2 dicts.

Why this gate exists: a future refactor or a well-intentioned simplification
could unwrap the cursor (e.g., "return cur directly to avoid the
indirection"). That single-line regression would re-introduce the entire
82-site dispatch need at every caller. This test fails loudly if either
``execute`` or ``executemany`` returns anything other than a
``_RowFactoryCursor``.

Called by: pytest
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_wrapper():
    """Return a PostgresConnectionWrapper with a mocked psycopg2 cursor.

    The mock cursor's ``fetchone()`` returns a raw dict (matching what a
    real ``RealDictCursor`` would emit). Tests then assert the wrapper's
    fetch methods convert this to ``CompatRow``.
    """
    from src.utils.db import PostgresConnectionWrapper

    mock_cursor = MagicMock(name="raw_psycopg2_cursor")
    mock_cursor.fetchone.return_value = {"count": 42}
    mock_cursor.fetchall.return_value = [{"a": 1}, {"a": 2}]

    mock_raw_conn = MagicMock(name="raw_psycopg2_conn")
    mock_raw_conn.cursor.return_value = mock_cursor

    return PostgresConnectionWrapper(mock_raw_conn), mock_cursor


def test_execute_returns_row_factory_cursor() -> None:
    """``wrapper.execute(sql)`` must return ``_RowFactoryCursor``, not raw cur.

    Was raw psycopg2 cursor pre-#98 — caused rows to flow back as raw dicts,
    which broke ``row[0]`` access and forced the 82-site defensive-dispatch
    sweep (T1ext). #98 wraps the cursor so fetched rows are CompatRow.
    """
    from src.utils.db import _RowFactoryCursor

    wrapper, _ = _make_wrapper()
    cur = wrapper.execute("SELECT 1")
    assert isinstance(cur, _RowFactoryCursor), (
        f"PostgresConnectionWrapper.execute() must return _RowFactoryCursor "
        f"(so fetch* return CompatRow, not raw dict). Got {type(cur).__name__}. "
        "Was the cursor unwrapped by a recent refactor? See PR #1059's review "
        "discussion of the dispatch root cause."
    )


def test_executemany_returns_row_factory_cursor() -> None:
    """``wrapper.executemany(sql, params)`` must also return ``_RowFactoryCursor``.

    Same rationale as execute(). Parity matters because callers expect
    ``executemany`` to return a cursor with the same fetch semantics.
    """
    from src.utils.db import _RowFactoryCursor

    wrapper, _ = _make_wrapper()
    cur = wrapper.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    assert isinstance(cur, _RowFactoryCursor), (
        f"PostgresConnectionWrapper.executemany() must return _RowFactoryCursor. "
        f"Got {type(cur).__name__}."
    )


def test_execute_fetchone_returns_compatrow_not_dict() -> None:
    """End-to-end: ``wrapper.execute(sql).fetchone()`` returns CompatRow.

    This is the bug class the wrapping closes structurally. Pre-#98, this
    expression returned a raw dict, and ``row[0]`` raised ``KeyError(0)``.
    Post-#98, ``row`` is a CompatRow and ``row[0]`` returns the first value.
    """
    from src.utils.db import CompatRow

    wrapper, _ = _make_wrapper()
    row = wrapper.execute("SELECT COUNT(*) FROM t").fetchone()
    assert isinstance(row, CompatRow), (
        f"fetchone() must produce CompatRow now, got {type(row).__name__}"
    )
    # Functional sanity: row[0] and row['count'] both work
    assert row[0] == 42
    assert row["count"] == 42


def test_execute_fetchall_returns_list_of_compatrow() -> None:
    """``fetchall()`` returns a list of CompatRow, not list of dict."""
    from src.utils.db import CompatRow

    wrapper, _ = _make_wrapper()
    rows = wrapper.execute("SELECT a FROM t").fetchall()
    assert all(isinstance(r, CompatRow) for r in rows), (
        "fetchall() must produce list of CompatRow, "
        f"got types: {[type(r).__name__ for r in rows]}"
    )
    # Functional sanity
    assert [r[0] for r in rows] == [1, 2]


def test_execute_passes_rowcount_through() -> None:
    """``wrapper.execute(sql).rowcount`` must still work — pass-through via __getattr__.

    Callers that read ``.rowcount`` / ``.description`` / etc. must not break
    when the cursor is wrapped. _RowFactoryCursor's __getattr__ delegates
    unknown attributes to the inner cursor.
    """
    wrapper, mock_cursor = _make_wrapper()
    mock_cursor.rowcount = 7
    cur = wrapper.execute("INSERT INTO t VALUES (1)")
    assert cur.rowcount == 7, (
        "Wrapped cursor must pass .rowcount through to the inner cursor "
        "via _RowFactoryCursor.__getattr__"
    )

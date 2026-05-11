"""Tests for CompatRow + _RowFactoryCursor in src/utils/db.py.

These tests pin the sqlite3.Row-compatible semantics for CompatRow:
1. Dual int/str indexing: `row[0]` AND `row['col']`
2. Membership: `'col' in row`
3. `keys()` for column names
4. `len(row) == num_columns`
5. `repr(row)` is human-readable
6. _RowFactoryCursor wraps fetchone/fetchall/fetchmany return values

CRITICAL (Devil's Advocate finding C3): __iter__ must yield VALUES, not keys.
This matches sqlite3.Row semantics — `for v in row`, `tuple(row)`, `list(row)`,
and `a, b = row` all destructure VALUES. Tuple/list-coercion of an iterable
sqlite3.Row gives the row's column values, NOT the column names. Code paths
that iterate rows for unpacking would silently corrupt data if CompatRow
yielded keys instead.

Tests 9-12 lock C3 specifically. Test for dict(CompatRow) documents the
chosen contract — see test_dict_of_compatrow.
"""

import pytest


# ---------------------------------------------------------------------------
# CompatRow — basic indexing
# ---------------------------------------------------------------------------


def test_compatrow_int_index_returns_first_value():
    """row[0] returns the first value (sqlite3.Row int-index compat)."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": "hello"})
    assert row[0] == 1


def test_compatrow_string_index_returns_named_column_value():
    """row['col'] returns the value at the named column (dict-style)."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": "hello"})
    assert row["b"] == "hello"


def test_compatrow_membership_via_in_operator():
    """`'col' in row` returns True for present columns, False otherwise."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": "hello"})
    assert "a" in row
    assert "b" in row
    assert "missing" not in row


def test_compatrow_keys_returns_column_names():
    """row.keys() returns an iterator over column names."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": "hello", "c": 3.14})
    assert list(row.keys()) == ["a", "b", "c"]


def test_compatrow_len_returns_column_count():
    """len(row) returns the number of columns."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": "hello", "c": 3.14})
    assert len(row) == 3
    assert len(CompatRow({})) == 0


def test_compatrow_repr_includes_columns_and_values():
    """repr(row) is human-readable, showing columns and values for debugging."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": "hello"})
    r = repr(row)
    assert "CompatRow" in r
    assert "a" in r
    assert "1" in r
    assert "b" in r
    assert "hello" in r


# ---------------------------------------------------------------------------
# C3 — Iteration yields VALUES, NOT keys (matches sqlite3.Row)
# ---------------------------------------------------------------------------


def test_compatrow_tuple_coercion_yields_values_C3():
    """C3: tuple(CompatRow({'a':1,'b':2})) == (1, 2) — VALUES, not keys.

    sqlite3.Row's tuple-coercion returns column values, NOT column names.
    Code paths that do `for col in row` expect values. If CompatRow yielded
    keys instead, this would silently corrupt data (e.g., a loop that sums
    numeric columns would sum string column names → TypeError or worse,
    a count of columns).
    """
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": 2})
    assert tuple(row) == (1, 2)


def test_compatrow_list_coercion_yields_values_C3():
    """C3: list(CompatRow({'a':1,'b':2})) == [1, 2] — VALUES, not keys."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": 2})
    assert list(row) == [1, 2]


def test_compatrow_for_loop_iterates_values_C3():
    """C3: `[v for v in row]` yields VALUES, matching sqlite3.Row."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": 2})
    assert [v for v in row] == [1, 2]


def test_compatrow_destructure_unpacking_yields_values_C3():
    """C3: `a, b = CompatRow(...)` destructures into VALUES, not keys."""
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": 2})
    a, b = row
    assert (a, b) == (1, 2)


# ---------------------------------------------------------------------------
# dict(CompatRow) — chosen contract: returns column-keyed dict (matches sqlite3.Row)
# ---------------------------------------------------------------------------


def test_dict_of_compatrow_returns_column_keyed_dict():
    """dict(CompatRow({'a':1,'b':2})) == {'a': 1, 'b': 2}.

    Chosen contract: dict() on a CompatRow yields a column-keyed dict, matching
    Python sqlite3.Row's documented behavior (verified empirically — `dict(row)`
    works on a sqlite3.Row because Python's dict() constructor detects the
    presence of `keys()` and routes through `keys() + __getitem__` rather than
    iterating the object). Since CompatRow exposes `keys()` and `__getitem__`
    accepts strings, `dict(CompatRow)` produces the expected column-keyed dict
    EVEN THOUGH `__iter__` itself yields values.

    Rationale: callers should be able to convert a CompatRow back to a plain
    dict — e.g. for JSON serialization or for passing to a SQL parameter dict.
    Forbidding this would force callers to write `{k: row[k] for k in row.keys()}`
    everywhere.
    """
    from src.utils.db import CompatRow

    row = CompatRow({"a": 1, "b": 2})
    assert dict(row) == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# _RowFactoryCursor — wraps psycopg2 cursor fetches in CompatRow
# ---------------------------------------------------------------------------


class _FakePsycopgCursor:
    """Mimics a psycopg2 cursor configured with RealDictCursor: fetches return dicts."""

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        out, self._rows = self._rows, []
        return out

    def fetchmany(self, size):
        out = self._rows[:size]
        self._rows = self._rows[size:]
        return out

    def execute(self, *a, **kw):
        return None

    def executemany(self, *a, **kw):
        return None

    def close(self):
        return None


def test_row_factory_cursor_fetchone_returns_compatrow():
    """_RowFactoryCursor.fetchone() returns CompatRow (or None when no rows)."""
    from src.utils.db import CompatRow, _RowFactoryCursor

    inner = _FakePsycopgCursor([{"a": 1, "b": "x"}])
    cursor = _RowFactoryCursor(inner)

    row = cursor.fetchone()
    assert isinstance(row, CompatRow)
    assert row[0] == 1
    assert row["b"] == "x"

    # After exhaustion, fetchone returns None (does not wrap in CompatRow).
    assert cursor.fetchone() is None


def test_row_factory_cursor_fetchall_returns_list_of_compatrow():
    """_RowFactoryCursor.fetchall() returns a list of CompatRow instances."""
    from src.utils.db import CompatRow, _RowFactoryCursor

    inner = _FakePsycopgCursor([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
    cursor = _RowFactoryCursor(inner)

    rows = cursor.fetchall()
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert all(isinstance(r, CompatRow) for r in rows)
    assert rows[0]["a"] == 1
    assert rows[1]["b"] == "y"

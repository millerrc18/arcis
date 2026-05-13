"""Regression-lock tests for CompatRow integer-indexing semantics.

Sprint 5 T16 fold-in for tracker #104. Verifies the `r[0]` access pattern
used by SQLite-shaped call sites (e.g. `[r[0] for r in cur.fetchall()]`
in `src/evaluation/build_score.py:341`) returns column-by-position values
when the underlying row is a `CompatRow` wrapping a PG RealDictCursor row.

The invariant from `src/utils/db.py::CompatRow`:
  - `row[int]` returns `list(self._row.values())[int]` — column-by-position
  - `row['col']` returns `self._row['col']` — column-by-name
  - `for v in row` yields VALUES not keys (matches sqlite3.Row)
  - `tuple(row)` / `list(row)` / `a, b = row` all yield values

These tests cover the integer-indexing arm specifically — the most common
pattern that risks silent data corruption if `CompatRow.__getitem__(int)`
ever drifts from "by position" to "by-key string-conversion."
"""

from __future__ import annotations

import pytest

from src.utils.db import CompatRow


def test_compatrow_integer_index_returns_first_column_value():
    """CompatRow[0] returns the value of the first column (by insertion order)."""
    row = CompatRow({"build_score": 87.5, "score_date": "2026-05-13"})
    assert row[0] == 87.5
    assert row[1] == "2026-05-13"


def test_compatrow_listcomp_pattern_extracts_first_column_across_fetchall():
    """The `[r[0] for r in rows]` pattern from build_score.py:341 returns a
    list of first-column values when rows are CompatRow instances."""
    rows = [
        CompatRow({"build_score": 80.0, "score_date": "2026-05-08"}),
        CompatRow({"build_score": 82.5, "score_date": "2026-05-09"}),
        CompatRow({"build_score": 87.5, "score_date": "2026-05-13"}),
    ]
    scores = [r[0] for r in rows]
    assert scores == [80.0, 82.5, 87.5]


def test_compatrow_integer_index_matches_keys_iteration_order():
    """CompatRow[i] for i in range(len(row)) MUST yield the same sequence
    as `row.keys()` mapped through `row[<key>]`. This is the implicit
    contract that integer-indexing call sites rely on across engines."""
    payload = {"a": 1, "b": 2, "c": 3}
    row = CompatRow(payload)
    positional = [row[i] for i in range(len(row))]
    by_name = [row[k] for k in row.keys()]
    assert positional == by_name == [1, 2, 3]


def test_compatrow_integer_index_does_not_coerce_to_string_key():
    """Regression lock: ensure that CompatRow[0] does NOT accidentally
    coerce 0 to "0" and try a key lookup (which would raise KeyError if
    no string key matches, or — worse — silently return the wrong column
    if a column named "0" existed)."""
    row = CompatRow({"build_score": 87.5})
    # If the implementation ever drifts to `self._row[str(key)]`, this
    # assertion catches it (no key "0" in the dict).
    assert row[0] == 87.5
    with pytest.raises(KeyError):
        # The string-key path MUST still raise on a missing key.
        _ = row["0"]


def test_compatrow_integer_index_out_of_bounds_raises_index_error():
    """CompatRow[N] for N >= len(row) MUST raise IndexError (matches
    list semantics) — call sites that depend on bounds-checking via
    `try: r[N]; except IndexError:` keep working under PG."""
    row = CompatRow({"a": 1, "b": 2})
    with pytest.raises(IndexError):
        _ = row[2]
    with pytest.raises(IndexError):
        _ = row[99]


def test_compatrow_integer_index_negative_indexing():
    """CompatRow[-1] should return the last column's value (list-style
    negative indexing) — matches sqlite3.Row's tuple-like behavior."""
    row = CompatRow({"a": 1, "b": 2, "c": 3})
    assert row[-1] == 3
    assert row[-2] == 2

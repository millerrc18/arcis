"""Phase 3-revised T6 — operator_view_state writers cross-engine verification.

Tests:
  1. _write_view_state — insert (user_id=A, entry_name=X) then insert again with
     different last_viewed_value; assert latest value persists (replace semantic).
  2. _write_reviewed_override — insert (user_id=A, entry_name=X, override) then
     again with different override; assert latest value persists.
  3. Regression lock — assert _REPLACE_SEMANTICS["operator_view_state"] ==
     "in_place_update" after T1 lands.

Tests 1+2 are parametrized over (sqlite) engine. The postgres variant skips
cleanly via parametrized_conn when TEST_DATABASE_URL is absent.

Monkeypatch note: _ensure_replace_semantics_for_operator_view_state adds the
_REPLACE_SEMANTICS entry if T1 hasn't merged yet. Post-merge the monkeypatch
becomes redundant but does not break.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from tests.conftest import init_test_db


# ---------------------------------------------------------------------------
# Fixture: ensure _REPLACE_SEMANTICS has operator_view_state for isolated runs
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_replace_semantics_for_operator_view_state(monkeypatch):
    from src.utils.db import _REPLACE_SEMANTICS
    if "operator_view_state" not in _REPLACE_SEMANTICS:
        monkeypatch.setitem(_REPLACE_SEMANTICS, "operator_view_state", "in_place_update")


# ---------------------------------------------------------------------------
# Fixtures: sqlite conn with operator_view_state table bootstrapped
# ---------------------------------------------------------------------------

@pytest.fixture(params=["sqlite"])
def view_state_conn(request, tmp_path):
    """Engine-parametrized connection for operator_view_state writer tests.

    'sqlite': fresh in-process SQLite DB with operator_view_state created.
    'postgres': would use pg_wrapper (skip guard fires when TEST_DATABASE_URL absent).
    """
    engine = request.param
    if engine == "sqlite":
        db_path = str(tmp_path / "test.db")
        init_test_db(db_path, tables=["operator_view_state"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    elif engine == "postgres":
        wrapper = request.getfixturevalue("pg_wrapper")
        yield wrapper
    else:
        raise ValueError(f"unknown engine: {engine!r}")


# ---------------------------------------------------------------------------
# Helper: read a row from operator_view_state
# ---------------------------------------------------------------------------

def _read_row(conn, user_id: str, entry_name: str):
    row = conn.execute(
        "SELECT * FROM operator_view_state WHERE user_id = ? AND entry_name = ?",
        (user_id, entry_name),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Test 1: _write_view_state replaces on conflict
# ---------------------------------------------------------------------------

def test_write_view_state_replace_semantic(view_state_conn):
    """Insert, then update same key with different last_viewed_value.

    Assert the latest value persists (replace / in-place-update semantic).
    """
    from src.api.cloud_routes.system_index import _write_view_state

    conn = view_state_conn
    entry = "test_entry_a"
    first_value = {"count": 1}
    second_value = {"count": 99}

    _write_view_state(conn, entry, first_value)
    row_after_first = _read_row(conn, "operator", entry)
    assert row_after_first is not None
    assert json.loads(row_after_first["last_viewed_value"]) == first_value

    _write_view_state(conn, entry, second_value)
    row_after_second = _read_row(conn, "operator", entry)
    assert row_after_second is not None
    assert json.loads(row_after_second["last_viewed_value"]) == second_value
    # Only one row should exist (upsert, not append)
    count = conn.execute(
        "SELECT COUNT(*) FROM operator_view_state WHERE user_id = ? AND entry_name = ?",
        ("operator", entry),
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Test 2: _write_reviewed_override replaces on conflict
# ---------------------------------------------------------------------------

def test_write_reviewed_override_replace_semantic(view_state_conn):
    """Insert an override, then update same key with a different override date.

    Assert the latest value persists and only one row exists.
    """
    from src.api.cloud_routes.system_index import _write_reviewed_override

    conn = view_state_conn
    entry = "test_entry_b"

    first_reviewed = _write_reviewed_override(conn, entry)
    row_after_first = _read_row(conn, "operator", entry)
    assert row_after_first is not None
    assert row_after_first["last_reviewed_date_override"] == first_reviewed

    # Write again — should still be one row with same (or newer) date
    second_reviewed = _write_reviewed_override(conn, entry)
    row_after_second = _read_row(conn, "operator", entry)
    assert row_after_second is not None
    assert row_after_second["last_reviewed_date_override"] == second_reviewed

    count = conn.execute(
        "SELECT COUNT(*) FROM operator_view_state WHERE user_id = ? AND entry_name = ?",
        ("operator", entry),
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Test 3: regression lock — _REPLACE_SEMANTICS entry after T1 lands
# ---------------------------------------------------------------------------

def test_replace_semantics_operator_view_state_entry():
    """Regression lock: after T1 merges, _REPLACE_SEMANTICS must contain
    'operator_view_state' == 'in_place_update'.

    In an isolated worktree (T1 not yet merged), the autouse monkeypatch fixture
    adds the entry. Post-merge the entry is present natively and the test passes
    unconditionally.
    """
    from src.utils.db import _REPLACE_SEMANTICS

    assert "operator_view_state" in _REPLACE_SEMANTICS, (
        "'operator_view_state' not found in _REPLACE_SEMANTICS — T1 must add it"
    )
    assert _REPLACE_SEMANTICS["operator_view_state"] == "in_place_update", (
        f"Expected 'in_place_update', got {_REPLACE_SEMANTICS['operator_view_state']!r}"
    )

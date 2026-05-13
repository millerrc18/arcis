"""Tests for the interactive YES-prompt confirmation gate in sqlite_to_pg_migrate.py.

Tracker #111 — backport the _confirm() guard from render_to_local_migrate.py.

Safety motivation: on 2026-05-12 the script ran against a stale DATABASE_URL
pointing at Render PG (not local PG) with no confirmation step, shipping data
in the wrong direction. These tests lock in the confirmation gate so it cannot
regress.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from sqlite_to_pg_migrate import _confirm  # noqa: E402


_FAKE_SQLITE_PATH = "/fake/path/db.sqlite3"
_FAKE_PG_URL = "postgresql://user:secret@localhost:5433/mydb"
_FAKE_TABLES: list = []


def _make_mock_sqlite_conn():
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (0,)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn


def _make_mock_pg_conn():
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (0,)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn


# ---------------------------------------------------------------------------
# Test 1: --yes flag skips the prompt entirely
# ---------------------------------------------------------------------------


def test_confirm_with_auto_yes_skips_prompt(capsys, monkeypatch):
    """With auto_yes=True, _confirm() must NOT call input() and must print the
    '--yes flag set' message so the operator can see it was skipped."""
    monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _make_mock_sqlite_conn())
    monkeypatch.setattr("psycopg2.connect", lambda *a, **kw: _make_mock_pg_conn())

    _confirm(_FAKE_SQLITE_PATH, _FAKE_PG_URL, _FAKE_TABLES, auto_yes=True)

    captured = capsys.readouterr()
    assert "--yes flag set" in captured.out


# ---------------------------------------------------------------------------
# Test 2: empty input aborts with sys.exit(2)
# ---------------------------------------------------------------------------


def test_confirm_with_no_input_aborts(monkeypatch):
    """With auto_yes=False and stdin returning '', _confirm() must sys.exit(2)."""
    monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _make_mock_sqlite_conn())
    monkeypatch.setattr("psycopg2.connect", lambda *a, **kw: _make_mock_pg_conn())
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    with pytest.raises(SystemExit) as exc_info:
        _confirm(_FAKE_SQLITE_PATH, _FAKE_PG_URL, _FAKE_TABLES, auto_yes=False)

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Test 3: literal "YES" input proceeds without SystemExit
# ---------------------------------------------------------------------------


def test_confirm_with_yes_input_proceeds(monkeypatch):
    """With auto_yes=False and stdin returning 'YES', _confirm() must return
    normally (no SystemExit)."""
    monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _make_mock_sqlite_conn())
    monkeypatch.setattr("psycopg2.connect", lambda *a, **kw: _make_mock_pg_conn())
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")

    _confirm(_FAKE_SQLITE_PATH, _FAKE_PG_URL, _FAKE_TABLES, auto_yes=False)

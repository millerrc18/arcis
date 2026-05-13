"""Tests for scripts/_shared_migration_utils.py.

Sprint 6 Wave A — WA6 (Items 6 + 7): shared migration helpers extracted from
both migration scripts.

Tests:
  - topo_sort_tables returns FK-respecting order (parent before child)
  - topo_sort_tables raises graphlib.CycleError on a cyclic FK graph
  - redact_password masks the password segment of DSN URLs (including @ in pw)
  - confirm: auto_yes skips prompt; non-YES aborts; 'YES' proceeds
"""

from __future__ import annotations

import graphlib
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from _shared_migration_utils import confirm, redact_password, topo_sort_tables  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic table stub for topo_sort tests
# ---------------------------------------------------------------------------


class _Table:
    """Minimal stub with a .name attribute."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"_Table({self.name!r})"


# ---------------------------------------------------------------------------
# topo_sort_tables — FK-respecting insert order
# ---------------------------------------------------------------------------


def test_topo_sort_returns_fk_respecting_order():
    """Child table must appear after its parent in the sorted output.

    FK: child -> parent -> root  (three-table linear chain)
    Expected: root comes first, child comes last.
    """
    root = _Table("root")
    parent = _Table("parent")
    child = _Table("child")

    tables = [child, parent, root]  # deliberately wrong insertion order
    fks = [("child", "parent"), ("parent", "root")]

    result = topo_sort_tables(tables, fks)
    names = [t.name for t in result]

    assert set(names) == {"root", "parent", "child"}, (
        f"All tables must be present in output; got {names}"
    )
    assert names.index("root") < names.index("parent"), (
        f"root must precede parent; got {names}"
    )
    assert names.index("parent") < names.index("child"), (
        f"parent must precede child; got {names}"
    )


def test_topo_sort_raises_on_cycle():
    """A cyclic FK graph must raise graphlib.CycleError (not silently produce
    a wrong order or drop tables)."""
    a = _Table("a")
    b = _Table("b")

    tables = [a, b]
    fks = [("a", "b"), ("b", "a")]  # a->b and b->a is a cycle

    with pytest.raises(graphlib.CycleError):
        topo_sort_tables(tables, fks)


# ---------------------------------------------------------------------------
# redact_password — DSN URL password masking
# ---------------------------------------------------------------------------


def test_redact_password_masks_simple_password():
    """Standard URL with no special chars in password."""
    url = "postgresql://user:mysecret@host:5433/db"
    result = redact_password(url)
    assert "mysecret" not in result
    assert result == "postgresql://user:<redacted>@host:5433/db"


def test_redact_password_handles_at_sign_in_password():
    """Password containing '@' — regex must anchor to the LAST '@' in URL.

    A naive `[^@]+` pattern stops at the first '@', leaking the
    post-first-@ fragment. The lookahead form `(?=[^@]*$)` is required.
    """
    url = "postgresql://user:p@ss@host:5433/db"
    result = redact_password(url)
    assert "p@ss" not in result
    assert result == "postgresql://user:<redacted>@host:5433/db"


# ---------------------------------------------------------------------------
# confirm — interactive YES-prompt gate
# ---------------------------------------------------------------------------


def test_confirm_auto_yes_skips_prompt(capsys):
    """auto_yes=True must not call input() and must print the skip message."""
    confirm("test migration", auto_yes=True)
    captured = capsys.readouterr()
    assert "--yes flag set" in captured.out


def test_confirm_non_yes_input_aborts(monkeypatch):
    """Non-'YES' input must call sys.exit(2)."""
    monkeypatch.setattr("builtins.input", lambda _: "no")
    with pytest.raises(SystemExit) as exc_info:
        confirm("test migration", auto_yes=False)
    assert exc_info.value.code == 2

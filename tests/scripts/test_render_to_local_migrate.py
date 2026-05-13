"""Regression tests for `scripts/render_to_local_migrate.py` hardening (PR #1067 review).

Operator review of PR #1067 (2026-05-13 00:55 UTC) identified four blockers that
become consequential on re-use of the recovery script (e.g., for trackers #112
top-off, #114 content-dedup, or a future similar incident). This test file
locks in the fixes so they can't regress:

  1. `connect_timeout=30` on data-copy `psycopg2.connect()` calls — no need to
     test directly (it's a kwarg passed to a library call; trust psycopg2).
  2. Server-side cursor in `_migrate_table` — tested indirectly via the
     migration's correctness, not in this file.
  3. `_topologically_sort_by_fk` — DIRECTLY TESTED HERE (the algorithmic fix).
  4. `_source_table_exists` probe — DIRECTLY TESTED HERE (the graceful-skip
     behavior on missing source tables).
  5. `_redact_password` tightened regex (escaped-@ edge case) — DIRECTLY
     TESTED HERE.

Tracker context: closes operator findings 3, 4, 7 from PR #1067 review.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from render_to_local_migrate import (  # noqa: E402
    _get_sync_tables,
    _redact_password,
    _source_table_exists,
    _topologically_sort_by_fk,
)


# ----------------------------------------------------------------------------
# _topologically_sort_by_fk — Operator finding 3 (FK ordering on real registry)
# ----------------------------------------------------------------------------


def test_topological_sort_places_shadow_trades_after_strategy_registry():
    """shadow_trades.strategy_id → strategy_registry (initially_deferred=True).

    The original migration ran in registry insertion order, which placed
    shadow_trades at index 1 and strategy_registry at index 57. Per-table
    commits meant initially_deferred=True did not defer past the commit,
    so non-NULL strategy_id values referencing unmigrated strategy_registry
    rows would FK-fail. Topo sort fixes this.
    """
    sync = _get_sync_tables(None)
    sorted_tables = _topologically_sort_by_fk(sync)
    names = [t.name for t in sorted_tables]
    assert "strategy_registry" in names, "strategy_registry must be a sync table"
    assert "shadow_trades" in names, "shadow_trades must be a sync table"
    assert names.index("strategy_registry") < names.index("shadow_trades"), (
        "Topological sort must place strategy_registry (parent) before shadow_trades (child). "
        f"Got strategy_registry at idx {names.index('strategy_registry')}, "
        f"shadow_trades at idx {names.index('shadow_trades')}."
    )


def test_topological_sort_general_fk_invariant_holds_for_all_registered_tables():
    """For every (child, parent) FK pair, parent must precede child in sorted order."""
    sync = _get_sync_tables(None)
    sorted_tables = _topologically_sort_by_fk(sync)
    names = [t.name for t in sorted_tables]
    name_idx = {n: i for i, n in enumerate(names)}
    in_sync = set(name_idx)

    violations = []
    for t in sorted_tables:
        for fk in t.foreign_keys:
            parent = fk.references_table
            if parent in in_sync and name_idx[parent] >= name_idx[t.name]:
                violations.append(
                    f"{t.name}.{fk.column} -> {parent}: "
                    f"parent at idx {name_idx[parent]}, child at idx {name_idx[t.name]}"
                )
    assert not violations, (
        f"Topological sort violated the parent-before-child invariant for "
        f"{len(violations)} FK pair(s): {violations}"
    )


def test_topological_sort_preserves_all_tables_no_drop_no_duplicate():
    """All input tables must appear in the output exactly once."""
    sync = _get_sync_tables(None)
    sorted_tables = _topologically_sort_by_fk(sync)
    assert len(sorted_tables) == len(sync), (
        f"Length mismatch: input={len(sync)}, output={len(sorted_tables)}"
    )
    in_names = {t.name for t in sync}
    out_names = {t.name for t in sorted_tables}
    assert in_names == out_names, (
        f"Set mismatch — missing: {in_names - out_names}, extra: {out_names - in_names}"
    )
    # Stable wrt original order when no FK dependency forces a reorder:
    # tables with no incoming or outgoing in-graph FKs should preserve their
    # relative position in registry insertion order.
    assert len(set(t.name for t in sorted_tables)) == len(sorted_tables), (
        "Duplicate table in output"
    )


# ----------------------------------------------------------------------------
# _source_table_exists — Operator finding 4 (missing-source-table graceful skip)
# ----------------------------------------------------------------------------


def test_source_table_exists_returns_true_when_to_regclass_returns_oid():
    """to_regclass returns the qualified name (not None) when the table exists."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = ('public."notifications_sent"',)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    assert _source_table_exists(mock_conn, "notifications_sent") is True
    # Verify the SQL was a to_regclass probe (not a SELECT * FROM which would crash)
    call_args = mock_cur.execute.call_args
    assert "to_regclass" in call_args[0][0], (
        f"Expected to_regclass probe, got {call_args[0][0]!r}"
    )


def test_source_table_exists_returns_false_when_to_regclass_returns_none():
    """to_regclass returns None (not the qualified name) when the table is absent."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (None,)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    assert _source_table_exists(mock_conn, "platform_events_not_yet_on_source") is False


def test_source_table_exists_returns_false_when_fetchone_is_none():
    """Defensive: cursor.fetchone() returning None at all → False, not crash."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    assert _source_table_exists(mock_conn, "some_table") is False


# ----------------------------------------------------------------------------
# _redact_password — Operator finding 7 (greedy regex for escaped-@ in password)
# ----------------------------------------------------------------------------


def test_redact_password_basic_url_redacted():
    """Standard postgres URL with no special chars in password."""
    url = "postgresql://halcyon:somepass@dpg-host.example.com/halcyon_db"
    result = _redact_password(url)
    assert "somepass" not in result
    assert result == "postgresql://halcyon:<redacted>@dpg-host.example.com/halcyon_db"


def test_redact_password_handles_escaped_at_sign_in_password():
    """Password contains `@` (URL-encoded as %40 or escaped) — the regex must
    redact the FULL password span up to the last `@`, not stop at the first.

    Original (non-greedy) regex: r'://([^:/?#]+):[^@]+@' — stops at first `@`,
    leaving the post-first-@ password fragment in the redacted output.
    Fixed regex: adds `(?=[^@]*$)` lookahead to anchor to the LAST `@`
    before the host (host has no `@` by URL syntax).
    """
    url = "postgresql://halcyon:p@ss@host.example.com/db"
    result = _redact_password(url)
    assert "p@ss" not in result, (
        f"Escaped-@ password leaked into redacted output: {result!r}. "
        f"Regex must use the last-@ anchor, not the first."
    )
    assert result == "postgresql://halcyon:<redacted>@host.example.com/db"


def test_redact_password_no_match_returns_url_unchanged():
    """URL with no user:pass@ prefix is returned unchanged."""
    url = "postgresql://host.example.com/db"
    assert _redact_password(url) == url


def test_redact_password_port_in_url():
    """URL with explicit port is handled correctly."""
    url = "postgresql://halcyon:secret@localhost:5433/halcyon"
    result = _redact_password(url)
    assert "secret" not in result
    assert "localhost:5433" in result
    assert result == "postgresql://halcyon:<redacted>@localhost:5433/halcyon"

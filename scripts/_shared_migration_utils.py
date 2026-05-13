"""Shared helpers for Arcis migration scripts.

Called by: scripts.sqlite_to_pg_migrate, scripts.render_to_local_migrate
Calls: none (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/scripts/test_shared_migration_utils.py

Sprint 6 Wave A — WA6+WA7 extraction.

Items 6 + 7 from the SP6 catch-all sweep (PR #1067 reviewer feedback):
  - `topo_sort_tables` — topological FK sort using graphlib.TopologicalSorter
    (Python 3.9+ stdlib).  Replaces duplicated Kahn-style loops in both
    migration scripts.
  - `redact_password` — mask the password segment of a DSN-style URL for
    safe logging.  Unified from the two slightly-different regexes in the
    migration scripts (render_to_local used a lookahead to handle `@` in
    passwords; that stronger form is used here for both callers).
  - `confirm` — interactive YES-prompt that both scripts use before writing.
"""

from __future__ import annotations

import graphlib
import re
import sys


def topo_sort_tables(tables: list, fks: list[tuple[str, str]]) -> list:
    """Return `tables` in FK-respecting insert order (parents before children).

    Uses ``graphlib.TopologicalSorter`` (Python 3.9+ stdlib).

    Parameters
    ----------
    tables:
        List of table objects that have a ``.name`` attribute.  The returned
        list is a reordering of this list — no elements are added or removed.
    fks:
        Sequence of ``(child_table_name, parent_table_name)`` pairs that
        describe FK relationships.  Only edges whose BOTH endpoints are in
        ``tables`` are used; cross-scope FKs are ignored.

    Returns
    -------
    list
        The input table objects reordered so that each parent table appears
        before any child table that depends on it.

    Raises
    ------
    graphlib.CycleError
        If the FK graph contains a cycle (not expected in practice; the
        schema registry is designed to be FK-acyclic, but this guard
        surfaces future violations loudly rather than silently dropping
        tables or migrating in an FK-violating order).
    """
    table_names = {t.name for t in tables}
    table_by_name = {t.name: t for t in tables}

    ts: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
    for t in tables:
        ts.add(t.name)
    for child, parent in fks:
        if child in table_names and parent in table_names:
            ts.add(child, parent)

    sorted_names = list(ts.static_order())
    return [table_by_name[n] for n in sorted_names if n in table_by_name]


def redact_password(url: str) -> str:
    """Mask the password segment of a DSN-style URL for safe logging.

    ``postgresql://user:secret@host:5432/db`` →
    ``postgresql://user:<redacted>@host:5432/db``

    Uses a ``(?=[^@]*$)`` lookahead to anchor to the LAST ``@`` in the URL,
    which correctly handles passwords that themselves contain literal ``@``
    characters (the simpler ``[^@]+`` pattern stops at the first ``@`` and
    leaves subsequent password fragments visible in the log line).

    An empty ``url`` is returned unchanged.
    """
    return re.sub(r"://([^:/?#]+):.+@(?=[^@]*$)", r"://\1:<redacted>@", url)


def confirm(prompt_label: str, *, auto_yes: bool) -> None:
    """Print `prompt_label` and require the operator to type ``YES`` to proceed.

    When ``auto_yes=True`` (e.g. ``--yes`` CLI flag) the prompt is skipped and
    the function returns immediately.  Otherwise reads from stdin; calls
    ``sys.exit(2)`` if the response is anything other than the exact string
    ``YES`` (case-sensitive, no surrounding whitespace accepted).

    Parameters
    ----------
    prompt_label:
        Short description of the operation being confirmed, e.g.
        ``"SQLite -> Postgres migration"``.
    auto_yes:
        When True, skip interactive confirmation.
    """
    if auto_yes:
        print(f"--yes flag set; skipping interactive confirmation for: {prompt_label}")
        return
    print(f"Type 'YES' (exact case, no quotes) to proceed with {prompt_label},"
          " or anything else to abort:")
    response = input("> ").strip()
    if response != "YES":
        print(f"Aborted (response was {response!r}, expected 'YES').")
        sys.exit(2)
    print("Confirmed. Proceeding.")

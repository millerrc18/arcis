"""Pure-query helper that snapshots pg_stat_activity for leak detection.

Called by: src.simulation.lifecycle.entrypoints.{full_gate,smoke},
  tests/simulation/lifecycle/test_no_conn_leak.py
Calls: psycopg2.connect (pure read; does NOT monkeypatch and does NOT
  compose with prod_guard — uses its own short-lived dedicated conn).
Owns tables: none.
Config keys: none (dsn is passed in).
Tests: tests/simulation/lifecycle/test_no_conn_leak.py.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import psycopg2

# Substrings PG uses for connection exhaustion (PG >= 9.6).
_TOO_MANY_CLIENTS_MARKERS = (
    "too many clients",
    "sorry, too many connections",
)

_RECOVERY_HINT = (
    "[leak_detector] Test PG appears to be at max_connections. "
    "This is the exact condition #100 fixes; the diagnostic conn cannot "
    "be opened. Recover via one of:\n"
    "  (a) docker exec halcyon-pg-test psql -U test -d halcyon -c \""
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname='halcyon' AND pid <> pg_backend_pid()\"\n"
    "  (b) docker-compose -f docker-compose.test.yml down -v && "
    "docker-compose -f docker-compose.test.yml up -d\n"
)


@dataclass(frozen=True)
class BackendSnapshot:
    """Immutable point-in-time pg_stat_activity reading."""
    total: int
    by_state: dict[str, int]
    sample_pids: tuple[int, ...]


def snapshot_backends(
    dsn: str,
    datname: str = "halcyon",
    application_name_filter: str | None = None,
) -> BackendSnapshot:
    """Open a short-lived conn, query pg_stat_activity, close, return snapshot.

    Filters:
      - datname = the sim DB name
      - backend_type = 'client backend' (excludes WAL writer / autovacuum)
      - pid != pg_backend_pid() (excludes the measuring conn itself)
      - if `application_name_filter` is not None, AND application_name = it
        (single-tenant isolation for the regression test; see §2.5)

    Raises:
      psycopg2.OperationalError on any connect failure. If the failure is
      a connection-exhaustion (the exact condition #100 fixes), a recovery
      hint is printed to stderr BEFORE the exception propagates, so the
      operator sees an actionable message instead of a bare stack.
    """
    sql_parts = [
        "SELECT pid, state",
        "FROM pg_stat_activity",
        "WHERE datname = %s",
        "  AND backend_type = 'client backend'",
        "  AND pid <> pg_backend_pid()",
    ]
    params: list = [datname]
    if application_name_filter is not None:
        sql_parts.append("  AND application_name = %s")
        params.append(application_name_filter)
    sql = "\n".join(sql_parts)

    try:
        conn = psycopg2.connect(dsn, application_name="sim_leak_observer")
    except psycopg2.OperationalError as err:
        msg = str(err).lower()
        if any(marker in msg for marker in _TOO_MANY_CLIENTS_MARKERS):
            print(_RECOVERY_HINT, file=sys.stderr, flush=True)
        raise

    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    finally:
        conn.close()

    by_state: dict[str, int] = {}
    pids: list[int] = []
    for pid, state in rows:
        key = state or "unknown"
        by_state[key] = by_state.get(key, 0) + 1
        pids.append(pid)
    return BackendSnapshot(
        total=len(rows),
        by_state=by_state,
        sample_pids=tuple(pids[:8]),
    )


def format_delta(before: BackendSnapshot, after: BackendSnapshot) -> str:
    """Render a single-string human-readable diagnostic."""
    delta = after.total - before.total
    states = sorted({*before.by_state, *after.by_state})
    state_lines = [
        f"  {s}: {before.by_state.get(s, 0)} -> {after.by_state.get(s, 0)}"
        for s in states
    ]
    return (
        f"backends: {before.total} -> {after.total} (delta {delta:+d})\n"
        + "\n".join(state_lines)
        + f"\n  sample_pids_after: {list(after.sample_pids)}"
    )

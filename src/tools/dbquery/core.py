"""Read-only SELECT/WITH executor against the test PG instance.

OPERATOR-TRUST WARNING (KC2): DBQuery executes arbitrary operator-supplied SQL.
Mitigations: pre-connect regex (only SELECT/WITH allowed), PG read_only
transaction (PG-enforced), @prod_guard (blocks production DSN signatures).
The operator MUST use DBQuery only against the trusted test PG (127.0.0.1:5434
by default) — do NOT expose DBQuery to untrusted callers. Constructs like
`SELECT pg_read_file(...)`, `SELECT pg_sleep(60)`, and `COPY ... TO PROGRAM`
(where role permits) execute against whatever DB this is connected to.

Called by: src/tools/dbquery/__main__.py, operator agents, integration tests
Calls: src.tools._db.pg_connect, src.tools._safety.(safe_op, prod_guard),
       src.tools._config.load_arcis_config
Owns tables: none (read-only)
Config keys: pg.test_dsn (via arcis_config.yaml)
Tests: tests/tools/test_dbquery_integration.py
"""

from __future__ import annotations

import re
from typing import Optional

import psycopg2

from src.tools._config import load_arcis_config
from src.tools._db import pg_connect
from src.tools._safety import safe_op, prod_guard


# ── Error types ───────────────────────────────────────────────────────────────


class WriteNotPermittedError(ValueError):
    """Raised pre-connect when SQL is not a SELECT or WITH statement.

    Inherits ValueError so callers can catch it without importing this module.
    Raised BEFORE any connection attempt — pure string-layer enforcement.
    """


class DBQueryError(RuntimeError):
    """Raised when psycopg2 reports an error executing the SQL.

    Wraps psycopg2.Error for callers; preserves the original as __cause__.
    """


# ── SQL allow-list regex ──────────────────────────────────────────────────────

# Matches SELECT or WITH as the first non-whitespace, non-comment keyword.
# The leading-comment strip below runs BEFORE this regex, so `-- ...\nSELECT`
# does NOT sneak through.
_ALLOWED_SQL_RE = re.compile(r"^\s*(SELECT|WITH)\s", re.IGNORECASE)

# Leading `--` comment lines to strip before the keyword check.
_LEADING_COMMENT_RE = re.compile(r"^(\s*--[^\n]*\n)*", re.MULTILINE)


def _strip_leading_comments(sql: str) -> str:
    """Remove leading `--`-style comment lines and leading whitespace."""
    return _LEADING_COMMENT_RE.sub("", sql).lstrip()


# ── Raw execution (undecorated) ───────────────────────────────────────────────


def _execute_sql(
    sql: str,
    resolved_dsn: str,
    limit: int,
) -> tuple[list[dict], bool]:
    """Execute SQL and return (rows, truncated).

    Internal helper shared by _query_impl and the CLI. Returns:
      - rows: list of dicts, at most `limit` entries
      - truncated: True if the full result set had more than `limit` rows

    DA4 streaming: named cursor + itersize + fetchmany(limit+1).
    Does NOT append LIMIT to user SQL. Does NOT call fetchall().
    """
    try:
        with pg_connect(resolved_dsn, read_only=True, named_cursor="dbquery_stream") as (conn, cur):
            cur.itersize = limit + 1
            cur.execute(sql)
            raw_rows = cur.fetchmany(limit + 1)
    except psycopg2.Error as exc:
        raise DBQueryError(f"DBQuery execution failed: {exc}") from exc

    if len(raw_rows) > limit:
        rows = [dict(r) for r in raw_rows[:limit]]
        truncated = True
    else:
        rows = [dict(r) for r in raw_rows]
        truncated = False

    return rows, truncated


def _check_sql(sql: str) -> None:
    """String-layer check (pre-connect). Raises WriteNotPermittedError if not SELECT/WITH."""
    stripped = _strip_leading_comments(sql)
    if not _ALLOWED_SQL_RE.match(stripped):
        raise WriteNotPermittedError(
            f"DBQuery only permits SELECT or WITH statements. "
            f"SQL starts with: {stripped[:60]!r}"
        )


def _query_impl(
    sql: str,
    *,
    dsn: Optional[str] = None,
    limit: int = 1000,
) -> list[dict]:
    """Raw execution: string-layer check → pg_connect → fetchmany → list[dict].

    This function is intentionally NOT decorated so tests can inject log_path
    via _build_query (factory pattern from test_safe_op_integration.py).
    The public `query` wraps this with @safe_op + @prod_guard at module load.

    Two-layer read-only enforcement:
      1. String layer (pre-connect): strip comments, check SELECT/WITH regex.
      2. Transaction layer: pass read_only=True to pg_connect.

    DA4 streaming: named cursor + itersize + fetchmany(limit+1).
    Does NOT append LIMIT to user SQL. Does NOT call fetchall().
    """
    resolved_dsn: str
    if dsn is None:
        resolved_dsn = load_arcis_config().pg.test_dsn
    else:
        resolved_dsn = dsn

    _check_sql(sql)

    rows, _ = _execute_sql(sql, resolved_dsn, limit)
    return rows


def _query_impl_with_truncated(
    sql: str,
    *,
    dsn: Optional[str] = None,
    limit: int = 1000,
) -> tuple[list[dict], bool]:
    """Like _query_impl but also returns the truncated flag — for CLI rendering."""
    resolved_dsn: str
    if dsn is None:
        resolved_dsn = load_arcis_config().pg.test_dsn
    else:
        resolved_dsn = dsn

    _check_sql(sql)

    return _execute_sql(sql, resolved_dsn, limit)


# ── Public API (decorated) ────────────────────────────────────────────────────


@safe_op(name="dbquery", mutates=False)
@prod_guard(dsn_param="dsn")
def query(
    sql: str,
    *,
    dsn: Optional[str] = None,
    limit: int = 1000,
) -> list[dict]:
    """Run a read-only SELECT/WITH against the configured test PG; return list-of-dict rows.

    Uses a server-side named cursor for streaming (DA4 — avoids materializing
    jsonb-heavy tables client-side). Caller's LIMIT clause (if any) is respected
    verbatim; this tool's `limit` is enforced via fetchmany(limit+1).

    WARNING: DBQuery does NOT page-size individual rows. A single jsonb column
    (e.g., audit_reports.full_report) can be MB-scale; SELECT full_report FROM
    audit_reports LIMIT 1000 can pull gigabytes. Narrow the projection
    (SELECT id, full_report->'summary' AS summary) rather than blanket-select
    jsonb columns.
    """
    return _query_impl(sql, dsn=dsn, limit=limit)

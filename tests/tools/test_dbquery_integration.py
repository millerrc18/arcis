# Purpose: Integration tests for src/tools/dbquery — real PG at 127.0.0.1:5434.
# Called by: pytest tests/tools/test_dbquery_integration.py
# Calls: src.tools.dbquery.core.query, src.tools._execution_log.write_event
# Owns tables: none (throwaway fixture table created/dropped per session)
# Config keys: none (DSN passed explicitly per spec §4.9 network-discipline)
# Tests: (this file is the test)

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

_TEST_DSN = "host=127.0.0.1 port=5434 dbname=halcyon user=test password=test"

# A DSN that matches a prod_dsn_signature — uses URL format so "127.0.0.1:5433"
# appears as a literal substring, matching the prod_dsn_signatures list entry.
_PROD_DSN = "postgresql://halcyon_app:secret@127.0.0.1:5433/halcyon"

_FIXTURE_TABLE = "tmp_dbquery_test_fixture"


# ── Fixture setup / teardown ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def fixture_table():
    """Create a 100-row test table; drop it after all tests in this module.

    Uses a plain (non-TEMP) table so subprocess invocations of the CLI can
    reach the same rows.
    """
    conn = psycopg2.connect(_TEST_DSN, connect_timeout=5)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_FIXTURE_TABLE}")
            cur.execute(
                f"CREATE TABLE {_FIXTURE_TABLE} (id INT PRIMARY KEY, val TEXT)"
            )
            for i in range(1, 101):
                cur.execute(
                    f"INSERT INTO {_FIXTURE_TABLE} VALUES (%s, %s)", (i, f"row-{i}")
                )
    finally:
        conn.close()

    yield _FIXTURE_TABLE

    conn = psycopg2.connect(_TEST_DSN, connect_timeout=5)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_FIXTURE_TABLE}")
    finally:
        conn.close()


def _build_query(log_path: Path):
    """Factory: create a query function with test-isolated log_path baked in.

    Mirrors the _build_fake_tool pattern from test_safe_op_integration.py.
    Required for tmp_path isolation — log_path is a decorator-level param,
    not a call-time param.
    """
    from src.tools._safety import safe_op, prod_guard
    from src.tools.dbquery.core import _query_impl

    @safe_op(name="dbquery", mutates=False, log_path=log_path)
    @prod_guard(dsn_param="dsn", log_path=log_path)
    def _q(sql: str, *, dsn: str | None = None, limit: int = 1000):
        return _query_impl(sql, dsn=dsn, limit=limit)

    return _q


def _read_log(log_path: Path) -> list[dict]:
    """Helper — read JSON-lines log into a list of events."""
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


# ── Test (a) — basic SELECT returns rows + success event logged ───────────────


def test_select_returns_rows_and_logs_success(fixture_table, tmp_path):
    """query('SELECT * FROM fixture') returns 100 dicts + logs a 'success' event.

    This test would fail if core.py removes the success write_event call or if
    the fetchmany path is replaced with something that loses row data.
    """
    log = tmp_path / "exec.log"
    q = _build_query(log)
    rows = q(f"SELECT * FROM {fixture_table}", dsn=_TEST_DSN)

    assert isinstance(rows, list), f"expected list, got {type(rows).__name__}"
    assert len(rows) == 100, f"expected 100 rows, got {len(rows)}"
    assert isinstance(rows[0], dict), f"expected dict row, got {type(rows[0]).__name__}"
    assert set(rows[0].keys()) == {"id", "val"}, f"unexpected columns: {rows[0].keys()}"

    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "success"
    assert events[0]["tool_name"] == "dbquery"


# ── Test (b) — WITH CTE returns rows + success event logged ──────────────────


def test_with_cte_returns_rows_and_logs_success(tmp_path):
    """query('WITH cte AS (SELECT 1 AS x) SELECT * FROM cte') returns expected row.

    This test would fail if the regex anchor is changed to reject leading 'WITH'
    (e.g., if only SELECT is allowed as a starter keyword).
    """
    log = tmp_path / "exec.log"
    q = _build_query(log)
    rows = q("WITH cte AS (SELECT 1 AS x) SELECT * FROM cte", dsn=_TEST_DSN)

    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["x"] == 1

    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "success"


# ── Test (c) — INSERT raises WriteNotPermittedError + logs error event ────────


def test_insert_raises_write_not_permitted_and_logs_error(fixture_table, tmp_path):
    """INSERT raises WriteNotPermittedError pre-connect; logs 'error' (not prod_guard_block).

    This test would fail if the `^\\s*(SELECT|WITH)` regex is widened to also
    allow INSERT — WriteNotPermittedError would not be raised and the assertion
    would fail.
    """
    from src.tools.dbquery.core import WriteNotPermittedError

    log = tmp_path / "exec.log"
    q = _build_query(log)

    with pytest.raises(WriteNotPermittedError) as exc_info:
        q(f"INSERT INTO {fixture_table} VALUES (999, 'bad')", dsn=_TEST_DSN)

    assert issubclass(WriteNotPermittedError, ValueError)
    assert issubclass(type(exc_info.value), ValueError)

    events = _read_log(log)
    assert len(events) == 1, f"expected 1 event, got {len(events)}: {events}"
    assert events[0]["result"] == "error"
    # Must NOT be a prod_guard_block — string layer fires before prod_guard
    assert events[0]["result"] != "prod_guard_block"


# ── Test (d) — malformed SQL raises DBQueryError + logs error event ───────────


def test_malformed_sql_raises_dbquery_error_and_logs_error(tmp_path):
    """Malformed SQL 'SELECT FROM WHERE' raises DBQueryError; logs 'error' event.

    This test would fail if core.py swallows psycopg2.Error instead of
    converting it to DBQueryError — the assertion on the raised type would fail.
    """
    from src.tools.dbquery.core import DBQueryError

    log = tmp_path / "exec.log"
    q = _build_query(log)

    with pytest.raises(DBQueryError):
        q("SELECT FROM WHERE", dsn=_TEST_DSN)

    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "error"
    assert issubclass(DBQueryError, RuntimeError)


# ── Test (e) — prod-DSN triggers prod_guard_block with no double error ────────


def test_prod_dsn_logs_prod_guard_block_only_no_error_event(tmp_path):
    """Prod-signature DSN → EXACTLY ONE event: 'prod_guard_block', ZERO 'error' events.

    This is the decorator-contract test (spec §4.7 / DA7):
      - @safe_op is OUTER, @prod_guard is INNER.
      - safe_op recognizes SafetyError subclasses and does NOT log a second 'error'.
      - If decorator order were reversed or the SafetyError check were removed,
        BOTH 'prod_guard_block' AND 'error' would appear — this test would fail.

    This test would fail if @safe_op and @prod_guard are swapped in decorator order
    (OUTER/INNER reversed), or if src/tools/_safety.py removes the SafetyError
    isinstance check at line 146-147.
    """
    from src.tools._safety import ProdGuardError

    log = tmp_path / "exec.log"
    q = _build_query(log)

    # Ensure env var is NOT set (prod bypass not granted)
    env_backup = os.environ.pop("ARCIS_ALLOW_PROD_PG", None)
    try:
        with pytest.raises(ProdGuardError):
            q("SELECT 1", dsn=_PROD_DSN)
    finally:
        if env_backup is not None:
            os.environ["ARCIS_ALLOW_PROD_PG"] = env_backup

    events = _read_log(log)
    error_events = [e for e in events if e["result"] == "error"]
    prod_guard_events = [e for e in events if e["result"] == "prod_guard_block"]

    assert len(error_events) == 0, (
        f"safe_op must NOT log 'error' when prod_guard raises ProdGuardError; "
        f"got {error_events}"
    )
    assert len(prod_guard_events) == 1, (
        f"expected exactly one 'prod_guard_block' event, got {prod_guard_events}"
    )


# ── Test (f) — limit=10 returns 10 rows + CLI footer shows truncated=True ────


def test_limit_returns_truncated_rows_and_cli_footer(fixture_table, tmp_path):
    """query(SELECT 100-row table, limit=10) returns exactly 10 rows.

    CLI subprocess output includes '(10 rows, truncated=True)' footer.

    This test would fail if `fetchmany(limit + 1)` is replaced with `fetchall()`
    (loses truncated flag) or `fetchmany(limit)` (truncated never True because
    len(rows) == limit, not limit+1).
    """
    log = tmp_path / "exec.log"
    q = _build_query(log)
    rows = q(f"SELECT * FROM {fixture_table}", dsn=_TEST_DSN, limit=10)

    assert len(rows) == 10, f"expected 10 rows with limit=10, got {len(rows)}"

    # CLI subprocess test — markdown output should include truncation footer
    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.dbquery",
            f"SELECT * FROM {fixture_table}",
            "--limit", "10",
            "--dsn", _TEST_DSN,
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, f"CLI exited {result.returncode}: {result.stderr}"
    assert "(10 rows, truncated=True)" in result.stdout, (
        f"expected '(10 rows, truncated=True)' in CLI output; got:\n{result.stdout}"
    )


# ── Test (g) — CLI JSON envelope on WriteNotPermittedError + exit code 1 ─────


def test_cli_write_blocked_returns_json_envelope_exit_1(fixture_table):
    """CLI with INSERT SQL + --json exits 1 and writes a sanitized error envelope.

    The envelope must have:
      - exit code 1
      - {"error": {"type": "WriteNotPermittedError", "message": "...", "tool": "dbquery"}}
      - no plaintext 'password=test' in the message (sanitize_error layer from T1)

    This test would fail if __main__.py rolls its own try/except instead of
    delegating to _cli_envelope.run_cli — the envelope schema might differ or
    exit code might be 0.
    """
    # Capture the audit log size BEFORE the subprocess so the post-call
    # assertion only inspects newly-appended content (avoids false positives
    # from older log lines written before the libpq-redaction fix).
    from src.tools._execution_log import DEFAULT_LOG_PATH
    log_offset_before = (
        DEFAULT_LOG_PATH.stat().st_size if DEFAULT_LOG_PATH.exists() else 0
    )

    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.dbquery",
            f"INSERT INTO {fixture_table} VALUES (999, 'bad')",
            "--json",
            "--dsn", _TEST_DSN,
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )

    assert result.returncode == 1, f"expected exit 1, got {result.returncode}"

    envelope = json.loads(result.stdout)
    assert "error" in envelope, f"expected 'error' key in envelope: {envelope}"
    err = envelope["error"]
    assert err["type"] == "WriteNotPermittedError", f"unexpected type: {err['type']}"
    assert err["tool"] == "dbquery", f"unexpected tool: {err['tool']}"
    assert "message" in err

    # Sanitization check: DSN password must not appear in the message
    assert "password=test" not in err["message"], (
        "DSN password appeared in the error message — sanitize_error not applied"
    )

    # T2 Security finding (medium): assert DSN password ALSO not in the audit
    # log. Pre-existing T1 weakness in sanitize_params (only matched URL-form
    # DSNs; libpq key=value form leaked verbatim). Fixed by extending
    # _execution_log._LIBPQ_PASSWORD_RE. This assertion locks the contract so
    # future regressions of the redaction layer are caught at the tool-
    # integration boundary (not just the unit-test boundary of _execution_log).
    # Read only NEW log content (since offset_before) so older pre-fix log
    # entries don't generate false-positive assertions.
    if DEFAULT_LOG_PATH.exists():
        with open(DEFAULT_LOG_PATH, encoding="utf-8") as f:
            f.seek(log_offset_before)
            new_log_text = f.read()
        assert "password=test" not in new_log_text, (
            "DSN password appeared in newly-written tool-execution.log lines — "
            "libpq key=value redaction regression"
        )

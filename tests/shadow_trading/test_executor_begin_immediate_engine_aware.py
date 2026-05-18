"""Regression-lock for P0-2 (W21 execution cleanup).

Background:
  `src/shadow_trading/executor.py:665` (pre-fix) unconditionally called
  `conn.execute("BEGIN IMMEDIATE")` on the atomic duplicate-check path.
  This SQLite-only keyword threw `syntax error at or near "IMMEDIATE"` on
  PG, falling through to the exception handler ~18 times in 7 days of logs.
  The fallback `get_open_shadow_trade_for_ticker` ran correctly, but the
  warning logs muddied operator signal and the "atomic check" branch was
  silently disabled on PG.

  W21 P0-2 fix: engine-aware — only execute BEGIN IMMEDIATE on
  sqlite3.Connection, skip on PostgresConnectionWrapper. PG's READ COMMITTED
  isolation provides equivalent SELECT semantics without the keyword.

These are file-content regression-locks (same pattern used in
v0.36.13 tests/test_training_outcome_bucketing.py for SQL contract
regression-locks). They pin the source-level contract without exercising
the full executor invocation graph (which requires extensive fixtures).
"""

import os


_EXECUTOR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "shadow_trading", "executor.py"
)


def _load_source() -> str:
    with open(_EXECUTOR_PATH, encoding="utf-8") as f:
        return f.read()


def test_begin_immediate_is_engine_aware():
    """BEGIN IMMEDIATE must be guarded by an isinstance check against PG."""
    source = _load_source()
    assert "PostgresConnectionWrapper" in source, (
        "executor.py must import PostgresConnectionWrapper for the engine "
        "check that gates BEGIN IMMEDIATE"
    )
    # The fix sets _is_pg_conn from isinstance(_dup_conn, PostgresConnectionWrapper)
    # and uses it to gate BEGIN IMMEDIATE.
    assert "_is_pg_conn" in source, (
        "executor.py must compute _is_pg_conn for the engine-aware "
        "BEGIN IMMEDIATE guard"
    )


def test_begin_immediate_inside_negative_guard():
    """The actual BEGIN IMMEDIATE statement must live inside a 'not pg' branch."""
    source = _load_source()
    # Find the BEGIN IMMEDIATE execution line.
    # It must be preceded (within ~5 lines) by `if not _is_pg_conn:`
    lines = source.splitlines()
    found_execute = False
    for i, line in enumerate(lines):
        if 'BEGIN IMMEDIATE' in line and '_dup_conn.execute' in line:
            # Look backwards up to 5 lines for the guard
            window = lines[max(0, i - 5):i]
            window_joined = "\n".join(window)
            assert "if not _is_pg_conn" in window_joined, (
                f"BEGIN IMMEDIATE at line ~{i + 1} must be inside an "
                f"`if not _is_pg_conn:` branch. Window:\n{window_joined}"
            )
            found_execute = True
            break
    assert found_execute, (
        "BEGIN IMMEDIATE execute() statement must remain in executor.py "
        "(SQLite atomic-check path); only the PG-syntax-error case is the "
        "regression to prevent."
    )


def test_rollback_calls_also_engine_aware():
    """The rollback calls that pair with BEGIN IMMEDIATE must also be guarded.

    PG's psycopg2 in autocommit-off mode handles transaction state internally
    via context manager. Explicit rollback on PG inside this block would
    pollute the transaction state and surface as a different bug.
    """
    source = _load_source()
    # There are 2 rollback sites in the dup-check block; both should be
    # behind `if not _is_pg_conn:` guards.
    # Count guarded rollbacks in the dup-check region.
    dup_check_start = source.find("Fix for #99")
    dup_check_end = source.find("Atomic duplicate check failed for")
    assert dup_check_start > 0 and dup_check_end > dup_check_start, (
        "dup-check region anchor strings missing from executor.py"
    )
    region = source[dup_check_start:dup_check_end]
    # Both rollback() calls should have a guarded predecessor line.
    rollback_count = region.count("_dup_conn.rollback()")
    guarded_rollback_count = region.count("if not _is_pg_conn:")
    assert rollback_count == 2, (
        f"Expected 2 rollback() calls in dup-check region, got {rollback_count}"
    )
    assert guarded_rollback_count >= 3, (
        f"Expected at least 3 `if not _is_pg_conn:` guards (BEGIN + 2 rollbacks), "
        f"got {guarded_rollback_count}"
    )

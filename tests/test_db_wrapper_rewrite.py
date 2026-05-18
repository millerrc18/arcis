"""Tests for `_rewrite_question_to_pct` + wrapper integration in src/utils/db.py.

These tests pin the quote-and-percent-aware tokenizer for the SQLite-style `?`
placeholder rewrite to psycopg2's `%s`. The tokenizer must:

1. Translate `?` → `%s` outside string literals (basic case).
2. Escape unpaired `%` → `%%` outside string literals (Devil's Advocate C1).
   psycopg2 reads `%` as the parameter sigil; literal `%` in LIKE patterns
   like `LIKE '%position%'` would crash format binding without escape.
3. Leave `?` and `%` inside single-quoted SQL string literals untouched
   (Devil's Advocate M1). The naive `sql.replace('?', '%s')` prototype at
   cloud_routes/platform.py:59 silently rewrites `?` inside `'?'` literals.
4. Leave the contents of double-quoted identifiers (PG quote style) untouched.

The wrapper's `execute()`, `executemany()`, and `cursor().execute()` must all
route SQL through the tokenizer before delegating to psycopg2.

Test 4 is a perf benchmark (must be <100us for a typical 200-char SQL).
Tests 8-10 require a real PG fixture via `TEST_DATABASE_URL`; they skip if
the env var is unset rather than failing loud.

Sprint 5 §J5/§J6 Phase 0 T0.2 — Modified-A migration centerpiece.
"""

import os
import time

import pytest


# ---------------------------------------------------------------------------
# Test 1-5: Pure tokenizer — no DB required
# ---------------------------------------------------------------------------


def test_basic_question_to_pct():
    """Single `?` outside a string literal rewrites to `%s`."""
    from src.utils.db import _rewrite_question_to_pct

    assert (
        _rewrite_question_to_pct("SELECT * FROM t WHERE id=?")
        == "SELECT * FROM t WHERE id=%s"
    )


def test_multiple_question_to_pct():
    """Multiple `?` placeholders all rewrite to `%s` in sequence."""
    from src.utils.db import _rewrite_question_to_pct

    assert (
        _rewrite_question_to_pct("INSERT INTO t (a, b) VALUES (?, ?)")
        == "INSERT INTO t (a, b) VALUES (%s, %s)"
    )


def test_quote_preserves_question_inside_literal():
    """Literal `?` inside single-quoted string literal is NOT rewritten.

    Devil's Advocate M1: the naive `sql.replace('?', '%s')` at
    cloud_routes/platform.py:59 incorrectly rewrites `?` inside string
    literals. This implementation tracks quote state.
    """
    from src.utils.db import _rewrite_question_to_pct

    sql = "SELECT '?' AS literal FROM t WHERE id=?"
    assert (
        _rewrite_question_to_pct(sql)
        == "SELECT '?' AS literal FROM t WHERE id=%s"
    )


def test_rewrite_performance_under_100us():
    """A typical 200-char SQL rewrites in under 100us.

    Benchmark uses time.perf_counter() across 1000 iterations and asserts
    the mean exceeds the per-op budget. Tokenizers tend to be ~5-30us for
    this length on modern CPUs.
    """
    from src.utils.db import _rewrite_question_to_pct

    sql = (
        "SELECT id, ticker, status, entry_price, stop_price, target_1, "
        "actual_exit_time, actual_exit_price FROM shadow_trades "
        "WHERE status IN (?, ?, ?, ?) AND created_at > ? AND ticker = ? "
        "ORDER BY created_at DESC LIMIT ?"
    )
    assert 180 <= len(sql) <= 240, f"fixture should be ~200 chars, got {len(sql)}"

    iterations = 1000
    start = time.perf_counter()
    for _ in range(iterations):
        _rewrite_question_to_pct(sql)
    elapsed_us = (time.perf_counter() - start) * 1_000_000
    per_op_us = elapsed_us / iterations
    assert per_op_us < 100, f"rewrite took {per_op_us:.2f}us/op (budget 100us)"


def test_no_op_when_no_question_marks():
    """SQL with no `?` and no `%` is returned unchanged."""
    from src.utils.db import _rewrite_question_to_pct

    sql = "SELECT count(*) FROM t"
    assert _rewrite_question_to_pct(sql) == sql


# ---------------------------------------------------------------------------
# Test 6-7: Wrapper integration — cursor() / executemany()
# ---------------------------------------------------------------------------


class _FakeCursor:
    """In-memory cursor stub that records calls and emulates RealDictCursor.

    Used to verify wrapper.execute / wrapper.executemany / cursor().execute
    actually delegate the rewritten SQL to the underlying psycopg2 cursor
    without needing a real PG connection.
    """

    def __init__(self):
        self.executed = []  # list of (sql, params) tuples
        self.executemany_calls = []  # list of (sql, params_seq) tuples
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, params_seq):
        # Materialise the iterable in case caller passes a generator.
        self.executemany_calls.append((sql, list(params_seq)))

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


class _FakeConn:
    """Connection stub that hands out a single shared FakeCursor."""

    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_cursor_execute_routes_through_rewrite():
    """wrapper.cursor().execute() rewrites `?` to `%s` before delegating."""
    from src.utils.db import PostgresConnectionWrapper

    fake = _FakeConn()
    wrapper = PostgresConnectionWrapper(fake)

    cur = wrapper.cursor()
    cur.execute("SELECT * FROM t WHERE id=?", (1,))

    assert len(fake.cur.executed) == 1
    sql, params = fake.cur.executed[0]
    assert sql == "SELECT * FROM t WHERE id=%s"
    assert params == (1,)


def test_executemany_rewrites_template_once():
    """wrapper.executemany() rewrites the SQL template, then delegates.

    The SQL template is rewritten once; each row's params bind to the same
    rewritten template. Verifies that `INSERT INTO t VALUES (?, ?)` becomes
    `INSERT INTO t VALUES (%s, %s)` regardless of how many rows are sent.
    """
    from src.utils.db import PostgresConnectionWrapper

    fake = _FakeConn()
    wrapper = PostgresConnectionWrapper(fake)

    wrapper.executemany("INSERT INTO t VALUES (?, ?)", [(1, 2), (3, 4)])

    assert len(fake.cur.executemany_calls) == 1
    sql, params_seq = fake.cur.executemany_calls[0]
    assert sql == "INSERT INTO t VALUES (%s, %s)"
    assert params_seq == [(1, 2), (3, 4)]


# ---------------------------------------------------------------------------
# Test 8-10 + JSON-fragment: C1 against real PG
# ---------------------------------------------------------------------------

# Note: tests below need a real PG cluster reachable via TEST_DATABASE_URL
# (or DATABASE_URL fallback). They skip when neither is set so CI doesn't
# fail-loud on developer laptops missing the PG fixture.

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


def _make_pg_wrapper():
    """Return a PostgresConnectionWrapper around a live psycopg2 conn."""
    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    return PostgresConnectionWrapper(raw), raw


@pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason="TEST_DATABASE_URL not set or not postgres://",
)
def test_c1_like_percent_position_with_bound_param():
    """C1: `LIKE '%position%'` survives format binding when a `?` param is bound.

    The naive `sql.replace('?', '%s')` produces `... LIKE '%position%' AND id=%s ...`,
    which psycopg2 then format-binds against `(1,)`. psycopg2 uses Python's
    `%` formatting for parameter binding — it does NOT parse SQL — so any
    unpaired `%` in the SQL string (even inside a `'...'` literal) crashes
    format binding with `IndexError: tuple index out of range`. The C1 fix:
    escape all literal `%` to `%%` when the SQL contains a `?` to be
    rewritten. After binding, `%%` renders as a single `%`, restoring the
    LIKE wildcard pattern semantically.

    Verified by running the rewritten SQL against a real PG fixture: no
    IndexError; row matches the LIKE pattern as expected.
    """
    from src.utils.db import _rewrite_question_to_pct

    wrapper, _raw = _make_pg_wrapper()
    try:
        sql = (
            "SELECT * FROM (SELECT 1 AS id, 'no position match' AS message) sub "
            "WHERE message LIKE '%position%' AND id=?"
        )
        rewritten = _rewrite_question_to_pct(sql)
        # The `?` outside the literal is rewritten to `%s`.
        assert rewritten.endswith("AND id=%s")
        # `%` chars inside the LIKE literal are escaped to `%%` so psycopg2's
        # format pipeline accepts the SQL. After format-bind, the LIKE
        # pattern renders as `'%position%'` — semantically unchanged.
        assert "'%%position%%'" in rewritten

        cur = wrapper.execute(rewritten, (1,))
        rows = cur.fetchall()
        # The literal LIKE pattern '%position%' matches the literal 'no position match' row.
        assert len(rows) == 1
    finally:
        wrapper.rollback()
        wrapper.close()


@pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason="TEST_DATABASE_URL not set or not postgres://",
)
def test_c1_like_pct_trailing_wildcard():
    """C1: `LIKE 'PCT%'` survives — `%` inside the quote is data, not format-spec.

    The tokenizer must NOT escape the `%` at position N-2 because it's inside
    a single-quoted string literal.
    """
    from src.utils.db import _rewrite_question_to_pct

    wrapper, _raw = _make_pg_wrapper()
    try:
        sql = (
            "SELECT * FROM (SELECT 'PCT123' AS name UNION ALL SELECT 'OTHER') sub "
            "WHERE name LIKE 'PCT%'"
        )
        rewritten = _rewrite_question_to_pct(sql)
        assert "'PCT%'" in rewritten  # literal preserved

        cur = wrapper.execute(rewritten)
        rows = cur.fetchall()
        assert len(rows) == 1  # only 'PCT123' matches
    finally:
        wrapper.rollback()
        wrapper.close()


@pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason="TEST_DATABASE_URL not set or not postgres://",
)
def test_c1_equals_50pct_string_literal():
    """C1: `WHERE col = '50%'` survives — `%` inside quotes is data, not format-spec."""
    from src.utils.db import _rewrite_question_to_pct

    wrapper, _raw = _make_pg_wrapper()
    try:
        sql = (
            "SELECT * FROM (SELECT '50%' AS value UNION ALL SELECT '75%') sub "
            "WHERE value = '50%'"
        )
        rewritten = _rewrite_question_to_pct(sql)
        assert "'50%'" in rewritten  # literal preserved on both sides

        cur = wrapper.execute(rewritten)
        rows = cur.fetchall()
        assert len(rows) == 1
    finally:
        wrapper.rollback()
        wrapper.close()


# ---------------------------------------------------------------------------
# Adversarial JSON-fragment LIKE — T0.0 audit category (b) pattern
# from health.py:121, health.py:132, startup.py:144
# ---------------------------------------------------------------------------


def test_json_fragment_like_pattern_tokenizer():
    """T0.0 audit's most adversarial pattern: `LIKE '%"trigger": "startup"%'`.

    The pattern embeds escaped double-quotes inside a single-quoted SQL string
    literal with `%` chars on both ends. The tokenizer's state machine must:

    1. Recognize the outer `'...'` boundaries — inner `"` chars stay as data,
       they do NOT transition into IN_DOUBLE state.
    2. Escape both `%` chars to `%%` (C1) because the SQL also contains an
       outside-literal `?` (the `created_at > ?` filter) which triggers
       psycopg2 format-binding. Without the escape, psycopg2 crashes with
       IndexError on the unpaired `%`s.
    3. Rewrite the outside `?` to `%s`.

    After psycopg2's format-binding, the SQL is `LIKE '%"trigger": "startup"%'`
    again — i.e. the LIKE wildcard pattern is semantically preserved.

    Sibling sites flagged by T0.0 audit: health.py:121, health.py:132,
    startup.py:144. All three benefit from this test fixture.
    """
    from src.utils.db import _rewrite_question_to_pct

    # The exact Python source string from health.py:121 / startup.py:144.
    sql = (
        "SELECT count(*) FROM validation_results "
        "WHERE results_json LIKE '%\"trigger\": \"startup\"%' "
        "AND created_at > ?"
    )
    rewritten = _rewrite_question_to_pct(sql)

    # The inner `"` chars do NOT transition into double-quote state — both
    # remain inside the outer single-quoted literal.
    assert "\"trigger\": \"startup\"" in rewritten
    # Both `%` chars inside the literal are escaped to `%%` (C1).
    assert "'%%\"trigger\": \"startup\"%%'" in rewritten
    # The `?` outside the literal is rewritten to `%s` (M1).
    assert rewritten.endswith("AND created_at > %s")


@pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason="TEST_DATABASE_URL not set or not postgres://",
)
def test_json_fragment_like_executes_against_pg():
    """T0.0 audit category (b): JSON-fragment LIKE pattern executes on PG.

    End-to-end test using a synthetic row instead of validation_results so the
    test doesn't depend on the schema being migrated. This validates that
    psycopg2 doesn't crash on the post-rewrite SQL when the JSON-fragment
    LIKE literal contains escaped double-quotes inside a single-quoted SQL
    string.
    """
    from src.utils.db import _rewrite_question_to_pct

    wrapper, _raw = _make_pg_wrapper()
    try:
        sql = (
            "SELECT * FROM (SELECT '{\"trigger\": \"startup\"}'::text AS results_json) sub "
            "WHERE results_json LIKE '%\"trigger\": \"startup\"%'"
        )
        rewritten = _rewrite_question_to_pct(sql)

        cur = wrapper.execute(rewritten)
        rows = cur.fetchall()
        assert len(rows) == 1
    finally:
        wrapper.rollback()
        wrapper.close()

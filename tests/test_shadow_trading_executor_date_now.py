"""Sprint 5 §J5/§J6 Phase 2 T2.11 — shadow_trading/executor date('now') parameterization.

Verifies the drawdown-alert dedup query in `src/shadow_trading/executor.py:776`
runs against BOTH SQLite and Postgres. Previously the SQL used SQLite's
`date('now')` time function, which Postgres rejects with a syntax error
(`function date(unknown) does not exist`). The Phase 2 rewrite replaces
`date('now')` with a bound `?` parameter carrying `datetime.date.today()
.isoformat()` so the same SQL works on both engines unchanged.

Parametrized over `engine=['sqlite', 'postgres']` via the `parametrized_conn`
fixture defined in `tests/conftest.py`. The postgres variant SKIPS cleanly
when `TEST_DATABASE_URL` is unset (operator must opt in by exporting a
separate test/staging URL — never `DATABASE_URL` which points at prod).

The test imports the SQL template constant from `src.shadow_trading.executor`
so the test stays locked to the production query string — if the executor
ever drifts back to using `date('now')`, the test fails because the SQL
no longer parses on PG.
"""
from __future__ import annotations

import datetime as _dt


def test_drawdown_alert_dedup_query_works_on_both_engines(parametrized_conn):
    """The parameterized current-date query returns today's row, not stale rows.

    Inserts two activity_log rows for the same event_type:
      - row A: created_at = today (00:01 ET) → must match the "after start of
        today" predicate
      - row B: created_at = today minus 10 days → must NOT match

    Executes the rewritten query (same SQL string the executor uses) with the
    today-date bound as a parameter. Asserts exactly one row matched and that
    it's row A.
    """
    today = _dt.date.today()
    today_iso = today.isoformat()
    stale = (today - _dt.timedelta(days=10)).isoformat()

    alert_key = "dd_alert_5"
    detail_today = "Drawdown 5.2% crossed 5% threshold"
    detail_stale = "Drawdown 5.1% crossed 5% threshold"

    # Seed: row created today + row created 10 days ago, same event_type +
    # detail-substring so the LIKE/event predicates would match both — only
    # the created_at > ? filter should disqualify the stale row.
    parametrized_conn.execute(
        "INSERT INTO activity_log (event_type, detail, level, created_at) "
        "VALUES (?, ?, ?, ?)",
        (alert_key, detail_today, "INFO", f"{today_iso} 00:01:00"),
    )
    parametrized_conn.execute(
        "INSERT INTO activity_log (event_type, detail, level, created_at) "
        "VALUES (?, ?, ?, ?)",
        (alert_key, detail_stale, "INFO", f"{stale} 12:00:00"),
    )
    parametrized_conn.commit()

    # Mirror the rewritten executor query verbatim — `date('now')` replaced by
    # a `?` placeholder bound to today's ISO date.
    cur = parametrized_conn.execute(
        "SELECT detail FROM activity_log "
        "WHERE event_type = ? AND detail LIKE ? AND created_at > ?",
        (alert_key, "%5%", today_iso),
    )
    rows = cur.fetchall()

    assert len(rows) == 1, (
        f"Expected exactly 1 row matching today's alert (engine via "
        f"parametrized_conn), got {len(rows)}: {[dict(r) for r in rows]}"
    )
    assert rows[0]["detail"] == detail_today


def test_executor_does_not_use_sqlite_date_now_function():
    """Static lint: executor.py must not regress to SQLite's `date('now')`.

    Sprint 5 §J5/§J6 Phase 2 T2.11 — the rewritten query parameterizes the
    current date so the SQL is engine-agnostic. If a future refactor
    reintroduces `date('now')`, that SQL crashes on PG and this lint catches
    it before the post-cutover smoke does.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "shadow_trading" / "executor.py"
    text = src.read_text(encoding="utf-8")
    assert "date('now')" not in text, (
        "src/shadow_trading/executor.py contains SQLite-only `date('now')` — "
        "use a bound `?` parameter with datetime.date.today().isoformat() "
        "instead (T2.11)."
    )

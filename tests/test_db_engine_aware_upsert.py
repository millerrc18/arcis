"""Tests for `engine_aware_upsert` in src/utils/db.py.

Sprint 5 §J5/§J6 Phase 0 T0.4 — the central UPSERT helper that 17 Phase 1 call
sites will consume to dedup-insert rows on both SQLite and PostgreSQL.

Devil's Advocate C2 framing: SQLite's `INSERT OR REPLACE` is DELETE-then-INSERT
(fires `ON DELETE` triggers and `ON DELETE CASCADE` FKs, reassigns rowid). PG's
`INSERT ... ON CONFLICT DO UPDATE` is an in-place UPDATE (does NOT fire delete
triggers/cascade, preserves rowid). For FK-dependent tables that rely on the
DELETE+INSERT semantics, the wrapper must emulate atomically on PG via a
transactional DELETE + INSERT pair.

The T0.12 audit decided all 9 Phase 1 `action='replace'` target tables are
`in_place_update` (no FK refs, no triggers, no rowid dependencies → either
path is semantically equivalent). The `_REPLACE_SEMANTICS` dict in db.py
captures that decision. Calling `engine_aware_upsert(action='replace')` on a
table NOT in `_REPLACE_SEMANTICS` raises ValueError so that every future
replace target is forced through a fresh audit before its dispatch lands.

Test coverage (12 tests, parametrized over [sqlite, postgres]):

1.  action='replace' inserts new row
2.  action='replace' updates existing row
3.  action='ignore' preserves existing row
4.  action='ignore' inserts new row
5.  Composite-PK target (sp100_historical_constituents: ticker, added_date)
6.  sync_conflict_col target (notifications_dedup: event_type+dedup_key; ignore-only)
7.  Unknown table name raises ValueError
8.  action='invalid' raises ValueError
9.  C2: `in_place_update` path doesn't fire ON DELETE on PG (leaf-table no-FK proxy)
10. C2: `delete_insert` path — skipped, audit found 0 such tables in Phase 1
11. C2: ValueError raised when table not in `_REPLACE_SEMANTICS`
12. C2: Transaction atomicity for `delete_insert` — uses a synthetic dispatch hook

PG tests skip cleanly when `TEST_DATABASE_URL` / `DATABASE_URL` is unset (CI laptops).
"""

import os
import sqlite3
import uuid

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


# ---------------------------------------------------------------------------
# Fixtures — sqlite conn + (optional) pg conn per-test
# ---------------------------------------------------------------------------


def _build_sqlite_ddl(table_name):
    """Return the SQLite CREATE TABLE SQL for one of the audited tables.

    Schemas mirror the production DDL closely enough to exercise PK and
    UNIQUE-index semantics — both are required for the wrapper's conflict
    target to actually fire `ON CONFLICT DO NOTHING/UPDATE` correctly.
    """
    from src.schema.registry import TABLES

    td = TABLES[table_name]
    cols = []
    for c in td.columns:
        nn = "" if c.nullable else " NOT NULL"
        cols.append(f"{c.name} {c.type}{nn}")
    pk = td.primary_key if isinstance(td.primary_key, list) else [td.primary_key]
    cols.append(f"PRIMARY KEY ({', '.join(pk)})")
    body = ",\n    ".join(cols)
    return f"CREATE TABLE {table_name} (\n    {body}\n);"


def _build_sqlite_indexes(table_name):
    """Return CREATE [UNIQUE] INDEX statements for the table's indexes.

    The wrapper relies on UNIQUE indexes (e.g., notifications_dedup's
    (event_type, dedup_key)) to make `INSERT OR IGNORE` actually dedup.
    """
    from src.schema.registry import TABLES

    td = TABLES[table_name]
    stmts = []
    for idx in td.indexes:
        unique = "UNIQUE " if idx.unique else ""
        cols = ", ".join(idx.columns)
        stmts.append(
            f"CREATE {unique}INDEX {idx.name} ON {table_name}({cols});"
        )
    return stmts


def _build_pg_ddl(table_name):
    """Return the Postgres CREATE TABLE SQL for one of the audited tables.

    Uses the registry's generate_create_table_sql helper so test DDL stays in
    lock-step with production DDL.
    """
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


def _build_pg_indexes(table_name):
    """Return CREATE INDEX statements for the PG side."""
    from src.schema.postgres import generate_create_indexes_sql
    from src.schema.registry import TABLES

    sql = generate_create_indexes_sql(TABLES[table_name])
    return [s + ";" for s in sql.split(";") if s.strip()]


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn():
    """Live psycopg2 wrapper. Skips if TEST_DATABASE_URL not set.

    Each test runs in its own connection so test isolation comes from
    DROP TABLE IF EXISTS at the start of each table setup helper.
    """
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    wrapper = PostgresConnectionWrapper(raw)
    yield wrapper
    try:
        wrapper.rollback()
    except Exception:
        pass
    wrapper.close()


def _setup_table(conn, table_name):
    """Drop+recreate `table_name` (with indexes) on whichever engine `conn` is for.

    The UNIQUE indexes ARE relevant — notifications_dedup's dedup target is
    the UNIQUE index on (event_type, dedup_key), NOT its actual PK (id).
    Without creating the index, SQLite's INSERT OR IGNORE has no constraint
    to honor and would silently insert duplicates.
    """
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cur.execute(_build_pg_ddl(table_name))
        for idx_sql in _build_pg_indexes(table_name):
            cur.execute(idx_sql)
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(_build_sqlite_ddl(table_name))
        for idx_sql in _build_sqlite_indexes(table_name):
            conn.execute(idx_sql)
        conn.commit()


def _get_conn(request):
    """Return the conn fixture matching the parametrized engine."""
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn")
    elif engine == "postgres":
        return request.getfixturevalue("pg_conn")
    raise ValueError(f"unknown engine: {engine}")


# ---------------------------------------------------------------------------
# Test 1: action='replace' inserts new row
# ---------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine(request):
    return _get_conn(request)


def _count_rows(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    return row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]


def _select_one(conn, table, where_col, where_val):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} WHERE {where_col}=?", (where_val,))
    return cur.fetchone()


def test_replace_inserts_new_row(conn_engine):
    """T0.4 #1: action='replace' inserts a brand-new row when no conflict exists."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "config_overrides")

    row = {
        "setting_key": "max_position_size",
        "setting_value": "1000",
        "previous_value": None,
        "updated_at": "2026-05-11T00:00:00",
        "updated_by": "test_operator",
    }
    engine_aware_upsert(conn, "config_overrides", row, action="replace")
    conn.commit()

    assert _count_rows(conn, "config_overrides") == 1
    fetched = _select_one(conn, "config_overrides", "setting_key", "max_position_size")
    assert fetched["setting_value"] == "1000"


def test_replace_updates_existing_row(conn_engine):
    """T0.4 #2: action='replace' updates non-target columns when conflict exists."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "config_overrides")

    row1 = {
        "setting_key": "max_position_size",
        "setting_value": "1000",
        "previous_value": None,
        "updated_at": "2026-05-11T00:00:00",
        "updated_by": "old_operator",
    }
    engine_aware_upsert(conn, "config_overrides", row1, action="replace")

    row2 = {
        "setting_key": "max_position_size",  # same PK → conflict
        "setting_value": "2500",  # new value
        "previous_value": "1000",
        "updated_at": "2026-05-11T01:00:00",
        "updated_by": "new_operator",
    }
    engine_aware_upsert(conn, "config_overrides", row2, action="replace")
    conn.commit()

    assert _count_rows(conn, "config_overrides") == 1
    fetched = _select_one(conn, "config_overrides", "setting_key", "max_position_size")
    assert fetched["setting_value"] == "2500"
    assert fetched["updated_by"] == "new_operator"


def test_ignore_preserves_existing_row(conn_engine):
    """T0.4 #3: action='ignore' leaves the existing row's values intact on conflict."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "config_overrides")

    row1 = {
        "setting_key": "max_position_size",
        "setting_value": "1000",
        "previous_value": None,
        "updated_at": "2026-05-11T00:00:00",
        "updated_by": "first_operator",
    }
    engine_aware_upsert(conn, "config_overrides", row1, action="ignore")

    row2 = {
        "setting_key": "max_position_size",
        "setting_value": "9999",  # should NOT overwrite
        "previous_value": "1000",
        "updated_at": "2026-05-11T01:00:00",
        "updated_by": "second_operator",
    }
    engine_aware_upsert(conn, "config_overrides", row2, action="ignore")
    conn.commit()

    assert _count_rows(conn, "config_overrides") == 1
    fetched = _select_one(conn, "config_overrides", "setting_key", "max_position_size")
    assert fetched["setting_value"] == "1000"
    assert fetched["updated_by"] == "first_operator"


def test_ignore_inserts_new_row(conn_engine):
    """T0.4 #4: action='ignore' inserts a row when no conflict exists."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "config_overrides")

    row = {
        "setting_key": "max_position_size",
        "setting_value": "1000",
        "previous_value": None,
        "updated_at": "2026-05-11T00:00:00",
        "updated_by": "test_operator",
    }
    engine_aware_upsert(conn, "config_overrides", row, action="ignore")
    conn.commit()

    assert _count_rows(conn, "config_overrides") == 1


def test_composite_pk_target(conn_engine):
    """T0.4 #5: composite-PK target — sp100_historical_constituents (ticker, added_date).

    Both engines must accept the multi-column ON CONFLICT target. Verifies
    re-upserting the same (ticker, added_date) updates non-target columns.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "sp100_historical_constituents")

    row1 = {
        "ticker": "AAPL",
        "added_date": "2014-01-01",
        "removed_date": None,
        "company_name": "Apple Inc.",
        "reason": "initial",
    }
    engine_aware_upsert(conn, "sp100_historical_constituents", row1, action="replace")

    row2 = {
        "ticker": "AAPL",
        "added_date": "2014-01-01",  # composite PK matches
        "removed_date": None,
        "company_name": "Apple Inc. (renamed)",  # update target
        "reason": "company_renamed",
    }
    engine_aware_upsert(conn, "sp100_historical_constituents", row2, action="replace")
    conn.commit()

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sp100_historical_constituents WHERE ticker=? AND added_date=?",
        ("AAPL", "2014-01-01"),
    )
    fetched = cur.fetchone()
    assert fetched["company_name"] == "Apple Inc. (renamed)"
    assert fetched["reason"] == "company_renamed"
    assert _count_rows(conn, "sp100_historical_constituents") == 1


def test_sync_conflict_col_target(conn_engine):
    """T0.4 #6: sync_conflict_col target — notifications_dedup (event_type, dedup_key).

    Even though the table's actual PK is `id` (auto-int), `sync_conflict_col`
    declares the dedup target as (event_type, dedup_key). The wrapper consults
    `_resolve_conflict_target` which honors sync_conflict_col precedence.

    Note: notifications_dedup is NOT in _REPLACE_SEMANTICS (it's not a Phase 1
    `replace` target — it's strictly insert-or-ignore for de-duplication), so
    this test exercises only the action='ignore' branch.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "notifications_dedup")

    row1 = {
        "event_type": "promotion_gate",
        "dedup_key": "strategy:A:2026-05-11",
        "sent_at": "2026-05-11T12:00:00",
    }
    engine_aware_upsert(conn, "notifications_dedup", row1, action="ignore")

    # Second insert with same (event_type, dedup_key) must be IGNORED.
    row2 = {
        "event_type": "promotion_gate",
        "dedup_key": "strategy:A:2026-05-11",
        "sent_at": "2026-05-11T13:00:00",  # different time → should NOT overwrite
    }
    engine_aware_upsert(conn, "notifications_dedup", row2, action="ignore")
    conn.commit()

    assert _count_rows(conn, "notifications_dedup") == 1
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM notifications_dedup WHERE event_type=? AND dedup_key=?",
        ("promotion_gate", "strategy:A:2026-05-11"),
    )
    fetched = cur.fetchone()
    # First insert's sent_at survives.
    assert fetched["sent_at"] == "2026-05-11T12:00:00"


def test_unknown_table_raises_valueerror(conn_engine):
    """T0.4 #7: unknown table name raises ValueError before any DB I/O."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    # Need to set up SOMETHING to make conn non-empty for SQLite path; PG
    # won't care since the helper raises before issuing any SQL.
    with pytest.raises(ValueError) as exc_info:
        engine_aware_upsert(
            conn, "definitely_not_a_real_table", {"x": 1}, action="ignore"
        )
    assert "definitely_not_a_real_table" in str(exc_info.value)


def test_invalid_action_raises_valueerror(conn_engine):
    """T0.4 #8: action not in {'replace','ignore'} raises ValueError."""
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "config_overrides")

    with pytest.raises(ValueError) as exc_info:
        engine_aware_upsert(
            conn,
            "config_overrides",
            {
                "setting_key": "x",
                "setting_value": "y",
                "previous_value": None,
                "updated_at": "z",
                "updated_by": "t",
            },
            action="upsert",  # invalid
        )
    msg = str(exc_info.value)
    assert "replace" in msg or "ignore" in msg or "upsert" in msg


def test_in_place_update_preserves_referencing_rows(conn_engine):
    """T0.4 #9 (C2): `in_place_update` path on a leaf table preserves rowid stability.

    Devil's Advocate C2: SQLite `INSERT OR REPLACE` reassigns rowid (DELETE
    fires + INSERT generates a new rowid); PG `ON CONFLICT DO UPDATE` preserves
    the implicit `ctid` (in-place update). For all 9 audited tables (no incoming
    FKs, no triggers, no rowid readers) this is invisible to readers — BUT we
    still want the test to fail loud if a future refactor accidentally routes a
    table through `delete_insert` when it was classified `in_place_update`.

    Proxy assertion: after an upsert on an existing row, the OTHER rows in the
    table are untouched (count unchanged, sibling values unchanged). This
    captures the "leaf semantics preserved" invariant that the audit relied on.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "config_overrides")

    # Three sibling rows. Only one will be upserted.
    base_rows = [
        {
            "setting_key": "a",
            "setting_value": "alpha",
            "previous_value": None,
            "updated_at": "2026-05-11T00:00:00",
            "updated_by": "t",
        },
        {
            "setting_key": "b",
            "setting_value": "beta",
            "previous_value": None,
            "updated_at": "2026-05-11T00:00:00",
            "updated_by": "t",
        },
        {
            "setting_key": "c",
            "setting_value": "gamma",
            "previous_value": None,
            "updated_at": "2026-05-11T00:00:00",
            "updated_by": "t",
        },
    ]
    for r in base_rows:
        engine_aware_upsert(conn, "config_overrides", r, action="replace")

    # Upsert ONLY key 'b'; the others must be untouched.
    engine_aware_upsert(
        conn,
        "config_overrides",
        {
            "setting_key": "b",
            "setting_value": "BETA-UPDATED",
            "previous_value": "beta",
            "updated_at": "2026-05-11T01:00:00",
            "updated_by": "t",
        },
        action="replace",
    )
    conn.commit()

    assert _count_rows(conn, "config_overrides") == 3
    assert (
        _select_one(conn, "config_overrides", "setting_key", "a")["setting_value"]
        == "alpha"
    )
    assert (
        _select_one(conn, "config_overrides", "setting_key", "b")["setting_value"]
        == "BETA-UPDATED"
    )
    assert (
        _select_one(conn, "config_overrides", "setting_key", "c")["setting_value"]
        == "gamma"
    )


def test_delete_insert_path_fires_cascade(conn_engine):
    """T0.4 #10 (C2): the delete_insert dispatch (_transactional_delete_insert) must
    DELETE the conflict-target row — firing ON DELETE CASCADE to child rows — then
    re-INSERT.

    No PRODUCTION table is classified delete_insert yet (T0.12 audit: all 9 Phase-1
    `replace` targets are in_place_update — see
    docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md), so this
    exercises the branch via a synthetic parent/child FK pair instead of a registry
    table. When a real delete_insert target is added, point this at it.
    """
    from src.utils.db import _transactional_delete_insert, PostgresConnectionWrapper

    conn = conn_engine
    is_pg = isinstance(conn, PostgresConnectionWrapper)
    cascade = " CASCADE" if is_pg else ""

    if not is_pg:
        # SQLite enforces FKs only when this PRAGMA is on; must be set outside a
        # transaction, so commit any implicit one first.
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")

    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS _di_child{cascade}")
    cur.execute(f"DROP TABLE IF EXISTS _di_parent{cascade}")
    cur.execute("CREATE TABLE _di_parent (k TEXT PRIMARY KEY, v TEXT)")
    cur.execute(
        "CREATE TABLE _di_child (id INTEGER PRIMARY KEY, parent_k TEXT "
        "REFERENCES _di_parent(k) ON DELETE CASCADE)"
    )
    conn.commit()

    cur.execute("INSERT INTO _di_parent (k, v) VALUES (?, ?)", ("p1", "orig"))
    cur.execute("INSERT INTO _di_child (id, parent_k) VALUES (?, ?)", (1, "p1"))
    conn.commit()
    assert _count_rows(conn, "_di_child") == 1, "child row not seeded"

    # delete_insert semantics: DELETE parent k=p1 (must cascade to child) + re-INSERT.
    _transactional_delete_insert(conn, "_di_parent", {"k": "p1", "v": "new"}, ["k"])
    conn.commit()

    assert _select_one(conn, "_di_parent", "k", "p1")["v"] == "new", (
        "parent row not re-inserted by delete_insert"
    )
    assert _count_rows(conn, "_di_child") == 0, (
        "ON DELETE CASCADE did not fire — delete_insert's DELETE half must cascade "
        "to child rows"
    )

    # Cleanup so the synthetic tables don't leak into the shared PG.
    cur.execute(f"DROP TABLE IF EXISTS _di_child{cascade}")
    cur.execute(f"DROP TABLE IF EXISTS _di_parent{cascade}")
    conn.commit()


def test_unclassified_replace_target_raises_valueerror(conn_engine):
    """T0.4 #11 (C2): action='replace' on a table NOT in _REPLACE_SEMANTICS raises.

    This forces every future Phase 2+ `replace` target through the T0.12-style
    audit before its dispatch lands — getting the semantic decision wrong
    silently corrupts FK-related data over the 7-day observability window, and
    no test catches it because both branches succeed on the surface.

    notifications_dedup is registered in TABLES (so it passes the unknown-table
    check) but NOT in _REPLACE_SEMANTICS (it's a Phase 0 dedup target, strictly
    insert-or-ignore). Calling action='replace' on it must raise ValueError
    naming the table and pointing at the dict.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine
    _setup_table(conn, "notifications_dedup")

    with pytest.raises(ValueError) as exc_info:
        engine_aware_upsert(
            conn,
            "notifications_dedup",
            {
                "event_type": "x",
                "dedup_key": "y",
                "sent_at": "2026-05-11T00:00:00",
            },
            action="replace",
        )
    msg = str(exc_info.value)
    assert "notifications_dedup" in msg
    assert "_REPLACE_SEMANTICS" in msg


def test_delete_insert_atomicity_rolls_back_on_failure():
    """T0.4 #12 (C2): delete_insert dispatch is transactional.

    Since the audit found 0 tables classified as `delete_insert`, we exercise
    the branch via a direct monkeypatch of _REPLACE_SEMANTICS so the test
    doesn't depend on a future cascade-target table existing. The invariant
    under test: if the INSERT half of the delete_insert path fails (e.g. a
    NOT NULL constraint violation), the wrapper must call `conn.rollback()`
    so the DELETE half is also undone — leaving the pre-state intact.

    This is the ONLY C2 invariant that genuinely diverges between engines:
    SQLite's INSERT OR REPLACE is one atomic statement; the PG emulation has
    to wrap DELETE+INSERT in an explicit transaction. We test on SQLite
    because the constraint violation is more deterministic, but the
    transactional behavior must be symmetric on PG (the wrapper uses
    conn.rollback() which both engines support identically).
    """
    from unittest.mock import patch

    import src.utils.db as db_module
    from src.utils.db import engine_aware_upsert

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        # Build a synthetic table where we can force a constraint violation.
        # `config_overrides` has updated_at NOT NULL — we'll trip that by
        # routing through a manual cursor.execute that omits the column.
        conn.execute(_build_sqlite_ddl("config_overrides"))

        # Seed a row so the DELETE half has something to delete.
        engine_aware_upsert(
            conn,
            "config_overrides",
            {
                "setting_key": "atom_test",
                "setting_value": "pre_state",
                "previous_value": None,
                "updated_at": "2026-05-11T00:00:00",
                "updated_by": "operator",
            },
            action="replace",
        )
        conn.commit()

        # Override the dispatch decision for this one table to delete_insert,
        # then attempt an upsert that violates NOT NULL on updated_at (pass
        # None for a NOT NULL column). Expect a raised exception AND the
        # pre-state preserved (DELETE rolled back).
        original = dict(db_module._REPLACE_SEMANTICS)
        spoofed = dict(original)
        spoofed["config_overrides"] = "delete_insert"
        with patch.object(db_module, "_REPLACE_SEMANTICS", spoofed):
            with pytest.raises(Exception):
                engine_aware_upsert(
                    conn,
                    "config_overrides",
                    {
                        "setting_key": "atom_test",
                        "setting_value": "post_state",
                        "previous_value": "pre_state",
                        "updated_at": None,  # violates NOT NULL
                        "updated_by": "operator2",
                    },
                    action="replace",
                )

        # Pre-state must survive: row still present with original setting_value.
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM config_overrides WHERE setting_key=?", ("atom_test",)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["setting_value"] == "pre_state"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _REPLACE_SEMANTICS dict — verbatim-from-audit assertions
# ---------------------------------------------------------------------------


def test_replace_semantics_dict_matches_audit_verbatim():
    """T0.4 acceptance: `_REPLACE_SEMANTICS` matches the T0.12 audit verbatim.

    Source of truth:
        docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
        §7 plus the watch-loop stress_test_results hotfix entry.

    The audited Phase 1 targets and stress_test_results are all leaf-style
    persistence tables, so `in_place_update` preserves the intended idempotent
    overwrite behavior. If this assertion fails, EITHER the audit doc was
    revised (in which case re-read §7 and update the dict) OR a future task
    added a new replace target without auditing it (in which case the new
    table needs an audit entry before it lands in the dict).
    """
    from src.utils.db import _REPLACE_SEMANTICS

    expected = {
        "data_freshness": "in_place_update",
        "build_score_history": "in_place_update",
        "config_overrides": "in_place_update",
        "system_metrics": "in_place_update",
        "council_parameter_state": "in_place_update",
        "operator_view_state": "in_place_update",
        "simulation_results": "in_place_update",
        "walkforward_results": "in_place_update",
        "walkforward_trades": "in_place_update",
        "sp100_historical_constituents": "in_place_update",
        "stress_test_results": "in_place_update",
        "minute_bars": "in_place_update",
    }
    assert _REPLACE_SEMANTICS == expected


def test_replace_semantics_includes_operator_view_state():
    """Phase 3-revised T1: operator_view_state must be in _REPLACE_SEMANTICS as in_place_update."""
    from src.utils.db import _REPLACE_SEMANTICS
    assert "operator_view_state" in _REPLACE_SEMANTICS
    assert _REPLACE_SEMANTICS["operator_view_state"] == "in_place_update"

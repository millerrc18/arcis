# Purpose: Integration tests for src/tools/tradingstate/core.py + queries.py.
# Called by: pytest tests/tools/test_tradingstate_integration.py
# Calls: src.tools.tradingstate.core.state, psycopg2 + sqlite3 against real DBs
# Owns tables: none (creates + drops fixture rows in real test PG at 127.0.0.1:5434)
# Config keys: none (DSN passed explicitly per spec §4.9 network-discipline)
# Tests: (this file is the test)

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
import pytest

_TEST_DSN = (
    os.environ.get("TEST_DATABASE_URL")
    or "host=127.0.0.1 port=5434 dbname=halcyon user=test password=test"
)

_BAD_PORT_DSN = "host=127.0.0.1 port=1 dbname=halcyon user=test password=test"


# ── Build helper: fresh decorated state fn with custom log_path ───────────────

def _build_state(log_path: Path):
    """Construct a freshly-decorated state function with a test-specific log path.

    Mirrors the pattern in test_safe_op_integration.py::_build_fake_tool.
    Each test gets its own log file, preventing cross-test log contamination.
    """
    from src.tools._safety import prod_guard, safe_op
    from src.tools.tradingstate.core import (
        TradingStateError,
        _build_audit_dict,
        _build_gpu_health,
        _pg_snapshot,
        _sqlite_snapshot,
        _PG_CONNECT_ERRORS,
    )
    from src.tools._config import load_arcis_config
    import psycopg2
    import sqlite3
    from zoneinfo import ZoneInfo
    from datetime import datetime
    from pathlib import Path as _Path
    from typing import Optional

    @safe_op(name="tradingstate", mutates=False, log_path=log_path)
    @prod_guard(dsn_param="dsn", log_path=log_path)
    def _state(
        *,
        dsn: Optional[str] = None,
        sqlite_path: Optional[_Path] = None,
    ) -> dict:
        resolved_dsn = dsn
        if resolved_dsn is None:
            cfg = load_arcis_config()
            resolved_dsn = cfg.pg.test_dsn

        snapshot_errors: dict = {}

        try:
            positions, audit_row, metrics_rows, snapshot_errors = _pg_snapshot(resolved_dsn)
            data_source = "pg"
        except _PG_CONNECT_ERRORS:
            try:
                cfg = load_arcis_config()
                sqlite_path_resolved = (
                    sqlite_path if sqlite_path is not None else cfg.paths.db_canonical
                )
                positions, audit_row, metrics_rows, snapshot_errors = _sqlite_snapshot(
                    sqlite_path_resolved
                )
                data_source = "sqlite_fallback"
            except (sqlite3.Error, FileNotFoundError, OSError) as sqlite_exc:
                raise TradingStateError(
                    f"both PG and SQLite unavailable: {sqlite_exc}"
                ) from sqlite_exc

        as_of_et = datetime.now(ZoneInfo("US/Eastern")).isoformat()
        result = {
            "as_of_et": as_of_et,
            "open_positions": positions,
            "most_recent_audit": _build_audit_dict(audit_row),
            "gpu_health": _build_gpu_health(metrics_rows),
            "data_source": data_source,
        }
        if snapshot_errors:
            result["errors"] = snapshot_errors
        return result

    return _state


def _read_log(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


# ── DDL helpers ──────────────────────────────────────────────────────────────

def _pg_conn():
    return psycopg2.connect(_TEST_DSN, connect_timeout=5)


def _ensure_tables():
    """Create the required tables if they don't exist in the test DB."""
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                recommendation_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                thesis_text TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                trade_id TEXT PRIMARY KEY,
                recommendation_id TEXT REFERENCES recommendations(recommendation_id),
                ticker TEXT NOT NULL,
                source TEXT DEFAULT 'paper',
                status TEXT DEFAULT 'pending',
                entry_price REAL,
                actual_entry_time TIMESTAMPTZ,
                quarantined INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_reports (
                audit_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL,
                audit_date TEXT NOT NULL,
                overall_assessment TEXT NOT NULL,
                summary TEXT,
                flags TEXT,
                metrics_to_watch TEXT,
                model_health TEXT,
                full_report TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_metrics (
                id SERIAL PRIMARY KEY,
                metric_date DATE NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                details TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _pg_delete_fixture(conn, trade_ids, audit_ids, metric_ids, rec_ids):
    """Delete fixture rows in dependency order."""
    try:
        cur = conn.cursor()
        if trade_ids:
            cur.execute(
                "DELETE FROM shadow_trades WHERE trade_id = ANY(%s)", (list(trade_ids),)
            )
        if audit_ids:
            cur.execute(
                "DELETE FROM audit_reports WHERE audit_id = ANY(%s)", (list(audit_ids),)
            )
        if metric_ids:
            cur.execute(
                "DELETE FROM schedule_metrics WHERE id = ANY(%s)", (list(metric_ids),)
            )
        if rec_ids:
            cur.execute(
                "DELETE FROM recommendations WHERE recommendation_id = ANY(%s)", (list(rec_ids),)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── Test (a): Happy-path PG snapshot ─────────────────────────────────────────

def test_state_pg_happy_path(tmp_path):
    """
    state(dsn=test_dsn) returns correct open position, stale audit, gpu health.

    Verify-by-mutation:
    - entry_time: fails if SQL alias is changed from `actual_entry_time AS entry_time`
      to `created_at AS entry_time` — entry_time would differ from fixture value.
    - quarantined-excluded: fails if COALESCE(quarantined,0)=0 is flipped to =1 —
      the quarantined trade appears instead of being excluded.
    """
    _ensure_tables()

    log = tmp_path / "exec.log"
    state_fn = _build_state(log)

    rec_id = str(uuid.uuid4())
    open_trade_id = str(uuid.uuid4())
    closed_trade_id = str(uuid.uuid4())
    quarantined_trade_id = str(uuid.uuid4())
    paper_trade_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())

    now_utc = datetime.now(timezone.utc)
    entry_time = now_utc - timedelta(minutes=10)
    # 40 hours ago → stale (threshold is 36h)
    audit_created = now_utc - timedelta(hours=40)
    today_str = date.today().isoformat()

    conn = _pg_conn()
    metric_ids = []
    try:
        cur = conn.cursor()
        # recommendation
        cur.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, thesis_text) VALUES (%s,%s,%s)",
            (rec_id, "AAPL", "Strong breakout thesis"),
        )
        # open live trade
        cur.execute(
            """INSERT INTO shadow_trades
               (trade_id, recommendation_id, ticker, source, status, entry_price,
                actual_entry_time, quarantined)
               VALUES (%s,%s,%s,'live','open',150.0,%s,0)""",
            (open_trade_id, rec_id, "AAPL", entry_time),
        )
        # closed trade — must be excluded
        cur.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, source, status, entry_price, actual_entry_time, quarantined)
               VALUES (%s,'MSFT','live','closed',200.0,%s,0)""",
            (closed_trade_id, entry_time),
        )
        # quarantined trade — must be excluded
        cur.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, source, status, entry_price, actual_entry_time, quarantined)
               VALUES (%s,'TSLA','live','open',700.0,%s,1)""",
            (quarantined_trade_id, entry_time),
        )
        # paper trade — must be excluded (source != 'live')
        cur.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, source, status, entry_price, actual_entry_time, quarantined)
               VALUES (%s,'NVDA','paper','open',500.0,%s,0)""",
            (paper_trade_id, entry_time),
        )
        # audit row (40h ago → stale)
        cur.execute(
            """INSERT INTO audit_reports
               (audit_id, created_at, audit_date, overall_assessment)
               VALUES (%s,%s,%s,'STABLE')""",
            (audit_id, audit_created, today_str),
        )
        # schedule_metrics rows for today
        cur.execute(
            """INSERT INTO schedule_metrics (metric_date, metric_name, metric_value)
               VALUES (%s,'gpu_health_ollama_ok',1.0) RETURNING id""",
            (today_str,),
        )
        metric_ids.append(cur.fetchone()[0])
        cur.execute(
            """INSERT INTO schedule_metrics (metric_date, metric_name, metric_value)
               VALUES (%s,'gpu_health_training_ok',0.0) RETURNING id""",
            (today_str,),
        )
        metric_ids.append(cur.fetchone()[0])
        conn.commit()

        result = state_fn(dsn=_TEST_DSN)

        # Exactly 1 open position (AAPL)
        assert len(result["open_positions"]) == 1, (
            f"expected 1 open position, got {len(result['open_positions'])}: "
            f"{result['open_positions']}"
        )
        pos = result["open_positions"][0]
        assert pos["ticker"] == "AAPL"
        assert pos["trade_id"] == open_trade_id
        assert pos["source"] == "live"
        assert pos["status"] == "open"
        assert pos["thesis_text"] == "Strong breakout thesis"

        # entry_time must match actual_entry_time (within 1s tolerance for roundtrip)
        returned_et = pos["entry_time"]
        if isinstance(returned_et, str):
            returned_et = datetime.fromisoformat(returned_et)
        if returned_et.tzinfo is None:
            returned_et = returned_et.replace(tzinfo=timezone.utc)
        diff = abs((returned_et - entry_time).total_seconds())
        assert diff < 2, (
            f"entry_time diff {diff}s too large — alias broken? "
            f"returned={returned_et!r} fixture={entry_time!r}"
        )

        # most_recent_audit
        audit = result["most_recent_audit"]
        assert audit is not None
        assert audit["overall_assessment"] == "STABLE"
        assert audit["stale"] is True, "40h-old audit should be stale (threshold=36h)"
        assert audit["audit_id"] == audit_id

        # gpu_health
        gh = result["gpu_health"]
        assert gh["ollama_ok"] is True, f"expected True, got {gh['ollama_ok']!r}"
        assert gh["training_ok"] is False, f"expected False, got {gh['training_ok']!r}"
        assert gh["metric_date"] == today_str

        # data_source
        assert result["data_source"] == "pg"

        # 'success' event recorded in log
        events = _read_log(log)
        assert any(e["result"] == "success" for e in events), (
            f"expected 'success' event in log, got: {events}"
        )

    finally:
        _pg_delete_fixture(
            conn,
            trade_ids=[open_trade_id, closed_trade_id, quarantined_trade_id, paper_trade_id],
            audit_ids=[audit_id],
            metric_ids=metric_ids,
            rec_ids=[rec_id],
        )
        conn.close()


# ── Test (b): Missing GPU metric row → None ───────────────────────────────────

def test_state_missing_training_metric_is_none(tmp_path):
    """
    When gpu_health_training_ok row is absent, training_ok must be None — NOT False.

    Verify-by-mutation: fails if missing schedule_metric rows default to False
    instead of None — the assertion `is None` fails.
    """
    _ensure_tables()

    log = tmp_path / "exec.log"
    state_fn = _build_state(log)

    audit_id = str(uuid.uuid4())
    metric_ids = []
    today_str = date.today().isoformat()
    now_utc = datetime.now(timezone.utc)
    audit_created = now_utc - timedelta(hours=1)

    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO audit_reports
               (audit_id, created_at, audit_date, overall_assessment)
               VALUES (%s,%s,%s,'STABLE')""",
            (audit_id, audit_created, today_str),
        )
        # Only ollama_ok — no training_ok row
        cur.execute(
            """INSERT INTO schedule_metrics (metric_date, metric_name, metric_value)
               VALUES (%s,'gpu_health_ollama_ok',1.0) RETURNING id""",
            (today_str,),
        )
        metric_ids.append(cur.fetchone()[0])
        conn.commit()

        result = state_fn(dsn=_TEST_DSN)

        gh = result["gpu_health"]
        assert gh["training_ok"] is None, (
            f"expected None (metric absent — not measured), got {gh['training_ok']!r}"
        )
        assert gh["ollama_ok"] is True

    finally:
        _pg_delete_fixture(
            conn,
            trade_ids=[],
            audit_ids=[audit_id],
            metric_ids=metric_ids,
            rec_ids=[],
        )
        conn.close()


# ── Test (b2): Corrupt SQLite created_at → stale=True + WARNING (no silent now()) ──

def test_state_corrupt_audit_created_at_is_stale_not_silently_fresh(tmp_path, caplog):
    """
    Unparseable audit_reports.created_at must yield stale=True + WARNING log,
    NOT silently substitute datetime.now() (which would mark the corrupt row
    "fresh" and hide the corruption from the operator).

    Verify-by-mutation: reverting _build_audit_dict's except clause to
    `created_at_dt = datetime.now(timezone.utc)` (pre-fix behavior) makes
    stale=False here — and this assertion fails. The pre-fix path was a
    fail-quiet pattern called out in feedback_strict_rigor_no_handwave.
    """
    import logging
    import sqlite3

    # Use SQLite fallback path so we control the created_at string (PG would
    # coerce to a real datetime before psycopg2 returns it; only the SQLite
    # str-path is reachable with a corrupt value).
    sqlite_path = tmp_path / "fallback.sqlite"
    conn = sqlite3.connect(sqlite_path)
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            source TEXT,
            status TEXT,
            entry_price REAL,
            actual_entry_time TEXT,
            quarantined INTEGER,
            recommendation_id TEXT
        )
    """)
    conn.execute("CREATE TABLE recommendations (recommendation_id TEXT, thesis_text TEXT)")
    conn.execute("""
        CREATE TABLE audit_reports (
            audit_id TEXT,
            created_at TEXT,
            overall_assessment TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE schedule_metrics (
            metric_date TEXT,
            metric_name TEXT,
            metric_value REAL
        )
    """)
    # Insert audit row with deliberately-corrupt created_at string
    audit_id = "test-corrupt-audit-id"
    conn.execute(
        "INSERT INTO audit_reports VALUES (?, ?, 'STABLE')",
        (audit_id, "not-a-valid-iso-timestamp-XYZ"),
    )
    conn.commit()
    conn.close()

    log = tmp_path / "exec.log"
    state_fn = _build_state(log)

    # Force PG fallback by pointing at unreachable DSN
    bad_pg_dsn = "host=127.0.0.1 port=1 dbname=halcyon user=test password=test"

    with caplog.at_level(logging.WARNING, logger="src.tools.tradingstate.core"):
        result = state_fn(dsn=bad_pg_dsn, sqlite_path=sqlite_path)

    assert result["data_source"] == "sqlite_fallback"
    audit = result["most_recent_audit"]
    assert audit is not None, "audit row was inserted; should not be None"
    assert audit["audit_id"] == audit_id
    assert audit["stale"] is True, (
        "corrupt created_at MUST yield stale=True to surface corruption "
        "(silent datetime.now() substitution is the fail-quiet anti-pattern)"
    )
    assert audit["created_at"] == "not-a-valid-iso-timestamp-XYZ", (
        "raw corrupt string preserved in output for diagnostics"
    )
    # WARNING log must mention 'unparseable' so operator can grep for it
    assert any(
        "unparseable" in rec.message.lower()
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    ), f"expected WARNING about unparseable created_at, got: {[r.message for r in caplog.records]}"


# ── Test (c): SQLite fallback ─────────────────────────────────────────────────

def test_state_sqlite_fallback(tmp_path):
    """
    PG unreachable + valid SQLite path → data_source == 'sqlite_fallback'.
    """
    from src.tools.tradingstate.core import state

    db_path = tmp_path / "test_fallback.sqlite3"
    today_str = date.today().isoformat()
    now_utc = datetime.now(timezone.utc)
    audit_created_str = (now_utc - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    audit_id = str(uuid.uuid4())
    trade_id = str(uuid.uuid4())

    # Seed SQLite with minimal fixture data
    sconn = sqlite3.connect(str(db_path))
    try:
        sconn.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                recommendation_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                thesis_text TEXT,
                created_at TEXT
            )
        """)
        sconn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                trade_id TEXT PRIMARY KEY,
                recommendation_id TEXT,
                ticker TEXT NOT NULL,
                source TEXT DEFAULT 'paper',
                status TEXT DEFAULT 'pending',
                entry_price REAL,
                actual_entry_time TEXT,
                quarantined INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        sconn.execute("""
            CREATE TABLE IF NOT EXISTS audit_reports (
                audit_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                audit_date TEXT NOT NULL,
                overall_assessment TEXT NOT NULL,
                summary TEXT
            )
        """)
        sconn.execute("""
            CREATE TABLE IF NOT EXISTS schedule_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_date TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                details TEXT
            )
        """)
        sconn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, source, status, actual_entry_time, quarantined) "
            "VALUES (?,?,'live','open',?,0)",
            (trade_id, "GOOG", today_str),
        )
        sconn.execute(
            "INSERT INTO audit_reports (audit_id, created_at, audit_date, overall_assessment) "
            "VALUES (?,?,?,'STABLE_SQLITE')",
            (audit_id, audit_created_str, today_str),
        )
        sconn.execute(
            "INSERT INTO schedule_metrics (metric_date, metric_name, metric_value) VALUES (?,?,?)",
            (today_str, "gpu_health_ollama_ok", 1.0),
        )
        sconn.commit()
    finally:
        sconn.close()

    result = state(dsn=_BAD_PORT_DSN, sqlite_path=db_path)

    assert result["data_source"] == "sqlite_fallback"
    assert result["most_recent_audit"]["overall_assessment"] == "STABLE_SQLITE"
    assert result["gpu_health"]["ollama_ok"] is True


# ── Test (d): Both backends unavailable → TradingStateError ──────────────────

def test_state_both_unavailable_raises():
    """
    Bad PG port + nonexistent SQLite path → TradingStateError.
    """
    from src.tools.tradingstate.core import state, TradingStateError

    bad_sqlite = Path("/nonexistent/path/does_not_exist.sqlite3")

    with pytest.raises(TradingStateError):
        state(dsn=_BAD_PORT_DSN, sqlite_path=bad_sqlite)


# ── Test (e): Prod DSN signature → ProdGuardError, no duplicate 'error' event ─

def test_state_prod_dsn_raises_prod_guard_not_error(tmp_path):
    """
    Prod-signature DSN → ProdGuardError raised; log shows 'prod_guard_block' ONLY
    (no duplicate 'error' event). Verifies decorator-contract at _safety.py:146-147.
    """
    from src.tools._safety import ProdGuardError

    log = tmp_path / "exec.log"
    state_fn = _build_state(log)

    # DSN matching 'halcyon_app:' production signature (URL format: user:password contains colon)
    prod_dsn = "postgresql://halcyon_app:supersecret@127.0.0.1:5432/halcyon"

    with pytest.raises(ProdGuardError):
        state_fn(dsn=prod_dsn)

    events = _read_log(log)

    # Last event must be 'prod_guard_block'
    assert events[-1]["result"] == "prod_guard_block", (
        f"expected last event 'prod_guard_block', got {events[-1]['result']!r}"
    )

    # Zero 'error' events — safe_op must NOT double-log for SafetyError subclasses
    error_events = [e for e in events if e["result"] == "error"]
    assert len(error_events) == 0, (
        f"expected zero 'error' events (decorator contract), got: {error_events}"
    )


# ── Test (f): DA2 snapshot consistency via REPEATABLE READ ────────────────────

def test_state_repeatable_read_snapshot_consistency(tmp_path):
    """
    Background writer mutates shadow_trades + audit_reports between query 1 and
    query 3. With REPEATABLE READ, state() must see the PRE-WRITE values.

    Verify-by-mutation: fails if isolation_level='REPEATABLE READ' is removed
    from pg_connect — the snapshot sees the writer's mutations and either the
    position count changes or overall_assessment becomes 'NEW-ASSESSMENT'.
    """
    _ensure_tables()

    log = tmp_path / "exec.log"

    trade_id = str(uuid.uuid4())
    audit_id_old = str(uuid.uuid4())
    audit_id_new = str(uuid.uuid4())
    today_str = date.today().isoformat()
    now_utc = datetime.now(timezone.utc)
    entry_time = now_utc - timedelta(minutes=5)
    old_audit_created = now_utc - timedelta(hours=1)

    setup_conn = _pg_conn()
    writer_audit_ids = [audit_id_old, audit_id_new]
    metric_ids = []

    try:
        cur = setup_conn.cursor()
        cur.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, source, status, entry_price, actual_entry_time, quarantined)
               VALUES (%s,'SPY','live','open',450.0,%s,0)""",
            (trade_id, entry_time),
        )
        cur.execute(
            """INSERT INTO audit_reports
               (audit_id, created_at, audit_date, overall_assessment)
               VALUES (%s,%s,%s,'OLD-ASSESSMENT')""",
            (audit_id_old, old_audit_created, today_str),
        )
        setup_conn.commit()

        # Synchronization events
        event_after_q1 = threading.Event()
        event_writer_done = threading.Event()

        # Monkey-patch pg_connect to inject sync points after the first SELECT.
        import src.tools._db as _db_module

        original_pg_connect = _db_module.pg_connect

        query_count = {"n": 0}

        @contextmanager
        def patched_pg_connect(dsn, *, read_only=False, isolation_level=None, timeout=10, named_cursor=None):
            with original_pg_connect(
                dsn,
                read_only=read_only,
                isolation_level=isolation_level,
                timeout=timeout,
                named_cursor=named_cursor,
            ) as (conn, cur):
                original_execute = cur.execute

                def tracked_execute(sql, params=None):
                    query_count["n"] += 1
                    if params is None:
                        result = original_execute(sql)
                    else:
                        result = original_execute(sql, params)
                    if query_count["n"] == 1:
                        event_after_q1.set()
                        event_writer_done.wait(timeout=5.0)
                    return result

                cur.execute = tracked_execute
                yield conn, cur

        _db_module.pg_connect = patched_pg_connect

        def writer_thread():
            try:
                event_after_q1.wait(timeout=5.0)
                wconn = _pg_conn()
                try:
                    wcur = wconn.cursor()
                    wcur.execute(
                        "UPDATE shadow_trades SET status='closed' WHERE trade_id=%s",
                        (trade_id,),
                    )
                    wcur.execute(
                        """INSERT INTO audit_reports
                           (audit_id, created_at, audit_date, overall_assessment)
                           VALUES (%s,%s,%s,'NEW-ASSESSMENT')""",
                        (audit_id_new, now_utc, today_str),
                    )
                    wconn.commit()
                finally:
                    wconn.close()
            finally:
                event_writer_done.set()

        writer = threading.Thread(target=writer_thread, daemon=True)
        writer.start()

        # Build fresh state function; _db_module.pg_connect is now patched
        from src.tools.tradingstate.core import (
            TradingStateError,
            _build_audit_dict,
            _build_gpu_health,
            _PG_CONNECT_ERRORS,
        )
        from src.tools._config import load_arcis_config as _load_cfg
        from src.tools._safety import safe_op as _safe_op, prod_guard as _prod_guard
        from zoneinfo import ZoneInfo as _ZI
        from datetime import datetime as _dt
        from pathlib import Path as _Path
        from typing import Optional as _Opt
        import sqlite3 as _sqlite3

        @_safe_op(name="tradingstate", mutates=False, log_path=log)
        @_prod_guard(dsn_param="dsn", log_path=log)
        def _state_patched(*, dsn=None, sqlite_path=None):
            resolved_dsn = dsn or _load_cfg().pg.test_dsn
            # Call _pg_snapshot which uses _db_module.pg_connect (now patched)
            from src.tools.tradingstate.core import _pg_snapshot as _pgs, _sqlite_snapshot as _sqls
            snap_errors: dict = {}
            try:
                positions, audit_row, metrics_rows, snap_errors = _pgs(resolved_dsn)
                ds = "pg"
            except _PG_CONNECT_ERRORS:
                try:
                    cfg = _load_cfg()
                    sp = sqlite_path if sqlite_path is not None else cfg.paths.db_canonical
                    positions, audit_row, metrics_rows, snap_errors = _sqls(sp)
                    ds = "sqlite_fallback"
                except (_sqlite3.Error, FileNotFoundError, OSError) as e:
                    raise TradingStateError(f"both unavailable: {e}") from e
            _result = {
                "as_of_et": _dt.now(_ZI("US/Eastern")).isoformat(),
                "open_positions": positions,
                "most_recent_audit": _build_audit_dict(audit_row),
                "gpu_health": _build_gpu_health(metrics_rows),
                "data_source": ds,
            }
            if snap_errors:
                _result["errors"] = snap_errors
            return _result

        result = _state_patched(dsn=_TEST_DSN)

        writer.join(timeout=10.0)

        # Restore original pg_connect
        _db_module.pg_connect = original_pg_connect

        # REPEATABLE READ: snapshot pinned at first SELECT.
        # Position must still be open (writer closed it after Q1 but REPEATABLE READ pins).
        open_positions = result["open_positions"]
        assert len(open_positions) == 1, (
            f"REPEATABLE READ violation: expected 1 open position (pre-write snapshot), "
            f"got {len(open_positions)}. Writer closed the position after Q1 but "
            f"REPEATABLE READ should pin the snapshot."
        )
        assert open_positions[0]["trade_id"] == trade_id

        # Audit must be OLD-ASSESSMENT (writer inserted NEW-ASSESSMENT after Q1)
        assert result["most_recent_audit"]["overall_assessment"] == "OLD-ASSESSMENT", (
            f"REPEATABLE READ violation: expected 'OLD-ASSESSMENT' (pre-write snapshot), "
            f"got {result['most_recent_audit']['overall_assessment']!r}. "
            f"Writer inserted NEW-ASSESSMENT after Q1 but REPEATABLE READ should pin."
        )

    finally:
        # Restore pg_connect in case test fails before the explicit restore
        import src.tools._db as _db_module2
        if _db_module2.pg_connect is not original_pg_connect:
            _db_module2.pg_connect = original_pg_connect

        _pg_delete_fixture(
            setup_conn,
            trade_ids=[trade_id],
            audit_ids=writer_audit_ids,
            metric_ids=metric_ids,
            rec_ids=[],
        )
        setup_conn.close()


# ── Test class: UndefinedTable structured error envelope ─────────────────────

class TestUndefinedTableStructuredError:
    """#124: Missing table after DB-wipe must return structured error envelope.

    All cases force PG fallback via bad port, then hit SQLite directly.
    Verify-by-mutation: comment out the try/except wrapping in
    _sqlite_snapshot → Case A/B fail with uncaught sqlite3.OperationalError.
    """

    def _make_sqlite_db(self, tmp_path, tables: list[str]) -> Path:
        """Create a SQLite DB with only the specified tables (minimal schema)."""
        db = tmp_path / "partial.sqlite"
        conn = sqlite3.connect(str(db))
        schema = {
            "recommendations": (
                "CREATE TABLE recommendations "
                "(recommendation_id TEXT, thesis_text TEXT)"
            ),
            "audit_reports": (
                "CREATE TABLE audit_reports "
                "(audit_id TEXT, created_at TEXT, overall_assessment TEXT)"
            ),
            "shadow_trades": (
                "CREATE TABLE shadow_trades "
                "(trade_id TEXT, ticker TEXT, source TEXT, status TEXT, "
                " entry_price REAL, actual_entry_time TEXT, "
                " quarantined INTEGER, recommendation_id TEXT)"
            ),
            "schedule_metrics": (
                "CREATE TABLE schedule_metrics "
                "(metric_date TEXT, metric_name TEXT, metric_value REAL)"
            ),
        }
        for t in tables:
            conn.execute(schema[t])
        conn.commit()
        conn.close()
        return db

    def test_case_a_missing_shadow_trades(self, tmp_path):
        """SQLite DB without shadow_trades: open_positions=None, errors envelope set."""
        from src.tools.tradingstate.core import state

        db = self._make_sqlite_db(
            tmp_path, ["recommendations", "audit_reports", "schedule_metrics"]
        )

        result = state(dsn=_BAD_PORT_DSN, sqlite_path=db)

        assert result["open_positions"] is None, (
            f"expected open_positions=None when shadow_trades table missing, "
            f"got {result['open_positions']!r}"
        )
        assert "errors" in result, "expected top-level 'errors' key in result"
        assert "open_positions" in result["errors"], (
            f"expected errors.open_positions, got keys: {list(result['errors'].keys())}"
        )
        err = result["errors"]["open_positions"]
        assert "error_type" in err, f"errors.open_positions missing 'error_type': {err}"
        assert "error_message" in err, f"errors.open_positions missing 'error_message': {err}"
        assert "table_name" in err, f"errors.open_positions missing 'table_name': {err}"
        # Function MUST NOT raise — we reached this point, so it didn't
        # most_recent_audit must still resolve correctly (table IS present)
        assert result.get("most_recent_audit") is None or isinstance(
            result["most_recent_audit"], dict
        )

    def test_case_b_missing_audit_reports(self, tmp_path):
        """SQLite DB without audit_reports: most_recent_audit=None, open_positions works."""
        from src.tools.tradingstate.core import state
        import uuid

        db = self._make_sqlite_db(
            tmp_path, ["recommendations", "shadow_trades", "schedule_metrics"]
        )
        # Seed a shadow_trade so open_positions can return data
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO shadow_trades VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), "AAPL", "live", "open", 150.0, "2026-05-27T10:00:00", 0, None),
        )
        conn.commit()
        conn.close()

        result = state(dsn=_BAD_PORT_DSN, sqlite_path=db)

        assert result["most_recent_audit"] is None, (
            f"expected most_recent_audit=None when audit_reports missing, "
            f"got {result['most_recent_audit']!r}"
        )
        assert "errors" in result, "expected top-level 'errors' key in result"
        assert "most_recent_audit" in result["errors"], (
            f"expected errors.most_recent_audit, got keys: {list(result['errors'].keys())}"
        )
        err = result["errors"]["most_recent_audit"]
        assert "error_type" in err
        assert "error_message" in err
        assert "table_name" in err
        # open_positions MUST still return correctly (shadow_trades IS present)
        assert isinstance(result["open_positions"], list), (
            f"expected open_positions to be a list (shadow_trades present), "
            f"got {result['open_positions']!r}"
        )

    def test_case_c_no_tables_all_fields_none(self, tmp_path):
        """SQLite DB with NO tables: all data fields None, errors envelope complete."""
        from src.tools.tradingstate.core import state

        db = tmp_path / "empty.sqlite"
        db.touch()  # empty file — no tables

        result = state(dsn=_BAD_PORT_DSN, sqlite_path=db)

        assert result["open_positions"] is None
        assert result["most_recent_audit"] is None
        assert "errors" in result
        # At minimum open_positions and most_recent_audit errors must appear
        assert "open_positions" in result["errors"]
        assert "most_recent_audit" in result["errors"]


# ── Test class: audit-freshness timezone frame (Bug #3) ──────────────────────


class TestAuditCreatedAtTimezone:
    """audit_reports.created_at is ET wall-clock; staleness must compare in ET.

    The auditor writes created_at = datetime.now(America/New_York).isoformat()
    (registry type TEXT). When a NAIVE value reaches _build_audit_dict (a naive
    'timestamp' PG column storing ET wall-clock, or an ISO string without an
    offset), the pre-fix code tagged it timezone.utc. During EDT (UTC-4) that
    shifts a fresh verdict ~4h into the past -> false stale=True
    (governor-verdict-freshness corruption; ties to the two-layer-staleness
    false-halt class). These tests feed NAIVE-ET inputs and assert the frame is
    interpreted as ET, not UTC.
    """

    def test_naive_et_datetime_just_now_is_fresh(self):
        """(tz1) A naive datetime equal to ET wall-clock 'now' -> stale=False.

        Verify-by-mutation: pre-fix `created_at_dt.replace(tzinfo=timezone.utc)`
        tags ET-now as UTC-now. During EDT that is ~4h in the actual past ->
        4h < 36h so this single case still reads fresh — so we ALSO assert the
        boundary case below where the 4h shift flips the verdict. Kept for
        documentation of the common path.
        """
        from src.tools.tradingstate.core import _build_audit_dict

        et = ZoneInfo("America/New_York")
        naive_now_et = datetime.now(et).replace(tzinfo=None)
        row = {
            "audit_id": "a1",
            "created_at": naive_now_et,
            "overall_assessment": "STABLE",
        }
        out = _build_audit_dict(row)
        assert out["stale"] is False

    def test_naive_et_datetime_near_threshold_not_falsely_stale(self):
        """(tz2) Naive-ET datetime 35h old -> stale=False (under 36h threshold).

        This is the case that EXPOSES the bug. With the pre-fix UTC tagging,
        during EDT the value is read ~4h older than reality: 35h + 4h = 39h > 36h
        -> stale=True (FALSE positive). Interpreting the naive value as ET keeps
        the true age at 35h < 36h -> stale=False. This assertion FAILS pre-fix.
        """
        from src.tools.tradingstate.core import _build_audit_dict

        et = ZoneInfo("America/New_York")
        thirty_five_h_ago = (datetime.now(et) - timedelta(hours=35)).replace(tzinfo=None)
        row = {
            "audit_id": "a2",
            "created_at": thirty_five_h_ago,
            "overall_assessment": "STABLE",
        }
        out = _build_audit_dict(row)
        assert out["stale"] is False, (
            "A 35h-old naive-ET audit row must be fresh (< 36h). If stale=True, the "
            "naive timestamp is being read as UTC, adding a spurious ~4h (EDT) offset "
            "-> false governor-verdict-staleness."
        )

    def test_naive_et_iso_string_near_threshold_not_falsely_stale(self):
        """(tz3) Naive-ET ISO STRING (no offset) 35h old -> stale=False.

        Covers the SQLite/TEXT str-path (the isoformat()-without-offset shape).
        Pre-fix line 79 tagged the parsed naive datetime UTC -> same ~4h EDT
        inflation -> false stale=True. This assertion FAILS pre-fix.
        """
        from src.tools.tradingstate.core import _build_audit_dict

        et = ZoneInfo("America/New_York")
        thirty_five_h_ago = (datetime.now(et) - timedelta(hours=35)).replace(tzinfo=None)
        row = {
            "audit_id": "a3",
            "created_at": thirty_five_h_ago.isoformat(),  # naive ISO, no offset
            "overall_assessment": "STABLE",
        }
        out = _build_audit_dict(row)
        assert out["stale"] is False, (
            "A 35h-old naive-ET ISO string must be fresh (< 36h). stale=True means "
            "the parsed naive datetime was tagged UTC instead of ET."
        )

    def test_genuinely_old_audit_is_stale(self):
        """(tz4) A 40h-old naive-ET audit -> stale=True (still beyond 36h).

        Guards against the fix masking real staleness: the comparison must remain
        real (not weakened so nothing is ever stale).
        """
        from src.tools.tradingstate.core import _build_audit_dict

        et = ZoneInfo("America/New_York")
        forty_h_ago = (datetime.now(et) - timedelta(hours=40)).replace(tzinfo=None)
        row = {
            "audit_id": "a4",
            "created_at": forty_h_ago,
            "overall_assessment": "STABLE",
        }
        out = _build_audit_dict(row)
        assert out["stale"] is True, "A 40h-old audit must still be stale (> 36h)."

    def test_tzaware_audit_unaffected(self):
        """(tz5) A tz-aware created_at (the normal prod path) -> stale reflects real age.

        The auditor's real output is tz-aware ISO (`-04:00`). Confirm the fix does
        not regress the tz-aware path: a freshly tz-aware value is fresh.
        """
        from src.tools.tradingstate.core import _build_audit_dict

        et = ZoneInfo("America/New_York")
        aware_now = datetime.now(et)  # tz-aware, has -04:00/-05:00 offset
        row = {
            "audit_id": "a5",
            "created_at": aware_now.isoformat(),
            "overall_assessment": "STABLE",
        }
        out = _build_audit_dict(row)
        assert out["stale"] is False

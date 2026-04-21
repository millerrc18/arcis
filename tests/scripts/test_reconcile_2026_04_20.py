"""Regression tests for scripts/reconcile_2026_04_20.py — Track A of Sprint 2.

Tests 5 behaviors:
  1. Happy-path end-to-end against a seeded test DB.
  2. Idempotency (second run is a no-op).
  3. Abort-on-persistent-short (Alpaca still short -> exit 3, DB unchanged).
  4. Abort-on-missing-kill-switch (no file -> exit 2, DB unchanged).
  5. Transaction rollback on verification mismatch (missing row -> exit 4,
     DB state reverts for all UPDATEs already staged).

Read-only: no live DB, no live Alpaca. All state is in tmp_path fixtures.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import reconcile_2026_04_20 as rec

# --- Seed helpers --------------------------------------------------------


def _seed_row(conn: sqlite3.Connection, trade_id: str, ticker: str,
              status: str, broker: str = "alpaca",
              exit_reason: str | None = None) -> None:
    """Insert a minimal shadow_trades row for the test DB.

    shadow_trades requires NOT NULL on trade_id / ticker / direction /
    status / created_at; other columns accept NULL. The script ignores
    every column it doesn't touch.
    """
    from datetime import datetime, timezone
    now = datetime(2026, 4, 15, tzinfo=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, direction, status, broker, exit_reason, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, ticker, "long", status, broker, exit_reason, now, now),
    )


def _seed_model(conn: sqlite3.Connection, name: str, status: str,
                notes: str | None = None) -> None:
    """model_versions requires NOT NULL version_id and created_at."""
    from datetime import datetime, timezone
    now = datetime(2026, 3, 25, tzinfo=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO model_versions "
        "(version_id, version_name, status, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("test-version-uuid", name, status, notes, now),
    )


@pytest.fixture
def seeded_db(tmp_path):
    """Create a schema-complete DB seeded with all 19 target rows + 1 model."""
    from src.schema.sqlite import create_all_tables

    db = str(tmp_path / "test.db")
    create_all_tables(db)

    with sqlite3.connect(db) as conn:
        # 12 CLOSE_TRADES — all start as needs_manual_review
        for trade_id, ticker, _ in rec.CLOSE_TRADES:
            # TGT #12 starts as broker=ib to test the correction path;
            # the other 11 are broker=alpaca.
            broker = "ib" if trade_id == rec.TGT_BROKER_CORRECT_ID else "alpaca"
            _seed_row(
                conn, trade_id, ticker, "needs_manual_review",
                broker=broker, exit_reason="exit_overshoot_detected",
            )

        # 7 ORPHAN_TRADES — 4 exit_failed + 3 open, various prior reasons
        orphan_prior_status = {
            "1630b6c5-d7df-44f6-aca6-d0c4826ca697": ("exit_failed", "timeout"),
            "bb10c4b7-1952-40fd-9a3a-c5db9b96c018": ("exit_failed", "timeout"),
            "9ad299c0-cf79-45f1-854a-3aa7b6ee2925": ("exit_failed", "target_1_hit"),
            "ce1322fd-3035-4e2d-9c08-10ad3755e00b": ("exit_failed", "stop_hit"),
            "09b629e3-0bf6-4ba7-8293-73f4f3f90265": ("open", None),
            "748a97f1-c0e9-462c-9ce0-41deaefa00dc": ("open", None),
            "730a113b-eb9b-4040-a320-6aaebacb3f2a": ("open", None),
        }
        for trade_id, ticker, _ in rec.ORPHAN_TRADES:
            status, reason = orphan_prior_status[trade_id]
            broker = "ib" if trade_id == "730a113b-eb9b-4040-a320-6aaebacb3f2a" else "alpaca"
            _seed_row(conn, trade_id, ticker, status, broker=broker,
                      exit_reason=reason)

        _seed_model(conn, rec.MODEL_NAME, "rolled_back",
                    notes="original rollback")
        conn.commit()
    return db


@pytest.fixture
def kill_switch(tmp_path):
    """Create a kill-switch file; return its path."""
    path = tmp_path / "trading_halted"
    path.touch()
    return path


@pytest.fixture
def audit_log(tmp_path):
    """Return audit-log path (not pre-created)."""
    return tmp_path / "audit.log"


def _zero_positions():
    """Stub for positions_fn returning no positions (no shorts)."""
    return []


def _short_nvda_positions():
    """Stub for positions_fn returning NVDA still short."""
    return [
        {"symbol": "NVDA", "qty": -100.0, "avg_entry_price": 188.0},
        {"symbol": "AMD",  "qty": 48.0,   "avg_entry_price": 278.0},
    ]


# --- Tests ---------------------------------------------------------------


def test_happy_path_end_to_end(seeded_db, kill_switch, audit_log):
    """Full run against seeded DB with no shorts and kill-switch present."""
    rc = rec.reconcile(
        db_path=seeded_db,
        kill_switch_path=kill_switch,
        audit_log_path=audit_log,
        positions_fn=_zero_positions,
    )
    assert rc == 0, "expected success exit code"

    with sqlite3.connect(seeded_db) as conn:
        conn.row_factory = sqlite3.Row

        # 12 close rows → status='closed', exit_reason='manual_reconcile'
        close_ids = [t[0] for t in rec.CLOSE_TRADES]
        ph = ",".join("?" * len(close_ids))
        rows = conn.execute(
            f"SELECT trade_id, status, exit_reason FROM shadow_trades "
            f"WHERE trade_id IN ({ph})", close_ids,
        ).fetchall()
        assert len(rows) == 12
        for r in rows:
            assert r["status"] == "closed", f"{r['trade_id']}"
            assert r["exit_reason"] == "manual_reconcile"

        # 7 orphan rows → status='exit_abandoned', exit_reason='phantom_row_cleanup'
        orphan_ids = [t[0] for t in rec.ORPHAN_TRADES]
        ph = ",".join("?" * len(orphan_ids))
        rows = conn.execute(
            f"SELECT trade_id, status, exit_reason FROM shadow_trades "
            f"WHERE trade_id IN ({ph})", orphan_ids,
        ).fetchall()
        assert len(rows) == 7
        for r in rows:
            assert r["status"] == "exit_abandoned"
            assert r["exit_reason"] == "phantom_row_cleanup"

        # TGT broker corrected from ib to alpaca
        tgt = conn.execute(
            "SELECT broker FROM shadow_trades WHERE trade_id=?",
            (rec.TGT_BROKER_CORRECT_ID,),
        ).fetchone()
        assert tgt["broker"] == "alpaca"

        # model_versions row re-activated
        model = conn.execute(
            "SELECT status, notes FROM model_versions WHERE version_name=?",
            (rec.MODEL_NAME,),
        ).fetchone()
        assert model["status"] == "active"
        assert "Re-activated 2026-04-20" in model["notes"]

    # Audit log written
    assert audit_log.exists()
    log_text = audit_log.read_text(encoding="utf-8")
    assert "[START]" in log_text
    assert "[SUCCESS]" in log_text


def test_idempotent_second_run_is_noop(seeded_db, kill_switch, audit_log):
    """Running twice: second run produces only SKIP entries, no UPDATEs."""
    rc1 = rec.reconcile(
        db_path=seeded_db,
        kill_switch_path=kill_switch,
        audit_log_path=audit_log,
        positions_fn=_zero_positions,
    )
    assert rc1 == 0

    # Snapshot DB state after first run
    with sqlite3.connect(seeded_db) as conn:
        snap_trades = conn.execute(
            "SELECT trade_id, status, exit_reason, updated_at, broker "
            "FROM shadow_trades ORDER BY trade_id",
        ).fetchall()
        snap_model = conn.execute(
            "SELECT version_name, status, notes FROM model_versions "
            "WHERE version_name=?", (rec.MODEL_NAME,),
        ).fetchone()

    # Truncate audit log so we can check only the second run's output
    audit_log.unlink()

    rc2 = rec.reconcile(
        db_path=seeded_db,
        kill_switch_path=kill_switch,
        audit_log_path=audit_log,
        positions_fn=_zero_positions,
    )
    assert rc2 == 0

    # DB state unchanged between runs
    with sqlite3.connect(seeded_db) as conn:
        snap_trades2 = conn.execute(
            "SELECT trade_id, status, exit_reason, updated_at, broker "
            "FROM shadow_trades ORDER BY trade_id",
        ).fetchall()
        snap_model2 = conn.execute(
            "SELECT version_name, status, notes FROM model_versions "
            "WHERE version_name=?", (rec.MODEL_NAME,),
        ).fetchone()
    assert snap_trades == snap_trades2, "trade rows must not change on re-run"
    assert snap_model == snap_model2, "model row must not change on re-run"

    # Second-run log shows only SKIP entries for the trade loops
    log_text = audit_log.read_text(encoding="utf-8")
    assert "[SUCCESS]" in log_text
    # 19 trade SKIPs + 1 broker SKIP + 1 model SKIP
    assert log_text.count("already resolved") == 19
    # No [CLOSE] / [ORPHAN] / [MODEL] / [BROKER] update lines on second run
    assert "[CLOSE] " not in log_text
    assert "[ORPHAN] " not in log_text
    assert "[MODEL] " not in log_text
    assert "[BROKER] " not in log_text


def test_abort_on_persistent_short(seeded_db, kill_switch, audit_log):
    """If Alpaca still shows a short in any target ticker, abort with exit 3."""
    rc = rec.reconcile(
        db_path=seeded_db,
        kill_switch_path=kill_switch,
        audit_log_path=audit_log,
        positions_fn=_short_nvda_positions,
    )
    assert rc == 3

    # No updates applied
    with sqlite3.connect(seeded_db) as conn:
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE trade_id=?",
            (rec.CLOSE_TRADES[0][0],),
        ).fetchone()
    assert row[0] == "needs_manual_review", "DB must be unchanged after abort"

    log_text = audit_log.read_text(encoding="utf-8")
    assert "NVDA still short qty=-100" in log_text
    assert "[ABORT]" in log_text


def test_abort_on_missing_kill_switch(seeded_db, tmp_path, audit_log):
    """If the kill-switch file doesn't exist, abort with exit 2."""
    missing = tmp_path / "does_not_exist"
    rc = rec.reconcile(
        db_path=seeded_db,
        kill_switch_path=missing,
        audit_log_path=audit_log,
        positions_fn=_zero_positions,
    )
    assert rc == 2

    # No updates applied
    with sqlite3.connect(seeded_db) as conn:
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE trade_id=?",
            (rec.CLOSE_TRADES[0][0],),
        ).fetchone()
    assert row[0] == "needs_manual_review"

    log_text = audit_log.read_text(encoding="utf-8")
    assert "kill-switch file missing" in log_text


def test_transaction_rollback_on_verification_mismatch(
    seeded_db, kill_switch, audit_log,
):
    """If the post-update verification count mismatches (row missing from seed),
    the transaction rolls back and all staged UPDATEs revert."""
    # Delete one of the close rows from the seed to force a count mismatch:
    # the update loop will skip it (row not found), then the post-update
    # verification will see 11 closed instead of 12 -> rollback.
    missing_trade_id = rec.CLOSE_TRADES[0][0]
    with sqlite3.connect(seeded_db) as conn:
        conn.execute(
            "DELETE FROM shadow_trades WHERE trade_id=?",
            (missing_trade_id,),
        )
        conn.commit()

    # Snapshot DB state before running
    with sqlite3.connect(seeded_db) as conn:
        pre = conn.execute(
            "SELECT trade_id, status, exit_reason FROM shadow_trades "
            "ORDER BY trade_id",
        ).fetchall()
        pre_model = conn.execute(
            "SELECT status FROM model_versions WHERE version_name=?",
            (rec.MODEL_NAME,),
        ).fetchone()

    rc = rec.reconcile(
        db_path=seeded_db,
        kill_switch_path=kill_switch,
        audit_log_path=audit_log,
        positions_fn=_zero_positions,
    )
    assert rc == 4, "expected verification-failure exit code"

    # DB state reverted — all the 11 + 7 + 1 updates that WOULD have
    # fired inside the transaction must have been rolled back.
    with sqlite3.connect(seeded_db) as conn:
        post = conn.execute(
            "SELECT trade_id, status, exit_reason FROM shadow_trades "
            "ORDER BY trade_id",
        ).fetchall()
        post_model = conn.execute(
            "SELECT status FROM model_versions WHERE version_name=?",
            (rec.MODEL_NAME,),
        ).fetchone()

    assert pre == post, "rollback must restore all trade-row state"
    assert pre_model == post_model, "rollback must restore model row state"

    log_text = audit_log.read_text(encoding="utf-8")
    assert "Verification failed" in log_text
    assert "rolling back" in log_text

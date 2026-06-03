"""Interrupted-run / forensic-marker safe-re-entry tests (#95, T13).

(a) Abort AFTER the TRUNCATE commit (inject a failure in Phase 5, after the
    Phase-3.2 marker write) → assert WIPE_COMMITTED.marker exists + manifest.json
    is ABSENT, and a re-run hits ALREADY_CLEAN safely (the wipe DID commit).
(b) Abort after the SQLite archive but before the empty step → assert the archive
    file is intact + non-empty and a re-run completes the empty step.

NEVER prod 5433; NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1. Uses a 5434 scratch DB +
a tmp SQLite. The ephemeral DB is always dropped.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import psycopg2
import pytest

import scripts.clean_slate_wipe as cs
from scripts._clean_slate import backup as backup_mod
from scripts._clean_slate import sqlite_retire as sqlite_retire_mod
from src.schema.postgres import create_all_tables

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="integration(authoritative-coverage:pg-tests): needs TEST_DATABASE_URL 5434 server",
)


def _maintenance_dsn() -> str:
    head, _, _db = os.environ["TEST_DATABASE_URL"].rpartition("/")
    return f"{head}/postgres"


def _dsn_for(db: str) -> str:
    head, _, _db = os.environ["TEST_DATABASE_URL"].rpartition("/")
    return f"{head}/{db}"


@pytest.fixture
def scratch_dsn():
    db_name = f"cs_int_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(_maintenance_dsn(), connect_timeout=10)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    dsn = _dsn_for(db_name)
    try:
        create_all_tables(dsn)
        yield dsn
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin.close()


@pytest.fixture(autouse=True)
def _gates_open(monkeypatch):
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: True)
    monkeypatch.setattr(
        backup_mod, "run_backup_and_verify",
        lambda dsn, s, out: {"result": "BACKUP_VERIFIED", "dump_path": str(out)},
    )


def _seed(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, created_at) "
            "VALUES ('cs-rec-1', 'AAA', NOW()::text)"
        )
        cur.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, status, created_at, updated_at) "
            "VALUES ('cs-st-1', 'AAA', 'open', NOW()::text, NOW()::text)"
        )
    conn.close()


def _count(dsn: str, table: str) -> int:
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            return int(cur.fetchone()[0])
    finally:
        conn.close()


# ── (a) abort AFTER the TRUNCATE commit, before the final manifest ──────────


def test_abort_after_commit_marker_present_manifest_absent_then_safe_reentry(
    scratch_dsn, monkeypatch, tmp_path
):
    _seed(scratch_dsn)

    # Inject a failure in Phase 5 (after the Phase-3.2 marker write, before Phase 7).
    def boom(*a, **k):
        raise RuntimeError("injected interruption after TRUNCATE commit")
    monkeypatch.setattr(sqlite_retire_mod, "archive_and_empty_sqlite", boom)

    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(RuntimeError, match="injected interruption"):
        entry(dsn=scratch_dsn, confirm=True, out_dir=tmp_path)

    # The TRUNCATE DID commit (wipe is irreversible).
    assert _count(scratch_dsn, "shadow_trades") == 0
    # Exactly one run dir; marker present, manifest absent.
    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    marker = run_dir / "WIPE_COMMITTED.marker"
    assert marker.exists(), "WIPE_COMMITTED.marker must exist after commit"
    assert marker.stat().st_size > 0
    assert not (run_dir / "manifest.json").exists(), "manifest must be absent on interrupt"

    # A committed-wipe-without-manifest is detectable: marker present + no manifest.
    # Re-entry is SAFE — the re-run hits ALREADY_CLEAN (all WIPE empty now).
    entry2 = cs._make_entry_point(log_path=tmp_path / "audit2.log")
    manifest2 = entry2(dsn=scratch_dsn, confirm=True, skip_sqlite=True, out_dir=tmp_path)
    assert manifest2["result"] == "ALREADY_CLEAN"


# ── (b) abort after the SQLite archive but before the empty step ────────────


def test_abort_after_sqlite_archive_before_empty_archive_intact(monkeypatch, tmp_path):
    # Build a tmp SQLite with a seeded WIPE table.
    src = tmp_path / "ai_research_desk.sqlite3"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE shadow_trades (trade_id TEXT, ticker TEXT)")
    conn.execute("INSERT INTO shadow_trades VALUES ('s1', 'AAA')")
    conn.commit()
    conn.close()

    archive_dir = tmp_path / "archive"

    # Patch the in-place DELETE step (sqlite3.connect on the LIVE file for empty)
    # to raise AFTER the archive + fsync completed. We wrap the real fsync helper
    # so the archive is fully flushed, then force the empty step to fail.
    real_fsync_file = sqlite_retire_mod._fsync_file
    state = {"archived": False}

    def tracking_fsync(path):
        real_fsync_file(path)
        state["archived"] = True
    monkeypatch.setattr(sqlite_retire_mod, "_fsync_file", tracking_fsync)

    real_connect = sqlite3.connect

    def failing_connect(target, *a, **k):
        # Fail the live-src writable open ONLY after the archive was fsync'd — i.e.
        # the empty step. The VACUUM-INTO archive open (before fsync) still works.
        if (
            state["archived"]
            and str(target) == str(src)
            and "mode=ro" not in str(target)
        ):
            raise sqlite3.OperationalError("injected: empty step interrupted")
        return real_connect(target, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", failing_connect)

    with pytest.raises(sqlite3.OperationalError, match="empty step interrupted"):
        sqlite_retire_mod.archive_and_empty_sqlite(src, archive_dir)

    # Archive is intact + non-empty + fsync'd; the live file is untouched.
    assert state["archived"], "archive must have been fsync'd before the empty step"
    archive_file = archive_dir / src.name
    assert archive_file.exists()
    assert archive_file.stat().st_size > 0
    # Live file still has its row (empty step never completed).
    monkeypatch.setattr(sqlite3, "connect", real_connect)
    live = sqlite3.connect(str(src))
    try:
        assert live.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0] == 1
    finally:
        live.close()

    # Re-run completes the empty step (archive already exists; a 2nd archive copy
    # is fine — it overwrites). The live WIPE table is emptied this time.
    verdict = sqlite_retire_mod.archive_and_empty_sqlite(src, archive_dir)
    assert verdict["result"] == "SQLITE_RETIRED"
    live = sqlite3.connect(str(src))
    try:
        assert live.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0] == 0
    finally:
        live.close()

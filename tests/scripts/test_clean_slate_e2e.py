"""End-to-end dry-run+confirm rehearsal against a 5434 scratch DB (#95, T14).

Provisions a 5434 scratch DB from the registry, seeds representative WIPE + KEEP
rows + an FK chain + a tmp SQLite, and drives the FULL clean_slate_wipe(confirm=True)
against the SCRATCH DSN (non-prod) end-to-end: live-schema+FK reconciliation PASS,
backup+verify ran (ephemeral verify DB created+dropped), TRUNCATE deltas correct,
KEEP preserved, SQLite tmp archived+emptied, manifest written with ALL verdicts
(reconciliation, backup, post-verify-db, POST_VERIFY_CONFIG_PENDING), and a clean
re-run short-circuits ALREADY_CLEAN.

Rehearses the full flow WITHOUT ever touching prod 5433. The docker pg_dump is
mocked (the scratch DSN is not a docker container); the ephemeral verify-restore
path runs FOR REAL against the 5434 server. NEVER prod 5433; NEVER
ARCIS_ALLOW_PROD_PG_IN_TESTS=1.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import uuid
from pathlib import Path

import psycopg2
import pytest

import scripts.clean_slate_wipe as cs
from scripts._clean_slate import backup as backup_mod
from scripts._clean_slate import config_verify as config_verify_mod
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


def _server_has_db(db_name: str) -> bool:
    admin = psycopg2.connect(_maintenance_dsn(), connect_timeout=10)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            return cur.fetchone() is not None
    finally:
        admin.close()


@pytest.fixture
def scratch_dsn():
    db_name = f"cs_e2e_{uuid.uuid4().hex[:12]}"
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
            "(trade_id, ticker, recommendation_id, status, created_at, updated_at) "
            "VALUES ('cs-st-1', 'AAA', 'cs-rec-1', 'open', NOW()::text, NOW()::text)"
        )
        cur.execute(
            "INSERT INTO macro_snapshots "
            "(series_id, series_name, value, collected_at, collected_date) "
            "VALUES ('DGS10', 'ten-yr', 4.5, NOW()::text, CURRENT_DATE::text)"
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


@pytest.fixture(autouse=True)
def _gates_open(monkeypatch):
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: True)
    # Ollama read is out-of-scope external; default to "not checked".
    monkeypatch.setattr(config_verify_mod, "_ollama_loaded_models", lambda: None)


def _wire_real_ephemeral_backup(monkeypatch, source_dsn: str):
    """Exercise the REAL ephemeral verify-restore path on 5434, with the docker
    pg_dump mocked (synthetic 80-table dump) and the psql restore simulated by
    provisioning the verify DB from the registry."""
    created: list[str] = []

    def fake_dump(out_sql):
        out_sql.parent.mkdir(parents=True, exist_ok=True)
        lines = ["-- synthetic\n"]
        for i in range(80):
            lines.append(f"CREATE TABLE t_{i} (id INT);\n")
        lines.append("-- pad " + ("x" * (backup_mod.MIN_DUMP_BYTES + 1024)))
        out_sql.write_text("".join(lines), encoding="utf-8")
    monkeypatch.setattr(backup_mod, "_pg_dump_to_file", fake_dump)

    real_split = backup_mod._split_scratch_dsn

    def tracking_split(server_dsn, new_db):
        created.append(new_db)
        return real_split(server_dsn, new_db)
    monkeypatch.setattr(backup_mod, "_split_scratch_dsn", tracking_split)

    class _OK:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, *a, **k):
        # Simulate a FAITHFUL restore: provision the registry schema into the
        # verify DB AND replicate the seeded source rows (a real pg_dump/psql
        # restore would carry the data; the docker mock cannot, so we copy the
        # rows the test seeded so the count-compare matches reality).
        verify_dsn = cmd[1]
        create_all_tables(verify_dsn)
        _replicate_seeded_rows(source_dsn, verify_dsn)
        return _OK()
    monkeypatch.setattr(subprocess, "run", fake_run)
    return created


def _replicate_seeded_rows(source_dsn: str, verify_dsn: str):
    """Copy the seeded rows from source → verify (simulates a faithful restore)."""
    src = psycopg2.connect(source_dsn)
    dst = psycopg2.connect(verify_dsn)
    dst.autocommit = True
    try:
        with src.cursor() as scur, dst.cursor() as dcur:
            scur.execute(
                "SELECT recommendation_id, ticker, created_at FROM recommendations"
            )
            for rid, ticker, created in scur.fetchall():
                dcur.execute(
                    "INSERT INTO recommendations (recommendation_id, ticker, created_at) "
                    "VALUES (%s, %s, %s)",
                    (rid, ticker, created),
                )
            scur.execute(
                "SELECT trade_id, ticker, recommendation_id, status, created_at, updated_at "
                "FROM shadow_trades"
            )
            for row in scur.fetchall():
                dcur.execute(
                    "INSERT INTO shadow_trades "
                    "(trade_id, ticker, recommendation_id, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    row,
                )
            scur.execute(
                "SELECT series_id, series_name, value, collected_at, collected_date "
                "FROM macro_snapshots"
            )
            for row in scur.fetchall():
                dcur.execute(
                    "INSERT INTO macro_snapshots "
                    "(series_id, series_name, value, collected_at, collected_date) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    row,
                )
    finally:
        src.close()
        dst.close()


def test_full_confirm_rehearsal_against_scratch(scratch_dsn, monkeypatch, tmp_path):
    _seed(scratch_dsn)
    created_verify_dbs = _wire_real_ephemeral_backup(monkeypatch, scratch_dsn)

    # A tmp SQLite with a seeded WIPE table for the retire phase.
    sqlite_src = tmp_path / "ai_research_desk.sqlite3"
    sconn = sqlite3.connect(str(sqlite_src))
    sconn.execute("CREATE TABLE shadow_trades (trade_id TEXT, ticker TEXT)")
    sconn.execute("INSERT INTO shadow_trades VALUES ('s1', 'AAA')")
    sconn.commit()
    sconn.close()

    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(
        dsn=scratch_dsn,
        scratch_server_dsn=_maintenance_dsn(),
        confirm=True,
        out_dir=tmp_path,
        sqlite_path=sqlite_src,
        sqlite_archive_dir=tmp_path / "sqlite_archive",
    )

    # ── Every phase verdict in the manifest ──
    assert manifest["result"] == "WIPE_COMPLETE"
    assert manifest["live_schema"]["result"] == "LIVE_SCHEMA_OK"
    assert manifest["live_fk_edges"]["result"] == "LIVE_FK_OK"
    assert manifest["backup"]["result"] == "BACKUP_VERIFIED"
    assert manifest["backup"]["restored_table_count"] == 80
    assert manifest["truncate"]["deltas"]["shadow_trades"] == (1, 0)
    assert manifest["post_verify_db"]["result"] == "POST_VERIFY_PASSED"
    assert manifest["post_verify_config"]["result"] == "POST_VERIFY_CONFIG_PENDING"
    assert manifest["sqlite_retire"]["result"] == "SQLITE_RETIRED"

    # ── DB state: WIPE → 0, KEEP preserved ──
    assert _count(scratch_dsn, "shadow_trades") == 0
    assert _count(scratch_dsn, "recommendations") == 0
    assert _count(scratch_dsn, "macro_snapshots") == 1

    # ── Ephemeral verify DB was created AND dropped; shared test DB untouched ──
    assert created_verify_dbs
    for db in created_verify_dbs:
        assert db.startswith("clean_slate_verify_")
        assert db != "halcyon"
        assert not _server_has_db(db), f"ephemeral verify DB {db} not dropped"

    # ── SQLite archived + emptied (source still exists, not deleted) ──
    assert sqlite_src.exists()
    archived = sqlite3.connect(str(sqlite_src))
    try:
        assert archived.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0] == 0
    finally:
        archived.close()

    # ── Manifest written atomically + forensic marker present ──
    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    run_dir = next(p for p in run_dirs if (p / "manifest.json").exists())
    assert (run_dir / "WIPE_COMMITTED.marker").exists()

    # ── Idempotent re-run short-circuits ALREADY_CLEAN ──
    entry2 = cs._make_entry_point(log_path=tmp_path / "audit2.log")
    manifest2 = entry2(
        dsn=scratch_dsn,
        scratch_server_dsn=_maintenance_dsn(),
        confirm=True,
        skip_sqlite=True,
        out_dir=tmp_path,
    )
    assert manifest2["result"] == "ALREADY_CLEAN"


def test_dry_run_then_confirm_sequence(scratch_dsn, monkeypatch, tmp_path):
    # Dry run first (no mutation), then confirm (mutates). Mirrors the operator
    # runbook sequence.
    _seed(scratch_dsn)
    _wire_real_ephemeral_backup(monkeypatch, scratch_dsn)

    from src.tools._safety import DryRunResult

    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    dry = entry(
        dsn=scratch_dsn, scratch_server_dsn=_maintenance_dsn(), out_dir=tmp_path,
    )
    assert isinstance(dry, DryRunResult)
    assert _count(scratch_dsn, "shadow_trades") == 1  # dry run did NOT mutate

    confirmed = entry(
        dsn=scratch_dsn, scratch_server_dsn=_maintenance_dsn(),
        confirm=True, skip_sqlite=True, out_dir=tmp_path,
    )
    assert confirmed["result"] == "WIPE_COMPLETE"
    assert _count(scratch_dsn, "shadow_trades") == 0

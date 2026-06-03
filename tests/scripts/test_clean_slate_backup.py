"""Backup verify-or-refuse + ephemeral-scratch-lifecycle tests (#95, T5).

Mocks the docker pg_dump subprocess (synthetic dump file) and the psql restore
(provisions the registry schema into the ephemeral DB to simulate a successful
restore). Exercises the REAL CREATE/assert-empty/DROP DATABASE ephemeral lifecycle
on the 5434 SERVER. Verify-by-mutation on the shortfall + excess + divergence
cases (assert they RAISE, not WARN).

NEVER prod 5433; NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1. The ephemeral DB lives on
the 5434 server and is always dropped; the shared `halcyon` test DB is never the
restore target.
"""

from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

from scripts._clean_slate import backup as bk
from scripts._clean_slate._errors import BackupVerifyError
from scripts._clean_slate.classification import KEEP_TABLES, WIPE_TABLES
from src.schema.postgres import create_all_tables

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="integration(authoritative-coverage:pg-tests): needs TEST_DATABASE_URL 5434 server",
)


def _maintenance_dsn() -> str:
    base = os.environ["TEST_DATABASE_URL"]
    head, _, _db = base.rpartition("/")
    return f"{head}/postgres"


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
def source_db():
    """A registry-provisioned ephemeral 'prod-stand-in' DB for count queries.

    Stands in for prod on the count-compare side WITHOUT being prod (5434, not
    5433). Always dropped on teardown.
    """
    db_name = f"cs_src_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(_maintenance_dsn(), connect_timeout=10)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    head, _, _ = os.environ["TEST_DATABASE_URL"].rpartition("/")
    dsn = f"{head}/{db_name}"
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


def _write_dump(path, n_create_tables: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["-- synthetic dump\n"]
    for i in range(n_create_tables):
        lines.append(f"CREATE TABLE t_{i} (id INT);\n")
    # Pad to exceed the 1MB minimum.
    lines.append("-- padding " + ("x" * (bk.MIN_DUMP_BYTES + 1024)) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _patch_dump(monkeypatch, n_create_tables: int):
    def fake_dump(out_sql):
        _write_dump(out_sql, n_create_tables)
    monkeypatch.setattr(bk, "_pg_dump_to_file", fake_dump)


def _patch_restore_success(monkeypatch):
    """Make the psql restore a no-op success (the verify DB is provisioned
    separately by _patch_restore_provisions to match counts)."""
    import subprocess

    class _OK:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, *a, **kw):
        return _OK()

    monkeypatch.setattr(subprocess, "run", fake_run)


# ── Verify-by-mutation: structural REFUSE paths ─────────────────────────────


def test_undersize_dump_refuses_backup(monkeypatch, source_db, tmp_path):
    def fake_dump(out_sql):
        out_sql.parent.mkdir(parents=True, exist_ok=True)
        out_sql.write_text("CREATE TABLE x (id INT);\n", encoding="utf-8")  # < 1MB
    monkeypatch.setattr(bk, "_pg_dump_to_file", fake_dump)
    with pytest.raises(BackupVerifyError) as exc:
        bk.run_backup_and_verify(source_db, _maintenance_dsn(), tmp_path)
    assert exc.value.code == "REFUSE_BACKUP"


def test_create_count_shortfall_hard_refuses(monkeypatch, source_db, tmp_path):
    # 79 < 80 → HARD REFUSE_BACKUP (NOT a warn).
    _patch_dump(monkeypatch, 79)
    with pytest.raises(BackupVerifyError) as exc:
        bk.run_backup_and_verify(source_db, _maintenance_dsn(), tmp_path)
    assert exc.value.code == "REFUSE_BACKUP"
    assert "shortfall" in str(exc.value).lower()


def test_create_count_excess_refuses_schema_drift(monkeypatch, source_db, tmp_path):
    # 81 > 80 → REFUSE_SCHEMA_DRIFT.
    _patch_dump(monkeypatch, 81)
    with pytest.raises(BackupVerifyError) as exc:
        bk.run_backup_and_verify(source_db, _maintenance_dsn(), tmp_path)
    assert exc.value.code == "REFUSE_SCHEMA_DRIFT"


def test_count_divergent_restore_refuses_verify(monkeypatch, source_db, tmp_path):
    # Dump structurally valid (80), restore "succeeds" but leaves the verify DB
    # EMPTY (no tables) while prod has the full schema → count divergence +
    # table-count mismatch → REFUSE_VERIFY.
    _patch_dump(monkeypatch, 80)
    # Seed a row in a WIPE table on the source so prod count != ephemeral (0).
    conn = psycopg2.connect(source_db)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, created_at) "
            "VALUES ('cs-div-1', 'AAA', NOW()::text)"
        )
    conn.close()
    _patch_restore_success(monkeypatch)  # restore is a no-op → verify DB empty
    with pytest.raises(BackupVerifyError) as exc:
        bk.run_backup_and_verify(source_db, _maintenance_dsn(), tmp_path)
    assert exc.value.code == "REFUSE_VERIFY"


# ── Happy path + ephemeral lifecycle ────────────────────────────────────────


def test_valid_dump_and_matching_restore_verifies(monkeypatch, source_db, tmp_path):
    # Make the "restore" actually provision the verify DB from the registry so
    # ephemeral-vs-source counts match (both empty schemas, equal table count).
    _patch_dump(monkeypatch, 80)

    created_verify_dbs: list[str] = []
    real_split = bk._split_scratch_dsn

    def tracking_split(server_dsn, new_db):
        created_verify_dbs.append(new_db)
        return real_split(server_dsn, new_db)
    monkeypatch.setattr(bk, "_split_scratch_dsn", tracking_split)

    import subprocess

    class _OK:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, *a, **kw):
        # cmd is ["psql", verify_dsn, ...]; provision the registry schema into it.
        verify_dsn = cmd[1]
        create_all_tables(verify_dsn)
        return _OK()
    monkeypatch.setattr(subprocess, "run", fake_run)

    verdict = bk.run_backup_and_verify(source_db, _maintenance_dsn(), tmp_path)

    assert verdict["result"] == "BACKUP_VERIFIED"
    assert verdict["create_table_count"] == 80
    assert verdict["restored_table_count"] == 80
    # Empty source → BACKUP_OF_EMPTY_STATE tag present.
    assert verdict.get("empty_state_tag") == "BACKUP_OF_EMPTY_STATE"
    assert (tmp_path / "prod.sql").exists()

    # Ephemeral DB lifecycle: it was created AND dropped (absent now); the shared
    # halcyon test DB was never the target.
    assert created_verify_dbs, "no ephemeral verify DB was created"
    for db in created_verify_dbs:
        assert db.startswith("clean_slate_verify_")
        assert db != "halcyon"
        assert not _server_has_db(db), f"ephemeral DB {db} was not dropped"

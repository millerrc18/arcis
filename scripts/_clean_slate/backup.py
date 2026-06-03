"""Backup + verify-restore into a FRESH EPHEMERAL scratch DB (#95, §Phase1).

run_backup_and_verify(dsn, scratch_server_dsn, out_dir):
  1. `docker exec halcyon-pg pg_dump -U halcyon -d halcyon` → plain SQL.
  2. `docker cp` the dump → out_dir/prod.sql.
  3. Verify structure: size > 1 MB, SHA256, count `^CREATE TABLE` statements:
       == EXPECTED_TABLE_COUNT (80) → PASS
       <  80 (SHORTFALL)            → HARD REFUSE_BACKUP (structurally unrestorable)
       >  80 (EXCESS)               → REFUSE_SCHEMA_DRIFT (live drift §3.7 must resolve)
  4. Verify-restore into an EPHEMERAL DB (clean_slate_verify_<ISO8601>) CREATEd on
     the scratch SERVER (the maintenance DB, NOT the shared test DB), asserted
     empty pre-restore, psql-restored, per-table count-compared ephemeral-vs-prod,
     then DROPped in a finally (force-disconnect). Never the shared test DB.

Any backup/verify failure raises BackupVerifyError → REFUSEs the TRUNCATE even
with --confirm. Uses pg_connect(dsn=...) for count queries; subprocess for
docker/psql. NEVER connect_db; NEVER touches prod beyond the read-only dump.

Tests: tests/scripts/test_clean_slate_backup.py
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg2

from scripts._clean_slate._errors import BackupVerifyError
from scripts._clean_slate.classification import KEEP_TABLES, WIPE_TABLES
from src.schema import registry
from src.tools._db import pg_connect

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

EXPECTED_TABLE_COUNT = 80
MIN_DUMP_BYTES = 1024 * 1024  # 1 MB
PROD_CONTAINER = "halcyon-pg"
PROD_DB_USER = "halcyon"
PROD_DB_NAME = "halcyon"

# KEEP tables that are high-churn / read live, where a tiny ephemeral-vs-prod
# row drift is the live delta during the dump window, not a backup fault.
_HIGH_CHURN_KEEP = frozenset({"minute_bars", "live_prices"})
_HIGH_CHURN_TOLERANCE = 0.005  # ±0.5%

_CREATE_TABLE_RE = re.compile(r"^\s*CREATE TABLE\b", re.MULTILINE)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing output. Separated for test-mocking."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _pg_dump_to_file(out_sql: Path) -> None:
    """docker exec pg_dump (plain SQL) → docker cp to out_sql. Raises
    BackupVerifyError/REFUSE_BACKUP on any docker failure."""
    container_dump = "/tmp/clean_slate_prod.sql"
    dump = _run([
        "docker", "exec", PROD_CONTAINER,
        "pg_dump", "-U", PROD_DB_USER, "-d", PROD_DB_NAME,
        "-f", container_dump,
    ])
    if dump.returncode != 0:
        raise BackupVerifyError(
            "REFUSE_BACKUP", f"pg_dump failed (rc={dump.returncode}): {dump.stderr.strip()}"
        )
    out_sql.parent.mkdir(parents=True, exist_ok=True)
    cp = _run([
        "docker", "cp", f"{PROD_CONTAINER}:{container_dump}", str(out_sql),
    ])
    if cp.returncode != 0:
        raise BackupVerifyError(
            "REFUSE_BACKUP", f"docker cp failed (rc={cp.returncode}): {cp.stderr.strip()}"
        )


def _verify_dump_structure(out_sql: Path) -> dict[str, Any]:
    """Size + SHA + CREATE-count checks. Raises on shortfall/excess/undersize."""
    if not out_sql.exists():
        raise BackupVerifyError("REFUSE_BACKUP", f"dump file missing: {out_sql}")
    size = out_sql.stat().st_size
    if size < MIN_DUMP_BYTES:
        raise BackupVerifyError(
            "REFUSE_BACKUP", f"dump too small: {size} bytes < {MIN_DUMP_BYTES} (structurally suspect)"
        )
    sha = _sha256_file(out_sql)
    text = out_sql.read_text(encoding="utf-8", errors="replace")
    create_count = len(_CREATE_TABLE_RE.findall(text))
    if create_count < EXPECTED_TABLE_COUNT:
        raise BackupVerifyError(
            "REFUSE_BACKUP",
            f"CREATE TABLE shortfall: dump has {create_count} < {EXPECTED_TABLE_COUNT} "
            f"tables — a dump missing tables is structurally unrestorable; never "
            f"proceed to TRUNCATE.",
        )
    if create_count > EXPECTED_TABLE_COUNT:
        raise BackupVerifyError(
            "REFUSE_SCHEMA_DRIFT",
            f"CREATE TABLE excess: dump has {create_count} > {EXPECTED_TABLE_COUNT} "
            f"tables — live schema drift the live reconciliation must resolve first.",
        )
    return {"size_bytes": size, "sha256": sha, "create_table_count": create_count}


def _table_counts(dsn: str, tables: list[str]) -> dict[str, int]:
    """Per-table COUNT(*) (read-only). Tables absent from the DB count as -1 so a
    missing table is visible (not silently 0)."""
    counts: dict[str, int] = {}
    with pg_connect(dsn, read_only=True) as (_conn, cur):
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) AS c FROM "{t}"')
                counts[t] = int(cur.fetchone()["c"])
            except psycopg2.Error:
                # roll back the aborted subtransaction so the next query works
                _conn.rollback()
                counts[t] = -1
    return counts


def _split_scratch_dsn(scratch_server_dsn: str, new_db: str) -> str:
    """Return a DSN identical to scratch_server_dsn but pointing at new_db."""
    # psycopg2 accepts URL DSNs; rewrite the path component (last '/<db>').
    base, _, _old_db = scratch_server_dsn.rpartition("/")
    return f"{base}/{new_db}"


def _restore_and_compare(
    dsn: str,
    scratch_server_dsn: str,
    out_sql: Path,
    prod_wipe_counts: dict[str, int],
) -> dict[str, Any]:
    """CREATE ephemeral DB → assert empty → psql restore → count-compare → DROP.

    Raises BackupVerifyError/REFUSE_VERIFY on any restore error, non-empty
    pre-restore state, or count divergence beyond tolerance. The ephemeral DB is
    ALWAYS dropped (finally, force-disconnect).
    """
    ts = datetime.now(_ET).strftime("%Y%m%dT%H%M%S%f")
    verify_db = f"clean_slate_verify_{ts}"
    verify_dsn = _split_scratch_dsn(scratch_server_dsn, verify_db)

    admin = psycopg2.connect(scratch_server_dsn, connect_timeout=10)
    admin.autocommit = True
    created = False
    try:
        with admin.cursor() as acur:
            acur.execute(f'CREATE DATABASE "{verify_db}"')
            created = True

        # Assert the new DB is empty before restoring.
        with pg_connect(verify_dsn, read_only=True) as (_c, cur):
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
            pre_count = int(cur.fetchone()["c"])
        if pre_count != 0:
            raise BackupVerifyError(
                "REFUSE_VERIFY",
                f"ephemeral verify DB not empty pre-restore ({pre_count} tables) — "
                f"refusing to compare against a dirty target.",
            )

        # Restore via psql (reads the plain-SQL dump on stdin).
        with open(out_sql, "r", encoding="utf-8", errors="replace") as fh:
            restore = subprocess.run(
                ["psql", verify_dsn, "-v", "ON_ERROR_STOP=1"],
                stdin=fh,
                capture_output=True,
                text=True,
                timeout=600,
            )
        if restore.returncode != 0:
            raise BackupVerifyError(
                "REFUSE_VERIFY",
                f"psql restore failed (rc={restore.returncode}): "
                f"{restore.stderr.strip()[:500]}",
            )

        # Count-compare per table (full WIPE+KEEP set) ephemeral-vs-prod.
        all_tables = sorted(set(WIPE_TABLES) | set(KEEP_TABLES))
        prod_all = dict(prod_wipe_counts)
        for t in all_tables:
            if t not in prod_all:
                prod_all[t] = _table_counts(dsn, [t])[t]
        eph_counts = _table_counts(verify_dsn, all_tables)

        divergences: list[str] = []
        for t in all_tables:
            p = prod_all.get(t, -1)
            e = eph_counts.get(t, -1)
            if p == e:
                continue
            if t in _HIGH_CHURN_KEEP and p > 0:
                if abs(p - e) <= max(1, int(p * _HIGH_CHURN_TOLERANCE)):
                    continue
            divergences.append(f"{t}: prod={p} ephemeral={e}")
        if divergences:
            raise BackupVerifyError(
                "REFUSE_VERIFY",
                f"restore count divergence: {divergences}",
            )

        # Total table count parity.
        with pg_connect(verify_dsn, read_only=True) as (_c, cur):
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
            eph_total = int(cur.fetchone()["c"])
        if eph_total != len(registry.TABLES):
            raise BackupVerifyError(
                "REFUSE_VERIFY",
                f"restored table count {eph_total} != registry {len(registry.TABLES)}",
            )

        return {
            "result": "RESTORE_VERIFIED",
            "verify_db": verify_db,
            "restored_table_count": eph_total,
        }
    finally:
        # Force-disconnect any sessions, then DROP. Always runs.
        try:
            if created:
                with admin.cursor() as acur:
                    acur.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (verify_db,),
                    )
                    acur.execute(f'DROP DATABASE IF EXISTS "{verify_db}"')
        except psycopg2.Error as exc:
            logger.warning("ephemeral DB drop failed for %s: %s", verify_db, exc)
        finally:
            admin.close()


def run_backup_and_verify(
    dsn: str,
    scratch_server_dsn: str,
    out_dir: Path | str,
) -> dict[str, Any]:
    """Full backup + verify-restore pipeline. Returns a verdict dict.

    Raises BackupVerifyError (with .code in REFUSE_BACKUP / REFUSE_SCHEMA_DRIFT /
    REFUSE_VERIFY) on any failure → the orchestrator REFUSEs the TRUNCATE.
    """
    out = Path(out_dir)
    out_sql = out / "prod.sql"

    prod_wipe_counts = _table_counts(dsn, sorted(WIPE_TABLES))
    empty_state = all(c <= 0 for c in prod_wipe_counts.values())

    _pg_dump_to_file(out_sql)
    structure = _verify_dump_structure(out_sql)
    restore = _restore_and_compare(dsn, scratch_server_dsn, out_sql, prod_wipe_counts)

    verdict: dict[str, Any] = {
        "result": "BACKUP_VERIFIED",
        "dump_path": str(out_sql),
        "backed_up_at_et": datetime.now(_ET).isoformat(),
        "per_wipe_table_counts": prod_wipe_counts,
        **structure,
        # restore details merged under a sub-key + a flattened restored count, so
        # restore's own "result" (RESTORE_VERIFIED) never clobbers the top-level
        # "result" (BACKUP_VERIFIED).
        "restore_verdict": restore["result"],
        "restored_table_count": restore["restored_table_count"],
        "verify_db": restore["verify_db"],
    }
    if empty_state:
        verdict["empty_state_tag"] = "BACKUP_OF_EMPTY_STATE"
    return verdict

"""W21 capstone (#95) — destructive prod clean-slate-wipe script.

A single audited, idempotent, DRY-RUN-BY-DEFAULT, ProdGuard-gated, backup-first
destructive script that resets the Arcis platform to a clean-slate state against
PROD PG so it restarts as a proven-sound stable release.

What it does (auto): reconciles the live schema against the registry, backs up
prod PG + verify-restores into a FRESH EPHEMERAL scratch DB (created+dropped on
the test server, NOT the shared test DB), single-transaction TRUNCATEs the
trade/learning table set (preserving market-data tables), retires (archives) the
legacy SQLite residue, and emits a structured audit trail + forensic markers.

What it does NOT do (emits operator runbook instead): edit prod YAML, pull the
Ollama base tag, flatten the Alpaca broker, or execute the wipe without --confirm.

Safety contract (spec §5):
  - DRY-RUN BY DEFAULT: @safe_op(mutates=True) returns a DryRunResult unless
    confirm=True; without --confirm execution stops after the preview.
  - PROD-GUARD: @prod_guard(dsn_param='dsn') refuses a prod-signature DSN unless
    ARCIS_ALLOW_PROD_PG=1 AND confirm=True. The DSN MUST be threaded as the
    `dsn=` kwarg or the guard silently never fires (memory:
    feedback_cli_decorated_public_api).
  - NO @safety_window('market_hours') — the config key does not exist (it would
    ValueError at call time, _safety.py:268-271). The hard preconditions
    (watch-loop NSSM-stopped + re-checked, live-schema+FK reconciliation,
    broker-flat) are the gates instead (spec §5.3).
  - TRUNCATE not DROP (avoids the #92/#129 'must be owner' crash-loop).
  - --emergency is a reserved, INERT flag (no @safety_window to bypass).

Connection discipline: pg_connect(dsn=...) with the literal prod DSN from
.env DATABASE_URL. NEVER connect_db (its cutover-gate could route to SQLite).

Runbook: docs/runbooks/clean_slate_wipe.md
Tests: tests/scripts/test_clean_slate_wipe.py, test_clean_slate_interrupted.py,
       test_clean_slate_e2e.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg2

from scripts._clean_slate import backup as backup_mod
from scripts._clean_slate import config_verify as config_verify_mod
from scripts._clean_slate import live_schema as live_schema_mod
from scripts._clean_slate import sqlite_retire as sqlite_retire_mod
from scripts._clean_slate._errors import BackupVerifyError, CleanSlateAbort
from scripts._clean_slate.classification import (
    KEEP_TABLES,
    WIPE_TABLES,
    assert_partition_complete,
)
from src.tools._db import pg_connect
from src.tools._execution_log import write_event
from src.tools._safety import prod_guard, safe_op

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# Reused verbatim from the archive_bootcamp precedent (PG/SQLite-agnostic).
# NB: _check_open_shadow_trades (SQLite, source_path-based) is intentionally NOT
# imported — this script is PG-only, so it uses the local _check_open_shadow_trades_safe.
from scripts.archive_bootcamp_2026_04_24 import (  # noqa: E402
    _check_alpaca_positions,
    _check_watch_loop_running,
)

_DEFAULT_SCRATCH_SERVER_DSN = "postgresql://test:test@127.0.0.1:5434/postgres"
_DEFAULT_OUT_DIR = Path("data/backups/clean_slate")

_BANNER = """
================================================================================
CLEAN-SLATE WIPE — {verdict}
  Server   : {server}
  Verdict  : {verdict}
  Manifest : {manifest}

OPERATOR FOLLOW-UP (the script does NOT do these — see docs/runbooks/clean_slate_wipe.md):
  1. config/settings.local.yaml (utf-8, MANUAL):
       - set  llm.model               -> base Ollama tag
       - set  live_trading.post_bootcamp -> false
       - set  risk.starting_capital      -> 100000  (PAPER)
       - DO NOT touch live_trading.starting_capital = 100 (LIVE account)
  2. Ollama (OS): ensure the base tag is the loaded model.
  3. Re-run:  clean_slate_wipe.py --verify-config   (flips POST_VERIFY_CONFIG_PENDING -> PASSED)
  4. Restart the watch loop AND force-regenerate the stale audit_reports verdict
     (two-layer staleness — the governor trusts the last verdict ~36h).

NOTES:
  - A DRY RUN still READS and DUMPS prod (reconcile + pg_dump + preview run before
    the confirm/guard short-circuit). This is read-only / off-box and reviewed.
  - --emergency does NOTHING here: the wipe still requires --confirm AND
    ARCIS_ALLOW_PROD_PG=1 and all hard gates (no @safety_window in the stack).
================================================================================
"""


# ── Phase-9 TRUNCATE core (no decorators) ───────────────────────────────────


def _capture_counts(dsn: str, tables: list[str]) -> dict[str, int]:
    """Per-table COUNT(*) (read-only). A table absent from the DB maps to -1 so a
    missing table is visible rather than silently 0."""
    counts: dict[str, int] = {}
    with pg_connect(dsn, read_only=True) as (conn, cur):
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) AS c FROM "{t}"')
                counts[t] = int(cur.fetchone()["c"])
            except psycopg2.Error:
                conn.rollback()
                counts[t] = -1
    return counts


def _truncate_wipe(dsn: str, wipe_tables: frozenset[str] | set[str]) -> dict[str, Any]:
    """Single-transaction TRUNCATE <sorted wipe> RESTART IDENTITY CASCADE.

    Uses pg_connect(dsn, isolation_level='SERIALIZABLE'); the helper commits on
    clean exit and rolls back on any exception (_db.py:66-71), so a failure
    commits nothing. Returns {before, after, deltas, statement}.
    """
    sorted_wipe = sorted(wipe_tables)
    before = _capture_counts(dsn, sorted_wipe)
    quoted = ", ".join(f'"{t}"' for t in sorted_wipe)
    stmt = f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"
    with pg_connect(dsn, isolation_level="SERIALIZABLE") as (_conn, cur):
        cur.execute(stmt)
    after = _capture_counts(dsn, sorted_wipe)
    deltas = {t: (before.get(t, 0), after.get(t, 0)) for t in sorted_wipe}
    return {"before": before, "after": after, "deltas": deltas, "statement": stmt}


def _post_verify_db(dsn: str, keep_baseline: dict[str, int]) -> dict[str, Any]:
    """Assert WIPE all 0, KEEP unchanged vs baseline, model_versions empty.

    Returns {result, failures}. result is POST_VERIFY_PASSED / POST_VERIFY_FAILED.
    """
    failures: list[str] = []
    wipe_counts = _capture_counts(dsn, sorted(WIPE_TABLES))
    for t, c in wipe_counts.items():
        if c > 0:
            failures.append(f"WIPE table {t} not empty: {c} rows")
    keep_counts = _capture_counts(dsn, sorted(KEEP_TABLES))
    for t, base in keep_baseline.items():
        now = keep_counts.get(t, -1)
        if now != base:
            failures.append(f"KEEP table {t} changed: baseline={base} now={now}")
    if wipe_counts.get("model_versions", 0) > 0:
        failures.append("model_versions not empty after wipe")
    return {
        "result": "POST_VERIFY_FAILED" if failures else "POST_VERIFY_PASSED",
        "failures": failures,
        "wipe_counts": wipe_counts,
        "keep_counts": keep_counts,
    }


def _write_fsync_marker(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write + fsync a forensic marker (file + dir)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    # fsync the directory entry so the rename is durable.
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _write_manifest_atomic(path: Path, manifest: dict[str, Any]) -> None:
    """Atomic manifest write (temp + os.replace), archive_bootcamp pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True, default=str)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _server_identity(dsn: str) -> dict[str, Any]:
    """Read current_database() + inet_server_port() (read-only DSN sanity)."""
    with pg_connect(dsn, read_only=True) as (_conn, cur):
        cur.execute("SELECT current_database() AS db, inet_server_port() AS port")
        row = cur.fetchone()
        return {"database": row["db"], "port": row["port"]}


def _resolve_run_dir(out_dir: Path | str | None, run_ts: str) -> Path:
    out_base = Path(out_dir) if out_dir is not None else _DEFAULT_OUT_DIR
    return out_base / run_ts


def _preflight_and_preview(
    *,
    dsn: str,
    scratch_server_dsn: str,
    i_have_flattened_broker: bool,
    run_dir: Path,
    manifest: dict[str, Any],
    do_backup: bool,
) -> dict[str, Any]:
    """Phases 0-2 (read-path; runs on BOTH dry-run and confirmed paths).

    Reconciles the live schema, runs the broker/watch-loop hard gates, the
    already-clean short-circuit, the backup+verify (read-only dump), and prints
    the preview. Returns a context dict with wipe_counts/keep_baseline and an
    `already_clean` flag. Mutates `manifest` in place with all read-path verdicts.

    This is what makes a DRY RUN still connect to + dump prod (spec §2.2): it runs
    inside the @safe_op `describe` callable on the dry path AND at the head of the
    confirmed path. It performs NO irreversible mutation.
    """
    # ── PHASE 0 — preflight + reconcile + already-clean ──
    trip = _check_watch_loop_running()
    if trip is not None:
        raise CleanSlateAbort("ABORT_WATCHLOOP", f"watch loop appears to be running: {trip}")
    manifest["server"] = _server_identity(dsn)
    assert_partition_complete()
    manifest["live_schema"] = live_schema_mod.reconcile_live_schema(dsn)
    manifest["live_fk_edges"] = live_schema_mod.reconcile_live_fk_edges(dsn)

    open_positions = _check_alpaca_positions()
    if open_positions:
        if not i_have_flattened_broker:
            raise CleanSlateAbort(
                "ABORT_BROKER_NOT_FLAT",
                f"open broker positions {open_positions} would become PERMANENT "
                f"orphans (the reconciler's backfill source is the very history "
                f"this wipe destroys) and defeat live-IB equity reset. Flatten the "
                f"broker, then pass --i-have-flattened-broker.",
            )
        manifest["warnings"].append(
            f"BROKER_NOT_FLAT_OVERRIDE: proceeding with open positions {open_positions} "
            f"under --i-have-flattened-broker attestation"
        )
    manifest["broker_positions_open"] = open_positions
    manifest["open_shadow_trades"] = _check_open_shadow_trades_safe(dsn)

    wipe_counts = _capture_counts(dsn, sorted(WIPE_TABLES))
    manifest["wipe_counts_phase0"] = wipe_counts
    already_clean = all(c <= 0 for c in wipe_counts.values())
    if already_clean:
        manifest["already_clean"] = True
        return {"wipe_counts": wipe_counts, "keep_baseline": {}, "already_clean": True}

    keep_baseline = _capture_counts(dsn, sorted(KEEP_TABLES))
    manifest["keep_counts_phase0"] = keep_baseline

    # ── PHASE 1 — backup + verify into a FRESH EPHEMERAL scratch DB ──
    if do_backup:
        manifest["backup"] = backup_mod.run_backup_and_verify(dsn, scratch_server_dsn, run_dir)

    # ── PHASE 2 — preview (always printed) ──
    _print_preview(dsn, wipe_counts, keep_baseline, manifest)
    return {"wipe_counts": wipe_counts, "keep_baseline": keep_baseline, "already_clean": False}


def _describe(kwargs: dict[str, Any]) -> str:
    """@safe_op dry-run description — RUNS Phases 0-2 (reconcile + dump + preview).

    On a dry run @safe_op calls describe() WITHOUT calling the wrapped function
    (_safety.py:121), so this is where the spec's "a dry run still reads + dumps
    prod" read-path lives. It performs no mutation. A read-path abort/refuse
    (CleanSlateAbort/BackupVerifyError) propagates out of the dry run, which is
    correct (a dry run that can't even reconcile/back up should surface that).
    """
    dsn = kwargs.get("dsn", "")
    run_ts = datetime.now(_ET).strftime("%Y%m%dT%H%M%S")
    run_dir = _resolve_run_dir(kwargs.get("out_dir"), run_ts)
    manifest: dict[str, Any] = {"warnings": [], "dry_run_preview": True}
    ctx = _preflight_and_preview(
        dsn=dsn,
        scratch_server_dsn=kwargs.get("scratch_server_dsn", _DEFAULT_SCRATCH_SERVER_DSN),
        i_have_flattened_broker=kwargs.get("i_have_flattened_broker", False),
        run_dir=run_dir,
        manifest=manifest,
        do_backup=True,
    )
    if ctx["already_clean"]:
        return "Clean-slate wipe DRY-RUN: platform is ALREADY CLEAN (all WIPE tables empty) — no-op."
    return (
        f"Clean-slate wipe DRY-RUN: reconciled live schema, backed up + "
        f"verify-restored prod (read-only), previewed TRUNCATE of "
        f"{len(WIPE_TABLES)} WIPE tables + preservation of {len(KEEP_TABLES)} "
        f"KEEP tables. Re-run with --confirm AND ARCIS_ALLOW_PROD_PG=1 to execute."
    )


# ── Phase orchestration (internal — NOT a public bypass) ─────────────────────


def _run_clean_slate(
    *,
    dsn: str,
    scratch_server_dsn: str,
    confirm: bool = False,
    i_have_flattened_broker: bool = False,
    i_have_stopped_nssm: bool = False,
    verify_config: bool = False,
    skip_sqlite: bool = False,
    emergency: bool = False,  # reserved/inert (no @safety_window to bypass)
    out_dir: Path | str | None = None,
    config_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
    sqlite_archive_dir: Path | str | None = None,
    base_tag: str | None = None,
    log_path: Path | str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Sequence Phase 0 -> 7 (spec §4). Returns the manifest dict.

    Reached ONLY when @safe_op confirmed confirm=True (it short-circuits to a
    DryRunResult otherwise) and @prod_guard passed. Injection seams (for tests):
    out_dir, config_path, sqlite_path, sqlite_archive_dir, base_tag, log_path,
    session_id. This is the post-decorator body — it never relaxes a gate.
    """
    started = datetime.now(_ET)
    run_ts = started.strftime("%Y%m%dT%H%M%S")
    run_dir = _resolve_run_dir(out_dir, run_ts)
    manifest: dict[str, Any] = {
        "started_at_et": started.isoformat(),
        "run_dir": str(run_dir),
        "confirm": confirm,
        "flags": {
            "i_have_flattened_broker": i_have_flattened_broker,
            "i_have_stopped_nssm": i_have_stopped_nssm,
            "verify_config": verify_config,
            "skip_sqlite": skip_sqlite,
            "emergency": emergency,
        },
        "warnings": [],
    }

    # ── PHASES 0-2 (read-path; same code the dry run exercises) ──
    ctx = _preflight_and_preview(
        dsn=dsn,
        scratch_server_dsn=scratch_server_dsn,
        i_have_flattened_broker=i_have_flattened_broker,
        run_dir=run_dir,
        manifest=manifest,
        do_backup=True,
    )
    if ctx["already_clean"]:
        # Already a clean slate — short-circuit WITHOUT a fresh (empty-state) backup.
        manifest["result"] = "ALREADY_CLEAN"
        manifest["completed_at_et"] = datetime.now(_ET).isoformat()
        _finalize(manifest, run_dir, log_path, session_id, dsn)
        return manifest
    keep_baseline = ctx["keep_baseline"]

    # ── PHASE 3 — TRUNCATE (watch-loop re-checked at the boundary) ──
    _phase3_watchloop_recheck(i_have_stopped_nssm)
    trunc = _truncate_wipe(dsn, WIPE_TABLES)
    manifest["truncate"] = trunc

    # 3.2 forensic WIPE_COMMITTED marker (fsync'd) immediately after commit.
    _write_fsync_marker(
        run_dir / "WIPE_COMMITTED.marker",
        {
            "committed_at_et": datetime.now(_ET).isoformat(),
            "server": manifest["server"],
            "deltas": trunc["deltas"],
        },
    )

    # ── PHASE 4 — model reset (DB) + config instructions (emit) ──
    model_versions_after = trunc["after"].get("model_versions", 0)
    manifest["model_reset"] = {
        "model_versions_after": model_versions_after,
        "l1_db_reset": model_versions_after == 0,
        "l2_l3_config": "EMITTED (operator must set llm.model -> base tag, "
        "post_bootcamp=false, starting_capital=100000; DO NOT touch "
        "live_trading.starting_capital=100)",
    }

    # ── PHASE 5 — SQLite retire (archive-fsync-then-empty) ──
    if skip_sqlite:
        manifest["sqlite_retire"] = {"result": "SKIPPED"}
    else:
        src = Path(sqlite_path) if sqlite_path is not None else _default_sqlite_path()
        arc_base = (
            Path(sqlite_archive_dir) if sqlite_archive_dir is not None
            else Path("data/archive/clean_slate")
        )
        manifest["sqlite_retire"] = sqlite_retire_mod.archive_and_empty_sqlite(
            src, arc_base / run_ts
        )

    # ── PHASE 6 — post-verify (DB) + optional config-verify ──
    manifest["post_verify_db"] = _post_verify_db(dsn, keep_baseline)
    cfg_path = (
        Path(config_path) if config_path is not None
        else Path("config/settings.local.yaml")
    )
    if verify_config:
        manifest["post_verify_config"] = config_verify_mod.verify_post_reset_config(
            cfg_path, base_tag=base_tag
        )
    else:
        manifest["post_verify_config"] = {"result": "POST_VERIFY_CONFIG_PENDING"}

    # ── PHASE 7 — audit + manifest + banner ──
    db_ok = manifest["post_verify_db"]["result"] == "POST_VERIFY_PASSED"
    manifest["result"] = "WIPE_COMPLETE" if db_ok else "POST_VERIFY_FAILED"
    manifest["completed_at_et"] = datetime.now(_ET).isoformat()
    _finalize(manifest, run_dir, log_path, session_id, dsn)
    return manifest


def _check_open_shadow_trades_safe(dsn: str) -> int:
    """Advisory open-shadow-trades count from live PG (best-effort, WARN-only)."""
    try:
        with pg_connect(dsn, read_only=True) as (_conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS c FROM shadow_trades "
                "WHERE status IN ('open', 'exit_pending', 'submission_uncertain')"
            )
            return int(cur.fetchone()["c"])
    except psycopg2.Error:
        return -1


def _phase3_watchloop_recheck(i_have_stopped_nssm: bool) -> None:
    """Re-check the watch loop immediately before the TRUNCATE transaction (MAJOR-2a).

    The watch loop is NSSM-managed + auto-restarts and the backup window is
    minutes, so a Phase-0-only check is point-in-time stale. Abort if running.
    Additionally require NSSM SERVICE_STOPPED evidence; if nssm is unavailable the
    precondition is UNVERIFIED → abort unless --i-have-stopped-nssm attests.
    """
    trip = _check_watch_loop_running()
    if trip is not None:
        raise CleanSlateAbort(
            "ABORT_WATCHLOOP_RECHECK",
            f"watch loop running at the TRUNCATE boundary: {trip} (nothing committed)",
        )
    if not _nssm_confirms_stopped() and not i_have_stopped_nssm:
        raise CleanSlateAbort(
            "ABORT_WATCHLOOP_UNVERIFIED",
            "could not verify NSSM SERVICE_STOPPED (nssm unavailable on PATH) and "
            "--i-have-stopped-nssm was not passed. Run `nssm stop ArcisWatchLoop` "
            "(verify SERVICE_STOPPED) or attest with --i-have-stopped-nssm.",
        )


def _nssm_confirms_stopped() -> bool:
    """True iff `nssm status ArcisWatchLoop` contains SERVICE_STOPPED. Any failure
    (nssm absent, error) → False (UNVERIFIED)."""
    import subprocess

    try:
        result = subprocess.run(
            ["nssm", "status", "ArcisWatchLoop"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False
    return "SERVICE_STOPPED" in (result.stdout or "")


def _default_sqlite_path() -> Path:
    """Resolve the canonical SQLite path from ARCIS_DB_PATH / src.config.DB_PATH."""
    env = os.environ.get("ARCIS_DB_PATH")
    if env:
        return Path(env)
    try:
        from src.config import DB_PATH
        return Path(DB_PATH)
    except Exception:
        return Path("C:/arcis/data/ai_research_desk.sqlite3")


def _print_preview(
    dsn: str,
    wipe_counts: dict[str, int],
    keep_counts: dict[str, int],
    manifest: dict[str, Any],
) -> None:
    """Phase-2 read-only preview (always printed)."""
    print("=" * 80)
    print(f"CLEAN-SLATE WIPE — DRY-RUN PREVIEW  (server={manifest.get('server')})")
    print("=" * 80)
    print(f"WIPE ({len(WIPE_TABLES)} tables) — current live row counts:")
    for t in sorted(WIPE_TABLES):
        print(f"  - {t:40s} {wipe_counts.get(t, 0):>10d}  -> 0")
    print(f"KEEP ({len(KEEP_TABLES)} tables) — preserved (current counts):")
    for t in sorted(KEEP_TABLES):
        print(f"  + {t:40s} {keep_counts.get(t, 0):>10d}  (unchanged)")
    print(f"backup        : {manifest.get('backup', {}).get('dump_path')}")
    print(f"live-schema   : {manifest.get('live_schema', {}).get('result')}")
    print(f"live-fk       : {manifest.get('live_fk_edges', {}).get('result')}")
    print(f"broker open   : {manifest.get('broker_positions_open')}")
    print(f"open shadow   : {manifest.get('open_shadow_trades')}")
    print("NOTE: this dry run already CONNECTED to and DUMPED prod (read-path).")
    print("=" * 80)


def _finalize(
    manifest: dict[str, Any],
    run_dir: Path,
    log_path: Path | str | None,
    session_id: str | None,
    dsn: str,
) -> None:
    """Phase-7 finalize: write_event + atomic manifest + banner."""
    manifest_path = run_dir / "manifest.json"
    _write_manifest_atomic(manifest_path, manifest)
    write_event(
        log_path=Path(log_path) if log_path is not None else None,
        tool_name="clean_slate_wipe",
        params={"dsn": dsn, "result": manifest.get("result")},
        result="success",
        duration_ms=0,
        session_id=session_id,
    )
    print(_BANNER.format(
        verdict=manifest.get("result"),
        server=manifest.get("server"),
        manifest=manifest_path,
    ))


# ── Decorated public entry point (the ONLY thing the CLI calls) ──────────────


def _make_entry_point(log_path: Path | str | None = None):
    """Build the decorated clean_slate_wipe with an optional log_path override
    (for tests). The default entry point below uses no override."""

    @safe_op(name="clean_slate_wipe", mutates=True, describe=_describe, log_path=log_path)
    @prod_guard(dsn_param="dsn", log_path=log_path)
    def clean_slate_wipe(
        *,
        dsn: str,
        scratch_server_dsn: str = _DEFAULT_SCRATCH_SERVER_DSN,
        confirm: bool = False,
        i_have_flattened_broker: bool = False,
        i_have_stopped_nssm: bool = False,
        verify_config: bool = False,
        skip_sqlite: bool = False,
        emergency: bool = False,
        out_dir: Path | str | None = None,
        config_path: Path | str | None = None,
        sqlite_path: Path | str | None = None,
        sqlite_archive_dir: Path | str | None = None,
        base_tag: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return _run_clean_slate(
            dsn=dsn,
            scratch_server_dsn=scratch_server_dsn,
            confirm=confirm,
            i_have_flattened_broker=i_have_flattened_broker,
            i_have_stopped_nssm=i_have_stopped_nssm,
            verify_config=verify_config,
            skip_sqlite=skip_sqlite,
            emergency=emergency,
            out_dir=out_dir,
            config_path=config_path,
            sqlite_path=sqlite_path,
            sqlite_archive_dir=sqlite_archive_dir,
            base_tag=base_tag,
            log_path=log_path,
            session_id=session_id,
        )

    return clean_slate_wipe


# The module-level decorated entry point. CLI __main__ calls THIS (never
# _run_clean_slate). DSN MUST be passed as the dsn= kwarg (prod_guard footgun).
clean_slate_wipe = _make_entry_point()


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clean_slate_wipe",
        description="W21 capstone (#95): dry-run-by-default destructive prod "
        "clean-slate wipe. Requires --confirm AND ARCIS_ALLOW_PROD_PG=1 for prod.",
    )
    p.add_argument("--confirm", action="store_true",
                   help="Execute the wipe (default: dry-run preview only).")
    p.add_argument("--dsn", default=None,
                   help="Prod PG DSN (default: .env DATABASE_URL via dotenv).")
    p.add_argument("--scratch-server-dsn", default=_DEFAULT_SCRATCH_SERVER_DSN,
                   help="Maintenance DSN on the test server for the ephemeral "
                        "verify DB (default: the 5434 /postgres maintenance DB — "
                        "NOT the shared halcyon test DB).")
    p.add_argument("--out-dir", default=None,
                   help=f"Backup/manifest output base (default: {_DEFAULT_OUT_DIR}).")
    p.add_argument("--skip-sqlite", action="store_true",
                   help="Skip the SQLite retire phase.")
    p.add_argument("--i-have-flattened-broker", action="store_true",
                   help="Attest the broker is flat (downgrades open-positions "
                        "ABORT to a recorded WARN).")
    p.add_argument("--i-have-stopped-nssm", action="store_true",
                   help="Attest `nssm stop ArcisWatchLoop` was run (when nssm is "
                        "unavailable on PATH to self-verify).")
    p.add_argument("--verify-config", action="store_true",
                   help="Run the config/Ollama post-reset assertion (run AFTER "
                        "completing the manual L2/L3 config steps).")
    p.add_argument("--base-tag", default=None,
                   help="Expected base Ollama tag for the --verify-config check.")
    p.add_argument("--emergency", action="store_true",
                   help="RESERVED / INERT: does nothing (no @safety_window in the "
                        "stack). The wipe still requires --confirm + "
                        "ARCIS_ALLOW_PROD_PG=1 and all hard gates.")
    return p


def main(argv: list[str] | None = None) -> int:
    """Entrypoint. Returns an exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = _build_parser().parse_args(argv)

    # Source the literal prod DSN ONCE, here in the CLI layer (dotenv), and thread
    # it down as dsn=. NEVER read DATABASE_URL elsewhere.
    dsn = args.dsn
    if dsn is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
        except Exception:
            pass
        dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        print("ERROR: no DSN (pass --dsn or set DATABASE_URL in .env).", file=sys.stderr)
        return 2

    try:
        result = clean_slate_wipe(
            dsn=dsn,
            scratch_server_dsn=args.scratch_server_dsn,
            confirm=args.confirm,
            i_have_flattened_broker=args.i_have_flattened_broker,
            i_have_stopped_nssm=args.i_have_stopped_nssm,
            verify_config=args.verify_config,
            skip_sqlite=args.skip_sqlite,
            emergency=args.emergency,
            out_dir=args.out_dir,
            base_tag=args.base_tag,
        )
    except (CleanSlateAbort, BackupVerifyError) as exc:
        print(f"ABORT/REFUSE: {exc}", file=sys.stderr)
        return 1

    # Dry-run path returns a DryRunResult (printed); real run returns the manifest.
    from src.tools._safety import DryRunResult
    if isinstance(result, DryRunResult):
        print(result)
        return 0
    verdict = result.get("result")
    return 0 if verdict in ("WIPE_COMPLETE", "ALREADY_CLEAN") else 3


if __name__ == "__main__":
    sys.exit(main())

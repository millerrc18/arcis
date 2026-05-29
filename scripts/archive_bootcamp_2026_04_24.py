"""Operator-executed SQLite archive script for the Friday 2026-04-24 bootcamp cutover.

Archives the current production SQLite DB via `VACUUM INTO`, writes a manifest
recording SHA-256 + row-counts + preserved prod-only columns, creates a schema-
only "fresh" successor DB, and emits operator instructions for the manual
cutover step.

This script does NOT:
  - Swap `ARCIS_DB_PATH` or move any real files
  - Start or stop the watch loop (ArcisWatchLoop NSSM service)
  - Touch Postgres or Render-sync state

Exit codes:
  0 - success
  1 - preflight failure (any of: target exists, source missing, watch loop
      running, nssm status != SERVICE_STOPPED, process-list scan dirty)
  2 - archive verification failure (row-count mismatch or SHA mismatch)
  3 - fresh DB creation failure (schema or table-count mismatch)
  4 - manifest write failure

CLI:
  python scripts/archive_bootcamp_2026_04_24.py --dry-run        # default: print plan
  python scripts/archive_bootcamp_2026_04_24.py --apply          # execute archive + fresh anchor
  python scripts/archive_bootcamp_2026_04_24.py --archive-only   # skip fresh DB anchor
  python scripts/archive_bootcamp_2026_04_24.py --fresh-only <path>  # skip archive
  python scripts/archive_bootcamp_2026_04_24.py --verify <path>  # re-verify an archive

References:
  docs/sprints/friday_archive_sprint_evaluation.md (Pass 1 §§1, 3, 4, 6)
  docs/sprints/friday_archive_sprint_research.md (Pass 2 §2 — prod-only columns)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Pass 2 §2 — prod-only columns preserved in the archive DB but LOST in the
# fresh DB. Operator decision 2: enumerate in the manifest as a breadcrumb.
# 17 columns across 6 tables (corrected in commit 3501dd8).
PROD_ONLY_COLUMNS_PRESERVED: dict[str, list[str]] = {
    "api_costs": ["estimated_cost"],
    "canary_evaluations": ["id", "perplexity", "verdict"],
    "quality_drift_metrics": [
        "avg_score",
        "id",
        "metric_date",
        "pass_rate",
        "score_std",
        "template_fallback_rate",
    ],
    "recommendations": ["setup_confidence"],
    "setup_signals": ["features_json", "scan_date"],
    "training_examples": [
        "model_version",
        "outcome",
        "regime_label",
        "trade_date",
    ],
}

# Tables whose row-counts we compare source↔archive as an integrity check.
# Kept small and trading-critical; full-schema parity is implicit via
# `VACUUM INTO` + SHA-256.
VERIFIED_TABLES: tuple[str, ...] = (
    "shadow_trades",
    "training_examples",
    "bracket_health",
)

# Staleness threshold for render sync — 3× typical interval (sync thread
# interval is 300s, so 900s = 15min). Warn-only.
_SYNC_STALENESS_MULTIPLIER = 3
_SYNC_INTERVAL_SECONDS = 300

ET = ZoneInfo("America/New_York")

_BANNER = """
================================================================================
ARCHIVE COMPLETE. DO NOT start the watch loop until ARCIS_DB_PATH is updated.
  1. Edit .env: set ARCIS_DB_PATH={fresh_path}
  2. Audit: nssm dump ArcisWatchLoop | findstr AppEnvironmentExtra
  3. Start : nssm start ArcisWatchLoop
See docs/archive/README.md for the full cutover checklist.

NOTE: ArcisWatchLoop is the only service — halting it transitively halts the
in-process RenderSyncThread daemon. There is no second service.
================================================================================
"""


# ── Preflight helpers ───────────────────────────────────────────────────


def _lockfile_path() -> Path:
    """Resolve the watch.lock path.

    Honors `ARCIS_DATA_DIR` env var (used by tests to redirect the probe
    at a tmp_path). Falls back to `data/watch.lock` relative to cwd — this
    matches `src.startup.is_watch_loop_running()` behavior (repo-relative).
    """
    data_dir = os.environ.get("ARCIS_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "watch.lock"
    return Path("data") / "watch.lock"


def _check_watch_loop_running() -> str | None:
    """Return a string describing the watch-loop signal that tripped, or None.

    Four independent signals AND together (any one trips => abort):
      1. data/watch.lock exists
      2. psutil finds a python process with 'watch' in its command line
      3. nssm status ArcisWatchLoop does NOT contain SERVICE_STOPPED
    """
    # 1. Lockfile.
    lockfile = _lockfile_path()
    if lockfile.exists():
        try:
            pid = lockfile.read_text(encoding="utf-8").strip()
        except OSError:
            pid = "?"
        return f"watch.lock present at {lockfile} (pid={pid})"

    # 2. Process-list scan via psutil.
    try:
        import psutil

        for proc in psutil.process_iter(attrs=("name", "cmdline")):
            try:
                info = proc.info
            except Exception:
                continue
            name = (info.get("name") or "").lower()
            cmdline = info.get("cmdline") or []
            cmd_str = " ".join(cmdline).lower() if cmdline else ""
            if "python" in name and "watch" in cmd_str:
                return f"python+watch process found: {cmd_str[:120]}"
    except ImportError:
        logger.warning("psutil not installed — skipping process-list scan")

    # 3. NSSM service status.
    try:
        result = subprocess.run(
            ["nssm", "status", "ArcisWatchLoop"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = (result.stdout or "").strip()
        if "SERVICE_STOPPED" not in stdout:
            return f"nssm status != SERVICE_STOPPED (got: {stdout!r})"
    except FileNotFoundError:
        logger.warning("nssm not on PATH — skipping NSSM status check")
    except subprocess.SubprocessError as exc:
        logger.warning("nssm invocation failed: %s — skipping", exc)

    return None


def _check_render_sync_staleness(source_path: Path) -> dict[str, Any]:
    """Return {last_synced_at, staleness_verdict} for manifest.

    Warn-only: does not abort preflight. If the cursor is FRESH
    (< 3× interval old), warn the operator that the watch loop may still be
    writing. If STALE or ABSENT, proceed without comment.
    """
    result: dict[str, Any] = {
        "last_synced_at": None,
        "staleness_verdict": "absent",
    }
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT MAX(last_synced_at) FROM sync_state"
        ).fetchone()
        last = row[0] if row else None
        if not last:
            return result
        result["last_synced_at"] = last
        # Try to parse the timestamp. If it fails, treat as stale.
        try:
            ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
            age = (now - ts).total_seconds()
            threshold = _SYNC_INTERVAL_SECONDS * _SYNC_STALENESS_MULTIPLIER
            if age < threshold:
                result["staleness_verdict"] = "fresh"
                logger.warning(
                    "Render sync cursor is FRESH (age=%.0fs < %ds) — "
                    "watch loop may still be running", age, threshold,
                )
            else:
                result["staleness_verdict"] = "stale"
        except (ValueError, TypeError):
            result["staleness_verdict"] = "unparseable"
    except sqlite3.Error as exc:
        logger.warning("render sync check failed: %s", exc)
    finally:
        if conn is not None:
            conn.close()
    return result


def _check_open_shadow_trades(source_path: Path) -> list[dict[str, Any]]:
    """Return list of open shadow trades (warn-only)."""
    rows: list[dict[str, Any]] = []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT trade_id, ticker, status FROM shadow_trades "
            "WHERE status IN ('open', 'exit_pending', 'submission_uncertain')"
        )
        for r in cursor:
            rows.append({
                "trade_id": r["trade_id"],
                "ticker": r["ticker"],
                "status": r["status"],
            })
    except sqlite3.Error as exc:
        logger.warning("open-trades check failed: %s", exc)
    finally:
        if conn is not None:
            conn.close()
    return rows


def _check_alpaca_positions() -> list[str]:
    """Return list of open Alpaca position tickers (warn-only).

    Tries to query Alpaca via the adapter. On any failure (offline, missing
    keys, etc.) returns an empty list and logs a warning — this is a
    best-effort advisory, not a gating check.
    """
    try:
        from src.shadow_trading.alpaca_adapter import AlpacaAdapter
        adapter = AlpacaAdapter()
        positions = adapter.get_open_positions() or []
        tickers: list[str] = []
        for p in positions:
            sym = getattr(p, "symbol", None) or (p.get("symbol") if isinstance(p, dict) else None)
            if sym:
                tickers.append(sym)
        return tickers
    except Exception as exc:  # broad — any failure = warn and continue
        logger.warning("Alpaca positions check skipped: %s", exc)
        return []


def preflight(
    source_path: Path,
    archive_path: Path,
    fresh_path: Path | None,
    *,
    require_fresh_nonexistent: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """Run all preflight checks. Return (ok, context_dict).

    `context_dict` carries results that downstream phases need in the
    manifest (watch_loop_process_state, render_sync_state, etc.).
    """
    ctx: dict[str, Any] = {
        "watch_loop_process_state": "SERVICE_STOPPED",
        "render_sync_state": {"last_synced_at": None, "staleness_verdict": "absent"},
        "alpaca_positions_open": [],
        "open_shadow_trades": [],
    }

    # 1. Source exists.
    if not source_path.exists():
        logger.error("PREFLIGHT FAIL: source DB missing: %s", source_path)
        return False, ctx

    # 2. Archive target dir exists (create if missing), target file does NOT exist.
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        logger.error(
            "PREFLIGHT FAIL: archive target already exists (refusing to overwrite): %s",
            archive_path,
        )
        return False, ctx

    # 3. Fresh DB path must not exist yet — BUT only if it's a DIFFERENT path
    # than the source. The script's default is fresh == source (because the
    # operator's .env swap moves ARCIS_DB_PATH to the fresh DB AFTER running
    # this script, with the old DB renamed to the archive). So "fresh == source"
    # is the expected normal case, not an error.
    if (
        fresh_path is not None
        and require_fresh_nonexistent
        and fresh_path.resolve() != source_path.resolve()
        and fresh_path.exists()
    ):
        logger.error(
            "PREFLIGHT FAIL: fresh DB target already exists: %s", fresh_path,
        )
        return False, ctx

    # 4. Watch loop NOT running (four signals — any trips = abort).
    trip = _check_watch_loop_running()
    if trip is not None:
        logger.error("PREFLIGHT FAIL: watch loop may be running — %s", trip)
        return False, ctx

    # 5. Warn-only checks.
    ctx["render_sync_state"] = _check_render_sync_staleness(source_path)
    ctx["open_shadow_trades"] = _check_open_shadow_trades(source_path)
    if ctx["open_shadow_trades"]:
        logger.warning(
            "WARN: %d open shadow trade(s) will be referenced by archive "
            "but absent from fresh DB: %s",
            len(ctx["open_shadow_trades"]),
            [t["trade_id"] for t in ctx["open_shadow_trades"]],
        )
    ctx["alpaca_positions_open"] = _check_alpaca_positions()
    if ctx["alpaca_positions_open"]:
        logger.warning(
            "WARN: %d open Alpaca position(s) — operator should confirm "
            "intent to carry across: %s",
            len(ctx["alpaca_positions_open"]),
            ctx["alpaca_positions_open"],
        )

    return True, ctx


# ── Archive phase ───────────────────────────────────────────────────────


def _row_counts(db_path: Path, tables: tuple[str, ...]) -> dict[str, int]:
    """Return {table: count} for the given tables from a read-only open.

    Explicitly closes the connection (unlike `with` context manager, which
    only commits — leaving the file handle open until GC on Windows can
    block subsequent `unlink()` or `os.replace()` calls).
    """
    counts: dict[str, int] = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for t in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                counts[t] = int(row[0]) if row else 0
            except sqlite3.Error:
                counts[t] = 0
    finally:
        conn.close()
    return counts


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 of a file in 1 MiB chunks (handles 1+ GB archives)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def archive_db(source_path: Path, archive_path: Path) -> tuple[bool, dict[str, int], str]:
    """Execute VACUUM INTO, verify row counts, compute SHA-256, write .sha256 sidecar.

    Returns (ok, row_counts_dict, sha256_hex). On any failure returns
    (False, {}, "").
    """
    # Source row-counts pre-archive.
    src_counts = _row_counts(source_path, VERIFIED_TABLES)

    # VACUUM INTO — Pass 1 §1's recommended primitive. Opens the SOURCE
    # (which must be writable briefly because VACUUM INTO pauses the source,
    # snapshot-reads, and emits a fresh file). Explicit close() is required
    # on Windows — the `with` context manager does not close the connection,
    # which would block later file operations on the source.
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(source_path))
        conn.execute(f"VACUUM INTO '{str(archive_path).replace(chr(39), chr(39)*2)}'")
    except sqlite3.Error as exc:
        logger.error("VACUUM INTO failed: %s", exc)
        if conn is not None:
            conn.close()
        return False, {}, ""
    finally:
        if conn is not None:
            conn.close()

    if not archive_path.exists():
        logger.error("VACUUM INTO completed but archive file missing: %s", archive_path)
        return False, {}, ""

    # Verify row-count parity.
    arc_counts = _row_counts(archive_path, VERIFIED_TABLES)
    for t in VERIFIED_TABLES:
        if src_counts.get(t, 0) != arc_counts.get(t, 0):
            logger.error(
                "ARCHIVE VERIFY FAIL: %s source=%d archive=%d",
                t, src_counts.get(t, 0), arc_counts.get(t, 0),
            )
            return False, {}, ""

    # SHA-256 + sidecar.
    sha = _sha256_file(archive_path)
    sha_sidecar = archive_path.with_suffix(archive_path.suffix + ".sha256")
    sha_sidecar.write_text(f"{sha}  {archive_path.name}\n", encoding="utf-8")

    return True, arc_counts, sha


# ── Manifest phase ──────────────────────────────────────────────────────


def write_manifest(
    *,
    archive_path: Path,
    source_path: Path,
    sha: str,
    row_counts: dict[str, int],
    ctx: dict[str, Any],
) -> bool:
    """Atomically write <archive_path>.manifest.json via temp + os.replace."""
    manifest = {
        "archive_path": str(archive_path.resolve()),
        "source_path": str(source_path.resolve()),
        "archive_timestamp_et": datetime.now(ET).isoformat(),
        "file_size_bytes": archive_path.stat().st_size,
        "sha256": sha,
        "row_counts": row_counts,
        "arcis_db_path_at_archive_time": os.environ.get("ARCIS_DB_PATH", ""),
        "watch_loop_process_state": ctx.get("watch_loop_process_state", "UNKNOWN"),
        "render_sync_state": ctx.get("render_sync_state", {}),
        "alpaca_positions_open": ctx.get("alpaca_positions_open", []),
        "open_shadow_trades": ctx.get("open_shadow_trades", []),
        "prod_only_columns_preserved": PROD_ONLY_COLUMNS_PRESERVED,
    }

    manifest_path = archive_path.with_suffix(".manifest.json")
    try:
        # Atomic write: temp in same dir, then os.replace.
        fd, tmp_name = tempfile.mkstemp(
            prefix=manifest_path.name + ".",
            suffix=".tmp",
            dir=str(manifest_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, sort_keys=True)
            os.replace(tmp_name, manifest_path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
    except Exception as exc:
        logger.error("Manifest write failed: %s", exc)
        return False

    return True


# ── Fresh DB anchor phase ───────────────────────────────────────────────


def create_fresh_db(
    fresh_path: Path,
    *,
    archive_ref_path: Path,
    archive_sha: str,
) -> bool:
    """Create empty SQLite at fresh_path, populate schema, verify, write anchor JSON.

    If fresh_path already exists (including the case where it equals the
    archived source — the default), the existing file is removed first so
    create_all_tables starts from a clean slate. Safe because the archive
    was already completed via VACUUM INTO before this phase runs.

    Returns True on success, False on any failure (exit code 3 upstream).
    """
    from src.schema.registry import TABLES
    from src.schema.sqlite import create_all_tables

    try:
        # Ensure parent exists.
        fresh_path.parent.mkdir(parents=True, exist_ok=True)
        # If the target exists (e.g. fresh == source by default), remove it
        # so create_all_tables populates an empty DB. The archive phase has
        # already committed a VACUUM INTO copy to archive_ref_path; removing
        # the source at this point is the intended cutover semantic.
        if fresh_path.exists():
            # Force GC so any lingering sqlite3 connection handles (e.g.
            # from fixture setup that used `with sqlite3.connect(...)`)
            # are finalized before unlink. Windows holds ERROR_SHARING_VIOLATION
            # until all handles are released.
            import gc
            gc.collect()
            # On Windows, retry briefly: the handle may not be released
            # synchronously even after GC if the OS hasn't processed it yet.
            import time
            last_exc: OSError | None = None
            for _ in range(10):
                try:
                    fresh_path.unlink()
                    last_exc = None
                    break
                except PermissionError as exc:  # WinError 32
                    last_exc = exc
                    gc.collect()
                    time.sleep(0.1)
            if last_exc is not None:
                raise last_exc
        # Create empty DB.
        sqlite3.connect(str(fresh_path)).close()
        # Populate schema from the registry (count is registry-driven).
        create_all_tables(str(fresh_path))
    except Exception as exc:
        logger.error("Fresh DB creation failed: %s", exc)
        return False

    # Verify: every registry table is present in the fresh DB and empty.
    # (A hardcoded registry-count tripwire used to live here; it fired on every
    # legitimate registry change. The dynamic all-tables-present check below is
    # the real invariant and auto-adapts as the schema evolves.)
    verify_conn: sqlite3.Connection | None = None
    try:
        verify_conn = sqlite3.connect(f"file:{fresh_path}?mode=ro", uri=True)
        existing = {
            r[0] for r in verify_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for tname in TABLES:
            if tname not in existing:
                logger.error("Fresh DB missing table: %s", tname)
                return False
            count = verify_conn.execute(
                f"SELECT COUNT(*) FROM {tname}"
            ).fetchone()[0]
            if count != 0:
                logger.error(
                    "Fresh DB table %s should be empty, has %d rows",
                    tname, count,
                )
                return False
    except Exception as exc:
        logger.error("Fresh DB verification failed: %s", exc)
        return False
    finally:
        if verify_conn is not None:
            verify_conn.close()

    # Anchor sidecar.
    anchor_path = fresh_path.parent / "ARCHIVE_ANCHOR_2026-04-24.json"
    anchor = {
        "fresh_db_path": str(fresh_path.resolve()),
        "schema_table_count": 68,
        "created_at": datetime.now(ET).isoformat(),
        "archive_ref_path": str(archive_ref_path.resolve()),
        "archive_sha": archive_sha,
    }
    try:
        anchor_path.write_text(
            json.dumps(anchor, indent=2, sort_keys=True), encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Anchor sidecar write failed: %s", exc)
        return False

    return True


# ── Verify mode ─────────────────────────────────────────────────────────


def verify_existing_archive(archive_path: Path) -> int:
    """Re-verify an existing archive against its .manifest.json sha256."""
    manifest_path = archive_path.with_suffix(".manifest.json")
    if not archive_path.exists():
        logger.error("Archive file not found: %s", archive_path)
        return 2
    if not manifest_path.exists():
        logger.error("Manifest not found: %s", manifest_path)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Manifest is not valid JSON: %s", exc)
        return 2

    recorded_sha = manifest.get("sha256", "")
    actual_sha = _sha256_file(archive_path)
    if recorded_sha != actual_sha:
        logger.error(
            "SHA-256 mismatch: manifest=%s actual=%s", recorded_sha, actual_sha,
        )
        return 2
    print(f"VERIFIED: {archive_path} sha256={actual_sha}")
    return 0


# ── CLI / entrypoint ────────────────────────────────────────────────────


def _default_source() -> str:
    """Lazy import to let tests override ARCIS_DB_PATH before import resolves."""
    from src.config import DB_PATH
    return DB_PATH


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="archive_bootcamp_2026_04_24",
        description="Archive the current SQLite DB and create a fresh successor.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="(default) Print plan, write nothing.")
    mode.add_argument("--apply", action="store_true",
                      help="Execute archive + fresh-DB anchor.")
    mode.add_argument("--archive-only", action="store_true",
                      help="Archive only; skip fresh DB anchor.")
    mode.add_argument("--fresh-only", metavar="TARGET",
                      help="Create fresh DB at TARGET; skip archiving.")
    mode.add_argument("--verify", metavar="ARCHIVE_PATH",
                      help="Re-verify an existing archive's SHA-256.")

    p.add_argument("--source", default=None,
                   help="Source DB path (default: src.config.DB_PATH).")
    p.add_argument("--archive-path", default=None,
                   help="Archive output path (default: "
                        "C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3).")
    p.add_argument("--fresh-path", default=None,
                   help="Fresh DB output path (default: same as --source).")
    return p


def _log_plan(source: Path, archive: Path, fresh: Path | None) -> None:
    print(f"[plan] source        : {source}")
    print(f"[plan] archive       : {archive}")
    print(f"[plan] manifest      : {archive.with_suffix('.manifest.json')}")
    print(f"[plan] sha sidecar   : {archive.with_suffix(archive.suffix + '.sha256')}")
    if fresh is not None:
        print(f"[plan] fresh DB      : {fresh}")
        print(f"[plan] anchor file   : {fresh.parent / 'ARCHIVE_ANCHOR_2026-04-24.json'}")
    print(f"[plan] prod-only cols : {sum(len(v) for v in PROD_ONLY_COLUMNS_PRESERVED.values())} "
          f"across {len(PROD_ONLY_COLUMNS_PRESERVED)} tables (see manifest)")


def main(argv: list[str] | None = None) -> int:
    """Entrypoint. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Verify mode — short-circuit.
    if args.verify:
        return verify_existing_archive(Path(args.verify))

    # Resolve paths.
    source_path = Path(args.source) if args.source else Path(_default_source())
    default_archive = Path(
        "C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3"
    )
    archive_path = Path(args.archive_path) if args.archive_path else default_archive

    # Fresh-only mode — no archiving, just schema init.
    if args.fresh_only:
        fresh_path = Path(args.fresh_only)
        if fresh_path.exists():
            logger.error("Fresh-only target already exists: %s", fresh_path)
            return 1
        # No archive reference in fresh-only mode.
        ok = create_fresh_db(
            fresh_path, archive_ref_path=archive_path, archive_sha="",
        )
        return 0 if ok else 3

    # For archive-only mode, no fresh DB.
    if args.archive_only:
        fresh_path: Path | None = None
    else:
        fresh_path = Path(args.fresh_path) if args.fresh_path else source_path

    # Default mode is dry-run if neither --apply nor --archive-only chosen.
    is_apply = args.apply or args.archive_only
    is_dry_run = args.dry_run or not is_apply

    print("=" * 80)
    print(f"archive_bootcamp_2026_04_24  mode={'DRY-RUN' if is_dry_run else 'APPLY'}")
    print("=" * 80)
    _log_plan(source_path, archive_path, fresh_path)

    # Preflight — runs in both dry-run and apply. In dry-run, the test
    # fixture fixes give us a clean preflight and we exit 0 without writing.
    ok, ctx = preflight(
        source_path, archive_path, fresh_path,
        require_fresh_nonexistent=(fresh_path is not None and not is_dry_run),
    )
    if not ok:
        logger.error("Preflight failed. Aborting.")
        return 1

    if is_dry_run:
        print("[dry-run] preflight OK — would proceed with archive + fresh anchor.")
        print("[dry-run] no files written.")
        return 0

    # Archive phase.
    ok, row_counts, sha = archive_db(source_path, archive_path)
    if not ok:
        logger.error("Archive phase failed. Exit 2.")
        return 2
    print(f"[archive] OK  size={archive_path.stat().st_size}  sha256={sha}")

    # Manifest phase.
    if not write_manifest(
        archive_path=archive_path,
        source_path=source_path,
        sha=sha,
        row_counts=row_counts,
        ctx=ctx,
    ):
        logger.error("Manifest phase failed. Exit 4.")
        return 4
    print(f"[manifest] OK  {archive_path.with_suffix('.manifest.json')}")

    # Fresh DB anchor phase (skip in archive-only).
    if fresh_path is not None:
        if not create_fresh_db(
            fresh_path, archive_ref_path=archive_path, archive_sha=sha,
        ):
            logger.error("Fresh DB anchor phase failed. Exit 3.")
            return 3
        print(f"[fresh-db] OK  {fresh_path}")

    # Cutover decision-point banner.
    print(_BANNER.format(fresh_path=fresh_path or "<no fresh DB created>"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Auto-fire helper for walk-forward runs (SP-WF-013).

Called by: scripts.run_backtest.main (post-persist hook), src.scheduler.watch._run_walkforward_reconciler.
Calls: subprocess.Popen, filelock.FileLock, src.utils.db.connect_db, src.evaluation.corpus.
Owns tables: none.
Config keys: WALKFORWARD_AUTOFIRE_ENABLED (env, default true).
Tests: tests/platform/test_walkforward_autofire.py.

WALKFORWARD_AUTOFIRE_ENABLED semantics: when absent or any truthy value ("true", "1", "yes"),
auto-fire is active. Set to "false" or "0" to disable globally. This mirrors the
fail-safe convention established by WALKFORWARD_GATE_ENABLED in T1 (promotion.py:286):
  os.environ.get("WALKFORWARD_GATE_ENABLED", "true").lower() in ("true", "1", "yes")
The sentinel asymmetry: GATE defaults true (safe to block), AUTOFIRE defaults true
(safe to fire). Both fail-open by design — the walkforward system is a research gate,
not a trading block; missing auto-fires are recoverable by the reconciler.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

_LOCK_DIR = Path("data")


def _emit_event(
    event_type: str,
    db_path: str,
    payload: dict | None = None,
    severity: str = "info",
) -> None:
    """Write one row to platform_events. Best-effort — never raises."""
    try:
        from src.utils.db import connect_db
        payload_json = json.dumps(payload or {}, default=str)
        with connect_db(db_path) as conn:
            conn.execute(
                "INSERT INTO platform_events "
                "(event_type, severity, payload_json, source) "
                "VALUES (?, ?, ?, ?)",
                (event_type, severity, payload_json, "walkforward_autofire"),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(
            "[AUTOFIRE] Failed to write platform_events row (%s): %s",
            event_type,
            exc,
        )


def _resolve_corpus_id_for_strategy(strategy_id: str, db_path: str) -> str | None:
    """Read strategy_registry.corpus_id (Stage 1 corpus binding). Returns None if
    no row or column is NULL. Corpus is REQUIRED per SP-WF-010; caller emits
    walkforward_auto_fire_skipped_no_corpus event when None.
    """
    try:
        from src.utils.db import connect_db
        conn = connect_db(db_path)
        try:
            row = conn.execute(
                "SELECT corpus_id FROM strategy_registry WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        corpus_id = row[0] if not hasattr(row, "keys") else row["corpus_id"]
        return corpus_id if corpus_id else None
    except Exception as exc:
        logger.warning(
            "[AUTOFIRE] _resolve_corpus_id_for_strategy failed for %s: %s",
            strategy_id,
            exc,
        )
        return None


def auto_fire_walkforward(
    strategy_id: str,
    backtest_result_id: str,
    db_path: str,
    *,
    timeout_seconds: int = 5400,
) -> None:
    """Spawn a detached subprocess invocation of `python -m scripts.backtest.run_walkforward
    --strategy-id <X> --backtest-result-id <Y> --auto-fire`.

    Pre-flight (in order):
      1. WALKFORWARD_AUTOFIRE_ENABLED env check (default true). When disabled: emit
         platform_events row event_type='walkforward_auto_fire_skipped_disabled' and return.
      2. corpus_id resolution via _resolve_corpus_id_for_strategy. When None: emit
         event_type='walkforward_auto_fire_skipped_no_corpus' and return (SP-WF-010 — corpus REQUIRED).
      3. Acquire filelock at data/walkforward-{strategy_id}.lock with timeout=0 (non-blocking).
         When locked: emit event_type='walkforward_auto_fire_skipped_locked' and return.

    Spawn: subprocess.Popen of `python -m scripts.backtest.run_walkforward ...` with
    detached process group; do NOT wait. Capture spawn-time errors only (Popen() raising
    OSError/FileNotFoundError) — emit event_type='walkforward_auto_fire_spawn_failed' with
    payload {'strategy_id', 'backtest_result_id', 'error_class', 'error_msg'} and return.

    NEVER raises. Backtest-persist failure must never come from auto-fire.
    """
    try:
        _auto_fire_inner(strategy_id, backtest_result_id, db_path, timeout_seconds)
    except Exception as exc:
        logger.exception(
            "[AUTOFIRE] Unhandled exception in auto_fire_walkforward for %s: %s",
            strategy_id,
            exc,
        )


def _preflight_check(
    strategy_id: str,
    backtest_result_id: str,
    db_path: str,
) -> str | None:
    """Run pre-flight checks 1+2. Returns corpus_id on pass, None to abort.

    Emits events and logs for each skip condition so the caller can return early.
    """
    enabled = os.environ.get("WALKFORWARD_AUTOFIRE_ENABLED", "true").lower() in (
        "true", "1", "yes"
    )
    if not enabled:
        _emit_event(
            "walkforward_auto_fire_skipped_disabled",
            db_path,
            {"strategy_id": strategy_id, "backtest_result_id": backtest_result_id},
        )
        logger.info(
            "[AUTOFIRE] Disabled via WALKFORWARD_AUTOFIRE_ENABLED — skipping %s",
            strategy_id,
        )
        return None

    corpus_id = _resolve_corpus_id_for_strategy(strategy_id, db_path)
    if corpus_id is None:
        _emit_event(
            "walkforward_auto_fire_skipped_no_corpus",
            db_path,
            {"strategy_id": strategy_id, "backtest_result_id": backtest_result_id},
            severity="warning",
        )
        logger.warning(
            "[AUTOFIRE] No corpus_id for %s — walkforward auto-fire skipped (SP-WF-010)",
            strategy_id,
        )
        return None

    return corpus_id


def _spawn_under_lock(
    strategy_id: str,
    backtest_result_id: str,
    db_path: str,
    corpus_id: str,
) -> None:
    """Acquire per-strategy filelock (non-blocking), spawn detached subprocess."""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _LOCK_DIR / f"walkforward-{strategy_id}.lock"
    lock = FileLock(str(lock_path), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        _emit_event(
            "walkforward_auto_fire_skipped_locked",
            db_path,
            {"strategy_id": strategy_id, "backtest_result_id": backtest_result_id},
        )
        logger.info("[AUTOFIRE] Lock held for %s — another run in progress, skipping", strategy_id)
        return

    try:
        cmd = [
            sys.executable, "-m", "scripts.backtest.run_walkforward",
            "--strategy-id", strategy_id,
            "--backtest-result-id", backtest_result_id,
            "--auto-fire", "--db-path", db_path,
        ]
        if corpus_id:
            cmd += ["--corpus-id", corpus_id]
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(cmd, **kwargs)
            logger.info(
                "[AUTOFIRE] Spawned walkforward for %s (backtest=%s) pid=%s",
                strategy_id, backtest_result_id, proc.pid,
            )
        except (OSError, FileNotFoundError) as exc:
            _emit_event(
                "walkforward_auto_fire_spawn_failed",
                db_path,
                {
                    "strategy_id": strategy_id,
                    "backtest_result_id": backtest_result_id,
                    "error_class": type(exc).__name__,
                    "error_msg": str(exc),
                },
                severity="error",
            )
            logger.error("[AUTOFIRE] Popen failed for %s: %s", strategy_id, exc)
    finally:
        lock.release()


def _auto_fire_inner(
    strategy_id: str,
    backtest_result_id: str,
    db_path: str,
    timeout_seconds: int,
) -> None:
    """Inner implementation — called from auto_fire_walkforward's catch-all wrapper."""
    corpus_id = _preflight_check(strategy_id, backtest_result_id, db_path)
    if corpus_id is None:
        return
    _spawn_under_lock(strategy_id, backtest_result_id, db_path, corpus_id)

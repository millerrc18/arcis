"""Nightly reconciliation pass for shadow_trades exit_reason consistency.

Called by: scheduler.overnight.run_daily_audit
Calls: src.utils.db.connect_db, json, logging, pathlib
Owns tables: none (persists to JSON file only)
Config keys: none
Tests: tests/scheduler/test_exit_reconciliation.py

Track 1.5 / B3 — checks closed trades from the last 24h against exit_reason
predicates. Anomalies are logged and persisted to data/reconciliation_log/YYYYMMDD.json.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.config import DB_PATH

logger = logging.getLogger(__name__)

_RECONCILE_LOG_DIR = Path(DB_PATH).parent / "reconciliation_log"

# 1% — anomaly threshold for the exit price exceeding stop_price on a stop_loss
# exit. Tracking distance is intentionally wider than typical broker slippage
# so that this pass surfaces real reconciliation gaps rather than ordinary
# fill noise. PR-690 review item O3.
_STOP_LOSS_SLIPPAGE_TOLERANCE = 0.01

_QUERY = """
    SELECT trade_id, ticker, exit_reason,
           actual_exit_price, stop_price, target_1, target_2,
           duration_days, timeout_days,
           actual_entry_time
    FROM shadow_trades
    WHERE status = 'closed'
      AND actual_exit_time >= datetime('now', '-24 hours')
      AND COALESCE(quarantined, 0) = 0
"""


def _computed_days(actual_entry_time: str | None) -> int:
    if not actual_entry_time:
        return 0
    try:
        entry = datetime.fromisoformat(actual_entry_time.replace("Z", "+00:00"))
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - entry
        return max(0, int(delta.total_seconds() / 86400))
    except Exception:
        return 0


def _check_trade(row: sqlite3.Row) -> bool:
    """Return True if the row is anomalous, False if clean or skipped."""
    reason = row["exit_reason"] or "unknown"
    exit_price = row["actual_exit_price"]

    if reason == "target_1":
        t1 = row["target_1"]
        if t1 is None:
            logger.warning("[RECONCILE_SKIP] trade_id=%s target_1=NULL", row["trade_id"])
            return False
        return exit_price is not None and exit_price < t1

    if reason == "target_2":
        t2 = row["target_2"]
        if t2 is None or t2 <= 0:
            logger.warning("[RECONCILE_SKIP] trade_id=%s target_2=NULL/zero", row["trade_id"])
            return False
        return exit_price is not None and exit_price < t2

    if reason == "stop_loss":
        sp = row["stop_price"]
        if sp is None or sp <= 0:
            return False
        return exit_price is not None and exit_price > sp * (1 + _STOP_LOSS_SLIPPAGE_TOLERANCE)

    if reason == "timeout":
        td = row["timeout_days"] or 15
        dd = row["duration_days"]
        if dd is None:
            dd = _computed_days(row["actual_entry_time"])
        return dd < td

    return False


def _init_by_reason_buckets() -> dict[str, dict]:
    return {
        "target_1": {"checked": 0, "anomalies": 0},
        "target_2": {"checked": 0, "anomalies": 0},
        "stop_loss": {"checked": 0, "anomalies": 0},
        "timeout":   {"checked": 0, "anomalies": 0},
        "reconciled": {"checked": 0},
        "manual":    {"checked": 0},
        "error":     {"checked": 0},
        "unknown":   {"checked": 0},
    }


def _evaluate_rows(rows, by_reason: dict[str, dict]) -> list[str]:
    """Run _check_trade on each row; mutate buckets; return flagged trade_ids."""
    flagged: list[str] = []
    for row in rows:
        reason = row["exit_reason"] or "unknown"
        bucket = by_reason.get(reason)
        if bucket is None:
            bucket = by_reason.get("unknown")
            reason = "unknown"
        if bucket is not None:
            bucket["checked"] = bucket.get("checked", 0) + 1
        if _check_trade(row):
            flagged.append(row["trade_id"])
            if "anomalies" in (bucket or {}):
                bucket["anomalies"] += 1
            logger.warning(
                "[EXIT_RECONCILE_ANOMALY] trade_id=%s ticker=%s exit_reason=%s "
                "exit_price=%s stop_price=%s target_1=%s target_2=%s",
                row["trade_id"], row["ticker"], row["exit_reason"],
                row["actual_exit_price"], row["stop_price"],
                row["target_1"], row["target_2"],
            )
    return flagged


def run_exit_reconciliation(
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Run nightly exit reconciliation pass.

    Accepts either a db_path (opens a connection) or a pre-existing conn
    (for tests using :memory:). Returns a result dict with anomaly_count
    and flagged_trade_ids plus per-reason breakdown.
    """
    from src.utils.db import connect_db

    owned = conn is None
    if owned:
        conn = connect_db(db_path or DB_PATH)
    try:
        rows = conn.execute(_QUERY).fetchall()
    finally:
        if owned:
            conn.close()

    by_reason = _init_by_reason_buckets()
    flagged = _evaluate_rows(rows, by_reason)

    result = {
        "reconciliation_date": date.today().isoformat(),
        "window_hours": 24,
        "total_closed": len(rows),
        "anomaly_count": len(flagged),
        "flagged_trade_ids": flagged,
        "by_reason": by_reason,
    }
    logger.info(
        "[RECON] anomaly_count=%d flagged=%s",
        result["anomaly_count"], result["flagged_trade_ids"],
    )
    _persist_result(result)
    return result


def _persist_result(result: dict) -> None:
    try:
        _RECONCILE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _RECONCILE_LOG_DIR / f"{result['reconciliation_date']}.json"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[RECON] Failed to persist reconciliation log: %s", exc)

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
from src.shadow_trading._status_sql import terminal_in_clause

logger = logging.getLogger(__name__)

_RECONCILE_LOG_DIR = Path(DB_PATH).parent / "reconciliation_log"

# 1% — anomaly threshold for the exit price exceeding stop_price on a stop_loss
# exit. Tracking distance is intentionally wider than typical broker slippage
# so that this pass surfaces real reconciliation gaps rather than ordinary
# fill noise. PR-690 review item O3.
_STOP_LOSS_SLIPPAGE_TOLERANCE = 0.01

# v0.36.32 (F-3): a multi-day hold (>= 1 trading day) that exits at ~entry
# price is the phantom-close signature (v0.36.28 wrote entry-fill-as-exit).
# 50 bps (0.5%) — NOT the 5 bps the W21 audit recommended: the canonical AMD
# phantom (dcd090be) drifted 21 bps (entry $439.80 → exit $440.72), so 5 bps
# would have MISSED the very bug this alarm is named for. 50 bps catches it
# with margin; genuine multi-day holds essentially never move < 0.5%. This is
# an anomaly LOG (not a halt), so modest false-positive tolerance is fine.
_PHANTOM_DRIFT_TOLERANCE = 0.005

# Exit reasons that imply a real price-based fill — the only ones for which
# a near-zero multi-day drift is anomalous. `reconciled_stale`/`unknown`/etc.
# are non-price closes and are exempt.
_PRICE_BASED_EXIT_REASONS = frozenset({"timeout", "target_1", "target_2", "stop_loss"})


def _build_query() -> tuple[str, tuple[str, ...]]:
    """Build the per-call reconcile SQL + bind params.

    Sprint 0 / Wave 1b STATUS-CONST: pre-fix this filtered on
    `status = 'closed'`, which silently dropped non-canonical terminal
    statuses (rejected, failed, exit_abandoned, needs_manual_review) and
    therefore never reconciled their exit_reason. Now uses
    terminal_in_clause() so the full TERMINAL_STATUSES vocabulary is
    covered by the 24-hour window.

    The 24-hour cutoff is computed in Python and bound as a parameter
    (instead of SQLite's datetime('now', '-24 hours')) so the query is
    engine-agnostic — Sprint 5 §J5/§J6 Phase 2.5 pattern.
    """
    frag, params = terminal_in_clause()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    sql = (
        "SELECT trade_id, ticker, exit_reason, "
        "actual_exit_price, actual_entry_price, entry_price, "
        "stop_price, target_1, target_2, "
        "duration_days, timeout_days, "
        "actual_entry_time, direction "
        "FROM shadow_trades "
        f"WHERE status IN ({frag}) "
        "AND actual_exit_time >= ? "
        "AND COALESCE(quarantined, 0) = 0"
    )
    return sql, params + (cutoff_iso,)


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


def _row_get(row: sqlite3.Row, key: str, default=None):
    """Safe accessor for sqlite3.Row that may not contain the key.

    sqlite3.Row supports __getitem__ but not .get(). Test fixtures sometimes
    omit the `direction` column entirely (older schema), so we fall back to
    the default when the key is absent.
    """
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return value if value is not None else default


def _check_long_stop_loss(
    row: sqlite3.Row, exit_price: float, sp: float, tolerance: float,
) -> bool:
    """Return True when a long stop_loss exit is anomalous.

    Anomalous: exit_price > stop_price * (1 + tolerance) — the fill
    was above the stop level (unexpected for a long stop-loss).
    """
    return exit_price > sp * (1 + tolerance)


def _check_short_stop_loss(
    row: sqlite3.Row, exit_price: float, sp: float, tolerance: float,
) -> bool:
    """Return True when a short stop_loss exit is anomalous.

    Anomalous: exit_price < stop_price * (1 - tolerance) — the fill
    was below the stop level (unexpected for a short stop-loss).
    """
    return exit_price < sp * (1 - tolerance)


def _check_direction_target(
    row: sqlite3.Row, exit_price: float, target: float,
    direction: str, reason: str,
) -> bool:
    """Return anomaly flag for target_1 / target_2 exits by direction."""
    if direction == "long":
        return exit_price < target
    if direction == "short":
        return exit_price > target
    logger.warning(
        "[EXIT_RECON_UNKNOWN_DIRECTION] trade_id=%s direction=%s reason=%s",
        row["trade_id"], direction, reason,
    )
    return False


def _is_phantom_drift_anomaly(row) -> bool:
    """v0.36.32 (F-3): detect the phantom-close signature.

    A price-based exit (timeout/target/stop) on a hold of >= 1 trading day
    where the exit price is within `_PHANTOM_DRIFT_TOLERANCE` of the entry
    price is anomalous — real market drift over a multi-day hold is
    essentially never that small. This is the natural detection point for
    the v0.36.28 phantom-close class (a position marked closed with the
    entry-order fill written as the exit price, no real SELL submitted).

    Returns False (non-anomalous) on any missing/uncomputable input —
    fail-safe, since a false negative here just means the legacy per-reason
    check still applies.
    """
    reason = _row_get(row, "exit_reason", None) or "unknown"
    if reason not in _PRICE_BASED_EXIT_REASONS:
        return False

    dd = _row_get(row, "duration_days", None)
    if dd is None:
        dd = _computed_days(_row_get(row, "actual_entry_time", None))
    if dd is None or dd < 1:
        return False

    exit_price = _row_get(row, "actual_exit_price", None)
    entry_price = _row_get(row, "actual_entry_price", None) or _row_get(row, "entry_price", None)
    try:
        exit_price = float(exit_price)
        entry_price = float(entry_price)
    except (TypeError, ValueError):
        return False
    if entry_price <= 0 or exit_price <= 0:
        return False

    drift = abs(exit_price - entry_price) / entry_price
    if drift < _PHANTOM_DRIFT_TOLERANCE:
        logger.warning(
            "[EXIT_RECON_PHANTOM_DRIFT] trade_id=%s ticker=%s reason=%s "
            "duration_days=%s entry=%.4f exit=%.4f drift=%.1fbps < %.0fbps — "
            "possible phantom close (v0.36.28 class); exit price too close to "
            "entry for a multi-day hold.",
            _row_get(row, "trade_id", "?"), _row_get(row, "ticker", "?"),
            reason, dd, entry_price, exit_price,
            drift * 10000, _PHANTOM_DRIFT_TOLERANCE * 10000,
        )
        return True
    return False


def _check_trade(row: sqlite3.Row) -> bool:
    """Return True if the row is anomalous, False if clean or skipped.

    v0.36.32 (F-3): a phantom-drift anomaly (price-based exit at ~entry price
    on a multi-day hold) is flagged regardless of the per-reason check below —
    it's the detection point for the v0.36.28 phantom-close class.

    Direction-aware (PR-690 O2): delegates stop-loss direction checks to
    _check_long_stop_loss / _check_short_stop_loss and target checks to
    _check_direction_target. Unknown directions are non-anomalous (fail-safe).
    """
    reason = row["exit_reason"] or "unknown"
    exit_price = row["actual_exit_price"]
    direction = str(_row_get(row, "direction", "long") or "long").lower()

    # v0.36.32 (F-3): phantom-close drift check runs first — a price-based
    # exit at ~entry price on a multi-day hold is anomalous regardless of
    # whether the per-reason predicate below passes.
    if _is_phantom_drift_anomaly(row):
        return True

    if reason == "target_1":
        t1 = row["target_1"]
        if t1 is None:
            logger.warning("[RECONCILE_SKIP] trade_id=%s target_1=NULL", row["trade_id"])
            return False
        if exit_price is None:
            return False
        return _check_direction_target(row, exit_price, t1, direction, reason)

    if reason == "target_2":
        t2 = row["target_2"]
        if t2 is None or t2 <= 0:
            logger.warning("[RECONCILE_SKIP] trade_id=%s target_2=NULL/zero", row["trade_id"])
            return False
        if exit_price is None:
            return False
        return _check_direction_target(row, exit_price, t2, direction, reason)

    if reason == "stop_loss":
        sp = row["stop_price"]
        if sp is None or sp <= 0 or exit_price is None:
            return False
        if direction == "long":
            return _check_long_stop_loss(row, exit_price, sp, _STOP_LOSS_SLIPPAGE_TOLERANCE)
        if direction == "short":
            return _check_short_stop_loss(row, exit_price, sp, _STOP_LOSS_SLIPPAGE_TOLERANCE)
        logger.warning(
            "[EXIT_RECON_UNKNOWN_DIRECTION] trade_id=%s direction=%s reason=%s",
            row["trade_id"], direction, reason,
        )
        return False

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
        sql, params = _build_query()
        rows = conn.execute(sql, params).fetchall()
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

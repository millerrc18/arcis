"""Platform-event Telegram notifications.

Called by: src.platform.backtest_engine, src.platform.promotion.
Calls: src.notifications.telegram.send_telegram.
Owns tables: none.
Config keys: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (transitively via
             telegram module).
Tests: tests/notifications/test_platform_events.py.

All messages prefixed '[RESEARCH]' — operator filter rule on Telegram
client distinguishes from swing trade notifications.

Deduplication for notify_backtest_complete and notify_shadow_gate_ready
uses _already_notified_recently_db (DB-backed, restart-safe via T15a).
_DEDUP_CACHE and _already_notified_recently are retained only for
notify_strategy_promoted / notify_strategy_demoted which do not need
restart-safe dedup (they are idempotent promotion events that fire once
per state transition and are intentionally not deduplicated across
restarts).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_PREFIX = "[RESEARCH]"
_DEDUP_WINDOW_HOURS = 24
_DEDUP_CACHE: dict[str, datetime] = {}


def _dedup_key(category: str, content: str) -> str:
    return hashlib.sha256(f"{category}::{content}".encode()).hexdigest()


def _already_notified_recently_db(
    event_type: str,
    dedup_key: str,
    conn=None,
    db_path: str | None = None,
) -> bool:
    """DB-backed dedup check: reads and writes notifications_dedup table.

    Returns True (already notified recently) — DB row within 24h window.
    Returns False (not notified recently) and upserts the row to record
    this send.

    Accepts an explicit ``conn`` or ``db_path`` for testing. Falls back
    to the production DB_PATH when neither is provided.

    Used directly by callers needing restart-safe dedup (T15a).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_DEDUP_WINDOW_HOURS)

    _own_conn = conn is None
    if conn is None:
        try:
            from src.config import DB_PATH
            from src.utils.db import connect_db
            conn = connect_db(db_path or DB_PATH)
        except Exception:
            logger.debug("[PLATFORM_EVENTS] dedup DB connect failed; skipping DB check")
            return False

    try:
        row = conn.execute(
            "SELECT sent_at FROM notifications_dedup WHERE event_type=? AND dedup_key=?",
            (event_type, dedup_key),
        ).fetchone()

        if row is not None:
            sent_at = row[0]
            try:
                sent_dt = datetime.fromisoformat(sent_at)
                if sent_dt.tzinfo is None:
                    sent_dt = sent_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                sent_dt = cutoff - timedelta(seconds=1)  # treat as expired

            if sent_dt > cutoff:
                return True

            # Expired — update the timestamp
            conn.execute(
                "UPDATE notifications_dedup SET sent_at=? WHERE event_type=? AND dedup_key=?",
                (now.isoformat(), event_type, dedup_key),
            )
            conn.commit()
            return False

        # No prior row — insert
        conn.execute(
            "INSERT OR IGNORE INTO notifications_dedup (event_type, dedup_key, sent_at)"
            " VALUES (?, ?, ?)",
            (event_type, dedup_key, now.isoformat()),
        )
        conn.commit()
        return False
    except Exception:
        logger.exception("[PLATFORM_EVENTS] dedup DB check failed; allowing send")
        return False
    finally:
        if _own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _already_notified_recently(key: str) -> bool:
    """In-memory dedup check — fast intra-process layer.

    Uses _DEDUP_CACHE (cleared on process restart). For restart-safe dedup,
    use _already_notified_recently_db directly.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_DEDUP_WINDOW_HOURS)
    last = _DEDUP_CACHE.get(key)
    if last and last > cutoff:
        return True
    _DEDUP_CACHE[key] = now
    # Opportunistic GC of expired entries
    expired = [k for k, v in _DEDUP_CACHE.items() if v < cutoff]
    for k in expired:
        del _DEDUP_CACHE[k]
    return False


def write_heartbeat(conn=None, db_path: str | None = None) -> None:
    """Write a heartbeat sentinel row to notifications_sent.

    Called periodically (e.g. every N hours) to confirm the notification
    pipeline is alive. Uses channel='telegram', status='heartbeat'.
    """
    now = datetime.now(timezone.utc)
    _own_conn = conn is None
    if conn is None:
        try:
            from src.config import DB_PATH
            from src.utils.db import connect_db
            conn = connect_db(db_path or DB_PATH)
        except Exception:
            logger.debug("[PLATFORM_EVENTS] heartbeat DB connect failed")
            return
    try:
        conn.execute(
            "INSERT INTO notifications_sent"
            " (event_type, channel, recipient, sent_at, status, retry_count, error_msg)"
            " VALUES ('heartbeat', 'telegram', NULL, ?, 'heartbeat', 0, NULL)",
            (now.isoformat(),),
        )
        conn.commit()
    except Exception:
        logger.exception("[PLATFORM_EVENTS] heartbeat write failed")
    finally:
        if _own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _send(message: str) -> None:
    """Send via the existing telegram module. Failures are logged,
    not raised — notifications must never crash business logic."""
    try:
        from src.notifications.telegram import send_telegram
        send_telegram(message)
    except Exception:
        logger.exception("[PLATFORM_EVENTS] telegram send failed")


def notify_backtest_complete(
    strategy_id: str, result_id: str, passed_gate_a: bool,
    _conn=None,
) -> None:
    """Fired from backtest_engine.run_backtest on completion."""
    key = _dedup_key("backtest_complete", f"{strategy_id}::{result_id}")
    if _already_notified_recently_db("backtest_complete", key, conn=_conn):
        return
    gate = "[OK] passed auto gate" if passed_gate_a else "[WAIT] awaiting manual"
    _send(
        f"{_PREFIX} Backtest complete: {strategy_id} "
        f"(result_id={result_id[:8]}) {gate}"
    )


def notify_shadow_gate_ready(strategy_id: str, evidence: dict, _conn=None) -> None:
    """Fired when a shadow_trading gate check first passes for a
    strategy. Dedup per-strategy within 24h."""
    key = _dedup_key("shadow_gate_ready", strategy_id)
    if _already_notified_recently_db("shadow_gate_ready", key, conn=_conn):
        return
    dsr = evidence.get("dsr")
    pbo = evidence.get("pbo")
    oos = evidence.get("oos_efficiency")
    parts = [f"{_PREFIX} Gate ready for shadow_trading: {strategy_id}"]
    if dsr is not None:
        parts.append(f"DSR={dsr:.3f}")
    if pbo is not None:
        parts.append(f"PBO={pbo:.3f}")
    if oos is not None:
        parts.append(f"OOS_eff={oos:.3f}")
    parts.append("awaiting manual approval.")
    _send(" ".join(parts))


def notify_strategy_promoted(
    strategy_id: str, from_status: str | None, to_status: str,
) -> None:
    """Fired from promotion.promote after successful state transition."""
    _send(
        f"{_PREFIX} Promoted: {strategy_id} {from_status or 'None'} → {to_status}"
    )


def notify_strategy_demoted(strategy_id: str, reason: str) -> None:
    """Fired from promotion.demote."""
    _send(
        f"{_PREFIX} Demoted: {strategy_id} → deprecated. Reason: {reason}"
    )

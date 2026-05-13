"""Alert silence detector — T14 D5.

Detects notification silence during market hours by reading a UNION of three
signal sources, then emitting via safe_send + writing a platform_events row.

Called by: src/scheduler/watch.py (tick_alert_silence — 5-min cadence)
Calls: src.notifications.telegram.safe_send (notification dispatch)
Owns tables: platform_events (INSERT only — TableDef owned by schema/registry.py)
Config keys: none (threshold_minutes passed by caller, default 60)
Tests: tests/monitoring/test_alert_silence.py
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.notifications.telegram import safe_send
from src.scheduler.holidays import is_market_open

logger = logging.getLogger(__name__)


@dataclass
class AlertSilenceFinding:
    last_notification_ts: Optional[datetime]
    minutes_silent: int
    source: str  # "notifications_sent" | "digest_flushed" | "digest_enqueued" | "none"


def check_alert_silence(
    now_et: datetime,
    threshold_minutes: int = 60,
    conn=None,
) -> "AlertSilenceFinding | None":
    """During market hours, check if no notifications have flowed in >threshold_minutes.

    Reads UNION of three sources:
    1. notifications_sent WHERE status='ok' MAX sent_at
    2. notifications_digest_queue WHERE flushed_at IS NOT NULL MAX flushed_at
    3. notifications_digest_queue WHERE created_at IS NOT NULL MAX created_at

    The third term (created_at) is critical: it proves the watch loop is alive
    during quiet-hours digest-only windows (no sends + no flushes).

    Outside market hours: no-op → returns None.
    On silence: emits safe_send(event_type='alert_silence') + platform_events row.
    """
    if not is_market_open(now_et):
        return None
    _conn, _opened = _resolve_conn(conn)
    try:
        return _run_silence_check(_conn, now_et, threshold_minutes)
    except Exception as exc:
        logger.error("[ALERT_SILENCE] check_alert_silence failed: %s", exc)
        return None
    finally:
        if _opened and _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass


def _resolve_conn(conn):
    """Return (conn, opened) — opened=True when we opened the connection."""
    if conn is not None:
        return conn, False
    from src.utils.db import connect_db
    from src.config import DB_PATH
    return connect_db(DB_PATH), True


def _run_silence_check(conn, now_et: datetime, threshold_minutes: int):
    """Core silence detection on an open connection. Returns finding or None."""
    max_ts_str, source = _query_max_signal(conn)
    if max_ts_str is not None:
        max_ts = _parse_ts(max_ts_str)
        if max_ts is not None:
            if (now_et - max_ts).total_seconds() < threshold_minutes * 60:
                return None
    minutes_silent = _compute_minutes_silent(now_et, max_ts_str, threshold_minutes)
    finding = AlertSilenceFinding(
        last_notification_ts=_parse_ts(max_ts_str) if max_ts_str else None,
        minutes_silent=minutes_silent,
        source=source,
    )
    _emit_side_effects(finding, conn, now_et)
    return finding


def _query_max_signal(conn) -> tuple:
    """Return (max_ts_str, source) from the UNION of three signal sources.

    Sources (in priority order by recency):
      1. notifications_sent status='ok' → source='notifications_sent'
      2. notifications_digest_queue flushed_at IS NOT NULL → source='digest_flushed'
      3. notifications_digest_queue created_at IS NOT NULL → source='digest_enqueued'
    """
    sql = """
        SELECT MAX(ts), source FROM (
            SELECT sent_at AS ts, 'notifications_sent' AS source
            FROM notifications_sent
            WHERE status = 'ok'
            UNION ALL
            SELECT flushed_at AS ts, 'digest_flushed' AS source
            FROM notifications_digest_queue
            WHERE flushed_at IS NOT NULL
            UNION ALL
            SELECT created_at AS ts, 'digest_enqueued' AS source
            FROM notifications_digest_queue
            WHERE created_at IS NOT NULL
        )
    """
    row = conn.execute(sql).fetchone()
    if row is None or row[0] is None:
        return (None, "none")
    return (row[0], row[1])


def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp string to a timezone-aware datetime (UTC if no tz)."""
    if not ts_str:
        return None
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _compute_minutes_silent(
    now_et: datetime,
    max_ts_str: Optional[str],
    threshold_minutes: int,
) -> int:
    """Compute minutes_silent. Falls back to threshold_minutes if no timestamp."""
    if max_ts_str is None:
        return threshold_minutes
    max_ts = _parse_ts(max_ts_str)
    if max_ts is None:
        return threshold_minutes
    delta = (now_et - max_ts).total_seconds()
    return max(threshold_minutes, int(delta / 60))


def _emit_side_effects(
    finding: AlertSilenceFinding,
    conn,
    now_et: datetime,
) -> None:
    """Emit safe_send notification and write platform_events row."""
    last_seen_str = (
        finding.last_notification_ts.isoformat()
        if finding.last_notification_ts is not None
        else "never"
    )
    try:
        safe_send(
            "alert_silence",
            severity="high",
            last_seen=last_seen_str,
            minutes_silent=finding.minutes_silent,
        )
    except Exception as exc:
        logger.warning("[ALERT_SILENCE] safe_send failed: %s", exc)

    payload = json.dumps({
        "last_seen": last_seen_str,
        "minutes_silent": finding.minutes_silent,
        "source": finding.source,
    })
    try:
        conn.execute(
            """INSERT INTO platform_events (event_type, severity, payload_json, source)
               VALUES (?, ?, ?, ?)""",
            ("alert_silence", "high", payload, "alert_silence"),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[ALERT_SILENCE] platform_events insert failed: %s", exc)

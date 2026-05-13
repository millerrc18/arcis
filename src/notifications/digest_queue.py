"""Notification digest queue — persistence layer for PolicyDecision(verdict='digest') outputs.

T11 Sprint 5 Wave D D2.

Called by: scheduler.watch (tick_digest_queue), tests (directly — T12 will call enqueue from safe_send)
Calls: none (DB writes only; dispatcher is injected)
Owns tables: notifications_digest_queue
Config keys: notifications.retry.attempts, notifications.digest_flush_minutes
Tests: tests/notifications/test_digest_queue.py, tests/notifications/test_digest_queue_atomicity.py

SCOPE FENCE: T11 provides the DigestQueue.enqueue(payload) API.
The only production caller will be T12 (safe_send). T11's test suite and
the flush hook are the only callers in this PR.

Atomicity contract (SQLite):
  - 'pending' → 'in_progress': UPDATE ... WHERE flush_status='pending'
    (atomic single-row transition; SQLite serialises writes, so no row
    is ever claimed by two concurrent flush calls in the same process)
  - 'in_progress' orphans from a crash are recovered on the next flush tick
    by treating them as failed (increment attempts, re-queue as pending or abandon)

FlushResult lifecycle for a single row:
  pending → in_progress → sent             (success)
  pending → in_progress → pending          (dispatcher raised; attempts < retry_attempts)
  pending → in_progress → abandoned        (dispatcher raised; attempts == retry_attempts)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from src.notifications.telegram import _KNOWN_EVENT_TYPES, _redact_token

logger = logging.getLogger(__name__)


@dataclass
class FlushResult:
    successes: int
    failures: int
    abandoned: int


class DigestQueue:
    def __init__(self, conn, *, config) -> None:
        self._conn = conn
        self._config = config

    def enqueue(
        self,
        *,
        event_type: str,
        severity: str,
        payload: dict,
        source_tag: str = "unknown",
    ) -> int:
        if event_type not in _KNOWN_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type {event_type!r}. "
                f"Must be one of the registered event types in src.notifications.telegram._KNOWN_EVENT_TYPES."
            )
        payload_json = json.dumps(payload)
        cur = self._conn.execute(
            "INSERT INTO notifications_digest_queue"
            " (event_type, severity, payload_json, source_tag, flush_status, flush_attempts)"
            " VALUES (?, ?, ?, ?, 'pending', 0)",
            (event_type, severity, payload_json, source_tag[:64]),
        )
        self._conn.commit()
        return cur.lastrowid

    def _dispatch_one_row(
        self,
        row_id: int,
        payload: dict,
        attempts: int,
        dispatcher: Callable[[dict], None],
    ) -> str:
        """Dispatch a single row. Returns 'sent', 'pending' (retry), or 'abandoned'."""
        try:
            dispatcher(payload)
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "UPDATE notifications_digest_queue"
                " SET flush_status='sent', flushed_at=?, flush_attempts=?"
                " WHERE id=?",
                (now, attempts + 1, row_id),
            )
            self._conn.commit()
            return "sent"
        except Exception as exc:
            new_attempts = attempts + 1
            if new_attempts >= self._config.retry_attempts:
                self._conn.execute(
                    "UPDATE notifications_digest_queue"
                    " SET flush_status='abandoned', flush_attempts=?, flush_error=?"
                    " WHERE id=?",
                    (new_attempts, _redact_token(str(exc))[:500], row_id),
                )
                self._conn.commit()
                return "abandoned"
            self._conn.execute(
                "UPDATE notifications_digest_queue"
                " SET flush_status='pending', flush_attempts=?"
                " WHERE id=?",
                (new_attempts, row_id),
            )
            self._conn.commit()
            return "pending"

    def flush(
        self,
        *,
        max_rows: int = 100,
        dispatcher: Callable[[dict], None],
    ) -> FlushResult:
        successes = 0
        failures = 0
        abandoned = 0

        self._recover_orphaned_in_progress()

        rows = self._conn.execute(
            "SELECT id, payload_json, flush_attempts FROM notifications_digest_queue"
            " WHERE flush_status='pending'"
            " ORDER BY created_at ASC"
            " LIMIT ?",
            (max_rows,),
        ).fetchall()

        for row in rows:
            claimed = self._conn.execute(
                "UPDATE notifications_digest_queue"
                " SET flush_status='in_progress'"
                " WHERE id=? AND flush_status='pending'",
                (row["id"],),
            ).rowcount
            self._conn.commit()
            if claimed == 0:
                continue

            outcome = self._dispatch_one_row(
                row["id"], json.loads(row["payload_json"]), row["flush_attempts"], dispatcher
            )
            if outcome == "sent":
                successes += 1
            elif outcome == "abandoned":
                abandoned += 1
            else:
                failures += 1

        return FlushResult(successes=successes, failures=failures, abandoned=abandoned)

    def mark_flush_failed(self, row_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE notifications_digest_queue"
            " SET flush_status='abandoned', flush_error=?"
            " WHERE id=?",
            (_redact_token(error)[:500], row_id),
        )
        self._conn.commit()

    def pending_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM notifications_digest_queue WHERE flush_status='pending'"
        ).fetchone()[0]

    def abandoned_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM notifications_digest_queue WHERE flush_status='abandoned'"
        ).fetchone()[0]

    def _recover_orphaned_in_progress(self) -> None:
        rows = self._conn.execute(
            "SELECT id, flush_attempts FROM notifications_digest_queue"
            " WHERE flush_status='in_progress'"
        ).fetchall()
        for row in rows:
            row_id = row["id"]
            attempts = row["flush_attempts"] + 1
            if attempts >= self._config.retry_attempts:
                self._conn.execute(
                    "UPDATE notifications_digest_queue"
                    " SET flush_status='abandoned', flush_attempts=?,"
                    " flush_error='orphaned in_progress row (crash recovery)'"
                    " WHERE id=?",
                    (attempts, row_id),
                )
            else:
                self._conn.execute(
                    "UPDATE notifications_digest_queue"
                    " SET flush_status='pending', flush_attempts=?"
                    " WHERE id=?",
                    (attempts, row_id),
                )
        if rows:
            self._conn.commit()

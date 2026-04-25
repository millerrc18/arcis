"""Broker exception structured logger and persistence helper.

Called by: shadow_trading.executor, services.recap_service,
           services.shadow_service, services.system_service
Calls: utils.db.connect_db
Owns tables: broker_exceptions (INSERT only)
Config keys: none
Tests: tests/shadow_trading/test_broker_exception_logger.py

Provides log_and_persist() as the public surface: logs at WARNING with
structured fields (ticker, operation, broker, recoverable) and persists a
row to broker_exceptions so operators can triage the frequency and type of
broker failures over time.

Design rule (B2): the persistence helper must never raise. If the DB write
fails (e.g. locked DB), it logs at CRITICAL and returns silently — an
exception logger must not throw exceptions or corrupt the calling trade path.
"""

import logging
import traceback as _tb
from datetime import datetime, timezone

from src.utils.db import connect_db

logger = logging.getLogger(__name__)


def _persist_broker_exception(
    ticker: str,
    operation: str,
    broker: str,
    exc: Exception,
    recoverable: bool,
    db_path: str | None = None,
    correlation_id: str | None = None,
    retry_count: int | None = None,
    outcome: str = "persisted",
) -> None:
    """Insert one row into broker_exceptions. Swallows all errors internally.

    If the INSERT fails (locked DB, missing table, etc.), logs at CRITICAL
    and returns — does NOT re-raise. This preserves the calling trade path.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    exc_class = type(exc).__name__
    exc_msg = str(exc)[:1000]
    tb_text = _tb.format_exc()
    try:
        kwargs = {} if db_path is None else {"db_path": db_path}
        conn = connect_db(**kwargs)
        with conn:
            conn.execute(
                """
                INSERT INTO broker_exceptions
                    (ticker, operation, broker, timestamp, exception_class,
                     exception_message, traceback, recoverable, created_at,
                     correlation_id, retry_count, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker, operation, broker, now_iso, exc_class,
                    exc_msg, tb_text, int(recoverable), now_iso,
                    correlation_id, retry_count, outcome,
                ),
            )
    except Exception as insert_err:
        logger.critical(
            "[BROKER_EXCEPTION_LOGGER] Failed to persist broker exception to DB: %s",
            insert_err,
        )


def log_and_persist(
    ticker: str,
    operation: str,
    broker: str,
    exc: Exception,
    recoverable: bool,
    db_path: str | None = None,
    correlation_id: str | None = None,
    retry_count: int | None = None,
    outcome: str = "persisted",
) -> None:
    """Log a broker exception at WARNING and persist it to broker_exceptions.

    Public surface for all bug_silent_swallow and partial_swallow upgrades.
    Returns None — does not re-raise the exception (caller decides policy).
    """
    logger.warning(
        "[BROKER_EXCEPTION] ticker=%s op=%s broker=%s recoverable=%s exc=%s: %s",
        ticker, operation, broker, recoverable, type(exc).__name__, exc,
        exc_info=True,
    )
    _persist_broker_exception(
        ticker=ticker,
        operation=operation,
        broker=broker,
        exc=exc,
        recoverable=recoverable,
        db_path=db_path,
        correlation_id=correlation_id,
        retry_count=retry_count,
        outcome=outcome,
    )

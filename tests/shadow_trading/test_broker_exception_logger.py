"""Tests for src.shadow_trading.broker_exception_logger.

Covers:
- log_and_persist() emits WARNING with structured fields
- log_and_persist() inserts a row into broker_exceptions in-memory DB
- _persist_broker_exception() swallows DB errors without re-raising (CRITICAL log)
- 4 bug_silent_swallow site upgrades: executor.py:1460, recap_service.py:57,
  shadow_service.py:98, system_service.py:175

All DB writes use an in-memory SQLite created from the registry DDL.
No live broker calls.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from src.shadow_trading.broker_exception_logger import log_and_persist, _persist_broker_exception


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_in_memory_db():
    """Return an in-memory SQLite connection with broker_exceptions table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE broker_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            operation TEXT NOT NULL,
            broker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            exception_class TEXT NOT NULL,
            exception_message TEXT NOT NULL,
            traceback TEXT,
            recoverable INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            correlation_id TEXT,
            retry_count INTEGER,
            outcome TEXT
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# log_and_persist() tests
# ---------------------------------------------------------------------------

def test_log_and_persist_emits_warning(caplog):
    """log_and_persist() must log at WARNING level with structured fields."""
    exc = ValueError("test broker error")
    conn = _make_in_memory_db()

    with caplog.at_level(logging.WARNING, logger="src.shadow_trading.broker_exception_logger"):
        with patch("src.shadow_trading.broker_exception_logger.connect_db", return_value=conn):
            log_and_persist(
                ticker="AAPL",
                operation="fetch_positions",
                broker="alpaca_paper",
                exc=exc,
                recoverable=True,
            )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records, "Expected at least one WARNING log record"
    combined = " ".join(r.getMessage() for r in warning_records)
    assert "AAPL" in combined or "fetch_positions" in combined or "alpaca_paper" in combined


def test_log_and_persist_inserts_db_row():
    """log_and_persist() must insert a row into broker_exceptions."""
    exc = AttributeError("'NoneType' has no attribute 'get_all_positions'")
    conn = _make_in_memory_db()

    with patch("src.shadow_trading.broker_exception_logger.connect_db", return_value=conn):
        log_and_persist(
            ticker="TSLA",
            operation="fetch_positions",
            broker="alpaca_paper",
            exc=exc,
            recoverable=True,
            correlation_id="trade-abc-123",
        )

    row = conn.execute("SELECT * FROM broker_exceptions").fetchone()
    assert row is not None, "Expected a row inserted into broker_exceptions"
    assert row["ticker"] == "TSLA"
    assert row["operation"] == "fetch_positions"
    assert row["broker"] == "alpaca_paper"
    assert row["exception_class"] == "AttributeError"
    assert "NoneType" in row["exception_message"]
    assert row["recoverable"] == 1
    assert row["correlation_id"] == "trade-abc-123"


def test_log_and_persist_recoverable_false_encodes_zero():
    """recoverable=False must store 0 in the INTEGER column."""
    exc = RuntimeError("place_order failed")
    conn = _make_in_memory_db()

    with patch("src.shadow_trading.broker_exception_logger.connect_db", return_value=conn):
        log_and_persist(
            ticker="SPY",
            operation="place_bracket_order",
            broker="alpaca_live",
            exc=exc,
            recoverable=False,
        )

    row = conn.execute("SELECT recoverable FROM broker_exceptions").fetchone()
    assert row["recoverable"] == 0


def test_log_and_persist_returns_none():
    """log_and_persist() must return None (not re-raise)."""
    exc = ConnectionError("timeout")
    conn = _make_in_memory_db()

    with patch("src.shadow_trading.broker_exception_logger.connect_db", return_value=conn):
        result = log_and_persist(
            ticker="MSFT",
            operation="connect",
            broker="ib",
            exc=exc,
            recoverable=True,
        )

    assert result is None


def test_persist_broker_exception_swallows_db_error(caplog):
    """_persist_broker_exception() must NOT re-raise when DB insert fails.

    When connect_db() or the INSERT raises, it must log at CRITICAL and return.
    """
    exc = RuntimeError("something bad")

    with caplog.at_level(logging.CRITICAL, logger="src.shadow_trading.broker_exception_logger"):
        with patch(
            "src.shadow_trading.broker_exception_logger.connect_db",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            # Must NOT raise
            _persist_broker_exception(
                ticker="GLD",
                operation="fetch_positions",
                broker="alpaca_paper",
                exc=exc,
                recoverable=True,
            )

    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert critical_records, "Expected CRITICAL log on DB insert failure"


# ---------------------------------------------------------------------------
# Silent-swallow site upgrade tests
# ---------------------------------------------------------------------------

def test_executor_get_positions_logs_warning_not_debug(caplog):
    """executor.py:1460 — get_all_positions() failure must log at WARNING, not DEBUG.

    The B2 design designates this as bug_silent_swallow R2: an AttributeError
    that was previously swallowed at DEBUG level.
    """
    from src.shadow_trading import executor

    with caplog.at_level(logging.DEBUG):
        with patch(
            "src.shadow_trading.alpaca_adapter.get_all_positions",
            side_effect=AttributeError("'NoneType' has no attribute 'positions'"),
        ):
            with patch(
                "src.shadow_trading.broker_exception_logger.connect_db",
                return_value=_make_in_memory_db(),
            ):
                with patch.object(executor, "get_open_shadow_trades", return_value=[]):
                    executor.check_and_manage_open_trades(db_path=":memory:")

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, (
        "Expected WARNING or higher log when get_all_positions raises — "
        "was still swallowed at DEBUG"
    )


def test_recap_service_shadow_data_failure_logs_warning(caplog):
    """recap_service.py — get_shadow_data_for_recap() failure must log WARNING and persist a broker_exceptions row.

    PR #690 O1: route through ``log_and_persist`` so the failure is dashboard-observable
    in BrokerExceptionsPanel.
    """
    from src.services import recap_service

    config = {"shadow_trading": {"enabled": True}}
    db_conn = _make_in_memory_db()

    # recap_service uses lazy imports; patch at the source module paths
    with caplog.at_level(logging.DEBUG):
        with patch(
            "src.shadow_trading.broker_exception_logger.connect_db",
            return_value=db_conn,
        ):
            with patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]):
                with patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=MagicMock()):
                    with patch("src.data_ingestion.market_data.fetch_spy_benchmark") as mock_spy:
                        mock_spy.return_value = MagicMock(empty=False)
                        with patch("src.features.engine.compute_all_features", return_value=MagicMock()):
                            with patch("src.ranking.ranker.rank_universe", return_value=MagicMock()):
                                with patch("src.ranking.ranker.get_top_candidates",
                                           return_value={"packet_worthy": [], "watchlist": []}):
                                    with patch("src.journal.store.get_todays_recommendations", return_value=[]):
                                        with patch("src.packets.eod_recap.build_eod_recap", return_value="body"):
                                            with patch(
                                                "src.packets.eod_recap.get_shadow_data_for_recap",
                                                side_effect=RuntimeError("DB unavailable"),
                                            ):
                                                with patch(
                                                    "src.notifications.email_digest.enqueue_for_email_digest"
                                                ):
                                                    recap_service.generate_eod_recap(config)

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, (
        "Expected WARNING log when get_shadow_data_for_recap raises — was silently swallowed"
    )

    # PR #690 O1: must also persist a broker_exceptions row for dashboard visibility
    row = db_conn.execute("SELECT * FROM broker_exceptions").fetchone()
    assert row is not None, (
        "Expected broker_exceptions row inserted for recap fetch_shadow_data failure — "
        "BrokerExceptionsPanel won't see this failure"
    )
    assert row["operation"] == "fetch_shadow_data"
    assert row["broker"] == "n/a"
    assert row["exception_class"] == "RuntimeError"
    assert row["recoverable"] == 1


def test_shadow_service_account_info_failure_logs_warning(caplog):
    """shadow_service.py — get_account_info() failure must log WARNING and persist a broker_exceptions row.

    PR #690 O1: route through ``log_and_persist`` so the failure is dashboard-observable
    in BrokerExceptionsPanel.
    """
    from src.services import shadow_service

    config = {"shadow_trading": {"timeout_days": 15}}
    db_conn = _make_in_memory_db()

    with caplog.at_level(logging.DEBUG):
        with patch(
            "src.shadow_trading.broker_exception_logger.connect_db",
            return_value=db_conn,
        ):
            with patch("src.journal.store.get_open_shadow_trades", return_value=[]):
                with patch(
                    "src.shadow_trading.alpaca_adapter.get_account_info",
                    side_effect=ConnectionError("Alpaca API down"),
                ):
                    shadow_service.get_shadow_status(config)

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, (
        "Expected WARNING log when get_account_info raises — was silently swallowed with pass"
    )

    # PR #690 O1: must also persist a broker_exceptions row for dashboard visibility
    row = db_conn.execute("SELECT * FROM broker_exceptions").fetchone()
    assert row is not None, (
        "Expected broker_exceptions row inserted for shadow fetch_account failure — "
        "BrokerExceptionsPanel won't see this failure"
    )
    assert row["operation"] == "fetch_account"
    assert row["broker"] == "alpaca_paper"
    assert row["exception_class"] == "ConnectionError"
    assert row["recoverable"] == 1


def test_system_service_get_live_broker_failure_logs_warning(caplog):
    """system_service.py — get_live_broker() failure must log WARNING and persist a broker_exceptions row.

    PR #690 O1: route through ``log_and_persist`` so the failure is dashboard-observable
    in BrokerExceptionsPanel.
    """
    from src.services import system_service

    config = {"live_trading": {"broker": "ib"}}
    db_conn = _make_in_memory_db()

    with caplog.at_level(logging.DEBUG):
        with patch(
            "src.shadow_trading.broker_exception_logger.connect_db",
            return_value=db_conn,
        ):
            with patch("src.trading.broker_factory.get_live_broker",
                       side_effect=TypeError("'NoneType' is not subscriptable")):
                with patch("src.llm.client.is_llm_available", return_value=False):
                    with patch("src.training.versioning.get_active_model_name", return_value="v1"):
                        with patch("src.training.versioning.get_training_example_counts",
                                   return_value={"total": 0}):
                            with patch("src.risk.governor._is_halted", return_value=False):
                                result = system_service.get_system_status(config)

    # Must not raise
    assert result["ib_connected"] is False

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, (
        "Expected WARNING log when get_live_broker raises TypeError — was silently swallowed"
    )

    # PR #690 O1: must also persist a broker_exceptions row for dashboard visibility
    row = db_conn.execute("SELECT * FROM broker_exceptions").fetchone()
    assert row is not None, (
        "Expected broker_exceptions row inserted for system get_live_broker failure — "
        "BrokerExceptionsPanel won't see this failure"
    )
    assert row["operation"] == "get_live_broker"
    assert row["broker"] == "ib"
    assert row["exception_class"] == "TypeError"
    assert row["recoverable"] == 1

"""Sprint 2 L5 — regression tests for EOD report format-string bug.

Audit 2026-04-20 arcis.log: EOD report failed on 04-14, 04-15, 04-16,
04-17 with:
  [WATCH] EOD report failed: Unknown format code 'f' for object of type 'str'

Root cause: shadow_trades.pnl_dollars and pnl_pct columns are stored as
SQLite TEXT (89 live rows typed text despite the REAL column type —
SQLite's type affinity allows str INSERTs through). notify_eod_report
uses f-strings like ``${pnl:+.2f}`` which raise TypeError on str input.

Fix: float-cast each PnL value at the call site in reports.py. Handles
None/NULL defensively.

These tests verify:
  1. notify_eod_report succeeds when given str-typed PnL values via
     send_eod_report (simulating the live DB's text storage).
  2. None values in best/worst PnL do not raise AttributeError.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    from src.schema.sqlite import create_all_tables
    db = str(tmp_path / "test.db")
    create_all_tables(db)
    return db


def _seed_closed_trade(conn, ticker: str, pnl_dollars: str, pnl_pct: str,
                        today_iso: str, source: str = "paper") -> None:
    """Insert a minimal closed trade with pnl values stored as TEXT
    (matching production storage behavior)."""
    import uuid
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, direction, status, pnl_dollars, pnl_pct, "
        "actual_exit_time, source, created_at, updated_at, quarantined) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), ticker, "long", "closed",
         pnl_dollars, pnl_pct, today_iso, source, today_iso, today_iso, 0),
    )


def _seed_rejected_trade(conn, ticker: str, today_iso: str, source: str = "paper") -> None:
    """Insert a rejected trade that should not count as a realized loss."""
    import uuid
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, direction, status, pnl_dollars, pnl_pct, "
        "actual_exit_time, source, created_at, updated_at, quarantined) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), ticker, "long", "rejected",
         "-999.00", "-10.00", today_iso, source, today_iso, today_iso, 0),
    )


def _seed_vix(conn, vix: float = 18.0) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO vix_term_structure "
        "(collected_at, collected_date, vix) VALUES (?, ?, ?)",
        (now.isoformat(), now.strftime("%Y-%m-%d"), vix),
    )


def test_send_eod_report_succeeds_with_text_typed_pnl(tmp_db, monkeypatch):
    """pnl_dollars and pnl_pct stored as str (production reality) must
    not produce ``Unknown format code 'f' for object of type 'str'``."""
    from datetime import datetime

    import src.scheduler.reports as reports

    # Patch DB_PATH in the reports module so send_eod_report uses tmp_db
    monkeypatch.setattr(reports, "DB_PATH", tmp_db)

    # Today's string
    today_iso = datetime.now(reports.ET).strftime("%Y-%m-%dT%H:%M:%S")

    with sqlite3.connect(tmp_db) as conn:
        # Seed 2 closed paper trades today, text-typed PnL
        _seed_closed_trade(conn, "AAPL", "142.50", "3.21", today_iso, "paper")
        _seed_closed_trade(conn, "MSFT", "-47.80", "-1.15", today_iso, "paper")
        _seed_vix(conn, 18.5)
        conn.commit()

    # Patch Telegram functions
    with patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ), patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_send:
        # Must not raise; should call send_telegram once
        reports.send_eod_report()

    assert mock_send.called, "send_telegram should be called with the formatted message"
    # The message body (first positional arg) should contain dollar-formatted PnL
    call_args = mock_send.call_args
    msg = call_args.args[0] if call_args.args else call_args.kwargs.get("message", "")
    assert "+$142" in msg or "$142" in msg or "$+94.70" in msg or "$94.70" in msg or "$+0" in msg, (
        f"expected formatted PnL in EOD message, got: {msg[:200]}"
    )


def test_send_eod_report_handles_none_best_worst(tmp_db, monkeypatch):
    """If no closed trades today, best/worst are None — must not crash."""
    from datetime import datetime

    import src.scheduler.reports as reports
    monkeypatch.setattr(reports, "DB_PATH", tmp_db)

    with sqlite3.connect(tmp_db) as conn:
        # Don't seed any closed trades — best/worst queries return None
        _seed_vix(conn, 18.0)
        conn.commit()

    with patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ), patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_send:
        reports.send_eod_report()
    assert mock_send.called


def test_notify_eod_report_format_accepts_float_inputs():
    """Direct sanity: notify_eod_report works with float kwargs
    (proves the fix-target signature is float-compatible)."""
    from src.notifications.telegram import notify_eod_report
    with patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ), patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ):
        result = notify_eod_report(
            paper_open=3, paper_open_pnl=142.5,
            paper_closed_today=2, paper_closed_pnl=-47.8,
            live_open=0, live_open_pnl=0.0,
            live_closed_today=0, live_closed_pnl=0.0,
            win_rate=0.75, wins=3, losses=1,
            best_ticker="AAPL", best_pct=3.21,
            worst_ticker="MSFT", worst_pct=-1.15,
            regime="GREEN", vix=18.5, vix_change=0.2,
            risk_rejected=2, risk_qualified=10,
        )
    assert result is True


def test_send_eod_report_ignores_rejected_trades_in_win_rate(tmp_db, monkeypatch):
    """Rejected terminal trades must not render as realized losses in Telegram."""
    from datetime import datetime

    import src.scheduler.reports as reports

    monkeypatch.setattr(reports, "DB_PATH", tmp_db)
    today_iso = datetime.now(reports.ET).strftime("%Y-%m-%dT%H:%M:%S")

    with sqlite3.connect(tmp_db) as conn:
        _seed_closed_trade(conn, "AAPL", "50.00", "2.00", today_iso, "paper")
        _seed_rejected_trade(conn, "MSFT", today_iso, "paper")
        _seed_vix(conn, 18.5)
        conn.commit()

    with patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ), patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_send:
        reports.send_eod_report()

    msg = mock_send.call_args.args[0]
    assert "(1W / 0L)" in msg

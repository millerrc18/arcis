"""T15b — safe_send + email notifier write hooks tests.

Tests that safe_send and send_email persist outcomes to notifications_sent table.

T15-REV additions:
- MUST_FIX 2: force_send=True bypasses silent-on-pass in notify_validation_summary
- SHOULD_FIX 5: safe_send failure end-to-end test against real DB (not mocked write)
"""
import sqlite3
import tempfile
import os
from unittest.mock import patch, MagicMock

from src.notifications.telegram import TradeOpenedPayload


def _payload():
    return TradeOpenedPayload(
        ticker="AAPL", entry_price=100.0, stop=95.0, target=110.0, score=80, shares=10
    )


def _make_sent_db():
    """In-memory DB with notifications_sent table."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE notifications_sent ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_type TEXT NOT NULL,"
        "  channel TEXT NOT NULL,"
        "  recipient TEXT,"
        "  sent_at TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  retry_count INTEGER NOT NULL DEFAULT 0,"
        "  error_msg TEXT"
        ")"
    )
    conn.commit()
    return conn


def test_safe_send_failure_writes_failed_row():
    """Network failure in safe_send → notifications_sent row with status='failed', error_msg populated."""
    import requests.exceptions
    from src.notifications.telegram import safe_send

    conn = _make_sent_db()

    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
        with patch(
            "src.notifications.telegram.notify_trade_opened",
            side_effect=requests.exceptions.RequestException("connection refused"),
        ):
            with patch("src.notifications.telegram._write_notification_sent") as mock_write:
                mock_write.side_effect = lambda **kw: _insert_sent(conn, **kw)
                safe_send("trade_opened", payload=_payload())

    rows = conn.execute("SELECT status, error_msg FROM notifications_sent").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "failed"
    assert rows[0][1] is not None
    assert "connection refused" in rows[0][1].lower() or "[REDACTED]" in rows[0][1]


def test_safe_send_success_writes_ok_row():
    """Successful safe_send dispatch → notifications_sent row with status='ok'."""
    from src.notifications.telegram import safe_send

    conn = _make_sent_db()

    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
        with patch(
            "src.notifications.telegram.notify_system_event",
            return_value=True,
        ):
            with patch("src.notifications.telegram._write_notification_sent") as mock_write:
                mock_write.side_effect = lambda **kw: _insert_sent(conn, **kw)
                result = safe_send("system_event", event="test_event", detail="ok")

    assert result is True
    rows = conn.execute("SELECT status FROM notifications_sent").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "ok"


def test_email_smtp_success_writes_ok_row():
    """SMTP success → notifications_sent row with channel='email', status='ok'."""
    from src.email.notifier import send_email

    conn = _make_sent_db()

    mock_server = MagicMock()
    mock_server.sendmail.return_value = {}

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("src.email.notifier.load_config", return_value={
            "email": {
                "smtp_server": "smtp.test.com",
                "smtp_port": 587,
                "use_tls": True,
                "username": "test@test.com",
                "to_address": "dest@test.com",
            }
        }):
            with patch.dict("os.environ", {"EMAIL_PASSWORD": "secret"}):
                with patch("src.email.notifier._write_notification_sent") as mock_write:
                    mock_write.side_effect = lambda **kw: _insert_sent(conn, **kw)
                    send_email("Test Subject", "Test Body")

    rows = conn.execute("SELECT channel, status FROM notifications_sent").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "email"
    assert rows[0][1] == "ok"


def test_email_smtp_fail_writes_failed_row():
    """SMTP failure → notifications_sent row with channel='email', status='failed'."""
    import smtplib
    from src.email.notifier import send_email

    conn = _make_sent_db()

    with patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "Service unavailable")):
        with patch("src.email.notifier.load_config", return_value={
            "email": {
                "smtp_server": "smtp.test.com",
                "smtp_port": 587,
                "use_tls": True,
                "username": "test@test.com",
                "to_address": "dest@test.com",
            }
        }):
            with patch.dict("os.environ", {"EMAIL_PASSWORD": "secret"}):
                with patch("src.email.notifier._write_notification_sent") as mock_write:
                    mock_write.side_effect = lambda **kw: _insert_sent(conn, **kw)
                    send_email("Test Subject", "Test Body")

    rows = conn.execute("SELECT channel, status FROM notifications_sent").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "email"
    assert rows[0][1] == "failed"


def _insert_sent(conn, event_type, channel, status, error_msg=None, **kw):
    """Helper: actually writes to the test in-memory connection."""
    from datetime import datetime, timezone
    conn.execute(
        "INSERT INTO notifications_sent (event_type, channel, recipient, sent_at, status, error_msg)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (event_type, channel, kw.get("recipient"), datetime.now(timezone.utc).isoformat(), status, error_msg),
    )
    conn.commit()


# ── MUST_FIX 2: force_send=True bypasses silent-on-pass ───────────────────────

def test_notify_validation_summary_silent_on_pass_default():
    """Default behavior: all-pass result returns True without calling send_telegram."""
    from src.notifications.telegram import notify_validation_summary
    result = {
        "checks_passed": 50, "checks_failed": 0, "checks_warning": 0,
        "checks_total": 50, "overall_status": "healthy", "categories": {},
    }
    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.send_telegram") as mock_send:
        ok = notify_validation_summary(result)
    assert ok is True
    mock_send.assert_not_called()


def test_notify_validation_summary_force_send_bypasses_silent_on_pass():
    """force_send=True sends notification even when failed=0 and warnings=0."""
    from src.notifications.telegram import notify_validation_summary
    result = {
        "checks_passed": 50, "checks_failed": 0, "checks_warning": 0,
        "checks_total": 50, "overall_status": "healthy", "categories": {},
    }
    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
        ok = notify_validation_summary(result, force_send=True)
    assert ok is True
    mock_send.assert_called_once()


def test_notify_validation_summary_force_send_with_failures_still_sends():
    """force_send=True does not interfere when there are failures (still sends)."""
    from src.notifications.telegram import notify_validation_summary
    result = {
        "checks_passed": 48, "checks_failed": 2, "checks_warning": 0,
        "checks_total": 50, "overall_status": "critical",
        "categories": {
            "database": [
                {"name": "db_test", "status": "fail", "detail": "conn error"},
            ],
        },
    }
    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
        ok = notify_validation_summary(result, force_send=True)
    assert ok is True
    mock_send.assert_called_once()


# ── SHOULD_FIX 5: end-to-end safe_send failure path via real DB ───────────────

def _make_tmp_db_path(tmp_dir):
    """Create a real SQLite DB file in tmp_dir with notifications_sent."""
    db_path = os.path.join(tmp_dir, "test_notifications.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE notifications_sent ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_type TEXT NOT NULL,"
        "  channel TEXT NOT NULL,"
        "  recipient TEXT,"
        "  sent_at TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  retry_count INTEGER NOT NULL DEFAULT 0,"
        "  error_msg TEXT"
        ")"
    )
    conn.commit()
    conn.close()
    return db_path


def test_safe_send_failure_writes_row_to_real_db():
    """Network failure in safe_send → real DB row with status='failed' (no mock on write)."""
    import requests.exceptions
    from src.notifications.telegram import safe_send

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _make_tmp_db_path(tmp_dir)

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
             patch(
                 "src.notifications.telegram.notify_trade_opened",
                 side_effect=requests.exceptions.RequestException("connection refused"),
             ), \
             patch("src.config.DB_PATH", db_path), \
             patch("src.notifications.telegram.DB_PATH", db_path, create=True):
            safe_send("trade_opened", payload=_payload())

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT status, error_msg FROM notifications_sent WHERE status='failed'"
        ).fetchall()
        conn.close()

    assert len(rows) == 1, f"Expected 1 failed row, got {len(rows)}"
    assert rows[0][0] == "failed"
    assert rows[0][1] is not None

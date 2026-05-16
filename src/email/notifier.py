"""SMTP email notifier for the Arcis system.

Called by: cli.commands, evaluation.auditor, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service
Calls: config, notifications
Owns tables: none
Config keys: cc_addresses, email, from_address, smtp_port, smtp_server, to_address, use_tls, username
Tests: tests/email/test_notifier.py
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText

from src.config import load_config
from src.notifications import safe_send

logger = logging.getLogger(__name__)

_TELEGRAM_BODY_LIMIT = 400
_yaml_password_warning_emitted = False


def _write_notification_sent(
    event_type: str,
    channel: str,
    status: str,
    error_msg: str | None = None,
    recipient: str | None = None,
    conn=None,
) -> None:
    """Persist an email dispatch outcome to notifications_sent. Silent on DB error."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _own_conn = conn is None
    try:
        if conn is None:
            from src.utils.db import connect_db
            from src.config import DB_PATH
            conn = connect_db(DB_PATH)
        conn.execute(
            "INSERT INTO notifications_sent"
            " (event_type, channel, recipient, sent_at, status, retry_count, error_msg)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (event_type, channel, recipient, now, status, error_msg),
        )
        conn.commit()
    except Exception:
        logger.debug("[EMAIL] _write_notification_sent failed silently", exc_info=True)
    finally:
        if _own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def send_email(subject: str, body: str, to_address: str | None = None) -> bool:
    """Send a plain-text email via SMTP.

    Supports CC recipients via config email.cc_addresses (list of strings).

    Returns True on success, False on failure.
    """
    config = load_config()
    email_cfg = config.get("email", {})

    smtp_server = email_cfg.get("smtp_server", "")
    smtp_port = email_cfg.get("smtp_port", 587)
    use_tls = email_cfg.get("use_tls", True)
    username = email_cfg.get("username", "")
    # C4: require EMAIL_PASSWORD env var; YAML fallback removed
    password = os.environ.get("EMAIL_PASSWORD", "")
    yaml_password = email_cfg.get("password", "")
    global _yaml_password_warning_emitted
    if yaml_password and not _yaml_password_warning_emitted:
        _yaml_password_warning_emitted = True
        logger.warning(
            "email.password YAML key is non-empty — passwords must be set via "
            "EMAIL_PASSWORD env var, not YAML config (security policy)"
        )
    from_address = email_cfg.get("from_address", username)
    recipient = to_address or email_cfg.get("to_address", "")
    # C5: handle None safely (YAML omission yields None, not [])
    cc_addresses = email_cfg.get("cc_addresses") or []

    if not smtp_server or not username or not password or not recipient:
        logger.warning("Email configuration is incomplete. Check your settings.")
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = recipient
    if cc_addresses:
        msg["Cc"] = ", ".join(cc_addresses)

    # Send to all recipients (To + CC)
    all_recipients = [recipient] + cc_addresses

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        if use_tls:
            server.starttls()
        server.login(username, password)
        failures = server.sendmail(from_address, all_recipients, msg.as_string())
        server.quit()
        # C17: sendmail returns {} on full success; non-empty dict means some/all recipients failed
        if failures:
            logger.warning("SMTP sendmail reported delivery failures: %s", failures)
            safe_send(
                "system_event",
                message=f"[EMAIL FAILED] {subject}\n{body[:_TELEGRAM_BODY_LIMIT]}",
            )
            _write_notification_sent(
                event_type="email_send", channel="email", status="failed",
                recipient=recipient, error_msg=str(failures)[:200],
            )
            return False
        _write_notification_sent(
            event_type="email_send", channel="email", status="ok", recipient=recipient,
        )
        return True
    except smtplib.SMTPAuthenticationError:
        logger.warning("SMTP authentication failed. Check username/password.")
        _write_notification_sent(
            event_type="email_send", channel="email", status="failed",
            recipient=recipient, error_msg="SMTPAuthenticationError",
        )
        return False
    except smtplib.SMTPConnectError:
        logger.warning("Could not connect to SMTP server.")
        _write_notification_sent(
            event_type="email_send", channel="email", status="failed",
            recipient=recipient, error_msg="SMTPConnectError",
        )
        return False
    except ConnectionRefusedError:
        logger.warning("Connection refused by SMTP server.")
        _write_notification_sent(
            event_type="email_send", channel="email", status="failed",
            recipient=recipient, error_msg="ConnectionRefusedError",
        )
        return False
    except Exception as e:
        logger.warning("Failed to send email: %s", e)
        _write_notification_sent(
            event_type="email_send", channel="email", status="failed",
            recipient=recipient, error_msg=str(e)[:200],
        )
        return False

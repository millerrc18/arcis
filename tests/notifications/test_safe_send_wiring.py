"""T12 — safe_send verdict-dispatch wiring tests.

+6 tests covering SEND/DIGEST/MUTE/ESCALATE/force/exception paths.
+3 fix-up tests: digest conn-close regression-lock, escalated-email redaction, non-network propagation.
"""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


def _make_notif_config(
    *,
    mute_event_types=None,
    digest_low=True,
    quiet_hours_start="22:00",
    quiet_hours_end="06:00",
    quiet_digest=True,
    routing_overrides=None,
):
    from src.notifications.policy import NotificationsConfig
    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=digest_low,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        quiet_digest=quiet_digest,
        mute_event_types=mute_event_types or [],
        routing_overrides=routing_overrides or {},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
        digest_flush_minutes=60,
    )


def _now_midday():
    return datetime(2026, 5, 12, 12, 0, tzinfo=ET)


def _make_digest_queue_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE notifications_digest_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_tag TEXT NOT NULL DEFAULT 'unknown',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            flushed_at TIMESTAMP,
            flush_status TEXT NOT NULL DEFAULT 'pending',
            flush_attempts INTEGER NOT NULL DEFAULT 0,
            flush_error TEXT
        )
    """)
    conn.commit()
    return conn


class TestSafeSendSendPath:
    def test_safe_send_send_path_dispatches_telegram(self):
        """severity=high → SEND verdict → notify_scan_complete called."""
        cfg = _make_notif_config()
        now = _now_midday()

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram.notify_scan_complete", return_value=True) as mock_notify:
                        with patch("src.notifications.telegram._write_notification_sent"):
                            from src.notifications.telegram import safe_send
                            result = safe_send(
                                "scan_complete",
                                severity="high",
                                packets_count=5,
                                trades_opened=1,
                                trades_closed=0,
                            )
                            assert result is True
                            mock_notify.assert_called_once_with(
                                packets_count=5, trades_opened=1, trades_closed=0
                            )


class TestSafeSendDigestPath:
    def test_safe_send_digest_path_enqueues(self):
        """severity=low + digest_low=True → DIGEST verdict → DigestQueue.enqueue called."""
        cfg = _make_notif_config(digest_low=True)
        now = _now_midday()
        conn = _make_digest_queue_conn()

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram._get_digest_db_conn", return_value=conn):
                        from src.notifications.telegram import safe_send
                        result = safe_send(
                            "scan_complete",
                            severity="low",
                            packets_count=2,
                            trades_opened=0,
                            trades_closed=0,
                        )
                        assert result is True
                        row = conn.execute(
                            "SELECT event_type, severity, flush_status FROM notifications_digest_queue"
                        ).fetchone()
                        assert row is not None
                        assert row["event_type"] == "scan_complete"
                        assert row["severity"] == "low"
                        assert row["flush_status"] == "pending"


class TestSafeSendMutePath:
    def test_safe_send_mute_path_drops(self):
        """event_type in mute_event_types → MUTE → no dispatch, returns False."""
        cfg = _make_notif_config(mute_event_types=["scan_complete"])
        now = _now_midday()

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram.notify_scan_complete") as mock_notify:
                        from src.notifications.telegram import safe_send
                        result = safe_send(
                            "scan_complete",
                            severity="normal",
                            packets_count=1,
                            trades_opened=0,
                            trades_closed=0,
                        )
                        assert result is False
                        mock_notify.assert_not_called()


class TestSafeSendForce:
    def test_safe_send_force_bypasses_policy(self):
        """force=True + muted event_type → still dispatches (SEND)."""
        cfg = _make_notif_config(mute_event_types=["scan_complete"])
        now = _now_midday()

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram.notify_scan_complete", return_value=True) as mock_notify:
                        with patch("src.notifications.telegram._write_notification_sent"):
                            from src.notifications.telegram import safe_send
                            result = safe_send(
                                "scan_complete",
                                severity="normal",
                                force=True,
                                packets_count=1,
                                trades_opened=0,
                                trades_closed=0,
                            )
                            assert result is True
                            mock_notify.assert_called_once()


class TestSafeSendDispatchException:
    def test_safe_send_handles_dispatch_exception(self):
        """dispatcher raises ConnectionError (network) → safe_send returns False."""
        cfg = _make_notif_config()
        now = _now_midday()

        import requests.exceptions
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram._record_send_failure") as mock_record:
                        with patch("src.notifications.telegram.notify_scan_complete",
                                   side_effect=requests.exceptions.ConnectionError("net down")):
                            from src.notifications.telegram import safe_send
                            result = safe_send(
                                "scan_complete",
                                severity="high",
                                packets_count=1,
                                trades_opened=0,
                                trades_closed=0,
                            )
                            assert result is False
                            mock_record.assert_called_once()


class TestSafeSendEscalatePath:
    def test_safe_send_escalate_path_high_priority(self):
        """escalate verdict → _do_dispatch_escalated called (both channels)."""
        from src.notifications.policy import PolicyDecision
        cfg = _make_notif_config(
            routing_overrides={
                "scan_complete": {"telegram": True, "email": True, "escalation_after_attempts": 1}
            }
        )
        now = _now_midday()

        escalate_decision = PolicyDecision(
            verdict="escalate",
            reason="test_escalate",
            channels=["telegram", "email"],
            matched_rule=1,
        )

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram.should_dispatch", return_value=escalate_decision):
                        with patch("src.notifications.telegram._do_dispatch_escalated",
                                   return_value=True) as mock_esc:
                            from src.notifications.telegram import safe_send
                            result = safe_send(
                                "scan_complete",
                                severity="high",
                                packets_count=1,
                                trades_opened=0,
                                trades_closed=0,
                            )
                            assert result is True
                            mock_esc.assert_called_once()


class TestSafeSendDigestConnClose:
    def test_safe_send_digest_path_closes_connection_after_enqueue(self):
        """Regression-lock: digest verdict must release DB connection after enqueue."""
        from sqlite3 import Connection
        from src.notifications.policy import PolicyDecision

        cfg = _make_notif_config(digest_low=True)
        now = _now_midday()

        digest_decision = PolicyDecision(
            verdict="digest",
            reason="digest_low",
            channels=["telegram"],
            matched_rule=4,
        )

        mock_conn = MagicMock(spec=Connection)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = 1

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram.should_dispatch",
                               return_value=digest_decision):
                        with patch("src.notifications.telegram._get_digest_db_conn",
                                   return_value=mock_conn):
                            with patch("src.notifications.digest_queue.DigestQueue",
                                       return_value=mock_queue):
                                from src.notifications.telegram import safe_send
                                result = safe_send(
                                    "scan_complete",
                                    severity="low",
                                    packets_count=2,
                                    trades_opened=0,
                                    trades_closed=0,
                                )
        assert result is True
        mock_conn.__exit__.assert_called_once()


class TestEscalatedEmailRedaction:
    def test_escalated_email_body_redacts_bot_token_in_payload(self):
        """Regression-lock: escalated email body must redact bot tokens in payload."""
        fake_token = "1234567890:AAAA-fake-token-do-not-leak"
        payload = {"telegram_url": f"https://api.telegram.org/bot{fake_token}/sendMessage"}
        captured_body = {"value": None}

        def mock_send_email(subject, body, **kwargs):
            captured_body["value"] = body
            return True

        with patch("src.notifications.telegram._do_dispatch", return_value=True):
            with patch("src.email.notifier.send_email", mock_send_email):
                from src.notifications.telegram import _do_dispatch_escalated
                _do_dispatch_escalated(
                    "manual_intervention_drift", payload, "critical", ["email"]
                )

        assert captured_body["value"] is not None, "send_email was not called"
        assert fake_token not in captured_body["value"], (
            f"Bot token leaked into email body: {captured_body['value'][:200]}"
        )
        assert "[REDACTED]" in captured_body["value"] or "REDACTED" in captured_body["value"]


class TestSafeSendNonNetworkPropagation:
    def test_safe_send_propagates_non_network_exceptions(self):
        """safe_send docstring: only network exceptions are caught.

        ImportError/NameError/AttributeError MUST propagate so import-time bugs
        surface at startup, not silently at runtime. Sprint 4 T2 incident.
        """
        cfg = _make_notif_config()
        now = _now_midday()

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg):
                with patch("src.notifications.telegram._now_et_for_safe_send", return_value=now):
                    with patch("src.notifications.telegram.notify_scan_complete",
                               side_effect=RuntimeError("code bug")):
                        from src.notifications.telegram import safe_send
                        with pytest.raises(RuntimeError, match="code bug"):
                            safe_send(
                                "scan_complete",
                                severity="high",
                                packets_count=1,
                                trades_opened=0,
                                trades_closed=0,
                            )

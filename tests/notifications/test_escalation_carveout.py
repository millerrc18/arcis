"""Regression tests for #115 DD-14 carve-out.

The escalation path in `_do_dispatch_escalated` must fire email IMMEDIATELY
(not via aggregator) because Telegram-down means email is the only operator
signal channel. This file locks the carve-out behavior:

  (a) Direct send_email call (no aggregator routing).
  (b) Distinguishable audit-row event_type='escalated_telegram_fail'.
  (c) Existing subject format preserved.
"""
from unittest.mock import patch, MagicMock


def test_escalation_calls_send_email_directly():
    """_do_dispatch_escalated must invoke send_email exactly once (no aggregator)."""
    with patch("src.email.notifier.send_email", return_value=True) as mock_send_email:
        from src.notifications.telegram import _do_dispatch_escalated
        _do_dispatch_escalated(
            event_type="manual_intervention_drift",
            payload={"drift_count": 3},
            severity="critical",
            channels=["email"],
        )
        assert mock_send_email.call_count == 1, (
            f"expected exactly one send_email call (no aggregator); got {mock_send_email.call_count}"
        )


def test_escalation_logs_with_event_type():
    """The audit row written for the escalated path must use event_type='escalated_telegram_fail', channel='email'."""
    with patch("src.email.notifier.send_email", return_value=True):
        with patch("src.notifications.telegram._write_notification_sent") as mock_write:
            from src.notifications.telegram import _do_dispatch_escalated
            _do_dispatch_escalated(
                event_type="manual_intervention_drift",
                payload={"drift_count": 3},
                severity="critical",
                channels=["email"],
            )

    # Find the call attributed to the escalation carve-out.
    matching_calls = [
        call for call in mock_write.call_args_list
        if call.kwargs.get("event_type") == "escalated_telegram_fail"
        and call.kwargs.get("channel") == "email"
    ]
    assert len(matching_calls) >= 1, (
        f"expected at least one _write_notification_sent with "
        f"event_type='escalated_telegram_fail' and channel='email'; "
        f"got calls: {mock_write.call_args_list}"
    )


def test_escalation_email_subject_starts_with_ESCALATED():
    """Existing subject format preserved: '[ESCALATED] {event_type}'."""
    captured = {"subject": None}

    def fake_send_email(subject, body, **kwargs):
        captured["subject"] = subject
        return True

    with patch("src.email.notifier.send_email", side_effect=fake_send_email):
        from src.notifications.telegram import _do_dispatch_escalated
        _do_dispatch_escalated(
            event_type="manual_intervention_drift",
            payload={"drift_count": 3},
            severity="critical",
            channels=["email"],
        )

    assert captured["subject"] is not None, "send_email was never called"
    assert captured["subject"].startswith("[ESCALATED] "), (
        f"expected subject to start with '[ESCALATED] '; got: {captured['subject']!r}"
    )

"""#115 T9 — Hybrid CRITICAL (enqueue + immediate) + ALERT queue-canonical.

Tests `src.evaluation.auditor.check_escalation` routing per spec Section 5.1
(DD-01 + DD-30 revised + DD-34).

CRITICAL severity: STEP 1 enqueues to `email:preopen:critical-overflow`
(canonical for digest replay — DD-34) THEN STEP 2 sends immediately as
today (24h-throttled). On ImportError of `enqueue_for_email_digest`
(catch ImportError/ModuleNotFoundError ONLY, NOT AssertionError —
DD-30 revised + DA-MIN-19): logger.critical FIREHOSE FALLBACK MODE,
best-effort `safe_send('system_event', ...)` Telegram, fall back to
immediate `send_email`.

ALERT severity: REPLACED with enqueue-only to `email:postclose`.
Throttle gate REMOVED for alert path (post-close digest aggregates within
day-window naturally — DD-34).

Sibling tests:
- tests/evaluation/test_audit_email_throttle.py (24h dedup throttle behavior)
"""

from unittest.mock import patch, MagicMock, call

import pytest

from src.evaluation.auditor import check_escalation
from src.journal.store import initialize_database


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    initialize_database(path)
    return path


def _audit(category=None, severity="critical"):
    """Build a single-flag audit. For critical severity we default to a
    `_NEVER_DOWNGRADE` category (risk_governor_breach) so bootcamp-mode
    downgrade does not interfere with the CRITICAL routing tests. Alert
    severity tests can use any category (no downgrade path)."""
    if category is None:
        category = "risk_governor_breach" if severity == "critical" else "drawdown"
    return {"flags": [{
        "severity": severity, "category": category,
        "description": f"{category} issue", "recommendation": "review",
    }]}


# ── CRITICAL severity (Hybrid: enqueue + immediate) ───────────────────────


def test_critical_calls_both_enqueue_and_send(db_path):
    """(a) Hybrid (DD-01): CRITICAL → enqueue FIRST, then send_email."""
    call_order: list[str] = []

    def _enq(*a, **kw):
        call_order.append("enqueue")
        return 1

    def _send(*a, **kw):
        call_order.append("send")
        return True

    with patch("src.notifications.email_digest.enqueue_for_email_digest", side_effect=_enq) as enq, \
         patch("src.email.notifier.send_email", side_effect=_send) as send:
        check_escalation(_audit(), db_path=db_path)

    assert enq.call_count == 1, f"enqueue called {enq.call_count} times, expected 1"
    assert send.call_count == 1, f"send_email called {send.call_count} times, expected 1"
    assert call_order == ["enqueue", "send"], (
        f"Expected enqueue BEFORE send (Step 1 then Step 2), got: {call_order}"
    )


def test_critical_enqueue_payload_includes_subject_and_body(db_path):
    """(b) DD-34: queue row payload has rendered subject + body so digest
    replay does not need to re-render."""
    with patch("src.notifications.email_digest.enqueue_for_email_digest", return_value=1) as enq, \
         patch("src.email.notifier.send_email", return_value=True):
        check_escalation(_audit(), db_path=db_path)  # default critical, _NEVER_DOWNGRADE cat

    assert enq.call_count == 1
    _, kwargs = enq.call_args
    # event_type is positional or kw — accept both
    args = enq.call_args.args
    event_type = args[0] if args else kwargs.get("event_type")
    assert event_type == "audit_critical"
    assert kwargs["severity"] == "critical"
    assert kwargs["source_tag"] == "email:preopen:critical-overflow"
    payload = kwargs["payload"]
    assert payload["category"] == "risk_governor_breach"
    assert payload["description"] == "risk_governor_breach issue"
    assert payload["recommendation"] == "review"
    assert "subject" in payload and payload["subject"]
    assert "body" in payload and payload["body"]
    assert "fired_immediately_at" in payload
    # subject + body must be the actual rendered email content
    assert "CRITICAL" in payload["subject"]
    assert "risk_governor_breach" in payload["body"]


def test_critical_throttled_still_enqueues(db_path):
    """(c) DD-34: queue row is canonical regardless of throttle. Throttle
    gates ONLY the immediate send_email."""
    with patch("src.notifications.email_digest.enqueue_for_email_digest", return_value=1) as enq, \
         patch("src.email.notifier.send_email", return_value=True) as send, \
         patch("src.evaluation.auditor._audit_email_throttled", return_value=True):
        check_escalation(_audit(), db_path=db_path)

    assert enq.call_count == 1, "Enqueue MUST still happen when immediate is throttled (DD-34)"
    assert send.call_count == 0, "Immediate send MUST be suppressed when throttle gate fires"


def test_critical_throttled_immediate_writes_notifications_sent_status_throttled_suppressed(db_path):
    """(d) When throttle gate fires, notifications_sent row reflects
    `status='throttled_suppressed'` to preserve audit trail."""
    import sqlite3

    with patch("src.notifications.email_digest.enqueue_for_email_digest", return_value=1), \
         patch("src.email.notifier.send_email", return_value=True), \
         patch("src.evaluation.auditor._audit_email_throttled", return_value=True):
        check_escalation(_audit(), db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event_type, channel, status FROM notifications_sent"
            " WHERE event_type = 'audit_critical'"
        ).fetchall()
    assert any(r[2] == "throttled_suppressed" for r in rows), (
        f"Expected notifications_sent row with status='throttled_suppressed', "
        f"got rows: {rows}"
    )


# ── ALERT severity (queue-canonical, no throttle) ────────────────────────


def test_alert_calls_enqueue_only(db_path):
    """(e) ALERT → enqueue only. Immediate send_email NOT called."""
    with patch("src.notifications.email_digest.enqueue_for_email_digest", return_value=1) as enq, \
         patch("src.email.notifier.send_email", return_value=True) as send:
        check_escalation(_audit(severity="alert"), db_path=db_path)

    assert enq.call_count == 1
    assert send.call_count == 0, (
        "send_email MUST NOT fire for alert severity — postclose digest "
        "aggregates within day-window naturally (DD-34)"
    )


def test_alert_payload_includes_category(db_path):
    """(f) Alert payload includes category + description + recommendation."""
    with patch("src.notifications.email_digest.enqueue_for_email_digest", return_value=1) as enq, \
         patch("src.email.notifier.send_email", return_value=True):
        check_escalation(_audit(category="rubric_drift", severity="alert"), db_path=db_path)

    assert enq.call_count == 1
    args = enq.call_args.args
    kwargs = enq.call_args.kwargs
    event_type = args[0] if args else kwargs.get("event_type")
    assert event_type == "audit_alert"
    assert kwargs["severity"] == "alert"
    assert kwargs["source_tag"] == "email:postclose"
    payload = kwargs["payload"]
    assert payload["category"] == "rubric_drift"
    assert payload["description"] == "rubric_drift issue"
    assert payload["recommendation"] == "review"


def test_alert_throttle_gate_removed(db_path):
    """(g) DD-34: alerts NO LONGER consult the throttle gate. Multiple alerts
    for the same category all enqueue (post-close digest aggregates within
    day-window naturally)."""
    with patch("src.notifications.email_digest.enqueue_for_email_digest", return_value=1) as enq, \
         patch("src.email.notifier.send_email", return_value=True), \
         patch("src.evaluation.auditor._audit_email_throttled", return_value=True) as throttled:
        check_escalation(_audit(severity="alert"), db_path=db_path)
        check_escalation(_audit(severity="alert"), db_path=db_path)
        check_escalation(_audit(severity="alert"), db_path=db_path)

    assert enq.call_count == 3, (
        f"All 3 alerts must enqueue (no throttle gate); got {enq.call_count}"
    )
    # Throttle gate function must NOT be consulted on alert path
    assert throttled.call_count == 0, (
        f"_audit_email_throttled must NOT be called on alert path (DD-34); "
        f"got {throttled.call_count} calls"
    )


# ── CRITICAL ImportError fallback (DD-30 revised) ────────────────────────


def test_critical_fallback_when_aggregator_importerror(db_path):
    """(h) DD-30 revised: if enqueue raises ImportError, log CRITICAL with
    'FIREHOSE FALLBACK MODE' marker, fire best-effort `safe_send`
    Telegram alert, AND continue to immediate send_email."""

    def _enq_raises(*a, **kw):
        raise ImportError("simulated partial deploy — module missing")

    with patch("src.notifications.email_digest.enqueue_for_email_digest", side_effect=_enq_raises), \
         patch("src.email.notifier.send_email", return_value=True) as send, \
         patch("src.notifications.telegram.safe_send", return_value=True) as ss, \
         patch("src.evaluation.auditor.logger") as mock_log:
        check_escalation(_audit(), db_path=db_path)

    # send_email must still fire (fallback to immediate)
    assert send.call_count == 1, (
        f"Fallback send_email must fire when enqueue ImportErrors; got {send.call_count}"
    )
    # logger.critical must include FIREHOSE FALLBACK MODE marker
    critical_calls = [
        c for c in mock_log.critical.call_args_list
        if "FIREHOSE FALLBACK MODE" in (c.args[0] if c.args else "")
    ]
    assert critical_calls, (
        f"Expected logger.critical with 'FIREHOSE FALLBACK MODE'; "
        f"got critical calls: {mock_log.critical.call_args_list}"
    )
    # best-effort safe_send Telegram alert with system_event
    assert ss.call_count >= 1, (
        f"Expected best-effort safe_send Telegram alert; got {ss.call_count}"
    )
    # first positional arg is event_type
    safe_send_first_arg = ss.call_args_list[0].args[0] if ss.call_args_list[0].args else None
    assert safe_send_first_arg == "system_event", (
        f"Expected safe_send('system_event', ...), got {safe_send_first_arg!r}"
    )


def test_critical_assertionerror_propagates(db_path):
    """(i) DA-MIN-19: AssertionError must NOT be swallowed by the
    ImportError/ModuleNotFoundError handler. It propagates so a real
    coverage gap surfaces loudly."""

    def _enq_raises_assertion(*a, **kw):
        raise AssertionError("simulated module-load drift — DD-30 boundary")

    with patch("src.notifications.email_digest.enqueue_for_email_digest", side_effect=_enq_raises_assertion), \
         patch("src.email.notifier.send_email", return_value=True), \
         patch("src.notifications.telegram.safe_send", return_value=True):
        with pytest.raises(AssertionError):
            check_escalation(_audit(), db_path=db_path)

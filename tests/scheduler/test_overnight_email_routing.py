"""Tests for #115 T10 — overnight.py daily-audit + Saturday-reports email routing.

DD-20 revised: in shadow / time_aligned mode, the original send_email
(operator inbox) must continue to fire alongside the queue enqueue. Only
in mode='off' does the queue become the sole consumer.

DD-30 revised: aggregator import failure surfaces as ImportError (NOT
AssertionError) so the caller's try/except catches it. The fallback is
FIREHOSE MODE — log CRITICAL, best-effort Telegram alert, then revert
to immediate send_email so operator visibility is never lost.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_audit(assessment: str = "green") -> dict:
    return {
        "overall_assessment": assessment,
        "summary": "test summary",
        "audit_date": "2026-05-26",
        "audit_id": 42,
    }


def _shadow_config(mode: str = "shadow") -> dict:
    return {"email": {"dual_write_hold_over": {"mode": mode}}}


# ── run_daily_audit RED → enqueue + dual-write ──────────────────────────


def test_daily_audit_red_enqueues_to_postclose():
    """RED assessment routes to email_digest under postclose tier."""
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("off")), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value=_make_audit("red")), \
         patch("src.evaluation.auditor.check_escalation",
               return_value=[]), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send:
        overnight.run_daily_audit()

    # Queue MUST receive the RED assessment under postclose tier.
    assert mock_enq.call_count == 1
    call = mock_enq.call_args
    assert call.args[0] == "audit_red_assessment"
    assert call.kwargs.get("severity") == "alert"
    assert call.kwargs.get("source_tag") == "email:postclose"
    payload = call.kwargs.get("payload") or {}
    assert payload.get("assessment") == "red"
    assert payload.get("summary") == "test summary"
    assert payload.get("audit_date") == "2026-05-26"
    assert payload.get("audit_id") == 42
    # mode='off' → only enqueue, no immediate send.
    assert mock_send.call_count == 0


def test_daily_audit_green_no_email():
    """GREEN assessment → neither enqueue nor send_email called for assessment."""
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("shadow")), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value=_make_audit("green")), \
         patch("src.evaluation.auditor.check_escalation",
               return_value=[]), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send:
        overnight.run_daily_audit()

    assert mock_enq.call_count == 0
    assert mock_send.call_count == 0


def test_daily_audit_yellow_no_email():
    """YELLOW assessment → no email path; logger.info only (operator-memory contract)."""
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("shadow")), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value=_make_audit("yellow")), \
         patch("src.evaluation.auditor.check_escalation",
               return_value=[]), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send:
        overnight.run_daily_audit()

    assert mock_enq.call_count == 0
    assert mock_send.call_count == 0


# ── run_saturday_reports — training + CTO → weekly tier ─────────────────


def test_saturday_training_enqueues_to_weekly():
    """Saturday training report enqueues under saturday_training_report / weekly."""
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("off")), \
         patch("src.training.report.generate_training_report",
               return_value="Training report body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.training.versioning.get_active_model_name",
               return_value="m1"), \
         patch("src.training.versioning.get_training_example_counts",
               return_value={"total": 0}), \
         patch("src.scheduler.overnight.safe_send"), \
         patch("src.scheduler.overnight.connect_db"), \
         patch("src.evaluation.auditor.run_weekly_audit",
               return_value={"overall_assessment": "green"}), \
         patch("src.evaluation.cto_report.generate_cto_report",
               return_value={"report_period": {"start": "2026-05-19",
                                                "end": "2026-05-26"}}), \
         patch("src.evaluation.cto_report.format_cto_report",
               return_value="CTO body"):
        overnight.run_saturday_reports()

    # Inspect calls for the saturday_training_report event.
    types_seen = [c.args[0] for c in mock_enq.call_args_list]
    assert "saturday_training_report" in types_seen
    training_call = [
        c for c in mock_enq.call_args_list
        if c.args[0] == "saturday_training_report"
    ][0]
    assert training_call.kwargs.get("severity") == "normal"
    assert training_call.kwargs.get("source_tag") == "email:weekly"
    payload = training_call.kwargs.get("payload") or {}
    assert payload.get("subject") == "[TRADE DESK] Weekly Training Report"
    assert payload.get("body") == "Training report body"
    assert "report_date" in payload


def test_saturday_cto_enqueues_to_weekly():
    """Saturday CTO report enqueues under saturday_cto_report / weekly."""
    from src.scheduler import overnight

    cto_data = {"report_period": {"start": "2026-05-19", "end": "2026-05-26"}}
    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("off")), \
         patch("src.training.report.generate_training_report",
               return_value="Training body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.training.versioning.get_active_model_name",
               return_value="m1"), \
         patch("src.training.versioning.get_training_example_counts",
               return_value={"total": 0}), \
         patch("src.scheduler.overnight.safe_send"), \
         patch("src.scheduler.overnight.connect_db"), \
         patch("src.evaluation.auditor.run_weekly_audit",
               return_value={"overall_assessment": "green"}), \
         patch("src.evaluation.cto_report.generate_cto_report",
               return_value=cto_data), \
         patch("src.evaluation.cto_report.format_cto_report",
               return_value="CTO formatted body"):
        overnight.run_saturday_reports()

    types_seen = [c.args[0] for c in mock_enq.call_args_list]
    assert "saturday_cto_report" in types_seen
    cto_call = [
        c for c in mock_enq.call_args_list
        if c.args[0] == "saturday_cto_report"
    ][0]
    assert cto_call.kwargs.get("severity") == "normal"
    assert cto_call.kwargs.get("source_tag") == "email:weekly"
    payload = cto_call.kwargs.get("payload") or {}
    assert "CTO Performance Report" in payload.get("subject", "")
    assert payload.get("body") == "CTO formatted body"
    assert "report_date" in payload


# ── DD-20 REVISED — dual-write in shadow / time_aligned ─────────────────


def test_shadow_mode_saturday_also_fires_immediate_send():
    """DA-CRIT-1: in mode='shadow', enqueue AND immediate send_email fire.

    Operator inbox MUST stay populated during the hold-over period — we
    only stop calling send_email when mode='off'.
    """
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("shadow")), \
         patch("src.training.report.generate_training_report",
               return_value="Training body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.training.versioning.get_active_model_name",
               return_value="m1"), \
         patch("src.training.versioning.get_training_example_counts",
               return_value={"total": 0}), \
         patch("src.scheduler.overnight.safe_send"), \
         patch("src.scheduler.overnight.connect_db"), \
         patch("src.evaluation.auditor.run_weekly_audit",
               return_value={"overall_assessment": "green"}), \
         patch("src.evaluation.cto_report.generate_cto_report",
               return_value={"report_period": {"start": "2026-05-19",
                                                "end": "2026-05-26"}}), \
         patch("src.evaluation.cto_report.format_cto_report",
               return_value="CTO body"):
        overnight.run_saturday_reports()

    # Both reports route to queue (2 enqueues) AND both also fire immediate send_email.
    assert mock_enq.call_count == 2
    # send_email called for both training and CTO during shadow mode.
    assert mock_send.call_count == 2


def test_off_mode_saturday_only_enqueues():
    """In mode='off', send_email is NOT called — queue is sole consumer."""
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("off")), \
         patch("src.training.report.generate_training_report",
               return_value="Training body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enq, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.training.versioning.get_active_model_name",
               return_value="m1"), \
         patch("src.training.versioning.get_training_example_counts",
               return_value={"total": 0}), \
         patch("src.scheduler.overnight.safe_send"), \
         patch("src.scheduler.overnight.connect_db"), \
         patch("src.evaluation.auditor.run_weekly_audit",
               return_value={"overall_assessment": "green"}), \
         patch("src.evaluation.cto_report.generate_cto_report",
               return_value={"report_period": {"start": "2026-05-19",
                                                "end": "2026-05-26"}}), \
         patch("src.evaluation.cto_report.format_cto_report",
               return_value="CTO body"):
        overnight.run_saturday_reports()

    assert mock_enq.call_count == 2
    assert mock_send.call_count == 0


# ── DD-30 REVISED — ImportError fallback (firehose mode) ─────────────────


def test_aggregator_importerror_falls_back_with_critical_log(caplog):
    """If email_digest import fails, log CRITICAL, best-effort Telegram, then send_email.

    DD-30 revised: catch (ImportError, ModuleNotFoundError) only — NOT
    AssertionError. A real render-time assertion bug MUST surface, not be
    silenced by a routing fallback.
    """
    import builtins
    import logging
    from src.scheduler import overnight

    real_import = builtins.__import__

    def _raise_on_email_digest(name, *args, **kwargs):
        if name == "src.notifications.email_digest" or name.endswith("email_digest"):
            raise ImportError("simulated import failure")
        return real_import(name, *args, **kwargs)

    with caplog.at_level(logging.CRITICAL, logger="src.scheduler.overnight"), \
         patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("off")), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value=_make_audit("red")), \
         patch("src.evaluation.auditor.check_escalation",
               return_value=[]), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"), \
         patch("src.scheduler.overnight.safe_send") as mock_tg, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch.object(builtins, "__import__", side_effect=_raise_on_email_digest):
        overnight.run_daily_audit()

    # CRITICAL log must be emitted naming firehose fallback.
    critical_msgs = [r.message for r in caplog.records
                     if r.levelno == logging.CRITICAL]
    assert any("FIREHOSE" in m or "firehose" in m.lower() for m in critical_msgs), \
        f"Expected FIREHOSE FALLBACK CRITICAL log; got: {critical_msgs}"
    # Telegram alert is best-effort — should be attempted.
    assert mock_tg.call_count >= 1
    # send_email is the fallback path — operator must still see the alert.
    assert mock_send.call_count == 1


def test_aggregator_assertionerror_propagates_DA_MIN_19():
    """DA-MIN-19: AssertionError from email_digest MUST propagate.

    The try/except catches ImportError only. A genuine render-time
    assertion bug must surface to the caller, not be silenced behind
    firehose fallback.
    """
    from src.scheduler import overnight

    with patch("src.scheduler.overnight.load_config", create=True,
               return_value=_shadow_config("off")), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value=_make_audit("red")), \
         patch("src.evaluation.auditor.check_escalation",
               return_value=[]), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest",
               side_effect=AssertionError("rendering bug")), \
         patch("src.email.notifier.send_email"):
        with pytest.raises(AssertionError, match="rendering bug"):
            overnight.run_daily_audit()

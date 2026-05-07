"""Regression tests for overnight.py alarm notification paths.

T2 — Group A.1: Locks in the 4 alarm paths that were silently broken because
send_telegram_message (non-existent) was called instead of send_telegram.
The try/except Exception blocks swallowed the NameError, so the operator
never received CUSUM, leakage, or model-regression alerts.
"""
from unittest.mock import MagicMock, patch


def test_cusum_alarm_invokes_send_telegram():
    """CUSUM alarm path calls send_telegram with CUSUM ALARM in body."""
    mock_change = {"alarm": True, "direction": "negative", "detail": "shift detected"}
    mock_send = MagicMock(return_value=True)

    with patch("src.evaluation.change_detector.check_performance_drift",
               return_value=mock_change), \
         patch("src.notifications.telegram.send_telegram", mock_send), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value={"overall_assessment": "green", "summary": "ok"}), \
         patch("src.evaluation.auditor.check_escalation", return_value=[]), \
         patch("src.email.notifier.send_email"), \
         patch("src.training.leakage_detector.run_leakage_check",
               return_value={"balanced_accuracy": 0.50}, create=True), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"):

        from src.scheduler import overnight
        overnight.run_daily_audit()

    mock_send.assert_called_once()
    body = mock_send.call_args[0][0]
    assert "CUSUM ALARM" in body


def test_leakage_alert_invokes_send_telegram():
    """Leakage alert path calls send_telegram with LEAKAGE ALERT in body."""
    mock_send = MagicMock(return_value=True)

    with patch("src.evaluation.change_detector.check_performance_drift",
               return_value={"alarm": False}), \
         patch("src.notifications.telegram.send_telegram", mock_send), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value={"overall_assessment": "green", "summary": "ok"}), \
         patch("src.evaluation.auditor.check_escalation", return_value=[]), \
         patch("src.email.notifier.send_email"), \
         patch("src.training.leakage_detector.run_leakage_check",
               return_value={"balanced_accuracy": 0.70}, create=True), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"):

        from src.scheduler import overnight
        overnight.run_daily_audit()

    mock_send.assert_called_once()
    body = mock_send.call_args[0][0]
    assert "LEAKAGE ALERT" in body


def test_model_regression_critical_invokes_send_telegram():
    """Critical regression path calls send_telegram with MODEL REGRESSION CRITICAL in body."""
    mock_result = {"status": "critical", "message": "new model is 15% worse"}
    mock_send = MagicMock(return_value=True)

    with patch("src.evaluation.model_monitor.check_model_regression",
               return_value=mock_result), \
         patch("src.notifications.telegram.send_telegram", mock_send):

        from src.scheduler import overnight
        overnight.run_model_regression_check()

    mock_send.assert_called_once()
    body = mock_send.call_args[0][0]
    assert "MODEL REGRESSION CRITICAL" in body


def test_model_regression_warning_invokes_send_telegram():
    """Warning regression path calls send_telegram with regression warning in body."""
    mock_result = {"status": "warning", "message": "new model is 5% worse"}
    mock_send = MagicMock(return_value=True)

    with patch("src.evaluation.model_monitor.check_model_regression",
               return_value=mock_result), \
         patch("src.notifications.telegram.send_telegram", mock_send):

        from src.scheduler import overnight
        overnight.run_model_regression_check()

    mock_send.assert_called_once()
    body = mock_send.call_args[0][0]
    assert "regression warning" in body.lower()


def test_cusum_path_uses_check_performance_drift():
    """Regression lock: CUSUM path imports check_performance_drift (not the old
    detect_performance_change name) AND calls send_telegram on alarm=True."""
    mock_change = {"alarm": True, "direction": "negative", "detail": "drift detected"}
    mock_drift = MagicMock(return_value=mock_change)
    mock_send = MagicMock(return_value=True)

    with patch("src.evaluation.change_detector.check_performance_drift", mock_drift), \
         patch("src.notifications.telegram.send_telegram", mock_send), \
         patch("src.evaluation.auditor.run_daily_audit",
               return_value={"overall_assessment": "green", "summary": "ok"}), \
         patch("src.evaluation.auditor.check_escalation", return_value=[]), \
         patch("src.email.notifier.send_email"), \
         patch("src.training.leakage_detector.run_leakage_check",
               return_value={"balanced_accuracy": 0.50}, create=True), \
         patch("src.shadow_trading.exit_reconciliation.run_exit_reconciliation"):

        from src.scheduler import overnight
        overnight.run_daily_audit()

    mock_drift.assert_called_once()
    mock_send.assert_called_once()
    body = mock_send.call_args[0][0]
    assert "CUSUM ALARM" in body


def test_no_send_telegram_message_references():
    """Sibling-search assertion: zero send_telegram_message call sites in src/ and scripts/.

    Excludes the test file itself to avoid false positives from docstrings/pattern literals.
    """
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).parents[2]
    this_file = pathlib.Path(__file__).resolve()
    pattern = re.compile(r"send_telegram_message")
    search_dirs = ["src", "scripts"]
    matches = []
    for search_dir in search_dirs:
        target = repo_root / search_dir
        if not target.is_dir():
            continue
        for path in target.rglob("*.py"):
            if path.resolve() == this_file:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    matches.append(f"{path}:{lineno}: {line.strip()}")
    assert matches == [], (
        f"Found {len(matches)} remaining send_telegram_message reference(s):\n"
        + "\n".join(matches)
    )

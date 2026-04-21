"""Sprint 2 H4 — regression tests for governor-disabled alert.

Without this alert, a config mistake (risk_governor.enabled=False)
silently approves every trade — bypassing all 8 risk checks — with
only an INFO-level log trail.

Fix: when `assess_trade` fires with `self.enabled=False`, emit exactly
one `logger.critical` + one `send_telegram` per process lifetime.
Subsequent rejections are no-ops (idempotency via module-level
sentinel).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_sentinel():
    """Each test starts with the sentinel reset."""
    from src.risk import governor
    governor._governor_disabled_alerted = False
    yield
    governor._governor_disabled_alerted = False


def test_warn_once_emits_critical_log_and_telegram():
    from src.risk import governor
    with patch.object(governor.logger, "critical") as mock_crit, patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_tg, patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ):
        governor._warn_governor_disabled_once()
    mock_crit.assert_called_once()
    mock_tg.assert_called_once()
    # Critical message must mention the config key to edit
    crit_msg = mock_crit.call_args[0][0]
    assert "DISABLED" in crit_msg
    assert "risk_governor.enabled" in crit_msg


def test_warn_once_is_idempotent_within_process():
    """Two calls emit exactly once: the first. Sentinel prevents re-emission."""
    from src.risk import governor
    with patch.object(governor.logger, "critical") as mock_crit, patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_tg, patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ):
        governor._warn_governor_disabled_once()
        governor._warn_governor_disabled_once()
        governor._warn_governor_disabled_once()
    assert mock_crit.call_count == 1, "critical must fire only on first call"
    assert mock_tg.call_count == 1, "telegram must fire only on first call"


def test_warn_once_skips_telegram_when_disabled():
    """If Telegram isn't enabled, critical still fires but telegram doesn't."""
    from src.risk import governor
    with patch.object(governor.logger, "critical") as mock_crit, patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_tg, patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=False,
    ):
        governor._warn_governor_disabled_once()
    mock_crit.assert_called_once()
    mock_tg.assert_not_called()


def test_warn_once_tolerates_telegram_error():
    """If telegram send raises, critical still fires and nothing propagates."""
    from src.risk import governor
    with patch.object(governor.logger, "critical") as mock_crit, patch.object(
        governor.logger, "warning",
    ) as mock_warn, patch(
        "src.notifications.telegram.send_telegram",
        side_effect=ConnectionError("telegram down"),
    ), patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ):
        governor._warn_governor_disabled_once()  # must not raise
    mock_crit.assert_called_once()
    # Telegram failure logged at warning level
    mock_warn.assert_called_once()


def test_check_trade_fires_alert_when_governor_disabled():
    """End-to-end: creating a disabled governor and calling check_trade
    triggers the alert exactly once across multiple invocations."""
    from src.risk import governor

    # Build a minimal governor with enabled=False (bypasses __init__)
    gov = governor.RiskGovernor.__new__(governor.RiskGovernor)
    gov.enabled = False

    with patch.object(governor.logger, "critical") as mock_crit, patch(
        "src.notifications.telegram.send_telegram", return_value=True,
    ) as mock_tg, patch(
        "src.notifications.telegram.is_telegram_enabled", return_value=True,
    ):
        # Call check_trade three times — each should take the disabled
        # branch and return approved=True, but the alert fires once.
        r1 = gov.check_trade(
            ticker="FOO", allocation_dollars=1000.0,
            features={}, portfolio={},
        )
        r2 = gov.check_trade(
            ticker="BAR", allocation_dollars=2000.0,
            features={}, portfolio={},
        )
        r3 = gov.check_trade(
            ticker="BAZ", allocation_dollars=3000.0,
            features={}, portfolio={},
        )
    for r in (r1, r2, r3):
        assert r["approved"] is True
        assert r["checks"][0]["name"] == "governor_disabled"
    assert mock_crit.call_count == 1
    assert mock_tg.call_count == 1

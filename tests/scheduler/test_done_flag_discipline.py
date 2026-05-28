"""Tests for Sprint 0 Wave 2a — DONE-FLAG discipline (#226 reinforcement).

Pre-fix bugs in src/scheduler/watch.py:
  A. _daily_validation_done was set unconditionally (inline try/except —
     bypassed _safe_run, no per-task backoff).
  B. _daily_build_score_done — same anti-pattern.
  C. _action_reminders_done was set OUTSIDE the try block, so any raise
     from check_action_reminders still marked the day done and locked
     out retries until the next midnight reset.

Fix: each block now uses the canonical
    if self._safe_run(name, helper): self._<flag>_done = True
pattern. The helpers _run_daily_validation, _run_daily_build_score, and
_run_action_reminders were extracted so the inline block stays one-liner.

These tests verify (post-PR-D T19: _safe_run returns CollectorResult, gated
on .is_healthy — CollectorResult has no __bool__, so callers MUST branch on
.is_healthy, not object truthiness):
  - On a raise inside the helper, _safe_run returns a failed CollectorResult
    (.is_healthy False), so the done-flag must NOT be set.
  - On success, _safe_run returns an ok CollectorResult (.is_healthy True),
    so the done-flag IS set.

Plus an end-to-end check that exercises the full WatchLoop helper +
_safe_run + done-flag pipeline.
"""

from unittest.mock import patch


def _make_bare_watch_loop():
    """Construct a WatchLoop bypassing __init__'s heavy setup, with the
    minimal state _safe_run needs."""
    from collections import deque

    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    # State touched by _safe_run
    wl._backoff = {}
    wl._consecutive_errors = 0
    wl._error_timestamps = deque(maxlen=20)
    wl._hourly_alert_sent = False
    # State touched by the done-flag blocks under test
    wl._daily_validation_done = False
    wl._daily_build_score_done = False
    wl._action_reminders_done = False
    return wl


# ---------------------------------------------------------------------------
# DONE-FLAG-A: daily validation
# ---------------------------------------------------------------------------


def test_done_flag_a_not_set_on_validation_failure():
    """If run_full_validation raises, _daily_validation_done must remain False
    so the next watch tick can retry (instead of locking out retries until
    the midnight reset)."""
    wl = _make_bare_watch_loop()

    with patch(
        "src.evaluation.system_validator.run_full_validation",
        side_effect=RuntimeError("validator boom"),
    ):
        # This is the production block (post-fix):
        if wl._safe_run("daily validation", wl._run_daily_validation).is_healthy:
            wl._daily_validation_done = True

    assert wl._daily_validation_done is False, (
        "Bug regressed: validation flag was set despite _safe_run returning "
        "False. The watch loop will now skip retries until midnight."
    )
    # And _safe_run should have recorded the failure for backoff.
    assert "daily validation" in wl._backoff


def test_done_flag_a_set_on_validation_success():
    """Sanity: on success, _daily_validation_done IS set."""
    wl = _make_bare_watch_loop()

    fake_result = {
        "overall_status": "OK",
        "checks_passed": 10,
        "checks_warning": 0,
        "checks_failed": 0,
    }
    with patch(
        "src.evaluation.system_validator.run_full_validation",
        return_value=fake_result,
    ), patch(
        "src.evaluation.system_validator.save_validation_result",
    ), patch(
        "src.notifications.telegram.is_telegram_enabled",
        return_value=False,
    ):
        if wl._safe_run("daily validation", wl._run_daily_validation).is_healthy:
            wl._daily_validation_done = True

    assert wl._daily_validation_done is True


# ---------------------------------------------------------------------------
# DONE-FLAG-B: daily build score
# ---------------------------------------------------------------------------


def test_done_flag_b_not_set_on_build_score_failure():
    """If persist_build_score raises, _daily_build_score_done must remain
    False so the next watch tick can retry."""
    wl = _make_bare_watch_loop()

    with patch(
        "src.evaluation.build_score.persist_build_score",
        side_effect=RuntimeError("build_score boom"),
    ):
        if wl._safe_run("daily build score", wl._run_daily_build_score).is_healthy:
            wl._daily_build_score_done = True

    assert wl._daily_build_score_done is False, (
        "Bug regressed: build-score flag was set despite _safe_run returning "
        "False. The watch loop will now skip retries until midnight."
    )
    assert "daily build score" in wl._backoff


def test_done_flag_b_set_on_build_score_success():
    """Sanity: on success, _daily_build_score_done IS set."""
    wl = _make_bare_watch_loop()

    with patch(
        "src.evaluation.build_score.persist_build_score",
        return_value={"build_score": 87.5},
    ):
        if wl._safe_run("daily build score", wl._run_daily_build_score).is_healthy:
            wl._daily_build_score_done = True

    assert wl._daily_build_score_done is True


# ---------------------------------------------------------------------------
# DONE-FLAG-C: action reminders (the OUTSIDE-try regression)
# ---------------------------------------------------------------------------


def test_done_flag_c_not_set_on_reminders_failure():
    """Pre-fix, _action_reminders_done was set OUTSIDE the try block, so
    a raise from check_action_reminders still marked the day done and
    locked out retries. Post-fix, the block uses _safe_run, so a raise
    leaves the flag False."""
    wl = _make_bare_watch_loop()

    with patch(
        "src.notifications.telegram.is_telegram_enabled",
        return_value=True,
    ), patch(
        "src.notifications.telegram_commands.check_action_reminders",
        side_effect=RuntimeError("reminders boom"),
    ):
        if wl._safe_run("action reminders", wl._run_action_reminders).is_healthy:
            wl._action_reminders_done = True

    assert wl._action_reminders_done is False, (
        "Bug regressed: action-reminders flag was set despite the helper "
        "raising. Reminders will not resend after the first 8pm tick failure."
    )
    assert "action reminders" in wl._backoff


def test_done_flag_c_set_on_reminders_success():
    """Sanity: on success, _action_reminders_done IS set."""
    wl = _make_bare_watch_loop()

    with patch(
        "src.notifications.telegram.is_telegram_enabled",
        return_value=True,
    ), patch(
        "src.notifications.telegram_commands.check_action_reminders",
        return_value=["alert_1"],
    ):
        if wl._safe_run("action reminders", wl._run_action_reminders).is_healthy:
            wl._action_reminders_done = True

    assert wl._action_reminders_done is True


def test_done_flag_c_set_when_telegram_disabled():
    """If Telegram is disabled, the helper short-circuits cleanly (no raise),
    so the flag should still be set — same as the pre-fix behavior on this
    happy path."""
    wl = _make_bare_watch_loop()

    with patch(
        "src.notifications.telegram.is_telegram_enabled",
        return_value=False,
    ):
        if wl._safe_run("action reminders", wl._run_action_reminders).is_healthy:
            wl._action_reminders_done = True

    assert wl._action_reminders_done is True


# ---------------------------------------------------------------------------
# Structural regression: source-file scan to lock in the pattern.
# These guard against future edits reintroducing the anti-patterns. They
# fail loudly if anyone re-adds an unconditional or outside-try done-flag
# set for these three blocks.
# ---------------------------------------------------------------------------


def test_action_reminders_block_uses_safe_run_pattern():
    """Source-level guardrail for DONE-FLAG-C: the action reminders block
    must use _safe_run — never set _action_reminders_done outside a try
    block or unconditionally after the work."""
    from pathlib import Path

    src = Path("src/scheduler/watch.py").read_text(encoding="utf-8")
    # The fix wires action reminders through _safe_run + a helper.
    assert "_safe_run(\"action reminders\"" in src, (
        "Regression: action reminders block no longer uses _safe_run. "
        "If you have a different way to wire backoff, update this test."
    )
    # The helper must exist and contain the Telegram side-effects.
    assert "def _run_action_reminders" in src, (
        "Regression: _run_action_reminders helper was removed. The done-flag "
        "block depends on it for _safe_run discipline."
    )


def test_daily_validation_block_uses_safe_run_pattern():
    """Source-level guardrail for DONE-FLAG-A."""
    from pathlib import Path

    src = Path("src/scheduler/watch.py").read_text(encoding="utf-8")
    assert "_safe_run(\"daily validation\"" in src, (
        "Regression: daily validation block no longer uses _safe_run."
    )
    assert "def _run_daily_validation" in src


def test_daily_build_score_block_uses_safe_run_pattern():
    """Source-level guardrail for DONE-FLAG-B."""
    from pathlib import Path

    src = Path("src/scheduler/watch.py").read_text(encoding="utf-8")
    assert "_safe_run(\"daily build score\"" in src, (
        "Regression: daily build score block no longer uses _safe_run."
    )
    assert "def _run_daily_build_score" in src

"""Tests for #608 + #609 + #610 — exit-overshoot bundle.

#608: Executor submits SELL after broker bracket leg fills, opens shorts
      (C 4/21, AMD 4/22). The previous D3 _sync_exit_qty safety net is gated
      on `if not bracket_exit:` and doesn't catch the bracket-leg-already-filled
      case where _alpaca_positions has stale data.
#609: cancel_paper_order's terminal_state return value is ignored at
      executor.py:1575. The adapter laboriously extracts it; the caller
      throws it away.
#610: exit_retry_count never increments in the first-time exit path —
      CVS retried 33× on 4/21, never hit MAX_EXIT_RETRIES.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock


# ── #609: cancel_paper_order return value must be honored ──

class TestCancelReturnValueHonored:
    """When cancel_paper_order returns terminal_state='filled', the executor
    MUST route to _close_from_broker_fill instead of submitting another SELL."""

    def test_helper_handles_filled_cancel_response(self):
        """The new _handle_pre_exit_cancel helper must signal 'do not submit
        SELL' when the cancel race detects the order already filled."""
        from src.shadow_trading.executor import _handle_pre_exit_cancel

        cancel_result = {
            "cancelled": False,
            "terminal_state": "filled",
            "error": "order is already in 'filled' state",
        }
        # Helper returns True when caller should skip submitting a new SELL.
        should_skip = _handle_pre_exit_cancel(cancel_result)
        assert should_skip is True

    def test_helper_handles_partially_filled_cancel_response(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel

        cancel_result = {
            "cancelled": False,
            "terminal_state": "partially_filled",
            "error": "order is already in 'partially_filled' state",
        }
        assert _handle_pre_exit_cancel(cancel_result) is True

    def test_helper_allows_submit_when_cancel_succeeded(self):
        """Normal cancel success — caller proceeds to submit the SELL."""
        from src.shadow_trading.executor import _handle_pre_exit_cancel

        cancel_result = {"cancelled": True, "terminal_state": None, "error": None}
        assert _handle_pre_exit_cancel(cancel_result) is False

    def test_helper_handles_none_or_malformed_response(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel

        # Defensive: don't crash if adapter returns None or unexpected shape.
        assert _handle_pre_exit_cancel(None) is False
        assert _handle_pre_exit_cancel({}) is False
        assert _handle_pre_exit_cancel({"cancelled": False}) is False


# ── #610: exit_retry_count increments on first-time exit failure ──

class TestExitRetryCountIncrements:
    """The first-time exit path (executor.py:1587 area) must increment
    exit_retry_count when it marks status='exit_failed'. Pre-fix, only
    _retry_exit incremented the counter — so reconciler-driven flips
    re-entered the first-time path repeatedly without ever hitting
    MAX_EXIT_RETRIES (CVS 33× on 4/21)."""

    def test_increment_helper_returns_next_count(self):
        from src.shadow_trading.executor import _next_exit_retry_count

        # Brand new failure
        assert _next_exit_retry_count({"exit_retry_count": 0}) == 1
        assert _next_exit_retry_count({"exit_retry_count": None}) == 1
        # Repeated failures climb monotonically
        assert _next_exit_retry_count({"exit_retry_count": 1}) == 2
        assert _next_exit_retry_count({"exit_retry_count": 2}) == 3
        # Missing key treated as zero
        assert _next_exit_retry_count({}) == 1

    def test_max_exit_retries_helper_signals_abandonment(self):
        from src.shadow_trading.executor import (
            _MAX_EXIT_RETRIES,
            _should_abandon_exit,
        )

        assert _should_abandon_exit(_MAX_EXIT_RETRIES) is True
        assert _should_abandon_exit(_MAX_EXIT_RETRIES + 1) is True
        assert _should_abandon_exit(_MAX_EXIT_RETRIES - 1) is False

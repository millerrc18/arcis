"""Unit-test coverage for helpers added in PR #634 that lacked direct tests.

PR #634 introduced several extracted helpers as part of the silent-failure /
exit-overshoot work. They were exercised end-to-end through the executor +
reconcile suites but had no dedicated unit tests. This file backfills those
tests so individual behaviors can be regressed without spinning up the full
trade lifecycle.

Helpers covered:
  - shadow_trading.executor._handle_pre_exit_cancel
  - shadow_trading.executor._next_exit_retry_count
  - shadow_trading.executor._should_abandon_exit
  - shadow_trading.reconcile._resolve_stuck_pnl
  - scheduler.watch._is_likely_sleep_gap
  - training.data_collector.CollectionResult.is_silent_failure
  - api.local_auth.verify_local_token
"""

from __future__ import annotations

import os

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# shadow_trading.executor._handle_pre_exit_cancel
# ─────────────────────────────────────────────────────────────────────────────


class TestHandlePreExitCancel:
    """#609 — when cancel race detects a terminal broker state, the executor
    must NOT submit a new SELL (would open a short)."""

    def test_returns_false_for_none_input(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel
        assert _handle_pre_exit_cancel(None) is False

    def test_returns_false_for_non_dict(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel
        assert _handle_pre_exit_cancel("filled") is False

    def test_returns_true_when_terminal_state_filled(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel
        assert _handle_pre_exit_cancel({"terminal_state": "filled"}) is True

    def test_returns_true_when_terminal_state_partially_filled(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel
        result = _handle_pre_exit_cancel({"terminal_state": "partially_filled"})
        assert result is True

    def test_returns_false_when_terminal_state_canceled(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel
        # canceled is NOT in _CANCEL_TERMINAL_NO_SUBMIT — we may safely resubmit
        assert _handle_pre_exit_cancel({"terminal_state": "canceled"}) is False

    def test_returns_false_when_dict_lacks_terminal_state(self):
        from src.shadow_trading.executor import _handle_pre_exit_cancel
        assert _handle_pre_exit_cancel({"other_key": "value"}) is False


# ─────────────────────────────────────────────────────────────────────────────
# shadow_trading.executor._next_exit_retry_count
# ─────────────────────────────────────────────────────────────────────────────


class TestNextExitRetryCount:
    """#610 — increment must be consistent across both retry paths."""

    def test_first_attempt_returns_one(self):
        from src.shadow_trading.executor import _next_exit_retry_count
        assert _next_exit_retry_count({}) == 1

    def test_none_count_returns_one(self):
        from src.shadow_trading.executor import _next_exit_retry_count
        assert _next_exit_retry_count({"exit_retry_count": None}) == 1

    def test_increments_existing_count(self):
        from src.shadow_trading.executor import _next_exit_retry_count
        assert _next_exit_retry_count({"exit_retry_count": 2}) == 3

    def test_handles_string_count(self):
        from src.shadow_trading.executor import _next_exit_retry_count
        assert _next_exit_retry_count({"exit_retry_count": "1"}) == 2

    def test_handles_invalid_count_gracefully(self):
        from src.shadow_trading.executor import _next_exit_retry_count
        # Garbage data shouldn't crash — falls back to 1
        assert _next_exit_retry_count({"exit_retry_count": "garbage"}) == 1


# ─────────────────────────────────────────────────────────────────────────────
# shadow_trading.executor._should_abandon_exit
# ─────────────────────────────────────────────────────────────────────────────


class TestShouldAbandonExit:
    """#196 / #610 — at the abandonment threshold, the trade is marked
    exit_abandoned for reconciliation rather than retried again."""

    def test_below_threshold_returns_false(self):
        from src.shadow_trading.executor import _should_abandon_exit, _MAX_EXIT_RETRIES
        assert _should_abandon_exit(_MAX_EXIT_RETRIES - 1) is False

    def test_at_threshold_returns_true(self):
        from src.shadow_trading.executor import _should_abandon_exit, _MAX_EXIT_RETRIES
        assert _should_abandon_exit(_MAX_EXIT_RETRIES) is True

    def test_above_threshold_returns_true(self):
        from src.shadow_trading.executor import _should_abandon_exit, _MAX_EXIT_RETRIES
        assert _should_abandon_exit(_MAX_EXIT_RETRIES + 5) is True


# ─────────────────────────────────────────────────────────────────────────────
# shadow_trading.reconcile._resolve_stuck_pnl
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveStuckPnl:
    """#624 — pre-fix the inline switch defaulted to exit_px=entry_px for
    timeout exits, writing literal pnl=$0.00 to training_examples."""

    def test_returns_none_when_no_price_provider(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"actual_entry_price": 100.0, "planned_shares": 10}
        # No price_provider → can't determine exit_px → return None (NOT $0)
        result = _resolve_stuck_pnl(trade, "timeout", current_price_provider=None)
        assert result is None

    def test_uses_current_price_when_provider_returns_value(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"actual_entry_price": 100.0, "planned_shares": 10}
        # 10 shares * (110-100) = $100 PnL
        result = _resolve_stuck_pnl(
            trade, "timeout", current_price_provider=lambda t: 110.0,
        )
        assert result == pytest.approx(100.0)

    def test_uses_stop_price_for_stop_hit(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        # Known reason — uses planned levels, no provider needed
        trade = {
            "actual_entry_price": 100.0,
            "planned_shares": 10,
            "stop_price": 95.0,
        }
        result = _resolve_stuck_pnl(trade, "stop_hit")
        # 10 * (95-100) = -$50 loss
        assert result == pytest.approx(-50.0)

    def test_returns_none_when_entry_price_zero(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"actual_entry_price": 0.0, "planned_shares": 10}
        result = _resolve_stuck_pnl(
            trade, "timeout", current_price_provider=lambda t: 110.0,
        )
        # No entry price → can't compute → None
        assert result is None

    def test_returns_none_when_provider_returns_none(self):
        from src.shadow_trading.reconcile import _resolve_stuck_pnl
        trade = {"actual_entry_price": 100.0, "planned_shares": 10}
        result = _resolve_stuck_pnl(
            trade, "timeout", current_price_provider=lambda t: None,
        )
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# scheduler.watch._is_likely_sleep_gap
# ─────────────────────────────────────────────────────────────────────────────


class TestIsLikelySleepGap:
    """Buffer must absorb scheduler jitter (~5%) without missing real gaps."""

    def test_normal_interval_is_not_a_gap(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        # 5-min interval, 5 min elapsed — no gap
        assert _is_likely_sleep_gap(5.0, 5) is False

    def test_jitter_under_threshold_is_not_a_gap(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        # 5-min interval, 6 min elapsed (1.2x) — within jitter buffer
        assert _is_likely_sleep_gap(6.0, 5) is False

    def test_at_threshold_is_not_a_gap(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        # Exactly 1.5x is the boundary — strictly greater required
        assert _is_likely_sleep_gap(7.5, 5) is False

    def test_above_threshold_is_a_gap(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        # 5-min interval, 8 min elapsed (1.6x) — sleep/wake gap
        assert _is_likely_sleep_gap(8.0, 5) is True

    def test_long_gap_is_a_gap(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        # 5-min interval, 30 min elapsed — definitely a gap
        assert _is_likely_sleep_gap(30.0, 5) is True


# ─────────────────────────────────────────────────────────────────────────────
# training.data_collector.CollectionResult.is_silent_failure
# ─────────────────────────────────────────────────────────────────────────────


class TestCollectionResultSilentFailure:
    """#615 — distinguish "no work" (count=0, attempted=0, rejected=0)
    from "tried and failed" (count=0 with non-zero work counters)."""

    def test_empty_result_is_not_silent_failure(self):
        from src.training.data_collector import CollectionResult
        # No closed trades to process → all zeros → NOT silent failure
        assert CollectionResult().is_silent_failure is False

    def test_successful_run_is_not_silent_failure(self):
        from src.training.data_collector import CollectionResult
        # Wrote some examples → not silent failure
        result = CollectionResult(count=5, attempted=5, rejected=0)
        assert result.is_silent_failure is False

    def test_zero_count_with_attempts_is_silent_failure(self):
        from src.training.data_collector import CollectionResult
        # Tried 5, wrote 0 → SILENT FAILURE
        result = CollectionResult(count=0, attempted=5, rejected=0)
        assert result.is_silent_failure is True

    def test_zero_count_with_rejections_is_silent_failure(self):
        from src.training.data_collector import CollectionResult
        result = CollectionResult(count=0, attempted=0, rejected=3)
        assert result.is_silent_failure is True

    def test_zero_count_with_stage1_failures_is_silent_failure(self):
        from src.training.data_collector import CollectionResult
        result = CollectionResult(count=0, stage1_failures=10)
        assert result.is_silent_failure is True


# ─────────────────────────────────────────────────────────────────────────────
# api.local_auth.verify_local_token
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyLocalToken:
    """#576 — opt-in local-API bearer token. Constant-time compare."""

    def test_no_op_when_env_unset(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.delenv("ARCIS_LOCAL_API_TOKEN", raising=False)
        # No token configured → no-op (returns None, raises nothing)
        assert verify_local_token(authorization=None) is None

    def test_no_op_when_env_empty_string(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "")
        assert verify_local_token(authorization=None) is None

    def test_no_op_when_env_only_whitespace(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "   ")
        assert verify_local_token(authorization=None) is None

    def test_rejects_missing_authorization_when_token_set(self, monkeypatch):
        from fastapi import HTTPException
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        with pytest.raises(HTTPException) as exc_info:
            verify_local_token(authorization=None)
        assert exc_info.value.status_code == 401

    def test_rejects_non_bearer_scheme(self, monkeypatch):
        from fastapi import HTTPException
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        with pytest.raises(HTTPException) as exc_info:
            verify_local_token(authorization="Basic some-credentials")
        assert exc_info.value.status_code == 401

    def test_rejects_wrong_token(self, monkeypatch):
        from fastapi import HTTPException
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        with pytest.raises(HTTPException) as exc_info:
            verify_local_token(authorization="Bearer wrong-token")
        assert exc_info.value.status_code == 401

    def test_accepts_correct_token(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        # Returns None on success (FastAPI dep convention)
        assert verify_local_token(authorization="Bearer secret123") is None

    def test_bearer_scheme_is_case_insensitive(self, monkeypatch):
        from src.api.local_auth import verify_local_token
        monkeypatch.setenv("ARCIS_LOCAL_API_TOKEN", "secret123")
        assert verify_local_token(authorization="bearer secret123") is None
        assert verify_local_token(authorization="BEARER secret123") is None

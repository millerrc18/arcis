"""Tests for qty_mismatch.py — parser, threshold, and executor-loop integration.

Track 1.5 / B2.C — CVS position-size mismatch detection + bounded retry.
"""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import MagicMock, patch, call

from src.shadow_trading.qty_mismatch import parse_qty_mismatch, should_abort_retry


# ---------------------------------------------------------------------------
# parse_qty_mismatch — positive cases
# ---------------------------------------------------------------------------

class TestParseQtyMismatchPositive(unittest.TestCase):
    """parse_qty_mismatch returns (requested, available) for Alpaca's exact message."""

    def test_exact_alpaca_message(self):
        msg = "insufficient qty available: requested 130, available 4 (code: 40310000)"
        result = parse_qty_mismatch(msg)
        self.assertEqual(result, (130, 4))

    def test_large_numbers(self):
        msg = "insufficient qty available: requested 1000, available 999 (code: 40310000)"
        result = parse_qty_mismatch(msg)
        self.assertEqual(result, (1000, 999))

    def test_available_zero(self):
        msg = "insufficient qty available: requested 50, available 0 (code: 40310000)"
        result = parse_qty_mismatch(msg)
        self.assertEqual(result, (50, 0))

    def test_single_digit_values(self):
        msg = "insufficient qty available: requested 1, available 0 (code: 40310000)"
        result = parse_qty_mismatch(msg)
        self.assertEqual(result, (1, 0))


# ---------------------------------------------------------------------------
# parse_qty_mismatch — negative cases (other errors → None)
# ---------------------------------------------------------------------------

class TestParseQtyMismatchNegative(unittest.TestCase):
    """parse_qty_mismatch returns None for non-matching messages."""

    def test_different_api_code(self):
        msg = "insufficient qty available: requested 10, available 0 (code: 40310001)"
        self.assertIsNone(parse_qty_mismatch(msg))

    def test_no_api_code(self):
        msg = "insufficient qty available: requested 10, available 0"
        self.assertIsNone(parse_qty_mismatch(msg))

    def test_buying_power_error(self):
        msg = "insufficient buying power for order (code: 40310000)"
        self.assertIsNone(parse_qty_mismatch(msg))

    def test_empty_string(self):
        self.assertIsNone(parse_qty_mismatch(""))

    def test_unrelated_error(self):
        msg = "order not found"
        self.assertIsNone(parse_qty_mismatch(msg))

    def test_none_input(self):
        self.assertIsNone(parse_qty_mismatch(None))


# ---------------------------------------------------------------------------
# parse_qty_mismatch — edge cases
# ---------------------------------------------------------------------------

class TestParseQtyMismatchEdge(unittest.TestCase):
    """Edge cases around number placement and surrounding text."""

    def test_extra_text_around(self):
        # Numbers in different positions but both anchors present
        msg = "APIError: insufficient qty available: requested 130, available 4 (code: 40310000) [trace_id=abc]"
        result = parse_qty_mismatch(msg)
        self.assertEqual(result, (130, 4))

    def test_code_without_parens(self):
        # If parens are absent but code is in the string — should still fail
        # because the regex anchors on the code literal, not parens.
        # Without '40310000' in message → None
        msg = "insufficient qty available: requested 130, available 4"
        self.assertIsNone(parse_qty_mismatch(msg))

    def test_requested_equals_available(self):
        msg = "insufficient qty available: requested 10, available 10 (code: 40310000)"
        result = parse_qty_mismatch(msg)
        self.assertEqual(result, (10, 10))


# ---------------------------------------------------------------------------
# should_abort_retry — boundary conditions
# ---------------------------------------------------------------------------

class TestShouldAbortRetry(unittest.TestCase):
    """should_abort_retry enforces the default threshold of 3."""

    def test_count_equals_threshold_default(self):
        self.assertTrue(should_abort_retry(3))

    def test_count_below_threshold(self):
        self.assertFalse(should_abort_retry(2))

    def test_count_zero(self):
        self.assertFalse(should_abort_retry(0))

    def test_count_one(self):
        self.assertFalse(should_abort_retry(1))

    def test_count_above_threshold(self):
        self.assertTrue(should_abort_retry(4))

    def test_threshold_override_lower(self):
        self.assertTrue(should_abort_retry(1, threshold=1))
        self.assertFalse(should_abort_retry(0, threshold=1))

    def test_threshold_override_higher(self):
        self.assertFalse(should_abort_retry(3, threshold=5))
        self.assertTrue(should_abort_retry(5, threshold=5))


# ---------------------------------------------------------------------------
# Integration — executor _retry_exit with qty-mismatch guard
# ---------------------------------------------------------------------------

def _make_db():
    """Return an in-memory SQLite connection with broker_exceptions table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE broker_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            operation TEXT,
            broker TEXT,
            timestamp TEXT,
            exception_class TEXT,
            exception_message TEXT,
            traceback TEXT,
            recoverable INTEGER,
            created_at TEXT,
            correlation_id TEXT,
            retry_count INTEGER,
            outcome TEXT
        )
    """)
    conn.commit()
    return conn


class _FakeAPIError(Exception):
    """Minimal stand-in for alpaca.common.exceptions.APIError."""
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class TestExecutorQtyMismatchIntegration(unittest.TestCase):
    """Integration: _retry_exit aborts after 3 consecutive qty-mismatch errors.

    Uses mock_db_path='::memory_stub::' so connect_db resolves to the
    in-memory fixture. The mock also patches update_shadow_trade so we
    can assert the final status + exit_reason write.
    """

    def setUp(self):
        self.db_conn = _make_db()
        self.db_path = "::test_stub::"

        self.trade = {
            "trade_id": "trade-cvs-001",
            "ticker": "CVS",
            "shares": 130,
            "planned_shares": 130,
            "exit_retry_count": 0,
            "status": "exit_failed",
            "exit_reason": None,
            "actual_entry_price": 60.0,
            "entry_price": 60.0,
            "alpaca_order_id": None,
            "exit_order_id": None,
            "source": "paper",
        }

    def _api_error(self):
        return _FakeAPIError(
            "insufficient qty available: requested 130, available 4 (code: 40310000)"
        )

    def test_log_and_persist_called_on_each_qty_error(self):
        """log_and_persist is called once per qty-mismatch raise inside _retry_exit."""
        from src.shadow_trading import executor

        api_err = self._api_error()

        with patch.object(executor, "update_shadow_trade") as mock_update, \
             patch.object(executor, "log_and_persist") as mock_lap, \
             patch.object(executor, "_submit_exit_order", side_effect=api_err), \
             patch.object(executor, "_sync_exit_qty", return_value=(130, None)), \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=None):

            # Set retry_count so we're on the first attempt (count=0 < threshold)
            self.trade["exit_retry_count"] = 0
            executor._retry_exit(self.trade, db_path=self.db_path)

        # log_and_persist should have been called at least once
        self.assertTrue(mock_lap.called)

    def test_abort_fires_after_three_qty_mismatch_errors(self):
        """After 3 consecutive 40310000 errors, status='exit_failed' and
        exit_reason='qty_mismatch_partial_fill' is written.

        We simulate the 3rd occurrence by pre-seeding exit_retry_count=2
        and letting the next raise be the 3rd qty-mismatch. The guard must
        catch it and write the terminal state without submitting a 4th order.
        """
        from src.shadow_trading import executor

        api_err = self._api_error()
        submit_mock = MagicMock(side_effect=api_err)

        with patch.object(executor, "update_shadow_trade") as mock_update, \
             patch.object(executor, "log_and_persist") as mock_lap, \
             patch.object(executor, "_submit_exit_order", submit_mock), \
             patch.object(executor, "_sync_exit_qty", return_value=(130, None)), \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=None):

            # Seed so that this is the 3rd attempt (count=2 means 2 already done)
            self.trade["exit_retry_count"] = 2
            executor._retry_exit(self.trade, db_path=self.db_path)

        # The trade must be marked exit_failed with qty_mismatch_partial_fill
        update_calls = mock_update.call_args_list
        statuses_written = []
        for c in update_calls:
            args, kwargs = c
            if len(args) >= 2 and isinstance(args[1], dict):
                statuses_written.append(args[1])

        final_write = {k: v for d in statuses_written for k, v in d.items()}
        self.assertEqual(final_write.get("status"), "exit_failed")
        self.assertEqual(final_write.get("exit_reason"), "qty_mismatch_partial_fill")

    def test_fourth_raise_never_fires(self):
        """After abort, _submit_exit_order is called at most once per invocation.

        On the 3rd consecutive qty-mismatch (exit_retry_count=2), we abort
        without scheduling a 4th submission — submit is called exactly once
        (the failed attempt that triggers the abort), then returns.
        """
        from src.shadow_trading import executor

        api_err = self._api_error()
        submit_mock = MagicMock(side_effect=api_err)

        with patch.object(executor, "update_shadow_trade"), \
             patch.object(executor, "log_and_persist"), \
             patch.object(executor, "_submit_exit_order", submit_mock), \
             patch.object(executor, "_sync_exit_qty", return_value=(130, None)), \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=None):

            self.trade["exit_retry_count"] = 2
            executor._retry_exit(self.trade, db_path=self.db_path)

        # Should have been called exactly once (the failing attempt) — NOT again
        self.assertEqual(submit_mock.call_count, 1)

    def test_alert_outcome_on_third_qty_mismatch(self):
        """On the 3rd occurrence, log_and_persist is called with outcome='alert_qty_mismatch'."""
        from src.shadow_trading import executor

        api_err = self._api_error()

        with patch.object(executor, "update_shadow_trade"), \
             patch.object(executor, "log_and_persist") as mock_lap, \
             patch.object(executor, "_submit_exit_order", side_effect=api_err), \
             patch.object(executor, "_sync_exit_qty", return_value=(130, None)), \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=None):

            self.trade["exit_retry_count"] = 2
            executor._retry_exit(self.trade, db_path=self.db_path)

        outcomes = [c.kwargs.get("outcome") for c in mock_lap.call_args_list]
        self.assertIn("alert_qty_mismatch", outcomes)

    def test_non_qty_error_does_not_abort(self):
        """A non-40310000 APIError on attempt 3 does NOT trigger qty-mismatch abort path."""
        from src.shadow_trading import executor

        other_err = _FakeAPIError("order not found (code: 40410000)")
        submit_mock = MagicMock(side_effect=other_err)

        with patch.object(executor, "update_shadow_trade") as mock_update, \
             patch.object(executor, "log_and_persist"), \
             patch.object(executor, "_submit_exit_order", submit_mock), \
             patch.object(executor, "_sync_exit_qty", return_value=(130, None)), \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=None):

            self.trade["exit_retry_count"] = 2
            executor._retry_exit(self.trade, db_path=self.db_path)

        # Should write exit_failed but NOT qty_mismatch_partial_fill
        update_calls = mock_update.call_args_list
        exit_reasons = []
        for c in update_calls:
            args, _ = c
            if len(args) >= 2 and isinstance(args[1], dict):
                if "exit_reason" in args[1]:
                    exit_reasons.append(args[1]["exit_reason"])

        self.assertNotIn("qty_mismatch_partial_fill", exit_reasons)


if __name__ == "__main__":
    unittest.main()

"""Tests for exponential backoff retry utility."""

import time
from unittest.mock import MagicMock, patch

from src.utils.retry import retry_with_backoff


class TestRetryWithBackoff:
    def test_succeeds_on_first_try(self):
        fn = MagicMock(return_value="ok")
        result = retry_with_backoff(fn, max_retries=3)
        assert result == "ok"
        assert fn.call_count == 1

    def test_retries_then_succeeds(self):
        fn = MagicMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "ok"])
        result = retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 3

    def test_exhausts_retries_returns_none(self):
        fn = MagicMock(side_effect=ConnectionError("always fails"))
        result = retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result is None
        assert fn.call_count == 3

    def test_only_catches_specified_exceptions(self):
        fn = MagicMock(side_effect=ValueError("not retryable"))
        try:
            retry_with_backoff(fn, max_retries=3, base_delay=0.01, exceptions=(ConnectionError,))
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        assert fn.call_count == 1

    def test_delay_increases_exponentially(self):
        fn = MagicMock(side_effect=[ConnectionError("1"), ConnectionError("2"), "ok"])
        delays = []
        with patch("src.utils.retry.time.sleep", side_effect=lambda d: delays.append(d)):
            retry_with_backoff(fn, max_retries=3, base_delay=1.0, max_delay=30.0)
        assert len(delays) == 2
        assert delays[1] > delays[0] * 1.5

    def test_delay_capped_at_max(self):
        fn = MagicMock(side_effect=ConnectionError("fail"))
        delays = []
        with patch("src.utils.retry.time.sleep", side_effect=lambda d: delays.append(d)):
            retry_with_backoff(fn, max_retries=10, base_delay=1.0, max_delay=5.0)
        assert all(d <= 6.0 for d in delays)

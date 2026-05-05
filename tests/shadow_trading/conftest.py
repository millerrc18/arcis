"""Shared fixtures for tests/shadow_trading/.

Called by: pytest (auto-discovered)
Calls: src.shadow_trading.alpaca_adapter (mocked)
Owns tables: none
Config keys: none
Tests: provides mock_alpaca fixture consumed by test_executor_retry_exit_path.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_alpaca():
    """Mock AlpacaAdapter submit_order, verify_order_accepted, and get_order.

    No env-var deps — safe for worktree isolation.
    """
    submit = MagicMock(return_value={"status": "accepted", "order_id": "mock-order-id"})
    verify = MagicMock(return_value=True)
    get_order = MagicMock(return_value={"status": "filled", "filled_avg_price": "150.0"})

    with (
        patch("src.shadow_trading.alpaca_adapter.submit_order", submit),
        patch("src.shadow_trading.alpaca_adapter.verify_order_accepted", verify),
        patch("src.shadow_trading.alpaca_adapter.get_order", get_order),
    ):
        yield {
            "submit_order": submit,
            "verify_order_accepted": verify,
            "get_order": get_order,
        }

"""End-to-end status normalization for `place_paper_*` / `place_live_*`.

Context: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md` §H5
deferred the 8 callsites in `alpaca_adapter_paper.py` and
`alpaca_adapter_live.py` that return `str(order.status)` directly instead
of going through `_strip_enum()`. The downstream comparison in
`executor.py` against ``FILLED_ORDER_STATUSES`` / ``PENDING_ORDER_STATUSES``
(lowercase canonical values) silently failed on every alpaca-py 0.43+
enum because ``str(OrderStatus.X)`` is ``"OrderStatus.X"``, not ``"x"``.

The 2026-05-15 MO/BK exit-overshoot incident traced to this deferred bug:
PENDING_NEW status was misclassified as ``exit_failed`` → retry loop →
duplicate SELL race → broker showed -51/-34 short in a long-only system.

This test file forces the migration by asserting every relevant adapter
function returns a dict whose ``status`` field is the canonical lowercase
value, not the raw ``OrderStatus.X`` form. RED before the fix, GREEN
after replacing ``str(order.status)`` with ``_strip_enum(order.status)``.

Coverage (the 8 deferred callsites):
- alpaca_adapter_paper.py:50   place_paper_entry
- alpaca_adapter_paper.py:86   place_paper_exit
- alpaca_adapter_paper.py:153  place_bracket_order
- alpaca_adapter_live.py:134   place_live_entry
- alpaca_adapter_live.py:208   place_live_bracket
- alpaca_adapter_live.py:242   place_live_exit (close_position branch)
- alpaca_adapter_live.py:269   place_live_exit (market-sell branch)
- alpaca_adapter_live.py:305   get_live_order_status
"""
from __future__ import annotations

import enum
from unittest.mock import MagicMock, patch

import pytest


# ── Local OrderStatus that mimics alpaca-py 0.43+ regular-Enum behavior ───────
#
# alpaca-py uses ``enum.Enum`` (not ``StrEnum``), so ``str(OrderStatus.FILLED)``
# returns ``"OrderStatus.FILLED"`` (Python default for regular enums) — NOT
# the lowercase value ``"filled"``. Conftest mocks ``alpaca.trading.enums``
# but does NOT populate ``OrderStatus``, so a real import would raise
# ``AttributeError`` here. We construct a local Enum with the same
# stringification semantics to exercise the production bug.

class _LocalOrderStatus(enum.Enum):
    FILLED = "filled"
    PENDING_NEW = "pending_new"
    NEW = "new"
    ACCEPTED = "accepted"
    CANCELED = "canceled"


# Confirm the assumption: this Enum stringifies the same way as alpaca-py's.
assert str(_LocalOrderStatus.PENDING_NEW) == "_LocalOrderStatus.PENDING_NEW"
assert _LocalOrderStatus.PENDING_NEW.value == "pending_new"


def _make_mock_order(status: _LocalOrderStatus = _LocalOrderStatus.FILLED) -> MagicMock:
    """Return a MagicMock that mimics an alpaca-py Order.

    The critical attribute is ``.status`` — we set it to a real Enum
    instance so the adapter's stringification path matches production.
    """
    order = MagicMock()
    order.id = "abc-123"
    order.symbol = "TEST"
    order.qty = "1"
    order.filled_qty = "1"
    order.side = MagicMock()
    order.type = MagicMock()
    order.status = status
    order.filled_avg_price = 100.0
    order.filled_at = None
    order.created_at = None
    order.legs = []
    return order


CANONICAL_STATUS_VALUES = frozenset({s.value for s in _LocalOrderStatus})


# ── Paper adapter — 3 callsites ───────────────────────────────────────────────


class TestPaperAdapterStatusNormalization:
    """Paper adapter (`alpaca_adapter_paper.py`) returns lowercase status."""

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_place_paper_entry_returns_normalized_status(
        self, mock_check_enabled, mock_get_trading_client,
    ):
        """``place_paper_entry`` returned dict must have lowercase ``status``."""
        from src.shadow_trading.alpaca_adapter import place_paper_entry

        mock_order = _make_mock_order(_LocalOrderStatus.FILLED)
        client = MagicMock()
        client.submit_order.return_value = mock_order
        mock_get_trading_client.return_value = client

        result = place_paper_entry("AAPL", 1)

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_paper_entry returned status={result['status']!r} — "
            f"must be lowercase canonical (one of {sorted(CANONICAL_STATUS_VALUES)}). "
            "Use `_strip_enum(order.status)` instead of `str(order.status)`."
        )

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_place_paper_exit_returns_normalized_status(
        self, mock_check_enabled, mock_get_trading_client,
    ):
        """``place_paper_exit`` returned dict must have lowercase ``status``.

        This is the exact bug class that triggered the 2026-05-15 MO/BK
        exit-overshoot incident. ``OrderStatus.PENDING_NEW`` from a paper
        SELL got misclassified as ``exit_failed``, causing duplicate SELLs.
        """
        from src.shadow_trading.alpaca_adapter import place_paper_exit

        mock_order = _make_mock_order(_LocalOrderStatus.PENDING_NEW)
        client = MagicMock()
        client.submit_order.return_value = mock_order
        mock_get_trading_client.return_value = client

        result = place_paper_exit("AAPL", 1)

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_paper_exit returned status={result['status']!r} — "
            f"must be lowercase canonical (one of {sorted(CANONICAL_STATUS_VALUES)}). "
            "This was the 2026-05-15 MO/BK overshoot trigger."
        )
        assert result["status"] == "pending_new", (
            "PENDING_NEW must round-trip as the canonical value `pending_new`. "
            f"Got {result['status']!r}."
        )

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_place_bracket_order_returns_normalized_status(
        self, mock_check_enabled, mock_get_trading_client,
    ):
        """``place_bracket_order`` returned dict must have lowercase ``status``."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_order = _make_mock_order(_LocalOrderStatus.NEW)
        client = MagicMock()
        client.submit_order.return_value = mock_order
        mock_get_trading_client.return_value = client

        result = place_bracket_order(
            "AAPL", 1, take_profit_price=105.0, stop_loss_price=95.0,
        )

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_bracket_order returned status={result['status']!r} — "
            f"must be lowercase canonical."
        )


# ── Live adapter — 5 callsites ────────────────────────────────────────────────


class TestLiveAdapterStatusNormalization:
    """Live adapter (`alpaca_adapter_live.py`) returns lowercase status.

    These are dormant in paper mode but would trigger identically if/when
    live trading is enabled. Fixing now is defense-in-depth.
    """

    @patch("src.shadow_trading.alpaca_adapter_live._get_live_trading_client")
    @patch("src.shadow_trading.alpaca_adapter_live._get_live_config")
    def test_place_live_entry_returns_normalized_status(
        self, mock_get_live_config, mock_get_live_trading_client,
    ):
        from src.shadow_trading.alpaca_adapter_live import place_live_entry

        mock_get_live_config.return_value = {"enabled": True}
        mock_order = _make_mock_order(_LocalOrderStatus.FILLED)
        client = MagicMock()
        client.submit_order.return_value = mock_order
        mock_get_live_trading_client.return_value = client

        result = place_live_entry("AAPL", 1)

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_live_entry returned status={result['status']!r} — "
            "must be lowercase canonical."
        )

    @patch("src.shadow_trading.alpaca_adapter_live._get_live_trading_client")
    @patch("src.shadow_trading.alpaca_adapter_live._get_live_config")
    def test_place_live_bracket_returns_normalized_status(
        self, mock_get_live_config, mock_get_live_trading_client,
    ):
        from src.shadow_trading.alpaca_adapter_live import place_live_bracket

        mock_get_live_config.return_value = {"enabled": True}
        mock_order = _make_mock_order(_LocalOrderStatus.NEW)
        client = MagicMock()
        client.submit_order.return_value = mock_order
        mock_get_live_trading_client.return_value = client

        result = place_live_bracket(
            "AAPL", 1, take_profit_price=105.0, stop_loss_price=95.0,
        )

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_live_bracket returned status={result['status']!r}"
        )

    @patch("src.shadow_trading.alpaca_adapter_live._get_live_trading_client")
    @patch("src.shadow_trading.alpaca_adapter_live._get_live_config")
    def test_place_live_exit_close_position_returns_normalized_status(
        self, mock_get_live_config, mock_get_live_trading_client,
    ):
        """``place_live_exit(shares=0)`` uses ``close_position`` — separate branch."""
        from src.shadow_trading.alpaca_adapter_live import place_live_exit

        mock_get_live_config.return_value = {"enabled": True}
        mock_order = _make_mock_order(_LocalOrderStatus.ACCEPTED)
        client = MagicMock()
        client.close_position.return_value = mock_order
        mock_get_live_trading_client.return_value = client

        result = place_live_exit("AAPL", shares=0)

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_live_exit (close_position branch) returned "
            f"status={result['status']!r}"
        )

    @patch("src.shadow_trading.alpaca_adapter_live._get_live_trading_client")
    @patch("src.shadow_trading.alpaca_adapter_live._get_live_config")
    def test_place_live_exit_market_sell_returns_normalized_status(
        self, mock_get_live_config, mock_get_live_trading_client,
    ):
        """``place_live_exit(shares>0)`` uses market SELL — separate branch."""
        from src.shadow_trading.alpaca_adapter_live import place_live_exit

        mock_get_live_config.return_value = {"enabled": True}
        mock_order = _make_mock_order(_LocalOrderStatus.PENDING_NEW)
        client = MagicMock()
        client.submit_order.return_value = mock_order
        mock_get_live_trading_client.return_value = client

        result = place_live_exit("AAPL", shares=1)

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"place_live_exit (market-sell branch) returned "
            f"status={result['status']!r}"
        )

    @patch("src.shadow_trading.alpaca_adapter_live._get_live_trading_client")
    def test_get_live_order_status_returns_normalized_status(
        self, mock_get_live_trading_client,
    ):
        from src.shadow_trading.alpaca_adapter_live import get_live_order_status

        mock_order = _make_mock_order(_LocalOrderStatus.FILLED)
        client = MagicMock()
        client.get_order_by_id.return_value = mock_order
        mock_get_live_trading_client.return_value = client

        result = get_live_order_status("abc-123")

        assert result["status"] in CANONICAL_STATUS_VALUES, (
            f"get_live_order_status returned status={result['status']!r}"
        )

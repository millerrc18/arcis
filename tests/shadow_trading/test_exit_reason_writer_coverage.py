"""Routing tests: every exit_reason writer outside executor.py must call coerce_exit_reason.

Track 1.5 / B3 follow-up — Pass 2.

Files under test:
  src/shadow_trading/reconcile.py  — 5 write sites
  src/cli/commands.py              — 3 write sites (shadow_close x1, live_close x2 via coerce-once)
  src/api/routes/shadow.py         — 2 write sites (coerce-once at top of close_trade)

Strategy: patch coerce_exit_reason where it is imported in each module (module-level
import) and assert it is called. DB helpers are mocked to avoid real I/O.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# reconcile.py — reconciled_stale (x2), exit_overshoot_detected, qty_mismatch_partial_fill
# ---------------------------------------------------------------------------

class TestReconcileRoutesThroughCoerce:
    """reconcile.py must route all exit_reason writes through coerce_exit_reason."""

    def test_reconcile_live_stale_close_routes_through_coerce(self):
        """reconcile_live_trades: stale close passes 'reconciled_stale' to coerce."""
        from src.shadow_trading.reconcile import reconcile_live_trades

        with (
            patch("src.shadow_trading.reconcile.connect_db") as mock_connect,
            patch("src.shadow_trading.reconcile._estimate_exit_pnl", return_value=(100.0, 0.0, 0.0)),
            patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0),
            patch("src.shadow_trading.reconcile.coerce_exit_reason") as mock_coerce,
            patch("src.trading.broker_factory.get_live_broker") as mock_broker_factory,
            patch("src.journal.store.insert_shadow_trade"),
            patch("src.journal.store.close_shadow_trade"),
        ):
            mock_coerce.return_value = "reconciled"

            mock_broker = MagicMock()
            mock_broker.get_all_positions.return_value = []
            mock_broker_factory.return_value = mock_broker

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            tracked_entry = {"trade_id": "trade-001", "ticker": "AAPL"}
            mock_conn.execute.return_value.fetchall.return_value = [tracked_entry]
            mock_conn.execute.return_value.fetchone.return_value = {
                "actual_entry_price": 100.0, "entry_price": 100.0,
                "planned_shares": 10.0,
                "alpaca_order_id": None, "exit_order_id": None,
                "ib_child_order_ids": None,
            }
            mock_connect.return_value = mock_conn

            reconcile_live_trades(desk="swing", dry_run=False, db_path=":memory:")

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "reconciled_stale" in coerced_values

    def test_reconcile_paper_stale_close_routes_through_coerce(self):
        """reconcile_paper_trades: stale close passes 'reconciled_stale' to coerce."""
        from src.shadow_trading.reconcile import reconcile_paper_trades

        old_trade_row = {
            "trade_id": "trade-001", "ticker": "AAPL",
            "planned_shares": 10.0, "broker": "alpaca",
            "actual_entry_price": 100.0, "entry_price": 100.0,
            "created_at": "2024-01-01T09:00:00",
        }

        with (
            patch("src.shadow_trading.reconcile.get_all_positions", return_value=[]),
            patch("src.shadow_trading.reconcile.connect_db") as mock_connect,
            patch("src.shadow_trading.reconcile._estimate_exit_pnl", return_value=(100.0, 0.0, 0.0)),
            patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0),
            patch("src.shadow_trading.reconcile.coerce_exit_reason") as mock_coerce,
            patch("src.journal.store.insert_shadow_trade"),
            patch("src.journal.store.close_shadow_trade"),
        ):
            mock_coerce.return_value = "reconciled"

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.row_factory = None

            call_count = [0]

            def fetchall_side_effect():
                call_count[0] += 1
                if call_count[0] == 1:
                    return [old_trade_row]
                return []

            mock_conn.execute.return_value.fetchall.side_effect = fetchall_side_effect
            mock_conn.execute.return_value.fetchone.return_value = old_trade_row
            mock_connect.return_value = mock_conn

            reconcile_paper_trades(desk="swing", dry_run=False, db_path=":memory:")

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "reconciled_stale" in coerced_values

    def test_reconcile_overshoot_detected_routes_through_coerce(self):
        """reconcile_paper_trades: exit_overshoot_detected passes to coerce before SQL UPDATE."""
        from src.shadow_trading.reconcile import reconcile_paper_trades

        stuck_row = {
            "trade_id": "trade-002", "ticker": "GOOG",
            "exit_reason": None,
            "actual_entry_price": 150.0, "entry_price": 150.0,
            "planned_shares": 5.0,
            "stop_price": 142.0, "target_1": 160.0, "target_2": 170.0,
        }

        alpaca_positions = [{"symbol": "GOOG", "qty": -1, "avg_entry_price": 150.0}]

        with (
            patch("src.shadow_trading.reconcile.get_all_positions", return_value=alpaca_positions),
            patch("src.shadow_trading.reconcile.connect_db") as mock_connect,
            patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0),
            patch("src.shadow_trading.reconcile.coerce_exit_reason") as mock_coerce,
            patch("src.journal.store.close_shadow_trade"),
        ):
            mock_coerce.return_value = "error"

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            call_count = [0]

            def fetchall_side_effect():
                call_count[0] += 1
                if call_count[0] == 1:
                    return []
                if call_count[0] == 2:
                    return [stuck_row]
                return []

            mock_conn.execute.return_value.fetchall.side_effect = fetchall_side_effect
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_connect.return_value = mock_conn

            reconcile_paper_trades(desk="swing", dry_run=False, db_path=":memory:")

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "exit_overshoot_detected" in coerced_values

    def test_reconcile_qty_mismatch_routes_through_coerce(self):
        """reconcile_paper_trades: qty_mismatch_partial_fill passes to coerce before SQL UPDATE."""
        from src.shadow_trading.reconcile import reconcile_paper_trades

        stuck_row = {
            "trade_id": "trade-003", "ticker": "MSFT",
            "exit_reason": None,
            "actual_entry_price": 200.0, "entry_price": 200.0,
            "planned_shares": 10.0,
            "stop_price": 190.0, "target_1": 210.0, "target_2": 220.0,
        }

        alpaca_positions = [{"symbol": "MSFT", "qty": 5, "avg_entry_price": 200.0}]

        with (
            patch("src.shadow_trading.reconcile.get_all_positions", return_value=alpaca_positions),
            patch("src.shadow_trading.reconcile.connect_db") as mock_connect,
            patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0),
            patch("src.shadow_trading.reconcile.coerce_exit_reason") as mock_coerce,
            patch("src.journal.store.close_shadow_trade"),
            patch("src.journal.store.insert_shadow_trade"),
        ):
            mock_coerce.return_value = "error"

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            call_count = [0]

            def fetchall_side_effect():
                call_count[0] += 1
                if call_count[0] == 1:
                    return []
                if call_count[0] == 2:
                    return [stuck_row]
                return []

            mock_conn.execute.return_value.fetchall.side_effect = fetchall_side_effect
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_connect.return_value = mock_conn

            reconcile_paper_trades(desk="swing", dry_run=False, db_path=":memory:")

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "qty_mismatch_partial_fill" in coerced_values


# ---------------------------------------------------------------------------
# commands.py — cmd_shadow_close, cmd_live_close
# ---------------------------------------------------------------------------

class TestCommandsRoutesThroughCoerce:
    """commands.py manual close commands must route exit_reason through coerce_exit_reason."""

    def test_shadow_close_routes_through_coerce(self):
        """cmd_shadow_close: paper close exit_reason passes through coerce_exit_reason."""
        from src.cli import commands

        args = MagicMock()
        args.ticker = "AAPL"
        args.reason = "manual"

        trade = {
            "trade_id": "trade-001", "ticker": "AAPL",
            "actual_entry_price": 100.0, "entry_price": 100.0,
            "planned_shares": 10.0, "source": "paper",
        }

        with (
            patch("src.journal.store.get_open_shadow_trades", return_value=[trade]),
            patch("src.shadow_trading.executor._get_current_price_safe", return_value=105.0),
            patch("src.shadow_trading.alpaca_adapter.place_paper_exit", side_effect=ImportError("mocked")),
            patch("src.journal.store.close_shadow_trade") as mock_cst,
            patch("src.cli.commands.coerce_exit_reason") as mock_coerce,
        ):
            mock_coerce.return_value = "manual"
            commands.cmd_shadow_close(args)

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "manual" in coerced_values

    def test_live_close_routes_through_coerce(self):
        """cmd_live_close: coerce_exit_reason is called with the operator reason."""
        from src.cli import commands

        args = MagicMock()
        args.ticker = "AAPL"
        args.reason = "manual"

        trade = {
            "trade_id": "trade-002", "ticker": "AAPL",
            "actual_entry_price": 100.0, "entry_price": 100.0,
            "planned_shares": 10.0, "source": "live",
        }

        broker_result = {"status": "filled", "filled_avg_price": 108.0}

        with (
            patch("src.journal.store.get_open_shadow_trades", return_value=[trade]),
            patch("src.shadow_trading.executor._get_current_price_safe", return_value=108.0),
            patch("src.shadow_trading.executor._submit_exit_order", return_value=broker_result),
            patch("src.shadow_trading.executor._is_filled_status", return_value=True),
            patch("src.shadow_trading.executor._is_pending_status", return_value=False),
            patch("src.journal.store.close_shadow_trade") as mock_cst,
            patch("src.journal.store.update_shadow_trade") as mock_ust,
            patch("src.cli.commands.coerce_exit_reason") as mock_coerce,
        ):
            mock_coerce.return_value = "manual"
            commands.cmd_live_close(args)

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "manual" in coerced_values


# ---------------------------------------------------------------------------
# shadow.py — POST /shadow/close/{ticker}
# ---------------------------------------------------------------------------

class TestShadowRouteRoutesThroughCoerce:
    """shadow.py close endpoint must route exit_reason through coerce_exit_reason."""

    def test_close_trade_paper_routes_through_coerce(self):
        """close_trade endpoint: paper close exit_reason passes through coerce_exit_reason."""
        from src.api.routes.shadow import close_trade

        trade = {
            "trade_id": "trade-001", "ticker": "AAPL",
            "actual_entry_price": 100.0, "entry_price": 100.0,
            "planned_shares": 10.0, "source": "paper",
            "alpaca_order_id": None,
            "actual_entry_time": "2026-01-01T09:00:00",
            "created_at": "2026-01-01T09:00:00",
            "recommendation_id": None,
        }

        with (
            patch("src.journal.store.get_open_shadow_trades", return_value=[trade]),
            patch("src.shadow_trading.executor._get_current_price_safe", return_value=105.0),
            patch("src.journal.store.close_shadow_trade") as mock_cst,
            patch("src.journal.store.update_shadow_trade") as mock_ust,
            patch("src.journal.store.update_recommendation"),
            patch("src.api.routes.shadow.coerce_exit_reason") as mock_coerce,
        ):
            mock_coerce.return_value = "manual"
            result = close_trade("AAPL", reason="manual")

        mock_coerce.assert_called()
        coerced_values = [c.args[0] for c in mock_coerce.call_args_list]
        assert "manual" in coerced_values

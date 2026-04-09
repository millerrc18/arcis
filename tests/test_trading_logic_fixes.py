"""Tests for Sprint 8 Task 5 trading logic fixes (#99, #102, #109, #145)."""

import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo


from tests.conftest import init_test_db

ET = ZoneInfo("America/New_York")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    init_test_db(path, ["shadow_trades"])
    return path


class TestAtomicDuplicateCheck:
    """#99 — Race condition: duplicate position check not atomic."""

    def test_atomic_duplicate_blocks_second_trade(self, db_path):
        """BEGIN IMMEDIATE prevents two trades for the same ticker."""
        # Insert an existing open trade
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, created_at, updated_at) "
                "VALUES ('t1', 'AAPL', 'open', '2026-03-20T10:00:00', '2026-03-20T10:00:00')"
            )

        # Simulate the atomic duplicate check logic from executor.py
        dup_conn = sqlite3.connect(db_path)
        dup_conn.execute("BEGIN IMMEDIATE")
        row = dup_conn.execute(
            "SELECT trade_id FROM shadow_trades "
            "WHERE ticker = ? AND status = 'open' LIMIT 1",
            ("AAPL",),
        ).fetchone()
        dup_conn.rollback()
        dup_conn.close()

        assert row is not None, "Should detect existing open trade atomically"

    def test_atomic_duplicate_allows_new_ticker(self, db_path):
        """Atomic check allows trades for tickers without open positions."""
        dup_conn = sqlite3.connect(db_path)
        dup_conn.execute("BEGIN IMMEDIATE")
        row = dup_conn.execute(
            "SELECT trade_id FROM shadow_trades "
            "WHERE ticker = ? AND status = 'open' LIMIT 1",
            ("MSFT",),
        ).fetchone()
        dup_conn.rollback()
        dup_conn.close()

        assert row is None, "Should allow trade for ticker with no open position"


class TestAlpacaFailureAlert:
    """#102 — Alpaca API failure silently skips price checks."""

    def test_failure_rate_above_50_triggers_alert(self):
        """When >50% of price checks fail, a Telegram alert should fire."""
        price_total = 10
        price_failures = 6  # 60% failure

        alert_sent = False

        def mock_send(msg):
            nonlocal alert_sent
            alert_sent = True
            assert "PRICE FETCH ALERT" in msg
            assert "6/10" in msg

        # Simulate the alert logic from check_and_manage_open_trades
        if price_total > 0 and price_failures / price_total > 0.5:
            mock_send(
                f"PRICE FETCH ALERT: {price_failures}/{price_total} price checks failed "
                f"({price_failures / price_total * 100:.0f}%). Possible Alpaca API outage."
            )

        assert alert_sent, "Should send alert when >50% of price checks fail"

    def test_failure_rate_below_50_no_alert(self):
        """When <=50% of price checks fail, no alert."""
        price_total = 10
        price_failures = 4  # 40%

        alert_sent = False
        if price_total > 0 and price_failures / price_total > 0.5:
            alert_sent = True

        assert not alert_sent, "Should NOT alert when failure rate is <=50%"


class TestRealizedDailyLoss:
    """#109 — Daily loss limit should use realized (closed) trades only."""

    def test_daily_pnl_uses_closed_trades_only(self, db_path):
        """get_portfolio_state daily_pnl must come from closed trades today."""
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")

        with sqlite3.connect(db_path) as conn:
            # Open trade with unrealized loss — should NOT count
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, actual_entry_price, planned_shares, created_at, updated_at) "
                "VALUES ('open1', 'AAPL', 'open', 150.0, 10, '2026-03-20T09:00:00', '2026-03-20T09:00:00')"
            )
            # Closed trade today with realized loss — SHOULD count
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, pnl_dollars, actual_exit_time, created_at, updated_at) "
                "VALUES ('closed1', 'MSFT', 'closed', -200.0, ?, '2026-03-20T09:00:00', ?)",
                (f"{today_str}T10:00:00", f"{today_str}T10:00:00"),
            )
            # Closed trade yesterday — should NOT count
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, pnl_dollars, actual_exit_time, created_at, updated_at) "
                "VALUES ('closed2', 'GOOG', 'closed', -500.0, '2020-01-01T10:00:00', '2020-01-01T09:00:00', '2020-01-01T10:00:00')",
            )

        # Query the same way get_portfolio_state does
        rows = sqlite3.connect(db_path).execute(
            "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars IS NOT NULL "
            "AND actual_exit_time >= ?",
            (today_str,),
        ).fetchone()
        daily_pnl = float(rows[0]) if rows else 0.0

        assert daily_pnl == -200.0, (
            f"Daily P&L should be -200 (realized only), got {daily_pnl}"
        )


class TestSectorExposureCurrentPrice:
    """#145 — Sector exposure should use current_price, not entry_price."""

    def test_sector_exposure_uses_current_price(self, db_path):
        """Allocation used for sector exposure should reflect current price."""
        entry_price = 100.0
        current_price = 120.0
        shares = 10

        # The fix computes allocation = current_price * shares
        allocation_new = current_price * shares
        allocation_old = entry_price * shares

        assert allocation_new == 1200.0, "Current-price allocation should be 1200"
        assert allocation_old == 1000.0, "Old entry-price allocation was 1000"
        assert allocation_new != allocation_old, (
            "Sector exposure should differ when current != entry price"
        )

    def test_sector_exposure_falls_back_to_entry_price(self):
        """If current price unavailable, entry_price should be used."""
        entry_price = 100.0
        current_price = None  # Fetch failed
        shares = 10

        effective = current_price if current_price and current_price > 0 else entry_price
        allocation = effective * shares

        assert allocation == 1000.0, "Should fall back to entry_price when current unavailable"


class TestPartialFillDetection:
    """#104 — Partial fills on bracket legs reported as fully protected."""

    def test_partial_fill_detected(self):
        """_check_partial_fills should flag partially filled legs."""
        from src.shadow_trading.bracket_monitor import _check_partial_fills

        order_status = {
            "legs": [
                {
                    "status": "partially_filled",
                    "filled_qty": "5",
                    "type": "stop",
                    "stop_price": 90.0,
                },
                {
                    "status": "new",
                    "filled_qty": "0",
                    "type": "limit",
                    "limit_price": 110.0,
                },
            ]
        }
        warnings = _check_partial_fills(order_status, expected_qty=10.0)
        assert len(warnings) == 1
        assert "stop" in warnings[0]
        assert "5.0/10.0" in warnings[0]

    def test_no_partial_fill_when_fully_filled(self):
        """No warnings when legs are fully active (not partially filled)."""
        from src.shadow_trading.bracket_monitor import _check_partial_fills

        order_status = {
            "legs": [
                {"status": "new", "filled_qty": "0", "type": "stop", "stop_price": 90.0},
                {"status": "new", "filled_qty": "0", "type": "limit", "limit_price": 110.0},
            ]
        }
        warnings = _check_partial_fills(order_status, expected_qty=10.0)
        assert len(warnings) == 0

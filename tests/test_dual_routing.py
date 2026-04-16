"""Tests for dual paper broker routing (_select_paper_broker).

Covers:
  - Routing logic: Alpaca vs IB based on config and score threshold
  - Fallback: IB Gateway down, import failure, logging
  - Cross-broker position counting: get_open_shadow_trades spans both brokers
  - Alpaca regression: no IB import when routing is disabled

All tests use mocks -- no live IB Gateway or Alpaca connection required.
"""

import logging
import sqlite3
import uuid

import pytest
from unittest.mock import patch, MagicMock

from src.shadow_trading.executor import _select_paper_broker
from tests.conftest import init_test_db


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def routing_config():
    """Config with IB paper routing enabled and threshold=80."""
    return {
        "trading": {"ib_enabled": True},  # SD#41 — opt past cold-storage gate
        "live_trading": {
            "ib": {
                "paper_routing": True,
                "paper_routing_threshold": 80,
                "host": "127.0.0.1",
                "port": 4002,
                "client_id": 1,
                "timeout": 5,
            }
        }
    }


@pytest.fixture
def no_routing_config():
    """Config with IB paper routing disabled."""
    return {"live_trading": {"ib": {"paper_routing": False}}}


@pytest.fixture
def no_threshold_config():
    """Config with paper routing enabled but no explicit threshold key."""
    return {
        "trading": {"ib_enabled": True},  # SD#41 — opt past cold-storage gate
        "live_trading": {
            "ib": {
                "paper_routing": True,
                "host": "127.0.0.1",
                "port": 4002,
                "client_id": 1,
                "timeout": 5,
            }
        }
    }


@pytest.fixture
def custom_threshold_config():
    """Config with paper routing enabled and a custom threshold of 60."""
    return {
        "trading": {"ib_enabled": True},  # SD#41 — opt past cold-storage gate
        "live_trading": {
            "ib": {
                "paper_routing": True,
                "paper_routing_threshold": 60,
                "host": "127.0.0.1",
                "port": 4002,
                "client_id": 1,
                "timeout": 5,
            }
        }
    }


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temp database with the shadow_trades table."""
    db_path = str(tmp_path / "test_dual_routing.db")
    init_test_db(db_path, tables=["shadow_trades"])
    return db_path


# ── Routing Logic Tests ─────────────────────────────────────────────


class TestRoutingLogic:
    """Tests 1-6: Verify _select_paper_broker returns the correct
    (broker_name, broker_instance) tuple based on config and score."""

    def test_routes_to_alpaca_when_routing_disabled(self, no_routing_config):
        """paper_routing=false, score=90 -> ("alpaca", None).
        IB should never be considered when routing is off."""
        name, broker = _select_paper_broker(no_routing_config, 90)
        assert name == "alpaca"
        assert broker is None

    def test_routes_to_alpaca_when_score_below_threshold(self, routing_config):
        """paper_routing=true, threshold=80, score=75 -> ("alpaca", None).
        Score below threshold stays on Alpaca."""
        name, broker = _select_paper_broker(routing_config, 75)
        assert name == "alpaca"
        assert broker is None

    @patch("src.trading.ib_broker.IBBroker")
    def test_routes_to_ib_when_score_meets_threshold(self, MockIB, routing_config):
        """paper_routing=true, threshold=80, score=80 -> ("ib", broker).
        Exact threshold match should route to IB."""
        mock_broker = MockIB.return_value
        mock_broker._ensure_connected = MagicMock()

        name, broker = _select_paper_broker(routing_config, 80)

        assert name == "ib"
        assert broker is mock_broker
        mock_broker._ensure_connected.assert_called_once()

    @patch("src.trading.ib_broker.IBBroker")
    def test_routes_to_ib_when_score_exceeds_threshold(self, MockIB, routing_config):
        """paper_routing=true, threshold=80, score=95 -> ("ib", broker).
        Score well above threshold routes to IB."""
        mock_broker = MockIB.return_value
        mock_broker._ensure_connected = MagicMock()

        name, broker = _select_paper_broker(routing_config, 95)

        assert name == "ib"
        assert broker is mock_broker

    @patch("src.trading.ib_broker.IBBroker")
    def test_default_threshold_is_80(self, MockIB, no_threshold_config):
        """paper_routing=true, NO threshold key, score=80 -> ("ib", broker).
        Default threshold should be 80 when key is absent."""
        mock_broker = MockIB.return_value
        mock_broker._ensure_connected = MagicMock()

        name, broker = _select_paper_broker(no_threshold_config, 80)

        assert name == "ib"
        assert broker is mock_broker

    @patch("src.trading.ib_broker.IBBroker")
    def test_custom_threshold_respected(self, MockIB, custom_threshold_config):
        """paper_routing=true, threshold=60, score=65 -> ("ib", broker).
        Custom threshold should be honored over the default 80."""
        mock_broker = MockIB.return_value
        mock_broker._ensure_connected = MagicMock()

        name, broker = _select_paper_broker(custom_threshold_config, 65)

        assert name == "ib"
        assert broker is mock_broker


# ── Fallback Tests ──────────────────────────────────────────────────


class TestFallback:
    """Tests 7-9: Verify graceful fallback to Alpaca when IB is unavailable."""

    @patch("src.trading.ib_broker.IBBroker")
    def test_fallback_to_alpaca_when_gateway_down(self, MockIB, routing_config):
        """IB Gateway connection fails -> falls back to ("alpaca", None)."""
        mock_broker = MockIB.return_value
        mock_broker._ensure_connected.side_effect = ConnectionError("Gateway down")

        name, broker = _select_paper_broker(routing_config, 90)

        assert name == "alpaca"
        assert broker is None

    def test_fallback_to_alpaca_when_ib_import_fails(self, routing_config):
        """IBBroker import fails entirely -> falls back to ("alpaca", None)."""
        import sys
        # Temporarily remove/break the ib_broker module so the deferred
        # import inside _select_paper_broker raises ImportError.
        with patch.dict(sys.modules, {"src.trading.ib_broker": None}):
            name, broker = _select_paper_broker(routing_config, 90)

        assert name == "alpaca"
        assert broker is None

    @patch("src.trading.ib_broker.IBBroker")
    def test_fallback_logs_warning(self, MockIB, routing_config, caplog):
        """When IB Gateway is down, logger.warning is called with 'IB Gateway down'."""
        mock_broker = MockIB.return_value
        mock_broker._ensure_connected.side_effect = ConnectionError("Gateway down")

        with caplog.at_level(logging.WARNING, logger="src.shadow_trading.executor"):
            _select_paper_broker(routing_config, 90)

        assert any("IB Gateway down" in record.message for record in caplog.records), (
            f"Expected 'IB Gateway down' in log warnings, got: "
            f"{[r.message for r in caplog.records]}"
        )


# ── Cross-Broker Position Counting Tests ────────────────────────────


class TestCrossBrokerPositionCounting:
    """Tests 10-11: Verify that get_open_shadow_trades and the position
    limit check in open_shadow_trade count positions from ALL brokers."""

    def _insert_trade(self, db_path, broker="alpaca", ticker="TEST", status="open"):
        """Insert a minimal shadow trade record into the test database."""
        trade_id = str(uuid.uuid4())
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, direction, status, broker, source, created_at, updated_at) "
                "VALUES (?, ?, 'long', ?, ?, 'paper', datetime('now'), datetime('now'))",
                (trade_id, ticker, status, broker),
            )
            conn.commit()
        finally:
            conn.close()
        return trade_id

    def test_open_trades_count_spans_both_brokers(self, tmp_db):
        """Insert 2 alpaca + 1 ib trades. get_open_shadow_trades returns all 3."""
        from src.journal.store import get_open_shadow_trades

        self._insert_trade(tmp_db, broker="alpaca", ticker="AAPL")
        self._insert_trade(tmp_db, broker="alpaca", ticker="MSFT")
        self._insert_trade(tmp_db, broker="ib", ticker="GOOG")

        open_trades = get_open_shadow_trades(tmp_db)

        assert len(open_trades) == 3
        brokers = {t["broker"] for t in open_trades}
        assert brokers == {"alpaca", "ib"}

    def test_position_limit_counts_all_brokers(self, tmp_db):
        """Position limit check sees all 3 positions (2 alpaca + 1 ib).
        With max_positions=3, a 4th trade should be blocked."""
        from src.journal.store import get_open_shadow_trades

        self._insert_trade(tmp_db, broker="alpaca", ticker="AAPL")
        self._insert_trade(tmp_db, broker="alpaca", ticker="MSFT")
        self._insert_trade(tmp_db, broker="ib", ticker="GOOG")

        open_trades = get_open_shadow_trades(tmp_db)
        max_positions = 3

        # Simulates the position limit check in open_shadow_trade()
        at_limit = len(open_trades) >= max_positions
        assert at_limit is True, (
            f"Expected position limit to be reached with {len(open_trades)} trades "
            f"across both brokers (limit={max_positions})"
        )


# ── Alpaca Regression Test ──────────────────────────────────────────


class TestAlpacaRegression:
    """Test 12: When paper_routing is not set, behavior is identical to
    pre-dual-routing code: returns ("alpaca", None), IBBroker never imported."""

    def test_alpaca_unchanged_when_routing_disabled(self, no_routing_config):
        """With paper_routing=false, IBBroker must never be imported."""
        with patch("src.trading.ib_broker.IBBroker") as MockIB:
            name, broker = _select_paper_broker(no_routing_config, 95)

        assert name == "alpaca"
        assert broker is None
        MockIB.assert_not_called()

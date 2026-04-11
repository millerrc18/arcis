"""Tests for IB Shadow Logger.

All tests use mocks — no IB Gateway required.
Verifies: logging, error handling, non-blocking behavior, never places orders.
"""
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from src.trading.ib_shadow import IBShadowLogger
from src.trading.broker_interface import BrokerAccount


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    from src.schema.sqlite import create_all_tables
    create_all_tables(db_path)
    return db_path


def _make_logger(broker_mock=None):
    """Create IBShadowLogger with optional pre-set broker mock."""
    shadow = IBShadowLogger(config={"live_trading": {"ib": {"client_id": 1}}})
    if broker_mock is not None:
        shadow._broker = broker_mock
    return shadow


def _get_shadow_row(db_path):
    """Read the single row from ib_shadow_log."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM ib_shadow_log").fetchone()


class TestIBShadowLogger:

    def test_logs_shadow_trade_when_connected(self, tmp_db):
        """Connected IB with valid contract and sufficient BP logs success."""
        broker = MagicMock()
        broker._ensure_connected.return_value = None
        contract = MagicMock()
        broker._make_contract.return_value = contract
        broker._ib.qualifyContracts.return_value = [contract]
        broker.get_account.return_value = BrokerAccount(
            equity=250_000, cash=200_000, buying_power=200_000,
            portfolio_value=250_000, broker="ib",
        )

        shadow = _make_logger(broker)
        shadow.log_shadow_trade(
            trade_id="T-001", ticker="AAPL", quantity=100,
            entry_price=150.0, stop_price=145.0, target_price=160.0,
            alpaca_order_id="ALP-001", alpaca_fill_price=150.05,
            db_path=tmp_db,
        )

        row = _get_shadow_row(tmp_db)
        assert row is not None
        assert row["ib_connected"] == 1
        assert row["ib_contract_valid"] == 1
        assert row["ib_would_accept"] == 1
        assert row["ticker"] == "AAPL"
        assert row["alpaca_order_id"] == "ALP-001"
        params = json.loads(row["ib_order_params"])
        assert params["action"] == "BUY"
        assert params["quantity"] == 100

    def test_logs_with_ib_disconnected(self, tmp_db):
        """When IB Gateway is down, logs ib_connected=0 with error."""
        broker = MagicMock()
        broker._ensure_connected.side_effect = ConnectionError("Gateway offline")

        shadow = _make_logger(broker)
        shadow.log_shadow_trade(
            trade_id="T-002", ticker="MSFT", quantity=50,
            entry_price=300.0, stop_price=290.0, target_price=320.0,
            db_path=tmp_db,
        )

        row = _get_shadow_row(tmp_db)
        assert row["ib_connected"] == 0
        assert "Connection failed" in row["ib_error"]

    def test_contract_invalid_logged(self, tmp_db):
        """When qualifyContracts raises, logs ib_contract_valid=0."""
        broker = MagicMock()
        broker._ensure_connected.return_value = None
        broker._make_contract.return_value = MagicMock()
        broker._ib.qualifyContracts.side_effect = ValueError("No contract found")
        broker.get_account.return_value = BrokerAccount(
            equity=100_000, cash=80_000, buying_power=80_000,
            portfolio_value=100_000, broker="ib",
        )

        shadow = _make_logger(broker)
        shadow.log_shadow_trade(
            trade_id="T-003", ticker="XYZ", quantity=100,
            entry_price=50.0, stop_price=48.0, target_price=55.0,
            db_path=tmp_db,
        )

        row = _get_shadow_row(tmp_db)
        assert row["ib_contract_valid"] == 0
        assert "Contract invalid" in row["ib_error"]

    def test_insufficient_buying_power_logged(self, tmp_db):
        """When buying power < required, logs ib_would_accept=0."""
        broker = MagicMock()
        broker._ensure_connected.return_value = None
        broker._make_contract.return_value = MagicMock()
        broker._ib.qualifyContracts.return_value = [MagicMock()]
        broker.get_account.return_value = BrokerAccount(
            equity=500, cash=100, buying_power=100,
            portfolio_value=500, broker="ib",
        )

        shadow = _make_logger(broker)
        shadow.log_shadow_trade(
            trade_id="T-004", ticker="NVDA", quantity=100,
            entry_price=150.0, stop_price=145.0, target_price=160.0,
            db_path=tmp_db,
        )

        row = _get_shadow_row(tmp_db)
        assert row["ib_would_accept"] == 0
        assert row["ib_buying_power"] == 100.0
        # Required is 150 * 100 = 15000 > 100 BP

    def test_never_calls_place_order(self, tmp_db):
        """Shadow logger must NEVER call placeOrder."""
        broker = MagicMock()
        broker._ensure_connected.return_value = None
        broker._make_contract.return_value = MagicMock()
        broker._ib.qualifyContracts.return_value = [MagicMock()]
        broker.get_account.return_value = BrokerAccount(
            equity=500_000, cash=400_000, buying_power=400_000,
            portfolio_value=500_000, broker="ib",
        )

        shadow = _make_logger(broker)
        shadow.log_shadow_trade(
            trade_id="T-005", ticker="GOOGL", quantity=10,
            entry_price=140.0, stop_price=135.0, target_price=150.0,
            db_path=tmp_db,
        )

        broker._ib.placeOrder.assert_not_called()

    def test_exception_does_not_propagate(self, tmp_db):
        """Even if _get_broker explodes, log_shadow_trade must not raise."""
        shadow = IBShadowLogger(config={})
        with patch.object(shadow, "_get_broker", side_effect=RuntimeError("boom")):
            # Should not raise
            shadow.log_shadow_trade(
                trade_id="T-006", ticker="META", quantity=25,
                entry_price=400.0, stop_price=390.0, target_price=420.0,
                db_path=tmp_db,
            )

        row = _get_shadow_row(tmp_db)
        assert row is not None
        assert "boom" in row["ib_error"]

"""Sprint IB-7 integration validation: verify all 6 IB sprints work together.

Tests the full IB integration across the shadow trading system:
  - IB trade lifecycle (entry -> monitor -> close)
  - Cross-broker position counting (IB + Alpaca coexistence)
  - Config progression (no IB -> shadow_mode -> paper_routing)
  - IB failure recovery (fallback to Alpaca when Gateway is down)
  - Multi-broker API responses (broker field, schema, status map)

Called by: CI
Calls: journal.store, shadow_trading.executor, shadow_trading.models, trading.ib_broker, schema.registry
"""

import json
import sqlite3
import uuid

import pytest
from unittest.mock import patch, MagicMock

from src.schema.sqlite import create_all_tables
from src.journal.store import (
    insert_shadow_trade,
    get_open_shadow_trades,
    close_shadow_trade,
)
from src.shadow_trading.models import TERMINAL_STATUSES, ACTIVE_STATUSES
from src.schema.registry import TABLES
from src.trading.ib_broker import IB_STATUS_MAP


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    create_all_tables(db_path)
    return db_path


def _insert_test_trade(db_path, ticker="AAPL", broker="alpaca", status="open",
                       pnl=None, ib_child_ids=None, score=50):
    """Insert a minimal shadow trade for integration testing."""
    trade = {
        "trade_id": str(uuid.uuid4()),
        "ticker": ticker,
        "direction": "long",
        "status": status,
        "source": "paper",
        "broker": broker,
        "entry_price": 150.0,
        "stop_price": 145.0,
        "target_1": 160.0,
        "planned_shares": 10,
        "created_at": "2026-04-11T09:30:00",
        "updated_at": "2026-04-11T09:30:00",
    }
    if pnl is not None:
        trade["pnl_dollars"] = pnl
    if ib_child_ids:
        trade["ib_child_order_ids"] = json.dumps(ib_child_ids)
    return insert_shadow_trade(trade, db_path)


# ═══════════════════════════════════════════════════════════════════════════
# Task 1 — IB Trade Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestIBTradeLifecycle:
    """Verify full IB paper trade lifecycle from entry through close."""

    def test_full_ib_paper_trade_lifecycle(self, tmp_db):
        """IB trade: insert -> query -> close with P&L."""
        child_ids = ["101", "102"]
        trade_id = _insert_test_trade(
            tmp_db, ticker="MSFT", broker="ib",
            ib_child_ids=child_ids,
        )

        # Verify the row was written with IB-specific fields
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM shadow_trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()

        assert row is not None
        assert row["broker"] == "ib"
        assert json.loads(row["ib_child_order_ids"]) == child_ids

        # get_open_shadow_trades should return it
        open_trades = get_open_shadow_trades(tmp_db)
        ib_trades = [t for t in open_trades if t["trade_id"] == trade_id]
        assert len(ib_trades) == 1
        assert ib_trades[0]["broker"] == "ib"

        # Close the trade and verify P&L is computed
        close_shadow_trade(
            trade_id,
            exit_price=160.0,
            exit_time="2026-04-12T15:00:00",
            exit_reason="target_1_hit",
            pnl_dollars=100.0,
            pnl_pct=6.67,
            db_path=tmp_db,
        )

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM shadow_trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()

        assert row["status"] == "closed"
        assert row["pnl_dollars"] == 100.0
        assert row["actual_exit_price"] == 160.0

    def test_full_alpaca_paper_trade_lifecycle_unchanged(self, tmp_db):
        """Alpaca trade lifecycle is unaffected by IB additions."""
        trade_id = _insert_test_trade(
            tmp_db, ticker="GOOG", broker="alpaca",
        )

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM shadow_trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()

        assert row["broker"] == "alpaca"
        assert row["ib_child_order_ids"] is None

        # Close it
        close_shadow_trade(
            trade_id,
            exit_price=155.0,
            exit_time="2026-04-12T15:00:00",
            exit_reason="target_1_hit",
            pnl_dollars=50.0,
            pnl_pct=3.33,
            db_path=tmp_db,
        )

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM shadow_trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()

        assert row["status"] == "closed"
        assert row["pnl_dollars"] == 50.0


# ═══════════════════════════════════════════════════════════════════════════
# Task 2 — Cross-Broker Position Counting
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossBrokerPositionCounting:
    """Verify positions from both brokers are counted together."""

    def test_governor_counts_both_brokers(self, tmp_db):
        """get_open_shadow_trades includes both IB and Alpaca trades."""
        # Insert 3 IB trades
        for i in range(3):
            _insert_test_trade(tmp_db, ticker=f"IB{i}", broker="ib")
        # Insert 4 Alpaca trades
        for i in range(4):
            _insert_test_trade(tmp_db, ticker=f"ALP{i}", broker="alpaca")

        open_trades = get_open_shadow_trades(tmp_db)
        assert len(open_trades) == 7

    def test_reconciler_checks_correct_broker_per_trade(self, tmp_db):
        """Each trade stores its broker — reconciler can filter by broker."""
        ib_id = _insert_test_trade(tmp_db, ticker="AMZN", broker="ib")
        alp_id = _insert_test_trade(tmp_db, ticker="META", broker="alpaca")

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            # Reconciler would filter by broker for each trade
            ib_rows = conn.execute(
                "SELECT * FROM shadow_trades WHERE broker = 'ib' AND status = 'open'"
            ).fetchall()
            alp_rows = conn.execute(
                "SELECT * FROM shadow_trades WHERE broker = 'alpaca' AND status = 'open'"
            ).fetchall()

        assert len(ib_rows) == 1
        assert ib_rows[0]["ticker"] == "AMZN"
        assert len(alp_rows) == 1
        assert alp_rows[0]["ticker"] == "META"

    def test_executor_duplicate_check_spans_brokers(self, tmp_db):
        """Duplicate check via get_open_shadow_trades sees IB trades too."""
        _insert_test_trade(tmp_db, ticker="AAPL", broker="ib")

        open_trades = get_open_shadow_trades(tmp_db)
        open_tickers = [t["ticker"] for t in open_trades]
        # The duplicate check in open_shadow_trade uses this list
        assert "AAPL" in open_tickers

    def test_mixed_broker_pnl_aggregation(self, tmp_db):
        """Total P&L aggregates across both brokers."""
        # 2 closed IB trades: +100, -50
        _insert_test_trade(tmp_db, ticker="IB1", broker="ib",
                           status="closed", pnl=100.0)
        _insert_test_trade(tmp_db, ticker="IB2", broker="ib",
                           status="closed", pnl=-50.0)
        # 2 closed Alpaca trades: +200, -30
        _insert_test_trade(tmp_db, ticker="ALP1", broker="alpaca",
                           status="closed", pnl=200.0)
        _insert_test_trade(tmp_db, ticker="ALP2", broker="alpaca",
                           status="closed", pnl=-30.0)

        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) as total "
                "FROM shadow_trades WHERE status = 'closed' "
                "AND pnl_dollars IS NOT NULL"
            ).fetchone()

        assert row[0] == 220.0


# ═══════════════════════════════════════════════════════════════════════════
# Task 3 — Config Progression
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigProgression:
    """Verify _select_paper_broker handles all config states correctly."""

    @patch("src.shadow_trading.executor.load_config")
    def test_no_ib_config_is_pure_alpaca(self, mock_cfg):
        """No IB config at all -> pure Alpaca."""
        from src.shadow_trading.executor import _select_paper_broker
        config = {"live_trading": {}}
        broker_name, broker_obj = _select_paper_broker(config, 90)
        assert broker_name == "alpaca"
        assert broker_obj is None

    @patch("src.shadow_trading.executor.load_config")
    def test_shadow_mode_does_not_route(self, mock_cfg):
        """shadow_mode=True without paper_routing -> stays Alpaca."""
        from src.shadow_trading.executor import _select_paper_broker
        config = {"live_trading": {"ib": {"shadow_mode": True}}}
        broker_name, broker_obj = _select_paper_broker(config, 90)
        assert broker_name == "alpaca"
        assert broker_obj is None

    @patch("src.shadow_trading.executor.load_config")
    def test_paper_routing_splits_by_score(self, mock_cfg):
        """paper_routing=True with threshold splits by score."""
        from src.shadow_trading.executor import _select_paper_broker

        config = {
            "live_trading": {
                "ib": {
                    "paper_routing": True,
                    "paper_routing_threshold": 80,
                }
            }
        }

        # Score above threshold -> IB
        mock_broker = MagicMock()
        with patch("src.trading.ib_broker.IBBroker", return_value=mock_broker):
            broker_name, broker_obj = _select_paper_broker(config, 85)
        assert broker_name == "ib"
        assert broker_obj is mock_broker

        # Score below threshold -> Alpaca
        broker_name, broker_obj = _select_paper_broker(config, 72)
        assert broker_name == "alpaca"
        assert broker_obj is None

    @patch("src.shadow_trading.executor.load_config")
    def test_paper_routing_takes_precedence_over_shadow(self, mock_cfg):
        """paper_routing=True + shadow_mode=True -> paper_routing wins."""
        from src.shadow_trading.executor import _select_paper_broker

        config = {
            "live_trading": {
                "ib": {
                    "shadow_mode": True,
                    "paper_routing": True,
                    "paper_routing_threshold": 80,
                }
            }
        }

        mock_broker = MagicMock()
        with patch("src.trading.ib_broker.IBBroker", return_value=mock_broker):
            broker_name, broker_obj = _select_paper_broker(config, 90)
        assert broker_name == "ib"
        assert broker_obj is mock_broker


# ═══════════════════════════════════════════════════════════════════════════
# Task 4 — IB Failure Recovery
# ═══════════════════════════════════════════════════════════════════════════

class TestIBFailureRecovery:
    """Verify IB Gateway failures fall back gracefully to Alpaca."""

    @patch("src.shadow_trading.executor.load_config")
    def test_ib_down_falls_back_to_alpaca(self, mock_cfg):
        """IB Gateway unreachable -> fall back to Alpaca."""
        from src.shadow_trading.executor import _select_paper_broker

        config = {
            "live_trading": {
                "ib": {
                    "paper_routing": True,
                    "paper_routing_threshold": 80,
                }
            }
        }

        mock_broker = MagicMock()
        mock_broker._ensure_connected.side_effect = ConnectionError("Gateway down")
        with patch("src.trading.ib_broker.IBBroker", return_value=mock_broker):
            broker_name, broker_obj = _select_paper_broker(config, 90)

        assert broker_name == "alpaca"
        assert broker_obj is None

    @patch("src.shadow_trading.executor.load_config")
    def test_ib_recovery_resumes_routing(self, mock_cfg):
        """After IB recovers, routing resumes to IB."""
        from src.shadow_trading.executor import _select_paper_broker

        config = {
            "live_trading": {
                "ib": {
                    "paper_routing": True,
                    "paper_routing_threshold": 80,
                }
            }
        }

        # First call: IB is down
        mock_broker_down = MagicMock()
        mock_broker_down._ensure_connected.side_effect = ConnectionError("Gateway down")
        with patch("src.trading.ib_broker.IBBroker", return_value=mock_broker_down):
            name1, obj1 = _select_paper_broker(config, 90)
        assert name1 == "alpaca"
        assert obj1 is None

        # Second call: IB recovers
        mock_broker_up = MagicMock()
        mock_broker_up._ensure_connected.return_value = None
        with patch("src.trading.ib_broker.IBBroker", return_value=mock_broker_up):
            name2, obj2 = _select_paper_broker(config, 90)
        assert name2 == "ib"
        assert obj2 is mock_broker_up

    def test_mixed_broker_trades_coexist(self, tmp_db):
        """IB and Alpaca trades coexist peacefully in the same DB."""
        ib_ids = [
            _insert_test_trade(tmp_db, ticker="IB1", broker="ib"),
            _insert_test_trade(tmp_db, ticker="IB2", broker="ib"),
        ]
        alp_ids = [
            _insert_test_trade(tmp_db, ticker="ALP1", broker="alpaca"),
            _insert_test_trade(tmp_db, ticker="ALP2", broker="alpaca"),
        ]

        open_trades = get_open_shadow_trades(tmp_db)
        assert len(open_trades) == 4

        brokers = {t["broker"] for t in open_trades}
        assert brokers == {"ib", "alpaca"}

        # Verify each trade has the correct broker
        for t in open_trades:
            if t["ticker"].startswith("IB"):
                assert t["broker"] == "ib"
            else:
                assert t["broker"] == "alpaca"


# ═══════════════════════════════════════════════════════════════════════════
# Task 6 — Multi-Broker API Responses
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiBrokerAPIResponses:
    """Verify API-layer contracts for multi-broker support."""

    def test_shadow_trades_include_broker_field(self, tmp_db):
        """Every trade dict from get_open_shadow_trades has a 'broker' key."""
        _insert_test_trade(tmp_db, ticker="IB1", broker="ib")
        _insert_test_trade(tmp_db, ticker="ALP1", broker="alpaca")

        open_trades = get_open_shadow_trades(tmp_db)
        for t in open_trades:
            assert "broker" in t, f"Trade {t['trade_id']} missing 'broker' key"

    def test_ib_columns_present_in_schema(self):
        """Schema registry has all IB-specific columns on shadow_trades."""
        table = TABLES["shadow_trades"]
        col_names = [c.name for c in table.columns]

        assert "broker" in col_names
        assert "ib_child_order_ids" in col_names
        assert "broker_order_id" in col_names
        assert "ib_perm_id" in col_names

    def test_ib_status_map_covers_all_states(self):
        """IB_STATUS_MAP covers the key IB order statuses."""
        required_statuses = {"presubmitted", "submitted", "filled", "cancelled", "inactive"}
        mapped_statuses = set(IB_STATUS_MAP.keys())
        assert required_statuses.issubset(mapped_statuses), (
            f"Missing IB statuses: {required_statuses - mapped_statuses}"
        )

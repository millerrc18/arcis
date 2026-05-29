"""Tests for the live trading dual-execution system.

Covers:
- Dual execution (paper + live)
- Source tagging in shadow_trades
- Safety guards (capital, daily loss, LLM requirement)
- Live-specific risk parameters
- CLI commands
- Telegram notification source parameter
"""

import sqlite3
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with schema."""
    db_path = str(tmp_path / "test.sqlite3")
    from src.journal.store import initialize_database
    initialize_database(db_path)
    return db_path


@pytest.fixture
def live_config():
    """Config dict with live trading enabled."""
    return {
        "live_trading": {
            "enabled": True,
            "api_key": "test-live-key",
            "secret_key": "test-live-secret",
            "starting_capital": 100,
            "max_open_positions": 2,
            "risk": {
                "planned_risk_pct_max": 0.02,
                "stop_atr_multiplier": 1.0,
                "target_atr_multiplier": 2.0,
                "timeout_days": 7,
            },
            "min_score": None,
            "max_price": None,
        },
        "shadow_trading": {
            "enabled": True,
            "max_positions": 10,
            "timeout_days": 15,
        },
        "risk_governor": {"enabled": False},
    }


@pytest.fixture
def mock_packet():
    """A mock TradePacket with LLM conviction."""
    ps = SimpleNamespace(
        allocation_dollars=50.0,
        allocation_pct=0.5,
        estimated_risk_dollars=5.0,
        entry_price=50.0,
        stop_level=48.0,
        target_1=54.0,
        shares=1,
    )
    packet = SimpleNamespace(
        ticker="AAPL",
        company_name="Apple Inc.",
        entry_zone="50.00",
        stop_invalidation="48.00",
        targets="54.00/58.00",
        position_sizing=ps,
        confidence=7.0,
        llm_conviction=8,
        setup_type="breakout",
        recommendation="Buy",
        deeper_analysis="Test thesis",
        expected_hold_period="5-7 days",
        event_risk="Normal",
    )
    return packet


@pytest.fixture
def mock_features():
    return {
        "atr_14": 2.0,
        "event_risk_level": "none",
        "_score": 75,
        "setup_type": "breakout",
        "setup_confidence": 0.8,
    }


# ── Source Column Migration ──────────────────────────────────────────

class TestSourceColumnMigration:
    def test_source_column_exists_after_init(self, tmp_db):
        """The source column should exist after initialize_database."""
        with sqlite3.connect(tmp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(shadow_trades)")
            columns = [row[1] for row in cursor.fetchall()]
        assert "source" in columns

    def test_source_default_is_paper(self, tmp_db):
        """Default source value should be 'paper'."""
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, created_at, updated_at) "
                "VALUES ('test-1', 'AAPL', '2024-01-01', '2024-01-01')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT source FROM shadow_trades WHERE trade_id = 'test-1'"
            ).fetchone()
        assert row[0] == "paper"

    def test_idempotent_migration(self, tmp_db):
        """Running initialize_database twice should not fail."""
        from src.journal.store import initialize_database
        initialize_database(tmp_db)
        initialize_database(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(shadow_trades)")
            columns = [row[1] for row in cursor.fetchall()]
        assert "source" in columns


# ── Paper Trade Source Tagging ───────────────────────────────────────

class TestPaperSourceTagging:
    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.get_account_info",
           return_value={"buying_power": 100000.0, "equity": 100000.0, "cash": 100000.0})
    def test_paper_trade_tagged_as_paper(self, mock_acct, mock_price, mock_config,
                                          tmp_db, mock_packet, mock_features, live_config):
        """Paper trades should be tagged with source='paper'."""
        mock_config.return_value = live_config
        mock_price.return_value = 50.0

        # Mock Alpaca to fail so trade is recorded without Alpaca
        # Mock LLM validator to pass (since safety fix now rejects trades on validator error)
        with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
            with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=Exception("test")):
                with patch("src.shadow_trading.alpaca_adapter.place_paper_entry", side_effect=Exception("test")):
                    from src.shadow_trading.executor import open_shadow_trade
                    trade_id = open_shadow_trade("rec-1", mock_packet, mock_features, tmp_db)

        assert trade_id is not None

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT source FROM shadow_trades WHERE trade_id = ?",
                (trade_id,),
            ).fetchone()
        assert row is not None
        assert row["source"] == "paper"


# ── Live Trade Safety Guards ─────────────────────────────────────────

class TestLiveSafetyGuards:
    @patch("src.shadow_trading.executor.load_config")
    def test_live_disabled_returns_none(self, mock_config, mock_packet, mock_features):
        """open_live_trade returns None when live trading is disabled."""
        mock_config.return_value = {"live_trading": {"enabled": False}}
        from src.shadow_trading.executor import open_live_trade
        result = open_live_trade("rec-1", mock_packet, mock_features)
        assert result is None

    @patch("src.shadow_trading.executor.load_config")
    def test_no_llm_conviction_returns_none(self, mock_config, live_config, mock_features):
        """open_live_trade rejects trades without LLM conviction."""
        mock_config.return_value = live_config

        # Packet without llm_conviction
        packet = SimpleNamespace(
            ticker="AAPL",
            entry_zone="50.00",
            stop_invalidation="48.00",
            targets="54.00/58.00",
            position_sizing=SimpleNamespace(allocation_dollars=50.0),
            # No llm_conviction attribute
        )

        from src.shadow_trading.executor import open_live_trade
        result = open_live_trade("rec-1", packet, mock_features)
        assert result is None

    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    def test_capital_guard_halts_trading(self, mock_acct, mock_config,
                                         live_config, mock_packet, mock_features):
        """Halt live trading if equity < 50% of starting capital."""
        mock_config.return_value = live_config
        # Equity at $40 which is < 50% of $100 starting
        mock_acct.return_value = {
            "equity": 40.0,
            "cash": 40.0,
            "buying_power": 40.0,
        }

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=False):
            from src.shadow_trading.executor import open_live_trade
            result = open_live_trade("rec-1", mock_packet, mock_features)

        assert result is None

    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.executor.get_open_shadow_trades")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    def test_daily_loss_guard_halts_trading(self, mock_price, mock_open_trades,
                                            mock_acct, mock_config,
                                            live_config, mock_packet, mock_features, tmp_db):
        """Halt live trading if daily P&L exceeds -5% of capital."""
        mock_config.return_value = live_config
        mock_acct.return_value = {
            "equity": 90.0,
            "cash": 40.0,
            "buying_power": 40.0,
        }

        # #239: The daily loss guard queries the DB directly (not get_open_shadow_trades),
        # so we must INSERT a losing live trade into tmp_db for the guard to find.
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, source, "
                "actual_entry_price, entry_price, planned_shares, direction, created_at, updated_at) "
                "VALUES (?, ?, 'open', 'live', 60.0, 60.0, 1, 'long', ?, ?)",
                ("loss-trade-1", "TSLA", f"{today}T09:30:00", f"{today}T09:30:00"),
            )

        mock_open_trades.return_value = []
        mock_price.return_value = 53.0  # $7 loss on 1 share (7% of $100)

        with patch("src.notifications.telegram.is_telegram_enabled", return_value=False):
            from src.shadow_trading.executor import open_live_trade
            result = open_live_trade("rec-1", mock_packet, mock_features, tmp_db)

        assert result is None

    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.executor.get_open_shadow_trades")
    def test_position_limit_enforced(self, mock_open_trades, mock_acct, mock_config,
                                      live_config, mock_packet, mock_features, tmp_db):
        """Halt if at max live positions."""
        mock_config.return_value = live_config
        mock_acct.return_value = {
            "equity": 100.0,
            "cash": 50.0,
            "buying_power": 50.0,
        }

        # 2 open live trades (max is 2)
        mock_open_trades.return_value = [
            {"ticker": "MSFT", "source": "live"},
            {"ticker": "GOOGL", "source": "live"},
        ]

        from src.shadow_trading.executor import open_live_trade
        result = open_live_trade("rec-1", mock_packet, mock_features, tmp_db)
        assert result is None

    @patch("src.shadow_trading.executor.load_config")
    def test_min_score_filter(self, mock_config, mock_packet, mock_features):
        """Reject live trades below min_score threshold."""
        config = {
            "live_trading": {
                "enabled": True,
                "min_score": 80,  # Score is 75 in mock_features
                "api_key": "test",
                "secret_key": "test",
                "starting_capital": 100,
                "max_open_positions": 2,
                "risk": {},
            },
        }
        mock_config.return_value = config

        from src.shadow_trading.executor import open_live_trade
        result = open_live_trade("rec-1", mock_packet, mock_features)
        assert result is None

    @patch("src.shadow_trading.executor.load_config")
    def test_max_price_filter(self, mock_config, mock_features):
        """Reject live trades above max_price threshold."""
        config = {
            "live_trading": {
                "enabled": True,
                "max_price": 30.0,  # Entry is $50
                "min_score": None,
                "api_key": "test",
                "secret_key": "test",
                "starting_capital": 100,
                "max_open_positions": 2,
                "risk": {},
            },
        }
        mock_config.return_value = config

        packet = SimpleNamespace(
            ticker="AAPL",
            entry_zone="50.00",
            stop_invalidation="48.00",
            targets="54.00/58.00",
            position_sizing=SimpleNamespace(allocation_dollars=50.0),
            llm_conviction=8,
        )

        from src.shadow_trading.executor import open_live_trade
        result = open_live_trade("rec-1", packet, mock_features)
        assert result is None


# ── Live Trade Execution ─────────────────────────────────────────────

class TestLiveTradeExecution:
    @patch("src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
           return_value={"verified": True, "status": "accepted",
                         "attempts": 1, "order": {}})
    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.executor.get_open_shadow_trades")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.place_live_bracket")
    @patch("src.notifications.telegram.is_telegram_enabled", return_value=False)
    def test_successful_live_trade(self, mock_tg, mock_place, mock_price,
                                    mock_open_trades, mock_acct, mock_config,
                                    mock_verify,
                                    live_config, mock_packet, mock_features, tmp_db):
        """Successful live trade should be recorded with source='live'."""
        mock_config.return_value = live_config
        mock_acct.return_value = {
            "equity": 100.0,
            "cash": 100.0,
            "buying_power": 100.0,
        }
        mock_open_trades.return_value = []  # No existing trades
        mock_price.return_value = 50.0
        mock_place.return_value = {
            "order_id": "live-order-123",
            "symbol": "AAPL",
            "qty": 1,
            "side": "buy",
            "type": "market",
            "status": "accepted",
            "filled_avg_price": 50.0,
            "filled_at": None,
            "created_at": None,
        }

        from src.shadow_trading.executor import open_live_trade
        trade_id = open_live_trade("rec-1", mock_packet, mock_features, tmp_db)

        assert trade_id is not None

        # Verify source is 'live' in DB
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT source, alpaca_order_id FROM shadow_trades WHERE trade_id = ?",
                (trade_id,),
            ).fetchone()
        assert row["source"] == "live"
        assert row["alpaca_order_id"] == "live-order-123"
        # LIVE-VERIFY: verify_live_order_accepted MUST have been called once
        # by AlpacaLiveBroker.place_bracket_order on the live order id.
        mock_verify.assert_called_once()
        assert mock_verify.call_args.args[0] == "live-order-123"

    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.executor.get_open_shadow_trades")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.place_live_bracket")
    def test_failed_order_not_recorded(self, mock_place, mock_price,
                                        mock_open_trades, mock_acct, mock_config,
                                        live_config, mock_packet, mock_features, tmp_db):
        """If the live order fails to submit, no trade should be recorded."""
        mock_config.return_value = live_config
        mock_acct.return_value = {
            "equity": 100.0,
            "cash": 100.0,
            "buying_power": 100.0,
        }
        mock_open_trades.return_value = []
        mock_price.return_value = 50.0
        mock_place.side_effect = Exception("Order rejected")

        from src.shadow_trading.executor import open_live_trade
        result = open_live_trade("rec-1", mock_packet, mock_features, tmp_db)
        assert result is None

        # Verify no live trade was recorded
        with sqlite3.connect(tmp_db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE source = 'live'"
            ).fetchone()[0]
        assert count == 0


# ── Live-Specific Risk Parameters ────────────────────────────────────

class TestLiveRiskParameters:
    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.executor.get_open_shadow_trades")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.place_live_bracket")
    @patch("src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
           return_value={"verified": True, "status": "accepted",
                         "attempts": 1, "order": {}})
    @patch("src.notifications.telegram.is_telegram_enabled", return_value=False)
    def test_atr_based_stop_and_target(self, mock_tg, mock_verify, mock_place,
                                        mock_price,
                                        mock_open_trades, mock_acct, mock_config,
                                        live_config, mock_packet, mock_features, tmp_db):
        """Live trades should use ATR-based stop/target from live_trading.risk."""
        mock_config.return_value = live_config
        mock_acct.return_value = {
            "equity": 100.0, "cash": 100.0, "buying_power": 100.0,
        }
        mock_open_trades.return_value = []
        mock_price.return_value = 50.0
        mock_place.return_value = {
            "order_id": "live-order-atr",
            "symbol": "AAPL",
            "qty": 1,
            "side": "buy",
            "type": "market",
            "status": "accepted",
            "filled_avg_price": 50.0,
            "filled_at": None,
            "created_at": None,
        }

        from src.shadow_trading.executor import open_live_trade
        trade_id = open_live_trade("rec-1", mock_packet, mock_features, tmp_db)

        assert trade_id is not None

        # ATR = 2.0, stop_atr_mult = 1.0, target_atr_mult = 2.0
        # entry = 50.0, stop = 50.0 - 2.0*1.0 = 48.0, target = 50.0 + 2.0*2.0 = 54.0
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT stop_price, target_1 FROM shadow_trades WHERE trade_id = ?",
                (trade_id,),
            ).fetchone()
        assert abs(row["stop_price"] - 48.0) < 0.01
        assert abs(row["target_1"] - 54.0) < 0.01


# ── Telegram Source Parameter ────────────────────────────────────────

class TestTelegramSourceParameter:
    @patch("src.notifications.telegram.send_telegram")
    @patch("src.notifications.telegram._get_telegram_config")
    def test_paper_trade_header(self, mock_cfg, mock_send):
        """Paper trade notification should show standard header."""
        mock_cfg.return_value = {"enabled": True, "bot_token": "t", "chat_id": "c"}
        mock_send.return_value = True

        from src.notifications.telegram import notify_trade_opened, TradeOpenedPayload
        notify_trade_opened(TradeOpenedPayload(
            ticker="AAPL", entry_price=50.0, stop=48.0, target=54.0,
            score=75, shares=1, source="paper"
        ))

        msg = mock_send.call_args[0][0]
        assert "TRADE OPENED" in msg
        assert "LIVE" not in msg

    @patch("src.notifications.telegram.send_telegram")
    @patch("src.notifications.telegram._get_telegram_config")
    def test_live_trade_header(self, mock_cfg, mock_send):
        """Live trade notification should show LIVE TRADE OPENED header."""
        mock_cfg.return_value = {"enabled": True, "bot_token": "t", "chat_id": "c"}
        mock_send.return_value = True

        from src.notifications.telegram import notify_trade_opened, TradeOpenedPayload
        notify_trade_opened(TradeOpenedPayload(
            ticker="AAPL", entry_price=50.0, stop=48.0, target=54.0,
            score=75, shares=1, source="live"
        ))

        msg = mock_send.call_args[0][0]
        assert "LIVE TRADE OPENED" in msg

    @patch("src.notifications.telegram.send_telegram")
    @patch("src.notifications.telegram._get_telegram_config")
    def test_default_source_is_paper(self, mock_cfg, mock_send):
        """Without source parameter, notification should be paper-style."""
        mock_cfg.return_value = {"enabled": True, "bot_token": "t", "chat_id": "c"}
        mock_send.return_value = True

        from src.notifications.telegram import notify_trade_opened, TradeOpenedPayload
        notify_trade_opened(TradeOpenedPayload(
            ticker="AAPL", entry_price=50.0, stop=48.0, target=54.0,
            score=75, shares=1
        ))

        msg = mock_send.call_args[0][0]
        assert "LIVE" not in msg


# ── CLI Commands ─────────────────────────────────────────────────────

class TestLiveCLICommands:
    def test_live_status_disabled(self, capsys):
        """live-status should indicate when live trading is disabled."""
        with patch("src.config.load_config", return_value={"live_trading": {"enabled": False}}):
            from src.main import cmd_live_status
            cmd_live_status(SimpleNamespace())
        output = capsys.readouterr().out
        assert "Disabled" in output

    @patch("src.config.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.alpaca_adapter.get_live_positions")
    def test_live_status_enabled(self, mock_positions, mock_acct, mock_config, capsys):
        """live-status should show account info when enabled."""
        mock_config.return_value = {
            "live_trading": {"enabled": True, "starting_capital": 100},
        }
        mock_acct.return_value = {
            "equity": 105.0, "cash": 55.0, "buying_power": 55.0,
            "status": "ACTIVE", "account_id": "test",
        }
        mock_positions.return_value = [
            {"symbol": "AAPL", "qty": 1, "avg_entry_price": 50.0,
             "current_price": 52.0, "unrealized_pl": 2.0, "market_value": 52.0,
             "unrealized_plpc": 0.04},
        ]

        from src.main import cmd_live_status
        cmd_live_status(SimpleNamespace())

        output = capsys.readouterr().out
        assert "105.00" in output
        assert "AAPL" in output

    def test_live_history_no_trades(self, capsys, tmp_db):
        """live-history with no trades should show appropriate message."""
        with patch("src.journal.store.initialize_database"):
            with patch("sqlite3.connect") as mock_conn:
                mock_cursor = MagicMock()
                mock_cursor.fetchall.return_value = []
                mock_conn.return_value.__enter__ = lambda s: s
                mock_conn.return_value.__exit__ = MagicMock(return_value=False)
                mock_conn.return_value.row_factory = None
                mock_conn.return_value.execute.return_value = mock_cursor

                from src.main import cmd_live_history
                cmd_live_history(SimpleNamespace(days=30))

        output = capsys.readouterr().out
        assert "No live trades" in output


# ── Dual Execution Integration ───────────────────────────────────────

class TestDualExecution:
    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    @patch("src.shadow_trading.alpaca_adapter.get_account_info",
           return_value={"buying_power": 100000.0, "equity": 100000.0, "cash": 100000.0})
    @patch("src.shadow_trading.executor.get_open_shadow_trades")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.place_live_bracket")
    @patch("src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
           return_value={"verified": True, "status": "accepted",
                         "attempts": 1, "order": {}})
    @patch("src.notifications.telegram.is_telegram_enabled", return_value=False)
    def test_paper_and_live_both_execute(self, mock_tg, mock_verify,
                                          mock_live_place, mock_price,
                                          mock_open_trades, mock_paper_acct, mock_acct,
                                          mock_config,
                                          live_config, mock_packet, mock_features, tmp_db):
        """Both paper and live trades should be created for the same recommendation."""
        mock_config.return_value = live_config
        mock_acct.return_value = {
            "equity": 100.0, "cash": 100.0, "buying_power": 100.0,
        }
        mock_open_trades.return_value = []
        mock_price.return_value = 50.0
        mock_live_place.return_value = {
            "order_id": "live-order-dual",
            "symbol": "AAPL", "qty": 1, "side": "buy", "type": "market",
            "status": "accepted", "filled_avg_price": 50.0,
            "filled_at": None, "created_at": None,
        }

        # First: paper trade (mock validator since safety fix rejects on error)
        with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
            with patch("src.shadow_trading.alpaca_adapter.place_bracket_order",
                        side_effect=Exception("test")):
                with patch("src.shadow_trading.alpaca_adapter.place_paper_entry",
                            side_effect=Exception("test")):
                    from src.shadow_trading.executor import open_shadow_trade
                    paper_id = open_shadow_trade("rec-1", mock_packet, mock_features, tmp_db)

        # Then: live trade (mock open_trades to include the paper trade)
        mock_open_trades.return_value = [
            {"ticker": "AAPL", "source": "paper", "actual_entry_price": 50.0,
             "entry_price": 50.0, "planned_shares": 1},
        ]

        from src.shadow_trading.executor import open_live_trade
        live_id = open_live_trade("rec-1", mock_packet, mock_features, tmp_db)

        assert paper_id is not None
        assert live_id is not None
        assert paper_id != live_id

        # Verify both in DB with correct sources
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            paper_row = conn.execute(
                "SELECT source FROM shadow_trades WHERE trade_id = ?", (paper_id,)
            ).fetchone()
            live_row = conn.execute(
                "SELECT source FROM shadow_trades WHERE trade_id = ?", (live_id,)
            ).fetchone()

        assert paper_row["source"] == "paper"
        assert live_row["source"] == "live"

    def test_live_duplicate_check_only_checks_live(self, tmp_db, live_config,
                                                     mock_packet, mock_features):
        """Live duplicate check should only look at live trades, not paper."""
        # Insert a paper trade for AAPL
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, source, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("paper-1", "AAPL", "open", "paper", "2024-01-01", "2024-01-01"),
            )
            conn.commit()

        with patch("src.shadow_trading.executor.load_config", return_value=live_config):
            # Fix for #272: mock validator and governor since live trades now enforce them
            with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                mock_gov = MagicMock()
                mock_gov.check_trade.return_value = {"approved": True, "effective_allocation_dollars": 50.0}
                with patch("src.risk.governor.RiskGovernor", return_value=mock_gov):
                    with patch("src.risk.governor.get_portfolio_state", return_value={}):
                        with patch("src.shadow_trading.alpaca_adapter.get_live_account_info",
                                    return_value={"equity": 100.0, "cash": 100.0, "buying_power": 100.0}):
                            with patch("src.shadow_trading.executor.get_open_shadow_trades") as mock_open:
                                # Return the paper trade only — no live duplicate
                                mock_open.return_value = [
                                    {"ticker": "AAPL", "source": "paper"},
                                ]
                                with patch("src.shadow_trading.executor._get_current_price_safe", return_value=50.0):
                                    with patch(
                                        "src.shadow_trading.alpaca_adapter.place_live_bracket"
                                    ) as mock_bracket, patch(
                                        "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
                                        return_value={"verified": True, "status": "accepted",
                                                      "attempts": 1, "order": {}},
                                    ):
                                        mock_bracket.return_value = {
                                            "order_id": "live-dup-test",
                                            "symbol": "AAPL", "qty": 1, "side": "buy",
                                            "type": "market", "order_class": "bracket",
                                            "status": "accepted", "filled_avg_price": 50.0,
                                            "legs": [],
                                        }
                                        with patch("src.notifications.telegram.is_telegram_enabled",
                                                    return_value=False):
                                            from src.shadow_trading.executor import open_live_trade
                                            result = open_live_trade(
                                                "rec-1", mock_packet, mock_features, tmp_db
                                            )

        # Should succeed — paper AAPL doesn't block live AAPL
        assert result is not None


# ── Adapter Tests ────────────────────────────────────────────────────

class TestLiveAdapter:
    @patch("src.shadow_trading.alpaca_adapter_live.load_config")
    def test_get_live_config_requires_credentials(self, mock_config):
        """_get_live_config should raise if no credentials configured."""
        mock_config.return_value = {
            "live_trading": {"enabled": True, "api_key": "", "secret_key": ""},
        }

        # Clear env vars
        import os
        env_backup = {}
        for key in ["ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY"]:
            env_backup[key] = os.environ.pop(key, None)

        try:
            from src.shadow_trading.alpaca_adapter import _get_live_config, LiveTradingError
            with pytest.raises(LiveTradingError):
                _get_live_config()
        finally:
            for key, val in env_backup.items():
                if val is not None:
                    os.environ[key] = val

    @patch("src.shadow_trading.alpaca_adapter_live.load_config")
    def test_live_trading_client_uses_paper_false(self, mock_config):
        """_get_live_trading_client should set paper=False."""
        mock_config.return_value = {
            "live_trading": {
                "enabled": True,
                "api_key": "test-key",
                "secret_key": "test-secret",
            },
        }

        # Fix for #239: remove env vars so they don't override mocked config values.
        # _get_live_config checks os.environ first, which has real keys in dev.
        import os as _os
        env_clean = {k: v for k, v in _os.environ.items()
                     if k not in ("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY")}
        with patch.dict("os.environ", env_clean, clear=True):
            with patch("alpaca.trading.client.TradingClient") as mock_tc:
                from src.shadow_trading.alpaca_adapter import _get_live_trading_client
                _get_live_trading_client()

                mock_tc.assert_called_once_with(
                    api_key="test-key",
                    secret_key="test-secret",
                    paper=False,
                )


# ── IB Shadow Integration Tests ─────────────────────────────────────

class TestIBShadowIntegration:
    """Verify IB shadow hook in executor — called when enabled, skipped when not."""

    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.get_account_info",
           return_value={"buying_power": 100000.0, "equity": 100000.0, "cash": 100000.0})
    @patch("src.trading.ib_shadow.IBShadowLogger")
    def test_shadow_hook_called_when_enabled(self, MockShadow, mock_acct,
                                              mock_price, mock_config,
                                              tmp_db, mock_packet, mock_features):
        """When ib.shadow_mode=true, shadow logger is invoked after successful paper trade."""
        config = {
            "trading": {"ib_enabled": True},  # SD#41 — opt past cold-storage gate
            "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
            "risk_governor": {"enabled": False},
            "live_trading": {"ib": {"shadow_mode": True}},
        }
        mock_config.return_value = config
        mock_price.return_value = 50.0

        # Mock a successful bracket order so the trade status is "open"
        mock_order = {
            "order_id": "test-123", "symbol": "AAPL", "qty": 1,
            "side": "buy", "type": "market", "status": "filled",
            "filled_avg_price": 50.0, "filled_at": None, "created_at": None,
            "legs": [],
        }
        with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
            with patch("src.shadow_trading.alpaca_adapter.place_bracket_order",
                       return_value=mock_order):
                with patch("src.shadow_trading.alpaca_adapter.verify_order_accepted",
                           return_value={"verified": True}):
                    from src.shadow_trading.executor import open_shadow_trade
                    trade_id = open_shadow_trade("rec-1", mock_packet, mock_features, tmp_db)

        assert trade_id is not None
        # Shadow logger should have been constructed and log_shadow_trade called
        MockShadow.assert_called_once_with(config)
        MockShadow.return_value.log_shadow_trade.assert_called_once()

    @patch("src.shadow_trading.executor.load_config")
    @patch("src.shadow_trading.executor._get_current_price_safe")
    @patch("src.shadow_trading.alpaca_adapter.get_account_info",
           return_value={"buying_power": 100000.0, "equity": 100000.0, "cash": 100000.0})
    def test_shadow_hook_skipped_when_disabled(self, mock_acct, mock_price,
                                                mock_config, tmp_db,
                                                mock_packet, mock_features):
        """When ib.shadow_mode not set, no shadow logging occurs."""
        config = {
            "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
            "risk_governor": {"enabled": False},
            "live_trading": {},  # No ib.shadow_mode
        }
        mock_config.return_value = config
        mock_price.return_value = 50.0

        with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
            with patch("src.shadow_trading.alpaca_adapter.place_bracket_order",
                       side_effect=Exception("test")):
                with patch("src.shadow_trading.alpaca_adapter.place_paper_entry",
                           side_effect=Exception("test")):
                    with patch("src.trading.ib_shadow.IBShadowLogger") as MockShadow:
                        from src.shadow_trading.executor import open_shadow_trade
                        open_shadow_trade("rec-1", mock_packet, mock_features, tmp_db)

        MockShadow.assert_not_called()

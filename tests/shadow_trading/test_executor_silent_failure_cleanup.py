"""Regression-lock tests for Sprint 0.D/D.1 executor silent-failure cleanup.

Closes: #754 (BC-1), #755 (BC-2), #756 (BC-3), #757 (BC-4), #758 (NI-1), #759 (NI-3/NI-4)

Each test class targets one tracker and must FAIL on pre-fix code.
"""
from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(
    trade_id="t-001",
    ticker="AAPL",
    exit_retry_count=0,
    shares=10,
    source="paper",
    exit_order_id=None,
):
    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "exit_retry_count": exit_retry_count,
        "shares": shares,
        "source": source,
        "exit_order_id": exit_order_id,
        "alpaca_order_id": None,
        "status": "open",
        "entry_price": 100.0,
        "actual_entry_price": 100.0,
        "exit_reason": "stop",
    }


# ---------------------------------------------------------------------------
# #754 (BC-1) — GovernorInputMissingError swallowed: must emit Telegram alert
# ---------------------------------------------------------------------------

class TestBC1GovernorInputMissingTelegramAlert:
    """#754: GovernorInputMissingError in open_live_trade must fire a Telegram
    critical-level alert, not just an ERROR log."""

    @pytest.fixture
    def live_cfg(self):
        return {
            "live_trading": {
                "enabled": True,
                "api_key": "k",
                "secret_key": "s",
                "starting_capital": 100_000,
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
            "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
            "risk_governor": {"enabled": False},
        }

    @pytest.fixture
    def mock_packet(self):
        ps = SimpleNamespace(
            allocation_dollars=500.0,
            allocation_pct=0.5,
            estimated_risk_dollars=10.0,
            entry_price=50.0,
            stop_level=48.0,
            target_1=54.0,
            shares=10,
        )
        return SimpleNamespace(
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

    @pytest.fixture
    def mock_features(self):
        return {
            "atr_14": 2.0,
            "event_risk_level": "none",
            "_score": 75,
            "traffic_light_multiplier": 1.0,
        }

    def test_governor_input_missing_fires_telegram_alert(
        self, live_cfg, mock_packet, mock_features
    ):
        """When GovernorInputMissingError fires in open_live_trade's risk block,
        a Telegram critical alert must be sent (not just an ERROR log)."""
        from src.risk.governor import GovernorInputMissingError

        with (
            patch("src.shadow_trading.executor.load_config", return_value=live_cfg),
            patch(
                "src.shadow_trading.executor._get_current_price_safe",
                return_value=50.0,
            ),
            patch("src.shadow_trading.executor._resolve_event_risk_multiplier", return_value=1.0),
            patch(
                "src.llm.validator.validate_llm_output",
                return_value=(True, ""),
            ),
            patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]),
            patch("src.shadow_trading.executor._enforce_position_cap", return_value=True),
            patch(
                "src.risk.governor.RiskGovernor",
                side_effect=GovernorInputMissingError("missing key: risk.max_risk_pct"),
            ),
            patch("src.shadow_trading.executor.send_telegram") as mock_tg,
        ):
            from src.shadow_trading.executor import open_live_trade

            result = open_live_trade("rec-1", mock_packet, mock_features)

        assert result is None, "Trade must be rejected when GovernorInputMissingError fires"
        assert mock_tg.called, (
            "Telegram alert must be sent when GovernorInputMissingError fires in "
            "open_live_trade — fix #754"
        )

    def test_governor_input_missing_telegram_message_contains_ticker(
        self, live_cfg, mock_packet, mock_features
    ):
        """The Telegram message must contain the ticker name for operator triaging."""
        from src.risk.governor import GovernorInputMissingError

        with (
            patch("src.shadow_trading.executor.load_config", return_value=live_cfg),
            patch(
                "src.shadow_trading.executor._get_current_price_safe",
                return_value=50.0,
            ),
            patch("src.shadow_trading.executor._resolve_event_risk_multiplier", return_value=1.0),
            patch(
                "src.llm.validator.validate_llm_output",
                return_value=(True, ""),
            ),
            patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]),
            patch("src.shadow_trading.executor._enforce_position_cap", return_value=True),
            patch(
                "src.risk.governor.RiskGovernor",
                side_effect=GovernorInputMissingError("missing key: risk.max_risk_pct"),
            ),
            patch("src.shadow_trading.executor.send_telegram") as mock_tg,
        ):
            from src.shadow_trading.executor import open_live_trade

            open_live_trade("rec-1", mock_packet, mock_features)

        assert mock_tg.called
        alert_msg = mock_tg.call_args[0][0]
        assert "AAPL" in alert_msg, (
            "Telegram alert must include the ticker — fix #754"
        )


# ---------------------------------------------------------------------------
# #755 (BC-2) — Stale exit-order cancel logged at WARNING; must be ERROR
# ---------------------------------------------------------------------------

class TestBC2StaleExitCancelLevel:
    """#755: Stale exit-order cancellation failure must log at ERROR not WARNING.

    The path at executor.py:2001-2010 fires when an open trade with a pending
    exit_order_id triggers an exit (stop/target) and cancel_paper_order raises.
    We drive this by:
      1. Trade is open + stop triggered (current_price < stop_price)
      2. exit_order_id is set so cancel is attempted
      3. cancel_paper_order raises an exception
    """

    def test_stale_cancel_failure_logs_at_error_not_warning(self, caplog):
        """Stale exit cancel failure must emit ERROR, not WARNING — fix #755."""
        trade = {
            "trade_id": "t-001",
            "ticker": "AAPL",
            "exit_retry_count": 0,
            "planned_shares": 10,
            "source": "paper",
            "exit_order_id": "old-order-id",
            "alpaca_order_id": None,
            "status": "open",
            "entry_price": 100.0,
            "actual_entry_price": 100.0,
            "stop_price": 95.0,
            "target_1": 110.0,
            "target_2": 0.0,
            "exit_reason": None,
            "updated_at": "2024-01-01T09:00:00",
            "created_at": "2024-01-01T09:00:00",
            "timeout_days": 15,
            "max_favorable_excursion": 0.0,
            "max_adverse_excursion": 0.0,
            "duration_days": 0,
            "time_to_mfe_days": None,
            "mfe_timestamp": None,
            "strategy_type": None,
            "recommendation_id": None,
            "desk": None,
            "ib_perm_id": None,
            "broker_order_id": None,
        }

        with (
            patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[trade]),
            patch("src.shadow_trading.executor._get_current_price_safe", return_value=94.0),
            patch("src.shadow_trading.executor.load_config", return_value={
                "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
                "risk_governor": {"enabled": False},
                "strategies": {},
            }),
            patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]),
            # Bypass qty-sync so code reaches the cancel path
            patch("src.shadow_trading.executor._sync_exit_qty", return_value=(10, None)),
            patch(
                "src.shadow_trading.alpaca_adapter.cancel_paper_order",
                side_effect=Exception("order not found — malformed order ID"),
            ),
            patch("src.shadow_trading.executor._submit_exit_order", return_value={"status": "pending"}),
            patch("src.shadow_trading.executor.update_shadow_trade"),
            patch("src.shadow_trading.executor.close_shadow_trade"),
            patch("src.shadow_trading.executor.log_and_persist"),
            caplog.at_level(logging.DEBUG, logger="src.shadow_trading.executor"),
        ):
            from src.shadow_trading.executor import check_and_manage_open_trades
            check_and_manage_open_trades()

        # Find the stale-cancel log entry
        cancel_records = [
            r for r in caplog.records
            if "Stale exit order cancellation failed" in r.message
            or "cancellation failed" in r.message.lower()
        ]
        assert cancel_records, "Expected a log record for stale cancel failure"
        levels = [r.levelname for r in cancel_records]
        assert "ERROR" in levels, (
            f"Stale exit cancel failure must log at ERROR, got {levels} — fix #755"
        )
        assert "WARNING" not in levels, (
            f"Stale exit cancel failure must NOT log at WARNING, got {levels} — fix #755"
        )


# ---------------------------------------------------------------------------
# #756 (BC-3) — yfinance call in _check_sector_exposure must use TTL cache
# ---------------------------------------------------------------------------

class TestBC3SectorExposureYfinanceCache:
    """#756: yfinance call in _check_sector_exposure must be cached (TTL) so
    repeated calls within the TTL do not make duplicate outbound network calls."""

    def test_yfinance_called_only_once_per_ticker_within_ttl(self):
        """Two consecutive calls to _check_sector_exposure with the same ticker
        should only call yf.Ticker once (TTL cache hit on second call).

        Regression-lock: call count <= 1 per ticker within TTL window.
        """
        import importlib

        call_count = {"n": 0}

        class _FakeTicker:
            def __init__(self, ticker):
                call_count["n"] += 1

            @property
            def info(self):
                return {"sector": "Technology"}

        open_trade = {
            "trade_id": "t-001",
            "ticker": "AAPL",
            "status": "open",
            "source": "paper",
        }

        with (
            patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[open_trade]),
            patch("src.notifications.telegram.is_telegram_enabled", return_value=True),
            patch("src.notifications.telegram.notify_exposure_alert"),
            patch("yfinance.Ticker", _FakeTicker),
        ):
            # Import fresh to pick up current state
            import src.shadow_trading.executor as _mod

            # Clear the cache so test is isolated
            if hasattr(_mod, "_sector_cache"):
                _mod._sector_cache.clear()

            _mod._check_sector_exposure()
            first_count = call_count["n"]

            # Second call — should be cache hit, no new yfinance call
            _mod._check_sector_exposure()
            second_count = call_count["n"]

        assert second_count == first_count, (
            f"yfinance called {second_count} times; expected {first_count} (cache hit on 2nd call) — fix #756"
        )


# ---------------------------------------------------------------------------
# #757 (BC-4) — Milestone/streak DB errors must log at WARNING not DEBUG
# ---------------------------------------------------------------------------

class TestBC4MilestoneStreakDBErrorLevel:
    """#757: DB errors in _check_close_milestones and _check_loss_streak must
    log at WARNING, not DEBUG."""

    def test_milestone_db_error_logs_at_warning(self, caplog):
        """DB OperationalError in _check_close_milestones must log at WARNING — fix #757."""
        import sqlite3 as _sqlite3

        with (
            patch("src.notifications.telegram.is_telegram_enabled", return_value=True),
            patch(
                "src.shadow_trading.executor.connect_db",
                side_effect=_sqlite3.OperationalError("database is locked"),
            ),
            caplog.at_level(logging.DEBUG, logger="src.shadow_trading.executor"),
        ):
            from src.shadow_trading import executor as _mod
            _mod._check_close_milestones()

        milestone_records = [
            r for r in caplog.records
            if "MILESTONE" in r.message or "milestone" in r.message.lower()
        ]
        assert milestone_records, "Expected a log record for milestone check failure"
        levels = [r.levelname for r in milestone_records]
        assert "WARNING" in levels, (
            f"Milestone DB error must log at WARNING, got {levels} — fix #757"
        )
        assert "DEBUG" not in levels, (
            f"Milestone DB error must NOT log at DEBUG, got {levels} — fix #757"
        )

    def test_streak_db_error_logs_at_warning(self, caplog):
        """DB OperationalError in _check_loss_streak must log at WARNING — fix #757."""
        import sqlite3 as _sqlite3

        with (
            patch("src.notifications.telegram.is_telegram_enabled", return_value=True),
            patch(
                "src.shadow_trading.executor.connect_db",
                side_effect=_sqlite3.OperationalError("database is locked"),
            ),
            caplog.at_level(logging.DEBUG, logger="src.shadow_trading.executor"),
        ):
            from src.shadow_trading import executor as _mod
            _mod._check_loss_streak()

        streak_records = [
            r for r in caplog.records
            if "STREAK" in r.message or "streak" in r.message.lower()
        ]
        assert streak_records, "Expected a log record for streak check failure"
        levels = [r.levelname for r in streak_records]
        assert "WARNING" in levels, (
            f"Streak DB error must log at WARNING, got {levels} — fix #757"
        )
        assert "DEBUG" not in levels, (
            f"Streak DB error must NOT log at DEBUG, got {levels} — fix #757"
        )


# ---------------------------------------------------------------------------
# #758 (NI-1) — _retry_exit qty_mismatch else branch must increment counter
# ---------------------------------------------------------------------------

class TestNI1RetryExitCounterIncrement:
    """#758: In _retry_exit, the non-qty-mismatch else branch must increment
    exit_retry_count so the loop terminates if reconcile resets status."""

    def test_non_qty_mismatch_exception_increments_retry_counter(self, tmp_path):
        """When _submit_exit_order raises a generic (non-qty-mismatch) exception,
        exit_retry_count must be incremented in the DB update — fix #758."""
        db_path = str(tmp_path / "test.sqlite3")
        from src.journal.store import initialize_database

        initialize_database(db_path)

        # Insert a trade with exit_retry_count=0
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, planned_shares, entry_price, "
                " created_at, updated_at, exit_retry_count) "
                "VALUES ('t-001','AAPL','open',10,100.0,"
                "       '2024-01-01','2024-01-01',0)"
            )
            conn.commit()

        trade = {
            "trade_id": "t-001",
            "ticker": "AAPL",
            "exit_retry_count": 0,
            "planned_shares": 10,
            "source": "paper",
            "exit_order_id": None,
            "alpaca_order_id": None,
            "status": "open",
            "entry_price": 100.0,
            "actual_entry_price": 100.0,
            "exit_reason": "stop",
        }

        with (
            patch(
                "src.shadow_trading.executor._submit_exit_order",
                side_effect=RuntimeError("generic broker error — not qty mismatch"),
            ),
            patch("src.shadow_trading.executor.log_and_persist"),
            patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value={}),
            patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=None),
        ):
            from src.shadow_trading.executor import _retry_exit

            _retry_exit(trade, db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT exit_retry_count FROM shadow_trades WHERE trade_id = 't-001'"
            ).fetchone()

        # The counter must have been incremented (pre-fix or new), so it is >= 1
        assert row is not None
        assert row[0] >= 1, (
            f"exit_retry_count must be >= 1 after a non-qty-mismatch exception, got {row[0]} — fix #758"
        )


# ---------------------------------------------------------------------------
# #759 (NI-3/NI-4) — live-trade DB-error must fire Telegram critical alert
# ---------------------------------------------------------------------------

class TestNI34LiveTradeDBErrorTelegramAlert:
    """#759: When get_open_shadow_trades raises (DB locked) in the live-trade
    position-check / dup-check paths, a Telegram critical alert must fire."""

    @pytest.fixture
    def live_cfg(self):
        return {
            "live_trading": {
                "enabled": True,
                "api_key": "k",
                "secret_key": "s",
                "starting_capital": 100_000,
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
            "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
            "risk_governor": {"enabled": False},
        }

    @pytest.fixture
    def mock_packet(self):
        ps = SimpleNamespace(
            allocation_dollars=500.0,
            allocation_pct=0.5,
            estimated_risk_dollars=10.0,
            entry_price=50.0,
            stop_level=48.0,
            target_1=54.0,
            shares=10,
        )
        return SimpleNamespace(
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

    @pytest.fixture
    def mock_features(self):
        return {
            "atr_14": 2.0,
            "event_risk_level": "none",
            "_score": 75,
            "traffic_light_multiplier": 1.0,
        }

    def _mock_live_broker(self, live_cfg):
        """Return a mock live broker that passes the capital guard."""
        mock_acct = SimpleNamespace(
            equity=live_cfg["live_trading"]["starting_capital"],
            cash=live_cfg["live_trading"]["starting_capital"],
            buying_power=live_cfg["live_trading"]["starting_capital"],
            portfolio_value=live_cfg["live_trading"]["starting_capital"],
        )
        mock_broker = MagicMock()
        mock_broker.get_account.return_value = mock_acct
        mock_broker.get_open_orders.return_value = []
        return mock_broker

    def test_position_check_db_error_fires_telegram_alert(
        self, live_cfg, mock_packet, mock_features
    ):
        """DB error in the position-limit check must send a Telegram alert — fix #759."""
        import sqlite3 as _sqlite3

        mock_broker = self._mock_live_broker(live_cfg)

        with (
            patch("src.shadow_trading.executor.load_config", return_value=live_cfg),
            patch("src.shadow_trading.executor._get_current_price_safe", return_value=50.0),
            patch("src.shadow_trading.executor._resolve_event_risk_multiplier", return_value=1.0),
            patch("src.llm.validator.validate_llm_output", return_value=(True, "")),
            patch("src.trading.broker_factory.get_live_broker", return_value=mock_broker),
            patch(
                "src.shadow_trading.executor.get_open_shadow_trades",
                side_effect=_sqlite3.OperationalError("database is locked"),
            ),
            patch("src.shadow_trading.executor._enforce_position_cap", return_value=True),
            patch("src.shadow_trading.executor.send_telegram") as mock_tg,
        ):
            from src.shadow_trading.executor import open_live_trade

            result = open_live_trade("rec-1", mock_packet, mock_features)

        assert result is None, "Trade must be rejected on DB error"
        assert mock_tg.called, (
            "Telegram alert must fire when get_open_shadow_trades raises in "
            "live-trade position check — fix #759"
        )

    def test_db_error_telegram_message_contains_ticker(
        self, live_cfg, mock_packet, mock_features
    ):
        """The DB-error Telegram message must identify the ticker — fix #759."""
        import sqlite3 as _sqlite3

        mock_broker = self._mock_live_broker(live_cfg)

        with (
            patch("src.shadow_trading.executor.load_config", return_value=live_cfg),
            patch("src.shadow_trading.executor._get_current_price_safe", return_value=50.0),
            patch("src.shadow_trading.executor._resolve_event_risk_multiplier", return_value=1.0),
            patch("src.llm.validator.validate_llm_output", return_value=(True, "")),
            patch("src.trading.broker_factory.get_live_broker", return_value=mock_broker),
            patch(
                "src.shadow_trading.executor.get_open_shadow_trades",
                side_effect=_sqlite3.OperationalError("database is locked"),
            ),
            patch("src.shadow_trading.executor._enforce_position_cap", return_value=True),
            patch("src.shadow_trading.executor.send_telegram") as mock_tg,
        ):
            from src.shadow_trading.executor import open_live_trade

            open_live_trade("rec-1", mock_packet, mock_features)

        assert mock_tg.called
        alert_msg = mock_tg.call_args[0][0]
        assert "AAPL" in alert_msg, (
            "DB-error Telegram alert must include the ticker — fix #759"
        )

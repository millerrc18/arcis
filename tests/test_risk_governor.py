"""Tests for the risk governor."""

import pytest
from pathlib import Path
from unittest.mock import patch


# #647 — Removed the autouse `_opt_in_activity_writes` fixture.
# It set ARCIS_LOG_ACTIVITY_IN_PYTEST=1 for the whole file (intended to support
# one tier-transition test) but never monkeypatched DB_PATH. Result: every test
# in this file wrote real rows to the production activity_log table — 562+
# pollution rows accumulated over weeks before discovery on 2026-04-24.
#
# The principle: opt-in to writes MUST be paired with redirection of writes.
# If a future test genuinely needs log_activity persistence, it should:
#   1. Patch src.utils.activity_logger.DB_PATH and the bound default in
#      log_activity (or pass db_path explicitly to the call site)
#   2. Set ARCIS_LOG_ACTIVITY_IN_PYTEST=1 inside that one test
# See test_pollution_regression in tests/test_activity_log_isolation.py.


@pytest.fixture
def governor(tmp_path, monkeypatch):
    from src.risk.governor import RiskGovernor
    from src.risk import governor as gov_module

    monkeypatch.setattr(gov_module, "_HALT_FILE", str(tmp_path / "test_halt"))
    config = {
        "risk_governor": {
            "enabled": True,
            "max_daily_loss_pct": 0.03,
            "max_position_pct": 0.10,
            "max_open_positions": 10,
            "max_sector_pct": 0.30,
            "max_correlated": 3,
            "vol_halt_pct": 35.0,
        }
    }
    return RiskGovernor(config)


@pytest.fixture
def base_portfolio():
    return {
        "equity": 5000,
        "cash": 3000,
        "open_positions": [],
        "open_count": 0,
        "sector_exposure": {},
        "daily_pnl": 0,
        "daily_pnl_pct": 0,
    }


class TestDailyLossHalt:
    def test_daily_loss_exceeds_limit(self, governor, base_portfolio):
        base_portfolio["daily_pnl_pct"] = -0.031  # 3.1% loss
        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is False
        assert "daily loss" in result["rejection_reason"].lower()

    def test_daily_loss_within_limit(self, governor, base_portfolio):
        base_portfolio["daily_pnl_pct"] = -0.02  # 2% loss
        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is True


class TestPositionSizeLimit:
    def test_oversized_position_rejected(self, governor, base_portfolio):
        # $600 on $5000 portfolio = 12% > 10% limit
        result = governor.check_trade("AAPL", 600, {}, base_portfolio)
        assert result["approved"] is False
        assert "position size" in result["rejection_reason"].lower()

    def test_normal_position_approved(self, governor, base_portfolio):
        # $400 on $5000 = 8% < 10%
        result = governor.check_trade("AAPL", 400, {}, base_portfolio)
        assert result["approved"] is True


class TestMaxPositions:
    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    def test_at_limit_rejected(self, mock_cfg, governor, base_portfolio):
        base_portfolio["open_count"] = 10
        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is False
        assert "position count" in result["rejection_reason"].lower()

    def test_below_limit_approved(self, governor, base_portfolio):
        base_portfolio["open_count"] = 4
        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is True

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": True, "max_positions": 50}})
    def test_bootcamp_override_allows_more_positions(self, mock_cfg, governor, base_portfolio):
        base_portfolio["open_count"] = 20
        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is True


class TestSectorConcentration:
    def test_sector_exceeds_limit(self, governor, base_portfolio):
        base_portfolio["sector_exposure"] = {"Technology": 0.28}
        # Adding 5% more tech would be 33% > 30%
        result = governor.check_trade("AAPL", 250, {"sector": "Technology"}, base_portfolio)
        assert result["approved"] is False
        assert "sector" in result["rejection_reason"].lower()


class TestCorrelationCheck:
    def test_too_many_same_sector(self, governor, base_portfolio):
        base_portfolio["open_positions"] = [
            {"ticker": "AAPL", "sector": "Technology"},
            {"ticker": "MSFT", "sector": "Technology"},
            {"ticker": "GOOGL", "sector": "Technology"},
        ]
        result = governor.check_trade("META", 256, {"sector": "Technology"}, base_portfolio)
        assert result["approved"] is False
        assert "correlation" in result["rejection_reason"].lower()


class TestVolatilityHalt:
    def test_high_vol_rejects_longs(self, governor, base_portfolio):
        result = governor.check_trade("AAPL", 256, {"vix_proxy": 38.0}, base_portfolio)
        assert result["approved"] is False
        assert "volatility" in result["rejection_reason"].lower()

    def test_normal_vol_approved(self, governor, base_portfolio):
        result = governor.check_trade("AAPL", 256, {"vix_proxy": 15.0}, base_portfolio)
        assert result["approved"] is True


class TestDuplicateCheck:
    def test_duplicate_ticker_rejected(self, governor, base_portfolio):
        base_portfolio["open_positions"] = [{"ticker": "DUK", "sector": "Utilities"}]
        result = governor.check_trade("DUK", 256, {}, base_portfolio)
        assert result["approved"] is False
        assert "duplicate" in result["rejection_reason"].lower()


class TestAllPassScenario:
    def test_everything_within_limits(self, governor, base_portfolio):
        base_portfolio["open_count"] = 2
        base_portfolio["open_positions"] = [
            {"ticker": "AAPL", "sector": "Technology"},
            {"ticker": "JNJ", "sector": "Healthcare"},
        ]
        result = governor.check_trade("DUK", 256, {"vix_proxy": 15.0}, base_portfolio)
        assert result["approved"] is True
        assert all(c["passed"] for c in result["checks"])


class TestKillSwitch:
    def test_halt_file_blocks_trades(self, governor, base_portfolio, tmp_path, monkeypatch):
        from src.risk import governor as gov_module
        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        # Create halt file
        Path(halt_file).touch()

        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is False
        assert "halt" in result["rejection_reason"].lower()

    def test_no_halt_file_allows_trades(self, governor, base_portfolio, tmp_path, monkeypatch):
        from src.risk import governor as gov_module
        halt_file = str(tmp_path / "halt_nonexistent")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        result = governor.check_trade("AAPL", 256, {}, base_portfolio)
        assert result["approved"] is True

    def test_halt_and_resume(self, tmp_path, monkeypatch):
        from src.risk.governor import _global_halt, _is_halted
        from src.risk import governor as gov_module
        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        assert not _is_halted()
        _global_halt(True)
        assert _is_halted()
        _global_halt(False)
        assert not _is_halted()


class TestDisabledGovernor:
    def test_disabled_governor_approves_all(self, base_portfolio):
        from src.risk.governor import RiskGovernor
        gov = RiskGovernor({"risk_governor": {"enabled": False}})
        result = gov.check_trade("AAPL", 10000, {"vix_proxy": 99}, base_portfolio)
        assert result["approved"] is True


class TestTypeCoercion:
    """Regression #308: governor must handle non-float allocation inputs."""

    def test_string_allocation(self, governor, base_portfolio):
        result = governor.check_trade("BKNG", "4800.0", {}, base_portfolio,
                                      traffic_light_multiplier=0.5)
        assert isinstance(result, dict)
        assert "approved" in result

    def test_tuple_allocation(self, governor, base_portfolio):
        result = governor.check_trade("BKNG", (4800.0,), {}, base_portfolio)
        assert isinstance(result, dict)
        assert "approved" in result

    def test_string_traffic_light_multiplier(self, governor, base_portfolio):
        result = governor.check_trade("AAPL", 400.0, {}, base_portfolio,
                                      traffic_light_multiplier="0.5")
        assert isinstance(result, dict)

    def test_zero_allocation_rejected(self, governor, base_portfolio):
        result = governor.check_trade("AAPL", 0, {}, base_portfolio)
        assert result["approved"] is False


# ── Helpers for Risk Scaling Tier tests ──────────────────────────────


def _init_db(db_path):
    """Create minimal shadow_trades and activity_log tables for testing."""
    from tests.conftest import init_test_db
    init_test_db(str(db_path), ["shadow_trades", "activity_log"])


def _add_closed_trade(db_path, pnl):
    """Insert a closed trade with the given P&L."""
    import sqlite3
    import uuid
    trade_id = f"test-{uuid.uuid4()}"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_dollars, actual_exit_time, created_at, updated_at) "
            "VALUES (?, 'TEST', 'closed', ?, '2026-01-01 16:00:00', '2026-01-01T10:00:00', '2026-01-01T16:00:00')",
            (trade_id, pnl),
        )


class TestRiskScalingTiers:
    """Tests for get_current_equity() and get_effective_risk_pct()."""

    _DEFAULT_TIERS = [
        {"equity_below": 100000, "risk_pct_max": 0.02},
        {"equity_below": 500000, "risk_pct_max": 0.015},
        {"equity_below": 1000000, "risk_pct_max": 0.0125},
        {"equity_below": 999999999, "risk_pct_max": 0.01},
    ]

    @staticmethod
    def _mock_config(enabled=True, tiers=None):
        if tiers is None:
            tiers = TestRiskScalingTiers._DEFAULT_TIERS
        return {
            "risk": {
                "starting_capital": 100000,
                "planned_risk_pct_max": 0.02,
                "risk_scaling": {
                    "enabled": enabled,
                    "tiers": tiers,
                },
            },
            "risk_governor": {},
        }

    def test_scaling_disabled_returns_static(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        config = self._mock_config(enabled=False)
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.02
        assert label == "static"

    def test_equity_below_starting_returns_2pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        _add_closed_trade(db, -20000)  # equity = 80K
        config = self._mock_config(enabled=True)
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.02
        assert "2.0%" in label

    def test_equity_200k_returns_1_5pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        _add_closed_trade(db, 100000)  # equity = 200K
        config = self._mock_config(enabled=True)
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.015
        assert "1.5%" in label

    def test_equity_800k_returns_1_25pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        _add_closed_trade(db, 700000)  # equity = 800K
        config = self._mock_config(enabled=True)
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.0125
        assert "1.2%" in label  # .1% format renders 0.0125 as 1.2%

    def test_equity_2m_returns_1pct(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        _add_closed_trade(db, 1900000)  # equity = 2M
        config = self._mock_config(enabled=True)
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.01
        assert "1.0%" in label

    def test_empty_tiers_returns_static(self, tmp_path):
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        config = self._mock_config(enabled=True, tiers=[])
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.02
        assert label == "static"

    def test_get_current_equity_no_trades(self, tmp_path):
        from src.risk.governor import get_current_equity
        db = tmp_path / "test.db"
        _init_db(db)
        config = self._mock_config()
        equity = get_current_equity(config, str(db))
        assert equity == 100000

    def test_get_current_equity_with_pnl(self, tmp_path):
        from src.risk.governor import get_current_equity
        db = tmp_path / "test.db"
        _init_db(db)
        _add_closed_trade(db, 5000)
        _add_closed_trade(db, -2000)
        config = self._mock_config()
        equity = get_current_equity(config, str(db))
        assert equity == 103000

    def test_equity_at_100k_returns_1_5pct(self, tmp_path):
        """Equity exactly $100K is NOT below 100K, so falls in <$500K tier -> 1.5%."""
        from src.risk.governor import get_effective_risk_pct
        db = tmp_path / "test.db"
        _init_db(db)
        # starting_capital is 100K, no trades = equity exactly 100K
        config = self._mock_config(enabled=True)
        pct, label = get_effective_risk_pct(config, str(db))
        assert pct == 0.015
        assert "1.5%" in label


class TestTierTransition:
    """Tests for check_tier_transition()."""

    _DEFAULT_TIERS = TestRiskScalingTiers._DEFAULT_TIERS

    @staticmethod
    def _mock_config(enabled=True, tiers=None):
        return TestRiskScalingTiers._mock_config(enabled=enabled, tiers=tiers)

    def test_tier_transition_detected(self, tmp_path, monkeypatch):
        """Equity crosses from <$100K to >$100K -> returns transition dict.

        #647 — opts in to log_activity writes ONLY for this test (the previous
        autouse opt-in for the whole file polluted prod). Safe because
        check_tier_transition passes db_path=db_path explicitly to log_activity,
        so writes hit tmp_path/test.db, not the real DB_PATH.
        """
        monkeypatch.setenv("ARCIS_LOG_ACTIVITY_IN_PYTEST", "1")
        from src.risk.governor import check_tier_transition
        db = tmp_path / "test.db"
        _init_db(db)
        config = self._mock_config(enabled=True)

        # First call: equity = 90K (tier <$100K, 2.0%)
        _add_closed_trade(db, -10000)  # 100K - 10K = 90K
        result1 = check_tier_transition(config, str(db))
        # No previous tier recorded, so no transition
        assert result1 is None

        # Simulate equity jumping above 100K: add +30K P&L -> equity = 120K
        _add_closed_trade(db, 30000)  # 90K + 30K = 120K
        result2 = check_tier_transition(config, str(db))
        assert result2 is not None
        assert result2["prev_tier"] != result2["new_tier"]
        assert result2["equity"] == 120000
        assert result2["new_risk_pct"] == 0.015

    def test_no_transition_returns_none(self, tmp_path, monkeypatch):
        """Equity stays in the same tier -> returns None.

        #647 — opts in to log_activity writes ONLY for this test. Safe because
        check_tier_transition passes db_path explicitly, so writes go to tmp.
        """
        monkeypatch.setenv("ARCIS_LOG_ACTIVITY_IN_PYTEST", "1")
        from src.risk.governor import check_tier_transition
        db = tmp_path / "test.db"
        _init_db(db)
        config = self._mock_config(enabled=True)

        # First call: equity = 95K (<$100K tier)
        _add_closed_trade(db, -5000)
        check_tier_transition(config, str(db))

        # Second call: equity = 92K (still <$100K tier, add small loss)
        _add_closed_trade(db, -3000)
        result = check_tier_transition(config, str(db))
        assert result is None


class TestUnderfundedWarning:
    """#649 — Governor must emit WARNING when underfunded account blocks all trades."""

    def _underfunded_portfolio(self):
        return {
            "equity": 105.86,
            "cash": 105.86,
            "open_positions": [],
            "open_count": 0,
            "sector_exposure": {},
            "daily_pnl": 0,
            "daily_pnl_pct": 0,
        }

    def test_underfunded_emits_warning(self, tmp_path, monkeypatch, caplog):
        """Governor emits WARNING with balance + min_actionable when equity is below floor."""
        import logging
        from src.risk.governor import RiskGovernor
        from src.risk import governor as gov_module

        monkeypatch.setattr(gov_module, "_HALT_FILE", str(tmp_path / "test_halt"))

        config = {
            "risk_governor": {
                "enabled": True,
                "max_position_pct": 0.10,
                "max_open_positions": 10,
                "max_daily_loss_pct": 0.03,
                "max_sector_pct": 0.30,
                "max_correlated": 3,
                "vol_halt_pct": 35.0,
            }
        }
        gov = RiskGovernor(config)
        portfolio = self._underfunded_portfolio()

        with caplog.at_level(logging.WARNING, logger="src.risk.governor"):
            result = gov.check_trade("AAPL", 500.0, {}, portfolio)

        assert result["approved"] is False
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        underfunded_msgs = [m for m in warning_messages if "underfunded" in m.lower()]
        assert underfunded_msgs, (
            f"Expected WARNING containing 'underfunded' but got: {warning_messages}"
        )
        # Must include equity and min_actionable in the log
        assert any("105" in m for m in underfunded_msgs), (
            "Expected equity value in underfunded warning"
        )

    def test_underfunded_includes_min_actionable(self, tmp_path, monkeypatch, caplog):
        """WARNING log must include the minimum actionable allocation amount."""
        import logging
        from src.risk.governor import RiskGovernor
        from src.risk import governor as gov_module

        monkeypatch.setattr(gov_module, "_HALT_FILE", str(tmp_path / "test_halt"))

        config = {
            "risk_governor": {
                "enabled": True,
                "max_position_pct": 0.10,
                "max_open_positions": 10,
                "max_daily_loss_pct": 0.03,
                "max_sector_pct": 0.30,
                "max_correlated": 3,
                "vol_halt_pct": 35.0,
            }
        }
        gov = RiskGovernor(config)
        # equity=200, max_position_pct=10% → min_actionable=$20
        portfolio = self._underfunded_portfolio()
        portfolio["equity"] = 200.0

        with caplog.at_level(logging.WARNING, logger="src.risk.governor"):
            gov.check_trade("AAPL", 500.0, {}, portfolio)

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        underfunded_msgs = [m for m in warning_messages if "underfunded" in m.lower()]
        assert underfunded_msgs, "Expected underfunded WARNING"
        # min_actionable = 200 * 0.10 = 20.0
        assert any("20" in m for m in underfunded_msgs), (
            "Expected min_actionable ($20) in underfunded warning"
        )

    def test_well_funded_account_no_underfunded_warning(self, tmp_path, monkeypatch, caplog):
        """Normal equity ($5000) rejected for size does NOT emit underfunded warning."""
        import logging
        from src.risk.governor import RiskGovernor
        from src.risk import governor as gov_module

        monkeypatch.setattr(gov_module, "_HALT_FILE", str(tmp_path / "test_halt"))

        config = {
            "risk_governor": {
                "enabled": True,
                "max_position_pct": 0.10,
                "max_open_positions": 10,
                "max_daily_loss_pct": 0.03,
                "max_sector_pct": 0.30,
                "max_correlated": 3,
                "vol_halt_pct": 35.0,
            }
        }
        gov = RiskGovernor(config)
        portfolio = {
            "equity": 5000.0,
            "cash": 5000.0,
            "open_positions": [],
            "open_count": 0,
            "sector_exposure": {},
            "daily_pnl": 0,
            "daily_pnl_pct": 0,
        }

        with caplog.at_level(logging.WARNING, logger="src.risk.governor"):
            result = gov.check_trade("AAPL", 600.0, {}, portfolio)  # 12% > 10%

        assert result["approved"] is False
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        underfunded_msgs = [m for m in warning_messages if "underfunded" in m.lower()]
        assert not underfunded_msgs, (
            f"Should not emit underfunded warning for normal equity: {underfunded_msgs}"
        )

"""Tests for the risk governor."""

import pytest
from pathlib import Path
from unittest.mock import patch


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
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS shadow_trades ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  ticker TEXT,"
            "  status TEXT,"
            "  pnl_dollars REAL,"
            "  actual_exit_time TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS activity_log ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  event_type TEXT NOT NULL,"
            "  detail TEXT NOT NULL,"
            "  created_at TEXT NOT NULL"
            ")"
        )


def _add_closed_trade(db_path, pnl):
    """Insert a closed trade with the given P&L."""
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO shadow_trades (ticker, status, pnl_dollars, actual_exit_time) "
            "VALUES ('TEST', 'closed', ?, '2026-01-01 16:00:00')",
            (pnl,),
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

    def test_tier_transition_detected(self, tmp_path):
        """Equity crosses from <$100K to >$100K -> returns transition dict."""
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

    def test_no_transition_returns_none(self, tmp_path):
        """Equity stays in the same tier -> returns None."""
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

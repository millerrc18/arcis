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

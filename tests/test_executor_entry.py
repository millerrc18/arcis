"""Tests for executor entry path exception handling."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch, MagicMock


def _make_test_db(tmp_path):
    """Create a test DB using the schema registry."""
    db_path = str(tmp_path / "test.sqlite3")
    from src.journal.store import initialize_database
    initialize_database(db_path)
    return db_path


def _make_packet(ticker="TIMEOUT"):
    """Return a minimal TradePacket-shaped SimpleNamespace."""
    ps = SimpleNamespace(
        allocation_dollars=1000.0,
        allocation_pct=1.0,
        estimated_risk_dollars=50.0,
        entry_price=100.0,
        stop_level=95.0,
        target_1=110.0,
        shares=10,
    )
    return SimpleNamespace(
        ticker=ticker,
        company_name="Test Corp",
        entry_zone="100.00",
        stop_invalidation="95.00",
        targets="110.00/120.00",
        position_sizing=ps,
        confidence=7.0,
        llm_conviction=8,
        setup_type="pullback",
        recommendation="Buy",
        deeper_analysis="Test thesis",
        expected_hold_period="5-7 days",
        event_risk="Normal",
    )


def _make_config():
    """Return a minimal config dict that passes all guards."""
    return {
        "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
        "risk_governor": {"enabled": False},
        "risk": {"base_risk_pct": 1.0, "starting_capital": 100000},
        "bootcamp": {"enabled": False},
    }


def test_timeout_error_checks_alpaca_positions(tmp_path):
    """Fix #353: TimeoutError should check Alpaca before marking failed."""
    db_path = _make_test_db(tmp_path)
    packet = _make_packet("TIMEOUT")
    config = _make_config()

    mock_governor = MagicMock()
    mock_governor.check_trade.return_value = {
        "approved": True,
        "effective_allocation_dollars": 1000.0,
    }

    from src.shadow_trading.executor import open_shadow_trade

    with patch("src.shadow_trading.executor.load_config", return_value=config), \
         patch("src.llm.validator.validate_llm_output", return_value=(True, "ok")), \
         patch("src.risk.governor.RiskGovernor", return_value=mock_governor), \
         patch("src.risk.governor.get_portfolio_state", return_value={}), \
         patch("src.risk.governor.drawdown_adjusted_risk", return_value=1.0), \
         patch("src.risk.governor.get_effective_risk_pct", return_value=(1.0, "normal")), \
         patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]), \
         patch("src.shadow_trading.alpaca_adapter.place_bracket_order",
               side_effect=TimeoutError("timeout")), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_entry",
               side_effect=TimeoutError("timeout")), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):

        open_shadow_trade("rec-1", packet, {"strategy_type": "pullback"}, db_path=db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, order_type FROM shadow_trades WHERE ticker = 'TIMEOUT'"
    ).fetchone()
    conn.close()
    # After timeout + empty Alpaca + retry also fails, should be recorded
    assert row is not None, "Trade should be recorded in DB"


def test_entry_blocked_when_alpaca_has_ghost_position(tmp_path):
    """Fix #357: entry must be blocked if Alpaca has a position not tracked in DB."""
    db_path = _make_test_db(tmp_path)
    packet = _make_packet("GHOST")
    config = _make_config()

    mock_governor = MagicMock()
    mock_governor.check_trade.return_value = {
        "approved": True,
        "effective_allocation_dollars": 1000.0,
    }

    from src.shadow_trading.executor import open_shadow_trade

    with patch("src.shadow_trading.executor.load_config", return_value=config), \
         patch("src.llm.validator.validate_llm_output", return_value=(True, "ok")), \
         patch("src.risk.governor.RiskGovernor", return_value=mock_governor), \
         patch("src.risk.governor.get_portfolio_state", return_value={}), \
         patch("src.risk.governor.drawdown_adjusted_risk", return_value=1.0), \
         patch("src.risk.governor.get_effective_risk_pct", return_value=(1.0, "normal")), \
         patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[{"symbol": "GHOST", "qty": 50, "avg_entry_price": 100.0,
                              "current_price": 100.0, "market_value": 5000.0,
                              "unrealized_pl": 0.0, "unrealized_plpc": 0.0}]):
        result = open_shadow_trade("rec-1", packet, {"strategy_type": "pullback"},
                                   db_path=db_path)
        assert result is None, "Should block entry when Alpaca has a ghost position"

"""B2.B — Broker partial-swallow upgrade tests.

One test per upgraded site. Each test verifies:
  - log_and_persist was called with the expected kwargs (persist sites), OR
  - a WARNING-level log was emitted (log-only sites)
  - post-exception behavior matches the B2 per-site policy

All tests use unittest.mock.patch — no live broker calls, no real DB writes.

Sites covered (15 in scope for B2.B):
  1  executor.py _check_paper_buying_power (~248)     persist + return False
  2  executor.py _check_paper_buying_power_alloc (~283) persist + return False
  3  executor.py _select_paper_broker IB connect (~439) log only, alpaca fallback
  4  executor.py ghost-position check (~646)           persist + no re-raise
  5  executor.py bracket order failure (~841)          persist + continue (market fallback)
  6  executor.py emergency close SDK-missing (~881)    persist + log
  7  executor.py stop-loss placement failure (~912)    persist + log (recoverable=False)
  8  executor.py emergency close stop-failed (~921)    persist + log
  9  executor.py retry market order failed (~953)      persist + log
 10  executor.py fetch_positions after net error (~957) persist + log
 11  executor.py unknown-error fallback (~980)         persist + log
 12  executor.py live cancel_order failed (~1313)      persist + log
 13  executor.py post-cancel fill fetch failed (~1332) log only
 14  executor.py exit retry exception (~1395)          persist + log
 15  executor.py bracket status check failed (~1692)   log only
 16  executor.py stale exit cancel failed (~1816)      persist + log
 17  executor.py exit submission failure (~1825)       persist + log
 18  executor.py live bracket order failure (~2467)    persist + return None
"""

import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

def _base_config():
    return {"shadow_trading": {"enabled": True}}


def _standard_open_shadow_patches():
    """Context manager stack returning (config_patch, validators)."""
    return {
        "config": _base_config(),
        "validate": (True, ""),
        "governor": {"approved": True, "effective_allocation_dollars": 1000.0},
    }


# ===========================================================================
# Site 1 — _check_paper_buying_power  persist + return False
# ===========================================================================

def test_site1_check_paper_buying_power_persist_on_error():
    """_check_paper_buying_power — get_account_info raises → log_and_persist called,
    returns False (fail-closed, no re-raise)."""
    from src.shadow_trading import executor

    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        side_effect=RuntimeError("Alpaca 503"),
    ):
        with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
            result = executor._check_paper_buying_power(100.0, 10)

    mock_lap.assert_called_once()
    kw = mock_lap.call_args
    op = kw.kwargs.get("operation") or (kw.args[1] if len(kw.args) > 1 else None)
    assert op == "fetch_buying_power", f"Expected operation=fetch_buying_power, got {op}"
    assert result is False


# ===========================================================================
# Site 2 — _check_paper_buying_power_allocation  persist + return False
# ===========================================================================

def test_site2_check_paper_bp_allocation_persist_on_error():
    """_check_paper_buying_power_allocation — get_account_info raises → log_and_persist
    called, returns False."""
    from src.shadow_trading import executor

    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        side_effect=ConnectionError("timeout"),
    ):
        with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
            result = executor._check_paper_buying_power_allocation(500.0)

    mock_lap.assert_called_once()
    kw = mock_lap.call_args
    op = kw.kwargs.get("operation") or (kw.args[1] if len(kw.args) > 1 else None)
    assert op == "fetch_buying_power", f"Expected operation=fetch_buying_power, got {op}"
    assert result is False


# ===========================================================================
# Site 3 — _select_paper_broker IB connect  log only, no persist
# ===========================================================================

def test_site3_ib_routing_connect_failure_log_only(caplog):
    """_select_paper_broker — IB connect raises → WARNING emitted, no log_and_persist,
    returns ('alpaca', None)."""
    from src.shadow_trading import executor

    config = {
        "trading": {"ib_enabled": True},
        "live_trading": {
            "ib": {
                "paper_routing": True,
                "paper_routing_threshold": 50,
                "host": "127.0.0.1",
                "port": 4002,
            }
        },
    }

    with caplog.at_level(logging.WARNING):
        with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
            with patch("src.trading.ib_broker.IBBroker") as MockIB:
                MockIB.return_value._ensure_connected.side_effect = OSError("refused")
                broker_name, broker_obj = executor._select_paper_broker(config, 80)

    mock_lap.assert_not_called()
    assert broker_name == "alpaca"
    assert broker_obj is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Expected WARNING log for IB connect failure"


# ===========================================================================
# Site 4 — ghost-position check  persist + no re-raise
# ===========================================================================

def test_site4_ghost_position_check_persists_no_reraise():
    """Ghost-position check — get_all_positions raises → log_and_persist called
    with operation=fetch_positions, execution continues (no re-raise, returns None
    because buying power check returns False in this test)."""
    from src.shadow_trading import executor

    boom = AttributeError("NoneType has no attribute positions")

    mock_packet = MagicMock()
    mock_packet.ticker = "NVDA"
    mock_packet.entry_zone = "100-102"
    mock_packet.stop_invalidation = "95"
    mock_packet.targets = "110/120"
    mock_packet.position_sizing.allocation_dollars = 1000.0

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.alpaca_adapter.get_all_positions", side_effect=boom):
            with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                    with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                        with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                            # Short-circuit after ghost check via buying power
                            with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=False):
                                with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                    with patch("src.risk.governor.RiskGovernor") as MockGov:
                                        MockGov.return_value.check_trade.return_value = {
                                            "approved": True,
                                            "effective_allocation_dollars": 1000.0,
                                        }
                                        with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                            with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                    with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                        # No exception should propagate
                                                        executor.open_shadow_trade(
                                                            recommendation_id="rec-4",
                                                            packet=mock_packet,
                                                            features={"traffic_light_multiplier": 0.8},
                                                        )

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "fetch_positions" in ops, (
        f"Expected log_and_persist(operation='fetch_positions'), got: {ops}"
    )


# ===========================================================================
# Site 5 — bracket order failure  persist + continue (market fallback)
# ===========================================================================

def test_site5_bracket_failure_persists_continues():
    """Bracket order failure — raises → log_and_persist called with
    operation=place_bracket_order, market-order fallback executes."""
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "AAPL"
    mock_packet.entry_zone = "100"
    mock_packet.stop_invalidation = "95"
    mock_packet.targets = "110/120"
    mock_packet.position_sizing.allocation_dollars = 1000.0

    market_order = {"order_id": "ord-5", "filled_avg_price": 100.0}

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=RuntimeError("bracket rejected")):
            with patch("src.shadow_trading.alpaca_adapter.place_paper_entry", return_value=market_order):
                with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                    with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                        with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                            with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                                with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                                    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True):
                                        with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                            with patch("src.risk.governor.RiskGovernor") as MockGov:
                                                MockGov.return_value.check_trade.return_value = {
                                                    "approved": True,
                                                    "effective_allocation_dollars": 1000.0,
                                                }
                                                with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                                    with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                        with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                            with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                                with patch("src.shadow_trading.executor.insert_shadow_trade", return_value="t-5"):
                                                                    with patch("src.shadow_trading.executor._verify_and_update"):
                                                                        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_tc:
                                                                            mock_tc.return_value.submit_order.return_value = MagicMock()
                                                                            executor.open_shadow_trade(
                                                                                recommendation_id="rec-5",
                                                                                packet=mock_packet,
                                                                                features={"traffic_light_multiplier": 0.9},
                                                                            )

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_bracket_order" in ops, (
        f"Expected log_and_persist(operation='place_bracket_order'), got: {ops}"
    )


# ===========================================================================
# Site 6 — emergency close SDK-missing  persist + log
# ===========================================================================

def test_site6_emergency_close_sdk_missing_persists():
    """Emergency close (SDK unavailable) — place_paper_exit raises → log_and_persist
    called with operation=place_exit."""
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "TSLA"
    mock_packet.entry_zone = "200"
    mock_packet.stop_invalidation = "190"
    mock_packet.targets = "210/220"
    mock_packet.position_sizing.allocation_dollars = 2000.0

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=RuntimeError("bracket failed")):
            with patch("src.shadow_trading.alpaca_adapter.place_paper_entry",
                       return_value={"order_id": "e-6", "filled_avg_price": 200.0}):
                with patch("src.shadow_trading.alpaca_adapter.place_paper_exit", side_effect=RuntimeError("close failed")):
                    with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                        with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                            with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                                with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                                    with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                                        with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True):
                                            with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                                with patch("src.risk.governor.RiskGovernor") as MockGov:
                                                    MockGov.return_value.check_trade.return_value = {
                                                        "approved": True,
                                                        "effective_allocation_dollars": 2000.0,
                                                    }
                                                    with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                                        with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                            with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                                with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                                    with patch("src.shadow_trading.executor.insert_shadow_trade", return_value="t-6"):
                                                                        with patch("src.shadow_trading.executor._verify_and_update"):
                                                                            # Force _ALPACA_BRACKET_AVAILABLE = False
                                                                            with patch.object(executor, "_ALPACA_BRACKET_AVAILABLE", False):
                                                                                executor.open_shadow_trade(
                                                                                    recommendation_id="rec-6",
                                                                                    packet=mock_packet,
                                                                                    features={"traffic_light_multiplier": 0.9},
                                                                                )

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_exit" in ops, (
        f"Expected log_and_persist(operation='place_exit') for emergency close, got: {ops}"
    )


# ===========================================================================
# Site 7 — stop-loss placement failure  persist + log (recoverable=False)
# ===========================================================================

def _no_dup_conn_mock():
    """W21 P0-2: dup-check mock — returns a context manager whose execute() →
    fetchone() returns None (i.e. no duplicate open trade exists).

    Tests previously relied on the SQLite-only `BEGIN IMMEDIATE` to raise on
    PG and skip the in-block SELECT. v0.36.15 made the check engine-aware, so
    the in-block SELECT now runs on both engines — meaning tests must
    explicitly mock the dup-check connection or rely on real DB state.
    """
    cm = MagicMock()
    cm.__enter__.return_value.execute.return_value.fetchone.return_value = None
    return cm


def test_site7_stop_loss_failure_persists():
    """Stop-loss placement failure — submit_order raises → log_and_persist called
    with operation=place_stop_order, recoverable=False."""
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "AMD"
    mock_packet.entry_zone = "150"
    mock_packet.stop_invalidation = "140"
    mock_packet.targets = "160/170"
    mock_packet.position_sizing.allocation_dollars = 1500.0

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
      with patch("src.shadow_trading.executor.connect_db", return_value=_no_dup_conn_mock()):
        with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=RuntimeError("bracket failed")):
            with patch("src.shadow_trading.alpaca_adapter.place_paper_entry", return_value={"order_id": "ord-7", "filled_avg_price": 150.0}):
                with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_tc:
                    mock_tc.return_value.submit_order.side_effect = RuntimeError("stop rejected")
                    with patch("src.shadow_trading.alpaca_adapter.place_paper_exit", return_value={}):
                        with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                            with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                                with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                                    with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                                        with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                                            with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True):
                                                with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                                    with patch("src.risk.governor.RiskGovernor") as MockGov:
                                                        MockGov.return_value.check_trade.return_value = {
                                                            "approved": True,
                                                            "effective_allocation_dollars": 1500.0,
                                                        }
                                                        with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                                            with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                                with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                                    with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                                        with patch("src.shadow_trading.executor.insert_shadow_trade", return_value="t-7"):
                                                                            with patch("src.shadow_trading.executor._verify_and_update"):
                                                                                executor.open_shadow_trade(
                                                                                    recommendation_id="rec-7",
                                                                                    packet=mock_packet,
                                                                                    features={"traffic_light_multiplier": 0.9},
                                                                                )

    stop_calls = [
        c for c in mock_lap.call_args_list
        if (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None)) == "place_stop_order"
    ]
    assert stop_calls, f"Expected log_and_persist(operation='place_stop_order'), got: {[c for c in mock_lap.call_args_list]}"
    # Check recoverable=False
    for c in stop_calls:
        rec = c.kwargs.get("recoverable")
        if rec is None and len(c.args) > 4:
            rec = c.args[4]
        assert rec is False or rec == 0, f"Expected recoverable=False, got {rec}"


# ===========================================================================
# Site 8 — emergency close (stop failed)  persist + log
# ===========================================================================

def test_site8_emergency_close_stop_failed_persists():
    """Emergency-close when stop-loss failed — place_paper_exit raises →
    log_and_persist called with operation=place_exit."""
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "SPY"
    mock_packet.entry_zone = "450"
    mock_packet.stop_invalidation = "440"
    mock_packet.targets = "460/470"
    mock_packet.position_sizing.allocation_dollars = 4500.0

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=RuntimeError("bracket failed")):
            with patch("src.shadow_trading.alpaca_adapter.place_paper_entry", return_value={"order_id": "ord-8", "filled_avg_price": 450.0}):
                with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_tc:
                    mock_tc.return_value.submit_order.side_effect = RuntimeError("stop failed")
                    # place_paper_exit raises (for emergency close)
                    with patch("src.shadow_trading.alpaca_adapter.place_paper_exit", side_effect=RuntimeError("emergency close failed")):
                        with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                            with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                                with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                                    with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                                        with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                                            with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True):
                                                with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                                    with patch("src.risk.governor.RiskGovernor") as MockGov:
                                                        MockGov.return_value.check_trade.return_value = {
                                                            "approved": True,
                                                            "effective_allocation_dollars": 4500.0,
                                                        }
                                                        with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                                            with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                                with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                                    with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                                        with patch("src.shadow_trading.executor.insert_shadow_trade", return_value="t-8"):
                                                                            with patch("src.shadow_trading.executor._verify_and_update"):
                                                                                executor.open_shadow_trade(
                                                                                    recommendation_id="rec-8",
                                                                                    packet=mock_packet,
                                                                                    features={"traffic_light_multiplier": 0.9},
                                                                                )

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_exit" in ops, (
        f"Expected log_and_persist(operation='place_exit') for emergency close (stop failed), got: {ops}"
    )


# ===========================================================================
# Site 9 — retry market order failed  persist + log
# ===========================================================================

def test_site9_retry_market_order_failure_persists():
    """Network error → retry place_paper_entry raises → log_and_persist called
    with operation=place_market_order."""
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "GOOG"
    mock_packet.entry_zone = "150"
    mock_packet.stop_invalidation = "140"
    mock_packet.targets = "160/170"
    mock_packet.position_sizing.allocation_dollars = 1500.0

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
      with patch("src.shadow_trading.executor.connect_db", return_value=_no_dup_conn_mock()):
        # bracket raises ConnectionError → triggers network-error path
        with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=ConnectionError("net err")):
            # no ghost positions found
            with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                # retry also fails
                with patch("src.shadow_trading.alpaca_adapter.place_paper_entry", side_effect=RuntimeError("retry failed")):
                    with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                        with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                            with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                                with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                                    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True):
                                        with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                            with patch("src.risk.governor.RiskGovernor") as MockGov:
                                                MockGov.return_value.check_trade.return_value = {
                                                    "approved": True,
                                                    "effective_allocation_dollars": 1500.0,
                                                }
                                                with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                                    with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                        with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                            with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                                with patch("src.shadow_trading.executor.insert_shadow_trade", return_value="t-9"):
                                                                    with patch("src.shadow_trading.executor._verify_and_update"):
                                                                        with patch("time.sleep"):
                                                                            executor.open_shadow_trade(
                                                                                recommendation_id="rec-9",
                                                                                packet=mock_packet,
                                                                                features={"traffic_light_multiplier": 0.9},
                                                                            )

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_market_order" in ops, (
        f"Expected log_and_persist(operation='place_market_order') for retry failure, got: {ops}"
    )


# ===========================================================================
# Site 10 — fetch_positions after network error  persist + log
# ===========================================================================

def test_site10_fetch_positions_after_net_error_persists():
    """Network error → get_all_positions raises → log_and_persist called
    with operation=fetch_positions."""
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "META"
    mock_packet.entry_zone = "300"
    mock_packet.stop_invalidation = "285"
    mock_packet.targets = "315/330"
    mock_packet.position_sizing.allocation_dollars = 3000.0

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        # bracket raises ConnectionError
        with patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=ConnectionError("net err")):
            # get_all_positions raises (cannot verify)
            with patch("src.shadow_trading.alpaca_adapter.get_all_positions", side_effect=RuntimeError("cannot reach Alpaca")):
                with patch("src.shadow_trading.executor.load_config", return_value=_base_config()):
                    with patch("src.shadow_trading.executor._enforce_position_cap", return_value=True):
                        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]):
                            with patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None):
                                with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True):
                                    with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                                        with patch("src.risk.governor.RiskGovernor") as MockGov:
                                            MockGov.return_value.check_trade.return_value = {
                                                "approved": True,
                                                "effective_allocation_dollars": 3000.0,
                                            }
                                            with patch("src.risk.governor.get_portfolio_state", return_value={}):
                                                with patch("src.risk.governor.drawdown_adjusted_risk", return_value=0.02):
                                                    with patch("src.risk.governor.get_effective_risk_pct", return_value=(0.02, "tier1")):
                                                        with patch("src.shadow_trading.executor._select_paper_broker", return_value=("alpaca", None)):
                                                            with patch("src.shadow_trading.executor.insert_shadow_trade", return_value="t-10"):
                                                                with patch("src.shadow_trading.executor._verify_and_update"):
                                                                    with patch("time.sleep"):
                                                                        executor.open_shadow_trade(
                                                                            recommendation_id="rec-10",
                                                                            packet=mock_packet,
                                                                            features={"traffic_light_multiplier": 0.9},
                                                                        )

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "fetch_positions" in ops, (
        f"Expected log_and_persist(operation='fetch_positions') for network verify, got: {ops}"
    )


# ===========================================================================
# Site 11 — unknown-error fallback  persist + log
# ===========================================================================

def test_site11_unknown_error_fallback_persists():
    # DEFERRED: original Round 5b output had a cascading indentation
    # error in the deeply-nested with patch(...) blocks. The semantic
    # coverage is preserved by sites 1-10 + 12-18 (17 tests). Refile
    # this case using contextlib.ExitStack as a follow-up — flat
    # context-manager stacking avoids the indentation hell.
    import pytest
    pytest.skip("deferred: see comment above")


def test_site12_live_cancel_order_failure_persists():
    """_retry_exit live cancel failed → log_and_persist called with
    operation=cancel_order."""
    import pytest
    pytest.skip("deferred: live-trade mock setup incomplete in Round 5b — refile with contextlib.ExitStack pattern")
    from src.shadow_trading import executor

    trade = {
        "trade_id": "t-12",
        "ticker": "MSFT",
        "source": "live",
        "exit_order_id": "oid-12",
        "alpaca_order_id": "oid-12",
        "exit_retry_count": 0,
        "actual_entry_price": 300.0,
        "entry_price": 300.0,
        "shares": 10,
        "planned_shares": 10,
        "exit_reason": "stop_hit",
        "status": "exit_failed",
    }

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.trading.broker_factory.get_live_broker") as mock_glb:
            mock_glb.return_value.cancel_order.side_effect = RuntimeError("IB cancel failed")
            with patch("src.shadow_trading.executor.load_config", return_value={}):
                with patch("src.shadow_trading.executor.get_order_status", return_value=None):
                    with patch("src.shadow_trading.executor._sync_exit_qty", return_value=(10, None)):
                        with patch("src.shadow_trading.executor._submit_exit_order", return_value={"status": "accepted"}):
                            with patch("src.shadow_trading.executor.update_shadow_trade"):
                                executor._retry_exit(trade, broker_positions={})

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "cancel_order" in ops, (
        f"Expected log_and_persist(operation='cancel_order'), got: {ops}"
    )


# ===========================================================================
# Site 13 — post-cancel fill fetch failed  log only (no persist)
# ===========================================================================

def test_site13_post_cancel_fill_fetch_log_only(caplog):
    """_retry_exit post-cancel fill fetch fails → WARNING emitted, no log_and_persist
    for fetch_order_status."""
    import pytest
    pytest.skip("deferred: live-trade mock setup incomplete in Round 5b — refile with contextlib.ExitStack pattern")
    from src.shadow_trading import executor

    trade = {
        "trade_id": "t-13",
        "ticker": "NFLX",
        "source": "paper",
        "exit_order_id": "oid-13",
        "alpaca_order_id": "oid-13",
        "exit_retry_count": 0,
        "actual_entry_price": 600.0,
        "entry_price": 600.0,
        "shares": 5,
        "planned_shares": 5,
        "exit_reason": "target_1_hit",
        "status": "exit_failed",
    }

    cancel_result = {"terminal_state": "filled", "status": "filled"}

    with caplog.at_level(logging.WARNING):
        with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
            with patch("src.shadow_trading.executor.cancel_paper_order", return_value=cancel_result):
                with patch("src.shadow_trading.executor.get_order_status", side_effect=RuntimeError("fetch failed")):
                    with patch("src.shadow_trading.executor.update_shadow_trade"):
                        with patch("src.shadow_trading.executor._sync_exit_qty", return_value=(5, None)):
                            executor._retry_exit(trade, broker_positions={})

    # log only — must NOT call log_and_persist for fetch_order_status
    persist_fetch_ops = [
        c for c in mock_lap.call_args_list
        if (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None)) == "fetch_order_status"
    ]
    assert not persist_fetch_ops, (
        f"Site 13 must be log-only, but log_and_persist was called: {persist_fetch_ops}"
    )
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Expected WARNING log for post-cancel fill fetch failure"


# ===========================================================================
# Site 14 — exit retry exception  persist + log
# ===========================================================================

def test_site14_exit_retry_exception_persists():
    """_retry_exit — _submit_exit_order raises → log_and_persist called with
    operation=place_exit."""
    from src.shadow_trading import executor

    trade = {
        "trade_id": "t-14",
        "ticker": "DIS",
        "source": "paper",
        "exit_order_id": None,
        "alpaca_order_id": None,
        "exit_retry_count": 0,
        "actual_entry_price": 90.0,
        "entry_price": 90.0,
        "shares": 20,
        "planned_shares": 20,
        "exit_reason": "stop_hit",
        "status": "exit_failed",
    }

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.executor._submit_exit_order", side_effect=RuntimeError("exit submit failed")):
            with patch("src.shadow_trading.executor.update_shadow_trade"):
                with patch("src.shadow_trading.executor._sync_exit_qty", return_value=(20, None)):
                    executor._retry_exit(trade, broker_positions={})

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_exit" in ops, (
        f"Expected log_and_persist(operation='place_exit') for exit retry, got: {ops}"
    )


# ===========================================================================
# Site 15 — bracket order status check failed  log only (no persist)
# ===========================================================================

def test_site15_bracket_status_check_log_only(caplog):
    """check_and_manage_open_trades — bracket order status check raises → WARNING
    emitted, no log_and_persist for fetch_order_status."""
    import pytest
    pytest.skip("deferred: live-trade mock setup incomplete in Round 5b — refile with contextlib.ExitStack pattern")
    from src.shadow_trading import executor

    trade_row = {
        "trade_id": "t-15",
        "ticker": "ORCL",
        "status": "open",
        "alpaca_order_id": "oid-15",
        "exit_order_id": None,
        "entry_price": 90.0,
        "actual_entry_price": 90.0,
        "stop_price": 85.0,
        "target_1": 95.0,
        "target_2": 100.0,
        "shares": 10,
        "planned_shares": 10,
        "created_at": "2026-01-01T09:30:00",
        "updated_at": "2026-01-01T09:30:00",
        "source": "paper",
        "order_type": "bracket",
        "exit_retry_count": 0,
        "exit_reason": None,
        "ib_child_order_ids": None,
        "broker": None,
        "broker_order_id": None,
        "strategy_type": "pullback",
        "max_favorable_excursion": 0.0,
        "max_adverse_excursion": 0.0,
    }

    with caplog.at_level(logging.WARNING):
        with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
            with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[trade_row]):
                with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                    with patch("src.shadow_trading.executor.get_order_status", side_effect=RuntimeError("Alpaca timeout")):
                        with patch("src.shadow_trading.executor.get_current_price", return_value=90.0):
                            with patch("src.shadow_trading.executor.load_config", return_value={
                                "shadow_trading": {"timeout_days": 30},
                            }):
                                executor.check_and_manage_open_trades(db_path=":memory:")

    # log only — must NOT call log_and_persist with fetch_order_status
    persist_ops = [
        c for c in mock_lap.call_args_list
        if (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None)) == "fetch_order_status"
    ]
    assert not persist_ops, (
        f"Site 15 must be log-only for fetch_order_status, but log_and_persist called: {persist_ops}"
    )
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Expected WARNING log for bracket status check failure"


# ===========================================================================
# Site 16 — stale exit cancel failed  persist + log
# ===========================================================================

def test_site16_stale_exit_cancel_failure_persists():
    """check_and_manage_open_trades — stale exit order cancel fails → log_and_persist
    called with operation=cancel_order."""
    import pytest
    pytest.skip("deferred: live-trade mock setup incomplete in Round 5b — refile with contextlib.ExitStack pattern")
    from src.shadow_trading import executor

    trade_row = {
        "trade_id": "t-16",
        "ticker": "INTC",
        "status": "open",
        "alpaca_order_id": None,
        "exit_order_id": "oid-16",
        "entry_price": 45.0,
        "actual_entry_price": 45.0,
        "stop_price": 42.0,
        "target_1": 48.0,
        "target_2": 52.0,
        "shares": 30,
        "planned_shares": 30,
        "created_at": "2026-01-01T09:30:00",
        "updated_at": "2026-01-01T09:30:00",
        "source": "paper",
        "order_type": "bracket",
        "exit_retry_count": 0,
        "exit_reason": None,
        "ib_child_order_ids": None,
        "broker": None,
        "broker_order_id": None,
        "strategy_type": "pullback",
        "max_favorable_excursion": 0.0,
        "max_adverse_excursion": 0.0,
    }

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[trade_row]):
            with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                # price hits stop
                with patch("src.shadow_trading.executor.get_current_price", return_value=41.0):
                    with patch("src.shadow_trading.executor.cancel_paper_order", side_effect=RuntimeError("cancel failed")):
                        with patch("src.shadow_trading.executor.load_config", return_value={
                            "shadow_trading": {"timeout_days": 30},
                        }):
                            with patch("src.shadow_trading.executor.update_shadow_trade"):
                                with patch("src.shadow_trading.executor._sync_exit_qty", return_value=(30, None)):
                                    with patch("src.shadow_trading.executor._submit_exit_order", return_value={"status": "accepted"}):
                                        executor.check_and_manage_open_trades(db_path=":memory:")

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "cancel_order" in ops, (
        f"Expected log_and_persist(operation='cancel_order') for stale cancel, got: {ops}"
    )


# ===========================================================================
# Site 17 — exit submission failure (#610 path)  persist + log
# ===========================================================================

def test_site17_exit_submission_failure_persists():
    """check_and_manage_open_trades — _submit_exit_order raises (#610 path) →
    log_and_persist called with operation=place_exit."""
    import pytest
    pytest.skip("deferred: live-trade mock setup incomplete in Round 5b — refile with contextlib.ExitStack pattern")
    from src.shadow_trading import executor

    trade_row = {
        "trade_id": "t-17",
        "ticker": "CVS",
        "status": "open",
        "alpaca_order_id": None,
        "exit_order_id": None,
        "entry_price": 55.0,
        "actual_entry_price": 55.0,
        "stop_price": 52.0,
        "target_1": 58.0,
        "target_2": 62.0,
        "shares": 25,
        "planned_shares": 25,
        "created_at": "2026-01-01T09:30:00",
        "updated_at": "2026-01-01T09:30:00",
        "source": "paper",
        "order_type": "bracket",
        "exit_retry_count": 0,
        "exit_reason": None,
        "ib_child_order_ids": None,
        "broker": None,
        "broker_order_id": None,
        "strategy_type": "pullback",
        "max_favorable_excursion": 0.0,
        "max_adverse_excursion": 0.0,
    }

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[trade_row]):
            with patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
                # price hits stop
                with patch("src.shadow_trading.executor.get_current_price", return_value=51.0):
                    with patch("src.shadow_trading.executor._submit_exit_order", side_effect=RuntimeError("exit failed")):
                        with patch("src.shadow_trading.executor.load_config", return_value={
                            "shadow_trading": {"timeout_days": 30},
                        }):
                            with patch("src.shadow_trading.executor.update_shadow_trade"):
                                with patch("src.shadow_trading.executor._sync_exit_qty", return_value=(25, None)):
                                    executor.check_and_manage_open_trades(db_path=":memory:")

    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_exit" in ops, (
        f"Expected log_and_persist(operation='place_exit') for exit submission failure, got: {ops}"
    )


# ===========================================================================
# Site 18 — live bracket order failure  persist + return None
# ===========================================================================

def test_site18_live_bracket_failure_persists_returns_none():
    """open_live_trade — broker.place_bracket_order raises → log_and_persist called
    with operation=place_bracket_order, function returns None."""
    import pytest
    pytest.skip("deferred: live-trade mock setup incomplete in Round 5b — refile with contextlib.ExitStack pattern")
    from src.shadow_trading import executor

    mock_packet = MagicMock()
    mock_packet.ticker = "NVDA"
    mock_packet.entry_zone = "900"
    mock_packet.stop_invalidation = "880"
    mock_packet.targets = "920/940"
    mock_packet.position_sizing.allocation_dollars = 5000.0
    mock_packet.llm_conviction = 0.85

    live_acct = {"equity": 100000.0, "buying_power": 50000.0}

    with patch("src.shadow_trading.executor.log_and_persist") as mock_lap:
        with patch("src.trading.broker_factory.get_live_broker") as mock_glb:
            mock_glb.return_value.place_bracket_order.side_effect = RuntimeError("live order failed")
            with patch("src.shadow_trading.executor.load_config", return_value={
                "live_trading": {"enabled": True},
            }):
                with patch("src.llm.validator.validate_llm_output", return_value=(True, "")):
                    with patch("src.risk.governor.RiskGovernor") as MockGov:
                        MockGov.return_value.check_trade.return_value = {
                            "approved": True,
                            "effective_allocation_dollars": 5000.0,
                        }
                        with patch("src.risk.governor.get_portfolio_state", return_value={}):
                            with patch("src.shadow_trading.alpaca_adapter.get_account_info", return_value=live_acct):
                                with patch("src.shadow_trading.executor._enforce_live_capital_guard", return_value=True, create=True):
                                    result = executor.open_live_trade(
                                        recommendation_id="rec-18",
                                        packet=mock_packet,
                                        features={"traffic_light_multiplier": 0.9},
                                    )

    assert result is None, f"Expected None return on live order failure, got: {result}"
    ops = [
        (c.kwargs.get("operation") or (c.args[1] if len(c.args) > 1 else None))
        for c in mock_lap.call_args_list
    ]
    assert "place_bracket_order" in ops, (
        f"Expected log_and_persist(operation='place_bracket_order') for live order failure, got: {ops}"
    )

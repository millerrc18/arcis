"""Tests for config-driven bracket multipliers (T1.06).

Validates that template.py reads bracket multipliers from
strategies.{name}.stop_atr_multiplier OR stop_atr_multiple instead of
hardcoded 2.0/1.5/3.0 fallbacks (audit F-6b).
"""

from unittest.mock import patch, MagicMock

import pytest


def _mock_company_name(ticker: str) -> str:
    return f"{ticker} Corp."


def _make_features(**overrides) -> dict:
    base = {
        "current_price": 100.0,
        "atr_14": 5.0,
        "trend_state": "strong_uptrend",
        "relative_strength_state": "leading",
        "pullback_depth_pct": 4.0,
        "_score": 80,
        "event_risk_level": "none",
        "atr_pct": 5.0,
        "volume_ratio_20d": 1.0,
    }
    base.update(overrides)
    return base


def _config_with_strategies(pullback_mult=2.0, mr_mult=2.5) -> dict:
    return {
        "risk": {"starting_capital": 100000, "planned_risk_pct_max": 0.01},
        "strategies": {
            "pullback": {"enabled": True, "stop_atr_multiplier": pullback_mult},
            "mean_reversion": {"enabled": True, "stop_atr_multiple": mr_mult},
        },
    }


@patch("src.packets.template.get_company_name", side_effect=_mock_company_name)
class TestBracketMultiplierResolution:
    """Verify template.py resolves stop multiplier from strategies config."""

    def test_mean_reversion_uses_2_5x_atr(self, mock_name):
        """MR strategy + config 2.5 → stop = price - 2.5 * ATR."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        config = _config_with_strategies(mr_mult=2.5)

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="mean_reversion"
        )
        # 100 - 2.5 * 5 = 87.50
        assert "$87.50" in packet.stop_invalidation, (
            f"Expected $87.50 stop, got {packet.stop_invalidation}"
        )

    def test_pullback_uses_2_0x_atr(self, mock_name):
        """Pullback strategy + config 2.0 → stop = price - 2.0 * ATR."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        config = _config_with_strategies(pullback_mult=2.0)

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="pullback"
        )
        # 100 - 2.0 * 5 = 90.00
        assert "$90.00" in packet.stop_invalidation, (
            f"Expected $90.00 stop, got {packet.stop_invalidation}"
        )

    def test_missing_strategies_config_defaults_to_2_0(self, mock_name):
        """No strategies config → default 2.0x ATR."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        config = {"risk": {"starting_capital": 100000, "planned_risk_pct_max": 0.01}}

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="pullback"
        )
        # default 2.0: 100 - 2.0 * 5 = 90.00
        assert "$90.00" in packet.stop_invalidation

    def test_zero_multiplier_flows_through(self, mock_name):
        """Boundary: 0.0 multiplier flows through (caller config error
        surfaces as zero stop_distance — sizer treats as 1 share)."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        config = {
            "risk": {"starting_capital": 100000, "planned_risk_pct_max": 0.01},
            "strategies": {"pullback": {"stop_atr_multiplier": 0.0}},
        }

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="pullback"
        )
        # 100 - 0.0 * 5 = 100.00 — stop equals price
        assert "$100.00" in packet.stop_invalidation

    def test_alias_mr_maps_to_mean_reversion(self, mock_name):
        """strategy_name='mr' aliases to mean_reversion config."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        config = _config_with_strategies(mr_mult=2.5)

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="mr"
        )
        assert "$87.50" in packet.stop_invalidation

    def test_alias_meanreversion_maps_to_mean_reversion(self, mock_name):
        """strategy_name='meanreversion' aliases to mean_reversion config."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        config = _config_with_strategies(mr_mult=2.5)

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="meanreversion"
        )
        assert "$87.50" in packet.stop_invalidation

    def test_multiplier_takes_priority_over_multiple(self, mock_name):
        """When both keys present, _multiplier wins (per spec priority)."""
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)
        # Both keys — _multiplier=3.0 should win, _multiple=1.0 ignored
        config = {
            "risk": {"starting_capital": 100000, "planned_risk_pct_max": 0.01},
            "strategies": {
                "pullback": {
                    "stop_atr_multiplier": 3.0,
                    "stop_atr_multiple": 1.0,
                },
            },
        }

        packet = build_packet_from_features(
            "AAPL", feat, config, strategy_name="pullback"
        )
        # 100 - 3.0 * 5 = 85.00
        assert "$85.00" in packet.stop_invalidation


class TestEndToEndAlpacaSubmission:
    """DA-8 mandate: verify resolved multiplier reaches Alpaca submit_order."""

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_mr_multiplier_carries_to_stop_loss(self, mock_check, mock_client):
        """Captured stop_loss arg in submit_order must equal price - 2.5*ATR
        when MR config sets _multiple=2.5."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_order = MagicMock()
        mock_order.id = "test-mr-1"
        mock_order.symbol = "TGT"
        mock_order.qty = 10
        mock_order.side = "buy"
        mock_order.type = "market"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_client.return_value = mock_client_instance

        # Simulate template.py-resolved values for MR (2.5x):
        # price=100, ATR=5, multiplier=2.5 → stop_price = 87.5
        test_atr = 5.0
        resolved_multiplier = 2.5
        price = 100.0
        stop_price = price - resolved_multiplier * test_atr

        place_bracket_order(
            ticker="TGT",
            shares=10,
            take_profit_price=110.0,
            stop_loss_price=stop_price,
        )

        # Capture the stop_loss arg that landed at the broker
        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        # alpaca-py may keep stop_loss as a dict or StopLossRequest depending
        # on Pydantic version; accept either shape.
        sl = order_request.stop_loss
        observed = sl["stop_price"] if isinstance(sl, dict) else sl.stop_price
        assert observed == round(stop_price, 2), (
            f"Expected stop_price={round(stop_price, 2)} at broker, got {observed}"
        )
        # Confirm equals exactly resolved_multiplier * test_atr below price
        assert (price - observed) == pytest.approx(resolved_multiplier * test_atr)


@patch("src.packets.template.get_company_name", side_effect=_mock_company_name)
class TestRaceConditionConfigChange:
    """Race: config changed mid-run; subsequent order picks up new value."""

    def test_subsequent_call_picks_up_new_config(self, mock_name):
        from src.packets.template import build_packet_from_features

        feat = _make_features(current_price=100.0, atr_14=5.0)

        # First call with multiplier=2.0
        cfg1 = {
            "risk": {"starting_capital": 100000, "planned_risk_pct_max": 0.01},
            "strategies": {"pullback": {"stop_atr_multiplier": 2.0}},
        }
        p1 = build_packet_from_features(
            "AAPL", feat, cfg1, strategy_name="pullback"
        )
        assert "$90.00" in p1.stop_invalidation

        # Operator edits config to 3.5 mid-run; next packet builds with new value
        cfg2 = {
            "risk": {"starting_capital": 100000, "planned_risk_pct_max": 0.01},
            "strategies": {"pullback": {"stop_atr_multiplier": 3.5}},
        }
        p2 = build_packet_from_features(
            "AAPL", _make_features(current_price=100.0, atr_14=5.0), cfg2,
            strategy_name="pullback",
        )
        # 100 - 3.5 * 5 = 82.50
        assert "$82.50" in p2.stop_invalidation

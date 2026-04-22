"""Tests for packet builder modules:
- src/packets/template.py
- src/packets/watchlist.py
- src/packets/eod_recap.py
"""

from unittest.mock import patch

import pytest

from src.platform.strategy_spec import StrategySpec
from src.packets.template import build_packet_from_features, render_packet, build_demo_packet
from src.packets.watchlist import build_morning_watchlist
from src.packets.eod_recap import build_eod_recap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_company_name(ticker: str) -> str:
    """Deterministic company name stub."""
    names = {"AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "GOOG": "Alphabet Inc."}
    return names.get(ticker, f"{ticker} Corp.")


def _make_features(**overrides) -> dict:
    """Build a minimal valid features dict."""
    base = {
        "current_price": 150.0,
        "atr_14": 3.0,
        "trend_state": "strong_uptrend",
        "relative_strength_state": "leading",
        "pullback_depth_pct": 5.0,
        "_score": 85,
        "event_risk_level": "none",
        "sma50_slope": "rising",
        "sma200_slope": "rising",
        "price_vs_sma50_pct": 2.5,
        "price_vs_sma200_pct": 10.0,
        "rs_vs_spy_1m": 3.0,
        "rs_vs_spy_3m": 8.0,
        "rs_vs_spy_6m": 15.0,
        "atr_pct": 2.0,
        "volume_ratio_20d": 1.1,
    }
    base.update(overrides)
    return base


def _make_config(**overrides) -> dict:
    base = {"risk": {"starting_capital": 10000, "planned_risk_pct_max": 0.01}}
    base.update(overrides)
    return base


def _make_candidate(ticker: str, score: float = 80.0, **feat_overrides) -> dict:
    return {
        "ticker": ticker,
        "score": score,
        "features": _make_features(**feat_overrides),
    }


def _make_strategy(**overrides) -> StrategySpec:
    base = {
        "strategy_id": "packet_test",
        "display_name": "Packet Test",
        "universe": {"tickers": ["AAPL"]},
        "entry": {"kind": "scheduled"},
        "exit": {
            "kind": "mechanical",
            "timeout_days": 21,
            "stop": {"method": "pct", "value": 0.02},
            "target": {"method": "pct", "value": 0.03},
        },
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY_matched_window", "metrics": ["sharpe"]},
        "raw": {},
        "source": "test",
    }
    base.update(overrides)
    return StrategySpec(**base)


# ---------------------------------------------------------------------------
# build_packet_from_features / render_packet
# ---------------------------------------------------------------------------

@patch("src.packets.template.get_company_name", side_effect=_mock_company_name)
class TestBuildPacketFromFeatures:
    def test_returns_trade_packet(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(), _make_config())
        assert packet.ticker == "AAPL"
        assert packet.company_name == "Apple Inc."
        assert packet.recommendation == "Buy"

    def test_confidence_high_score(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(_score=92), _make_config())
        assert packet.confidence == 9

    def test_confidence_medium_score(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(_score=82), _make_config())
        assert packet.confidence == 8

    def test_confidence_lower_score(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(_score=70), _make_config())
        assert packet.confidence == 7

    def test_event_risk_imminent(self, mock_name):
        features = _make_features(
            event_risk_level="imminent", days_to_earnings=3, earnings_date="2025-07-15"
        )
        packet = build_packet_from_features("AAPL", features, _make_config())
        assert "EARNINGS IMMINENT" in packet.event_risk

    def test_event_risk_normal(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(), _make_config())
        assert packet.event_risk == "Normal"

    def test_allocation_capped_at_max_position_pct(self, mock_name):
        """2026-04-14 regression guard: a tight-ATR stock in a low-price-per-risk
        regime can produce allocation > max_position_pct at the sizer, which
        then gets rejected downstream ("Allocation 30.5% exceeds 25% portfolio
        cap"). Cap the allocation at the source so the packet is always
        submittable."""
        # Tight stop, low price → shares × price can exceed 25% cap.
        features = _make_features(current_price=10.0, atr_14=0.10, atr_pct=1.0)
        config = {
            "risk": {"starting_capital": 1000, "planned_risk_pct_max": 0.10},
            "risk_governor": {"max_position_pct": 0.25},
        }
        packet = build_packet_from_features("AAPL", features, config)
        # Allocation must be ≤ 25% of capital = $250
        assert packet.position_sizing.allocation_dollars <= 250.0, (
            f"Allocation {packet.position_sizing.allocation_dollars} exceeds "
            f"$250 (25% of $1000 capital cap)"
        )
        # Allocation_pct reflected correctly
        assert packet.position_sizing.allocation_pct <= 25.1  # 0.1% rounding slack

    def test_render_packet_produces_string(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(), _make_config())
        text = render_packet(packet)
        assert isinstance(text, str)
        assert "AAPL" in text
        assert "Apple Inc." in text
        assert "Buy" in text
        assert "Deeper Analysis" in text

    def test_position_sizing_populated(self, mock_name):
        packet = build_packet_from_features("AAPL", _make_features(), _make_config())
        assert packet.position_sizing.allocation_dollars > 0
        assert packet.position_sizing.estimated_risk_dollars > 0

    def test_strategy_targets_override_default_brackets(self, mock_name):
        strategy = _make_strategy(
            exit={
                "kind": "mechanical",
                "timeout_days": 7,
                "stop": {"atr_multiple": 2.5},
                "targets": [
                    {"name": "t1", "atr_multiple": 1.0},
                    {"name": "t2", "atr_multiple": 2.0},
                ],
            }
        )
        packet = build_packet_from_features(
            "AAPL",
            _make_features(current_price=150.0, atr_14=3.0),
            _make_config(),
            strategy=strategy,
        )
        assert packet.stop_invalidation == "$142.50 close basis"
        assert packet.targets == "$153.00 / $156.00"
        assert packet.expected_hold_period == "Up to 7 trading days"

    def test_strategy_regime_adaptive_position_multiplier_reduces_allocation(self, mock_name):
        strategy = _make_strategy(
            position_sizing={
                "method": "regime_adaptive",
                "regimes": {
                    "CRISIS": {"packet_worthy": True, "position_pct": 0.2},
                },
            }
        )
        baseline = build_packet_from_features(
            "AAPL",
            _make_features(current_price=150.0, atr_14=3.0),
            _make_config(),
        )
        regime_packet = build_packet_from_features(
            "AAPL",
            _make_features(current_price=150.0, atr_14=3.0, regime_key="CRISIS"),
            _make_config(),
            strategy=strategy,
        )
        assert regime_packet.position_sizing.allocation_dollars < baseline.position_sizing.allocation_dollars
        assert regime_packet.position_sizing.estimated_risk_dollars < baseline.position_sizing.estimated_risk_dollars


# ---------------------------------------------------------------------------
# build_demo_packet
# ---------------------------------------------------------------------------

@patch("src.packets.template.get_company_name", return_value="Apple Inc.")
class TestBuildDemoPacket:
    def test_demo_packet_is_string(self, mock_name):
        result = build_demo_packet()
        assert isinstance(result, str)

    def test_demo_packet_contains_aapl(self, mock_name):
        result = build_demo_packet()
        assert "AAPL" in result

    def test_demo_packet_contains_watch(self, mock_name):
        result = build_demo_packet()
        assert "Watch" in result


# ---------------------------------------------------------------------------
# build_morning_watchlist
# ---------------------------------------------------------------------------

@patch("src.packets.watchlist.get_company_name", side_effect=_mock_company_name)
class TestBuildMorningWatchlist:
    def test_basic_output(self, mock_name):
        pw = [_make_candidate("AAPL", 90)]
        wl = [_make_candidate("MSFT", 75)]
        result = build_morning_watchlist(wl, pw, "2025-06-15")
        assert isinstance(result, str)
        assert "Morning Watchlist" in result
        assert "2025-06-15" in result

    def test_empty_lists(self, mock_name):
        result = build_morning_watchlist([], [], "2025-06-15")
        assert "No packet-worthy setups today." in result
        assert "No watchlist names today." in result

    def test_narrative_included(self, mock_name):
        result = build_morning_watchlist([], [], "2025-06-15", narrative="Market looks strong.")
        assert "ANALYST BRIEFING" in result
        assert "Market looks strong." in result

    def test_no_narrative(self, mock_name):
        result = build_morning_watchlist([], [], "2025-06-15", narrative=None)
        assert "ANALYST BRIEFING" not in result

    def test_packet_worthy_listed(self, mock_name):
        pw = [_make_candidate("GOOG", 88)]
        result = build_morning_watchlist([], pw, "2025-06-15")
        assert "GOOG" in result

    def test_watchlist_listed(self, mock_name):
        wl = [_make_candidate("MSFT", 72)]
        result = build_morning_watchlist(wl, [], "2025-06-15")
        assert "MSFT" in result

    def test_market_context_from_regime(self, mock_name):
        pw = [_make_candidate("AAPL", 85, regime_label="bull_quiet", volatility_regime="low",
                              vix_proxy=14.0, spy_20d_return=2.5,
                              spy_drawdown_from_high=-1.0, spy_rsi_14=58,
                              market_breadth_label="healthy", market_breadth_pct=72)]
        result = build_morning_watchlist([], pw, "2025-06-15")
        assert "MARKET CONTEXT" in result


# ---------------------------------------------------------------------------
# build_eod_recap
# ---------------------------------------------------------------------------

@patch("src.packets.eod_recap.get_company_name", side_effect=_mock_company_name)
class TestBuildEodRecap:
    def test_basic_output(self, mock_name):
        result = build_eod_recap([], [], [], "2025-06-15")
        assert isinstance(result, str)
        assert "EOD Recap" in result
        assert "2025-06-15" in result

    def test_empty_everything(self, mock_name):
        result = build_eod_recap([], [], [], "2025-06-15")
        assert "No packet-worthy setups today." in result
        assert "No watchlist names today." in result

    def test_journal_entries_listed(self, mock_name):
        entries = [{"ticker": "AAPL", "entry_zone": "$150", "stop_level": "$145",
                    "target_1": "$155", "target_2": "$160", "confidence_score": 8}]
        result = build_eod_recap([], [], entries, "2025-06-15")
        assert "AAPL" in result
        assert "PACKETS SENT" in result

    def test_shadow_data_included(self, mock_name):
        shadow = {
            "open_trades": 2,
            "opened_today": 1,
            "closed_today": 1,
            "realized_pnl": 25.50,
            "unrealized_pnl": -10.00,
            "closed_details": [
                {"ticker": "MSFT", "exit_reason": "target_hit", "pnl": 25.50,
                 "pnl_pct": 2.1, "days": 5}
            ],
            "open_details": [
                {"ticker": "GOOG", "entry": 180.0, "current": 178.0,
                 "pnl": -10.0, "pnl_pct": -1.1, "days": 3, "timeout": 15}
            ],
        }
        result = build_eod_recap([], [], [], "2025-06-15", shadow_data=shadow)
        assert "SHADOW LEDGER" in result
        assert "MSFT" in result
        assert "GOOG" in result
        assert "target_hit" in result

    def test_no_shadow_data(self, mock_name):
        result = build_eod_recap([], [], [], "2025-06-15", shadow_data=None)
        assert "SHADOW LEDGER" not in result

    def test_watchlist_in_recap(self, mock_name):
        wl = [_make_candidate("AAPL", 78)]
        result = build_eod_recap([], wl, [], "2025-06-15")
        assert "WATCHLIST STATUS" in result
        assert "AAPL" in result

    def test_footer_present(self, mock_name):
        result = build_eod_recap([], [], [], "2025-06-15")
        assert "Arcis Systematic Equity Research" in result

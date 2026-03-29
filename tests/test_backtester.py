"""Tests for src/evaluation/backtester.py — walk-forward backtesting.

backtester.py uses function-level imports including one from a module that has
since been refactored (src.training.backfill.slice_to_date / compute_outcome).
We inject a mock module into sys.modules to make these imports succeed, then
patch the actual heavy dependencies.
"""

import sys
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ── Create a mock backfill module with the missing functions ──

_mock_backfill = ModuleType("src.training.backfill")
_mock_backfill.slice_to_date = MagicMock(return_value={})
_mock_backfill.compute_outcome = MagicMock(return_value={"pnl_pct": 3.5, "exit_reason": "target_1", "duration_days": 5})


@pytest.fixture(autouse=True)
def _patch_backfill_module():
    """Inject mock backfill module so backtester's function-level imports work."""
    original = sys.modules.get("src.training.backfill")
    sys.modules["src.training.backfill"] = _mock_backfill
    yield
    if original is not None:
        sys.modules["src.training.backfill"] = original
    else:
        sys.modules.pop("src.training.backfill", None)


# ── Helpers ──

def _mock_config():
    return {"shadow_trading": {"enabled": False}}


def _make_ohlcv():
    dates = pd.bdate_range("2025-01-01", periods=250)
    df = pd.DataFrame(
        {"Open": 100, "High": 105, "Low": 98, "Close": 102, "Volume": 1_000_000},
        index=dates,
    )
    return {"AAPL": df.copy(), "MSFT": df.copy()}


def _make_spy():
    dates = pd.bdate_range("2025-01-01", periods=250)
    return pd.DataFrame(
        {"Open": 400, "High": 410, "Low": 398, "Close": 405, "Volume": 5_000_000},
        index=dates,
    )


def _make_features():
    return {
        "AAPL": {"trend_state": "uptrend", "regime_label": "bull", "current_price": 150},
        "MSFT": {"trend_state": "uptrend", "regime_label": "bull", "current_price": 300},
    }


def _make_candidates():
    return {
        "packet_worthy": [
            {"ticker": "AAPL", "score": 85, "features": {"trend_state": "uptrend", "regime_label": "bull"}},
        ],
        "watchlist": [],
    }


def _make_packet():
    return SimpleNamespace(
        entry_zone="$150.00",
        stop_invalidation="$145.00",
        targets="$160.00 / $170.00",
        llm_conviction=None,
    )


# ── backtest_model tests ──

@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates())
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price", side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_backtest_model_normal(
    mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    # Configure the backfill mocks for this test
    _mock_backfill.slice_to_date = MagicMock(return_value=_make_ohlcv())
    _mock_backfill.compute_outcome = MagicMock(
        return_value={"pnl_pct": 3.5, "exit_reason": "target_1", "duration_days": 5}
    )

    from src.evaluation.backtester import backtest_model
    result = backtest_model("test_model_v1", months=6)

    assert result["model"] == "test_model_v1"
    assert "trades_generated" in result
    assert "win_rate" in result
    assert "total_pnl_pct" in result
    assert "sharpe_ratio" in result
    assert "max_drawdown_pct" in result
    assert "equity_curve" in result


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.ranking.ranker.get_top_candidates", return_value={"packet_worthy": [], "watchlist": []})
def test_backtest_model_empty_candidates(
    mock_top, mock_rank, mock_feat, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    _mock_backfill.slice_to_date = MagicMock(return_value=_make_ohlcv())

    from src.evaluation.backtester import backtest_model
    result = backtest_model("empty_model", months=2)

    assert result["model"] == "empty_model"
    assert result["trades_generated"] == 0


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", side_effect=Exception("API down"))
def test_backtest_model_data_fetch_error(mock_ohlcv, mock_universe, mock_config):
    from src.evaluation.backtester import backtest_model
    result = backtest_model("broken_model", months=1)
    assert "error" in result


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=pd.DataFrame())
def test_backtest_model_empty_spy(mock_spy, mock_ohlcv, mock_universe, mock_config):
    from src.evaluation.backtester import backtest_model
    result = backtest_model("spy_empty_model", months=1)
    assert "error" in result


# ── compare_models tests ──

@patch("src.evaluation.backtester.backtest_model")
def test_compare_models_picks_winner_by_sharpe(mock_bt):
    from src.evaluation.backtester import compare_models
    mock_bt.side_effect = [
        {"model": "A", "win_rate": 0.5, "sharpe_ratio": 0.3},
        {"model": "B", "win_rate": 0.6, "sharpe_ratio": 1.5},
    ]
    result = compare_models("A", "B", months=3)
    assert result["winner"] == "B"

@patch("src.evaluation.backtester.backtest_model")
def test_compare_models_tie_when_close_sharpe(mock_bt):
    from src.evaluation.backtester import compare_models
    mock_bt.side_effect = [
        {"model": "A", "win_rate": 0.5, "sharpe_ratio": 1.0},
        {"model": "B", "win_rate": 0.5, "sharpe_ratio": 1.05},
    ]
    result = compare_models("A", "B")
    assert result["winner"] == "tie"

@patch("src.evaluation.backtester.backtest_model")
def test_compare_models_a_wins(mock_bt):
    from src.evaluation.backtester import compare_models
    mock_bt.side_effect = [
        {"model": "A", "win_rate": 0.7, "sharpe_ratio": 2.0},
        {"model": "B", "win_rate": 0.4, "sharpe_ratio": 0.5},
    ]
    result = compare_models("A", "B")
    assert result["winner"] == "A"

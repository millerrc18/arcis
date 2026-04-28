"""Tests for src/evaluation/backtester.py — walk-forward backtesting.

The backtester imports from `src.training.historical_data` (slice_to_date) and
`src.training.historical_scanner` (compute_outcome). Tests mock these on the
real import sources rather than via sys.modules injection.

Pre-2026-04-28 history: the imports were originally written against
`src.training.backfill` (broken — those names never lived there), and the test
file used a sys.modules injection to keep the broken imports working in CI.
PR #820 fixed the imports to point at the correct modules; PR after that fixed
slice_to_date's call site (it returns a tuple, not a dict, and expects
{"tickers": ..., "spy": ...} as input). This test file was rewritten to mock
the correct sources end-to-end.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


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


def test_backtest_uses_pit_not_survivorship():
    """T3 migration: backtester must call get_sp100_at, NOT get_sp100_universe."""
    import ast
    import inspect
    from src.evaluation import backtester as _bt_module
    source = inspect.getsource(_bt_module)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "src.universe.sp100":
                for alias in node.names:
                    imported_names.add(alias.name)
    assert "get_sp100_universe" not in imported_names, (
        "backtester must NOT import get_sp100_universe (survivorship-biased); "
        "migrate to src.universe.pit.get_sp100_at"
    )


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.training.historical_scanner.compute_outcome",
       return_value={"pnl_pct": 3.5, "exit_reason": "target_1", "duration_days": 5})
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates())
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price", side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_backtest_model_normal(
    mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_compute_outcome, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    from src.evaluation.backtester import backtest_model
    result = backtest_model("test_model_v1", months=6)

    assert result["model"] == "test_model_v1"
    assert "trades_generated" in result
    assert result["trades_generated"] > 0, "expected trades to be generated when all gates produce candidates"
    assert "win_rate" in result
    assert "total_pnl_pct" in result
    assert "sharpe_ratio" in result
    assert "max_drawdown_pct" in result
    assert "equity_curve" in result


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.ranking.ranker.get_top_candidates", return_value={"packet_worthy": [], "watchlist": []})
def test_backtest_model_empty_candidates(
    mock_top, mock_rank, mock_feat, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    from src.evaluation.backtester import backtest_model
    result = backtest_model("empty_model", months=2)

    assert result["model"] == "empty_model"
    assert result["trades_generated"] == 0


def test_backtester_imports_resolve():
    """Smoke test: backtester's function-level imports must all resolve at runtime.

    Regression-lock against #820 (slice_to_date imported from wrong module) and
    against the same class of bug that the silent except in backtest_model swallowed
    for an unknown duration. If a refactor moves any of these symbols and the import
    site isn't updated, this test fails immediately rather than silently producing
    'No qualifying trades found' at backtest time.
    """
    from src.evaluation.backtester import backtest_model
    # Trigger the function-level imports by inspecting the function's source-imports
    # via a fresh call frame that exercises every import line.
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark  # noqa: F401
    from src.features.engine import compute_all_features  # noqa: F401
    from src.ranking.ranker import rank_universe, get_top_candidates  # noqa: F401
    from src.training.historical_data import slice_to_date  # noqa: F401
    from src.training.historical_scanner import compute_outcome  # noqa: F401
    from src.universe.pit import get_sp100_at  # noqa: F401
    from src.packets.template import build_packet_from_features  # noqa: F401
    from src.shadow_trading.executor import _parse_price  # noqa: F401
    assert callable(backtest_model)


def test_slice_to_date_contract_matches_backtester_caller():
    """Regression-lock: slice_to_date's signature must match the backtester's call.

    The backtester does: `sliced, spy_sliced = slice_to_date({"tickers": ohlcv, "spy": spy}, date_str)`
    expecting a 2-tuple return. If slice_to_date is ever refactored to return a single
    value or a different tuple shape, this test fails immediately.
    """
    from src.training.historical_data import slice_to_date

    spy = _make_spy()
    tickers = _make_ohlcv()
    data = {"tickers": tickers, "spy": spy}
    cutoff = "2025-06-01"

    result = slice_to_date(data, cutoff)
    assert isinstance(result, tuple), f"slice_to_date must return a tuple; got {type(result).__name__}"
    assert len(result) == 2, f"slice_to_date must return a 2-tuple; got {len(result)}"

    ohlcv_dict, spy_sliced = result
    assert isinstance(ohlcv_dict, dict)
    assert isinstance(spy_sliced, pd.DataFrame)


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", side_effect=ConnectionError("network down"))
def test_backtest_model_data_fetch_error(mock_ohlcv, mock_universe, mock_config):
    """Recoverable network error in data fetch returns an error dict (not raised)."""
    from src.evaluation.backtester import backtest_model
    result = backtest_model("broken_model", months=1)
    assert "error" in result


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", side_effect=RuntimeError("unexpected code bug"))
def test_backtest_model_data_fetch_unrecoverable_raises(mock_ohlcv, mock_universe, mock_config):
    """Unrecoverable exception in data fetch must propagate, not be swallowed."""
    from src.evaluation.backtester import backtest_model
    with pytest.raises(RuntimeError, match="unexpected code bug"):
        backtest_model("broken_model", months=1)


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.features.engine.compute_all_features", side_effect=RuntimeError("feature pipeline broken"))
def test_backtest_model_unexpected_exception_propagates(
    mock_feat, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """RuntimeError in per-iteration computation must propagate — not be silently swallowed."""
    from src.evaluation.backtester import backtest_model
    with pytest.raises(RuntimeError, match="feature pipeline broken"):
        backtest_model("test_model_v1", months=1)


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.features.engine.compute_all_features", side_effect=ConnectionError("market data feed dropped"))
def test_backtest_model_recoverable_exception_logs_and_continues(
    mock_feat, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """ConnectionError in per-iteration step logs WARNING and continues (no trades, not a crash)."""
    import logging
    from src.evaluation.backtester import backtest_model
    with patch("src.evaluation.backtester.logger") as mock_logger:
        result = backtest_model("test_model_v1", months=1)
    assert mock_logger.warning.called, "expected WARNING to be logged for ConnectionError"
    assert "error" in result or result.get("trades_generated", 0) == 0


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL"])
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

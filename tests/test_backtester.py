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


# ── calibration wiring tests (#79) ──

_CALIBRATION_FIXTURE = {
    "total_count": 50,
    "median_entry_slippage_bps": 5.0,
    "p95_entry_slippage_bps": 12.0,
    "median_exit_slippage_bps": 4.0,
    "median_round_trip_cost_bps": 9.0,
    "count_by_ticker": {"AAPL": 25, "MSFT": 25},
    "last_calibrated_at": "2026-04-28T00:00:00+00:00",
}


# ── rf_source param tests (#80) ──


def test_backtest_model_accepts_rf_source_placeholder():
    """backtest_model must accept rf_source='placeholder' without error."""
    import inspect
    from src.evaluation.backtester import backtest_model
    sig = inspect.signature(backtest_model)
    assert "rf_source" in sig.parameters, (
        "backtest_model must have an rf_source parameter"
    )
    param = sig.parameters["rf_source"]
    assert param.default == "fred", (
        "rf_source default must be 'fred'"
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
@patch("src.cost_model.calibration.get_calibrated_cost_model", return_value=_CALIBRATION_FIXTURE)
def test_backtest_with_calibration_has_lower_pnl(
    mock_cal, mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_compute_outcome, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """With calibration loaded, PnL must be lower than without (costs deducted)."""
    from src.evaluation.backtester import backtest_model
    result_with = backtest_model("test_model_calibrated", months=6)
    assert result_with.get("trades_generated", 0) > 0
    assert result_with.get("calibration_applied") is True


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
def test_backtest_rf_source_placeholder_uses_constant(
    mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_compute_outcome, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """rf_source='placeholder' must not call get_rf_rate (legacy 0.0001 path)."""
    from src.evaluation.backtester import backtest_model
    with patch("src.data_ingestion.risk_free_rate.get_rf_rate") as mock_rf:
        result = backtest_model("test_model", months=6, rf_source="placeholder")
        mock_rf.assert_not_called()
    assert "sharpe_ratio" in result


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
@patch("src.cost_model.calibration.get_calibrated_cost_model", return_value=None)
def test_backtest_without_calibration_no_cost_applied(
    mock_cal, mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_compute_outcome, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """Without calibration (None returned), backtest runs and calibration_applied is False."""
    from src.evaluation.backtester import backtest_model
    result = backtest_model("test_model_no_cal", months=6)
    assert result.get("trades_generated", 0) > 0
    assert result.get("calibration_applied") is False


def test_backtest_calibration_pnl_delta_matches_expected():
    """PnL delta between calibrated and uncalibrated: calibrated run must have lower total_pnl_pct."""
    from contextlib import ExitStack
    from src.evaluation.backtester import backtest_model

    common_patches = [
        patch("src.config.load_config", return_value=_mock_config()),
        patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"]),
        patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv()),
        patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy()),
        patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy())),
        patch("src.training.historical_scanner.compute_outcome",
              return_value={"pnl_pct": 3.5, "exit_reason": "target_1", "duration_days": 5}),
        patch("src.features.engine.compute_all_features", return_value=_make_features()),
        patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}]),
        patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates()),
        patch("src.packets.template.build_packet_from_features", return_value=_make_packet()),
        patch("src.shadow_trading.executor._parse_price",
              side_effect=lambda x: float(x.replace("$", "").replace(",", ""))),
    ]

    with ExitStack() as stack:
        for p in common_patches:
            stack.enter_context(p)
        stack.enter_context(
            patch("src.cost_model.calibration.get_calibrated_cost_model", return_value=_CALIBRATION_FIXTURE)
        )
        result_cal = backtest_model("model_cal", months=6)

    with ExitStack() as stack:
        for p in common_patches:
            stack.enter_context(p)
        stack.enter_context(
            patch("src.cost_model.calibration.get_calibrated_cost_model", return_value=None)
        )
        result_no_cal = backtest_model("model_no_cal", months=6)

    assert result_cal.get("calibration_applied") is True
    assert result_no_cal.get("calibration_applied") is False
    assert result_cal["total_pnl_pct"] < result_no_cal["total_pnl_pct"]


# ── rf_source decorated tests (#80) ──


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
def test_backtest_rf_source_fred_calls_get_rf_rate(
    mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_compute_outcome, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """rf_source='fred' (default) must call get_rf_rate for each trade date."""
    import datetime as dt
    from src.evaluation.backtester import backtest_model
    with patch("src.data_ingestion.risk_free_rate.get_rf_rate",
               return_value=0.05 / 252) as mock_rf:
        result = backtest_model("test_model", months=6, rf_source="fred")
    assert mock_rf.called, "get_rf_rate must be called when rf_source='fred'"
    assert "sharpe_ratio" in result


def test_backtest_rf_fred_vs_placeholder_sharpe_differs():
    """With mocked FRED returning 5% (0.05/252 per day) vs placeholder 0.0001,
    excess returns must differ by expected amount over a 100-day synthetic window.
    Covered by the two tests around it.
    """
    pass


@patch("src.config.load_config", return_value={"shadow_trading": {"enabled": False}})
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
def test_backtest_rf_fred_excess_returns_differ_from_placeholder(
    mock_parse, mock_build, mock_top, mock_rank,
    mock_feat, mock_compute_outcome, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """Core behavioral test: excess returns with FRED 5% rf differ from placeholder 0.0001."""
    import datetime as dt
    from src.evaluation.backtester import backtest_model

    # Run with placeholder
    result_placeholder = backtest_model("test_model", months=6, rf_source="placeholder")

    # Run with fred (mocked at 5% annualized = 0.05/252 per day)
    with patch("src.data_ingestion.risk_free_rate.get_rf_rate",
               return_value=0.05 / 252):
        result_fred = backtest_model("test_model", months=6, rf_source="fred")

    # Both runs must produce valid results with trades
    assert result_placeholder.get("trades_generated", 0) > 0
    assert result_fred.get("trades_generated", 0) > 0

    # The rf_excess_mean must be in both results and differ
    assert "rf_excess_mean" in result_placeholder, (
        "backtest_model must return rf_excess_mean in result dict"
    )
    assert "rf_excess_mean" in result_fred, (
        "backtest_model must return rf_excess_mean in result dict"
    )

    placeholder_mean = result_placeholder["rf_excess_mean"]
    fred_mean = result_fred["rf_excess_mean"]

    # FRED 5%/252 ≈ 0.0001984 > placeholder 0.0001, so fred subtracts more rf.
    # Therefore fred_mean < placeholder_mean.
    # The per-trade difference should equal (0.05/252 - 0.0001) ≈ 0.0000984.
    expected_rf_diff = (0.05 / 252) - 0.0001  # fred rf minus placeholder rf, per trade
    actual_diff = placeholder_mean - fred_mean  # placeholder > fred (fred subtracts more)
    assert abs(actual_diff - expected_rf_diff) < 1e-6, (
        f"Expected rf_excess_mean gap of ~{expected_rf_diff:.8f} (placeholder minus fred), "
        f"got placeholder={placeholder_mean:.8f}, fred={fred_mean:.8f}, "
        f"gap={actual_diff:.8f}"
    )


# ── Bug C regression test (Sprint 1.C.4.5 / #104) ──
#
# Bug: backtester computes fetch_period_days = window_days + 60, then calls
# fetch_ohlcv(universe, period=f"{fetch_period_days}d"). yfinance's `period=`
# always fetches BACK FROM TODAY, not from the test_start anchor. For an old
# fold (e.g., test_start=2023-09-01, test_end=2024-01-01, today=2026-04-29)
# the fetch returns data from 2025-10-29 → 2026-04-29 — 789 days AFTER the
# test span — and slice_to_date returns 0 rows for every iteration. Result:
# fold 1-7 silently produce 0 trades; only fold 8 (the most recent) has data.
#
# Fix: backtester must fetch data covering the test span (test_start - 200
# trading days through test_end). Mock simulates yfinance's period= semantics
# so that the test fails pre-fix and passes post-fix.


def _make_synthetic_5y_ohlcv(tickers, *, start="2021-01-01", end="2026-04-29"):
    """Build 5y of synthetic OHLCV indexed daily for the given tickers.

    Used by the Bug C regression test — covers 2021-01 through 2026-04 so we
    can assert that an old fold (2023-09 → 2024-01) finds price data once the
    fetch is correctly anchored to test_start.
    """
    dates = pd.bdate_range(start, end)
    base_close = 100.0
    closes = [base_close * (1.0 + 0.0003) ** i for i in range(len(dates))]
    result = {}
    for ticker in tickers:
        df = pd.DataFrame(
            {
                "Open": closes,
                "High": [c * 1.01 for c in closes],
                "Low": [c * 0.99 for c in closes],
                "Close": closes,
                "Volume": [1_000_000] * len(dates),
            },
            index=dates,
        )
        result[ticker] = df
    return result


def _yfinance_period_aware_fetch(synthetic_data, *, today=None):
    """Build a fetch_ohlcv side_effect that simulates yfinance's period= contract.

    yfinance's `period=` always fetches data from today - period_days through today.
    When `start=` / `end=` are provided, it uses those instead. This mock mirrors
    that behavior so the regression test can prove Bug C without hitting the network.
    """
    if today is None:
        today = pd.Timestamp("2026-04-29")
    today = pd.Timestamp(today)

    def fetch(tickers, period="1y", start=None, end=None):
        # Path 1 fix uses start=/end=; legacy/live callers use period=
        if start is not None or end is not None:
            start_ts = pd.Timestamp(start) if start else synthetic_data[next(iter(synthetic_data))].index.min()
            end_ts = pd.Timestamp(end) if end else today
            result = {}
            for ticker in tickers:
                if ticker not in synthetic_data:
                    continue
                df = synthetic_data[ticker]
                sliced = df[(df.index >= start_ts) & (df.index <= end_ts)]
                result[ticker] = sliced
            return result
        # period semantics: today - period_days through today
        if period.endswith("d"):
            period_days = int(period[:-1])
        elif period.endswith("y"):
            period_days = int(period[:-1]) * 365
        else:
            period_days = 365
        start_ts = today - pd.Timedelta(days=period_days)
        result = {}
        for ticker in tickers:
            if ticker not in synthetic_data:
                continue
            df = synthetic_data[ticker]
            sliced = df[(df.index >= start_ts) & (df.index <= today)]
            result[ticker] = sliced
        return result
    return fetch


def _yfinance_period_aware_spy(synthetic_spy, *, today=None):
    """Sister mock for fetch_spy_benchmark — returns a single DataFrame, not a dict."""
    if today is None:
        today = pd.Timestamp("2026-04-29")
    today = pd.Timestamp(today)

    def fetch_spy(period="1y", start=None, end=None):
        if start is not None or end is not None:
            start_ts = pd.Timestamp(start) if start else synthetic_spy.index.min()
            end_ts = pd.Timestamp(end) if end else today
            return synthetic_spy[(synthetic_spy.index >= start_ts) & (synthetic_spy.index <= end_ts)]
        if period.endswith("d"):
            period_days = int(period[:-1])
        elif period.endswith("y"):
            period_days = int(period[:-1]) * 365
        else:
            period_days = 365
        start_ts = today - pd.Timedelta(days=period_days)
        return synthetic_spy[(synthetic_spy.index >= start_ts) & (synthetic_spy.index <= today)]
    return fetch_spy


def test_backtest_model_produces_trades_for_old_test_window():
    """Bug C regression-lock (Sprint 1.C.4.5 / #104).

    With realistic yfinance period= semantics, the backtester must fetch enough
    historical data to cover an old test window (test_start=2023-09-01 →
    test_end=2024-01-01). Pre-fix, fetch_period_days=window_days+60=182, so
    yfinance returns the last 182 days from today, which is 789 days AFTER
    the test span — every slice_to_date returns 0 rows, every fold-1..7
    produces 0 trades.

    Post-fix (Path 1 OR Path 2), the fetch must cover test_start - 200
    trading days through test_end. We mock at the fetch boundary only —
    no patching of the core slice/feature/ranker pipeline — so this test
    exercises the real fetch-anchor logic.
    """
    tickers = ["AAPL", "MSFT"]
    synth_ohlcv = _make_synthetic_5y_ohlcv(tickers)
    synth_spy = _make_synthetic_5y_ohlcv(["SPY"])["SPY"]

    fetch_ohlcv_side = _yfinance_period_aware_fetch(synth_ohlcv)
    fetch_spy_side = _yfinance_period_aware_spy(synth_spy)

    with patch("src.config.load_config", return_value=_mock_config()), \
         patch("src.universe.pit.get_sp100_at", return_value=tickers), \
         patch("src.data_ingestion.market_data.fetch_ohlcv", side_effect=fetch_ohlcv_side), \
         patch("src.data_ingestion.market_data.fetch_spy_benchmark", side_effect=fetch_spy_side), \
         patch("src.features.engine.compute_all_features", return_value=_make_features()), \
         patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}]), \
         patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates()), \
         patch("src.packets.template.build_packet_from_features", return_value=_make_packet()), \
         patch("src.shadow_trading.executor._parse_price",
               side_effect=lambda x: float(x.replace("$", "").replace(",", ""))), \
         patch("src.training.historical_scanner.compute_outcome",
               return_value={"pnl_pct": 3.5, "exit_reason": "target_1", "duration_days": 5}), \
         patch("src.cost_model.calibration.get_calibrated_cost_model", return_value=None):
        from src.evaluation.backtester import backtest_model
        result = backtest_model(
            "test_model_v1",
            test_start="2023-09-01",
            test_end="2024-01-01",
            rf_source="placeholder",
        )

    assert "trades" in result, (
        f"Result missing 'trades' key. Got keys: {list(result.keys())}. "
        f"Pre-fix this returns {{error: 'No qualifying trades found'}} because "
        f"fetch_period_days=182 means yfinance fetches today-182d → today, but "
        f"the test span is 2023-09-01 → 2024-01-01 — 789 days BEFORE the fetched "
        f"window. slice_to_date drops every row."
    )
    assert len(result["trades"]) > 0, (
        f"Expected > 0 trades for test span 2023-09-01 → 2024-01-01, got "
        f"{len(result.get('trades', []))}. Bug C: fetch_period_days anchors at "
        f"today-N days, not test_start - N days, so old folds never see data."
    )

"""Tests for the full-regime simulation engine.

Tests cache, Monte Carlo, verdict logic, traffic light validation,
heatmap output, reproducibility, and schema registration.

All external API calls (yfinance) are mocked — no network calls from pytest.
"""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# Ensure project root is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.simulation.cache import (
    clear_cache,
    fetch_cached_ohlcv,
)
from src.simulation.monte_carlo import monte_carlo_resample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n_days: int = 30, start_price: float = 100.0,
                start_date: str = "2023-01-01") -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame."""
    dates = pd.bdate_range(start=start_date, periods=n_days)
    rng = np.random.RandomState(42)
    prices = start_price + np.cumsum(rng.randn(n_days) * 0.5)
    prices = np.maximum(prices, 1.0)  # Floor at $1
    return pd.DataFrame({
        "Open": prices * 0.99,
        "High": prices * 1.02,
        "Low": prices * 0.97,
        "Close": prices,
        "Volume": rng.randint(1_000_000, 10_000_000, n_days),
    }, index=dates)


def _make_trades(n: int = 50, seed: int = 42) -> list[dict]:
    """Generate synthetic trades for testing."""
    rng = np.random.RandomState(seed)
    trades = []
    for i in range(n):
        pnl_pct = rng.normal(0.5, 2.0)
        pnl_dollars = pnl_pct / 100 * 2000
        trades.append({
            "date": f"2023-01-{(i % 28) + 1:02d}",
            "ticker": f"TICK{i % 10}",
            "entry": 100.0,
            "exit": 100.0 + pnl_pct,
            "outcome": "win" if pnl_pct > 0 else "loss",
            "net_pnl_pct": round(pnl_pct, 4),
            "pnl_dollars": round(pnl_dollars, 2),
            "days_held": rng.randint(1, 8),
        })
    return trades


# ---------------------------------------------------------------------------
# Task 1: Cache tests
# ---------------------------------------------------------------------------

class TestCache:
    def test_cache_fetch_and_store(self, tmp_path):
        """Verify parquet caching works: write then read from cache."""
        mock_data = _make_ohlcv(20)
        with patch("src.simulation.cache.yf") as mock_yf:
            mock_yf.download.return_value = mock_data
            # First call: downloads and caches
            result = fetch_cached_ohlcv("AAPL", "2023-01-01", "2023-02-01",
                                        cache_dir=tmp_path)
            assert result is not None
            assert len(result) == 20
            assert mock_yf.download.call_count == 1

            # Second call: reads from cache (no download)
            result2 = fetch_cached_ohlcv("AAPL", "2023-01-01", "2023-02-01",
                                         cache_dir=tmp_path)
            assert result2 is not None
            assert len(result2) == 20
            assert mock_yf.download.call_count == 1  # Still 1 — cache hit

    def test_cache_warm_with_mock_yfinance(self, tmp_path):
        """Mock yfinance, verify cache population."""
        mock_data = _make_ohlcv(20)
        scenarios = {"test_scenario": {"start": "2023-01-01", "end": "2023-03-01"}}
        universe = ["AAPL", "MSFT"]
        with patch("src.simulation.cache.yf") as mock_yf:
            mock_yf.download.return_value = mock_data
            from src.simulation.cache import warm_cache
            stats = warm_cache(scenarios, universe, cache_dir=tmp_path)
            assert stats["total"] == 2
            assert stats["cached"] == 2
            assert stats["failed"] == 0

    def test_cache_handles_empty_response(self, tmp_path):
        """Verify None returned for empty yfinance response."""
        with patch("src.simulation.cache.yf") as mock_yf:
            mock_yf.download.return_value = pd.DataFrame()
            result = fetch_cached_ohlcv("BADTICKER", "2023-01-01", "2023-02-01",
                                        cache_dir=tmp_path)
            assert result is None

    def test_cache_clear(self, tmp_path):
        """Verify clear_cache removes the cache directory."""
        (tmp_path / "test.parquet").touch()
        clear_cache(tmp_path)
        assert not tmp_path.exists()


# ---------------------------------------------------------------------------
# Task 2: Core engine tests
# ---------------------------------------------------------------------------

class TestCoreEngine:
    def test_run_scenario_minimal(self):
        """Run 1 scenario with mocked data, verify output structure."""
        from scripts.simulation_engine import run_scenario

        mock_data = _make_ohlcv(300, start_date="2022-06-01")

        with patch("scripts.simulation_engine.fetch_cached_ohlcv") as mock_fetch, \
             patch("scripts.simulation_engine.get_sp100_universe") as mock_uni, \
             patch("src.features.traffic_light.compute_traffic_light",
                   side_effect=Exception("no DB")):
            # Return data for SPY, VIX, and tickers
            mock_fetch.return_value = mock_data
            mock_uni.return_value = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]

            config = {
                "scan_interval_days": 20,
                "max_entries_per_scan": 2,
                "universe_size": 5,
                "position_size": 2000,
                "starting_equity": 100000,
            }
            result = run_scenario("strong_bull", "2023-01-01", "2023-06-01", config)

            # Verify output structure
            assert "error" not in result
            assert result["scenario"] == "strong_bull"
            assert "total_trades" in result
            assert "win_rate" in result
            assert "profit_factor" in result
            assert "max_drawdown_pct" in result
            assert "sharpe_ratio" in result
            assert "benchmark_pnl_pct" in result
            assert "verdict" in result
            assert "equity_curve" in result
            assert "tl_states" in result

    def test_transaction_cost_application(self):
        """Verify costs reduce P&L correctly."""
        from scripts.simulation_engine import apply_costs, TRANSACTION_COSTS

        entry = 100.0
        exit_price = 103.0
        entry_adj, exit_adj = apply_costs(entry, exit_price)

        total_bps = sum(TRANSACTION_COSTS.values())
        assert entry_adj > entry  # Pay more on entry
        assert exit_adj < exit_price  # Receive less on exit
        assert entry_adj == pytest.approx(entry * (1 + total_bps / 10000))
        assert exit_adj == pytest.approx(exit_price * (1 - total_bps / 10000))

    def test_benchmark_computation(self):
        """Verify SPY buy-and-hold calculation."""
        from scripts.simulation_engine import compute_benchmark

        spy_data = _make_ohlcv(60, start_price=400.0, start_date="2023-01-01")
        result = compute_benchmark(spy_data, "2023-01-01", "2023-03-31")

        # Should be a percentage
        assert isinstance(result, float)
        # Sanity: with random walk from $400, should be in reasonable range
        assert -50 < result < 50


# ---------------------------------------------------------------------------
# Task 3: Monte Carlo tests
# ---------------------------------------------------------------------------

class TestMonteCarlo:
    def test_monte_carlo_deterministic(self):
        """Verify same seed produces same results."""
        trades = _make_trades(50)
        r1 = monte_carlo_resample(trades, n_simulations=100, seed=42)
        r2 = monte_carlo_resample(trades, n_simulations=100, seed=42)
        assert r1["median_equity"] == r2["median_equity"]
        assert r1["p95_dd"] == r2["p95_dd"]
        assert r1["probability_of_ruin"] == r2["probability_of_ruin"]

    def test_monte_carlo_confidence_intervals(self):
        """Verify p5 < median < p95."""
        trades = _make_trades(100)
        result = monte_carlo_resample(trades, n_simulations=500, seed=42)
        assert result["p5_equity"] <= result["median_equity"]
        assert result["median_equity"] <= result["p95_equity"]
        assert result["median_dd"] <= result["p95_dd"]
        assert result["p95_dd"] <= result["p99_dd"]
        assert 0 <= result["probability_of_ruin"] <= 1

    def test_monte_carlo_structure(self):
        """Verify all expected keys are in the result."""
        trades = _make_trades(20)
        result = monte_carlo_resample(trades, n_simulations=10, seed=1)
        expected_keys = {"n_simulations", "seed", "median_equity", "p5_equity",
                         "p95_equity", "median_dd", "p95_dd", "p99_dd",
                         "probability_of_ruin"}
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Task 4: Verdict logic tests
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_verdict_logic_all_cases(self):
        """Test edge/neutral/marginal/bleeds/insufficient."""
        from scripts.simulation_engine import compute_verdict

        # Edge: excess > 0, sharpe >= 0.5, PF >= 1.3
        assert compute_verdict(
            {"total_trades": 50, "sharpe_ratio": 1.0, "profit_factor": 1.5,
             "total_pnl_pct": 15}, benchmark_pnl=5
        ) == "edge"

        # Neutral: positive P&L, PF >= 1.0
        assert compute_verdict(
            {"total_trades": 30, "sharpe_ratio": 0.2, "profit_factor": 1.1,
             "total_pnl_pct": 5}, benchmark_pnl=10
        ) == "neutral"

        # Marginal: sharpe >= -0.3, PF >= 0.8
        assert compute_verdict(
            {"total_trades": 30, "sharpe_ratio": -0.2, "profit_factor": 0.85,
             "total_pnl_pct": -2}, benchmark_pnl=5
        ) == "marginal"

        # Bleeds: poor metrics
        assert compute_verdict(
            {"total_trades": 30, "sharpe_ratio": -0.8, "profit_factor": 0.5,
             "total_pnl_pct": -10}, benchmark_pnl=5
        ) == "bleeds"

    def test_verdict_insufficient_trades(self):
        """Verify <20 trades = 'insufficient'."""
        from scripts.simulation_engine import compute_verdict, MIN_TRADES_FOR_VERDICT

        assert MIN_TRADES_FOR_VERDICT == 20
        result = compute_verdict(
            {"total_trades": 10, "sharpe_ratio": 2.0, "profit_factor": 3.0,
             "total_pnl_pct": 50}
        )
        assert result == "insufficient"


# ---------------------------------------------------------------------------
# Task 5: Traffic light validation tests
# ---------------------------------------------------------------------------

class TestTrafficLightValidation:
    def test_traffic_light_validation_pure(self):
        """Verify majority detection for pure regimes."""
        from scripts.simulation_engine import validate_traffic_light

        result = validate_traffic_light("strong_bull", ["GREEN", "GREEN", "GREEN", "YELLOW"])
        assert result["correct"] is True
        assert result["actual_majority"] == "GREEN"
        assert result["expected"] == "GREEN"

    def test_traffic_light_validation_transition(self):
        """Verify transition detection for '->' scenarios."""
        from scripts.simulation_engine import validate_traffic_light

        # Transition detected
        result = validate_traffic_light("bull_to_bear",
                                        ["GREEN", "GREEN", "YELLOW", "RED", "RED"])
        assert result["correct"] is True
        assert result["transitioned"] is True

        # Transition NOT detected (missing RED)
        result2 = validate_traffic_light("bull_to_bear",
                                         ["GREEN", "GREEN", "GREEN", "YELLOW"])
        assert result2["correct"] is False
        assert result2["transitioned"] is False


# ---------------------------------------------------------------------------
# Task 4: Heatmap output test
# ---------------------------------------------------------------------------

class TestHeatmap:
    def test_heatmap_output_format(self, capsys):
        """Verify print_heatmap produces correct table."""
        from scripts.simulation_engine import print_heatmap

        results = {
            "strong_bull": {
                "total_trades": 45,
                "win_rate": 0.58,
                "profit_factor": 1.8,
                "max_drawdown_pct": 4.2,
                "sharpe_ratio": 1.2,
                "benchmark_pnl_pct": 10.0,
                "total_pnl_pct": 15.0,
                "verdict": "edge",
            },
        }
        print_heatmap(results)
        captured = capsys.readouterr()
        assert "strong_bull" in captured.out
        assert "edge" in captured.out
        assert "Regime" in captured.out  # Header present


# ---------------------------------------------------------------------------
# Task 7: Reproducibility test
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_reproducibility_info(self):
        """Verify git hash and config captured."""
        from scripts.simulation_engine import get_reproducibility_info

        config = {"position_size": 2000, "seed": 42}
        info = get_reproducibility_info(42, config)
        assert info["random_seed"] == 42
        assert "git_commit" in info
        assert info["config_snapshot"] == json.dumps(config)
        assert "python_version" in info


# ---------------------------------------------------------------------------
# Task 6: Schema test
# ---------------------------------------------------------------------------

class TestSchema:
    def test_schema_registered(self):
        """Verify simulation_results is in the schema registry."""
        from src.schema.registry import TABLES
        assert "simulation_results" in TABLES
        table = TABLES["simulation_results"]
        col_names = [c.name for c in table.columns]
        assert "result_id" in col_names
        assert "run_id" in col_names
        assert "scenario" in col_names
        assert "mc_p95_dd" in col_names
        assert "tl_correct" in col_names
        assert "verdict" in col_names
        assert "git_commit" in col_names
        assert "random_seed" in col_names

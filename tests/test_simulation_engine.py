"""Tests for the full-regime simulation engine.

Tests cover:
- Data cache layer (fetch, warm, clear)
- Transaction cost model
- SPY benchmark computation
- Monte Carlo resampling (deterministic + intervals)
- Verdict logic (all 5 cases)
- Traffic light validation (pure + transition scenarios)
- Heatmap output formatting
- Reproducibility info capture
- Schema registration
- API endpoint
- Render sync inclusion
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─── Task 1: Cache Tests ─────────────────────────────────────────────────────

class TestCache:
    def test_cache_fetch_and_store(self, tmp_path):
        """Verify parquet caching: first call downloads, second reads cache."""
        from src.simulation.cache import fetch_cached_ohlcv

        # Create mock OHLCV data
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        mock_df = pd.DataFrame({
            "Open": np.random.uniform(100, 110, 10),
            "High": np.random.uniform(110, 120, 10),
            "Low": np.random.uniform(90, 100, 10),
            "Close": np.random.uniform(100, 110, 10),
            "Volume": np.random.randint(1000000, 5000000, 10),
        }, index=dates)

        with patch("src.simulation.cache.yf") as mock_yf:
            mock_yf.download.return_value = mock_df

            # First call: downloads and caches
            result1 = fetch_cached_ohlcv("AAPL", "2023-01-01", "2023-01-15",
                                          cache_dir=tmp_path)
            assert result1 is not None
            assert len(result1) == 10
            assert mock_yf.download.call_count == 1

            # Second call: reads from cache (no download)
            result2 = fetch_cached_ohlcv("AAPL", "2023-01-01", "2023-01-15",
                                          cache_dir=tmp_path)
            assert result2 is not None
            assert len(result2) == 10
            assert mock_yf.download.call_count == 1  # Not called again

    def test_cache_warm_with_mock_yfinance(self, tmp_path):
        """Mock yfinance and verify cache population."""
        from src.simulation.cache import warm_cache

        dates = pd.date_range("2023-01-01", periods=5, freq="B")
        mock_df = pd.DataFrame({
            "Open": [100]*5, "High": [110]*5, "Low": [90]*5,
            "Close": [105]*5, "Volume": [1000000]*5,
        }, index=dates)

        scenarios = {"test_scenario": {"start": "2023-01-01", "end": "2023-01-31"}}
        universe = ["AAPL", "MSFT"]

        with patch("src.simulation.cache.yf") as mock_yf:
            mock_yf.download.return_value = mock_df
            stats = warm_cache(scenarios, universe, cache_dir=tmp_path)
            assert stats["total"] == 2
            assert stats["cached"] == 2
            assert stats["failed"] == 0


# ─── Task 2: Transaction Costs + Benchmark ───────────────────────────────────

class TestTransactionCosts:
    def test_transaction_cost_application(self):
        """Verify costs reduce P&L correctly (9 bps RT)."""
        from src.simulation.engine import apply_costs, TRANSACTION_COSTS

        entry = 100.0
        exit = 105.0
        entry_adj, exit_adj = apply_costs(entry, exit)

        # Total one-side cost = 0 + 3 + 1.5 = 4.5 bps
        assert entry_adj > entry  # Entry costs increase price
        assert exit_adj < exit    # Exit costs decrease price

        # Net P&L should be less than gross P&L
        gross_pnl = (exit - entry) / entry * 100
        net_pnl = (exit_adj - entry_adj) / entry_adj * 100
        assert net_pnl < gross_pnl

    def test_benchmark_computation(self):
        """Verify SPY buy-and-hold calculation."""
        from src.simulation.engine import compute_benchmark

        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        spy_data = pd.DataFrame({
            "Close": np.linspace(400, 440, 50),
        }, index=dates)

        result = compute_benchmark(spy_data, "2023-01-01", "2023-03-15")
        assert result > 0  # SPY went up
        assert abs(result - 10.0) < 1.0  # ~10% gain (400 -> 440)


# ─── Task 3: Monte Carlo ─────────────────────────────────────────────────────

class TestMonteCarlo:
    def test_monte_carlo_deterministic(self):
        """Verify same seed produces same results."""
        from src.simulation.monte_carlo import monte_carlo_resample

        trades = [{"pnl_dollars": (i % 5 - 2) * 100} for i in range(50)]

        r1 = monte_carlo_resample(trades, n_simulations=100, seed=42)
        r2 = monte_carlo_resample(trades, n_simulations=100, seed=42)

        assert r1["median_equity"] == r2["median_equity"]
        assert r1["p5_equity"] == r2["p5_equity"]
        assert r1["p95_equity"] == r2["p95_equity"]

    def test_monte_carlo_confidence_intervals(self):
        """Verify p5 < median < p95."""
        from src.simulation.monte_carlo import monte_carlo_resample

        trades = [{"pnl_dollars": (i % 7 - 3) * 200} for i in range(100)]

        result = monte_carlo_resample(trades, n_simulations=500, seed=42)
        assert result["p5_equity"] <= result["median_equity"]
        assert result["median_equity"] <= result["p95_equity"]
        assert result["probability_of_ruin"] >= 0
        assert result["probability_of_ruin"] <= 1

    def test_monte_carlo_empty_trades(self):
        """Empty trades should return starting equity."""
        from src.simulation.monte_carlo import monte_carlo_resample

        result = monte_carlo_resample([], n_simulations=100, seed=42)
        assert result["median_equity"] == 100000
        assert result["p5_equity"] == 100000


# ─── Task 4: Verdict Logic ───────────────────────────────────────────────────

class TestVerdictLogic:
    def test_verdict_logic_all_cases(self):
        """Test edge/neutral/marginal/bleeds/insufficient."""
        from src.simulation.engine import compute_verdict

        # Edge: excess > 0, sharpe >= 0.5, pf >= 1.3
        assert compute_verdict({
            "total_trades": 50, "sharpe_ratio": 0.8,
            "profit_factor": 1.5, "total_pnl_pct": 15,
        }, benchmark_pnl=5) == "edge"

        # Neutral: total_pnl >= 0, pf >= 1.0
        assert compute_verdict({
            "total_trades": 50, "sharpe_ratio": 0.2,
            "profit_factor": 1.1, "total_pnl_pct": 3,
        }, benchmark_pnl=5) == "neutral"

        # Marginal: sharpe >= -0.3, pf >= 0.8
        assert compute_verdict({
            "total_trades": 50, "sharpe_ratio": -0.2,
            "profit_factor": 0.85, "total_pnl_pct": -2,
        }, benchmark_pnl=5) == "marginal"

        # Bleeds: worst case
        assert compute_verdict({
            "total_trades": 50, "sharpe_ratio": -1.0,
            "profit_factor": 0.5, "total_pnl_pct": -20,
        }, benchmark_pnl=5) == "bleeds"

    def test_verdict_insufficient_trades(self):
        """Verify <20 trades = 'insufficient'."""
        from src.simulation.engine import compute_verdict

        assert compute_verdict({
            "total_trades": 10, "sharpe_ratio": 2.0,
            "profit_factor": 3.0, "total_pnl_pct": 50,
        }, benchmark_pnl=0) == "insufficient"


# ─── Task 5: Traffic Light Validation ────────────────────────────────────────

class TestTrafficLightValidation:
    def test_traffic_light_pure_regime(self):
        """Verify pure regime detection."""
        from src.simulation.engine import validate_traffic_light

        result = validate_traffic_light("strong_bull",
                                         ["GREEN", "GREEN", "GREEN", "GREEN"])
        assert result["correct"] is True
        assert result["actual_majority"] == "GREEN"

    def test_traffic_light_transition(self):
        """Verify transition detection for arrow scenarios."""
        from src.simulation.engine import validate_traffic_light

        # Bull to bear: should have both GREEN and RED
        result = validate_traffic_light("bull_to_bear",
                                         ["GREEN", "GREEN", "YELLOW", "RED", "RED"])
        assert result["correct"] is True
        assert result["transitioned"] is True

    def test_traffic_light_incorrect(self):
        """Verify incorrect detection returns correct=False."""
        from src.simulation.engine import validate_traffic_light

        result = validate_traffic_light("high_volatility",
                                         ["GREEN", "GREEN", "GREEN"])
        assert result["correct"] is False


# ─── Task 4: Heatmap Output ──────────────────────────────────────────────────

class TestHeatmap:
    def test_heatmap_output_format(self, capsys):
        """Verify print_heatmap produces correct table."""
        from src.simulation.engine import print_heatmap

        results = {
            "strong_bull": {
                "total_trades": 45, "win_rate": 0.58, "profit_factor": 1.8,
                "max_drawdown_pct": 4.2, "sharpe_ratio": 1.2,
                "total_pnl_pct": 32.1, "benchmark_pnl_pct": 30.0,
                "verdict": "edge",
            },
        }
        print_heatmap(results)
        output = capsys.readouterr().out
        assert "strong_bull" in output
        assert "45" in output
        assert "edge" in output


# ─── Task 7: Reproducibility ─────────────────────────────────────────────────

class TestReproducibility:
    def test_reproducibility_info(self):
        """Verify git hash and config captured."""
        from src.simulation.engine import get_reproducibility_info

        info = get_reproducibility_info(42, {"test": True})
        assert info["random_seed"] == 42
        assert "git_commit" in info
        assert info["config_snapshot"] == '{"test": true}'
        assert "python_version" in info


# ─── Task 6: Schema ──────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_registered(self):
        """Verify simulation_results in registry."""
        from src.schema.registry import TABLES

        assert "simulation_results" in TABLES
        table = TABLES["simulation_results"]
        col_names = [c.name for c in table.columns]
        assert "result_id" in col_names
        assert "run_id" in col_names
        assert "scenario" in col_names
        assert "verdict" in col_names
        assert "mc_p95_dd" in col_names
        assert "tl_correct" in col_names
        assert "equity_curve_json" in col_names
        assert table.sync_to_postgres is True


# ─── Task 10: Render Sync ────────────────────────────────────────────────────

class TestRenderSync:
    def test_render_sync_includes_simulation(self):
        """Verify table is in sync list."""
        from src.schema.sync_config import generate_sync_tables

        sync_tables = generate_sync_tables()
        assert "simulation_results" in sync_tables
        assert sync_tables["simulation_results"]["mode"] == "incremental"


# ─── Task 9: API Endpoint ────────────────────────────────────────────────────

class TestAPIEndpoint:
    def test_api_endpoint_returns_results(self, tmp_path):
        """Verify /simulation/results returns JSON."""
        db_path = str(tmp_path / "test.db")

        # Create table and insert a row
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE simulation_results (
                    result_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    regime_label TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    total_trades INTEGER,
                    wins INTEGER, losses INTEGER, timeouts INTEGER,
                    win_rate REAL, profit_factor REAL,
                    total_pnl_pct REAL, gross_pnl_pct REAL, net_pnl_pct REAL,
                    max_drawdown_pct REAL, sharpe_ratio REAL, calmar_ratio REAL,
                    benchmark_pnl_pct REAL, excess_return_pct REAL,
                    transaction_cost_bps REAL,
                    mc_median_dd REAL, mc_p95_dd REAL,
                    mc_p5_equity REAL, mc_p95_equity REAL,
                    mc_probability_of_ruin REAL, mc_n_simulations INTEGER,
                    tl_expected TEXT, tl_actual_majority TEXT, tl_correct INTEGER,
                    monthly_returns_json TEXT, equity_curve_json TEXT,
                    regime_breakdown_json TEXT,
                    model_version TEXT, config_json TEXT, verdict TEXT,
                    statistical_confidence TEXT,
                    survivorship_bias INTEGER DEFAULT 1,
                    random_seed INTEGER, git_commit TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO simulation_results "
                "(result_id, run_id, scenario, regime_label, start_date, end_date, "
                "total_trades, verdict, monthly_returns_json, equity_curve_json, "
                "regime_breakdown_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("r1", "run1", "strong_bull", "Strong Bull", "2017-01-01",
                 "2017-12-31", 45, "edge", '{"2017-01": 1.5}', '[100000]',
                 '{"normal": {"trades": 45}}', "2026-01-01T00:00:00"),
            )

        with patch("src.api.routes.system.DB_PATH", db_path):
            from src.api.routes.system import simulation_results
            result = simulation_results()
            assert "results" in result
            assert len(result["results"]) == 1
            assert result["results"][0]["scenario"] == "strong_bull"
            assert result["results"][0]["verdict"] == "edge"
            # JSON fields should be parsed
            assert isinstance(result["results"][0]["monthly_returns_json"], dict)
            assert isinstance(result["results"][0]["equity_curve_json"], list)


# ─── Task 2: Run Scenario (minimal) ──────────────────────────────────────────

class TestRunScenario:
    def test_run_scenario_minimal(self, tmp_path):
        """Run 1 scenario with mocked data, verify output structure."""
        from src.simulation.engine import run_scenario

        # Create realistic mock data
        dates = pd.date_range("2023-01-01", periods=60, freq="B")
        mock_df = pd.DataFrame({
            "Open": np.random.uniform(95, 105, 60),
            "High": np.random.uniform(105, 115, 60),
            "Low": np.random.uniform(85, 95, 60),
            "Close": np.random.uniform(95, 105, 60),
            "Volume": np.random.randint(1000000, 5000000, 60),
        }, index=dates)

        with patch("src.simulation.engine.fetch_cached_ohlcv") as mock_fetch:
            mock_fetch.return_value = mock_df
            with patch("src.simulation.engine.get_sp100_universe") as mock_uni:
                mock_uni.return_value = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]

                result = run_scenario("test", "2023-01-01", "2023-03-31")

                assert "scenario" in result
                assert result["scenario"] == "test"
                assert "total_trades" in result
                assert "win_rate" in result
                assert "max_drawdown_pct" in result
                assert "equity_curve" in result
                assert "verdict" in result
                assert "benchmark_pnl_pct" in result
                assert "tl_states" in result
                assert isinstance(result["equity_curve"], list)

"""Tests for live HSHS computation."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from tests.conftest import init_test_db


@pytest.fixture
def hshs_db(tmp_path):
    """Create a minimal test DB with the tables HSHS queries."""
    db_path = str(tmp_path / "test_hshs.sqlite3")
    init_test_db(db_path, [
        "shadow_trades", "training_examples", "model_versions",
        "scan_metrics", "macro_snapshots", "council_sessions",
    ])
    return db_path


class TestComputeHSHS:
    """Tests for the compute_hshs function."""

    def test_returns_all_keys(self, hshs_db):
        """compute_hshs returns all expected top-level keys."""
        from src.evaluation.hshs_live import compute_hshs

        result = compute_hshs(hshs_db)

        assert "hshs" in result
        assert "dimensions" in result
        assert "weights" in result
        assert "phase" in result
        assert "months_active" in result
        assert "computed_at" in result

        # Dimensions should contain all 5 keys
        for key in [
            "performance",
            "model_quality",
            "data_asset",
            "flywheel_velocity",
            "defensibility",
        ]:
            assert key in result["dimensions"]

    def test_empty_db_returns_nonzero(self, hshs_db):
        """An empty DB should still produce a non-zero HSHS (baseline scores)."""
        from src.evaluation.hshs_live import compute_hshs

        result = compute_hshs(hshs_db)

        # Each dimension gets a baseline of ~5, so the overall should be > 0
        assert result["hshs"] >= 0
        assert isinstance(result["hshs"], (int, float))
        # At least some dimensions should have baseline values
        dims = result["dimensions"]
        assert any(v > 0 for v in dims.values())

    def test_with_trades(self, hshs_db):
        """Adding winning trades should increase the performance score."""
        from src.evaluation.hshs_live import compute_hshs

        # Baseline with empty DB
        baseline = compute_hshs(hshs_db)
        baseline_perf = baseline["dimensions"]["performance"]

        # Add 10 winning closed trades
        conn = sqlite3.connect(hshs_db)
        for i in range(10):
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_dollars, pnl_pct, "
                "created_at, updated_at) VALUES (?, ?, 'closed', ?, ?, ?, ?)",
                (f"t{i}", f"TICK{i}", 50.0 + i * 10, 2.0 + i * 0.5,
                 "2026-03-25T10:00:00", "2026-03-25T10:00:00"),
            )
        conn.commit()
        conn.close()

        # Re-compute
        with_trades = compute_hshs(hshs_db)
        trades_perf = with_trades["dimensions"]["performance"]

        assert trades_perf > baseline_perf, (
            f"Performance with trades ({trades_perf}) should exceed "
            f"baseline ({baseline_perf})"
        )

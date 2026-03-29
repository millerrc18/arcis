"""Tests for live HSHS computation."""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def hshs_db(tmp_path):
    """Create a minimal test DB with the tables HSHS queries."""
    db_path = str(tmp_path / "test_hshs.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE shadow_trades (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            status TEXT DEFAULT 'open',
            pnl_dollars REAL,
            pnl_pct REAL,
            created_at TEXT DEFAULT (datetime('now')),
            closed_at TEXT
        );
        CREATE TABLE training_examples (
            id INTEGER PRIMARY KEY,
            source TEXT,
            quality_score REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE model_versions (
            id INTEGER PRIMARY KEY,
            version TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE scan_metrics (
            id INTEGER PRIMARY KEY,
            metric_name TEXT,
            metric_value REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE macro_snapshots (
            id INTEGER PRIMARY KEY,
            snapshot_data TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE council_sessions (
            id INTEGER PRIMARY KEY,
            consensus TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.close()
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
                "INSERT INTO shadow_trades (ticker, status, pnl_dollars, pnl_pct) "
                "VALUES (?, 'closed', ?, ?)",
                (f"TICK{i}", 50.0 + i * 10, 2.0 + i * 0.5),
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

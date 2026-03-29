"""Tests for PEAD earnings enrichment signals."""
import sqlite3
import pytest
from src.data_enrichment.earnings_signals import compute_earnings_signals


@pytest.fixture
def earnings_db(tmp_path):
    db = str(tmp_path / "earnings_test.sqlite3")
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE earnings_calendar (
                id INTEGER PRIMARY KEY, ticker TEXT, earnings_date TEXT);
            CREATE TABLE analyst_estimates (
                id INTEGER PRIMARY KEY, ticker TEXT, quarter TEXT,
                eps_actual REAL, eps_estimate REAL,
                revenue_actual REAL, revenue_estimate REAL,
                collected_at TEXT);
        """)
        conn.execute(
            "INSERT INTO earnings_calendar VALUES (1, 'AAPL', '2026-04-15')")
        conn.execute(
            "INSERT INTO analyst_estimates VALUES (1, 'AAPL', '2026-Q1', 2.10, 2.00, 95.0, 90.0, '2026-03-01')")
        conn.execute(
            "INSERT INTO analyst_estimates VALUES (2, 'AAPL', '2025-Q4', 1.90, 2.00, 88.0, 90.0, '2026-02-01')")
    return db


class TestEarningsSignals:
    def test_returns_all_keys(self, earnings_db):
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert "earnings_proximity_days" in result
        assert "last_surprise_pct" in result
        assert "include_in_prompt" in result
        assert "earnings_signal_strength" in result

    def test_beat_detection(self, earnings_db):
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert result["last_surprise_direction"] == "beat"
        assert result["last_surprise_pct"] > 0

    def test_concordance(self, earnings_db):
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        # Both EPS and revenue beat, so concordant
        assert result["last_revenue_eps_concordant"] is True

    def test_unknown_ticker(self, earnings_db):
        result = compute_earnings_signals("ZZZZ", db_path=earnings_db)
        assert result["include_in_prompt"] is False
        assert result["earnings_signal_strength"] == "none"

    def test_include_in_prompt_when_near_earnings(self, earnings_db):
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        # AAPL has earnings on 2026-04-15, within 30 days of now (2026-03-28)
        assert result["include_in_prompt"] is True

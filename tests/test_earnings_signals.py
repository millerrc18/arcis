"""Tests for PEAD earnings enrichment signals."""
import sqlite3
import pytest
from src.data_enrichment.earnings_signals import compute_earnings_signals
from tests.conftest import init_test_db


@pytest.fixture
def earnings_db(tmp_path):
    db = str(tmp_path / "earnings_test.sqlite3")
    init_test_db(db, ["earnings_calendar", "analyst_estimates"])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO earnings_calendar (id, ticker, earnings_date, collected_at) "
            "VALUES (1, 'AAPL', '2026-04-15', '2026-01-01T00:00:00')")
        # EPS: actual 2.10 vs estimate 2.00 = beat (5%)
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, surprise_pct, collected_at) "
            "VALUES (1, 'AAPL', '2026-03-01', 'EPS', '2026-Q1', 2.00, 2.10, 5.0, 5.0, '2026-03-01')")
        # Revenue: actual 95.0 vs estimate 90.0 = beat (use date '2026-03-02' to avoid unique index conflict on ticker+date+source)
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, surprise_pct, collected_at) "
            "VALUES (2, 'AAPL', '2026-03-02', 'Revenue', '2026-Q1', 90.0, 95.0, 5.56, 5.56, '2026-03-02')")
        # Older EPS estimate for revision velocity
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, surprise_pct, collected_at) "
            "VALUES (3, 'AAPL', '2026-02-01', 'EPS', '2025-Q4', 2.00, 1.90, -5.0, -5.0, '2026-02-01')")
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

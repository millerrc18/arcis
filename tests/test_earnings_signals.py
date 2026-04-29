"""Tests for PEAD earnings enrichment signals."""
import sqlite3
from datetime import datetime, timedelta
import pytest
from src.data_enrichment.earnings_signals import compute_earnings_signals
from tests.conftest import init_test_db


@pytest.fixture
def earnings_db(tmp_path):
    db = str(tmp_path / "earnings_test.sqlite3")
    init_test_db(db, ["earnings_calendar", "analyst_estimates"])
    # Use a dynamic earnings date 15 days in the future so the "within 30 days"
    # test stays valid as real-world time advances past any hardcoded literal.
    future_earnings_date = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO earnings_calendar (id, ticker, earnings_date, collected_at) "
            "VALUES (1, 'AAPL', ?, '2026-01-01T00:00:00')",
            (future_earnings_date,),
        )
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
        # Earnings fixture is 15 days in the future — always within the
        # 30-day "near earnings" window regardless of when the test runs.
        assert result["include_in_prompt"] is True


@pytest.fixture
def earnings_pit_db(tmp_path):
    """Synthetic DB with rows spanning multiple temporal points for PIT routing tests.

    Layout:
    - earnings_calendar: AAPL has earnings on 2024-04-15 (past) and 2024-08-15 (past) and 2024-12-15 (future from as_of=2024-06-15)
    - analyst_estimates EPS rows collected at 2024-03-01, 2024-05-01, 2024-07-01 — so an
      as_of=2024-06-15 should NOT see the 2024-07-01 row.
    """
    db = str(tmp_path / "earnings_pit_test.sqlite3")
    init_test_db(db, ["earnings_calendar", "analyst_estimates"])
    with sqlite3.connect(db) as conn:
        # Earnings calendar — rows in past, around as_of, and far future
        conn.execute(
            "INSERT INTO earnings_calendar (id, ticker, earnings_date, collected_at) "
            "VALUES (1, 'AAPL', '2024-04-15', '2024-01-01T00:00:00')")
        conn.execute(
            "INSERT INTO earnings_calendar (id, ticker, earnings_date, collected_at) "
            "VALUES (2, 'AAPL', '2024-08-15', '2024-01-01T00:00:00')")
        conn.execute(
            "INSERT INTO earnings_calendar (id, ticker, earnings_date, collected_at) "
            "VALUES (3, 'AAPL', '2024-12-15', '2024-01-01T00:00:00')")
        # Analyst estimates EPS — three rows with different collected_at timestamps
        # Row at 2024-03-01: oldest, estimate 2.00 actual 1.95 (miss)
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, collected_at) "
            "VALUES (1, 'AAPL', '2024-03-01', 'EPS', '2024-Q1', 2.00, 1.95, -2.5, '2024-03-01T00:00:00')")
        # Row at 2024-05-01: middle, estimate 2.10 actual 2.20 (beat) — visible at as_of=2024-06-15
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, collected_at) "
            "VALUES (2, 'AAPL', '2024-05-01', 'EPS', '2024-Q1', 2.10, 2.20, 4.76, '2024-05-01T00:00:00')")
        # Row at 2024-07-01: future relative to as_of=2024-06-15, MUST be filtered out
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, collected_at) "
            "VALUES (3, 'AAPL', '2024-07-01', 'EPS', '2024-Q2', 2.30, 2.40, 4.35, '2024-07-01T00:00:00')")
        # Revenue rows mirroring the EPS pattern for concordance test
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, collected_at) "
            "VALUES (4, 'AAPL', '2024-05-02', 'Revenue', '2024-Q1', 90.0, 95.0, 5.56, '2024-05-02T00:00:00')")
        conn.execute(
            "INSERT INTO analyst_estimates (id, ticker, date, metric, period, estimate, actual, surprise, collected_at) "
            "VALUES (5, 'AAPL', '2024-07-02', 'Revenue', '2024-Q2', 100.0, 110.0, 10.0, '2024-07-02T00:00:00')")
    return db


class TestEarningsSignalsAsOfRouting:
    """Sprint 1.C Phase 2 / #859 — PIT compliance for compute_earnings_signals.

    When `as_of` is set, the function MUST:
      1. Use as_of (not datetime.now) for proximity calc
      2. Bind as_of into earnings_calendar lookup ('earnings_date >= ?')
      3. Filter analyst_estimates by collected_at <= as_of
    """

    def test_proximity_uses_as_of_not_now(self, earnings_pit_db):
        # as_of=2024-06-15 — next earnings should be 2024-08-15 (61 days out)
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-06-15")
        assert result["earnings_proximity_days"] == 61

    def test_proximity_excludes_past_earnings(self, earnings_pit_db):
        # as_of=2024-06-15 — must not pick the 2024-04-15 past row
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-06-15")
        # Days to 2024-08-15 from 2024-06-15 == 61. Days to 2024-04-15 would be -61.
        assert result["earnings_proximity_days"] is not None
        assert result["earnings_proximity_days"] >= 0

    def test_proximity_at_late_as_of_picks_only_future(self, earnings_pit_db):
        # as_of=2024-09-01 — should pick 2024-12-15 (future), not 2024-04 or 2024-08 (past)
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-09-01")
        # Days to 2024-12-15 from 2024-09-01 = 105
        assert result["earnings_proximity_days"] == 105

    def test_proximity_no_future_earnings_returns_none(self, earnings_pit_db):
        # as_of after all 3 earnings dates — nothing to find
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2025-01-01")
        assert result["earnings_proximity_days"] is None

    def test_analyst_estimates_filtered_by_as_of(self, earnings_pit_db):
        # as_of=2024-06-15 — should NOT see the 2024-07-01 row's surprise (4.35).
        # Should see 2024-05-01 row's surprise (4.76) as the latest visible.
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-06-15")
        # 2024-05-01 row: estimate 2.10, actual 2.20, surprise 4.76
        assert result["last_surprise_pct"] == 4.8  # round(4.76, 1)
        assert result["last_surprise_direction"] == "beat"

    def test_analyst_estimates_with_late_as_of_sees_more_rows(self, earnings_pit_db):
        # as_of=2024-09-01 — should now see the 2024-07-01 row (surprise 4.35)
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-09-01")
        assert result["last_surprise_pct"] == round(4.35, 1)  # Python banker's rounding -> 4.3

    def test_default_behavior_unchanged_when_as_of_none(self, earnings_pit_db):
        # When as_of is None, behavior matches the legacy default ('now' semantics).
        # With current real-world date in the future of all fixture rows, no past
        # earnings_calendar rows are ahead of "now" — so proximity should be None.
        # But the analyst_estimates queries don't use 'date(now)' — they use
        # ORDER BY collected_at DESC LIMIT 1 — so the latest row (2024-07-01) wins.
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of=None)
        assert result["last_surprise_pct"] == round(4.35, 1)  # 2024-07-01 row (latest by date DESC)

    def test_revision_velocity_uses_as_of_window(self, earnings_pit_db):
        # as_of=2024-06-15 should compute velocity over rows with collected_at <= 2024-06-15.
        # Visible EPS rows: 2024-03-01 (estimate 2.00) and 2024-05-01 (estimate 2.10).
        # velocity = ((2.10 - 2.00) / 2.00) * 100 = 5.0
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-06-15")
        assert result["analyst_revision_velocity_30d"] == 5.0

    def test_concordance_uses_as_of(self, earnings_pit_db):
        # as_of=2024-06-15: latest EPS row visible is 2024-05-01 (beat),
        # latest Revenue row visible is 2024-05-02 (beat) — concordant.
        result = compute_earnings_signals("AAPL", db_path=earnings_pit_db, as_of="2024-06-15")
        assert result["last_revenue_eps_concordant"] is True

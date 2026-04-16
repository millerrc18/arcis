"""Regression tests for SD#33 / Sprint H1 earnings hard-block behavior.

Verifies that compute_event_risk_score forces a hard block (sizing
multiplier = 0.0) when earnings are scheduled within ~7 trading days
(<=10 calendar days), independent of the market-wide score.

Before SD#33, earnings within 2 days only added +4 to a score that
needs >=8 to block. On calm market days, earnings-imminent tickers
slipped past the filter.
"""

import datetime as dt
import os
import sqlite3
import tempfile

import pytest

from src.features.event_risk_score import compute_event_risk_score


@pytest.fixture
def temp_db():
    """Empty earnings_calendar table — tests insert per-ticker rows as needed."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE earnings_calendar (ticker TEXT, earnings_date TEXT)"
    )
    conn.commit()
    conn.close()
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass  # Windows holds the handle briefly; harmless leftover in tmp


def _insert_earnings(db_path: str, ticker: str, earnings_date: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO earnings_calendar VALUES (?, ?)", (ticker, earnings_date)
    )
    conn.commit()
    conn.close()


def test_earnings_tomorrow_forces_hard_block(temp_db):
    """Earnings within 2 days -> total_score >= block_threshold -> multiplier 0."""
    today = dt.date(2026, 4, 16)
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    _insert_earnings(temp_db, "AAPL", tomorrow)

    result = compute_event_risk_score(
        ticker="AAPL",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["total_score"] >= 8, (
        f"Expected block-threshold score, got {result['total_score']}"
    )
    assert result["sizing_multiplier"] == 0.0, (
        f"Expected multiplier 0.0 (hard block), got {result['sizing_multiplier']}"
    )
    assert result["components"]["earnings_forces_block"] is True


def test_earnings_in_five_trading_days_forces_block(temp_db):
    """Earnings 7 calendar days out (~5 trading days) -> hard block."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=7)).isoformat()
    _insert_earnings(temp_db, "MSFT", earnings)

    result = compute_event_risk_score(
        ticker="MSFT",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 0.0
    assert result["components"]["earnings_forces_block"] is True


def test_earnings_fifteen_days_out_no_block(temp_db):
    """Earnings 15 days out -> no hard block (normal scoring applies)."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=15)).isoformat()
    _insert_earnings(temp_db, "GOOGL", earnings)

    result = compute_event_risk_score(
        ticker="GOOGL",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 1.0
    assert result["components"]["earnings_forces_block"] is False


def test_no_earnings_data_no_block(temp_db):
    """Ticker with no earnings_calendar row -> no earnings-driven block."""
    today = dt.date(2026, 4, 16)
    # temp_db is empty for "UNKNOWN"

    result = compute_event_risk_score(
        ticker="UNKNOWN",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 1.0
    assert result["components"]["earnings_proximity"] == 0


def test_high_market_risk_and_distant_earnings_still_blocks(temp_db):
    """Market score already >= block_threshold -> block independent of earnings."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=30)).isoformat()
    _insert_earnings(temp_db, "JPM", earnings)

    result = compute_event_risk_score(
        ticker="JPM",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 9, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 0.0  # blocked by market, not earnings


# ── Boundary tests around the 10-day cutoff ──────────────────────────────


@pytest.mark.parametrize("days_until,should_block", [
    (0, True),    # earnings today
    (10, True),   # last day inside the cutoff
    (11, False),  # first day outside the cutoff
])
def test_earnings_block_boundary(temp_db, days_until, should_block):
    """Boundary: <=10 calendar days blocks; 11+ does not."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=days_until)).isoformat()
    _insert_earnings(temp_db, "TGT", earnings)

    result = compute_event_risk_score(
        ticker="TGT",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["components"]["earnings_forces_block"] is should_block
    assert (result["sizing_multiplier"] == 0.0) is should_block


def test_earnings_forces_block_key_present_when_no_earnings(temp_db):
    """SD#33: components['earnings_forces_block'] is always set, even without earnings.

    Downstream consumers (dashboard, logging) can rely on the key existing.
    """
    today = dt.date(2026, 4, 16)
    result = compute_event_risk_score(
        ticker="UNKNOWN",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )
    assert "earnings_forces_block" in result["components"]
    assert result["components"]["earnings_forces_block"] is False

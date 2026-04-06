"""Tests for Tier-4 fundamentals refresh scheduler task."""

from unittest.mock import patch

from src.scheduler.fundamentals_refresh import run_fundamentals_refresh


def test_run_fundamentals_refresh_uses_current_collectors():
    with (
        patch(
            "src.data_collection.macro_collector.collect_macro_snapshots",
            return_value={"series_collected": 31},
        ) as mock_macro,
        patch(
            "scripts.fetch_earnings_calendar.fetch_earnings_dates",
            return_value={"tickers_with_dates": 101},
        ) as mock_earnings,
    ):
        summary = run_fundamentals_refresh(config={}, db_path=":memory:")

    assert summary["errors"] == 0
    assert any(item.startswith("FRED (31 series)") for item in summary["refreshed"])
    assert "earnings" in summary["refreshed"]
    mock_macro.assert_called_once()
    mock_earnings.assert_called_once()

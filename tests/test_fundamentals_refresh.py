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


def test_run_fundamentals_refresh_reads_collectorresult_primary_count():
    """Dual-mode (kin #23 / DD-15 r3): once macro_collector migrates to
    CollectorResult, the FRED series count must come from .primary_count
    instead of the legacy dict key.

    VERIFY-BY-MUTATION (feedback_vacuous_test_pattern): without the
    CollectorResult branch, ``result.get('series_collected', 0)`` raises
    AttributeError on a frozen dataclass, summary['errors'] becomes 1, and the
    "FRED (31 series)" assertion fails. Proven non-vacuous against the pre-edit
    dict-only consumer.
    """
    from src.data_collection.result import CollectorResult

    with (
        patch(
            "src.data_collection.macro_collector.collect_macro_snapshots",
            return_value=CollectorResult.ok_from_count("macro", 31, notable_changes=4),
        ) as mock_macro,
        patch(
            "scripts.fetch_earnings_calendar.fetch_earnings_dates",
            return_value={"tickers_with_dates": 101},
        ),
    ):
        summary = run_fundamentals_refresh(config={}, db_path=":memory:")

    assert summary["errors"] == 0
    assert any(item.startswith("FRED (31 series)") for item in summary["refreshed"])
    mock_macro.assert_called_once()

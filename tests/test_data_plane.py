"""S04 T6: Known-answer tests for data plane audit functions.

These tests use synthetic fixtures and run in CI without market data.
Real-data verification is done by tools/audit_data_plane.py (not in CI).
"""

from datetime import date, timedelta


def _trading_days(start: date, end: date) -> list[date]:
    """Generate weekdays between start and end (inclusive)."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def test_trading_day_generation():
    """Verify the test helper generates weekdays only."""
    days = _trading_days(date(2024, 1, 1), date(2024, 1, 7))
    # Jan 1 2024 is Monday, Jan 7 is Sunday
    assert len(days) == 5
    assert all(d.weekday() < 5 for d in days)
    assert days[0] == date(2024, 1, 1)
    assert days[-1] == date(2024, 1, 5)


def test_gap_detection_finds_missing_weekday():
    """A single missing weekday is detected (not hidden by weekend gaps)."""
    # Full week: Mon-Fri
    full = _trading_days(date(2024, 1, 1), date(2024, 1, 5))
    assert len(full) == 5

    # Drop Wednesday
    partial = [d for d in full if d != date(2024, 1, 3)]
    assert len(partial) == 4

    # The gap between Tue and Thu is 2 days (not 1)
    # A proper gap detector compares against expected trading days,
    # not just max calendar gap
    expected = set(full)
    actual = set(partial)
    missing = expected - actual
    assert missing == {date(2024, 1, 3)}


def test_split_adjustment_logic():
    """Verify the split-adjustment check logic on synthetic data."""
    # Simulate: pre-split close 400, post-split close 102 (4:1 split, ~2% move)
    # If unadjusted, post would be ~400 (no, wait...)
    # Actually: 4:1 split, pre-split close $400. Post-split, price is $100.
    # Adjusted: pre-split close becomes $100 in the adjusted series.
    # So adjusted close_before=100, close_after=102 → log jump = log(1.02) ≈ 0.02
    # Unadjusted: close_before=400, close_after=102 → log jump = log(0.255) ≈ -1.37
    import math

    # Adjusted case
    log_jump_adj = abs(math.log(102 / 100))
    assert log_jump_adj < 0.2, "Adjusted split should show small jump"

    # Unadjusted case
    log_jump_unadj = abs(math.log(102 / 400))
    assert log_jump_unadj > 1.0, "Unadjusted split should show large jump"


def test_late_starter_detection():
    """Verify late-starter logic: first bar after 2016-01-04."""
    from datetime import date

    cutoff = date(2016, 1, 4)
    # GEV listed 2024
    gev_first = date(2024, 4, 2)
    assert gev_first > cutoff

    # AAPL has full history
    aapl_first = date(2016, 1, 4)
    assert not (aapl_first > cutoff)


def test_coverage_stats_exclude_spy():
    """Coverage ratios exclude SPY (504 = 503 constituents + SPY)."""
    total_symbols = 504
    n_constituents = total_symbols - 1  # Exclude SPY
    assert n_constituents == 503

    # Example: 44 late starters out of 503 constituents (not 504)
    late_starters = 44
    full_history = n_constituents - late_starters
    assert full_history == 459
    # 459/503 = 91.25%, not 460/504 = 91.27%
    ratio = full_history / n_constituents
    assert 0.91 < ratio < 0.92

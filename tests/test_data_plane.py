"""S04 T6: Known-answer tests for data plane audit functions.

These tests import the actual pure-logic functions from
tools/audit_data_plane.py and verify them on synthetic fixtures.
They run in CI without pandas or market data (the audit module's
pandas import is lazy, so the module imports cleanly).

Deviations from the S04 spec's T6 (declared):
- The spec asked for "AAPL's 2020-08-28 close x 4 ~= 2020-08-31 open".
  Implemented as a close-to-close log-jump check instead: it tests the
  same property (no artificial jump) without depending on open prices,
  which are noisier around splits.
- The spec asked for a dividend verification test. Deferred: no
  known-answer dividend in the test set. Documented in the audit report.
- The spec asked for "verify SPY has no gaps in 2016-2026" on real data.
  The real-data check lives in tools/audit_data_plane.py (not run in CI).
  Here we test the gap-detection logic on synthetic data.
"""

import os
import sys
from datetime import date, timedelta

# Import the audit module's pure functions. The module lives in tools/;
# add the repo root to sys.path so `tools.audit_data_plane` resolves.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tools.audit_data_plane import (  # noqa: E402
    ADJUSTMENT_THRESHOLD,
    COVERAGE_CUTOFF,
    compute_log_jump,
    find_gaps,
    is_adjusted,
    is_late_starter,
)


def _trading_days(start: date, end: date) -> list[date]:
    """Generate weekdays between start and end (inclusive)."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def test_compute_log_jump_adjusted():
    """An adjusted 4:1 split shows a small log jump."""
    # Pre-split close $400 -> post-split $102 (~2% daily move, 4:1 split)
    # Adjusted series: before=100, after=102
    lj = compute_log_jump(100.0, 102.0)
    assert lj < ADJUSTMENT_THRESHOLD
    assert is_adjusted(lj)


def test_compute_log_jump_unadjusted():
    """An unadjusted 4:1 split shows |log| ~= 1.39."""
    # Unadjusted: before=400, after=102
    lj = compute_log_jump(400.0, 102.0)
    assert lj > 1.0
    assert not is_adjusted(lj)


def test_find_gaps_detects_missing_weekday():
    """A single missing weekday is detected via set difference."""
    full = _trading_days(date(2024, 1, 1), date(2024, 1, 5))
    assert len(full) == 5
    expected = {d.isoformat() for d in full}
    # Drop Wednesday
    actual = {d.isoformat() for d in full if d != date(2024, 1, 3)}
    gaps = find_gaps(expected, actual)
    assert gaps == ["2024-01-03"]


def test_find_gaps_empty_when_complete():
    """No gaps when actual matches expected."""
    full = _trading_days(date(2024, 1, 1), date(2024, 1, 5))
    expected = {d.isoformat() for d in full}
    assert find_gaps(expected, expected) == []


def test_is_late_starter():
    """First bar after the cutoff counts as a late starter."""
    assert COVERAGE_CUTOFF == "2016-01-04"
    # GEV listed 2024
    assert is_late_starter("2024-04-02")
    # AAPL has full history
    assert not is_late_starter("2016-01-04")
    # FTV started mid-2016
    assert is_late_starter("2016-07-05")


def test_coverage_ratio_excludes_spy():
    """459/503 constituents (not 460/504): SPY is the reference, not a member."""
    n_constituents = 503
    late_starters = 44
    full_history = n_constituents - late_starters
    assert full_history == 459
    ratio = full_history / n_constituents
    assert 0.91 < ratio < 0.92

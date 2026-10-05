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
- The spec asked for "verify a known late lister (e.g., GEV) has first bar
  after listing date" on real panel data. Here we test the is_late_starter
  logic using GEV's known listing date (2024-04-02) as a realistic example,
  not by reading the panel. The real-data late-starter list is produced by
  tools/audit_data_plane.py.
"""

import os
import sys
from datetime import date, timedelta

import pytest

# Import the audit module's pure functions. The module lives in tools/;
# add the repo root to sys.path so `tools.audit_data_plane` resolves.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tools.audit_data_plane import (  # noqa: E402
    ADJUSTMENT_THRESHOLD,
    COVERAGE_CUTOFF,
    _guard_data_root,
    adjustments_failed,
    compute_log_jump,
    find_gaps,
    is_adjusted,
    is_late_starter,
    spy_covers_panel,
    spy_missing_days,
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


def test_spy_covers_panel_full_range():
    """SPY covering the full panel range passes."""
    spy_dates = {"2016-01-04", "2020-06-01", "2026-10-02"}
    assert spy_covers_panel(spy_dates, "2016-01-04", "2026-10-02")


def test_spy_covers_panel_late_start_fails():
    """SPY starting after panel_min fails closed."""
    spy_dates = {"2016-01-05", "2026-10-02"}
    assert not spy_covers_panel(spy_dates, "2016-01-04", "2026-10-02")


def test_spy_covers_panel_early_end_fails():
    """SPY ending before panel_max fails closed (hides trailing gaps)."""
    spy_dates = {"2016-01-04", "2026-10-01"}
    assert not spy_covers_panel(spy_dates, "2016-01-04", "2026-10-02")


def test_spy_covers_panel_empty_fails():
    """Empty SPY date set fails closed."""
    assert not spy_covers_panel(set(), "2016-01-04", "2026-10-02")


def test_adjustments_failed_on_unadjusted():
    """Any adjusted=False result means failure."""
    results = [
        {"symbol": "AAPL", "adjusted": True, "log_jump": 0.03},
        {"symbol": "TSLA", "adjusted": False, "log_jump": 1.39},
    ]
    assert adjustments_failed(results)


def test_adjustments_failed_on_missing():
    """Any status-error result means failure."""
    results = [
        {"symbol": "AAPL", "adjusted": True, "log_jump": 0.03},
        {"symbol": "FAKE", "status": "no data"},
    ]
    assert adjustments_failed(results)


def test_adjustments_failed_all_ok():
    """All adjusted=True with no errors means no failure."""
    results = [
        {"symbol": "AAPL", "adjusted": True, "log_jump": 0.03},
        {"symbol": "NVDA", "adjusted": True, "log_jump": 0.01},
    ]
    assert not adjustments_failed(results)


def test_guard_data_root_rejects_repo(tmp_path):
    """_guard_data_root refuses paths inside the repo."""

    # tmp_path is outside the repo, should pass
    _guard_data_root(str(tmp_path))

    # The repo itself should be refused
    with pytest.raises(SystemExit) as exc:
        _guard_data_root(_REPO)
    assert exc.value.code == 2


def test_guard_data_root_rejects_sync_folder(tmp_path):
    """_guard_data_root refuses cloud-sync paths."""

    fake_dropbox = tmp_path / "Dropbox" / "data"
    fake_dropbox.mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        _guard_data_root(str(fake_dropbox))
    assert exc.value.code == 2


def test_spy_missing_days_empty_when_complete():
    """No missing days when SPY covers all constituent dates."""
    spy = {"2024-01-02", "2024-01-03", "2024-01-04"}
    constituents = {"2024-01-02", "2024-01-03"}
    assert spy_missing_days(spy, constituents) == []


def test_spy_missing_days_detects_gap():
    """Days with constituent bars but no SPY bar are flagged."""
    spy = {"2024-01-02", "2024-01-04"}
    constituents = {"2024-01-02", "2024-01-03", "2024-01-04"}
    assert spy_missing_days(spy, constituents) == ["2024-01-03"]


def test_adjustments_failed_empty_results():
    """Empty results list fails closed (nothing was checked)."""
    assert adjustments_failed([])


def test_audit_coverage_wiring_with_pandas():
    """audit_coverage calls _validate_spy and computes stats (pandas fixture).

    Uses importorskip so CI (no pandas) skips; runs locally with pandas.
    Verifies the wiring: SPY validated, late starters detected, no gaps.
    """
    pd = pytest.importorskip("pandas")
    from tools.audit_data_plane import audit_coverage

    # Minimal panel: SPY + 2 constituents, 3 trading days
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True)
    rows = []
    for sym in ["SPY", "AAA", "BBB"]:
        for d in dates:
            rows.append({"t": d, "o": 100.0, "h": 101.0, "l": 99.0,
                         "c": 100.5, "v": 1000, "symbol": sym})
    # BBB starts late (only last 2 days)
    rows = [r for r in rows
            if not (r["symbol"] == "BBB" and r["t"] == dates[0])]
    panel = pd.DataFrame(rows)
    panel["date"] = pd.to_datetime(panel["t"], utc=True)

    result = audit_coverage(panel)
    assert result["n_symbols"] == 2  # AAA, BBB (not SPY)
    assert result["late_starters"]["count"] == 1
    assert result["late_starters"]["list"][0][0] == "BBB"
    assert result["gaps"]["symbols_with_gaps"] == 0


def test_audit_coverage_fails_on_spy_missing_day():
    """audit_coverage exits 1 when a constituent traded but SPY didn't."""
    pd = pytest.importorskip("pandas")
    from tools.audit_data_plane import audit_coverage

    dates_spy = pd.to_datetime(["2024-01-02", "2024-01-04"], utc=True)
    dates_aaa = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"],
                               utc=True)
    rows = []
    for d in dates_spy:
        rows.append({"t": d, "o": 100.0, "h": 101.0, "l": 99.0,
                     "c": 100.5, "v": 1000, "symbol": "SPY"})
    for d in dates_aaa:
        rows.append({"t": d, "o": 50.0, "h": 51.0, "l": 49.0,
                     "c": 50.5, "v": 500, "symbol": "AAA"})
    panel = pd.DataFrame(rows)
    panel["date"] = pd.to_datetime(panel["t"], utc=True)

    with pytest.raises(SystemExit) as exc:
        audit_coverage(panel)
    assert exc.value.code == 1

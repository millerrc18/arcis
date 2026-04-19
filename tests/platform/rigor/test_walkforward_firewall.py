"""Tests for R8 — strategy identity firewall + runtime heuristic."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.platform.rigor.walkforward_firewall import (
    ALLOWED_SOURCE_TYPES,
    R8ViolationError,
    Window,
    assert_no_overlap,
    check_provenance_heuristic,
    ensure_bootcamp_off,
    validate_derived_from,
)


def _valid_derived():
    return {
        "source_type": "forensic_audit_ruleset",
        "source_run_id": "forensic_2026_04_18",
        "source_date_range": {"start": "2025-10-01", "end": "2026-03-15"},
    }


def test_validate_missing_key_raises():
    with pytest.raises(R8ViolationError, match="missing required 'derived_from'"):
        validate_derived_from({"strategy_id": "x"})


def test_validate_null_value_accepted():
    """R8(a): explicit null is the documented way to declare no derivation."""
    validate_derived_from({"derived_from": None})  # should not raise


def test_validate_bad_type_raises():
    with pytest.raises(R8ViolationError, match="dict"):
        validate_derived_from({"derived_from": "some string"})


def test_validate_missing_source_type():
    df = _valid_derived()
    df["source_type"] = "unknown_type"
    with pytest.raises(R8ViolationError, match="source_type"):
        validate_derived_from({"derived_from": df})


def test_validate_all_allowed_source_types_accepted():
    for st in ALLOWED_SOURCE_TYPES:
        df = _valid_derived()
        df["source_type"] = st
        validate_derived_from({"derived_from": df})


def test_validate_missing_source_run_id():
    df = _valid_derived()
    del df["source_run_id"]
    with pytest.raises(R8ViolationError, match="source_run_id"):
        validate_derived_from({"derived_from": df})


def test_validate_bad_date_format():
    df = _valid_derived()
    df["source_date_range"]["start"] = "not-a-date"
    with pytest.raises(R8ViolationError, match="ISO"):
        validate_derived_from({"derived_from": df})


def test_validate_start_after_end():
    df = _valid_derived()
    df["source_date_range"] = {"start": "2025-10-01", "end": "2025-09-01"}
    with pytest.raises(R8ViolationError, match="start"):
        validate_derived_from({"derived_from": df})


def test_validate_trade_ids_must_be_str_list():
    df = _valid_derived()
    df["source_trade_ids"] = [1, 2, 3]
    with pytest.raises(R8ViolationError, match="source_trade_ids"):
        validate_derived_from({"derived_from": df})


def test_assert_no_overlap_null_is_noop():
    # derived_from=None → skipped per R8(b) note.
    assert_no_overlap(None, [Window("2020-01-01", "2020-06-30")])


def test_assert_no_overlap_clean_range_passes():
    df = _valid_derived()
    df["source_date_range"] = {"start": "2018-01-01", "end": "2018-12-31"}
    assert_no_overlap(df, [Window("2019-01-01", "2019-12-31")])


def test_assert_no_overlap_overlap_raises():
    df = _valid_derived()
    df["source_date_range"] = {"start": "2025-10-01", "end": "2026-02-15"}
    with pytest.raises(R8ViolationError, match="overlaps"):
        assert_no_overlap(df, [
            Window("2024-01-01", "2024-06-30"),
            Window("2026-02-01", "2026-03-31"),  # overlaps
        ])


def test_assert_no_overlap_edge_touching_overlap():
    """Boundary touching (shared endpoint) counts as overlap — conservative."""
    df = _valid_derived()
    df["source_date_range"] = {"start": "2024-01-01", "end": "2024-06-30"}
    with pytest.raises(R8ViolationError):
        assert_no_overlap(df, [Window("2024-06-30", "2024-12-31")])


def test_ensure_bootcamp_off_true_raises():
    with pytest.raises(R8ViolationError, match="bootcamp"):
        ensure_bootcamp_off(True)


def test_ensure_bootcamp_off_false_is_noop():
    ensure_bootcamp_off(False)  # no raise


def test_heuristic_returns_empty_when_derived_from_declared():
    spec = {"derived_from": _valid_derived(), "strategy_id": "x"}
    audits = [{"strategy_family": "x", "completed_at": "2026-04-01",
               "audit_id": "a1"}]
    with patch("src.platform.rigor.walkforward_firewall._first_commit_date_for_path",
               return_value=date(2026, 4, 15)):
        out = check_provenance_heuristic("x.yaml", spec, audits)
    assert out == []


def test_heuristic_returns_empty_when_no_first_commit():
    spec = {"derived_from": None, "strategy_id": "lazy_prices_v1"}
    audits = [{"strategy_family": "lazy_prices",
               "completed_at": "2026-04-01", "audit_id": "a1"}]
    with patch("src.platform.rigor.walkforward_firewall._first_commit_date_for_path",
               return_value=None):
        out = check_provenance_heuristic("lazy_prices.yaml", spec, audits)
    assert out == []


def test_heuristic_fires_on_matching_family_within_30d():
    spec = {"derived_from": None, "strategy_id": "lazy_prices_v1"}
    audits = [{"strategy_family": "lazy_prices",
               "completed_at": "2026-04-01", "audit_id": "a1"}]
    with patch("src.platform.rigor.walkforward_firewall._first_commit_date_for_path",
               return_value=date(2026, 4, 15)):
        out = check_provenance_heuristic("lazy_prices.yaml", spec, audits)
    assert len(out) == 1
    assert "lazy_prices" in out[0]


def test_heuristic_silent_when_outside_30d_window():
    spec = {"derived_from": None, "strategy_id": "lazy_prices_v1"}
    audits = [{"strategy_family": "lazy_prices",
               "completed_at": "2025-04-01", "audit_id": "a1"}]
    with patch("src.platform.rigor.walkforward_firewall._first_commit_date_for_path",
               return_value=date(2026, 4, 15)):
        out = check_provenance_heuristic("lazy_prices.yaml", spec, audits)
    assert out == []


def test_heuristic_silent_when_different_family():
    spec = {"derived_from": None, "strategy_id": "lazy_prices_v1"}
    audits = [{"strategy_family": "earnings_drift",
               "completed_at": "2026-04-01", "audit_id": "a1"}]
    with patch("src.platform.rigor.walkforward_firewall._first_commit_date_for_path",
               return_value=date(2026, 4, 15)):
        out = check_provenance_heuristic("lazy_prices.yaml", spec, audits)
    assert out == []


def test_heuristic_multiple_audits_produces_multiple_warnings():
    spec = {"derived_from": None, "strategy_id": "lazy_prices_v1"}
    audits = [
        {"strategy_family": "lazy_prices", "completed_at": "2026-04-01",
         "audit_id": "a1"},
        {"strategy_family": "lazy_prices", "completed_at": "2026-03-25",
         "audit_id": "a2"},
    ]
    with patch("src.platform.rigor.walkforward_firewall._first_commit_date_for_path",
               return_value=date(2026, 4, 15)):
        out = check_provenance_heuristic("lazy_prices.yaml", spec, audits)
    assert len(out) == 2

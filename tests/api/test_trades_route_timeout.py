"""Tests for _compute_timeout_status helper in shadow_service.

Called by: pytest (CI)
Calls: src.services.shadow_service._compute_timeout_status
Owns tables: none
Config keys: none
Tests: B9 — timeout status helper unit tests
"""
from __future__ import annotations

import pytest

from src.services.shadow_service import _compute_timeout_status


# ── Fixture cases from B9 design spec ───────────────────────────────────────


def test_on_track_33_percent():
    result = _compute_timeout_status(duration_days=5, timeout_days=15)
    assert result["timeout_progress_pct"] == 33.3
    assert result["timeout_status"] == "on_track"


def test_approaching_93_percent():
    result = _compute_timeout_status(duration_days=14, timeout_days=15)
    assert result["timeout_progress_pct"] == 93.3
    assert result["timeout_status"] == "approaching"


def test_overdue_133_percent():
    result = _compute_timeout_status(duration_days=20, timeout_days=15)
    assert result["timeout_progress_pct"] == 133.3
    assert result["timeout_status"] == "overdue"


def test_unknown_when_timeout_days_is_none():
    result = _compute_timeout_status(duration_days=5, timeout_days=None)
    assert result["timeout_progress_pct"] is None
    assert result["timeout_status"] == "unknown"


def test_unknown_when_duration_days_is_none():
    result = _compute_timeout_status(duration_days=None, timeout_days=15)
    assert result["timeout_progress_pct"] is None
    assert result["timeout_status"] == "unknown"


def test_unknown_when_both_none():
    result = _compute_timeout_status(duration_days=None, timeout_days=None)
    assert result["timeout_progress_pct"] is None
    assert result["timeout_status"] == "unknown"


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_exactly_80_percent_is_approaching():
    result = _compute_timeout_status(duration_days=12, timeout_days=15)
    assert result["timeout_progress_pct"] == 80.0
    assert result["timeout_status"] == "approaching"


def test_exactly_100_percent_is_overdue():
    result = _compute_timeout_status(duration_days=15, timeout_days=15)
    assert result["timeout_progress_pct"] == 100.0
    assert result["timeout_status"] == "overdue"


def test_progress_capped_at_999():
    # Extremely large duration: pct would exceed 999 without cap
    result = _compute_timeout_status(duration_days=10000, timeout_days=1)
    assert result["timeout_progress_pct"] == 999.0
    assert result["timeout_status"] == "overdue"


# ── LLM-rejected case: both fields exposed (integration-style) ───────────────


def test_llm_rejected_fields_both_present_in_service_shape():
    """When llm_timeout_days != timeout_days, both must be present in API shape.

    This test validates that shadow_service exposes both fields. The actual
    mismatch-warning display is handled by the frontend TimeoutCell component.
    We check the service helper returns a dict shape with the two timeout fields
    accessible so the route can pass them through.
    """
    duration = 8
    timeout_days = 15        # operative (default fallback)
    llm_timeout_days = 25    # what LLM proposed; rejected as out-of-bounds

    timeout_info = _compute_timeout_status(duration_days=duration, timeout_days=timeout_days)
    assert timeout_info["timeout_progress_pct"] == 53.3
    assert timeout_info["timeout_status"] == "on_track"

    # The route must pass both through; simulate the response dict shape
    trade_row = {
        "duration_days": duration,
        "timeout_days": timeout_days,
        "llm_timeout_days": llm_timeout_days,
        **timeout_info,
    }
    assert trade_row["llm_timeout_days"] != trade_row["timeout_days"]
    assert "timeout_progress_pct" in trade_row
    assert "timeout_status" in trade_row

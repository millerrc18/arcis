"""Tests for plan-conditional nightly cap in analyst_collector.

T25 (Wave C7b.5) — verifies that _get_nightly_cap returns the correct value
based on the Finnhub plan tier.

fundamental-1: 100/night (well within the 30 calls/sec rate limit)
free: 20/night (preserved current behavior)

Rate-limit source: https://finnhub.io/docs/api/company-dps-estimates
"On top of all plan's limit, there is a 30 API calls/second limit."
Retrieved: 2026-05-13

Implementation note: _get_nightly_cap uses get_finnhub_plan() directly
(not finnhub_plan_supports) because the cap is a tier-numeric property,
not a binary feature gate. Per operator decision 2026-05-13.
"""

from __future__ import annotations

from unittest.mock import patch


def test_nightly_cap_fundamental_1_returns_100():
    """When plan resolves to 'fundamental-1', _get_nightly_cap returns 100."""
    with patch(
        "src.data_collection.analyst_collector.get_finnhub_plan",
        return_value="fundamental-1",
    ):
        from src.data_collection.analyst_collector import _get_nightly_cap
        assert _get_nightly_cap({}) == 100


def test_nightly_cap_free_tier_returns_20():
    """When plan resolves to 'free', _get_nightly_cap returns 20 (preserved)."""
    with patch(
        "src.data_collection.analyst_collector.get_finnhub_plan",
        return_value="free",
    ):
        from src.data_collection.analyst_collector import _get_nightly_cap
        assert _get_nightly_cap({}) == 20

"""R8 firewall regression tests for v0.26.2-scoped.

Confirms forensic_audit_ruleset source_type is accepted and that the
validator's key-absence semantics for source_trade_ids match the Pass 2
verification.
"""

import pytest

from src.platform.rigor.walkforward_firewall import (
    R8ViolationError,
    validate_derived_from,
)


def test_firewall_accepts_forensic_audit_source_type():
    spec = {
        "derived_from": {
            "source_type": "forensic_audit_ruleset",
            "source_run_id": "april-2026-forensic-audit",
            "source_date_range": {"start": "2026-04-01", "end": "2026-04-18"},
        }
    }
    validate_derived_from(spec)


def test_firewall_rejects_source_trade_ids_null():
    spec = {
        "derived_from": {
            "source_type": "forensic_audit_ruleset",
            "source_run_id": "april-2026-forensic-audit",
            "source_date_range": {"start": "2026-04-01", "end": "2026-04-18"},
            "source_trade_ids": None,
        }
    }
    with pytest.raises(R8ViolationError, match="source_trade_ids"):
        validate_derived_from(spec)


def test_firewall_accepts_omitted_source_trade_ids():
    """Key absence is allowed (in-check); null is not."""
    spec = {
        "derived_from": {
            "source_type": "forensic_audit_ruleset",
            "source_run_id": "april-2026-forensic-audit",
            "source_date_range": {"start": "2026-04-01", "end": "2026-04-18"},
        }
    }
    # Should not raise
    validate_derived_from(spec)


def test_firewall_accepts_empty_source_trade_ids_list():
    spec = {
        "derived_from": {
            "source_type": "forensic_audit_ruleset",
            "source_run_id": "april-2026-forensic-audit",
            "source_date_range": {"start": "2026-04-01", "end": "2026-04-18"},
            "source_trade_ids": [],
        }
    }
    validate_derived_from(spec)


def test_firewall_accepts_null_derived_from():
    """Organic/literature-derived strategies (lazy_prices style)."""
    validate_derived_from({"derived_from": None})


def test_firewall_requires_iso_dates_in_source_date_range():
    spec = {
        "derived_from": {
            "source_type": "forensic_audit_ruleset",
            "source_run_id": "april-2026-forensic-audit",
            "source_date_range": {"start": "April 1 2026", "end": "2026-04-18"},
        }
    }
    with pytest.raises(R8ViolationError, match="ISO"):
        validate_derived_from(spec)

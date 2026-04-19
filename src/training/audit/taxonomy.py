"""Fixed taxonomy of quarantine-reason codes for the training data audit.

R3 of the v0.26.0 sprint: every quarantined row has a reason from
this fixed vocabulary. No free-form strings accepted. Downstream
consumers can rely on the set being stable.

Called by: src.training.audit.pass_a_citation,
           src.training.audit.pass_b_format,
           src.training.audit.pass_c_leakage,
           src.training.audit.core,
           src.training.audit.report
Calls: typing (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/training/test_audit_integration.py
"""
from __future__ import annotations

from typing import Literal

QuarantineReason = Literal[
    "v1_attribution_contradicts_narrative",
    "format_drift_missing_section",
    "format_drift_deprecated_marker",
    "format_drift_malformed",
    "leakage_ngram_suspect",
]

# Informational — not a quarantine reason, tracked in report only.
# Used when a v1-affected trade link exists but the narrative is outcome-neutral.
INFO_OUTCOME_NEUTRAL_PRESERVED = "v1_attribution_linked_outcome_neutral_preserved"

VALID_REASONS: frozenset[str] = frozenset({
    "v1_attribution_contradicts_narrative",
    "format_drift_missing_section",
    "format_drift_deprecated_marker",
    "format_drift_malformed",
    "leakage_ngram_suspect",
})


def is_valid_reason(code: str | None) -> bool:
    """Accept any taxonomy code or NULL (= not quarantined)."""
    return code is None or code in VALID_REASONS

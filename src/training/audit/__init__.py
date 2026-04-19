"""Training data v1-citation audit package.

Entry point: `run_training_audit(db_path, dry_run, passes)`. The
function is decorated with @register_action so it appears in the
capability registry at import time (consumed by
src.platform.capability_registry.bootstrap).

Called by: src.commands.diagnostic_handlers (via dashboard kickoff);
           scripts/audits/training_data_v1_audit.py (CLI wrapper)
Calls: src.training.audit.core (for the actual audit logic);
       src.platform.capability_registry (for @register_action)
Owns tables: training_examples (sets quarantined + quarantine_reason)
Config keys: none
Tests: tests/training/test_audit_integration.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action

_INTRODUCED = "v0.26.0"
_LAST_REVIEWED = date(2026, 4, 19)


@register_action(
    name="training_data_audit",
    description=(
        "Three-pass audit of training examples: v1-attribution citation "
        "contamination, format drift, TF-IDF leakage detection. "
        "Quarantines contaminated examples without deleting."
    ),
    category="audit",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_LAST_REVIEWED,
    kickoff_endpoint="/api/diagnostic-runs/training-audit",
    history_endpoint="/api/diagnostic-runs?type=training_audit",
    input_schema={
        "type": "object",
        "properties": {
            "db_path": {"type": "string"},
            "dry_run": {"type": "boolean", "default": False},
            "passes": {
                "type": "array",
                "items": {"type": "string", "enum": ["A", "B", "C"]},
                "default": ["A", "B", "C"],
            },
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "total_audited": {"type": "integer"},
            "quarantined_by_reason": {"type": "object"},
            "leakage_accuracy": {"type": "number"},
            "clean_corpus_size": {"type": "integer"},
        },
    },
    estimated_duration="3-5 minutes",
)
def run_training_audit(
    db_path: str | None = None,
    dry_run: bool = False,
    passes: list[str] | None = None,
) -> dict:
    """Kickoff the three-pass training-data audit.

    Thin wrapper that defers to src.training.audit.core for the real
    work. Keeps the @register_action anchor light so the registration
    stays close to the documented API surface.
    """
    from src.training.audit.core import run_audit
    return run_audit(db_path=db_path, dry_run=dry_run, passes=passes)


__all__ = ["run_training_audit"]

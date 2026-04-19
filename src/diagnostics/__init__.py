"""Diagnostics — statistical analysis tools for strategy evaluation.

Called by: scripts/diagnostics/regime_diagnostic_v1.py,
           src.commands.executor (via src.diagnostics.dashboard_runner)
Calls: none (leaf package)
Owns tables: none (read-only)
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py

Capability registrations (Sprint 1B):
- regime_diagnostic   — stratified analysis of trade cohort
- forensic_trade_audit — per-trade forensic decomposition
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action

_INTRODUCED = "v0.25.0"
_LAST_REVIEWED = date(2026, 4, 18)


@register_action(
    name="regime_diagnostic",
    description=(
        "Stratified analysis of the trade cohort across five dimensions "
        "(VIX regime, days-since-entry, sector, entry hour, holding-period "
        "bucket). Produces a CONTAMINATED / UNCONTAMINATED / INCONCLUSIVE "
        "decision plus bootstrapped confidence intervals and inline plots."
    ),
    category="diagnostics",
    version="1.0",
    maintainer="operator",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_LAST_REVIEWED,
    kickoff_endpoint="/api/diagnostic-runs/regime",
    history_endpoint="/api/diagnostic-runs?type=regime",
    input_schema={
        "type": "object",
        "properties": {
            "exclude_quarantined": {"type": "boolean", "default": False},
            "bootstrap_n": {
                "type": "integer",
                "minimum": 100,
                "maximum": 50000,
                "description": "Number of bootstrap resamples (default 10000).",
            },
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "status": {"type": "string"},
            "decision": {"type": "string"},
            "n_total": {"type": "integer"},
            "mean_excess": {"type": "number"},
        },
        "required": ["run_id", "status"],
    },
    estimated_duration="3-5 minutes",
)
def regime_diagnostic_capability() -> dict:
    """Registration anchor — the actual kickoff is the executor command
    `run-regime-diagnostic`. This function exists so the decorator has
    something to attach to; callers should hit the kickoff_endpoint.
    """
    return {
        "registered_at": _LAST_REVIEWED.isoformat(),
        "entry_module": "src.diagnostics",
    }


@register_action(
    name="forensic_trade_audit",
    description=(
        "Per-trade forensic decomposition: risk-return attribution, "
        "quality-of-execution diagnostics, survivorship and selection "
        "bias probes. Output is a single markdown report plus plots."
    ),
    category="diagnostics",
    version="1.0",
    maintainer="operator",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_LAST_REVIEWED,
    kickoff_endpoint="/api/diagnostic-runs/forensic",
    history_endpoint="/api/diagnostic-runs?type=forensic",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "status": {"type": "string"},
            "findings_count": {"type": "integer"},
        },
        "required": ["run_id", "status"],
    },
    estimated_duration="2-4 minutes",
)
def forensic_trade_audit_capability() -> dict:
    """Registration anchor for the forensic audit capability."""
    return {
        "registered_at": _LAST_REVIEWED.isoformat(),
        "entry_module": "src.diagnostics",
    }

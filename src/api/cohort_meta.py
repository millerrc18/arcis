"""Cohort taxonomy labels and _meta envelope helper for API responses.

Defines the 8 canonical cohort identifiers used across all /api/* endpoints
and provides the meta_entry() factory for building per-field _meta objects.

shadow_metrics cohort-resolution rule (§2.3):
    /api/shadow/metrics emits cohort='trades.live_only' IFF the query was
    filtered by source='live' (via the desk parameter). Otherwise it emits
    cohort='trades.all_closed'. The endpoint must emit a single cohort per
    request based on the actual SQL filter applied.

Called by: src.api.cloud_routes.kpis, src.api.cloud_routes.core,
    src.api.cloud_routes.analytics, src.api.cloud_routes.trades,
    src.api.cloud_routes.training
Calls: nothing
Owns tables: none
Config keys: none
Tests: tests/api/test_status.py
"""
from __future__ import annotations

COHORT_LABELS: dict[str, str] = {
    "kpi.canonical": "Instrumented + quarantine-filtered",
    "trades.all_closed": "All closed shadow trades",
    "trades.strategy": "Strategy-attributed (Pullback only)",
    "trades.model": "Model-attributed (excl. unknown)",
    "trades.live_only": "Live trades only (broker positions)",
    "stress.scenario": "Backtest scenario",
    "attribution.pairs": "Paired (both arms resolved)",
    "none": "Not cohort-specific",
}


def meta_entry(cohort_id: str, n: int, label: str | None = None) -> dict:
    """Return a _meta entry dict for a single field.

    Args:
        cohort_id: One of the 8 canonical cohort identifiers in COHORT_LABELS.
        n: Count of records in this cohort for this response.
        label: Human-readable label override. If None, uses COHORT_LABELS[cohort_id].

    Returns:
        Dict with keys: cohort, label, n.

    Raises:
        KeyError: If cohort_id is not in COHORT_LABELS.
    """
    resolved_label = COHORT_LABELS[cohort_id] if label is None else label
    return {"cohort": cohort_id, "label": resolved_label, "n": n}

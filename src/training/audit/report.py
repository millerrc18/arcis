"""Report generator + summary JSON shape (real 5-section renderer in commit 7).

For commit 4 this module exposes two functions: `summarize` (returns a
compact dict for summary_json) and `render_report` (returns a short
placeholder markdown body). Commit 7 replaces render_report with the
full 5-section renderer.

Called by: src.training.audit.core
Owns tables: none
Config keys: none
Tests: tests/training/test_audit_integration.py
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import at runtime
    from src.training.audit.core import AuditResult


def summarize(
    result: "AuditResult", *, dry_run: bool, written: int,
) -> dict:
    """Compact summary — target for diagnostic_runs.summary_json.

    Flat keys so the frontend can render without recursion. Counts by
    reason code live under `quarantined_by_reason`; an info-only row
    count lives under `preserved_outcome_neutral` and is not part of
    the quarantined total.
    """
    reason_counts = dict(Counter(result.quarantines.values()))
    info_counts = dict(Counter(result.info_rows.values()))
    return {
        "total_audited": result.total_audited,
        "quarantined_by_reason": reason_counts,
        "quarantined_total": sum(reason_counts.values()),
        "preserved_outcome_neutral": info_counts,
        "pass_a_diverged_join_cohort": result.pass_a_diverged_join,
        "pass_b_checked": result.pass_b_checked,
        "pass_c_leakage_accuracy": result.pass_c_leakage_accuracy,
        "pass_c_majority_baseline": result.pass_c_majority_baseline,
        "pass_c_n_examples": result.pass_c_n_examples,
        "clean_corpus_size": max(
            result.total_audited - sum(reason_counts.values()), 0
        ),
        "dry_run": dry_run,
        "rows_written": written,
    }


def render_report(result: "AuditResult", *, dry_run: bool) -> str:
    """Placeholder 5-section markdown — replaced with full renderer in commit 7."""
    reason_counts = dict(Counter(result.quarantines.values()))
    info_counts = dict(Counter(result.info_rows.values()))
    lines: list[str] = [
        "# Training Data v1-Citation Audit",
        "",
        "## Executive Summary",
        "",
        f"- **Total audited**: {result.total_audited}",
        f"- **Quarantined**: {sum(reason_counts.values())}",
        f"- **Preserved outcome-neutral**: {sum(info_counts.values())}",
        f"- **Dry-run**: {dry_run}",
        "",
        "## Pass A — v1-Attribution Citation Contamination",
        "",
        f"- Diverged-trade join cohort: {result.pass_a_diverged_join}",
        f"- Quarantined: "
        f"{reason_counts.get('v1_attribution_contradicts_narrative', 0)}",
        "",
        "## Pass B — Format Drift",
        "",
        f"- Checked: {result.pass_b_checked}",
        "",
        "## Pass C — TF-IDF Leakage",
        "",
        f"- Balanced accuracy: {result.pass_c_leakage_accuracy}",
        f"- Majority baseline: {result.pass_c_majority_baseline}",
        "",
        "## Remaining Clean Corpus",
        "",
        f"- Clean examples: "
        f"{max(result.total_audited - sum(reason_counts.values()), 0)}",
        "",
    ]
    return "\n".join(lines) + "\n"

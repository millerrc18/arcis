"""5-section markdown report + summary JSON for the training audit.

Two public functions:
  - summarize(result, dry_run, written) -> dict  (for summary_json)
  - render_report(result, dry_run) -> str        (5-section markdown)

The report always contains the R4-mandated sections:
  ## Executive Summary
  ## Pass A — v1-Attribution Citation Contamination
  ## Pass B — Format Drift
  ## Pass C — TF-IDF Leakage
  ## Remaining Clean Corpus

Missing any section is a sprint failure. A regression test lives in
tests/training/test_audit_integration.py.

Called by: src.training.audit.core
Calls: collections.Counter, datetime (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/training/test_audit_integration.py
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import at runtime
    from src.training.audit.core import AuditResult


REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Executive Summary",
    "## Pass A",
    "## Pass B",
    "## Pass C",
    "## Remaining Clean Corpus",
)


def summarize(
    result: "AuditResult", *, dry_run: bool, written: int,
) -> dict:
    """Compact summary — target for diagnostic_runs.summary_json.

    Flat keys so the frontend can render without recursion.
    """
    reason_counts = dict(Counter(result.quarantines.values()))
    info_counts = dict(Counter(result.info_rows.values()))
    return {
        "total_audited": result.total_audited,
        "quarantined_by_reason": reason_counts,
        "quarantined_total": sum(reason_counts.values()),
        "preserved_outcome_neutral": info_counts,
        "pass_a_diverged_join_cohort": result.pass_a_diverged_join,
        "pass_a_candidates": result.pass_a_candidates,
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


def _fmt_count(counts: dict[str, int], key: str) -> int:
    return int(counts.get(key, 0))


def _render_exec_summary(
    result: "AuditResult",
    reason_counts: dict[str, int],
    info_counts: dict[str, int],
    *,
    dry_run: bool,
) -> list[str]:
    quarantined = sum(reason_counts.values())
    clean = max(result.total_audited - quarantined, 0)
    lines = [
        "## Executive Summary",
        "",
        f"- **Total audited**: {result.total_audited}",
        f"- **Quarantined**: {quarantined}",
        f"- **Preserved outcome-neutral (v1-linked, pattern-only)**: "
        f"{sum(info_counts.values())}",
        f"- **Clean corpus remaining**: {clean}",
        f"- **Dry-run**: {dry_run}",
    ]
    if result.pass_c_leakage_accuracy is not None:
        lines.append(
            f"- **Pass C balanced accuracy**: "
            f"{result.pass_c_leakage_accuracy:.3f} "
            f"(majority baseline {result.pass_c_majority_baseline:.3f}, "
            f"threshold 0.65)"
        )
    lines.append("")
    if quarantined == 0:
        lines += ["No rows were flagged for quarantine in this run.", ""]
    else:
        lines.append("**Quarantined by reason:**")
        lines.append("")
        for code in sorted(reason_counts):
            lines.append(f"- `{code}`: {reason_counts[code]}")
        lines.append("")
    return lines


def _render_pass_a(
    result: "AuditResult",
    reason_counts: dict[str, int],
    info_counts: dict[str, int],
) -> list[str]:
    q = _fmt_count(reason_counts, "v1_attribution_contradicts_narrative")
    info = _fmt_count(info_counts, "v1_attribution_linked_outcome_neutral_preserved")
    lines = [
        "## Pass A — v1-Attribution Citation Contamination",
        "",
        "Rows are examined only if their `recommendation_id` joins an",
        "`attribution_trades` row where `ranker_only_outcome_v1 !=",
        "`ranker_only_outcome` (the v1 bug corrected by v2).",
        "",
        f"- **Candidates with recommendation_id linkage**: "
        f"{result.pass_a_candidates}",
        f"- **Diverged v1→v2 join cohort**: {result.pass_a_diverged_join}",
        f"- **Quarantined (narrative contradicts v2)**: {q} → "
        "`v1_attribution_contradicts_narrative`",
        f"- **Preserved (outcome-neutral narrative)**: {info} → "
        "`v1_attribution_linked_outcome_neutral_preserved` (info only)",
        "",
    ]
    if result.pass_a_diverged_join == 0:
        lines += [
            "No diverged-trade join cohort in the current data. Pass A",
            "reports zero findings; this is expected if the v1→v2",
            "resolution has not yet linked any training examples.",
            "",
        ]
    return lines


def _render_pass_b(
    result: "AuditResult", reason_counts: dict[str, int],
) -> list[str]:
    missing = _fmt_count(reason_counts, "format_drift_missing_section")
    deprecated = _fmt_count(reason_counts, "format_drift_deprecated_marker")
    malformed = _fmt_count(reason_counts, "format_drift_malformed")
    lines = [
        "## Pass B — Format Drift",
        "",
        "Schema checks on each row:",
        "- Output XML required tags: `<why_now>`, `<analysis>` (95% corpus prevalence)",
        "- Output deprecated tags: `<risk_management>`, `<execution_plan>`, `<monitoring>`",
        "- Input required labels: `Ticker:`, `Current Price:`, `Trend State:`",
        "",
        f"- **Rows checked**: {result.pass_b_checked}",
        f"- **Missing section / label**: {missing} → `format_drift_missing_section`",
        f"- **Deprecated marker present**: {deprecated} → `format_drift_deprecated_marker`",
        f"- **Malformed (open/close imbalance)**: {malformed} → `format_drift_malformed`",
        "",
    ]
    return lines


def _render_pass_c(result: "AuditResult") -> list[str]:
    lines = ["## Pass C — TF-IDF Leakage", ""]
    if result.pass_c_leakage_accuracy is None:
        lines += [
            "Pass C not run or insufficient labeled data (<50 rows in "
            "`blinded_win`/`blinded_loss`/`outcome_win`/`outcome_loss`).",
            "",
        ]
        return lines
    acc = result.pass_c_leakage_accuracy
    baseline = result.pass_c_majority_baseline or 0.0
    leaking = acc > 0.65
    lines += [
        f"- **Balanced accuracy (5-fold CV)**: {acc:.3f}",
        f"- **Majority baseline**: {baseline:.3f}",
        f"- **Leakage threshold**: 0.65",
        f"- **Is leaking?**: {'YES' if leaking else 'NO'}",
        f"- **Labeled examples**: {result.pass_c_n_examples or 0}",
        "",
    ]
    if leaking:
        lines += [
            "**Top suspect example IDs (report-only; not quarantined):**",
            "",
        ]
        for ex_id in result.pass_c_suspect_ids[:10]:
            lines.append(f"- `{ex_id}`")
        if len(result.pass_c_suspect_ids) > 10:
            lines.append(
                f"- …and {len(result.pass_c_suspect_ids) - 10} more"
            )
        lines += [
            "",
            "_Pass C is report-only in v1. Leakage remediation is a "
            "separate sprint._",
            "",
        ]
    else:
        lines.append(
            "No leakage signal above threshold; narrative text is not "
            "predicting outcome beyond class-imbalance baseline."
        )
        lines.append("")
    return lines


def _render_clean(
    result: "AuditResult", reason_counts: dict[str, int],
) -> list[str]:
    quarantined = sum(reason_counts.values())
    clean = max(result.total_audited - quarantined, 0)
    lines = [
        "## Remaining Clean Corpus",
        "",
        f"- **Clean examples after audit**: {clean}",
        f"- **Quarantined count**: {quarantined}",
        f"- **Clean / total ratio**: "
        f"{(clean / result.total_audited) if result.total_audited else 0:.3f}",
        "",
        "The remaining clean corpus is the input for the next training run.",
        "Quarantined rows are retained in the database and can be "
        "un-quarantined via SQL if the operator finds a false positive "
        "(reversibility — R5).",
        "",
    ]
    return lines


def render_report(result: "AuditResult", *, dry_run: bool) -> str:
    """Build the 5-section markdown report.

    Caller is responsible for writing the string to disk. The report is
    UTF-8 plaintext; inline plots are not generated (Pass C may refer
    to suspect example_ids but we do not embed images in v1).
    """
    reason_counts = dict(Counter(result.quarantines.values()))
    info_counts = dict(Counter(result.info_rows.values()))
    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        "# Training Data v1-Citation Audit",
        "",
        f"**Run at**: {now}",
        f"**Dry-run**: {dry_run}",
        "",
    ]
    lines += _render_exec_summary(
        result, reason_counts, info_counts, dry_run=dry_run,
    )
    lines += _render_pass_a(result, reason_counts, info_counts)
    lines += _render_pass_b(result, reason_counts)
    lines += _render_pass_c(result)
    lines += _render_clean(result, reason_counts)
    return "\n".join(lines) + "\n"

"""Three-pass training-data audit orchestrator (DB-aware layer).

Opens DB, fetches rows, dispatches to the pure logic in pass_a, pass_b,
pass_c, and writes quarantine flags back to training_examples (unless
dry_run=True). Composes the report via src.training.audit.report.

Called by: src.training.audit.run_training_audit (via __init__.py)
Calls: src.training.audit.pass_a_citation,
       src.training.audit.pass_b_format (lazy),
       src.training.audit.pass_c_leakage (lazy),
       src.training.audit.report (lazy)
Owns tables: training_examples (writes quarantined + quarantine_reason)
Config keys: none
Tests: tests/training/test_audit_integration.py
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

DEFAULT_PASSES: Sequence[str] = ("A", "B", "C")


@dataclass
class AuditResult:
    """Aggregate result from a full audit run.

    Every quarantine is keyed by example_id → reason code. `info_rows`
    tracks outcome-neutral v1-linked examples we deliberately preserved
    (Pass A's INFO_OUTCOME_NEUTRAL_PRESERVED).
    """
    total_audited: int = 0
    quarantines: dict[str, str] = field(default_factory=dict)
    info_rows: dict[str, str] = field(default_factory=dict)
    pass_a_candidates: int = 0
    pass_a_diverged_join: int = 0
    pass_b_checked: int = 0
    pass_c_leakage_accuracy: float | None = None
    pass_c_majority_baseline: float | None = None
    pass_c_n_examples: int | None = None
    pass_c_suspect_ids: list[str] = field(default_factory=list)


def _fetch_training_examples(db_path: str) -> list[dict]:
    """Pull every training example keyed by example_id.

    One query, no filtering — Pass A/B/C decide what to do with each
    row. Returns a list of plain dicts so the logic layer doesn't
    depend on sqlite3.Row semantics.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT example_id, recommendation_id, source, ticker, "
            "input_text, output_text, outcome, trade_outcome, outcome_type, "
            "COALESCE(quarantined, 0) AS quarantined, quarantine_reason "
            "FROM training_examples"
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_attribution_map(db_path: str) -> dict[str, dict]:
    """Return {recommendation_id: {v1_outcome, v2_outcome}} for diverged trades.

    Only diverged trades (v1 != v2) are loaded — the rest are irrelevant
    to Pass A. Uses `resolution_version` as a tiebreaker for any dup on
    recommendation_id by taking the row with the highest lexicographic
    resolution_version (most recent resolution wins).
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT recommendation_id, ranker_only_outcome AS v2_outcome, "
            "ranker_only_outcome_v1 AS v1_outcome, resolution_version "
            "FROM attribution_trades "
            "WHERE ranker_only_outcome_v1 IS NOT NULL "
            "AND ranker_only_outcome_v1 != ranker_only_outcome"
        ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        key = r["recommendation_id"]
        if key is None:
            continue
        existing = out.get(key)
        if existing is None or (r["resolution_version"] or "") > (
            existing.get("resolution_version") or ""
        ):
            out[key] = {
                "v1_outcome": r["v1_outcome"],
                "v2_outcome": r["v2_outcome"],
                "resolution_version": r["resolution_version"],
            }
    return out


def _apply_pass_a(
    examples: list[dict], attr_map: dict[str, dict], result: AuditResult,
) -> None:
    """Run Pass A; mutate `result` in place with its findings."""
    from src.training.audit.pass_a_citation import run_pass_a
    enriched = []
    for ex in examples:
        rec_id = ex.get("recommendation_id")
        attr = attr_map.get(rec_id) if rec_id else None
        enriched.append({
            "example_id": ex["example_id"],
            "output_text": ex.get("output_text") or "",
            "recommendation_id": rec_id,
            "v1_outcome": (attr or {}).get("v1_outcome"),
            "v2_outcome": (attr or {}).get("v2_outcome"),
        })
    decisions = run_pass_a(enriched)
    result.pass_a_candidates = sum(
        1 for d in decisions if d.recommendation_id is not None
    )
    result.pass_a_diverged_join = sum(
        1 for d in decisions
        if d.v1_outcome is not None
        and d.v2_outcome is not None
        and d.v1_outcome != d.v2_outcome
    )
    for d in decisions:
        if d.quarantine and d.reason_code:
            result.quarantines[d.example_id] = d.reason_code
        elif d.reason_code and not d.quarantine:
            result.info_rows[d.example_id] = d.reason_code


def _apply_pass_b(examples: list[dict], result: AuditResult) -> None:
    """Run Pass B (XML + label drift); mutate result in place."""
    from src.training.audit.pass_b_format import run_pass_b
    decisions = run_pass_b(examples)
    result.pass_b_checked = len(decisions)
    for d in decisions:
        if d.quarantine and d.reason_code:
            # Pass A wins if both would quarantine — its reason is more specific.
            result.quarantines.setdefault(d.example_id, d.reason_code)


def _apply_pass_c(
    examples: list[dict], result: AuditResult, db_path: str,
) -> None:
    """Run Pass C leakage probe; report-only in v1 per sprint prompt."""
    from src.training.audit.pass_c_leakage import run_pass_c
    c_out = run_pass_c(examples, db_path=db_path)
    result.pass_c_leakage_accuracy = c_out.get("balanced_accuracy")
    result.pass_c_majority_baseline = c_out.get("majority_baseline")
    result.pass_c_n_examples = c_out.get("n_examples")
    result.pass_c_suspect_ids = list(c_out.get("suspect_example_ids") or [])


def _write_quarantines(
    db_path: str, quarantines: dict[str, str],
) -> int:
    """Set quarantined=1 + reason for each example_id in the map.

    Writes are UPDATE-only (never DELETE). Runs inside a single
    transaction so partial failures don't leave half-flagged rows.
    """
    if not quarantines:
        return 0
    count = 0
    with sqlite3.connect(db_path) as conn:
        for example_id, reason in quarantines.items():
            cur = conn.execute(
                "UPDATE training_examples "
                "SET quarantined = 1, quarantine_reason = ? "
                "WHERE example_id = ?",
                (reason, example_id),
            )
            count += cur.rowcount
        conn.commit()
    return count


def _dispatch_passes(
    examples: list[dict],
    selected: tuple[str, ...],
    db_path: str,
    result: AuditResult,
) -> None:
    """Run each enabled pass against the loaded examples."""
    attr_map = _fetch_attribution_map(db_path) if "A" in selected else {}
    if "A" in selected:
        _apply_pass_a(examples, attr_map, result)
    if "B" in selected:
        _apply_pass_b(examples, result)
    if "C" in selected:
        _apply_pass_c(examples, result, db_path)


def _write_report(report_path: str, result: AuditResult, dry_run: bool) -> None:
    """Render + write the report to disk."""
    from src.training.audit.report import render_report
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(
        render_report(result, dry_run=dry_run),
        encoding="utf-8",
    )


def run_audit(
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    passes: Iterable[str] | None = None,
    report_path: str | None = None,
    plot_dir: str | None = None,
) -> dict:
    """Run the full three-pass audit and return its summary dict.

    Args match the CLI: db_path, dry_run, passes (subset of A/B/C),
    report_path, plot_dir (unused; kept for dashboard_runner symmetry).
    Returns a dict suitable for diagnostic_runs.summary_json.
    """
    from src.config import DB_PATH
    from src.training.audit.report import summarize

    if db_path is None:
        db_path = DB_PATH
    selected = tuple(p.upper() for p in (passes or DEFAULT_PASSES))

    examples = _fetch_training_examples(db_path)
    result = AuditResult(total_audited=len(examples))
    _dispatch_passes(examples, selected, db_path, result)

    written = 0 if dry_run else _write_quarantines(db_path, result.quarantines)
    summary = summarize(result, dry_run=dry_run, written=written)

    if report_path:
        _write_report(report_path, result, dry_run)
    _ = plot_dir  # dashboard_runner supplies this for symmetry with regime/forensic
    logger.info(
        "[TRAINING-AUDIT] total=%d quarantined=%d dry_run=%s written=%d",
        result.total_audited, len(result.quarantines), dry_run, written,
    )
    return summary

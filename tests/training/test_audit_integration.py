"""Integration tests for the training-data audit package.

Covers the sprint's integration matrix:
  - @register_action makes training_data_audit queryable via
    /api/system/index (via the ACTIONS registry)
  - Report contains all five R4-required sections
  - summary_extractor.parse_training_audit_report extracts headline counts
  - run_audit() with dry_run=True does NOT mutate the DB
  - Two dry-runs over the same DB produce identical summaries (R5)
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.diagnostics.summary_extractor import parse_training_audit_report
from src.training.audit.core import AuditResult, run_audit
from src.training.audit.report import REQUIRED_SECTIONS, render_report


# ── capability registration ─────────────────────────────────────────


def test_register_action_exposes_training_data_audit():
    """ACTIONS registry must contain our entry after bootstrap.

    We don't call clear_registries_for_tests() here because the module
    is already imported during test collection and re-importing via
    importlib won't re-fire the decorator (import cache). The existence
    check is the real invariant.
    """
    import src.training.audit  # noqa: F401 — ensures import has fired
    from src.platform.capability_registry import ACTIONS
    from src.platform.capability_registry.bootstrap import ensure_bootstrapped
    ensure_bootstrapped()
    assert "training_data_audit" in ACTIONS
    entry = ACTIONS["training_data_audit"]
    assert entry.category == "audit"
    assert entry.kickoff_endpoint == "/api/diagnostic-runs/training-audit"
    assert entry.version == "1.0"


# ── report renderer ──────────────────────────────────────────────────


def _mk_result(**kwargs) -> AuditResult:
    base = {
        "total_audited": 1782,
        "quarantines": {"ex-1": "v1_attribution_contradicts_narrative"},
        "info_rows": {},
        "pass_a_candidates": 12,
        "pass_a_diverged_join": 6,
        "pass_b_checked": 1782,
        "pass_c_leakage_accuracy": 0.55,
        "pass_c_majority_baseline": 0.72,
        "pass_c_n_examples": 301,
        "pass_c_suspect_ids": [],
    }
    base.update(kwargs)
    return AuditResult(**base)


def test_report_contains_all_required_sections():
    """R4: all 5 sections present; missing any = sprint failure."""
    md = render_report(_mk_result(), dry_run=False)
    for section in REQUIRED_SECTIONS:
        assert section in md, f"Report missing required section: {section!r}"


def test_report_exec_summary_contains_total_and_quarantined():
    md = render_report(_mk_result(), dry_run=False)
    assert "**Total audited**: 1782" in md
    assert "**Quarantined**: 1" in md
    assert "**Clean corpus remaining**: 1781" in md


def test_report_marks_dry_run_in_header():
    md_dry = render_report(_mk_result(), dry_run=True)
    md_write = render_report(_mk_result(), dry_run=False)
    assert "**Dry-run**: True" in md_dry
    assert "**Dry-run**: False" in md_write


# ── summary_extractor ───────────────────────────────────────────────


def test_parse_training_audit_report_extracts_headline_fields():
    result = _mk_result(
        pass_c_leakage_accuracy=0.723,
        pass_c_majority_baseline=0.721,
    )
    md = render_report(result, dry_run=False)
    parsed = parse_training_audit_report(md)
    assert parsed["total_audited"] == 1782
    assert parsed["quarantined_total"] == 1
    assert parsed["clean_corpus_size"] == 1781
    assert parsed["leakage_accuracy"] == pytest.approx(0.723, abs=1e-3)
    assert "parse_errors" not in parsed


def test_parse_training_audit_report_handles_missing_executive_summary():
    parsed = parse_training_audit_report("# a report\n\nsome content\n")
    assert parsed.get("parse_errors") == ["no_executive_summary"]


def test_parse_training_audit_report_handles_no_pass_c():
    """Insufficient data for Pass C → leakage_accuracy absent (not an error)."""
    result = _mk_result(
        pass_c_leakage_accuracy=None,
        pass_c_majority_baseline=None,
        pass_c_n_examples=0,
    )
    md = render_report(result, dry_run=False)
    parsed = parse_training_audit_report(md)
    assert "leakage_accuracy" not in parsed
    assert "parse_errors" not in parsed


# ── run_audit() against a synthetic in-DB fixture ──────────────────


def _make_test_db(tmp_path: Path) -> Path:
    """Materialize a tiny SQLite with 6 rows: 3 that drift, 3 clean."""
    db_path = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE training_examples ("
        "example_id TEXT PRIMARY KEY, source TEXT, ticker TEXT, "
        "input_text TEXT, output_text TEXT, trade_outcome TEXT, "
        "outcome TEXT, outcome_type TEXT, recommendation_id TEXT, "
        "quarantined INTEGER DEFAULT 0, quarantine_reason TEXT)"
    )
    conn.execute(
        "CREATE TABLE attribution_trades ("
        "attribution_id TEXT, recommendation_id TEXT, "
        "ranker_only_outcome TEXT, ranker_only_outcome_v1 TEXT, "
        "resolution_version TEXT)"
    )
    rows = [
        # clean v1-linked with outcome-neutral narrative (info, no quarantine)
        ("c1", "blinded_win", "AAPL",
         "Ticker: AAPL\nCurrent Price: $150\n=== ACTUAL OUTCOME ===",
         "<why_now>pullback in trend</why_now>\n<analysis>x</analysis>",
         "win", "win", "primary", "rec-1", 0, None),
        # v1-contradicting narrative (quarantine via Pass A)
        ("c2", "blinded_win", "CSCO",
         "Ticker: CSCO\nCurrent Price: $60\n=== ACTUAL OUTCOME ===",
         "<why_now>Trade stopped out and continued decline.</why_now>\n"
         "<analysis>x</analysis>",
         "loss", "loss", "primary", "rec-2", 0, None),
        # missing required XML tag (quarantine via Pass B)
        ("c3", "blinded_win", "MSFT",
         "Ticker: MSFT\nCurrent Price: $400\n=== ACTUAL OUTCOME ===",
         "<why_now>only this tag</why_now>",
         "win", "win", "primary", "rec-3", 0, None),
        # clean non-linked
        ("c4", "synthetic_claude", "AMZN",
         "Ticker: AMZN\nCurrent Price: $180\n=== ACTUAL OUTCOME ===",
         "<why_now>pullback in trend</why_now>\n<analysis>x</analysis>",
         "win", "win", "primary", None, 0, None),
        # malformed
        ("c5", "blinded_loss", "GOOG",
         "Ticker: GOOG\nCurrent Price: $200\n=== ACTUAL OUTCOME ===",
         "<why_now>unclosed",
         "loss", "loss", "primary", None, 0, None),
        # all clean
        ("c6", "blinded_loss", "META",
         "Ticker: META\nCurrent Price: $500\n=== ACTUAL OUTCOME ===",
         "<why_now>x</why_now>\n<analysis>y</analysis>",
         "loss", "loss", "primary", None, 0, None),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO training_examples VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", r,
        )
    # One diverged attribution_trades row for rec-2
    conn.execute(
        "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?)",
        ("att-1", "rec-2", "win", "loss", "v2"),
    )
    # rec-1 linked but not diverged
    conn.execute(
        "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?)",
        ("att-2", "rec-1", "win", "win", "v2"),
    )
    conn.commit()
    conn.close()
    return db_path


def test_dry_run_does_not_mutate_db(tmp_path):
    db_path = _make_test_db(tmp_path)
    summary = run_audit(db_path=str(db_path), dry_run=True, passes=["A", "B"])
    assert summary["dry_run"] is True
    assert summary["rows_written"] == 0
    # Verify no rows were actually flagged
    with sqlite3.connect(str(db_path)) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE quarantined = 1"
        ).fetchone()[0]
    assert n == 0


def test_write_mode_flags_quarantined_rows(tmp_path):
    db_path = _make_test_db(tmp_path)
    summary = run_audit(db_path=str(db_path), dry_run=False, passes=["A", "B"])
    assert summary["rows_written"] > 0
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT example_id, quarantine_reason FROM training_examples "
            "WHERE quarantined = 1"
        ).fetchall()
    reasons = {r[0]: r[1] for r in rows}
    # c2 → Pass A quarantine
    assert reasons.get("c2") == "v1_attribution_contradicts_narrative"
    # c3 → Pass B missing section (has only <why_now>, no <analysis>)
    assert reasons.get("c3") == "format_drift_missing_section"
    # c5 → Pass B malformed
    assert reasons.get("c5") == "format_drift_malformed"


def test_dry_run_is_reproducible_rerun_identical_summary(tmp_path):
    """R5: rerunning the audit produces identical results."""
    db_path = _make_test_db(tmp_path)
    s1 = run_audit(db_path=str(db_path), dry_run=True, passes=["A", "B"])
    s2 = run_audit(db_path=str(db_path), dry_run=True, passes=["A", "B"])
    # Normalize — these keys come from dict-order of dict(Counter(...))
    s1.pop("pass_c_leakage_accuracy", None)
    s2.pop("pass_c_leakage_accuracy", None)
    assert s1 == s2


def test_single_pass_runs_in_isolation(tmp_path):
    """R2: Pass A alone does not run Pass B; Pass B alone does not run Pass A."""
    db_path = _make_test_db(tmp_path)
    only_a = run_audit(db_path=str(db_path), dry_run=True, passes=["A"])
    only_b = run_audit(db_path=str(db_path), dry_run=True, passes=["B"])
    # Pass A alone: quarantines come from Pass A only
    assert only_a["quarantined_by_reason"].keys() <= {
        "v1_attribution_contradicts_narrative",
    }
    # Pass A alone leaves pass_b_checked=0 (B not run)
    assert only_a["pass_b_checked"] == 0
    # Pass B alone: no v1_attribution reasons
    assert "v1_attribution_contradicts_narrative" not in (
        only_b["quarantined_by_reason"]
    )


def test_summary_has_taxonomy_conformant_reason_codes(tmp_path):
    """R3: every reason code in summary must be from the fixed taxonomy."""
    from src.training.audit.taxonomy import VALID_REASONS
    db_path = _make_test_db(tmp_path)
    summary = run_audit(db_path=str(db_path), dry_run=True)
    for code in summary["quarantined_by_reason"]:
        assert code in VALID_REASONS, f"Non-taxonomy reason code: {code}"

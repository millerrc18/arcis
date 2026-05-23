"""Tests for the VerdictReporter (Tasks 12 + 13).

Asserts the zero-tolerance verdict rule (any integrity violation or swallowed
error => UNSTABLE) and the MANDATORY "Blind Spots & Trust Calibration" section
(spec §9): the rendered report must enumerate the known blind spots plainly so a
STABLE verdict can never be mistaken for proof of the full organic lifecycle.

T13 additions: honest STABLE scope (organic open→reconcile-when-gone +
provenance) + 10 residual blind-spots enumeration.
"""

from __future__ import annotations

from src.simulation.lifecycle.oracle import InvariantResult
from src.simulation.lifecycle.verdict import (
    Verdict,
    VerdictReporter,
    classify,
)


def _ok(name: str) -> InvariantResult:
    return InvariantResult(
        name=name, passed=True, detail="ok",
        degraded_correctly=False, error_swallowed=False,
    )


def _all_clean() -> list[InvariantResult]:
    return [
        _ok("attribution_1to1"),
        _ok("zero_orphans"),
        _ok("zero_synthetic_closes"),
        _ok("db_open_equals_broker"),
        _ok("capital_conservation"),
        _ok("honest_metrics"),
        _ok("corpus_integrity"),
        _ok("no_wedged_processes"),
        _ok("deterministic_reproducibility"),
    ]


# ── verdict rule ───────────────────────────────────────────────────────────


def test_integrity_violation_is_unstable():
    results = _all_clean()
    results[1] = InvariantResult(
        name="zero_orphans", passed=False, detail="2 orphans",
        degraded_correctly=False, error_swallowed=False,
    )
    assert classify(results) is Verdict.UNSTABLE


def test_error_swallowed_is_unstable_even_when_passed():
    results = _all_clean()
    results[5] = InvariantResult(
        name="honest_metrics", passed=True, detail="plausible number",
        degraded_correctly=False, error_swallowed=True,
    )
    assert classify(results) is Verdict.UNSTABLE


def test_coverage_gap_only_is_degraded():
    results = _all_clean()
    results.append(
        InvariantResult(
            name="coverage_full_loop", passed=False,
            detail="full WatchLoop handlers deferred",
            degraded_correctly=True, error_swallowed=False,
        )
    )
    assert classify(results) is Verdict.DEGRADED


def test_all_clean_is_stable():
    assert classify(_all_clean()) is Verdict.STABLE


# ── blind-spots section (mandatory) ─────────────────────────────────────────


def test_report_contains_blind_spots_section():
    report = VerdictReporter().render(_all_clean())
    assert "Blind Spots & Trust Calibration" in report


def test_report_states_core_path_vs_full_loop_gap():
    report = VerdictReporter().render(_all_clean())
    assert "core trade path" in report
    assert "WatchLoop" in report
    assert "NOT" in report and "full organic lifecycle" in report


def test_report_states_concurrency_blind_spot():
    report = VerdictReporter().render(_all_clean())
    assert "single-threaded" in report
    assert "thread-safety" in report


def test_report_states_dst_shape_only():
    report = VerdictReporter().render(_all_clean())
    assert "DST" in report
    assert "shape-tested" in report or "shape-only" in report


def test_report_states_live_fill_gap_uncovered():
    report = VerdictReporter().render(_all_clean())
    assert "UNCOVERED" in report
    assert "live" in report.lower()


def test_report_does_not_invent_a_live_monitor():
    report = VerdictReporter().render(_all_clean())
    # The gap must be stated as a tracked follow-up, never as an existing monitor.
    assert "no live broker-vs-db" in report.lower()


# ── tier authority labelling ────────────────────────────────────────────────


def test_smoke_tier_labels_integrity_non_authoritative():
    report = VerdictReporter(tier="smoke").render(_all_clean())
    assert "non-authoritative" in report.lower()
    assert "SQLite" in report


def test_full_pg_tier_is_authoritative():
    report = VerdictReporter(tier="full").render(_all_clean())
    assert "non-authoritative" not in report.lower()


def test_verdict_appears_in_report():
    report = VerdictReporter(tier="full").render(_all_clean())
    assert "STABLE" in report


# ── T13: honest STABLE scope ─────────────────────────────────────────────────


def test_stable_certifies_organic_open_path():
    report = VerdictReporter().render(_all_clean())
    assert "organic" in report.lower()
    assert "open_shadow_trade" in report or "open→reconcile" in report or "open path" in report


def test_stable_certifies_provenance_guard():
    report = VerdictReporter().render(_all_clean())
    assert "provenance" in report.lower()


def test_stable_certifies_reconcile_when_gone():
    report = VerdictReporter().render(_all_clean())
    assert "reconcile-when-gone" in report or "reconcile_when_gone" in report


def test_stable_certifies_zero_orphans():
    report = VerdictReporter().render(_all_clean())
    assert "zero orphan" in report.lower() or "ZERO orphan" in report


def test_stable_certifies_teardown_discipline():
    report = VerdictReporter().render(_all_clean())
    assert "teardown" in report.lower() or "try/finally" in report


def test_stable_certifies_recommendation_id_determinism():
    report = VerdictReporter().render(_all_clean())
    assert "recommendation_id" in report
    assert "determinism" in report.lower() or "deterministic" in report.lower()


def test_stable_does_not_claim_clean_close_certified():
    report = VerdictReporter().render(_all_clean())
    assert "PARTIAL" in report or "xfail" in report.lower() or "clean-close" in report.lower()


def test_stable_does_not_claim_governor_reject_certified():
    report = VerdictReporter().render(_all_clean())
    assert "T11" in report or "governor-reject" in report.lower() or "DEFERRED" in report


def test_stable_does_not_claim_per_fault_matrix_certified():
    report = VerdictReporter().render(_all_clean())
    assert "T12" in report or "per-fault" in report.lower() or "DEFERRED" in report


# ── T13: residual blind-spots enumeration ───────────────────────────────────


def test_blindspot_clean_close_xfail_stated():
    report = VerdictReporter().render(_all_clean())
    assert "xfail" in report.lower() or "xfailed" in report.lower()
    assert "clean-close" in report.lower() or "OCO" in report


def test_blindspot_packet_worthy_threshold_stated():
    report = VerdictReporter().render(_all_clean())
    assert "packet_worthy_threshold" in report
    assert "30" in report


def test_blindspot_ranker_tie_break_stated():
    report = VerdictReporter().render(_all_clean())
    assert "tie-break" in report.lower() or "tie break" in report.lower()
    assert "ranker" in report.lower()


def test_blindspot_t11_governor_reject_deferred():
    report = VerdictReporter().render(_all_clean())
    assert "T11" in report
    assert "governor" in report.lower()


def test_blindspot_t12_per_fault_matrix_deferred():
    report = VerdictReporter().render(_all_clean())
    assert "T12" in report
    assert "fault" in report.lower()


def test_blindspot_t10_inv9_end_to_end_deferred():
    report = VerdictReporter().render(_all_clean())
    assert "T10" in report
    assert "inv9" in report.lower() or "determinism" in report.lower()


def test_blindspot_synthetic_capital_ledger_stated():
    report = VerdictReporter().render(_all_clean())
    assert "ledger" in report.lower() or "CapitalLedger" in report or "accounting" in report.lower()
    assert "synthetic" in report.lower()


def test_blindspot_overnight_subprocess_handlers_stated():
    report = VerdictReporter().render(_all_clean())
    assert "subprocess" in report.lower() or "overnight" in report.lower()
    assert "freezegun" in report.lower() or "in-process" in report.lower() or "fired-not-asserted" in report.lower()


def test_blindspot_actual_shares_null_at_open_stated():
    report = VerdictReporter().render(_all_clean())
    assert "actual_shares" in report
    assert "NULL" in report or "null" in report.lower()


def test_blindspot_count_is_ten():
    from src.simulation.lifecycle.verdict import _BLIND_SPOT_COUNT
    assert _BLIND_SPOT_COUNT == 10

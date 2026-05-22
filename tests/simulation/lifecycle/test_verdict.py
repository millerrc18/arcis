"""Tests for the VerdictReporter (Task 12).

Asserts the zero-tolerance verdict rule (any integrity violation or swallowed
error => UNSTABLE) and the MANDATORY "Blind Spots & Trust Calibration" section
(spec §9): the rendered report must enumerate the known blind spots plainly so a
STABLE verdict can never be mistaken for proof of the full organic lifecycle.
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

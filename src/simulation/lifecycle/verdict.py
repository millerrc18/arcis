"""VerdictReporter — aggregates InvariantResults into an honest verdict (Tasks 12+13).

The operator's bar: a simulator that grants FALSE CONFIDENCE is worse than none.
This module enforces that bar in two ways.

1. Zero-tolerance classification. ``classify()`` reduces the 9 oracle invariants
   (T9) to one of three verdicts:
     - UNSTABLE if ANY data-integrity invariant FAILED, or ANY result has
       ``error_swallowed=True`` (a masked error is a fail even when the surface
       number looks plausible — the anti-masking axis of T81/T9).
     - DEGRADED if the only failures are non-integrity quality/coverage gaps
       (e.g. a deferred full-loop handler recorded as a coverage gap).
     - STABLE otherwise.
   This rule is fixed; do not soften it.

2. The MANDATORY "Blind Spots & Trust Calibration" section (spec §9 / T13).
   A STABLE verdict means "the organic open path + provenance guard +
   reconcile-when-gone are sound," NOT "the full lifecycle (clean-close,
   governor-reject, per-fault matrix) is proven." The report enumerates,
   plainly, what STABLE certifies and what remains DEFERRED so the verdict
   can never be over-read.

Called by: the entrypoint (Task 13 — NOT wired here).
Calls: nothing (pure reduction + string rendering over InvariantResult).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_verdict.py
"""

from __future__ import annotations

from enum import Enum

from src.simulation.lifecycle.oracle import InvariantResult

__all__ = ["Verdict", "VerdictReporter", "classify", "INTEGRITY_INVARIANTS", "_BLIND_SPOT_COUNT"]


# The 9 oracle checks (T9) ARE the data-integrity set — zero-tolerance applies to
# them. Any result whose name is NOT in this set is treated as a non-integrity
# quality/coverage gap (DEGRADED-eligible, never UNSTABLE on its own).
INTEGRITY_INVARIANTS = frozenset(
    {
        "attribution_1to1",
        "zero_orphans",
        "zero_synthetic_closes",
        "db_open_equals_broker",
        "capital_conservation",
        "honest_metrics",
        "corpus_integrity",
        "no_wedged_processes",
        "deterministic_reproducibility",
    }
)


class Verdict(Enum):
    """The three possible stability verdicts for a sim run."""

    STABLE = "STABLE"
    DEGRADED = "DEGRADED"
    UNSTABLE = "UNSTABLE"


def classify(results: list[InvariantResult]) -> Verdict:
    """Reduce a list of InvariantResults to a single Verdict (zero-tolerance)."""
    integrity_failed = any(
        r.name in INTEGRITY_INVARIANTS and not r.passed for r in results
    )
    error_swallowed = any(r.error_swallowed for r in results)
    if integrity_failed or error_swallowed:
        return Verdict.UNSTABLE

    quality_gap = any(
        r.name not in INTEGRITY_INVARIANTS and not r.passed for r in results
    )
    if quality_gap:
        return Verdict.DEGRADED
    return Verdict.STABLE


# The mandatory blind-spots section. Kept as data so the test can assert on the
# exact substrings the operator requires; rendered verbatim into every report.
# T13 rewrite: honest STABLE scope + 10 residual blind-spots (design §8).
_BLIND_SPOT_COUNT = 10

_BLIND_SPOTS = """\
## Blind Spots & Trust Calibration

STABLE NOW CERTIFIES (this sprint):
- The organic open path: scan → features → packet → LLM → governor →
  executor.open_shadow_trade → reconcile_all_paper_trades — emitting exactly
  1 organic recommendation + 1 organic shadow_trade row.
- The provenance guard (assert_real_path_executed): seams invoked, executor-only
  order_type artifact present, runtime DSN identity holds.
- The reconcile-when-gone path: broker-flat positions resolved with ZERO orphans
  (no recommendation_id IS NULL rows).
- Teardown discipline: try/finally restoration of all wiring patches + sim
  bridges + _config_cache + brokers — no leakage even on exception.
- Determinism of recommendation_id via T7 §3.4 uuid stub (counter-based
  deterministic minter replacing stdlib uuid.uuid4 in journal.store).
- Determinism of actual_shares and pnl_dollars (pure math under fixed seeds;
  verified by T7 spike).

A STABLE verdict means the core trade path (organic open→reconcile-when-gone
+ provenance guard) is sound. It does NOT mean the full organic lifecycle
(clean-close, governor-reject, per-fault matrix) is proven. WatchLoop
handlers beyond the scan path (overnight, training, DST) remain outside the
certified scope. Read the residual blind-spots below before trusting it.

RESIDUAL BLIND-SPOTS (10 enumerated; deferred for follow-up):

1. CLEAN-CLOSE EXIT-DETECTION IS XFAILED (T9 follow-up): the fake's OCO-leg
   fill is not detected by check_and_manage_open_trades's .filled_avg_price
   path; reconcile then hits the "close-didn't-clear" pattern
   (reconcile.py:908). Fake↔executor contract drift requires further
   tightening. STABLE's clean-close arm is currently PARTIAL.

2. SIM RUNS AT packet_worthy_threshold=30 VS PROD DEFAULT 70 (T9 Finding A):
   lifecycle is what STABLE certifies; the threshold gate itself is NOT
   exercised at the prod level. Risk governor is NOT being weakened — T11
   (deferred) covers the governor-reject path separately.

3. PROD RANKER TIE-BREAK IS UNSTABLE (T6 finding): ranker.py:629 uses
   ranked.sort(key=lambda x: x['score'], reverse=True) with no secondary key.
   Equal scores → dict-insertion-order tie-break. Fakes side-step via distinct
   95/85/80 scores. Recommended one-line PROD fix: add ticker as secondary sort
   key.

4. GOVERNOR-REJECT SCENARIO DEFERRED (T11 not built this sprint): no organic
   test confirms the governor's BP-reject/position-cap/max-positions reject
   branches write a rejected recommendation with ZERO shadow_trade and ZERO
   NULL-rec orphan. The risk governor is sacred; T11 follow-up must drive its
   real reject path organically.

5. PER-FAULT MATRIX DEFERRED (T12 not built this sprint): no first-principles
   binding verifies each fault family (broker/clock/data/market/network/process)
   breaks the SPECIFIC invariant it should. Without T12, fault-induced
   UNSTABLE/DEGRADED verdicts are NOT first-principles tested.

6. FULL INV9 ORGANIC-DETERMINISM END-TO-END DEFERRED (T10 not built this
   sprint): recommendation_id + actual_shares + pnl_dollars columns are
   individually verified (T7 spike) but no end-to-end test of two organic
   open→exit→close runs producing identical inv9 hashes (the equality test
   depends on clean-close working, which is xfailed).

7. SYNTHETIC-ACCOUNTING-SIDE CapitalLedger FEED (DA disclosure folded): the
   ledger invariants (5/6) verify that the sim's accounting reconciles with the
   organic fills, NOT that prod's independent accounting path is exercised
   end-to-end. The sim routes fills via fill_listener → ledger.apply_fill
   (organic on trade side, synthetic on accounting side).

8. OVERNIGHT SUBPROCESS HANDLERS (VRAM/training) DEFERRED: freezegun is
   in-process; cannot reach subprocess children. These handlers stay
   fired-not-asserted. DBLogHandler log-thread timestamps NOT asserted.

9. actual_shares NULL AT TRADE-OPEN TIME (T6 finding): populated on fill by
   close/fill flow; inv9 sees NULL until trade closes. Trivially stable but
   uninformative until the full lifecycle drives to terminal status.

10. REAL-FILL LATENCY / CONCURRENCY / MARKET REGIMES / REAL BROKER BEHAVIOR
    / DST SHAPE-ONLY / DB WALL-CLOCK EXCLUDED (per original spec §8 disclosures):
    real fills, latency, slippage, and partial-fill timing are absent; fills are
    fixed deterministic prices. A single deterministic scenario — not bull/bear/
    chop/halt market regimes. The sim is single-threaded with frozen time, so
    OCO-race / dup-fill faults test DATA-SHAPE resilience, NOT thread-safety;
    real thread+timer interleavings are not run. DST is shape-tested, not fully
    exercised: VirtualClock.advance() is offset-naive and does not produce a
    genuine DST fold yet. DB WALL-CLOCK is excluded: invariants assert against
    app-supplied frozen timestamps, not the database's now(). LIVE-FILL GAP
    (§9.1) — UNCOVERED: there is NO live broker-vs-DB consistency monitor in
    this project. The live-fill consistency gap is currently UNCOVERED; it is a
    tracked follow-up, not an existing safeguard.
"""


class VerdictReporter:
    """Renders an InvariantResult list into a verdict report with blind spots."""

    def __init__(self, *, tier: str = "full") -> None:
        # tier "smoke" => SQLite wiring run (integrity NON-authoritative); only
        # the "full" PG gate is integrity-authoritative.
        self.tier = tier

    def render(self, results: list[InvariantResult]) -> str:
        """Render the full report: verdict, per-invariant lines, blind spots."""
        verdict = classify(results)
        lines: list[str] = []
        lines.append(f"# Lifecycle Simulator Verdict: {verdict.value}")
        lines.append("")
        lines.append(self._authority_line())
        lines.append("")
        lines.append("## Invariant Results")
        for r in results:
            lines.extend(self._result_lines(r))
        lines.append("")
        lines.append(_BLIND_SPOTS)
        return "\n".join(lines)

    def _authority_line(self) -> str:
        """One line stating whether integrity results are authoritative."""
        if self.tier == "smoke":
            return (
                "Tier: smoke — integrity results are wiring-only / "
                "non-authoritative (SQLite). Only the full PG gate is "
                "integrity-authoritative."
            )
        return "Tier: full PG — integrity results are authoritative."

    def _result_lines(self, r: InvariantResult) -> list[str]:
        """Render one invariant as a status line plus its detail."""
        scope = "integrity" if r.name in INTEGRITY_INVARIANTS else "quality"
        status = "PASS" if r.passed else "FAIL"
        flags = []
        if r.degraded_correctly:
            flags.append("degraded-correctly")
        if r.error_swallowed:
            flags.append("ERROR-SWALLOWED")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        return [f"- {status} ({scope}) {r.name}: {r.detail}{suffix}"]

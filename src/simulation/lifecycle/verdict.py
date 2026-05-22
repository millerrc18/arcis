"""VerdictReporter — aggregates InvariantResults into an honest verdict (Task 12).

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

2. The MANDATORY "Blind Spots & Trust Calibration" section (spec §9). A STABLE
   verdict means "the core trade path + oracle are sound," NOT "the full organic
   lifecycle is proven." The report enumerates, plainly, what the sim does and
   does NOT exercise so the verdict can never be over-read.

Called by: the entrypoint (Task 13 — NOT wired here).
Calls: nothing (pure reduction + string rendering over InvariantResult).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_verdict.py
"""

from __future__ import annotations

from enum import Enum

from src.simulation.lifecycle.oracle import InvariantResult

__all__ = ["Verdict", "VerdictReporter", "classify", "INTEGRITY_INVARIANTS"]


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
_BLIND_SPOTS = """\
## Blind Spots & Trust Calibration

A STABLE verdict means "the core trade path + oracle are sound." It does NOT
mean the full organic lifecycle is proven. Read this section before trusting it.

- CORE-PATH-vs-FULL-LOOP GAP (CRITICAL): the simulator currently asserts
  integrity against a RUNNER-DRIVEN core trade path (FakeTradingClient
  entry/fill/OCO-close + 1:1-attributed rows + CapitalLedger), NOT yet against
  the REAL WatchLoop's full handler chain (scan/packet/governor/execute emitting
  organic DB writes — those handlers fire-and-no-op pending a follow-up that
  wires them to the fakes). A STABLE verdict therefore certifies the core trade
  path + oracle, NOT the full organic lifecycle.
- REAL BROKER behavior is NOT exercised: real fills, latency, slippage, and
  partial-fill timing are absent; fills are fixed deterministic prices.
- REGIME-SPECIFIC behavior is NOT exercised: a single deterministic scenario,
  not bull/bear/chop/halt market regimes.
- REAL GPU/Ollama placement is NOT exercised: the trainer is faked via a pidfile
  stub; no real model load, no VRAM handoff.
- REAL NETWORK nondeterminism is NOT exercised: no flaky upstreams, no retries,
  no timeouts against live services.
- REAL CONCURRENCY is NOT exercised: the sim is single-threaded with frozen
  time, so OCO-race / dup-fill faults test DATA-SHAPE resilience, NOT
  thread-safety; real thread+timer interleavings are not run.
- DST is shape-tested, not fully exercised: the DST fault asserts the
  cadence-fires-once expectation, but VirtualClock.advance() is offset-naive and
  does not produce a genuine DST fold yet.
- DB WALL-CLOCK is excluded: invariants assert against app-supplied frozen
  timestamps, not the database's now().
- LIVE-FILL GAP (§9.1) — UNCOVERED: there is NO live broker-vs-DB consistency
  monitor in this project. The live-fill consistency gap is currently UNCOVERED;
  it is a tracked follow-up, not an existing safeguard.
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

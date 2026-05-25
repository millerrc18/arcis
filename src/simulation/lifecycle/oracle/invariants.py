"""The Oracle — the 9 data-integrity invariants that define "stable" (Task 9).

This is the heart of the lifecycle simulator. It consumes the CapitalLedger
(T8), the SwallowedErrorObserver (T81), the fakes (FakeTradingClient T5,
FakeTrainerPidfile T7) and the frozen VirtualClock (T4), and asserts against the
ephemeral 5434 Postgres the simulator wrote to. ``Oracle.assert_all()`` runs
every invariant and returns one ``InvariantResult`` each.

The 9 invariants:
  1. attribution_1to1            — every non-reconciled trade links a rec
  2. zero_orphans                — no order_type='reconciled' / NULL rec_id rows
  3. zero_synthetic_closes       — no reconciled_stale / synthetic closes
  4. db_open_equals_broker       — open DB trades EXACTLY == FakeBroker positions
  5. capital_conservation        — no phantom P&L (CapitalLedger.detect_phantom_pnl)
  6. honest_metrics              — governor drawdown denominator honest, with the
                                   degraded-correctly vs error-swallowed split
  7. corpus_integrity            — empty-holdout blocks model promotion
  8. no_wedged_processes         — no stale / recycled training pidfile
  9. deterministic_reproducibility — canonical hash of the business DB snapshot

§7.1 per-branch distinguishing-evidence mapping (which signal classifies
degraded-correctly vs error-swallowed for each fail-conservative branch):

  - governor drawdown (governor.py:396): OBSERVABLE. The observer captures the
    ERROR "[RISK] Drawdown computation failed: ... CONSERVATIVE estimate (15%)".
    Its presence => error_swallowed=True (invariant 6). Absence => the metric is
    honest and compared against the ledger's authoritative drawdown.
  - validator reject-on-import-fail (validator.py:44): OBSERVABLE. The observer
    captures the ERROR "[VALIDATOR] Universe lookup failed — rejecting ...
    (fail closed)". (The simulator surfaces it through the same observer; the
    oracle keys on the [VALIDATOR] log to classify it.)
  - reconcile tz-coercion (reconcile.py:128-131): NOT OBSERVABLE. That branch is
    a bare ``except (...): continue`` that logs NOTHING — there is no signal to
    observe. The oracle therefore does NOT claim to observe it; it catches the
    EFFECT instead: the branch fails toward backfill and produces an orphan /
    reconciled row, which invariant 2 (zero_orphans) flags.

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: oracle._checks_db, oracle._checks_signal, oracle.capital,
    oracle.error_observer.
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_oracle.py
"""

from __future__ import annotations

from src.simulation.lifecycle.oracle import _checks_db, _checks_signal
from src.simulation.lifecycle.oracle._result import InvariantResult

__all__ = ["Oracle", "InvariantResult"]


class Oracle:
    """Runs the 9 lifecycle invariants against the post-run DB + sim state.

    All collaborators are injected so the oracle stays a pure asserter: it owns
    no clock, no DB connection lifecycle, no fakes — it only reads them.
    """

    def __init__(
        self,
        *,
        conn,
        capital_ledger,
        fake_trading_client,
        observer,
        marks,
        db_reported_pnl,
        governor_drawdown_pct,
        pidfile=None,
        pidfile_identity="sim-trainer",
        clock=None,
    ) -> None:
        self.conn = conn
        self.capital_ledger = capital_ledger
        self.fake_trading_client = fake_trading_client
        self.observer = observer
        self.marks = marks
        self.db_reported_pnl = db_reported_pnl
        self.governor_drawdown_pct = governor_drawdown_pct
        self.pidfile = pidfile
        self.pidfile_identity = pidfile_identity
        # clock is retained so invariant 8's freshness reads the FROZEN virtual
        # clock rather than wall time; the pidfile stale/recycle detect is the
        # observable surface, the clock is the time authority behind it.
        self.clock = clock

    def assert_all(self) -> list[InvariantResult]:
        """Run every invariant and return its InvariantResult, in 1..9 order.

        Each check runs inside a try/finally that rolls back `self.conn` on exit,
        so a check failure (or an InFailedSqlTransaction state from the prior
        check) does not poison the next check. Rollback on a clean / unstarted
        transaction is a no-op in psycopg2, so signal-only checks are unaffected.
        """
        results: list[InvariantResult] = []
        invocations = (
            lambda: _checks_db.check_attribution(self.conn),
            lambda: _checks_db.check_zero_orphans(self.conn),
            lambda: _checks_db.check_zero_synthetic_closes(self.conn),
            lambda: _checks_signal.check_db_open_equals_broker(
                self.conn, self.fake_trading_client),
            lambda: _checks_signal.check_capital_conservation(
                self.capital_ledger, self.db_reported_pnl),
            lambda: _checks_signal.check_honest_metrics(
                self.capital_ledger, self.marks,
                self.governor_drawdown_pct, self.observer),
            lambda: _checks_db.check_corpus_integrity(self.conn),
            lambda: _checks_signal.check_no_wedged_processes(
                self.pidfile, self.pidfile_identity),
            lambda: _checks_db.check_deterministic_reproducibility(self.conn),
        )
        for invoke in invocations:
            try:
                results.append(invoke())
            finally:
                self.conn.rollback()
        return results

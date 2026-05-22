"""Signal / observer-derived invariant checks for the Oracle (Task 9).

These checks compare DB state against the in-memory truth (CapitalLedger,
FakeTradingClient) and the SwallowedErrorObserver's captured log events.
Invariants 4 (position parity), 5 (capital conservation), 6 (honest metrics +
degraded-vs-swallowed) and 8 (no wedged processes) live here.
"""

from __future__ import annotations

from src.simulation.lifecycle.oracle._result import InvariantResult

# The EXACT governor fail-conservative substring the observer captures
# (governor.py:396). Its presence means the drawdown denominator was masked.
_GOVERNOR_RISK_SIGNAL = "Drawdown computation failed"
_DRAWDOWN_TOLERANCE_PCT = 0.5  # honest-denominator agreement band (percent points)


def check_db_open_equals_broker(conn, fake_trading_client) -> InvariantResult:
    """Invariant 4 — DB-open shadow_trades (ticker, qty) EXACTLY == broker book.

    The set of (ticker, qty) for open shadow_trades must equal exactly the set
    FakeTradingClient.get_all_positions() reports. Any mismatch (extra DB open,
    extra broker position, or a quantity divergence) fails.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT ticker, actual_shares FROM shadow_trades "
        "WHERE status = 'open' "
        "ORDER BY ticker, actual_shares"
    )
    db_open = {(t, float(q or 0.0)) for t, q in cur.fetchall()}
    broker = {
        (p.symbol, float(p.qty)) for p in fake_trading_client.get_all_positions()
    }
    passed = db_open == broker
    detail = (
        f"db_open == broker ({len(db_open)} position(s))"
        if passed
        else f"mismatch: db_only={db_open - broker}, broker_only={broker - db_open}"
    )
    return InvariantResult(
        name="db_open_equals_broker", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )


def check_capital_conservation(capital_ledger, db_reported_pnl) -> InvariantResult:
    """Invariant 5 — capital conservation via CapitalLedger.detect_phantom_pnl.

    The DB-reported P&L must reconcile (within the ledger's tolerance) to the
    realized P&L the independent ledger attributed to actual fills. Phantom P&L
    — capital appearing/vanishing with no attributed fill — fails.
    """
    phantom = capital_ledger.detect_phantom_pnl(db_reported_pnl)
    passed = not phantom
    detail = (
        f"db_pnl={db_reported_pnl} reconciles to attributed "
        f"realized={capital_ledger.realized_pnl()}"
        if passed
        else f"phantom P&L: db_pnl={db_reported_pnl} != "
        f"attributed realized={capital_ledger.realized_pnl()}"
    )
    return InvariantResult(
        name="capital_conservation", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )


def check_honest_metrics(
    capital_ledger, marks, governor_drawdown_pct, observer
) -> InvariantResult:
    """Invariant 6 — honest metrics: degraded-correctly vs error-swallowed.

    The governor's drawdown denominator must match the CapitalLedger's
    authoritative capital. The distinguishing evidence (spec §7.1) is the
    SwallowedErrorObserver: if the governor emitted the
    "[RISK] Drawdown computation failed ... CONSERVATIVE estimate (15%)" line
    (governor.py:396, observable), the real value was MASKED ->
    error_swallowed=True (FAIL). If no such log fired, the metric is honest and
    we compare it to the ledger's drawdown — agreement => degraded_correctly.
    """
    swallowed = any(
        ev.logger_name == "src.risk.governor" and _GOVERNOR_RISK_SIGNAL in ev.message
        for ev in observer.events
    )
    if swallowed:
        return InvariantResult(
            name="honest_metrics", passed=False,
            detail="governor logged [RISK] Drawdown computation failed — "
                   "CONSERVATIVE 15% estimate masks the real denominator",
            degraded_correctly=False, error_swallowed=True,
        )
    authoritative_pct = capital_ledger.drawdown(marks) * 100.0
    agrees = abs(authoritative_pct - governor_drawdown_pct) <= _DRAWDOWN_TOLERANCE_PCT
    detail = (
        f"governor_dd={governor_drawdown_pct:.4f}% matches authoritative "
        f"ledger_dd={authoritative_pct:.4f}%"
        if agrees
        else f"governor_dd={governor_drawdown_pct:.4f}% diverges from "
        f"authoritative ledger_dd={authoritative_pct:.4f}%"
    )
    return InvariantResult(
        name="honest_metrics", passed=agrees, detail=detail,
        degraded_correctly=agrees, error_swallowed=False,
    )


def check_no_wedged_processes(pidfile, pidfile_identity) -> InvariantResult:
    """Invariant 8 — no wedged processes: no stale / recycled training pidfile.

    Uses the FakeTrainerPidfile stale (PID not alive) / recycle (PID alive but
    a different process identity) detection from T7. When no pidfile is supplied
    the invariant passes (no training process was claimed this run). Heartbeat
    freshness is keyed to the FROZEN virtual clock by construction — the pidfile
    detect reads the controllable liveness flag, never the wall clock.
    """
    if pidfile is None:
        return InvariantResult(
            name="no_wedged_processes", passed=True,
            detail="no training pidfile claimed this run",
            degraded_correctly=True, error_swallowed=False,
        )
    stale = pidfile.is_stale()
    recycled = pidfile.is_recycled(pidfile_identity)
    passed = not (stale or recycled)
    if passed:
        detail = "training pidfile fresh (alive + identity matches)"
    elif stale:
        detail = "wedged: training pidfile PID is not alive (stale leftover)"
    else:
        detail = "wedged: training pidfile PID recycled by a different process"
    return InvariantResult(
        name="no_wedged_processes", passed=passed, detail=detail,
        degraded_correctly=passed, error_swallowed=False,
    )

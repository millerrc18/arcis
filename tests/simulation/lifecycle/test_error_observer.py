"""Tests for the SwallowedErrorObserver (Task 81).

The observer is the anti-masking seam the oracle uses to tell "degraded
correctly" from "error silently swallowed". It attaches a logging handler
to prod fail-conservative loggers WITHOUT editing prod control flow.

We exercise the REAL governor fail-conservative branch (compute_current_drawdown
returns the CONSERVATIVE 15% estimate and logs "[RISK] Drawdown computation
failed ...") by pointing it at an unusable db_path so connect_db raises.
"""

import logging
import sqlite3

from src.risk.governor import compute_current_drawdown
from src.simulation.lifecycle.oracle.error_observer import (
    OBSERVED_LOGGERS,
    SwallowedErrorObserver,
)

GOVERNOR_LOGGER = "src.risk.governor"


def _force_governor_failconservative(tmp_path) -> float:
    """Drive compute_current_drawdown into its except branch.

    Passing a directory path as db_path makes the sqlite connect raise,
    so the function hits the fail-conservative branch and returns 15.0.
    """
    bad_db = tmp_path  # a directory, not a file => sqlite cannot open it
    return compute_current_drawdown(db_path=str(bad_db))


def test_observer_records_governor_failconservative(tmp_path):
    obs = SwallowedErrorObserver().install()
    try:
        result = _force_governor_failconservative(tmp_path)
    finally:
        obs.detach()

    # The real fail-conservative branch returns the 15% estimate ...
    assert result == 15.0
    # ... and the observer captured exactly that swallowed-error signal.
    risk_events = [e for e in obs.events if e.logger_name == GOVERNOR_LOGGER]
    assert len(risk_events) == 1
    evt = risk_events[0]
    assert "[RISK] Drawdown computation failed" in evt.message
    assert "CONSERVATIVE estimate" in evt.message
    assert evt.levelname == "ERROR"


def test_clean_compute_records_no_event(tmp_path):
    """A successful drawdown computation must produce NO swallowed-error event."""
    db = tmp_path / "clean.sqlite3"
    # A valid, initialized DB with the table the query reads but zero rows =>
    # the clean (non-failing) drawdown path, which must log nothing.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE shadow_trades ("
        "pnl_dollars REAL, status TEXT, quarantined INTEGER, actual_exit_time TEXT)"
    )
    conn.commit()
    conn.close()

    obs = SwallowedErrorObserver().install()
    try:
        result = compute_current_drawdown(db_path=str(db))
    finally:
        obs.detach()

    assert result == 0.0  # no rows => 0% drawdown, clean path
    assert obs.events == []


def test_detach_removes_handler_and_stops_capture(tmp_path):
    obs = SwallowedErrorObserver().install()
    logger = logging.getLogger(GOVERNOR_LOGGER)
    assert obs in logger.handlers

    obs.detach()
    # Handler fully removed ...
    assert obs not in logger.handlers
    assert not any(isinstance(h, SwallowedErrorObserver) for h in logger.handlers)

    # ... and a subsequent log produces no new event.
    before = len(obs.events)
    logger.error("[RISK] Drawdown computation failed: boom — using CONSERVATIVE estimate (15%)")
    assert len(obs.events) == before


def test_reinstall_does_not_duplicate_handler():
    obs = SwallowedErrorObserver().install()
    obs.install()  # re-install must not stack a second copy
    try:
        for name in OBSERVED_LOGGERS:
            logger = logging.getLogger(name)
            copies = [h for h in logger.handlers if h is obs]
            assert len(copies) == 1
    finally:
        obs.detach()


def test_emit_captures_exception_object():
    obs = SwallowedErrorObserver().install()
    logger = logging.getLogger("src.llm.validator")
    try:
        try:
            raise ValueError("universe down")
        except ValueError:
            logger.error("[VALIDATOR] Universe lookup failed — rejecting AAPL (fail closed): boom",
                         exc_info=True)
        events = [e for e in obs.events if e.logger_name == "src.llm.validator"]
        assert len(events) == 1
        assert isinstance(events[0].exception, ValueError)
        assert "[VALIDATOR] Universe lookup failed" in events[0].message
    finally:
        obs.detach()

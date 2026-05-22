"""Test-only observer for prod fail-conservative log signals.

Called by: simulation.lifecycle.oracle (Task 9 invariant checks)
Calls: none (attaches a logging.Handler to prod loggers)
Owns tables: none
Config keys: none
Tests: tests/simulation/lifecycle/test_error_observer.py

The lifecycle oracle needs to tell "the system degraded correctly" apart
from "an error was silently swallowed". Several prod paths catch an
exception and continue with a conservative default; the ONLY externally
visible trace of that branch is a log line. This module attaches a
``logging.Handler`` to those prod loggers and records every fail-conservative
branch it sees, WITHOUT touching prod control flow.

Confirmed fail-conservative log seams (read 2026-05-22 against
sprint/lifecycle-sim/base HEAD 03af9a4e):

  - src.risk.governor (governor.py:396)
      ERROR "[RISK] Drawdown computation failed: %s — using CONSERVATIVE
      estimate (15%%)" — except branch of compute_current_drawdown.

  - src.shadow_trading.reconcile (reconcile.py:128-131)
      NO distinguishing log line. The tz-coercion / parse fail-conservative
      path is a bare ``except (ValueError, TypeError, AttributeError):
      continue`` (treat row as not-recent => fail toward backfill). It emits
      nothing, so this seam cannot be observed via logging. Documented as a
      gap for the oracle author (Task 9). The nearest observable reconcile
      signal is the WARNING "[RECONCILE] Rejecting backfill for %s: qty=%s
      (long-only system)" at reconcile.py:150, which is a different branch.

  - src.llm.validator (validator.py:44)
      ERROR "[VALIDATOR] Universe lookup failed — rejecting %s (fail closed):
      %s" — except branch of validate_llm_output's universe check.

Task 9 owns the invariant checks; this module only captures the events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

# Prod loggers carrying a distinguishing fail-conservative signal. reconcile
# is included so the oracle still sees ANY error/warning the module emits even
# though its tz-coercion branch logs nothing (see module docstring).
OBSERVED_LOGGERS = (
    "src.risk.governor",
    "src.shadow_trading.reconcile",
    "src.llm.validator",
)


@dataclass
class SwallowedErrorEvent:
    """One fail-conservative branch hit captured from a prod logger."""

    logger_name: str
    levelname: str
    message: str
    exc_info: object | None = None
    exception: BaseException | None = None


class SwallowedErrorObserver(logging.Handler):
    """A test-only logging handler that records fail-conservative branches.

    On ``install()`` it attaches itself to each prod logger in
    ``logger_names``; ``detach()`` removes it cleanly. Every record routed to
    those loggers is captured into ``self.events`` so the oracle can assert
    whether a degradation was logged (correct) or silently swallowed.
    """

    events: list[SwallowedErrorEvent] = field(default_factory=list)

    def __init__(self, logger_names: tuple[str, ...] = OBSERVED_LOGGERS,
                 level: int = logging.WARNING):
        super().__init__(level=level)
        self.logger_names = tuple(logger_names)
        self.events = []
        self._attached_to: list[logging.Logger] = []

    def emit(self, record: logging.LogRecord) -> None:
        exc = record.exc_info[1] if record.exc_info else None
        self.events.append(
            SwallowedErrorEvent(
                logger_name=record.name,
                levelname=record.levelname,
                message=record.getMessage(),
                exc_info=record.exc_info,
                exception=exc,
            )
        )

    def install(self) -> "SwallowedErrorObserver":
        """Attach to every observed prod logger (idempotent — no duplicates)."""
        self.detach()
        for name in self.logger_names:
            target = logging.getLogger(name)
            target.addHandler(self)
            self._attached_to.append(target)
        return self

    def detach(self) -> None:
        """Remove this handler from all loggers it is attached to.

        Also sweeps every observed logger so a re-install can't leave a
        duplicate handler behind even if state drifted.
        """
        for name in self.logger_names:
            target = logging.getLogger(name)
            while self in target.handlers:
                target.removeHandler(self)
        self._attached_to = []

    def clear(self) -> None:
        """Drop captured events without detaching."""
        self.events = []

    def __enter__(self) -> "SwallowedErrorObserver":
        return self.install()

    def __exit__(self, *exc) -> None:
        self.detach()

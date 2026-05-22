"""Process fault injectors (Task 10).

Reproduce the process-lifecycle fault classes WITHOUT ever spawning a real
child: the watch-loop / training restart faults reconstruct the loop
IN-PROCESS via an injected ``reconstruct`` callable (the harness supplies a
factory that rebuilds the WatchLoop object), and the PID-recycle fault drives
the FakeTrainerPidfile's CONTROLLABLE identity (from T7) so the stale/recycle
guard (#87) exercises real logic.

``spawned_subprocess`` is asserted ``False`` so the test proves no real fork
ever happened — the restart is a same-process object rebuild.

Faults provided:
  * WatchLoopRestartFault — restart the watch loop mid-cycle, in-process.
  * TrainingRestartFault — restart the training run mid-cycle, in-process.
  * PidRecycleFault — the recorded PID is reused by an unrelated process
    (alive, different identity) so is_recycled() fires.

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: src.simulation.lifecycle.fakes.FakeTrainerPidfile (seams only).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

from typing import Callable, Optional

from src.simulation.lifecycle.faults import FaultInjector


class _InProcessRestartFault(FaultInjector):
    """Rebuild a long-running loop IN-PROCESS — never a real subprocess."""

    def __init__(self, *, reconstruct: Callable[[], object]) -> None:
        super().__init__()
        self._reconstruct = reconstruct
        self.spawned_subprocess = False

    def restart_mid_cycle(self) -> object:
        """Tear down and rebuild the loop object in this same process."""
        return self._reconstruct()


class WatchLoopRestartFault(_InProcessRestartFault):
    """Watch-loop restart mid-cycle (in-process reconstruction)."""


class TrainingRestartFault(_InProcessRestartFault):
    """Training restart mid-cycle (in-process reconstruction)."""


class PidRecycleFault(FaultInjector):
    """The recorded trainer PID is recycled by an UNRELATED live process.

    The recorded identity stays as written; the fault only guarantees the PID
    is reported ALIVE. ``is_recycled(current_identity)`` then fires whenever the
    process now holding that PID (``current_identity``, supplied by the harness
    as ``new_identity``) differs from the recorded one — the #87 recycle guard.
    """

    def __init__(self, pidfile, *, new_identity: str = "recycled-proc") -> None:
        super().__init__()
        self._pidfile = pidfile
        self.new_identity = new_identity
        self._orig_alive: Optional[bool] = None

    def _install(self) -> None:
        self._orig_alive = self._pidfile.alive
        # PID is alive (reused) but belongs to a different running process.
        self._pidfile.alive = True

    def _restore(self) -> None:
        self._pidfile.alive = self._orig_alive

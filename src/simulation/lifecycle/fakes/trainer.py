"""Faked GPU/Ollama boundary for src.training.trainer (Task 7).

The lifecycle simulator must exercise the REAL trainer DATA logic — the corpus
query, the temporal-holdout split, the empty-holdout promotion block, the
canary / holdout / promotion-gate chain — without ever spawning torch, Ollama,
or touching a real GPU. This module supplies that boundary as monkeypatch
installers / context managers that, while active:

  * Replace ``trainer.subprocess.run`` so the GPU train (trainer.py:814) and
    the ``ollama create`` / ``ollama cp`` calls (851/861) return ``returncode 0``
    instead of spawning a child. Any real child a caller chooses to spawn must
    pass ``env=scrubbed_env()`` (re-exported from bootstrap) — closing the
    prod-PG subprocess wipe-vector.
  * Replace ``trainer._find_gguf`` (838) so it returns a REAL temp ``.gguf``
    file that exists on disk (so the Modelfile step and registration proceed).
  * Redirect the CWD-relative ``training_data/`` writes (797/844) to a sim temp
    dir via a chdir, so a sim run never clobbers the repo's tracked
    ``training_data/`` artifacts.

What this module does NOT fake (left to run for real): ``export_training_data``,
the empty-corpus guard, the empty-holdout block (786-794), canary,
``evaluate_on_holdout``, and register/promotion logic.

FakeTrainerPidfile reproduces the prod pidfile lifecycle from
``scheduler.watch`` (LOCKFILE): write the PID on acquire, remove only when the
file's PID matches ours on release, and expose stale (PID not alive) and
recycled (PID alive but a different process identity) detection — driven by a
CONTROLLABLE PID + liveness hook so invariant #8 tests real logic, not a
fiction.

Content faults (empty corpus, malformed examples) are NOT seeded here — that
is Task 10.

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: src.simulation.lifecycle.bootstrap (scrubbed_env).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_trainer_stub.py
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Optional
from unittest import mock

from src.simulation.lifecycle.bootstrap import scrubbed_env


class _FakeCompletedProcess:
    """Minimal stand-in for subprocess.CompletedProcess (returncode 0)."""

    def __init__(self, args) -> None:
        self.args = args
        self.returncode = 0
        self.stdout = "TRAINING COMPLETE\n"
        self.stderr = ""


class _FakeSubprocessRunner:
    """Records calls and returns a success CompletedProcess (never spawns)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, *_, **__) -> _FakeCompletedProcess:
        self.calls.append(list(args))
        return _FakeCompletedProcess(args)

    @staticmethod
    def scrubbed_env() -> dict:
        """Re-export the bootstrap helper any real child spawn MUST use."""
        return scrubbed_env()


@contextlib.contextmanager
def fake_trainer_subprocess(training_data_dir: Optional[str] = None):
    """Patch trainer's GPU/Ollama boundary; yield the recording stub.

    While active:
      * ``trainer.subprocess.run`` -> success CompletedProcess (recorded).
      * ``trainer._find_gguf`` -> a real temp .gguf path that exists.
      * CWD is moved to a sim temp dir (override with ``training_data_dir``)
        so the trainer's ``training_data/`` writes never hit the repo. Pass
        ``training_data_dir=None`` AND use as a bare ``with`` (no ``as``) to
        keep CWD redirection but ignore the stub — handy when only the data
        logic is under test.
    """
    import src.training.trainer as trainer

    runner = _FakeSubprocessRunner()
    stack = contextlib.ExitStack()
    with stack:
        work_dir = training_data_dir or stack.enter_context(
            tempfile.TemporaryDirectory(prefix="arcis-sim-trainer-")
        )
        gguf_path = Path(work_dir) / "training_data" / "halcyon-latest.gguf"

        def _fake_find_gguf(_directory: str) -> str:
            gguf_path.parent.mkdir(parents=True, exist_ok=True)
            if not gguf_path.exists():
                gguf_path.write_bytes(b"GGUF\x00fake")
            return str(gguf_path)

        stack.enter_context(
            mock.patch.object(trainer.subprocess, "run", runner)
        )
        stack.enter_context(
            mock.patch.object(trainer, "_find_gguf", _fake_find_gguf)
        )
        prev_cwd = os.getcwd()
        os.chdir(work_dir)
        try:
            yield runner
        finally:
            os.chdir(prev_cwd)


class FakeTrainerPidfile:
    """A REAL pidfile with a CONTROLLABLE PID, mirroring scheduler.watch.

    Reproduces the prod lifecycle faithfully:
      * ``acquire`` writes the PID to the lockfile (scheduler.watch:1435).
      * ``release`` removes the lockfile ONLY when its PID matches ours
        (scheduler.watch:1450) — a foreign-owned lock is left untouched.
      * ``is_stale`` is True when the file's PID is not alive
        (scheduler.watch:1419/1427 stale path), driven by a controllable
        ``alive`` flag instead of a real OS probe.
      * ``is_recycled`` is True when the PID is alive but the running process
        identity differs from the recorded one (#87 recycle guard) — the PID
        was reused by an unrelated process.
    """

    def __init__(
        self,
        path,
        *,
        pid: int,
        alive: bool = True,
        identity: str = "sim-trainer",
    ) -> None:
        self.path = Path(path)
        self.pid = pid
        self.alive = alive
        self.identity = identity

    def acquire(self) -> None:
        """Write the controllable PID to the lockfile."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(self.pid))

    def release(self) -> None:
        """Remove the lockfile only when its PID matches ours."""
        if self.path.exists() and self.path.read_text().strip() == str(self.pid):
            self.path.unlink(missing_ok=True)

    def _file_pid(self) -> Optional[int]:
        if not self.path.exists():
            return None
        try:
            return int(self.path.read_text().strip())
        except ValueError:
            return None

    def is_stale(self) -> bool:
        """True when the lockfile's PID is not alive (force-kill leftover)."""
        return self._file_pid() is not None and not self.alive

    def is_recycled(self, current_identity: str) -> bool:
        """True when the PID is alive but belongs to a different process."""
        return (
            self._file_pid() is not None
            and self.alive
            and current_identity != self.identity
        )

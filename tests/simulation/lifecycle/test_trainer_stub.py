"""Tests for the faked trainer subprocess boundary with a REAL pidfile (Task 7).

What is DRIVEN-REAL vs STUBBED here:

  DRIVEN-REAL (the prod trainer logic actually executes):
    * src.training.trainer.export_training_data — the corpus query, temporal
      split, 5-day-gap holdout logic, empty-holdout guard (L786-794).
    * The pidfile lifecycle is reproduced faithfully from
      scheduler.watch (LOCKFILE: write os.getpid()-style PID on acquire,
      remove only if the file's PID matches on release; stale/recycled PID
      detect via _is_pid_alive).

  STUBBED (the GPU/Ollama boundary only):
    * subprocess.run (the GPU train at trainer.py:814 and the two ollama
      create/cp calls at 851/861) — returns returncode 0, never spawns torch.
    * trainer._find_gguf — returns a real temp file path that exists.
    * The CWD-relative training_data/ dir is redirected to a sim temp dir.

The empty-holdout case drives the REAL trainer through a tmp SQLite seeded
with a recent-only corpus (train>0, holdout==0) and asserts run_fine_tune
returns None and never reaches the (stubbed) subprocess.
"""

import importlib
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.simulation.lifecycle.fakes.trainer import (
    FakeTrainerPidfile,
    fake_trainer_subprocess,
)


def _seed_recent_only_corpus(db_path: str, n: int = 20) -> None:
    """Seed n training examples all dated within a 2-day window (recent-only).

    A tight recent window guarantees the 5-day temporal gap pushes the holdout
    boundary past the end of the corpus: train_count > 0, holdout_count == 0.
    """
    from src.training.versioning import init_training_tables
    from src.utils.db import connect_db

    init_training_tables(db_path)
    base = datetime(2026, 5, 20)
    with connect_db(db_path) as conn:
        conn.execute("DELETE FROM training_examples")
        for i in range(n):
            created = (base + timedelta(hours=i)).isoformat()
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, instruction, input_text, "
                " output_text, curriculum_stage, quarantined) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    str(uuid.uuid4()),
                    created,
                    "outcome_win",
                    "Analyze this trade setup.",
                    f"Ticker AAA, setup #{i}.",
                    "<why_now>x</why_now><analysis>y</analysis>",
                    "structure",
                ),
            )
        conn.commit()


@pytest.fixture
def trainer_mod(tmp_path, monkeypatch):
    """Import src.training.trainer after injecting ARCIS_DB_PATH via monkeypatch.

    The lifecycle bootstrap's _scrub_environment() removes ARCIS_DB_PATH before
    this module is collected, leaving src.config.DB_PATH as None. This fixture
    restores a valid path before importing the trainer module so that
    training_stop.STOP_FLAG (computed at module level from src.config.DB_PATH)
    does not raise TypeError: expected str, bytes or os.PathLike, not NoneType.
    """
    db = str(tmp_path / "simtest-trainer.sqlite3")
    monkeypatch.setenv("ARCIS_DB_PATH", db)

    import src.config as _cfg
    monkeypatch.setattr(_cfg, "DB_PATH", db)

    for _mod in (
        "src.training.training_stop",
        "src.training.training_control",
        "src.training.trainer",
    ):
        sys.modules.pop(_mod, None)

    mod = importlib.import_module("src.training.trainer")
    yield mod


# ---------------------------------------------------------------------------
# (a) subprocess boundary + gguf stub
# ---------------------------------------------------------------------------

def test_fake_subprocess_returns_success_and_gguf_resolves(trainer_mod):
    """With the stub active, subprocess.run returns 0 and _find_gguf resolves."""
    trainer = trainer_mod

    with fake_trainer_subprocess() as stub:
        result = trainer.subprocess.run(
            ["python", "train.py"], capture_output=True, text=True,
            env=stub.scrubbed_env(),
        )
        assert result.returncode == 0

        ollama = trainer.subprocess.run(
            ["ollama", "create", "halcyon-v1"], capture_output=True, text=True,
        )
        assert ollama.returncode == 0

        gguf = trainer._find_gguf("training_data")
        assert gguf is not None
        assert Path(gguf).exists()
        assert gguf.endswith(".gguf")


def test_fake_subprocess_never_spawns_real_child(trainer_mod):
    """The stub records calls and never invokes the real subprocess.run."""
    trainer = trainer_mod

    with fake_trainer_subprocess() as stub:
        trainer.subprocess.run(["python", "train.py"])
        trainer.subprocess.run(["ollama", "create", "x", "-f", "Modelfile"])
    assert len(stub.calls) == 2
    assert stub.calls[0][0] == "python"
    assert stub.calls[1][0] == "ollama"


def test_fake_subprocess_requires_scrubbed_env_helper():
    """scrubbed_env() is the bootstrap helper, carrying the safe 5434 URL."""
    with fake_trainer_subprocess() as stub:
        env = stub.scrubbed_env()
    assert "5434" in env["DATABASE_URL"]
    assert env["ARCIS_DISABLE_DOTENV"] == "1"


# ---------------------------------------------------------------------------
# (b) empty-holdout drives REAL trainer logic to return None
# ---------------------------------------------------------------------------

def test_empty_holdout_blocks_promotion_returns_none(tmp_path, trainer_mod):
    """Recent-only corpus → holdout==0 → run_fine_tune returns None (real logic)."""
    trainer = trainer_mod
    db_path = str(tmp_path / "simtest-trainer.sqlite3")

    _seed_recent_only_corpus(db_path, n=20)

    # Confirm the REAL export logic produces train>0, holdout==0.
    with fake_trainer_subprocess(training_data_dir=None):
        split_counts, total = trainer.export_training_data(
            db_path=db_path, alert_on_empty_holdout=False,
        )
    assert total == 20
    assert split_counts["training"] > 0
    assert split_counts["holdout"] == 0

    with fake_trainer_subprocess() as stub:
        result = trainer.run_fine_tune(db_path=db_path)
    assert result is None
    # The empty-holdout guard returns before the subprocess train step.
    assert stub.calls == []


# ---------------------------------------------------------------------------
# (c) REAL pidfile: written, cleared, stale/recycle detectable
# ---------------------------------------------------------------------------

def test_pidfile_written_then_cleared_with_controllable_pid(tmp_path):
    """A REAL pidfile is written with a controllable PID, then cleared."""
    lock = tmp_path / "trainer.lock"
    pidfile = FakeTrainerPidfile(lock, pid=424242)

    assert not lock.exists()
    pidfile.acquire()
    assert lock.exists()
    assert lock.read_text().strip() == "424242"

    pidfile.release()
    assert not lock.exists()


def test_pidfile_stale_detect(tmp_path):
    """A pidfile whose PID is not alive is detectable as stale."""
    lock = tmp_path / "trainer.lock"
    # PID 0 / a never-alive sentinel: the controllable liveness hook says dead.
    pidfile = FakeTrainerPidfile(lock, pid=999999, alive=False)
    pidfile.acquire()
    assert pidfile.is_stale() is True


def test_pidfile_recycle_detect(tmp_path):
    """A recycled PID (file PID alive but identity differs) is detectable."""
    lock = tmp_path / "trainer.lock"
    pidfile = FakeTrainerPidfile(lock, pid=12345, alive=True)
    pidfile.acquire()
    # Same PID is alive but belongs to a different process now (recycled).
    assert pidfile.is_recycled(current_identity="other-process") is True
    assert pidfile.is_recycled(current_identity=pidfile.identity) is False


def test_pidfile_release_only_when_pid_matches(tmp_path):
    """release() must NOT delete a lockfile owned by a different PID."""
    lock = tmp_path / "trainer.lock"
    lock.write_text("777")  # foreign owner
    pidfile = FakeTrainerPidfile(lock, pid=12345)
    pidfile.release()
    assert lock.exists()
    assert lock.read_text().strip() == "777"

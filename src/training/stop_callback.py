"""Cooperative mid-training stop callback for HuggingFace / TRL.

Called by: trainer.py (reference impl; the runtime inline script embeds a copy)
Calls: scheduler.training_stop (is_stop_requested)
Owns tables: none
Owns files: none
Config keys: none
Tests: tests/test_stop_callback.py

``StopOnFlagCallback`` is the importable, unit-tested reference implementation
of the cooperative stop. The actual training script is written to disk at
runtime by trainer.py and cannot import ``src`` — that inline copy (added in a
later task) mirrors the semantics here: on every step / epoch boundary, check
the STOP_OVERNIGHT flag and request a clean training stop when present.
"""

from transformers import TrainerCallback

from src.scheduler.training_stop import is_stop_requested


class StopOnFlagCallback(TrainerCallback):
    """Set ``control.should_training_stop`` when the STOP_OVERNIGHT flag exists.

    ``flag_path`` defaults to None, in which case resolution defers to
    ``is_stop_requested`` (ARCIS_STOP_FLAG env -> absolute STOP_FLAG default).
    """

    def __init__(self, flag_path: str | None = None):
        self._flag_path = flag_path

    def on_step_end(self, args, state, control, **kwargs):
        if is_stop_requested(self._flag_path):
            control.should_training_stop = True
        return control

    def on_epoch_end(self, args, state, control, **kwargs):
        if is_stop_requested(self._flag_path):
            control.should_training_stop = True
        return control

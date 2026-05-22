"""HuggingFace TrainerCallback that honors the absolute overnight STOP flag.

Called by: training.trainer (T9, injects into the generated train script's Trainer)
Calls: training.training_stop (is_stop_requested)
Owns tables: none
Config keys: none
Tests: tests/test_stop_callback.py

When the STOP flag is set mid-training, the next on_step_end / on_evaluate
requests a clean checkpoint (should_save) and a graceful training stop
(should_training_stop) so the morning stop window can hand GPU0 back to
inference without losing the in-progress LoRA adapter.
"""

from transformers import TrainerCallback

from src.training.training_stop import is_stop_requested


class StopOnFlagCallback(TrainerCallback):
    """Stop training cleanly when the overnight STOP flag is observed."""

    def _maybe_stop(self, control):
        if is_stop_requested():
            control.should_save = True
            control.should_training_stop = True
        return control

    def on_step_end(self, args, state, control, **kwargs):
        return self._maybe_stop(control)

    def on_evaluate(self, args, state, control, **kwargs):
        return self._maybe_stop(control)

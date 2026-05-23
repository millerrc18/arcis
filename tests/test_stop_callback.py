"""Tests for stop_callback.StopOnFlagCallback.

The callback bridges the absolute STOP flag (training_stop) into a HuggingFace
Trainer loop: when the flag is set, the next on_step_end / on_evaluate requests
a clean checkpoint + training stop. When unset, control is left untouched.

`transformers` lives in `training/requirements.txt` (relocated from repo-root
`requirements-training.txt` in v0.36.55 / #101 to stop GitHub auto
dep-submission from choking on the unsloth git+URL pin), not the base
`requirements.txt` that `.github/workflows/pg-tests.yml` installs. Module-level
`pytest.importorskip` keeps these tests runnable on training boxes (where
the dep is installed) while skipping cleanly on CI hosted runners. Pre-existing
v0.36.50 (#94) CI gap surfaced by v0.36.54 billing-unblock — guard added to
unblock pg-tests floor enforcement.
"""

from unittest.mock import patch

import pytest

transformers = pytest.importorskip("transformers")
TrainerControl = transformers.TrainerControl

from src.training.stop_callback import StopOnFlagCallback  # noqa: E402


def _control():
    c = TrainerControl()
    c.should_save = False
    c.should_training_stop = False
    return c


def test_on_step_end_sets_flags_when_stop_requested():
    cb = StopOnFlagCallback()
    control = _control()
    with patch("src.training.stop_callback.is_stop_requested", return_value=True):
        ret = cb.on_step_end(args=None, state=None, control=control)
    assert control.should_save is True
    assert control.should_training_stop is True
    # HF callbacks return the (possibly mutated) control object.
    assert ret is control


def test_on_step_end_noop_when_not_requested():
    cb = StopOnFlagCallback()
    control = _control()
    with patch("src.training.stop_callback.is_stop_requested", return_value=False):
        cb.on_step_end(args=None, state=None, control=control)
    assert control.should_save is False
    assert control.should_training_stop is False


def test_on_evaluate_sets_flags_when_stop_requested():
    cb = StopOnFlagCallback()
    control = _control()
    with patch("src.training.stop_callback.is_stop_requested", return_value=True):
        ret = cb.on_evaluate(args=None, state=None, control=control)
    assert control.should_save is True
    assert control.should_training_stop is True
    assert ret is control


def test_on_evaluate_noop_when_not_requested():
    cb = StopOnFlagCallback()
    control = _control()
    with patch("src.training.stop_callback.is_stop_requested", return_value=False):
        cb.on_evaluate(args=None, state=None, control=control)
    assert control.should_save is False
    assert control.should_training_stop is False


def test_is_a_trainer_callback():
    from transformers import TrainerCallback

    assert issubclass(StopOnFlagCallback, TrainerCallback)

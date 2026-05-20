"""Regression-lock for v0.36.35 issue C — trainer Modelfile path crash.

`_find_gguf()` is declared `-> str | None` and returns `str(p)`. `run_fine_tune`
called `gguf_path.as_posix()` on that str, crashing EVERY fine-tune at the
Modelfile-write step (`trainer.py` ~846):

    AttributeError: 'str' object has no attribute 'as_posix'

Fix: `_modelfile_content()` wraps the path in `Path(...)` before `.as_posix()`,
so it works whether the input is a str (the real contract) or a Path.
"""
from __future__ import annotations

from pathlib import Path

from src.training.trainer import _modelfile_content


def test_modelfile_content_accepts_str():
    """The exact regression: a str gguf path must not raise (it did pre-fix)."""
    out = _modelfile_content("training_data/model.gguf")
    assert out == "FROM ./training_data/model.gguf\n"


def test_modelfile_content_normalizes_backslashes():
    """Windows backslash paths become forward slashes for the Modelfile."""
    out = _modelfile_content("training_data\\models\\halcyon.gguf")
    assert out == "FROM ./training_data/models/halcyon.gguf\n"
    assert "\\" not in out


def test_modelfile_content_accepts_path():
    """A Path input also works (forward-compatible)."""
    out = _modelfile_content(Path("training_data") / "model.gguf")
    assert out == "FROM ./training_data/model.gguf\n"

"""Tests for src/scheduler/handler_registration.py (T10+T12).

The capability registry iterates ALL_HANDLERS and looks up _HANDLER_META for
every handler at import time. A missing entry raises KeyError and breaks the
registry plus every test that imports it. These tests lock the invariant that:

- handler_registration imports without raising (no KeyError);
- the 3 new dual-GPU training-lifecycle ACTIONs are registered;
- the 2 retired *_vram_handoff ACTIONs are gone;
- every handler in ALL_HANDLERS has a _HANDLER_META entry.
"""

from __future__ import annotations

import importlib

from src.scheduler import handler_registration
from src.scheduler.handler_registration import _HANDLER_META, _stripped
from src.scheduler.watch_handlers import ALL_HANDLERS


def test_handler_registration_imports_without_keyerror():
    """Re-importing the module must not raise (every handler has metadata)."""
    importlib.reload(handler_registration)


def test_every_handler_has_meta_entry():
    """No handler in ALL_HANDLERS may be missing from _HANDLER_META."""
    missing = [
        _stripped(h.__name__)
        for h in ALL_HANDLERS
        if _stripped(h.__name__) not in _HANDLER_META
    ]
    assert not missing, f"handlers without _HANDLER_META entry: {missing}"


def test_new_training_action_names_present():
    """The 3 dual-GPU training-lifecycle actions are registered in metadata."""
    for name in (
        "evening_training_launch",
        "morning_training_stop",
        "market_open_training_stop",
    ):
        assert name in _HANDLER_META, f"{name} missing from _HANDLER_META"


def test_old_vram_handoff_actions_absent():
    """The retired VRAM-handoff actions must not remain in metadata."""
    assert "morning_vram_handoff" not in _HANDLER_META
    assert "evening_vram_handoff" not in _HANDLER_META


def test_no_vram_handoff_keys_in_meta():
    """Defense-in-depth: no metadata key references the old handoff family."""
    assert not [k for k in _HANDLER_META if "vram_handoff" in k]


def test_overnight_training_collection_description_drops_handoff_wording():
    """The collection description must no longer reference the VRAM handoff."""
    desc, _duration = _HANDLER_META["overnight_training_collection"]
    assert "handoff" not in desc.lower()
    assert "vram" not in desc.lower()

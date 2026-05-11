"""API test fixtures — worktree isolation backstop.

Phase 3-revised T6: inject _REPLACE_SEMANTICS['operator_view_state'] into the
db module so that engine_aware_upsert(action='replace') works in isolated
worktrees where T1 (which adds the entry to db.py) has not yet merged.

Post-merge this fixture is a no-op (the entry is already present natively).
"""
import pytest


@pytest.fixture(autouse=True)
def _ensure_replace_semantics_for_operator_view_state(monkeypatch):
    from src.utils.db import _REPLACE_SEMANTICS
    if "operator_view_state" not in _REPLACE_SEMANTICS:
        monkeypatch.setitem(_REPLACE_SEMANTICS, "operator_view_state", "in_place_update")

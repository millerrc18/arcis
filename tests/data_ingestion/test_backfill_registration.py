"""Verify EDGAR historical backfill capability registers correctly."""
from __future__ import annotations

import importlib


def test_backfill_registration_imports_clean():
    """Importing the registration module must not raise."""
    import src.data_ingestion.backfill_registration as mod
    importlib.reload(mod)
    assert mod is not None


def test_edgar_backfill_is_registered_action():
    """After import, edgar_historical_backfill should appear in ACTIONS."""
    import src.data_ingestion.backfill_registration  # noqa: F401 — side effect
    from src.platform.capability_registry import get_action

    entry = get_action("edgar_historical_backfill")
    assert entry is not None
    assert entry.kind == "action"
    assert entry.ui_kickoff_available is False
    assert "backfill_edgar" in entry.kickoff_endpoint

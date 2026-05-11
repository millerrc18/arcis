"""Phase 3-revised T7 — regression lock for render_sync deletion.

Called by: pytest (Sprint 5 §J5/§J6 Phase 3-revised T7)
Calls: importlib
Owns tables: none
Config keys: none
Tests: that render_sync.py + reconcile.py + reset-live-prices-watermark CLI are gone

Per SP-ONEDB-006: render_sync.py + reconcile.py existed solely to ship rows
between SQLite and PG when the dashboard read from Render PG. The one-DB
cutover (Phase 3-revised) makes PG authoritative and SQLite a stale snapshot.
Both files have no callers post-cutover and were deleted in T7. This test
locks the deletion so future merge conflicts don't accidentally re-introduce.
"""

from __future__ import annotations

import importlib

import pytest


def test_render_sync_module_removed():
    """src/sync/render_sync.py was deleted in T7 — import must fail."""
    with pytest.raises(ImportError):
        importlib.import_module("src.sync.render_sync")


def test_reconcile_module_removed():
    """src/sync/reconcile.py was deleted in T7 — import must fail."""
    with pytest.raises(ImportError):
        importlib.import_module("src.sync.reconcile")


def test_reset_live_prices_watermark_cli_removed():
    """The reset-live-prices-watermark CLI subcommand was deleted in T7."""
    # Inspect the CLI entry-point module for the subcommand registration.
    import src.main as cli_main  # noqa: F401  (imported for its side-effect import check)
    # The simplest assertion is that the function is not present on the commands module.
    import src.cli.commands as cli_cmds
    assert not hasattr(cli_cmds, "cmd_reset_live_prices_watermark"), (
        "cmd_reset_live_prices_watermark should be deleted in T7 "
        "(deprecated alongside render_sync.py per SP-ONEDB-006)"
    )

"""Populate all registries by importing every capability-hosting module.

Call `ensure_bootstrapped()` from any caller that needs a fully-populated
registry (the /api/system/index endpoint; the CI metadata test). Subsequent
calls are no-ops thanks to `_BOOTSTRAPPED` + Python's import cache — modules
only execute their decorators on first import.

Philosophy: registries live in code (R1 of sprint spec). The "import side
effect" is deliberate — a module that hosts a capability must be imported
for its decorator to fire. This module is the single place that enumerates
those hosts.

Error handling: a module that fails to import logs a
CAPABILITY_REGISTRY_BOOTSTRAP_ERROR at WARNING and continues. The CI
metadata test will detect the missing registration and fail the build;
local dev stays unblocked so the operator can still run the app.

Called by: src.api.cloud_app startup; src.api.app startup;
           tests/test_capability_registry_metadata.py fixture.
Calls: the capability-hosting modules below.
Owns tables: none
Config keys: none
Tests: tests/platform/test_capability_registry.py, tests/test_capability_registry_integration.py
"""
from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

_BOOTSTRAPPED = False
_ERRORS: list[tuple[str, Exception]] = []

CAPABILITY_MODULES: tuple[str, ...] = (
    # Actions — registered next to their kickoff logic
    "src.diagnostics",
    "src.platform",
    "src.data_ingestion.backfill_registration",
    # States — registered next to their query logic
    "src.shadow_trading.state",
    "src.services.training_service",
    "src.services.bootcamp_state",
    "src.shadow_trading.alpaca_adapter",
    "src.llm.ollama_state",
    # Systems — registered next to their health-signal source
    "src.startup",
    "src.shadow_trading.reconcile_state",
    "src.attribution.logger",
    "src.platform.capability_registry.audit_registration",
    # Decisions — en-bloc file (see evaluation doc §8.1)
    "src.platform.capability_registry.decisions",
)


def ensure_bootstrapped() -> None:
    """Import every capability-hosting module exactly once.

    Safe to call from request-time code — repeat invocations short-circuit
    via `_BOOTSTRAPPED`. A module that fails to import is logged and skipped;
    the CI metadata test catches missing registrations.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    for module_name in CAPABILITY_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 — intentional broad catch; see module docstring
            logger.warning(
                "CAPABILITY_REGISTRY_BOOTSTRAP_ERROR module=%s error=%s",
                module_name, exc,
            )
            _ERRORS.append((module_name, exc))
    _BOOTSTRAPPED = True


def bootstrap_errors() -> list[tuple[str, Exception]]:
    """Return any errors encountered during the most recent bootstrap."""
    return list(_ERRORS)


def reset_for_tests() -> None:
    """Force the next ensure_bootstrapped call to re-import. Test-only."""
    global _BOOTSTRAPPED
    _BOOTSTRAPPED = False
    _ERRORS.clear()

"""Regression-lock for #807 / dashboard Tier 1.B.

Imports cloud_app and asserts each capability registry has at least one entry.
If a future refactor removes a registry-populating import from cloud_app.py,
this test fails at PR-review time instead of silently shipping an empty
dashboard.

When D1b structural fix replaces module-level imports with per-registry
bootstrap() functions, this test stays — it's testing the *behavior* (registries
are non-empty after cloud_app loads), not the implementation.
"""
import pytest


def test_action_registry_populated():
    import src.api.cloud_app  # noqa: F401 — triggers cascade of registry-populating imports
    from src.platform.capability_registry.registry import list_actions
    assert len(list_actions()) > 0, (
        "ActionRegistry is empty after cloud_app import — dashboard Tier 1.B regression. "
        "Verify cloud_app.py imports modules with @register_action decorators."
    )


def test_state_registry_populated():
    import src.api.cloud_app  # noqa: F401
    from src.platform.capability_registry.registry import list_states
    assert len(list_states()) > 0, (
        "StateRegistry is empty after cloud_app import — dashboard Tier 1.B regression."
    )


def test_system_registry_populated():
    import src.api.cloud_app  # noqa: F401
    from src.platform.capability_registry.registry import list_systems
    assert len(list_systems()) > 0, (
        "SystemRegistry is empty after cloud_app import — dashboard Tier 1.B regression."
    )

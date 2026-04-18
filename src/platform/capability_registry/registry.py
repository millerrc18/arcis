"""Four in-process registries + decorators that populate them at import time.

The registries are module-level dicts. Decorators validate their kwargs
against Pydantic models (see schemas.py) and side-effect the corresponding
registry dict. Any validation error raises at decoration time so malformed
capabilities fail loudly before reaching an endpoint.

Design: mirrors src/platform/plugin_registry.py:19 in shape; one shared
style for "code-colocated registration" across the platform.

Called by: any module that declares capabilities (import-time side effect);
           src.api.cloud_routes.system_index (read-only iteration).
Calls: src.platform.capability_registry.schemas.
Owns tables: none.
Config keys: none.
Tests: tests/platform/test_capability_registry.py.
"""
from __future__ import annotations

from typing import Any, Callable

from src.platform.capability_registry.schemas import (
    ActionEntry,
    BaseEntry,
    DecisionEntry,
    StateEntry,
    SystemEntry,
)


class CapabilityRegistryError(RuntimeError):
    """Raised on duplicate registration or other registry-state violations."""


ACTIONS: dict[str, ActionEntry] = {}
STATES: dict[str, StateEntry] = {}
SYSTEMS: dict[str, SystemEntry] = {}
DECISIONS: dict[str, DecisionEntry] = {}


def _check_duplicate(registry: dict[str, BaseEntry], entry: BaseEntry) -> None:
    """Reject second registration of the same name unless it's an identical re-run.

    Identical re-run (same Pydantic model dump) is allowed so that pytest
    re-imports and dev hot-reloads don't crash. A genuine name collision
    between different capabilities raises CapabilityRegistryError so the
    offender sees a clear message.
    """
    existing = registry.get(entry.name)
    if existing is None:
        return
    if existing.model_dump(mode="json") == entry.model_dump(mode="json"):
        return
    raise CapabilityRegistryError(
        f"Capability {entry.name!r} already registered with different metadata. "
        f"Names must be unique within a registry.",
    )


def register_action(**metadata: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register an Action (kickoff-able operation).

    Usage:

        @register_action(
            name="regime_diagnostic",
            description="Stratified analysis of trade cohort...",
            category="diagnostics",
            version="1.0",
            maintainer="ai_session",
            introduced_in="v0.25.0",
            last_reviewed_date=date(2026, 4, 18),
            kickoff_endpoint="/api/diagnostic-runs/regime",
            history_endpoint="/api/diagnostic-runs?type=regime",
            input_schema={"type": "object", ...},
            output_schema={"type": "object", ...},
            estimated_duration="3-5 minutes",
        )
        def run_regime_diagnostic(...):
            ...

    The decorated function is returned unchanged — the decorator's only
    effect is populating the ACTIONS registry. Registering is idempotent
    for identical metadata; conflicting metadata raises.
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = ActionEntry(**metadata)
        _check_duplicate(ACTIONS, entry)
        ACTIONS[entry.name] = entry
        return fn

    return _decorator


def register_state(**metadata: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a State query.

    The decorated function becomes the entry's `query_function`. The
    endpoint invokes it at request time with a 2-second timeout.
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = StateEntry(query_function=fn, **metadata)
        _check_duplicate(STATES, entry)
        STATES[entry.name] = entry
        return fn

    return _decorator


def register_system(**metadata: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a System with a health check.

    The decorated function becomes the entry's `health_check_function`.
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = SystemEntry(health_check_function=fn, **metadata)
        _check_duplicate(SYSTEMS, entry)
        SYSTEMS[entry.name] = entry
        return fn

    return _decorator


def register_decision(**metadata: Any) -> DecisionEntry:
    """Register a strategic decision (no function required).

    Unlike the other three, Decisions don't wrap behavior — they're
    facts. Called directly in src/platform/capability_registry/decisions.py
    with all fields as kwargs.

    Returns the DecisionEntry for introspection by tests or callers.
    """
    entry = DecisionEntry(**metadata)
    _check_duplicate(DECISIONS, entry)
    DECISIONS[entry.name] = entry
    return entry


# ─── Read-only accessors ───────────────────────────────────────────────

def list_actions() -> list[ActionEntry]:
    return sorted(ACTIONS.values(), key=lambda e: (e.category, e.name))


def list_states() -> list[StateEntry]:
    return sorted(STATES.values(), key=lambda e: (e.category, e.name))


def list_systems() -> list[SystemEntry]:
    return sorted(SYSTEMS.values(), key=lambda e: (e.category, e.name))


def list_decisions() -> list[DecisionEntry]:
    return sorted(DECISIONS.values(), key=lambda e: (e.category, e.name))


def get_action(name: str) -> ActionEntry | None:
    return ACTIONS.get(name)


def get_state(name: str) -> StateEntry | None:
    return STATES.get(name)


def get_system(name: str) -> SystemEntry | None:
    return SYSTEMS.get(name)


def get_decision(name: str) -> DecisionEntry | None:
    return DECISIONS.get(name)


def clear_registries_for_tests() -> None:
    """Clear all four registries. Test hook only — production code must not call this."""
    ACTIONS.clear()
    STATES.clear()
    SYSTEMS.clear()
    DECISIONS.clear()


def all_entries() -> list[BaseEntry]:
    """Return every registered entry across all four registries, sorted by kind + category + name."""
    return (
        list_actions()  # type: ignore[return-value]
        + list_states()
        + list_systems()
        + list_decisions()
    )

"""Structural CI guards for the capability registry (Convention A-E).

This module implements hard (merge-blocking) structural guards. Each guard
derives its expected set from a live oracle (handler list, filename glob,
gate tuple, source-scan, package walk) rather than a static snapshot.

Task 2 scope: Convention B.
Task 3 scope: Convention A (watch-handler ACTIONs).
Conventions C/D/E are added in later tasks per the sequencing contract in
the design spec §8 (guard must land in the SAME batch as or after its target
registrations).
"""
from __future__ import annotations

import pkgutil

import pytest

import src.data_collection as dc
from src.platform.capability_registry import ensure_bootstrapped, list_actions, list_systems
from src.scheduler.watch_handlers import ALL_HANDLERS


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    """Populate registries from production modules before any guard runs."""
    ensure_bootstrapped()
    yield


# ---------------------------------------------------------------------------
# Convention B — every src/data_collection/*_collector.py registers a SYSTEM
# ---------------------------------------------------------------------------

# EXEMPT contract: add a *_collector module stem here ONLY if it is a shared
# helper that hosts no real collector (none today).
# Each entry MUST carry a one-line reason.
EXEMPT: set[str] = set()


def test_every_collector_module_registers_a_system():
    """Every *_collector.py module stem has a corresponding data-collection SYSTEM.

    Oracle: pkgutil.iter_modules over src.data_collection — live code drives
    the expected set, so a new collector file that skips registration fails CI.

    Convention B EXEMPT contract: add a *_collector module stem to EXEMPT only
    if it is a shared helper that hosts no real collector. Each entry MUST carry
    a one-line reason. EXEMPT starts empty — no current exemptions.
    """
    expected = {
        n
        for _, n, _ in pkgutil.iter_modules(dc.__path__)
        if n.endswith("_collector") and n not in EXEMPT
    }
    registered = {s.name for s in list_systems() if s.category == "data-collection"}
    missing = expected - registered
    assert not missing, (
        f"Collector modules with no SYSTEM (name must == module stem): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Convention A — every ALL_HANDLERS handler is a registered ACTION
# ---------------------------------------------------------------------------

def _expected_action_name(h) -> str:
    n = h.__name__
    return n[len("maybe_"):] if n.startswith("maybe_") else n


def test_all_handlers_are_plain_maybe_functions():
    """Every handler in ALL_HANDLERS is a plain maybe_-prefixed function.

    DA-minor hardening: no partials/lambdas — each entry must be callable,
    have a __name__, and that name must start with 'maybe_'.
    """
    for h in ALL_HANDLERS:
        assert callable(h) and hasattr(h, "__name__"), (
            f"ALL_HANDLERS entry {h!r} is not a plain function with __name__"
        )
        assert h.__name__.startswith("maybe_"), (
            f"ALL_HANDLERS entry {h.__name__!r} does not start with 'maybe_'"
        )


def test_all_handlers_stripped_names_have_no_collisions():
    """maybe_-strip produces no duplicate ACTION names across ALL_HANDLERS.

    DA-minor hardening: 16 handlers must produce 16 distinct stripped names.
    """
    stripped = [_expected_action_name(h) for h in ALL_HANDLERS]
    unique = set(stripped)
    assert len(unique) == len(ALL_HANDLERS), (
        f"maybe_-strip produced colliding ACTION names: "
        f"{len(ALL_HANDLERS)} handlers -> {len(unique)} names"
    )


def test_every_watch_handler_is_a_registered_action():
    """Every fn in ALL_HANDLERS maps to a registered ACTION (maybe_-stripped name).

    Oracle: ALL_HANDLERS list — live code drives the expected set, so a new
    handler that skips registration fails CI.
    """
    expected = {_expected_action_name(h) for h in ALL_HANDLERS}
    registered_names = {a.name for a in list_actions()}
    missing = expected - registered_names
    assert not missing, (
        f"Watch handlers without a registered ACTION: {sorted(missing)}"
    )


def test_action_count_increased_by_16():
    """Exactly 16 new scheduler ACTIONs are registered (one per ALL_HANDLERS handler)."""
    scheduler_actions = [a for a in list_actions() if a.category == "scheduler"]
    assert len(scheduler_actions) == 16, (
        f"Expected 16 scheduler category ACTIONs; found {len(scheduler_actions)}: "
        f"{sorted(a.name for a in scheduler_actions)}"
    )

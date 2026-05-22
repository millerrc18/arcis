"""Structural CI guards for the capability registry (Convention A-E).

This module implements hard (merge-blocking) structural guards. Each guard
derives its expected set from a live oracle (handler list, filename glob,
gate tuple, source-scan, package walk) rather than a static snapshot.

Task 2 scope: Convention B only.
Conventions A/C/D/E are added in later tasks per the sequencing contract in
the design spec §8 (guard must land in the SAME batch as or after its target
registrations).
"""
from __future__ import annotations

import pkgutil

import pytest

import src.data_collection as dc
from src.platform.capability_registry import ensure_bootstrapped, list_systems


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

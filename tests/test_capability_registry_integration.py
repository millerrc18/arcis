"""End-to-end integration test for the capability registry.

The ratchet: asserts the post-Sprint-1B final state:
- Zero bootstrap errors
- >= 18 capabilities registered
- Every registry type has entries
- /api/system/index round-trip succeeds when invoked through a
  real TestClient against the cloud router.

Lives at tests/ root (not tests/platform/) so every CI run exercises it.

Test-order robustness: prior tests (e.g. tests/platform/test_capability_registry.py
or tests/api/test_system_index.py) may clear-and-restore the registries, but
the restore only covers the dict contents — the original modules are already
in Python's import cache, so a subsequent ensure_bootstrapped() call cannot
re-run the decorators. The module-scope fixture below force-reloads each
CAPABILITY_MODULE so decorators fire again, restoring the full 18 regardless
of what other tests did.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.system_index import create_router
from src.platform.capability_registry import (
    clear_registries_for_tests,
    ensure_bootstrapped,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)
from src.platform.capability_registry.bootstrap import (
    CAPABILITY_MODULES,
    bootstrap_errors,
    reset_for_tests,
)


def _noop_auth() -> None:
    return None


@pytest.fixture(scope="module", autouse=True)
def _force_repopulate():
    """Guarantee the registries are populated at test-module entry.

    Other test files may have left registries in a partially-cleared
    state; Python's import cache prevents ensure_bootstrapped from
    re-firing the decorators. Force-reload each capability module so
    decorators execute again against a clean registry.
    """
    clear_registries_for_tests()
    reset_for_tests()
    for module_name in CAPABILITY_MODULES:
        try:
            importlib.import_module(module_name)
            importlib.reload(importlib.import_module(module_name))
        except ModuleNotFoundError:
            # Tolerated during incremental rollout
            pass
    reset_for_tests()
    ensure_bootstrapped()
    yield


def test_bootstrap_is_clean_in_final_state():
    errs = bootstrap_errors()
    assert errs == [], (
        "Capability registry bootstrap has errors after full registration. "
        "Every module in bootstrap.CAPABILITY_MODULES must import cleanly. "
        "Errors: " + "; ".join(f"{mod}: {exc!r}" for mod, exc in errs)
    )


def test_18_capabilities_registered():
    total = (
        len(list_actions())
        + len(list_states())
        + len(list_systems())
        + len(list_decisions())
    )
    assert total >= 18, (
        f"Sprint 1B target is 18 capabilities; found {total}. "
        "Audit bootstrap.CAPABILITY_MODULES and each module's decorators."
    )


def test_every_registry_type_has_entries():
    assert list_actions(), "No Actions registered"
    assert list_states(), "No States registered"
    assert list_systems(), "No Systems registered"
    assert list_decisions(), "No Decisions registered"


def test_system_index_endpoint_round_trip(tmp_path, monkeypatch):
    # Use a tmp SQLite for operator_view_state
    db_file = tmp_path / "integration.sqlite3"
    monkeypatch.setattr("src.api.cloud_routes.system_index.DB_PATH", str(db_file))
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql
    import sqlite3

    conn = sqlite3.connect(str(db_file))
    try:
        conn.executescript(generate_create_sql(TABLES["operator_view_state"]))
        conn.commit()
    finally:
        conn.close()

    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(), _noop_auth))
    client = TestClient(app)

    response = client.get("/api/system/index")
    assert response.status_code == 200
    body = response.json()

    assert "actions" in body
    assert "states" in body
    assert "systems" in body
    assert "decisions" in body
    assert body["counts"]["total"] >= 18

    # Every state entry has a live block (possibly unavailable — test env
    # doesn't have Alpaca creds or Ollama).
    for state in body["states"]:
        assert "live" in state
        assert state["live"]["status"] in {"ok", "unavailable", "timeout"}

    # Every system entry has a health block.
    for system in body["systems"]:
        assert "health" in system
        assert system["health"]["status"] in {"ok", "degraded", "down", "unavailable", "timeout"}


def test_mark_reviewed_works_for_real_capability(tmp_path, monkeypatch):
    db_file = tmp_path / "mark.sqlite3"
    monkeypatch.setattr("src.api.cloud_routes.system_index.DB_PATH", str(db_file))
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql
    import sqlite3

    conn = sqlite3.connect(str(db_file))
    try:
        conn.executescript(generate_create_sql(TABLES["operator_view_state"]))
        conn.commit()
    finally:
        conn.close()

    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(), _noop_auth))
    client = TestClient(app)

    response = client.post("/api/system/index/regime_diagnostic/mark-reviewed")
    assert response.status_code == 200
    body = response.json()
    assert body["entry_name"] == "regime_diagnostic"
    assert body["last_reviewed_date_override"]

"""End-to-end integration test for the capability registry.

The ratchet: asserts the post-Sprint-1B final state:
- Zero bootstrap errors
- >= 18 capabilities registered
- Every registry type has entries
- /api/system/index round-trip succeeds when invoked through a
  real TestClient against the cloud router.

Lives at tests/ root (not tests/platform/) so every CI run exercises it.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.system_index import create_router
from src.platform.capability_registry import (
    ensure_bootstrapped,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)
from src.platform.capability_registry.bootstrap import bootstrap_errors


def _noop_auth() -> None:
    return None


def test_bootstrap_is_clean_in_final_state():
    ensure_bootstrapped()
    errs = bootstrap_errors()
    assert errs == [], (
        "Capability registry bootstrap has errors after full registration. "
        "Every module in bootstrap.CAPABILITY_MODULES must import cleanly. "
        "Errors: " + "; ".join(f"{mod}: {exc!r}" for mod, exc in errs)
    )


def test_18_capabilities_registered():
    ensure_bootstrapped()
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
    ensure_bootstrapped()
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

    ensure_bootstrapped()

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

    ensure_bootstrapped()
    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(), _noop_auth))
    client = TestClient(app)

    response = client.post("/api/system/index/regime_diagnostic/mark-reviewed")
    assert response.status_code == 200
    body = response.json()
    assert body["entry_name"] == "regime_diagnostic"
    assert body["last_reviewed_date_override"]

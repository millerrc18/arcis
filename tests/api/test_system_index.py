"""API tests for GET /api/system/index and POST /mark-reviewed.

Covers: empty/populated payloads, counts, timeout fallback, broken query
isolation (one bad state query doesn't break others), delta tracking
across successive calls, and mark-reviewed round-trip.
"""
from __future__ import annotations

import os
import time
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.platform.capability_registry import (
    ACTIONS,
    DECISIONS,
    STATES,
    SYSTEMS,
    clear_registries_for_tests,
    register_action,
    register_decision,
    register_state,
    register_system,
)
from src.platform.capability_registry.bootstrap import reset_for_tests
from src.api.cloud_routes.system_index import create_router


BASE_META = dict(
    description="A capability.",
    category="testing",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.25.0",
    last_reviewed_date=date(2026, 4, 18),
)
VALID_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp SQLite for test isolation.

    Also creates the operator_view_state table via the schema registry.
    """
    db_file = tmp_path / "test.sqlite3"
    # Point the system_index module at the tmp DB.
    monkeypatch.setattr("src.api.cloud_routes.system_index.DB_PATH", str(db_file))
    # Create the operator_view_state table via the schema registry
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    try:
        conn.executescript(generate_create_sql(TABLES["operator_view_state"]))
        conn.commit()
    finally:
        conn.close()
    return str(db_file)


@pytest.fixture
def client(isolated_db, monkeypatch):
    """Build a FastAPI test client with only the system_index router mounted."""
    # Disable bootstrap's real-module imports for test isolation; we'll
    # register synthetic entries per-test.
    monkeypatch.setattr(
        "src.platform.capability_registry.bootstrap.CAPABILITY_MODULES", tuple()
    )
    reset_for_tests()

    # Snapshot+clear registries so each test starts clean.
    saved = (dict(ACTIONS), dict(STATES), dict(SYSTEMS), dict(DECISIONS))
    clear_registries_for_tests()

    app = FastAPI()

    def _noop_auth() -> None:  # no-auth in tests
        return None

    runtime = SimpleNamespace()
    router = create_router(runtime, _noop_auth)
    app.include_router(router)

    yield TestClient(app)

    # Restore.
    clear_registries_for_tests()
    ACTIONS.update(saved[0])
    STATES.update(saved[1])
    SYSTEMS.update(saved[2])
    DECISIONS.update(saved[3])


def _register_synthetic():
    @register_action(
        name="demo_action",
        kickoff_endpoint="/api/demo",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1 minute",
        **BASE_META,
    )
    def act():
        pass

    @register_state(
        name="demo_state",
        refresh_hint="real-time",
        **BASE_META,
    )
    def st():
        return {"value": 42}

    @register_system(
        name="demo_system",
        expected_runtime="always",
        **BASE_META,
    )
    def health():
        return {"status": "ok", "detail": "fine"}

    register_decision(
        name="demo_decision",
        decision_text="We do X.",
        rationale="Because Y.",
        revisit_trigger="Z",
        **BASE_META,
    )


def test_get_empty_index(client):
    response = client.get("/api/system/index")
    assert response.status_code == 200
    body = response.json()
    assert body["actions"] == []
    assert body["states"] == []
    assert body["systems"] == []
    assert body["decisions"] == []
    assert body["counts"]["total"] == 0
    assert body["counts"]["deprecated"] == 0


def test_get_populated_index(client):
    _register_synthetic()
    response = client.get("/api/system/index")
    assert response.status_code == 200
    body = response.json()
    assert len(body["actions"]) == 1
    assert len(body["states"]) == 1
    assert len(body["systems"]) == 1
    assert len(body["decisions"]) == 1
    assert body["counts"]["total"] == 4
    assert body["counts"]["by_category"] == {"testing": 4}


def test_state_query_result_included(client):
    _register_synthetic()
    response = client.get("/api/system/index")
    body = response.json()
    state = body["states"][0]
    assert state["live"]["status"] == "ok"
    assert state["live"]["result"] == {"value": 42}


def test_system_health_included(client):
    _register_synthetic()
    response = client.get("/api/system/index")
    body = response.json()
    system = body["systems"][0]
    assert system["health"]["status"] == "ok"
    assert system["health"]["result"]["status"] == "ok"


def test_broken_state_query_does_not_break_others(client):
    @register_state(name="broken", refresh_hint="rt", **BASE_META)
    def broken():
        raise RuntimeError("intentional failure")

    @register_state(name="working", refresh_hint="rt", **BASE_META)
    def working():
        return {"value": 7}

    response = client.get("/api/system/index")
    assert response.status_code == 200
    body = response.json()
    by_name = {s["name"]: s for s in body["states"]}
    assert by_name["broken"]["live"]["status"] == "unavailable"
    assert "intentional failure" in by_name["broken"]["live"]["error"]
    assert by_name["working"]["live"]["status"] == "ok"
    assert by_name["working"]["live"]["result"] == {"value": 7}


def test_slow_state_query_times_out(client, monkeypatch):
    # Lower the timeout so the test runs fast.
    monkeypatch.setattr("src.api.cloud_routes.system_index.QUERY_TIMEOUT_SECONDS", 0.3)

    @register_state(name="slow", refresh_hint="rt", **BASE_META)
    def slow():
        time.sleep(1.0)
        return {"value": 1}

    response = client.get("/api/system/index")
    assert response.status_code == 200
    body = response.json()
    slow_entry = next(s for s in body["states"] if s["name"] == "slow")
    assert slow_entry["live"]["status"] == "timeout"


def test_delta_tracks_between_successive_calls(client):
    # First call: delta is None (no prior baseline).
    state_value = {"value": 10}

    @register_state(name="counter", refresh_hint="rt", **BASE_META)
    def counter():
        return state_value

    first = client.get("/api/system/index").json()
    c1 = next(s for s in first["states"] if s["name"] == "counter")
    assert c1["delta_since_last_view"] is None

    # Bump the value; second call sees a delta.
    state_value["value"] = 25
    second = client.get("/api/system/index").json()
    c2 = next(s for s in second["states"] if s["name"] == "counter")
    # delta is dict of key diffs per _compute_delta implementation.
    assert c2["delta_since_last_view"] == {"value": 15}


def test_type_change_produces_null_delta(client):
    values = iter([{"value": 10}, {"value": "now_a_string"}])

    @register_state(name="morphing", refresh_hint="rt", **BASE_META)
    def q():
        return next(values, {"value": None})

    client.get("/api/system/index")  # seed baseline: numeric 10
    # Second call returns a value where 'value' is a string; numeric delta shouldn't apply.
    body = client.get("/api/system/index").json()
    entry = next(s for s in body["states"] if s["name"] == "morphing")
    # Either delta is None (type changed) or the dict-diff skipped the key.
    assert entry["delta_since_last_view"] in (None, {})


def test_mark_reviewed_round_trip(client):
    _register_synthetic()
    # Round trip: POST then GET, confirm the override appears.
    resp = client.post("/api/system/index/demo_state/mark-reviewed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entry_name"] == "demo_state"
    assert body["last_reviewed_date_override"]

    index = client.get("/api/system/index").json()
    state = next(s for s in index["states"] if s["name"] == "demo_state")
    assert state["last_reviewed_date_override"] == body["last_reviewed_date_override"]


def test_cloud_runtime_fallback_builds_live_state_payload(monkeypatch):
    monkeypatch.setattr("src.api.cloud_routes.system_index.DB_PATH", None)
    monkeypatch.setattr(
        "src.platform.capability_registry.bootstrap.CAPABILITY_MODULES", tuple()
    )
    monkeypatch.setattr(
        "src.config.load_config",
        lambda: {"bootcamp": {"enabled": False, "email_mode": "digest"}},
    )
    reset_for_tests()
    saved = (dict(ACTIONS), dict(STATES), dict(SYSTEMS), dict(DECISIONS))
    clear_registries_for_tests()

    @register_state(name="shadow_trade_cohort", refresh_hint="real-time", **BASE_META)
    def shadow_trade_cohort():
        return {"error": "should not hit sqlite query function"}

    @register_state(name="training_corpus", refresh_hint="real-time", **BASE_META)
    def training_corpus():
        return {"error": "should not hit sqlite query function"}

    @register_state(name="strategy_registry_state", refresh_hint="real-time", **BASE_META)
    def strategy_registry_state():
        return {"error": "should not hit sqlite query function"}

    @register_state(name="bootcamp_mode", refresh_hint="deploy-time", **BASE_META)
    def bootcamp_mode():
        return {"error": "should not hit sqlite query function"}

    @register_system(name="demo_system", expected_runtime="always", **BASE_META)
    def health():
        return {"status": "ok", "detail": "fine"}

    def query(sql: str, params: tuple = ()):
        if "FROM strategy_registry GROUP BY current_status" in sql:
            return [{"current_status": "shadow_live", "n": 2}]
        if "FROM training_examples GROUP BY UPPER(COALESCE(outcome_type, 'UNKNOWN'))" in sql:
            return [{"outcome": "WIN", "n": 3}]
        if "FROM training_examples GROUP BY COALESCE(source, 'unknown')" in sql:
            return [{"source": "shadow", "n": 3}]
        return []

    def query_one(sql: str, params: tuple = ()):
        if "FROM shadow_trades" in sql:
            return {"open_n": 4, "closed_n": 7, "quarantined_n": 1, "total_n": 11}
        if "SELECT COUNT(*) AS c FROM training_examples" in sql:
            return {"c": 3}
        return None

    app = FastAPI()

    def _noop_auth() -> None:
        return None

    runtime = SimpleNamespace(query=query, query_one=query_one)
    app.include_router(create_router(runtime, _noop_auth))
    client = TestClient(app)

    try:
        response = client.get("/api/system/index")
        assert response.status_code == 200
        body = response.json()
        states = {entry["name"]: entry for entry in body["states"]}
        assert body["counts"]["total"] == 5
        assert states["shadow_trade_cohort"]["live"]["status"] == "ok"
        assert states["shadow_trade_cohort"]["live"]["result"]["value"]["total"] == 11
        assert states["training_corpus"]["live"]["result"]["value"]["by_outcome"] == {"WIN": 3}
        assert states["strategy_registry_state"]["live"]["result"]["value"]["by_status"] == {"shadow_live": 2}
        assert states["bootcamp_mode"]["live"]["result"]["value"]["email_mode"] == "digest"
        assert states["shadow_trade_cohort"]["delta_since_last_view"] is None
    finally:
        clear_registries_for_tests()
        ACTIONS.update(saved[0])
        STATES.update(saved[1])
        SYSTEMS.update(saved[2])
        DECISIONS.update(saved[3])


def test_mark_reviewed_returns_503_when_local_state_unavailable(monkeypatch):
    monkeypatch.setattr("src.api.cloud_routes.system_index.DB_PATH", None)
    monkeypatch.setattr(
        "src.platform.capability_registry.bootstrap.CAPABILITY_MODULES", tuple()
    )
    reset_for_tests()
    saved = (dict(ACTIONS), dict(STATES), dict(SYSTEMS), dict(DECISIONS))
    clear_registries_for_tests()
    _register_synthetic()

    app = FastAPI()

    def _noop_auth() -> None:
        return None

    runtime = SimpleNamespace(query=lambda *args, **kwargs: [], query_one=lambda *args, **kwargs: None)
    app.include_router(create_router(runtime, _noop_auth))
    client = TestClient(app)

    try:
        resp = client.post("/api/system/index/demo_state/mark-reviewed")
        assert resp.status_code == 503
    finally:
        clear_registries_for_tests()
        ACTIONS.update(saved[0])
        STATES.update(saved[1])
        SYSTEMS.update(saved[2])
        DECISIONS.update(saved[3])


def test_mark_reviewed_nonexistent_name_returns_404(client):
    _register_synthetic()
    resp = client.post("/api/system/index/not_a_real_capability/mark-reviewed")
    assert resp.status_code == 404


def test_counts_track_deprecated(client):
    @register_action(
        name="old",
        kickoff_endpoint="/api/old",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        deprecated=True,
        deprecated_replacement="new",
        **BASE_META,
    )
    def old_fn():
        pass

    body = client.get("/api/system/index").json()
    assert body["counts"]["deprecated"] == 1
    assert body["counts"]["total"] == 1


def test_counts_track_stale(client):
    stale_meta = dict(BASE_META, last_reviewed_date=date(2020, 1, 1))

    @register_action(
        name="ancient",
        kickoff_endpoint="/api/x",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **stale_meta,
    )
    def old_fn():
        pass

    body = client.get("/api/system/index").json()
    assert body["counts"]["needs_review"] == 1

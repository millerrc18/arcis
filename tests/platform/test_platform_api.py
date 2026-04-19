"""Tests for /api/platform/* endpoints (Sprint 4 cont. Task 12b)."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App with platform router registered + isolated temp database.

    NOTE: uses importlib.reload because cloud_app.py has no create_app()
    factory — app is built at module level. The platform module must be
    reloaded BEFORE cloud_app so its ``from src.config import DB_PATH``
    re-binds to the monkeypatched value. Tech debt: accessing
    src.config.DB_PATH at call time would remove this reload chain.
    """
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    create_all_tables(db)
    monkeypatch.setenv("API_SECRET", "test-platform-secret")
    # Platform router's read endpoints now route to Postgres when
    # DATABASE_URL is set (hotfix for cloud-mode research-platform page).
    # Tests exercise the SQLite path — delete the env var so _read_rows
    # falls through to sqlite against the monkeypatched DB_PATH.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("src.config.DB_PATH", db)
    import importlib
    import src.api.cloud_routes.platform as platform_mod
    importlib.reload(platform_mod)
    import src.api.cloud_app as cloud_mod
    importlib.reload(cloud_mod)
    return TestClient(cloud_mod.app)


@pytest.fixture(autouse=True)
def patch_auth(monkeypatch):
    """Stub out verify_auth so tests don't need a real API_SECRET bearer."""
    async def _noop(*args, **kwargs):
        return True

    for mod in ["src.api.cloud_routes.platform", "src.api.cloud_routes.core"]:
        try:
            monkeypatch.setattr(f"{mod}.verify_auth", _noop)
        except AttributeError:
            pass  # module may not import verify_auth


def test_strategies_returns_empty_list_when_registry_empty(client, tmp_path):
    """GET /api/platform/strategies with no registered strategies."""
    import sqlite3
    db = str(tmp_path / "test.db")
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM strategy_registry")
    conn.commit()
    conn.close()

    r = client.get("/api/platform/strategies")
    assert r.status_code == 200
    assert r.json() == []


def test_strategy_detail_404_on_unknown_id(client):
    r = client.get("/api/platform/strategies/nonexistent_strategy")
    assert r.status_code == 404


def test_backtest_results_filter_by_strategy(client):
    r = client.get("/api/platform/backtest-results?strategy_id=x&limit=5")
    assert r.status_code == 200
    # Empty for unknown strategy — no error
    assert r.json() == []


def test_promotion_rejects_short_justification(client):
    """NON-NEGOTIABLE GATE #3: justification_note < 40 chars -> 422."""
    r = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "x",
            "target_status": "shadow_trading",
            "confirmation_token": "yes",
            "justification_note": "too short",  # < 40 chars
        },
    )
    # FastAPI returns 422 for Pydantic min_length validation failures
    assert r.status_code in (400, 422)


def test_promotion_accepts_long_justification_even_if_strategy_missing(client):
    """Validation passes; promote() raises downstream if strategy missing.
    The 40-char gate should run at request-validation level."""
    r = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "nonexistent",
            "target_status": "shadow_trading",
            "confirmation_token": "yes",
            "justification_note": "x" * 50,  # >= 40 chars
        },
    )
    # Validation passed; promote() then failed on missing strategy -> 422
    # Actually 404 or 422 acceptable — either is NOT a validation error
    # on the justification length
    assert r.status_code != 400
    # If it returned 422, it should be a promote() downstream error,
    # not a validation error on justification length
    if r.status_code == 422:
        body = r.json()
        detail = str(body).lower()
        assert "justification" not in detail


def test_demotion_rejects_short_reason(client):
    """NON-NEGOTIABLE GATE #4: reason < 20 chars -> 422."""
    r = client.post(
        "/api/platform/demotions",
        json={
            "strategy_id": "x",
            "reason": "short",  # < 20 chars
        },
    )
    assert r.status_code in (400, 422)


def test_demotion_accepts_long_reason(client):
    r = client.post(
        "/api/platform/demotions",
        json={
            "strategy_id": "nonexistent",
            "reason": "x" * 25,  # >= 20 chars
        },
    )
    # Validation passed; demote() may fail downstream
    assert r.status_code != 400
    if r.status_code == 422:
        body = r.json()
        detail = str(body).lower()
        assert "reason" not in detail or "strategy" in detail


def test_backtest_trigger_returns_result_id(client, tmp_path):
    """POST /api/platform/backtests kicks off async; returns result_id + 202."""
    from src.platform.promotion import register_strategy
    db = str(tmp_path / "test.db")
    register_strategy(
        "lazy_prices_v1", "Lazy Prices", "yaml:lazy_prices_v1.yaml",
        "hash1", db_path=db,
    )
    with patch("asyncio.create_task"):
        r = client.post(
            "/api/platform/backtests",
            json={
                "strategy_id": "lazy_prices_v1",
                "start_date": "2023-06-01",
                "end_date": "2023-06-30",
            },
        )
    assert r.status_code in (200, 202)
    body = r.json()
    assert "result_id" in body


def test_production_promotion_requires_24h_delay(client, tmp_path):
    """Two-step: first POST returns 202 with delay_until; second POST with
    same token within 24h also returns 202."""
    import sqlite3
    from src.platform.promotion import register_strategy
    db = str(tmp_path / "test.db")
    register_strategy("p_test", "P", "yaml:p.yaml", "h", db_path=db)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading' "
        "WHERE strategy_id='p_test'",
    )
    conn.commit()
    conn.close()

    # First attempt — records marker
    r1 = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "p_test",
            "target_status": "production",
            "confirmation_token": "step1",
            "justification_note": "x" * 50,
        },
    )
    assert r1.status_code in (202, 425)  # too-early / accepted
    body1 = r1.json()
    assert "delay_until" in body1 or body1.get("status") == "awaiting_delay"

    # Second attempt with same token + still within 24h -> still 202
    r2 = client.post(
        "/api/platform/promotions",
        json={
            "strategy_id": "p_test",
            "target_status": "production",
            "confirmation_token": "step1",
            "justification_note": "x" * 50,
        },
    )
    assert r2.status_code in (202, 425)

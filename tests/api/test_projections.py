"""Tests for /projections/live — revenue projection analytics endpoint.

Called by: pytest (CI)
Calls: src.api.routes.projections, src.analytics.canonical_sharpe
Owns tables: none
Config keys: none

PR #690 B5 regression test: the endpoint must use canonical_sharpe.raw_sharpe
and never re-introduce the `mean/std` non-annualized formula. R1 in the
Track-1.5 audit retired that formula; if a future change reverts to it, this
test fails immediately.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.analytics.canonical_sharpe import raw_sharpe
from src.api.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def temp_db_with_trades():
    """Build a tiny shadow_trades fixture with known returns.

    Uses ARCIS_DB_PATH redirection (CLAUDE.md: tests must NEVER write to the
    prod DB). Yields the path; src.config.DB_PATH is monkeypatched separately
    in the test using `patch.object(...)` so the route picks up the temp file.
    """
    fd, path = tempfile.mkstemp(suffix=".sqlite3", prefix="proj_test_")
    os.close(fd)
    conn = sqlite3.connect(path)
    try:
        # Minimal shadow_trades schema for the route's SELECT.
        conn.execute(
            "CREATE TABLE shadow_trades ("
            "  trade_id TEXT PRIMARY KEY,"
            "  status TEXT,"
            "  pnl_dollars REAL,"
            "  pnl_pct REAL,"
            "  quarantined INTEGER DEFAULT 0,"
            "  actual_exit_time TEXT"
            ")"
        )
        # Five known returns: known mean, known std → predictable raw_sharpe.
        rows = [
            ("t1", "closed", 100.0, 1.5, 0, "2026-04-01T15:00:00"),
            ("t2", "closed", -50.0, -0.8, 0, "2026-04-02T15:00:00"),
            ("t3", "closed", 200.0, 2.3, 0, "2026-04-03T15:00:00"),
            ("t4", "closed", 75.0, 1.1, 0, "2026-04-04T15:00:00"),
            ("t5", "closed", -25.0, -0.4, 0, "2026-04-05T15:00:00"),
        ]
        conn.executemany(
            "INSERT INTO shadow_trades (trade_id, status, pnl_dollars, pnl_pct, "
            "quarantined, actual_exit_time) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ── PR #690 B5: canonical Sharpe regression ──────────────────────────────────


def test_projections_live_sharpe_matches_canonical_raw_sharpe(
    client, temp_db_with_trades,
):
    """projections/live `sharpe` must equal canonical_sharpe.raw_sharpe(pnl_pcts).

    Pre-PR-#690-B5 the endpoint used `mean/std` (non-annualized, no ddof=1
    contract) — the very formula R1 in Track-1.5 retired. This regression
    test fixes the contract: any future drift from canonical fails CI.
    """
    pnl_pcts = [1.5, -0.8, 2.3, 1.1, -0.4]
    expected = raw_sharpe(pnl_pcts)
    assert expected is not None, "fixture must produce a defined Sharpe"

    with patch("src.api.routes.projections.DB_PATH", temp_db_with_trades):
        resp = client.get("/api/projections/live")

    assert resp.status_code == 200
    data = resp.json()
    assert data["trades"] == 5
    # Endpoint rounds to 3 dp; canonical is the truth source.
    assert data["sharpe"] == round(expected, 3), (
        f"endpoint sharpe={data['sharpe']} but canonical raw_sharpe="
        f"{round(expected, 3)} — non-canonical formula has been re-introduced"
    )


def test_projections_live_sharpe_zero_when_undefined(client):
    """Zero closed trades → endpoint returns trades=0, no sharpe field needed.

    Verifies the empty-set early return path is preserved.
    """
    fd, path = tempfile.mkstemp(suffix=".sqlite3", prefix="proj_empty_")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE shadow_trades ("
            "  trade_id TEXT PRIMARY KEY, status TEXT, pnl_dollars REAL,"
            "  pnl_pct REAL, quarantined INTEGER DEFAULT 0,"
            "  actual_exit_time TEXT)"
        )
        conn.commit()
        conn.close()
        with patch("src.api.routes.projections.DB_PATH", path):
            resp = client.get("/api/projections/live")
        assert resp.status_code == 200
        assert resp.json() == {"trades": 0}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_projections_live_sharpe_uses_canonical_module(client, temp_db_with_trades):
    """B5 anti-regression: the endpoint must call canonical_sharpe.raw_sharpe.

    If a future refactor inlines a mean/std computation, the patched mock won't
    be called and this assertion fails — catching the regression.
    """
    real_raw_sharpe = raw_sharpe  # capture before patching
    with patch(
        "src.api.routes.projections.raw_sharpe",
        side_effect=real_raw_sharpe,
    ) as mock_sharpe, patch(
        "src.api.routes.projections.DB_PATH", temp_db_with_trades,
    ):
        resp = client.get("/api/projections/live")
    assert resp.status_code == 200
    assert mock_sharpe.called, (
        "projections.py must call canonical_sharpe.raw_sharpe; if this fails, "
        "PR #690 B5 has regressed"
    )

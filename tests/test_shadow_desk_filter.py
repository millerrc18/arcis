"""Defensive desk-filter tests for /api/shadow/* endpoints — Sprint 3 Task 12c.

Non-negotiable gates:
  2. no ?desk= param → swing-only (backward compat)
  3. ?desk=all → sums across desks
  4. ?desk=research_* wildcard matches all research desks

Test style mirrors tests/test_cloud_app.py:
  - Uses the `client` fixture from conftest (or re-declared here identically)
  - Patches src.api.cloud_app._query / _query_one
  - Tests grouped in a class per behaviour
"""

import os
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures (replicate test_cloud_app.py style exactly) ─────────────────────

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/halcyon")
    monkeypatch.delenv("API_SECRET", raising=False)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_SECRET", "test-api-secret")
    import importlib
    import src.api.cloud_app as cloud_mod
    importlib.reload(cloud_mod)

    test_client = TestClient(cloud_mod.app)

    original_get = test_client.get

    def get_with_auth(url, **kwargs):
        if "headers" not in kwargs:
            kwargs["headers"] = {"Authorization": "Bearer test-api-secret"}
        elif "Authorization" not in kwargs.get("headers", {}):
            kwargs["headers"]["Authorization"] = "Bearer test-api-secret"
        return original_get(url, **kwargs)

    test_client.get = get_with_auth
    return test_client


# ── Helper data ───────────────────────────────────────────────────────────────

_SWING_ROWS = [
    {"pnl_pct": 2.0, "spy_return_over_hold": 0.5, "excess_return": 1.5, "desk": "swing"},
    {"pnl_pct": -1.0, "spy_return_over_hold": 0.3, "excess_return": -1.3, "desk": "swing"},
    {"pnl_pct": 3.0, "spy_return_over_hold": 0.8, "excess_return": 2.2, "desk": "swing"},
]

_RESEARCH_ROW = {
    "pnl_pct": 5.0,
    "spy_return_over_hold": 0.5,
    "excess_return": 4.5,
    "desk": "research_lazy_prices_v1",
}

_SWING_OPEN_ROWS = [
    {
        "trade_id": "sw1",
        "ticker": "AAPL",
        "status": "open",
        "desk": "swing",
        "actual_entry_price": None,
        "entry_price": None,
        "actual_shares": None,
        "planned_shares": None,
    }
]

_RESEARCH_OPEN_ROW = {
    "trade_id": "re1",
    "ticker": "MSFT",
    "status": "open",
    "desk": "research_lazy_prices_v1",
    "actual_entry_price": None,
    "entry_price": None,
    "actual_shares": None,
    "planned_shares": None,
}


# ── sharpe-attribution desk filter ───────────────────────────────────────────

class TestSharpeAttributionDeskFilter:
    """Non-negotiable gates 2, 3, 4 via /api/shadow/sharpe-attribution."""

    @patch("src.api.cloud_app._query")
    def test_desk_absent_returns_swing_only(self, mock_query, client):
        """Gate 2: no ?desk= → endpoint must query with desk='swing' clause."""
        mock_query.return_value = _SWING_ROWS

        resp = client.get("/api/shadow/sharpe-attribution")
        assert resp.status_code == 200
        data = resp.json()
        # The endpoint called _query exactly once
        assert mock_query.call_count == 1
        sql_called = mock_query.call_args.args[0]
        params_called = mock_query.call_args.args[1] if len(mock_query.call_args.args) > 1 else mock_query.call_args.kwargs.get("params", ())
        # Must contain the desk equality filter and pass 'swing' as the param
        assert "desk" in sql_called.lower()
        assert "swing" in str(params_called)
        # Response should reflect the 3 swing rows
        assert data.get("n_trades") == 3

    @patch("src.api.cloud_app._query")
    def test_desk_swing_explicit_returns_swing_only(self, mock_query, client):
        """Gate 2 (explicit): ?desk=swing → identical to absent."""
        mock_query.return_value = _SWING_ROWS

        resp = client.get("/api/shadow/sharpe-attribution?desk=swing")
        assert resp.status_code == 200
        data = resp.json()
        assert mock_query.call_count == 1
        sql_called = mock_query.call_args.args[0]
        params_called = mock_query.call_args.args[1] if len(mock_query.call_args.args) > 1 else ()
        assert "desk" in sql_called.lower()
        assert "swing" in str(params_called)
        assert data.get("n_trades") == 3

    @patch("src.api.cloud_app._query")
    def test_desk_all_sums_across_desks(self, mock_query, client):
        """Gate 3: ?desk=all → 1=1 fragment (no desk filter), all rows returned."""
        all_rows = _SWING_ROWS + [_RESEARCH_ROW]
        mock_query.return_value = all_rows

        resp = client.get("/api/shadow/sharpe-attribution?desk=all")
        assert resp.status_code == 200
        data = resp.json()
        assert mock_query.call_count == 1
        sql_called = mock_query.call_args.args[0]
        # The desk=all clause is '1=1' — no desk column filter in the SQL
        assert "1=1" in sql_called
        assert data.get("n_trades") == 4

    @patch("src.api.cloud_app._query")
    def test_desk_wildcard_matches_all_research(self, mock_query, client):
        """Gate 4: ?desk=research_* → LIKE 'research_%', returns only research rows."""
        mock_query.return_value = [_RESEARCH_ROW]

        resp = client.get("/api/shadow/sharpe-attribution?desk=research_*")
        assert resp.status_code == 200
        data = resp.json()
        assert mock_query.call_count == 1
        sql_called = mock_query.call_args.args[0]
        params_called = mock_query.call_args.args[1] if len(mock_query.call_args.args) > 1 else ()
        # Must use LIKE with the % wildcard
        assert "LIKE" in sql_called.upper()
        assert "research_%" in str(params_called)
        # Insufficient data for sharpe computation — mock returns only 1 row
        assert data.get("n_trades") == 1

    @patch("src.api.cloud_app._query")
    def test_desk_exact_match_single_strategy(self, mock_query, client):
        """?desk=research_lazy_prices_v1 → exact equality, only that strategy's rows."""
        mock_query.return_value = [_RESEARCH_ROW]

        resp = client.get("/api/shadow/sharpe-attribution?desk=research_lazy_prices_v1")
        assert resp.status_code == 200
        data = resp.json()
        assert mock_query.call_count == 1
        sql_called = mock_query.call_args.args[0]
        params_called = mock_query.call_args.args[1] if len(mock_query.call_args.args) > 1 else ()
        # Must NOT use LIKE — exact equality
        assert "LIKE" not in sql_called.upper()
        assert "research_lazy_prices_v1" in str(params_called)


# ── /api/shadow/open desk filter ─────────────────────────────────────────────

class TestShadowOpenDeskFilter:
    """Regression: desk filter applied to /api/shadow/open."""

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_open_desk_absent_is_swing_only(self, mock_query, mock_one, client):
        """No ?desk= → /api/shadow/open queries swing desk only."""
        mock_query.return_value = _SWING_OPEN_ROWS
        mock_one.return_value = {"total": 0}

        resp = client.get("/api/shadow/open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        # Verify SQL contained desk='swing' filter
        first_call_sql = mock_query.call_args_list[0].args[0]
        first_call_params = mock_query.call_args_list[0].args[1] if len(mock_query.call_args_list[0].args) > 1 else ()
        assert "desk" in first_call_sql.lower()
        assert "swing" in str(first_call_params)

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_open_desk_all_passes_no_desk_filter(self, mock_query, mock_one, client):
        """?desk=all → /api/shadow/open uses 1=1 clause."""
        all_open = _SWING_OPEN_ROWS + [_RESEARCH_OPEN_ROW]
        mock_query.return_value = all_open
        mock_one.return_value = {"total": 0}

        resp = client.get("/api/shadow/open?desk=all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        first_call_sql = mock_query.call_args_list[0].args[0]
        assert "1=1" in first_call_sql


# ── /api/shadow/desks endpoint ────────────────────────────────────────────────

class TestShadowDesksEndpoint:
    """GET /api/shadow/desks returns distinct desk values."""

    @patch("src.api.cloud_app._query")
    def test_desks_returns_swing_and_all_when_no_research(self, mock_query, client):
        """With no research desks in DB, endpoint returns exactly ['swing', 'all']."""
        # The query for non-swing desks returns empty
        mock_query.return_value = []

        resp = client.get("/api/shadow/desks")
        assert resp.status_code == 200
        data = resp.json()
        assert data == ["swing", "all"]

    @patch("src.api.cloud_app._query")
    def test_desks_includes_research_desks_from_db(self, mock_query, client):
        """With research trades in DB, endpoint includes those desks."""
        mock_query.return_value = [
            {"desk": "research_lazy_prices_v1"},
            {"desk": "research_momentum_v2"},
        ]

        resp = client.get("/api/shadow/desks")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0] == "swing"
        assert data[1] == "all"
        assert "research_lazy_prices_v1" in data
        assert "research_momentum_v2" in data
        assert len(data) == 4

    @patch("src.api.cloud_app._query")
    def test_desks_gracefully_handles_db_error(self, mock_query, client):
        """On DB error, endpoint falls back to ['swing', 'all'] — never 500."""
        mock_query.side_effect = Exception("connection lost")

        resp = client.get("/api/shadow/desks")
        assert resp.status_code == 200
        data = resp.json()
        assert "swing" in data
        assert "all" in data


# ── _desk_clause unit tests ───────────────────────────────────────────────────

class TestDeskClauseHelper:
    """Unit-test the _desk_clause helper directly (no HTTP overhead)."""

    def test_none_returns_swing_clause(self):
        from src.api.cloud_routes.trades import _desk_clause
        frag, params = _desk_clause(None)
        assert "desk = %s" in frag
        assert params == ["swing"]

    def test_swing_returns_swing_clause(self):
        from src.api.cloud_routes.trades import _desk_clause
        frag, params = _desk_clause("swing")
        assert "desk = %s" in frag
        assert params == ["swing"]

    def test_all_returns_no_filter(self):
        from src.api.cloud_routes.trades import _desk_clause
        frag, params = _desk_clause("all")
        assert frag == "1=1"
        assert params == []

    def test_wildcard_converted_to_like(self):
        from src.api.cloud_routes.trades import _desk_clause
        frag, params = _desk_clause("research_*")
        assert "LIKE" in frag
        assert params == ["research_%"]

    def test_exact_research_strategy_uses_equality(self):
        from src.api.cloud_routes.trades import _desk_clause
        frag, params = _desk_clause("research_lazy_prices_v1")
        assert "desk = %s" in frag
        assert params == ["research_lazy_prices_v1"]
        assert "LIKE" not in frag

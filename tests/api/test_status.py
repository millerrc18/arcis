"""Tests for _meta envelope on /api/status and the cohort_meta helper module.

Sprint 3 — Cockpit Coherence — Task T8 (A1 backend _meta helper).
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_db_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/halcyon")
    monkeypatch.setenv("API_SECRET", "test-api-secret")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_SECRET", "test-api-secret")
    import src.api.cloud_app as cloud_mod
    importlib.reload(cloud_mod)
    c = TestClient(cloud_mod.app)
    original_get = c.get

    def get_with_auth(url, **kwargs):
        if "headers" not in kwargs:
            kwargs["headers"] = {"Authorization": "Bearer test-api-secret"}
        return original_get(url, **kwargs)

    c.get = get_with_auth
    return c


# ── cohort_meta module tests ──────────────────────────────────────────────────

class TestCohortLabels:
    def test_all_eight_cohort_ids_present(self):
        from src.api.cohort_meta import COHORT_LABELS
        expected = {
            "kpi.canonical",
            "trades.all_closed",
            "trades.strategy",
            "trades.model",
            "trades.live_only",
            "stress.scenario",
            "attribution.pairs",
            "none",
        }
        assert set(COHORT_LABELS.keys()) == expected

    def test_labels_are_non_empty_strings(self):
        from src.api.cohort_meta import COHORT_LABELS
        for cohort_id, label in COHORT_LABELS.items():
            assert isinstance(label, str) and label, (
                f"COHORT_LABELS['{cohort_id}'] must be a non-empty string"
            )


class TestMetaEntry:
    def test_returns_dict_with_cohort_label_n(self):
        from src.api.cohort_meta import meta_entry
        result = meta_entry("kpi.canonical", 5)
        assert result["cohort"] == "kpi.canonical"
        assert result["n"] == 5
        assert "label" in result
        assert isinstance(result["label"], str) and result["label"]

    def test_uses_cohort_labels_when_label_none(self):
        from src.api.cohort_meta import meta_entry, COHORT_LABELS
        result = meta_entry("trades.all_closed", 10)
        assert result["label"] == COHORT_LABELS["trades.all_closed"]

    def test_custom_label_overrides_default(self):
        from src.api.cohort_meta import meta_entry
        result = meta_entry("trades.strategy", 3, label="Strategy-attributed (Pullback)")
        assert result["label"] == "Strategy-attributed (Pullback)"

    def test_unknown_cohort_raises_key_error(self):
        from src.api.cohort_meta import meta_entry
        with pytest.raises(KeyError):
            meta_entry("unknown", 0)

    def test_n_is_preserved_as_passed(self):
        from src.api.cohort_meta import meta_entry
        result = meta_entry("none", 42)
        assert result["n"] == 42


# ── /api/kpis _meta tests ─────────────────────────────────────────────────────

class TestKpisMetaEnvelope:
    def test_kpis_response_has_meta_key(self):
        from src.api.cloud_routes.kpis import get_kpis
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert "_meta" in result

    def test_rf_adjusted_excess_sharpe_cohort_is_canonical(self):
        from src.api.cloud_routes.kpis import get_kpis
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert "_meta" in result
        assert "rf_adjusted_excess_sharpe" in result["_meta"]
        assert result["_meta"]["rf_adjusted_excess_sharpe"]["cohort"] == "kpi.canonical"

    def test_win_rate_cohort_is_canonical(self):
        from src.api.cloud_routes.kpis import get_kpis
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert result["_meta"]["win_rate"]["cohort"] == "kpi.canonical"

    def test_meta_n_matches_instrumented_count(self):
        from src.api.cloud_routes.kpis import get_kpis
        trades = [
            {"pnl_pct": 2.0, "spy_return_over_hold": None,
             "actual_entry_time": "2026-01-01T10:00:00",
             "actual_exit_time": "2026-01-05T15:00:00",
             "excess_return": 0.01},
            {"pnl_pct": -1.0, "spy_return_over_hold": None,
             "actual_entry_time": "2026-01-02T10:00:00",
             "actual_exit_time": "2026-01-06T15:00:00",
             "excess_return": -0.005},
        ]
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=trades), \
             patch("src.analytics.instrumentation_filter.filter_fully_instrumented",
                   return_value=trades):
            result = get_kpis()
        assert result["_meta"]["win_rate"]["n"] == 2


# ── /api/status _meta tests ───────────────────────────────────────────────────

class TestStatusMetaEnvelope:
    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_status_response_has_meta_key(self, mock_query, mock_query_one, client):
        mock_query.return_value = [{"count": 3}]
        mock_query_one.side_effect = [
            {"version_name": "v1", "created_at": "2026-01-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2026-01-01"},
            {"c": 100},
        ]
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "_meta" in data

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_open_positions_cohort_is_live_only(self, mock_query, mock_query_one, client):
        mock_query.return_value = [{"count": 5}]
        mock_query_one.side_effect = [
            {"version_name": "v1", "created_at": "2026-01-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2026-01-01"},
            {"c": 100},
        ]
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "_meta" in data
        assert "open_positions" in data["_meta"]
        assert data["_meta"]["open_positions"]["cohort"] == "trades.live_only"

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_version_cohort_is_none(self, mock_query, mock_query_one, client):
        mock_query.return_value = [{"count": 5}]
        mock_query_one.side_effect = [
            {"version_name": "v1", "created_at": "2026-01-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2026-01-01"},
            {"c": 100},
        ]
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "_meta" in data
        assert "version" in data["_meta"]
        assert data["_meta"]["version"]["cohort"] == "none"

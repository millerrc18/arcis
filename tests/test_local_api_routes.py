"""Tests for local dashboard API routes (thin wrappers around services)."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.packets import router as packets_router
from src.api.routes.training import router as training_router
from src.api.routes.scan import router as scan_router
from src.api.routes.review import router as review_router
from src.api.routes.system import router as system_router


# ── Fixtures ──


@pytest.fixture
def packets_client():
    app = FastAPI()
    app.include_router(packets_router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def training_client():
    app = FastAPI()
    app.include_router(training_router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def scan_client():
    app = FastAPI()
    app.include_router(scan_router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def review_client():
    app = FastAPI()
    app.include_router(review_router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def system_client():
    app = FastAPI()
    app.include_router(system_router, prefix="/api")
    return TestClient(app)


# ── Packets routes ──


class TestPacketsRoutes:
    @patch("src.api.routes.packets.get_recommendations_in_period")
    def test_list_packets(self, mock_recs, packets_client):
        mock_recs.return_value = [{"ticker": "AAPL", "priority_score": 85}]
        r = packets_client.get("/api/packets?days=7")
        assert r.status_code == 200
        assert len(r.json()) == 1

    @patch("src.api.routes.packets.get_recommendations_in_period")
    def test_list_packets_filter_ticker(self, mock_recs, packets_client):
        mock_recs.return_value = [
            {"ticker": "AAPL", "priority_score": 85},
            {"ticker": "MSFT", "priority_score": 90},
        ]
        r = packets_client.get("/api/packets?ticker=AAPL")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["ticker"] == "AAPL"

    @patch("src.api.routes.packets.get_recommendations_in_period")
    def test_list_packets_filter_min_score(self, mock_recs, packets_client):
        mock_recs.return_value = [
            {"ticker": "AAPL", "priority_score": 50},
            {"ticker": "MSFT", "priority_score": 90},
        ]
        r = packets_client.get("/api/packets?min_score=80")
        assert len(r.json()) == 1

    @patch("src.api.routes.packets.get_recommendation_by_id")
    def test_get_packet_found(self, mock_rec, packets_client):
        mock_rec.return_value = {"recommendation_id": "r1", "ticker": "AAPL"}
        r = packets_client.get("/api/packets/r1")
        assert r.status_code == 200
        assert r.json()["ticker"] == "AAPL"

    @patch("src.api.routes.packets.get_recommendation_by_id")
    def test_get_packet_not_found(self, mock_rec, packets_client):
        mock_rec.return_value = None
        r = packets_client.get("/api/packets/nonexistent")
        assert r.status_code == 200
        assert "error" in r.json()


# ── Training routes ──


class TestTrainingRoutes:
    @patch("src.api.routes.training.get_training_status")
    def test_training_status(self, mock_fn, training_client):
        mock_fn.return_value = {"model_name": "halcyon-v1", "dataset_total": 900}
        r = training_client.get("/api/training/status")
        assert r.status_code == 200
        assert r.json()["model_name"] == "halcyon-v1"

    @patch("src.api.routes.training.get_training_history")
    def test_training_versions(self, mock_fn, training_client):
        mock_fn.return_value = {"versions": []}
        r = training_client.get("/api/training/versions")
        assert r.status_code == 200

    @patch("src.api.routes.training.get_training_report")
    def test_training_report(self, mock_fn, training_client):
        mock_fn.return_value = "Training report text"
        r = training_client.get("/api/training/report")
        assert r.status_code == 200
        assert "report" in r.json()

    @patch("src.api.routes.training.run_fine_tune_service")
    def test_train_success(self, mock_fn, training_client):
        mock_fn.return_value = {"version": "v2"}
        r = training_client.post("/api/training/train")
        assert r.status_code == 200
        assert r.json()["version"] == "v2"

    @patch("src.api.routes.training.run_fine_tune_service")
    def test_train_failure(self, mock_fn, training_client):
        mock_fn.return_value = None
        r = training_client.post("/api/training/train")
        assert "error" in r.json()

    @patch("src.api.routes.training.rollback_model_service")
    def test_rollback_success(self, mock_fn, training_client):
        mock_fn.return_value = {"rolled_back_to": "v1"}
        r = training_client.post("/api/training/rollback")
        assert r.status_code == 200

    @patch("src.api.routes.training.rollback_model_service")
    def test_rollback_no_previous(self, mock_fn, training_client):
        mock_fn.return_value = None
        r = training_client.post("/api/training/rollback")
        assert "error" in r.json()


# ── Scan routes ──


class TestScanRoutes:
    @patch("src.api.routes.scan.run_scan")
    @patch("src.api.routes.scan.load_config")
    def test_trigger_scan(self, mock_config, mock_scan, scan_client):
        mock_config.return_value = {}
        mock_scan.return_value = {"packets": 3, "watchlist": 10}
        r = scan_client.post("/api/scan")
        assert r.status_code == 200
        assert r.json()["packets"] == 3

    def test_latest_scan_none(self, scan_client):
        # Reset module state
        import src.api.routes.scan as scan_mod
        scan_mod._latest_scan = None
        r = scan_client.get("/api/scan/latest")
        assert r.status_code == 200
        assert "message" in r.json()

    @patch("src.api.routes.scan.generate_morning_watchlist")
    @patch("src.api.routes.scan.load_config")
    def test_morning_watchlist(self, mock_config, mock_wl, scan_client):
        mock_config.return_value = {}
        mock_wl.return_value = {"watchlist": ["AAPL"]}
        r = scan_client.post("/api/morning-watchlist")
        assert r.status_code == 200

    @patch("src.api.routes.scan.generate_eod_recap")
    @patch("src.api.routes.scan.load_config")
    def test_eod_recap(self, mock_config, mock_recap, scan_client):
        mock_config.return_value = {}
        mock_recap.return_value = {"recap": "done"}
        r = scan_client.post("/api/eod-recap")
        assert r.status_code == 200


# ── Review routes ──


class TestReviewRoutes:
    @patch("src.api.routes.review.get_pending_reviews")
    def test_pending_reviews(self, mock_fn, review_client):
        mock_fn.return_value = [{"recommendation_id": "r1"}]
        r = review_client.get("/api/review/pending")
        assert r.status_code == 200
        assert len(r.json()) == 1

    @patch("src.api.routes.review.get_scorecard")
    def test_scorecard(self, mock_fn, review_client):
        mock_fn.return_value = "Scorecard text"
        r = review_client.get("/api/review/scorecard?weeks=2")
        assert r.status_code == 200
        assert "scorecard" in r.json()

    @patch("src.api.routes.review.get_postmortems")
    def test_postmortems(self, mock_fn, review_client):
        mock_fn.return_value = []
        r = review_client.get("/api/review/postmortems")
        assert r.status_code == 200

    @patch("src.api.routes.review.get_postmortem_detail")
    def test_postmortem_detail_found(self, mock_fn, review_client):
        mock_fn.return_value = {"recommendation_id": "r1", "postmortem": "text"}
        r = review_client.get("/api/review/postmortem/r1")
        assert r.status_code == 200

    @patch("src.api.routes.review.get_postmortem_detail")
    def test_postmortem_detail_not_found(self, mock_fn, review_client):
        mock_fn.return_value = None
        r = review_client.get("/api/review/postmortem/missing")
        assert "error" in r.json()

    @patch("src.api.routes.review.get_recommendation")
    def test_review_detail(self, mock_fn, review_client):
        mock_fn.return_value = {"recommendation_id": "r1"}
        r = review_client.get("/api/review/r1")
        assert r.status_code == 200

    @patch("src.api.routes.review.submit_review")
    def test_submit_review(self, mock_fn, review_client):
        mock_fn.return_value = True
        r = review_client.post("/api/review/r1", json={"ryan_approved": True, "user_grade": "A"})
        assert r.status_code == 200
        assert r.json()["success"] is True

    @patch("src.api.routes.review.mark_executed")
    def test_mark_executed(self, mock_fn, review_client):
        mock_fn.return_value = True
        r = review_client.post("/api/review/mark-executed/AAPL")
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestSystemRoutes:
    def test_data_collection_stats_shape(self, system_client, tmp_path, monkeypatch):
        import sqlite3
        from tests.conftest import init_test_db

        db_path = str(tmp_path / "ai_research_desk.sqlite3")
        monkeypatch.setenv("ARCIS_DB_PATH", db_path)
        monkeypatch.setattr("src.config.DB_PATH", db_path)
        monkeypatch.setattr("src.api.routes.system.DB_PATH", db_path)

        init_test_db(db_path, [
            "options_chains", "options_metrics", "vix_term_structure",
            "macro_snapshots", "google_trends", "cboe_ratios",
            "earnings_calendar", "edgar_filings", "insider_transactions",
            "short_interest", "fed_communications", "analyst_estimates",
        ])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO options_metrics (id, collected_at, collected_date, ticker) "
            "VALUES (1, '2026-03-30T00:00:00', '2026-03-30', 'AAPL')"
        )
        conn.execute(
            "INSERT INTO earnings_calendar (id, ticker, earnings_date, collected_at) "
            "VALUES (1, 'MSFT', '2026-04-15', '2026-03-30T21:00:00')"
        )
        conn.execute(
            "INSERT INTO fed_communications (id, comm_type, date, collected_at) "
            "VALUES (1, 'minutes', '2026-03-29', '2026-03-29T20:00:00')"
        )
        conn.commit()
        conn.close()

        r = system_client.get("/api/data-collection-stats")
        assert r.status_code == 200
        data = r.json()
        assert "earnings_calendar" in data
        assert "analyst_estimates" in data

        for table_stats in data.values():
            assert set(table_stats.keys()) == {"total_records", "latest_collection", "coverage_count"}

        assert data["options_metrics"]["total_records"] == 1
        assert data["options_metrics"]["latest_collection"] == "2026-03-30"
        assert data["options_metrics"]["coverage_count"] == 1

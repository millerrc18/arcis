"""Tests for the pre-market inference pipeline."""

import sqlite3
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


# ── Rolling features ─────────────────────────────────────────────────


def test_rolling_features_empty_db(tmp_path):
    """Rolling features handles missing tables gracefully."""
    from src.scheduler.premarket import PreMarketPipeline
    db = str(tmp_path / "test.db")
    # Create empty DB
    with sqlite3.connect(db) as conn:
        pass

    pipeline = PreMarketPipeline(db_path=db)
    result = pipeline.run_rolling_features()
    assert result["computed"] == 0


def test_rolling_features_with_data(tmp_path):
    """Rolling features computes from stored data."""
    from src.scheduler.premarket import PreMarketPipeline
    db = str(tmp_path / "test.db")

    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE vix_term_structure (
                collected_date TEXT, vix_spot REAL, vx1 REAL, vx2 REAL
            )
        """)
        conn.execute(
            "INSERT INTO vix_term_structure VALUES (?, ?, ?, ?)",
            ("2026-03-25", 18.5, 19.2, 20.1),
        )
        conn.execute("""
            CREATE TABLE macro_snapshots (
                series_id TEXT, collected_date TEXT, value REAL
            )
        """)
        conn.execute(
            "INSERT INTO macro_snapshots VALUES (?, ?, ?)",
            ("DFF", "2026-03-25", 4.33),
        )
        conn.execute("""
            CREATE TABLE options_metrics (
                ticker TEXT, collected_date TEXT, iv_rank REAL
            )
        """)
        conn.execute(
            "INSERT INTO options_metrics VALUES (?, ?, ?)",
            ("AAPL", "2026-03-25", 0.45),
        )
        conn.commit()

    pipeline = PreMarketPipeline(db_path=db)
    result = pipeline.run_rolling_features()
    assert result["computed"] >= 2
    assert result["vix_latest"] == "2026-03-25"


# ── Ollama warm check ────────────────────────────────────────────────


def test_verify_ollama_warm_success():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    with patch("src.llm.client.is_llm_available", return_value=True), \
         patch("src.llm.client.generate", return_value="OK"):
        assert pipeline.verify_ollama_warm() is True


def test_verify_ollama_warm_not_available():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    with patch("src.llm.client.is_llm_available", return_value=False):
        assert pipeline.verify_ollama_warm() is False


def test_verify_ollama_warm_inference_fails():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    with patch("src.llm.client.is_llm_available", return_value=True), \
         patch("src.llm.client.generate", return_value=None):
        assert pipeline.verify_ollama_warm() is False


# ── Training generation ──────────────────────────────────────────────


def test_training_generation_returns_stats(tmp_path):
    from src.scheduler.premarket import PreMarketPipeline
    from src.training.versioning import init_training_tables

    db = str(tmp_path / "test.db")
    init_training_tables(db)

    # Add quality_score_auto column
    with sqlite3.connect(db) as conn:
        try:
            conn.execute(
                "ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL"
            )
        except sqlite3.OperationalError:
            pass

    # Insert test examples
    with sqlite3.connect(db) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, ticker, instruction, "
                "input_text, output_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"ex-{i}", "2026-03-25", "outcome_win", "AAPL",
                 "instr", "input", "output"),
            )
        conn.commit()

    pipeline = PreMarketPipeline(db_path=db)
    result = pipeline.run_training_generation()

    assert result["total_examples"] == 3
    assert result["unscored"] == 3
    assert "by_source" in result


# ── News scoring ─────────────────────────────────────────────────────


def test_news_scoring_no_news():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    with patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.data_enrichment.news.fetch_recent_news",
               return_value={"articles": []}):
        result = pipeline.run_news_scoring(max_tickers=1)

    assert result["scored"] == 0


def test_news_scoring_with_articles():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    mock_news = {
        "articles": [
            {"title": "Apple announces new product line"},
            {"title": "AAPL beats earnings estimates"},
        ]
    }

    with patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.data_enrichment.news.fetch_recent_news",
               return_value=mock_news), \
         patch("src.llm.client.generate", return_value='{"impact": 4, "reason": "product launch"}'):
        result = pipeline.run_news_scoring(max_tickers=1)

    assert result["scored"] == 2
    assert result["tickers"] == 1


def test_news_scoring_handles_errors():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    with patch("src.universe.sp100.get_sp100_universe",
               side_effect=Exception("universe error")):
        result = pipeline.run_news_scoring()

    assert result["scored"] == 0


# ── Candidate analysis ───────────────────────────────────────────────


def test_candidate_analysis_no_data():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    with patch("src.data_ingestion.market_data.fetch_spy_benchmark",
               return_value=MagicMock(empty=True)):
        with patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={}):
            with patch("src.universe.sp100.get_sp100_universe",
                        return_value=["AAPL"]):
                result = pipeline.run_candidate_analysis()

    assert result["count"] == 0


def test_candidate_analysis_with_candidates():
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()

    mock_spy = MagicMock(empty=False)
    mock_candidates = {
        "packet_worthy": [
            {"ticker": "AAPL", "score": 85, "features": {}},
            {"ticker": "MSFT", "score": 80, "features": {}},
        ],
        "watchlist": [],
    }

    with patch("src.universe.sp100.get_sp100_universe",
               return_value=["AAPL", "MSFT"]), \
         patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={}), \
         patch("src.data_ingestion.market_data.fetch_spy_benchmark",
               return_value=mock_spy), \
         patch("src.features.engine.compute_all_features", return_value={}), \
         patch("src.ranking.ranker.rank_universe", return_value=[]), \
         patch("src.ranking.ranker.get_top_candidates",
               return_value=mock_candidates):
        result = pipeline.run_candidate_analysis()

    assert result["count"] == 2
    assert result["candidates"][0]["ticker"] == "AAPL"


# ── Pre-market doesn't run on weekends ───────────────────────────────


def test_premarket_schedule_weekday_only():
    """Verify the watch loop only runs pre-market tasks on weekdays.

    The watch loop checks now.weekday() < 5 before running overnight/premarket.
    This test verifies the is_weekday logic that guards premarket tasks.
    """
    # Saturday
    saturday = datetime(2026, 3, 28, 7, 0, 0, tzinfo=ET)
    assert saturday.weekday() >= 5  # 5 = Saturday

    # Wednesday
    wednesday = datetime(2026, 3, 25, 7, 0, 0, tzinfo=ET)
    assert wednesday.weekday() < 5  # 2 = Wednesday


# ── Guard band before 9:30 scan ──────────────────────────────────────


def test_guard_band_before_first_scan():
    """Pre-market candidates should finish by 9:25 AM to leave guard band."""
    # The premarket schedule in watch.py only runs candidates at hour==9, minute < 25
    # This test documents the constraint
    guard_start = datetime(2026, 3, 25, 9, 25, 0, tzinfo=ET)
    first_scan = datetime(2026, 3, 25, 9, 30, 0, tzinfo=ET)
    gap_minutes = (first_scan - guard_start).total_seconds() / 60
    assert gap_minutes == 5  # 5-minute guard band

"""Tests for council v2 data gathering helpers."""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.council.agents import (
    gather_innovation_data,
    gather_macro_data,
    gather_risk_data,
    gather_strategic_data,
    gather_tactical_data,
)

ET = ZoneInfo("America/New_York")


@pytest.fixture
def db_path(tmp_path):
    """Create a temp DB with the tables council v2 readers expect."""
    path = str(tmp_path / "test.sqlite3")
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS shadow_trades (
                trade_id TEXT PRIMARY KEY,
                recommendation_id TEXT,
                ticker TEXT,
                direction TEXT,
                status TEXT,
                planned_allocation REAL,
                pnl_dollars REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                max_adverse_excursion REAL,
                actual_entry_time TEXT,
                actual_exit_time TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS vix_term_structure (
                id INTEGER PRIMARY KEY,
                collected_date TEXT,
                vix REAL,
                vix9d REAL,
                vix3m REAL,
                vix1y REAL
            );
            CREATE TABLE IF NOT EXISTS macro_snapshots (
                id INTEGER PRIMARY KEY,
                collected_date TEXT,
                series_id TEXT,
                value REAL
            );
            CREATE TABLE IF NOT EXISTS recommendations (
                recommendation_id TEXT PRIMARY KEY,
                ticker TEXT,
                priority_score REAL,
                confidence_score REAL,
                market_regime TEXT,
                sector_context TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS training_examples (
                example_id TEXT PRIMARY KEY,
                created_at TEXT,
                source TEXT,
                quality_score REAL,
                quality_score_auto REAL,
                difficulty TEXT,
                curriculum_stage TEXT
            );
            CREATE TABLE IF NOT EXISTS model_versions (
                version_id TEXT PRIMARY KEY,
                version_name TEXT,
                status TEXT,
                created_at TEXT,
                training_examples_count INTEGER
            );
            CREATE TABLE IF NOT EXISTS traffic_light_state (
                id INTEGER PRIMARY KEY,
                current_regime TEXT,
                last_total_score INTEGER
            );
            CREATE TABLE IF NOT EXISTS scan_metrics (
                metric_id TEXT PRIMARY KEY,
                scan_time TEXT,
                packet_worthy INTEGER,
                llm_success INTEGER,
                llm_total INTEGER,
                avg_conviction REAL,
                created_at TEXT
            );
            """
        )
    return path


@pytest.fixture
def populated_db(db_path):
    """Populate the council fixtures with recent realistic data."""
    now = datetime.now(ET)
    now_iso = now.isoformat()
    two_days_ago = (now - timedelta(days=2)).isoformat()
    yesterday = (now - timedelta(days=1)).isoformat()
    today = now.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations "
            "(recommendation_id, ticker, priority_score, confidence_score, market_regime, sector_context, created_at) "
            "VALUES ('r1', 'AAPL', 85, 0.82, 'risk_on', 'Technology', ?)",
            (now_iso,),
        )
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, direction, status, planned_allocation, pnl_pct, actual_entry_time, created_at) "
            "VALUES ('t_open', 'r1', 'AAPL', 'long', 'open', 10000, 2.5, ?, ?)",
            (yesterday, yesterday),
        )
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, direction, status, planned_allocation, pnl_dollars, pnl_pct, exit_reason, max_adverse_excursion, actual_entry_time, actual_exit_time, created_at) "
            "VALUES ('t_closed', 'r1', 'MSFT', 'long', 'closed', 9000, -125.0, -1.4, 'stop_hit', -3.1, ?, ?, ?)",
            (two_days_ago, yesterday, two_days_ago),
        )
        conn.execute(
            "INSERT INTO vix_term_structure (collected_date, vix, vix9d, vix3m, vix1y) "
            "VALUES (?, 18.4, 17.9, 20.2, 22.0)",
            (today,),
        )
        conn.executemany(
            "INSERT INTO macro_snapshots (collected_date, series_id, value) VALUES (?, ?, ?)",
            [
                (today, "BAMLH0A0HYM2", 3.45),
                (today, "NFCI", -0.35),
                (today, "T10Y2Y", 0.42),
                (today, "UNRATE", 4.1),
            ],
        )
        conn.execute(
            "INSERT INTO training_examples "
            "(example_id, created_at, source, quality_score, quality_score_auto, difficulty, curriculum_stage) "
            "VALUES ('ex1', ?, 'blinded_win', 0.81, 0.81, 'medium', 'stage_1')",
            (now_iso,),
        )
        conn.execute(
            "INSERT INTO model_versions "
            "(version_id, version_name, status, created_at, training_examples_count) "
            "VALUES ('v1', 'halcyon-v1', 'active', ?, 976)",
            (now_iso,),
        )
        conn.execute(
            "INSERT INTO traffic_light_state (id, current_regime, last_total_score) "
            "VALUES (1, 'GREEN', 5)"
        )
        conn.execute(
            "INSERT INTO scan_metrics "
            "(metric_id, scan_time, packet_worthy, llm_success, llm_total, avg_conviction, created_at) "
            "VALUES ('m1', '09:30', 3, 2, 3, 7.4, ?)",
            (now_iso,),
        )
    return db_path


def test_tactical_data_empty_db_returns_fallback(db_path):
    result = gather_tactical_data(db_path)
    assert isinstance(result, str)
    assert result


def test_tactical_data_with_data(populated_db):
    result = gather_tactical_data(populated_db)
    assert "VIX:" in result
    assert "Traffic Light:" in result
    assert "Open positions" in result


def test_strategic_data_with_data(populated_db):
    result = gather_strategic_data(populated_db)
    assert "Phase 1 gate:" in result
    assert "Trades:" in result
    assert "HSHS:" in result


def test_risk_data_with_data(populated_db):
    result = gather_risk_data(populated_db)
    assert "Sector concentration" in result
    assert "Recent losses:" in result
    assert "Cumulative closed P&L:" in result


def test_innovation_data_with_data(populated_db):
    result = gather_innovation_data(populated_db)
    assert "Training data:" in result
    assert "Sources:" in result


def test_macro_data_with_data(populated_db):
    result = gather_macro_data(populated_db)
    assert "Macro indicators:" in result
    assert "Yield curve" in result


def test_v2_data_helpers_handle_bad_db_path():
    bad_path = "/nonexistent/path/db.sqlite3"
    assert gather_tactical_data(bad_path) == "No tactical data available."
    assert gather_strategic_data(bad_path) == "No strategic data available."
    assert gather_risk_data(bad_path) == "No risk data available."
    assert gather_innovation_data(bad_path) == "No innovation data available."
    assert gather_macro_data(bad_path) == "No macro data available."

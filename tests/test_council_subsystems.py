"""Tests for council v2 subsystems — agent data, value tracker, rate limiter, parsing.

Restores coverage dropped during Codex PR #64 refactoring (53 → 11 tests).
These tests cover the modules that have ZERO test coverage currently.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.council.agents import AGENT_NAMES, AGENT_DATA_FUNCTIONS
from src.council.agent_data import (
    gather_tactical_data,
    gather_strategic_data,
    gather_risk_data,
    gather_innovation_data,
    gather_macro_data,
)
from src.council.engine import init_council_tables
from src.council.parsing import default_response, parse_agent_response
from src.council.rate_limiter import _clip_to_bounds, apply_rate_limiters
from src.council.value_tracker import (
    init_value_tables,
    get_current_parameters,
    log_parameter_change,
    compute_attribution,
    get_rolling_value_summary,
)

ET = ZoneInfo("America/New_York")


@pytest.fixture
def populated_db(tmp_path):
    """DB with data in all tables that council agents query."""
    db_path = str(tmp_path / "test_subsystems.sqlite3")
    from tests.conftest import init_test_db
    init_test_db(db_path)  # create all tables from registry
    init_council_tables(db_path)
    init_value_tables(db_path)

    now = datetime.now(ET)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    with sqlite3.connect(db_path) as conn:

        conn.execute(
            "INSERT INTO vix_term_structure (collected_at, collected_date, vix, vix9d, vix3m, vix1y) "
            "VALUES (?, ?, 18.5, 16.0, 20.1, 22.0)", (now_iso, today)
        )
        conn.execute(
            "INSERT INTO traffic_light_state (id, current_regime, last_total_score) "
            "VALUES (1, 'GREEN', 4)"
        )
        conn.execute(
            "INSERT INTO scan_metrics (scan_time, packet_worthy, llm_success, llm_total, avg_conviction, created_at) "
            "VALUES ('09:30', 3, 2, 3, 7.5, ?)", (now_iso,)
        )

        rec_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO recommendations (recommendation_id, created_at, ticker, sector_context) "
            "VALUES (?, ?, 'AAPL', 'Technology')", (rec_id, now_iso)
        )
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, planned_allocation, "
            "actual_entry_time, pnl_pct, pnl_dollars, created_at, updated_at) "
            "VALUES (?, ?, 'AAPL', 'open', 10000, ?, NULL, NULL, ?, ?)",
            (str(uuid.uuid4()), rec_id, yesterday, yesterday, yesterday)
        )
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, planned_allocation, "
            "actual_entry_time, actual_exit_time, pnl_pct, pnl_dollars, exit_reason, "
            "max_adverse_excursion, created_at, updated_at) "
            "VALUES (?, ?, 'MSFT', 'closed', 9000, ?, ?, 2.1, 189.0, 'target_hit', -1.5, ?, ?)",
            (str(uuid.uuid4()), rec_id, week_ago, yesterday, week_ago, yesterday)
        )

        conn.execute(
            "INSERT INTO training_examples (example_id, created_at, quality_score, source, "
            "curriculum_stage, instruction, input_text, output_text) "
            "VALUES ('ex1', ?, 22.0, 'blinded_win', 'stage_2', 'evaluate', 'input', 'output')", (now_iso,)
        )
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) VALUES ('v1', 'halcyon-v1.0.0', 'released', ?)", (now_iso,)
        )
        conn.executemany(
            "INSERT INTO macro_snapshots (series_id, series_name, collected_date, collected_at, value) VALUES (?, ?, ?, ?, ?)",
            [("DFF", "Fed Funds Rate", today, now_iso, 5.25),
             ("T10Y2Y", "10Y-2Y Spread", today, now_iso, 0.42),
             ("T10Y3M", "10Y-3M Spread", today, now_iso, 0.15),
             ("BAMLH0A0HYM2", "HY Spread", today, now_iso, 3.8),
             ("UNRATE", "Unemployment", today, now_iso, 4.1)],
        )

    return db_path


@pytest.fixture
def empty_db(tmp_path):
    """DB with tables but no data."""
    db_path = str(tmp_path / "test_empty.sqlite3")
    init_council_tables(db_path)
    init_value_tables(db_path)
    return db_path


# ══════════════════════════════════════════════════════════
# AGENT DATA GATHERING TESTS
# ══════════════════════════════════════════════════════════

class TestAgentDataGathering:
    """Each gather function must return a non-empty string and never raise."""

    def test_agent_names_count(self):
        assert len(AGENT_NAMES) == 5

    def test_agent_data_functions_match_names(self):
        assert set(AGENT_DATA_FUNCTIONS.keys()) == set(AGENT_NAMES)

    def test_tactical_returns_string_on_populated_db(self, populated_db):
        result = gather_tactical_data(populated_db)
        assert isinstance(result, str)
        assert len(result) > 20
        assert "VIX" in result or "vix" in result.lower()

    def test_strategic_returns_string_on_populated_db(self, populated_db):
        result = gather_strategic_data(populated_db)
        assert isinstance(result, str)
        assert len(result) > 20

    def test_risk_returns_string_on_populated_db(self, populated_db):
        result = gather_risk_data(populated_db)
        assert isinstance(result, str)
        assert len(result) > 20

    def test_innovation_returns_string_on_populated_db(self, populated_db):
        result = gather_innovation_data(populated_db)
        assert isinstance(result, str)
        assert len(result) > 20

    def test_macro_returns_string_on_populated_db(self, populated_db):
        result = gather_macro_data(populated_db)
        assert isinstance(result, str)
        assert len(result) > 20

    def test_tactical_returns_fallback_on_empty_db(self, empty_db):
        result = gather_tactical_data(empty_db)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_strategic_returns_fallback_on_empty_db(self, empty_db):
        result = gather_strategic_data(empty_db)
        assert isinstance(result, str)

    def test_risk_returns_fallback_on_empty_db(self, empty_db):
        result = gather_risk_data(empty_db)
        assert isinstance(result, str)

    def test_innovation_returns_fallback_on_empty_db(self, empty_db):
        result = gather_innovation_data(empty_db)
        assert isinstance(result, str)

    def test_macro_returns_fallback_on_empty_db(self, empty_db):
        result = gather_macro_data(empty_db)
        assert isinstance(result, str)

    def test_all_gather_functions_never_raise_on_bad_path(self):
        bad_path = "/nonexistent/path/db.sqlite3"
        for name, func in AGENT_DATA_FUNCTIONS.items():
            result = func(bad_path)
            assert isinstance(result, str), f"{name} raised or returned non-string on bad path"

    def test_tactical_includes_vix_data(self, populated_db):
        result = gather_tactical_data(populated_db)
        assert "18.5" in result or "VIX" in result

    def test_macro_includes_indicators(self, populated_db):
        result = gather_macro_data(populated_db)
        # Should mention at least one of the macro series
        has_data = any(term in result for term in ["5.25", "0.42", "3.8", "4.1", "Yield", "HY", "Fed", "Unemployment"])
        assert has_data, f"Macro data missing indicators: {result[:200]}"


# ══════════════════════════════════════════════════════════
# PARSING EDGE CASES
# ══════════════════════════════════════════════════════════

class TestParsing:

    def test_default_response_has_all_required_fields(self):
        resp = default_response("test_agent")
        assert resp["agent"] == "test_agent"
        assert resp["direction"] == "neutral"
        assert resp["confidence"] == 0.1
        assert "parameters" in resp
        assert "position_sizing_multiplier" in resp["parameters"]
        assert resp["vote"] == "hold_steady"

    def test_parse_valid_json(self):
        raw = json.dumps({
            "agent": "tactical_operator",
            "direction": "bullish",
            "confidence": 0.85,
            "parameters": {
                "position_sizing_multiplier": 1.1,
                "cash_reserve_target_pct": 15,
                "scan_aggressiveness": "normal",
            },
            "key_reasoning": "Strong pullback setup.",
            "key_risk": "Fed surprise.",
        })
        parsed = parse_agent_response(raw, "tactical_operator")
        assert parsed["direction"] == "bullish"
        assert parsed["confidence"] == 0.85
        assert parsed["vote"] == "increase_exposure"

    def test_parse_code_fenced_json(self):
        inner = json.dumps({"agent": "red_team", "direction": "bearish", "confidence": 0.7,
                            "parameters": {"position_sizing_multiplier": 0.8,
                                           "cash_reserve_target_pct": 25,
                                           "scan_aggressiveness": "conservative"}})
        raw = f"```json\n{inner}\n```"
        parsed = parse_agent_response(raw, "red_team")
        assert parsed["direction"] == "bearish"
        assert parsed["vote"] == "reduce_exposure"

    def test_parse_none_returns_default(self):
        parsed = parse_agent_response(None, "macro_navigator")
        assert parsed["direction"] == "neutral"
        assert parsed["confidence"] == 0.1

    def test_parse_garbage_returns_default(self):
        parsed = parse_agent_response("This is not JSON at all!", "innovation_engine")
        assert parsed["direction"] == "neutral"
        assert parsed["confidence"] == 0.1

    def test_parse_confidence_over_1_clamped(self):
        raw = json.dumps({"agent": "test", "direction": "bullish", "confidence": 8,
                          "parameters": {"position_sizing_multiplier": 1.0,
                                         "cash_reserve_target_pct": 15,
                                         "scan_aggressiveness": "normal"}})
        parsed = parse_agent_response(raw, "test")
        assert parsed["confidence"] <= 1.0

    def test_parse_old_schema_position_converted(self):
        raw = json.dumps({"agent": "test", "position": "offensive", "confidence": 8,
                          "parameters": {"position_sizing_multiplier": 1.0,
                                         "cash_reserve_target_pct": 15,
                                         "scan_aggressiveness": "normal"}})
        parsed = parse_agent_response(raw, "test")
        assert parsed["direction"] in ("bullish", "neutral", "bearish")

    def test_parse_missing_direction_defaults_neutral(self):
        raw = json.dumps({"agent": "test", "confidence": 0.5,
                          "parameters": {"position_sizing_multiplier": 1.0,
                                         "cash_reserve_target_pct": 15,
                                         "scan_aggressiveness": "normal"}})
        parsed = parse_agent_response(raw, "test")
        assert parsed["direction"] == "neutral"


# ══════════════════════════════════════════════════════════
# RATE LIMITER TESTS
# ══════════════════════════════════════════════════════════

class TestRateLimiter:

    def test_clip_to_bounds_sizing_floor(self):
        assert _clip_to_bounds("position_sizing_multiplier", 0.1) == 0.25

    def test_clip_to_bounds_sizing_ceiling(self):
        assert _clip_to_bounds("position_sizing_multiplier", 2.0) == 1.5

    def test_clip_to_bounds_within_range(self):
        assert _clip_to_bounds("position_sizing_multiplier", 1.0) == 1.0

    def test_clip_to_bounds_cash_reserve_floor(self):
        assert _clip_to_bounds("cash_reserve_target_pct", 5) == 10

    def test_clip_to_bounds_cash_reserve_ceiling(self):
        assert _clip_to_bounds("cash_reserve_target_pct", 60) == 50

    def test_apply_rate_limiters_small_change_not_clipped(self, empty_db):
        recommended = {"position_sizing_multiplier": 1.1, "cash_reserve_target_pct": 18}
        current = {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15}
        applied = apply_rate_limiters(recommended, current, empty_db)
        assert applied["position_sizing_multiplier"] == 1.1

    def test_apply_rate_limiters_large_change_clipped(self, empty_db):
        recommended = {"position_sizing_multiplier": 1.5, "cash_reserve_target_pct": 15}
        current = {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15}
        applied = apply_rate_limiters(recommended, current, empty_db)
        # 25% daily max: 1.0 * 1.25 = 1.25 max
        assert applied["position_sizing_multiplier"] <= 1.25


# ══════════════════════════════════════════════════════════
# VALUE TRACKER TESTS
# ══════════════════════════════════════════════════════════

class TestValueTracker:

    def test_get_current_parameters_returns_defaults_on_empty(self, empty_db):
        params = get_current_parameters(empty_db)
        assert "position_sizing_multiplier" in params
        assert "cash_reserve_target_pct" in params
        assert params["position_sizing_multiplier"] == 1.0

    def test_log_parameter_change_stores_entry(self, empty_db):
        log_id = log_parameter_change(
            session_id="test-session",
            parameter_name="position_sizing_multiplier",
            default_value=1.0,
            council_value=1.2,
            applied_value=1.15,
            db_path=empty_db,
        )
        assert log_id

        with sqlite3.connect(empty_db) as conn:
            row = conn.execute(
                "SELECT * FROM council_parameter_log WHERE log_id = ?", (log_id,)
            ).fetchone()
            assert row is not None

    def test_log_parameter_change_closes_previous_window(self, empty_db):
        log_parameter_change("s1", "position_sizing_multiplier", 1.0, 1.1, 1.1, db_path=empty_db)
        log_parameter_change("s2", "position_sizing_multiplier", 1.0, 1.2, 1.2, db_path=empty_db)

        with sqlite3.connect(empty_db) as conn:
            open_windows = conn.execute(
                "SELECT COUNT(*) FROM council_parameter_log "
                "WHERE parameter_name = 'position_sizing_multiplier' AND attribution_end IS NULL"
            ).fetchone()[0]
            assert open_windows == 1  # Only the latest window is open

    def test_log_parameter_change_updates_state(self, empty_db):
        log_parameter_change("s1", "position_sizing_multiplier", 1.0, 1.3, 1.2, db_path=empty_db)
        params = get_current_parameters(empty_db)
        assert params["position_sizing_multiplier"] == 1.2

    def test_compute_attribution_returns_dict(self, empty_db):
        result = compute_attribution(empty_db)
        assert isinstance(result, dict)
        assert "total_value_added" in result
        assert "windows_computed" in result

    def test_rolling_summary_returns_full_authority_on_empty(self, empty_db):
        summary = get_rolling_value_summary(30, empty_db)
        assert summary["authority_status"] == "full"
        assert summary["weeks_negative"] == 0

    def test_rolling_summary_structure(self, empty_db):
        summary = get_rolling_value_summary(30, empty_db)
        assert "period_days" in summary
        assert "total_value_added" in summary
        assert "per_parameter" in summary
        assert "per_agent" in summary
        assert "authority_status" in summary

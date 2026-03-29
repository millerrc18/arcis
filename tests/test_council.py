"""Council v2 tests — vote-first protocol with 5 analytical-lens agents."""
import json
import os
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def council_db(tmp_path):
    """Create a temporary database with all required tables populated."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)

    # Create ALL tables that gather functions query
    conn.executescript("""
        CREATE TABLE vix_term_structure (date TEXT, vix_close REAL, vix9d REAL, vix3m REAL);
        CREATE TABLE traffic_light_state (id INTEGER PRIMARY KEY, current_regime TEXT, last_total_score REAL);
        CREATE TABLE scan_metrics (created_at TEXT, scan_time TEXT, packet_worthy INTEGER,
            llm_success INTEGER, llm_total INTEGER, avg_conviction REAL);
        CREATE TABLE shadow_trades (trade_id TEXT, ticker TEXT, status TEXT, pnl_pct REAL,
            pnl_dollars REAL, sector TEXT, actual_entry_time TEXT, actual_exit_time TEXT,
            exit_reason TEXT, planned_allocation REAL, signal_price REAL,
            implementation_shortfall_bps REAL, max_adverse_excursion REAL,
            strategy_type TEXT DEFAULT 'pullback');
        CREATE TABLE training_examples (example_id TEXT, created_at TEXT, quality_score REAL,
            quality_score_auto REAL, source TEXT, difficulty TEXT, curriculum_stage TEXT);
        CREATE TABLE model_versions (version_id TEXT, created_at TEXT);
        CREATE TABLE macro_snapshots (series_id TEXT, date TEXT, value REAL);
        CREATE TABLE recommendations (
            recommendation_id TEXT, created_at TEXT, priority_score REAL,
            ticker TEXT
        );

        -- Populate with realistic test data
        INSERT INTO vix_term_structure VALUES ('2026-03-28', 18.5, 17.2, 20.1);
        INSERT INTO traffic_light_state VALUES (1, 'GREEN', 5.0);
        INSERT INTO scan_metrics VALUES (datetime('now'), '2026-03-28 10:00', 3, 8, 10, 6.5);
        INSERT INTO shadow_trades VALUES ('t1', 'AAPL', 'open', 1.5, 150, 'Technology',
            datetime('now', '-3 days'), NULL, NULL, 5000, 175.0, NULL, NULL, 'pullback');
        INSERT INTO shadow_trades VALUES ('t2', 'XOM', 'closed', -0.8, -80, 'Energy',
            datetime('now', '-10 days'), datetime('now', '-5 days'), 'stop_loss',
            5000, 110.0, 5.2, -2.1, 'pullback');
        INSERT INTO training_examples VALUES ('ex1', datetime('now'), 22.0, 20.0, 'live', 'medium', 'evidence');
        INSERT INTO macro_snapshots VALUES ('DFF', '2026-03-28', 4.50);
        INSERT INTO macro_snapshots VALUES ('T10Y2Y', '2026-03-28', 0.35);
        INSERT INTO macro_snapshots VALUES ('BAMLH0A0HYM2', '2026-03-28', 3.80);
        INSERT INTO model_versions VALUES ('v1', datetime('now'));
        INSERT INTO recommendations VALUES ('r1', datetime('now', '-1 hour'), 85.0, 'AAPL');
    """)
    conn.commit()
    conn.close()
    return db_path


def _make_v2_response(agent_name, direction="bullish", confidence=0.8):
    """Build a mock v2 agent response JSON string."""
    return json.dumps({
        "agent": agent_name,
        "direction": direction,
        "confidence": confidence,
        "parameters": {
            "position_sizing_multiplier": 1.0,
            "cash_reserve_target_pct": 15,
            "scan_aggressiveness": "normal",
        },
        "sector_tilts": {"prefer": [], "avoid": []},
        "key_reasoning": f"Mock analysis from {agent_name}",
        "key_risk": "Test risk",
        "falsifiable_prediction": {
            "claim": "SPY above 550 by April 10",
            "confidence": 0.7,
            "verification_date": "2026-04-10",
        },
    })


# ── agents.py tests ───────────────────────────────────────────


class TestAgents:
    def test_agent_names_has_5_entries(self):
        from src.council.agents import AGENT_NAMES
        assert len(AGENT_NAMES) == 5

    def test_agent_names_correct(self):
        from src.council.agents import AGENT_NAMES
        expected = {"tactical_operator", "strategic_architect", "red_team",
                    "innovation_engine", "macro_navigator"}
        assert set(AGENT_NAMES) == expected

    def test_agent_data_functions_match_names(self):
        from src.council.agents import AGENT_NAMES, AGENT_DATA_FUNCTIONS
        assert set(AGENT_DATA_FUNCTIONS.keys()) == set(AGENT_NAMES)

    def test_agent_prompts_match_names(self):
        from src.council.agents import AGENT_NAMES, AGENT_PROMPTS
        assert set(AGENT_PROMPTS.keys()) == set(AGENT_NAMES)

    def test_tactical_returns_string(self, council_db):
        from src.council.agents import gather_tactical_data
        result = gather_tactical_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_strategic_returns_string(self, council_db):
        from src.council.agents import gather_strategic_data
        result = gather_strategic_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_risk_returns_string(self, council_db):
        from src.council.agents import gather_risk_data
        result = gather_risk_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_innovation_returns_string(self, council_db):
        from src.council.agents import gather_innovation_data
        result = gather_innovation_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_macro_returns_string(self, council_db):
        from src.council.agents import gather_macro_data
        result = gather_macro_data(db_path=council_db)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_all_gather_functions_handle_empty_db(self, tmp_path):
        from src.council.agents import AGENT_DATA_FUNCTIONS
        empty_db = str(tmp_path / "empty.sqlite3")
        sqlite3.connect(empty_db).close()
        for name, fn in AGENT_DATA_FUNCTIONS.items():
            result = fn(db_path=empty_db)
            assert isinstance(result, str), f"{name} didn't return string on empty DB"

    def test_all_gather_functions_never_raise(self, tmp_path):
        from src.council.agents import AGENT_DATA_FUNCTIONS
        bad_db = str(tmp_path / "nonexistent" / "bad.sqlite3")
        for name, fn in AGENT_DATA_FUNCTIONS.items():
            result = fn(db_path=bad_db)
            assert isinstance(result, str), f"{name} raised or didn't return string"

    def test_query_db_helper(self, council_db):
        from src.council.agents import _query_db
        rows = _query_db("SELECT COUNT(*) as n FROM shadow_trades", db_path=council_db)
        assert rows[0]["n"] == 2

    def test_tactical_data_contains_vix(self, council_db):
        from src.council.agents import gather_tactical_data
        result = gather_tactical_data(db_path=council_db)
        assert "VIX" in result

    def test_tactical_data_contains_traffic_light(self, council_db):
        from src.council.agents import gather_tactical_data
        result = gather_tactical_data(db_path=council_db)
        assert "GREEN" in result

    def test_strategic_data_contains_trades(self, council_db):
        from src.council.agents import gather_strategic_data
        result = gather_strategic_data(db_path=council_db)
        assert "closed" in result.lower() or "Trades" in result

    def test_risk_data_contains_sector(self, council_db):
        from src.council.agents import gather_risk_data
        result = gather_risk_data(db_path=council_db)
        # Should mention Technology since we have an open AAPL trade
        assert "Technology" in result

    def test_macro_data_contains_indicators(self, council_db):
        from src.council.agents import gather_macro_data
        result = gather_macro_data(db_path=council_db)
        assert "Fed Funds" in result or "DFF" in result or "4.50" in result


# ── protocol.py tests ─────────────────────────────────────────


class TestProtocol:
    def test_parse_valid_json(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({
            "agent": "tactical_operator",
            "direction": "bullish",
            "confidence": 0.8,
            "parameters": {
                "position_sizing_multiplier": 1.0,
                "cash_reserve_target_pct": 15,
                "scan_aggressiveness": "normal",
            },
            "key_reasoning": "Market looks strong",
            "key_risk": "VIX spike",
            "falsifiable_prediction": {
                "claim": "SPY above 550 by April 10",
                "confidence": 0.7,
                "verification_date": "2026-04-10",
            },
        })
        result = _parse_agent_response(raw, "tactical_operator")
        assert result["direction"] == "bullish"
        assert result["confidence"] == 0.8
        assert result.get("_parse_failed") is not True

    def test_parse_code_fenced_json(self):
        from src.council.protocol import _parse_agent_response
        raw = '```json\n{"agent": "red_team", "direction": "bearish", "confidence": 0.6, "key_reasoning": "Risk", "key_risk": "Gap down"}\n```'
        result = _parse_agent_response(raw, "red_team")
        assert result["direction"] == "bearish"

    def test_parse_json_in_prose(self):
        from src.council.protocol import _parse_agent_response
        raw = 'Here is my assessment: {"agent": "macro_navigator", "direction": "neutral", "confidence": 0.5, "key_reasoning": "Mixed signals", "key_risk": "Unclear"} That is all.'
        result = _parse_agent_response(raw, "macro_navigator")
        assert result["direction"] == "neutral"

    def test_parse_old_schema_autoconvert(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({
            "agent": "tactical_operator",
            "position": "offensive",
            "confidence": 8,
            "recommendation": "Buy",
            "key_data_points": [],
            "risk_flags": [],
        })
        result = _parse_agent_response(raw, "tactical_operator")
        # Old confidence 8 (1-10) should convert to 0.8 (0.0-1.0)
        assert 0.7 <= result["confidence"] <= 0.9

    def test_parse_old_position_maps_to_direction(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({"position": "defensive", "confidence": 5})
        result = _parse_agent_response(raw, "red_team")
        assert result["direction"] == "bearish"

    def test_parse_garbage_returns_default(self):
        from src.council.protocol import _parse_agent_response
        result = _parse_agent_response("This is not JSON at all", "red_team")
        assert result.get("_parse_failed") is True
        assert result["agent"] == "red_team"
        assert result["direction"] == "neutral"

    def test_parse_none_returns_default(self):
        from src.council.protocol import _parse_agent_response
        result = _parse_agent_response(None, "tactical_operator")
        assert result.get("_parse_failed") is True
        assert result["direction"] == "neutral"
        assert result["confidence"] == 0.1

    def test_parse_defaults_parameters(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({"direction": "bullish", "confidence": 0.7})
        result = _parse_agent_response(raw, "test")
        assert result["parameters"]["position_sizing_multiplier"] == 1.0
        assert result["parameters"]["cash_reserve_target_pct"] == 15
        assert result["parameters"]["scan_aggressiveness"] == "normal"

    def test_parse_backward_compat_fields(self):
        from src.council.protocol import _parse_agent_response
        raw = json.dumps({"direction": "bullish", "confidence": 0.8, "key_reasoning": "Good"})
        result = _parse_agent_response(raw, "test")
        assert result["position"] == "offensive"
        assert result["confidence_int"] == 8
        assert result["vote"] == "increase_exposure"

    def test_aggregate_5_bullish_consensus(self):
        from src.council.protocol import aggregate_votes
        votes = [
            {
                "agent": f"agent_{i}",
                "direction": "bullish",
                "confidence": 0.8,
                "parameters": {
                    "position_sizing_multiplier": 1.1,
                    "cash_reserve_target_pct": 15,
                    "scan_aggressiveness": "normal",
                },
            }
            for i in range(5)
        ]
        result = aggregate_votes(votes, "daily")
        assert result["consensus_reached"] is True
        assert result["round2_needed"] is False
        assert result["direction"] == "bullish"

    def test_aggregate_split_needs_round2(self):
        from src.council.protocol import aggregate_votes
        votes = [
            {"agent": "a1", "direction": "bullish", "confidence": 0.8, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}},
            {"agent": "a2", "direction": "bullish", "confidence": 0.7, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}},
            {"agent": "a3", "direction": "bearish", "confidence": 0.8, "parameters": {"position_sizing_multiplier": 0.5, "cash_reserve_target_pct": 30, "scan_aggressiveness": "conservative"}},
            {"agent": "a4", "direction": "bearish", "confidence": 0.7, "parameters": {"position_sizing_multiplier": 0.5, "cash_reserve_target_pct": 30, "scan_aggressiveness": "conservative"}},
            {"agent": "a5", "direction": "neutral", "confidence": 0.5, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 20, "scan_aggressiveness": "normal"}},
        ]
        result = aggregate_votes(votes, "daily")
        assert result["round2_needed"] is True

    def test_aggregate_3_2_is_consensus(self):
        from src.council.protocol import aggregate_votes
        votes = [
            {"agent": f"a{i}", "direction": "bullish", "confidence": 0.8, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}}
            for i in range(3)
        ] + [
            {"agent": f"b{i}", "direction": "bearish", "confidence": 0.6, "parameters": {"position_sizing_multiplier": 0.5, "cash_reserve_target_pct": 25, "scan_aggressiveness": "conservative"}}
            for i in range(2)
        ]
        result = aggregate_votes(votes, "daily")
        assert result["consensus_reached"] is True
        assert result["direction"] == "bullish"

    def test_aggregate_all_neutral(self):
        from src.council.protocol import aggregate_votes
        votes = [
            {"agent": f"a{i}", "direction": "neutral", "confidence": 0.5, "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 20, "scan_aggressiveness": "normal"}}
            for i in range(5)
        ]
        result = aggregate_votes(votes, "daily")
        assert result["consensus_reached"] is True
        assert result["direction"] == "neutral"

    def test_aggregate_empty(self):
        from src.council.protocol import aggregate_votes
        result = aggregate_votes([], "daily")
        assert result["direction"] == "neutral"

    def test_rate_limiter_clips_large_change(self):
        from src.council.protocol import apply_rate_limiters
        recommended = {"position_sizing_multiplier": 0.3, "cash_reserve_target_pct": 40}
        current = {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15}
        result = apply_rate_limiters(recommended, current)
        # Can't drop more than 25% daily
        assert result["position_sizing_multiplier"] >= 0.75

    def test_rate_limiter_small_change_passes(self):
        from src.council.protocol import apply_rate_limiters
        recommended = {"position_sizing_multiplier": 0.9, "cash_reserve_target_pct": 18}
        current = {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15}
        result = apply_rate_limiters(recommended, current)
        assert result["position_sizing_multiplier"] == 0.9

    def test_rate_limiter_scan_aggressiveness_passthrough(self):
        from src.council.protocol import apply_rate_limiters
        recommended = {"scan_aggressiveness": "aggressive"}
        current = {"scan_aggressiveness": "normal"}
        result = apply_rate_limiters(recommended, current)
        assert result["scan_aggressiveness"] == "aggressive"

    def test_tally_votes_backward_compat(self):
        from src.council.protocol import tally_votes
        votes = [
            {"agent": "a1", "direction": "bullish", "confidence": 0.8,
             "parameters": {"position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 15, "scan_aggressiveness": "normal"}}
        ]
        result = tally_votes(votes)
        assert "consensus" in result
        assert "_v2" in result

    def test_domain_weights_exist_for_all_types(self):
        from src.council.protocol import DOMAIN_WEIGHTS
        for session_type in ("daily", "weekly", "monthly", "strategic"):
            assert session_type in DOMAIN_WEIGHTS
            assert len(DOMAIN_WEIGHTS[session_type]) == 5

    def test_parameter_bounds_enforced(self):
        from src.council.protocol import apply_rate_limiters
        # Trying to go above upper bound
        recommended = {"position_sizing_multiplier": 5.0}
        current = {"position_sizing_multiplier": 1.5}
        result = apply_rate_limiters(recommended, current)
        assert result["position_sizing_multiplier"] <= 1.5


# ── engine.py tests ───────────────────────────────────────────


class TestEngine:
    def test_init_creates_tables(self, council_db):
        from src.council.engine import init_council_tables
        init_council_tables(council_db)
        conn = sqlite3.connect(council_db)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'council%'"
            ).fetchall()
        ]
        assert "council_sessions" in tables
        assert "council_votes" in tables
        assert "council_calibrations" in tables
        assert "council_debug_log" in tables

    def test_init_adds_v2_columns(self, council_db):
        from src.council.engine import init_council_tables
        init_council_tables(council_db)
        conn = sqlite3.connect(council_db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(council_votes)").fetchall()]
        assert "direction" in cols
        assert "confidence_float" in cols
        assert "assessment_json" in cols
        cols2 = [r[1] for r in conn.execute("PRAGMA table_info(council_sessions)").fetchall()]
        assert "result_json" in cols2

    def test_cost_estimation(self):
        from src.council.engine import _estimate_session_cost
        cost_1 = _estimate_session_cost(1)
        cost_2 = _estimate_session_cost(2)
        assert cost_2 > cost_1
        assert cost_1 > 0

    def test_cost_estimation_zero_rounds(self):
        from src.council.engine import _estimate_session_cost
        assert _estimate_session_cost(0) == 0

    def test_council_engine_init(self, council_db):
        from src.council.engine import CouncilEngine
        engine = CouncilEngine(db_path=council_db)
        assert engine.db_path == council_db

    def test_get_session_returns_none_for_missing(self, council_db):
        from src.council.engine import CouncilEngine
        engine = CouncilEngine(db_path=council_db)
        assert engine.get_session("nonexistent-id") is None

    def test_get_recent_sessions_empty(self, council_db):
        from src.council.engine import CouncilEngine
        engine = CouncilEngine(db_path=council_db)
        sessions = engine.get_recent_sessions()
        assert sessions == []


# ── value_tracker.py tests ────────────────────────────────────


class TestValueTracker:
    def test_get_current_parameters_defaults_on_empty(self, council_db):
        from src.council.value_tracker import get_current_parameters, init_value_tables
        init_value_tables(council_db)
        params = get_current_parameters(council_db)
        assert "position_sizing_multiplier" in params
        assert params["position_sizing_multiplier"] == 1.0

    def test_log_parameter_change(self, council_db):
        from src.council.value_tracker import log_parameter_change, init_value_tables
        init_value_tables(council_db)
        log_id = log_parameter_change(
            session_id="test-session",
            parameter_name="position_sizing_multiplier",
            default_value=1.0,
            council_value=0.8,
            applied_value=0.85,
            rate_limited=True,
            db_path=council_db,
        )
        assert log_id  # non-empty string

        conn = sqlite3.connect(council_db)
        row = conn.execute(
            "SELECT * FROM council_parameter_log WHERE log_id = ?", (log_id,)
        ).fetchone()
        assert row is not None

    def test_log_parameter_updates_state(self, council_db):
        from src.council.value_tracker import log_parameter_change, get_current_parameters, init_value_tables
        init_value_tables(council_db)
        log_parameter_change(
            session_id="test-session",
            parameter_name="position_sizing_multiplier",
            default_value=1.0,
            council_value=0.8,
            applied_value=0.85,
            db_path=council_db,
        )
        params = get_current_parameters(council_db)
        assert params["position_sizing_multiplier"] == 0.85

    def test_rolling_summary_empty_db(self, council_db):
        from src.council.value_tracker import get_rolling_value_summary, init_value_tables
        init_value_tables(council_db)
        summary = get_rolling_value_summary(db_path=council_db)
        assert summary["authority_status"] == "full"
        assert summary["total_value_added"] == 0.0

    def test_init_value_tables_idempotent(self, council_db):
        from src.council.value_tracker import init_value_tables
        init_value_tables(council_db)
        init_value_tables(council_db)  # Should not raise

    def test_compute_attribution_empty(self, council_db):
        from src.council.value_tracker import compute_attribution, init_value_tables
        init_value_tables(council_db)
        result = compute_attribution(council_db)
        assert result["total_value_added"] == 0.0
        assert result["windows_computed"] == 0


# ── Integration: Round 1 with mocked Claude ──────────────────


class TestRound1Integration:
    @patch("src.council.protocol._call_claude")
    def test_round_1_produces_5_assessments(self, mock_claude, council_db):
        from src.council.protocol import run_round_1, build_shared_context
        mock_claude.return_value = (_make_v2_response("test"), {"latency_ms": 100, "raw": "test"})
        context = build_shared_context(council_db)
        assessments = run_round_1(context, db_path=council_db)
        assert len(assessments) == 5

    @patch("src.council.protocol._call_claude")
    def test_round_1_handles_api_failure(self, mock_claude, council_db):
        from src.council.protocol import run_round_1, build_shared_context
        mock_claude.return_value = (None, {"latency_ms": 0, "raw": None})
        context = build_shared_context(council_db)
        assessments = run_round_1(context, db_path=council_db)
        assert len(assessments) == 5
        for a in assessments:
            assert a["direction"] == "neutral"
            assert a["confidence"] == 0.1

    @patch("src.council.protocol._call_claude")
    def test_round_1_handles_malformed_json(self, mock_claude, council_db):
        from src.council.protocol import run_round_1, build_shared_context
        mock_claude.return_value = ("This is not valid JSON at all {{{}", {"latency_ms": 50, "raw": "garbage"})
        context = build_shared_context(council_db)
        assessments = run_round_1(context, db_path=council_db)
        assert len(assessments) == 5
        for a in assessments:
            assert a["direction"] == "neutral"

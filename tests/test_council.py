"""Tests for the council v2 vote-first workflow."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.council.agents import AGENT_NAMES
from src.council.engine import CouncilEngine, init_council_tables
from src.council.protocol import (
    _parse_agent_response,
    aggregate_votes,
    build_shared_context,
    run_round_1,
    run_round_2,
    tally_votes,
)

ET = ZoneInfo("America/New_York")


def _make_agent_response(
    agent: str,
    direction: str = "bullish",
    confidence: float = 0.8,
    sizing: float = 1.1,
    reserve: int = 18,
    scan: str = "normal",
) -> str:
    """Build a mock council v2 JSON response."""
    return json.dumps(
        {
            "agent": agent,
            "direction": direction,
            "confidence": confidence,
            "parameters": {
                "position_sizing_multiplier": sizing,
                "cash_reserve_target_pct": reserve,
                "scan_aggressiveness": scan,
            },
            "sector_tilts": {"prefer": ["Technology"], "avoid": ["Utilities"]},
            "key_reasoning": f"Mock analysis from {agent}.",
            "key_risk": "Macro shock could disrupt the setup.",
            "falsifiable_prediction": {
                "claim": f"{agent} expects the next scan cadence to stay stable.",
                "confidence": 0.7,
                "verification_date": "2026-04-30",
            },
        }
    )


@pytest.fixture
def council_db(tmp_path):
    """Create a temp DB with the tables council v2 touches."""
    db_path = str(tmp_path / "test_council.sqlite3")
    from tests.conftest import init_test_db
    init_test_db(db_path)  # create all tables from registry
    init_council_tables(db_path)

    with sqlite3.connect(db_path) as conn:

        now = datetime.now(ET)
        now_iso = now.isoformat()
        yesterday = (now - timedelta(days=1)).isoformat()
        two_days_ago = (now - timedelta(days=2)).isoformat()
        today = now.strftime("%Y-%m-%d")

        rec_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO recommendations "
            "(recommendation_id, created_at, ticker, priority_score, confidence_score, market_regime, sector_context) "
            "VALUES (?, ?, 'AAPL', 85.0, 0.82, 'risk_on', 'Technology')",
            (rec_id, now_iso),
        )
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, direction, status, planned_allocation, actual_entry_time, created_at, updated_at) "
            "VALUES (?, ?, 'AAPL', 'long', 'open', 10000, ?, ?, ?)",
            (str(uuid.uuid4()), rec_id, yesterday, yesterday, yesterday),
        )
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, direction, status, planned_allocation, actual_entry_time, actual_exit_time, pnl_dollars, pnl_pct, exit_reason, max_adverse_excursion, created_at, updated_at) "
            "VALUES (?, ?, 'MSFT', 'long', 'closed', 9000, ?, ?, 220.0, 2.4, 'target_hit', -1.8, ?, ?)",
            (str(uuid.uuid4()), rec_id, two_days_ago, yesterday, two_days_ago, yesterday),
        )
        conn.execute(
            "INSERT INTO vix_term_structure (collected_at, collected_date, vix, vix9d, vix3m, vix1y) "
            "VALUES (?, ?, 15.2, 14.0, 16.5, 18.0)",
            (now_iso, today),
        )
        conn.executemany(
            "INSERT INTO macro_snapshots (series_id, series_name, collected_date, collected_at, value) VALUES (?, ?, ?, ?, ?)",
            [
                ("NFCI", "NFCI", today, now_iso, -0.5),
                ("BAMLH0A0HYM2", "HY Spread", today, now_iso, 3.5),
                ("T10Y2Y", "10Y-2Y Spread", today, now_iso, 0.45),
                ("UNRATE", "Unemployment", today, now_iso, 4.0),
            ],
        )
        conn.execute(
            "INSERT INTO training_examples "
            "(example_id, created_at, quality_score, quality_score_auto, source, difficulty, "
            "curriculum_stage, instruction, input_text, output_text) "
            "VALUES ('ex1', ?, 0.84, 0.84, 'blinded_win', 'medium', 'stage_1', 'evaluate', 'input', 'output')",
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
            "(scan_time, packet_worthy, llm_success, llm_total, avg_conviction, created_at) "
            "VALUES ('09:30', 3, 2, 3, 7.2, ?)",
            (now_iso,),
        )
    return db_path


def test_build_shared_context_includes_core_sections(council_db):
    context = build_shared_context(council_db)
    assert "Today's scan:" in context
    assert "Open positions:" in context
    assert "System Health (HSHS):" in context
    assert "Traffic Light:" in context
    assert "VIX:" in context


@patch("src.council.protocol._call_claude")
def test_round_1_returns_all_current_agents(mock_claude, council_db):
    mock_claude.side_effect = [_make_agent_response(agent) for agent in AGENT_NAMES]
    assessments = run_round_1(build_shared_context(council_db), db_path=council_db)

    assert len(assessments) == len(AGENT_NAMES)
    assert {item["agent"] for item in assessments} == set(AGENT_NAMES)
    assert {item["direction"] for item in assessments} == {"bullish"}


@patch("src.council.protocol._call_claude")
def test_round_1_uses_default_response_on_api_failure(mock_claude, council_db):
    mock_claude.return_value = None
    assessments = run_round_1(build_shared_context(council_db), db_path=council_db)

    assert len(assessments) == len(AGENT_NAMES)
    assert all(item["direction"] == "neutral" for item in assessments)
    assert all(item["confidence"] == 0.1 for item in assessments)
    assert all(item["vote"] == "hold_steady" for item in assessments)


@patch("src.council.protocol._call_claude")
def test_round_2_includes_round_1_summary_and_tracks_flips(mock_claude):
    round1 = [
        _parse_agent_response(_make_agent_response(agent, direction="neutral", confidence=0.5), agent)
        for agent in AGENT_NAMES
    ]
    prompts = []

    def side_effect(system_prompt, user_prompt):
        prompts.append(user_prompt)
        idx = len(prompts) - 1
        direction = "bullish" if idx == 0 else "neutral"
        return _make_agent_response(AGENT_NAMES[idx], direction=direction, confidence=0.7)

    mock_claude.side_effect = side_effect

    updated, sycophancy_flags = run_round_2(round1, shared_context="Shared context")

    assert len(updated) == len(AGENT_NAMES)
    assert AGENT_NAMES[0] in sycophancy_flags
    assert all("ROUND 1 RESULTS" in prompt for prompt in prompts)


def test_aggregate_votes_reports_majority_consensus():
    assessments = [
        _parse_agent_response(_make_agent_response(AGENT_NAMES[0], "bullish", 0.9, sizing=1.2), AGENT_NAMES[0]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[1], "bullish", 0.8, sizing=1.1), AGENT_NAMES[1]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[2], "bullish", 0.7, sizing=1.0), AGENT_NAMES[2]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[3], "neutral", 0.4, sizing=0.9), AGENT_NAMES[3]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[4], "bearish", 0.2, sizing=0.8), AGENT_NAMES[4]),
    ]

    result = aggregate_votes(assessments)

    assert result["consensus_reached"] is True
    assert result["direction"] == "bullish"
    assert result["consensus_type"] == "3-2"
    assert result["round2_needed"] is False
    assert result["parameter_recommendations"]["position_sizing_multiplier"] > 1.0


def test_aggregate_votes_reports_split_decision():
    assessments = [
        _parse_agent_response(_make_agent_response(AGENT_NAMES[0], "bullish", 0.8), AGENT_NAMES[0]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[1], "bullish", 0.7), AGENT_NAMES[1]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[2], "bearish", 0.8), AGENT_NAMES[2]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[3], "bearish", 0.7), AGENT_NAMES[3]),
        _parse_agent_response(_make_agent_response(AGENT_NAMES[4], "neutral", 0.5), AGENT_NAMES[4]),
    ]

    result = aggregate_votes(assessments)

    assert result["consensus_reached"] is False
    assert result["round2_needed"] is True
    assert result["consensus_type"] == "2-3"


def test_tally_votes_returns_backward_compat_shape():
    assessments = [
        _parse_agent_response(_make_agent_response(agent, "bullish", 0.8), agent)
        for agent in AGENT_NAMES[:3]
    ] + [
        _parse_agent_response(_make_agent_response(agent, "neutral", 0.3), agent)
        for agent in AGENT_NAMES[3:]
    ]

    result = tally_votes(assessments)

    assert result["consensus"] == "bullish"
    assert result["leading_vote"] == "increase_exposure"
    assert result["is_contested"] is False
    assert result["confidence_weighted_score"] > 0


def test_parse_agent_response_handles_fences_and_defaults():
    fenced = "```json\n" + _make_agent_response(AGENT_NAMES[0], confidence=99) + "\n```"
    parsed = _parse_agent_response(fenced, AGENT_NAMES[0])
    fallback = _parse_agent_response(None, AGENT_NAMES[0])

    assert parsed["agent"] == AGENT_NAMES[0]
    assert parsed["confidence"] == 1.0
    assert parsed["vote"] == "increase_exposure"
    assert fallback["direction"] == "neutral"
    assert fallback["confidence"] == 0.1
    assert fallback["vote"] == "hold_steady"


@patch("src.council.protocol._call_claude")
def test_engine_run_session_stores_single_round_consensus(mock_claude, council_db):
    mock_claude.side_effect = [_make_agent_response(agent, "bullish", 0.8) for agent in AGENT_NAMES]

    engine = CouncilEngine(db_path=council_db)
    result = engine.run_session(session_type="daily")

    assert result["rounds_completed"] == 1
    assert result["consensus"] == "bullish"
    assert result["total_cost"] > 0

    with sqlite3.connect(council_db) as conn:
        vote_count = conn.execute(
            "SELECT COUNT(*) FROM council_votes WHERE session_id = ?",
            (result["session_id"],),
        ).fetchone()[0]
        session_row = conn.execute(
            "SELECT result_json, total_cost FROM council_sessions WHERE session_id = ?",
            (result["session_id"],),
        ).fetchone()

    assert vote_count == len(AGENT_NAMES)
    assert session_row[0]
    assert session_row[1] > 0


@patch("src.council.protocol._call_claude")
def test_engine_runs_round_2_when_round_1_is_split(mock_claude, council_db):
    round1 = [
        _make_agent_response(AGENT_NAMES[0], "bullish", 0.9),
        _make_agent_response(AGENT_NAMES[1], "bullish", 0.8),
        _make_agent_response(AGENT_NAMES[2], "bearish", 0.8),
        _make_agent_response(AGENT_NAMES[3], "bearish", 0.7),
        _make_agent_response(AGENT_NAMES[4], "neutral", 0.6),
    ]
    round2 = [
        _make_agent_response(AGENT_NAMES[0], "bullish", 0.9),
        _make_agent_response(AGENT_NAMES[1], "bullish", 0.8),
        _make_agent_response(AGENT_NAMES[2], "bullish", 0.7),
        _make_agent_response(AGENT_NAMES[3], "bearish", 0.6),
        _make_agent_response(AGENT_NAMES[4], "bullish", 0.6),
    ]
    mock_claude.side_effect = round1 + round2

    engine = CouncilEngine(db_path=council_db)
    result = engine.run_session(session_type="weekly")

    assert result["rounds_completed"] == 2
    assert result["consensus"] == "bullish"
    assert result["is_contested"] is False

    session = engine.get_session(result["session_id"])
    assert session is not None
    assert len(session["votes"]) == len(AGENT_NAMES) * 2
    assert session["result_json"]["votes"]["round2_triggered"] is True


@patch("src.council.protocol._call_claude")
def test_get_recent_sessions_returns_latest_first(mock_claude, council_db):
    mock_claude.side_effect = [_make_agent_response(agent, "bullish", 0.8) for agent in AGENT_NAMES] + [
        _make_agent_response(agent, "neutral", 0.6) for agent in AGENT_NAMES
    ]

    engine = CouncilEngine(db_path=council_db)
    first = engine.run_session(session_type="daily")
    second = engine.run_session(session_type="strategic", custom_question="Should we add a new desk?")

    recent = engine.get_recent_sessions(limit=5)

    assert len(recent) == 2
    assert {row["session_id"] for row in recent} == {first["session_id"], second["session_id"]}

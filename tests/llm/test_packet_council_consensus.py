"""Sprint 5 Wave C7a.1 / T17 — COUNCIL CONSENSUS packet section tests.

Covers:
1. Per-pillar council read populates the 5 vote feature-dict fields plus
   session metadata (consensus score, age days).
2. _build_feature_prompt renders the COUNCIL CONSENSUS section with a 5-row
   pillar table when the feature dict is populated.
3. Missing-session fallback renders the empty-state message.
4. Stale (>3d) session appends the [STALE] marker.

These tests intentionally bypass network/Ollama — they exercise enricher DB
reads against a synthetic SQLite fixture, then drive _build_feature_prompt
directly.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.data_enrichment.enricher import enrich_council_consensus
from src.llm.packet_writer import _build_feature_prompt
from tests.conftest import init_test_db


@pytest.fixture
def council_db(tmp_path):
    """Synthetic DB with a fresh council session + 5 pillar votes for AAPL ticker context."""
    db = str(tmp_path / "council_test.sqlite3")
    init_test_db(db, ["council_sessions", "council_votes"])
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO council_sessions (session_id, session_type, created_at, "
            "consensus, confidence_weighted_score, rounds_completed) VALUES "
            "(?, 'daily', ?, 'BULLISH', 0.72, 3)",
            ("sess-1", now_iso),
        )
        # The 5 pillar agents. agent_name carries the pillar label.
        pillar_rows = [
            ("v-macro", "sess-1", "macro_pillar", 1, "BULLISH", 7, "BUY"),
            ("v-strategic", "sess-1", "strategic_pillar", 1, "BULLISH", 8, "BUY"),
            ("v-tactical", "sess-1", "tactical_pillar", 1, "NEUTRAL", 5, "HOLD"),
            ("v-innovation", "sess-1", "innovation_pillar", 1, "BULLISH", 6, "BUY"),
            ("v-risk", "sess-1", "risk_pillar", 1, "BEARISH", 4, "CAUTION"),
        ]
        for row in pillar_rows:
            conn.execute(
                "INSERT INTO council_votes (vote_id, session_id, agent_name, round, "
                "position, confidence, recommendation) VALUES (?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        conn.commit()
    return db


class TestEnrichCouncilConsensus:
    """Per-pillar read populates the 5 vote fields + session metadata."""

    def test_populates_five_pillar_votes(self, council_db):
        feat = {}
        enrich_council_consensus(feat, db_path=council_db)
        assert feat.get("council_macro_vote") == "BULLISH"
        assert feat.get("council_strategic_vote") == "BULLISH"
        assert feat.get("council_tactical_vote") == "NEUTRAL"
        assert feat.get("council_innovation_vote") == "BULLISH"
        assert feat.get("council_risk_vote") == "BEARISH"
        assert feat.get("council_session_id") == "sess-1"
        assert feat.get("council_consensus_score") == pytest.approx(0.72)
        assert feat.get("council_session_age_days") == 0


class TestRenderCouncilConsensusSection:
    """Section 13: rendered prompt contains COUNCIL CONSENSUS header + 5 pillar rows."""

    def test_section_rendered_with_five_rows(self, council_db):
        feat = {}
        enrich_council_consensus(feat, db_path=council_db)
        prompt = _build_feature_prompt(feat, "AAPL")
        assert "=== COUNCIL CONSENSUS ===" in prompt
        # 5 pillar rows visible
        assert "Macro" in prompt
        assert "Strategic" in prompt
        assert "Tactical" in prompt
        assert "Innovation" in prompt
        assert "Risk" in prompt
        # Consensus + age line surfaces
        assert "0.72" in prompt
        # Stale marker not present on fresh session
        assert "[STALE]" not in prompt

    def test_missing_session_fallback(self, tmp_path):
        """Empty-state message when no council session in DB."""
        db = str(tmp_path / "empty.sqlite3")
        init_test_db(db, ["council_sessions", "council_votes"])
        feat = {}
        enrich_council_consensus(feat, db_path=db)
        prompt = _build_feature_prompt(feat, "AAPL")
        assert "=== COUNCIL CONSENSUS ===" in prompt
        assert "No recent council session" in prompt

    def test_stale_session_marker(self, tmp_path):
        """Session older than 3 days renders [STALE] marker."""
        db = str(tmp_path / "stale.sqlite3")
        init_test_db(db, ["council_sessions", "council_votes"])
        stale_iso = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO council_sessions (session_id, session_type, created_at, "
                "consensus, confidence_weighted_score, rounds_completed) VALUES "
                "(?, 'daily', ?, 'BULLISH', 0.65, 3)",
                ("sess-stale", stale_iso),
            )
            for vote_id, agent in [
                ("v1", "macro_pillar"), ("v2", "strategic_pillar"),
                ("v3", "tactical_pillar"), ("v4", "innovation_pillar"),
                ("v5", "risk_pillar"),
            ]:
                conn.execute(
                    "INSERT INTO council_votes (vote_id, session_id, agent_name, "
                    "round, position, confidence, recommendation) VALUES "
                    "(?, 'sess-stale', ?, 1, 'BULLISH', 5, 'BUY')",
                    (vote_id, agent),
                )
            conn.commit()
        feat = {}
        enrich_council_consensus(feat, db_path=db)
        prompt = _build_feature_prompt(feat, "AAPL")
        assert "[STALE]" in prompt
        assert feat.get("council_session_age_days") == 5

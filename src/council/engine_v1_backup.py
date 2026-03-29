"""Council Engine -- orchestrates full Delphi sessions and persists results."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.council.protocol import (
    build_shared_context,
    run_round_1,
    run_round_2,
    run_round_3,
    tally_votes,
)

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

COUNCIL_SCHEMA = """\
CREATE TABLE IF NOT EXISTS council_sessions (
    session_id TEXT PRIMARY KEY,
    session_type TEXT NOT NULL,
    trigger_reason TEXT,
    created_at TEXT NOT NULL,
    consensus TEXT,
    confidence_weighted_score REAL,
    is_contested INTEGER DEFAULT 0,
    total_cost REAL,
    rounds_completed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS council_votes (
    vote_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    round INTEGER NOT NULL,
    position TEXT,
    confidence INTEGER,
    recommendation TEXT,
    key_data_points TEXT,
    risk_flags TEXT,
    vote TEXT,
    is_devils_advocate INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES council_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_council_votes_session
    ON council_votes(session_id);
CREATE INDEX IF NOT EXISTS idx_council_sessions_created
    ON council_sessions(created_at);
"""


def init_council_tables(db_path: str = DB_PATH) -> None:
    """Create the council tables if they do not exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(COUNCIL_SCHEMA)
        conn.commit()


def _store_votes(
    conn: sqlite3.Connection,
    session_id: str,
    round_num: int,
    assessments: list[dict],
) -> None:
    """Persist a list of agent assessments for a given round."""
    for assessment in assessments:
        vote_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO council_votes
               (vote_id, session_id, agent_name, round,
                position, confidence, recommendation,
                key_data_points, risk_flags, vote, is_devils_advocate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vote_id,
                session_id,
                assessment.get("agent", "unknown"),
                round_num,
                assessment.get("position"),
                assessment.get("confidence"),
                assessment.get("recommendation"),
                json.dumps(assessment.get("key_data_points", [])),
                json.dumps(assessment.get("risk_flags", [])),
                assessment.get("vote"),
                1 if assessment.get("agent") == "devils_advocate" else 0,
            ),
        )


def _estimate_session_cost(rounds_completed: int, agents_per_round: int = 5) -> float:
    """Estimate the API cost for a council session.

    Uses rough Anthropic pricing: ~$3/M input, ~$15/M output tokens.
    Each council call is approximately 2k input + 500 output tokens.
    """
    calls = rounds_completed * agents_per_round
    input_cost = calls * 2000 * (3.0 / 1_000_000)
    output_cost = calls * 500 * (15.0 / 1_000_000)
    return round(input_cost + output_cost, 4)


class CouncilEngine:
    """Orchestrate a full Modified Delphi council session."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        init_council_tables(self.db_path)

    def run_session(
        self,
        session_type: str = "daily",
        trigger_reason: str | None = None,
    ) -> dict:
        """Run a full three-round council session.

        Args:
            session_type: Type of session (daily, emergency, ad_hoc).
            trigger_reason: Optional reason that triggered this session.

        Returns:
            Dict with session results including consensus, votes, and cost.
        """
        session_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        logger.info(
            "Starting council session %s (type=%s)", session_id, session_type
        )

        # Create session record
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO council_sessions
                   (session_id, session_type, trigger_reason, created_at,
                    rounds_completed)
                   VALUES (?, ?, ?, ?, 0)""",
                (session_id, session_type, trigger_reason, created_at),
            )
            conn.commit()

        rounds_completed = 0

        # Build shared context
        shared_context = build_shared_context(self.db_path)

        # Round 1: Independent assessment
        try:
            round1 = run_round_1(shared_context, db_path=self.db_path)
            rounds_completed = 1
            with sqlite3.connect(self.db_path) as conn:
                _store_votes(conn, session_id, 1, round1)
                conn.execute(
                    "UPDATE council_sessions SET rounds_completed = ? WHERE session_id = ?",
                    (rounds_completed, session_id),
                )
                conn.commit()
        except Exception as e:
            logger.error("Round 1 failed: %s", e)
            return self._finalize_session(
                session_id, rounds_completed, None, None
            )

        # Round 2: Cross-examination
        try:
            round2 = run_round_2(round1)
            rounds_completed = 2
            with sqlite3.connect(self.db_path) as conn:
                _store_votes(conn, session_id, 2, round2)
                conn.execute(
                    "UPDATE council_sessions SET rounds_completed = ? WHERE session_id = ?",
                    (rounds_completed, session_id),
                )
                conn.commit()
        except Exception as e:
            logger.error("Round 2 failed: %s", e)
            return self._finalize_session(
                session_id, rounds_completed, round1, None
            )

        # Round 3: Final vote
        try:
            round3 = run_round_3(round2)
            rounds_completed = 3
            with sqlite3.connect(self.db_path) as conn:
                _store_votes(conn, session_id, 3, round3)
                conn.execute(
                    "UPDATE council_sessions SET rounds_completed = ? WHERE session_id = ?",
                    (rounds_completed, session_id),
                )
                conn.commit()
        except Exception as e:
            logger.error("Round 3 failed: %s", e)
            return self._finalize_session(
                session_id, rounds_completed, round1, round2
            )

        # Tally votes from Round 3
        tally = tally_votes(round3)
        cost = _estimate_session_cost(rounds_completed)

        # Finalize session
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE council_sessions
                   SET consensus = ?,
                       confidence_weighted_score = ?,
                       is_contested = ?,
                       total_cost = ?,
                       rounds_completed = ?
                   WHERE session_id = ?""",
                (
                    tally["consensus"],
                    tally["confidence_weighted_score"],
                    1 if tally["is_contested"] else 0,
                    cost,
                    rounds_completed,
                    session_id,
                ),
            )
            conn.commit()

        result = {
            "session_id": session_id,
            "session_type": session_type,
            "rounds_completed": rounds_completed,
            "consensus": tally["consensus"],
            "confidence_weighted_score": tally["confidence_weighted_score"],
            "is_contested": tally["is_contested"],
            "vote_breakdown": tally["vote_breakdown"],
            "reason": tally["reason"],
            "total_cost": cost,
            "round1": round1,
            "round2": round2,
            "round3": round3,
        }

        logger.info(
            "Council session %s complete: consensus=%s, contested=%s, cost=$%.4f",
            session_id,
            tally["consensus"],
            tally["is_contested"],
            cost,
        )

        return result

    def _finalize_session(
        self,
        session_id: str,
        rounds_completed: int,
        round1: list[dict] | None,
        round2: list[dict] | None,
    ) -> dict:
        """Finalize a session that ended early due to errors."""
        cost = _estimate_session_cost(rounds_completed)

        # If we have at least round 1, try to tally whatever we have
        tally = None
        final_assessments = round2 or round1
        if final_assessments:
            tally = tally_votes(final_assessments)

        consensus = tally["consensus"] if tally else "incomplete"
        score = tally["confidence_weighted_score"] if tally else 0.0
        contested = tally["is_contested"] if tally else True

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE council_sessions
                   SET consensus = ?,
                       confidence_weighted_score = ?,
                       is_contested = ?,
                       total_cost = ?,
                       rounds_completed = ?
                   WHERE session_id = ?""",
                (
                    consensus,
                    score,
                    1 if contested else 0,
                    cost,
                    rounds_completed,
                    session_id,
                ),
            )
            conn.commit()

        return {
            "session_id": session_id,
            "rounds_completed": rounds_completed,
            "consensus": consensus,
            "confidence_weighted_score": score,
            "is_contested": contested,
            "vote_breakdown": tally["vote_breakdown"] if tally else {},
            "reason": "Session ended early due to errors",
            "total_cost": cost,
            "round1": round1,
            "round2": round2,
            "round3": None,
        }

    def get_session(self, session_id: str) -> dict | None:
        """Retrieve a council session and its votes from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                "SELECT * FROM council_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not session:
                return None

            votes = conn.execute(
                "SELECT * FROM council_votes WHERE session_id = ? ORDER BY round, agent_name",
                (session_id,),
            ).fetchall()

        return {
            "session": dict(session),
            "votes": [dict(v) for v in votes],
        }

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        """Retrieve the most recent council sessions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM council_sessions
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

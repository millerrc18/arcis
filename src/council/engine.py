"""Council Engine v2 — vote-first Modified Delphi sessions.

Orchestrates council sessions with conditional rounds, parameter
auto-application, value tracking, calibration, and debug logging.

Changes from v1:
- Import from protocol and agents (v2 implementations)
- Run Round 1, aggregate, conditionally run Round 2 (not always 3 rounds)
- Store structured result_json in council_sessions
- Extract falsifiable predictions into council_calibrations
- Log parameter changes via value_tracker for counterfactual attribution
- Support custom_question for strategic/on-demand sessions
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.council.constants import PARAMETER_DEFAULTS, RATE_LIMITS
from src.council.protocol import (
    aggregate_votes,
    apply_rate_limiters,
    build_shared_context,
    run_round_1,
    run_round_2,
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

CREATE TABLE IF NOT EXISTS council_calibrations (
    calibration_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    prediction TEXT NOT NULL,
    prediction_confidence REAL NOT NULL,
    verification_date TEXT NOT NULL,
    actual_outcome TEXT,
    correct INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS council_debug_log (
    debug_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    round INTEGER NOT NULL,
    system_prompt_hash TEXT,
    user_message TEXT,
    raw_response TEXT,
    parsed_successfully INTEGER DEFAULT 0,
    parse_error TEXT,
    latency_ms INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES council_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_council_votes_session
    ON council_votes(session_id);
CREATE INDEX IF NOT EXISTS idx_council_sessions_created
    ON council_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_council_calibrations_session
    ON council_calibrations(session_id);
CREATE INDEX IF NOT EXISTS idx_council_debug_session
    ON council_debug_log(session_id);
"""


def init_council_tables(db_path: str = DB_PATH) -> None:
    """Create all council tables if they do not exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(COUNCIL_SCHEMA)
        # Safe ALTERs for v2 columns (backward compat)
        for alter in [
            "ALTER TABLE council_sessions ADD COLUMN result_json TEXT",
            "ALTER TABLE council_votes ADD COLUMN direction TEXT",
            "ALTER TABLE council_votes ADD COLUMN confidence_float REAL",
            "ALTER TABLE council_votes ADD COLUMN assessment_json TEXT",
        ]:
            try:
                conn.execute(alter)
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.commit()


def _store_votes(
    conn: sqlite3.Connection,
    session_id: str,
    round_num: int,
    assessments: list[dict],
) -> None:
    """Persist agent assessments — stores both old and new schema fields.

    FIX #2: Maps new direction/confidence to old position/confidence_int/vote
    for backward compatibility with existing dashboard and queries.
    """
    for assessment in assessments:
        vote_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO council_votes
               (vote_id, session_id, agent_name, round,
                position, confidence, recommendation,
                key_data_points, risk_flags, vote, is_devils_advocate,
                direction, confidence_float, assessment_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vote_id,
                session_id,
                assessment.get("agent", "unknown"),
                round_num,
                # Old schema fields (backward compat)
                assessment.get("position", "neutral"),
                assessment.get("confidence_int", int(assessment.get("confidence", 0.5) * 10)),
                assessment.get("recommendation", assessment.get("key_reasoning", "")),
                json.dumps(assessment.get("key_data_points", [])),
                json.dumps(assessment.get("risk_flags", [])),
                assessment.get("vote", "hold_steady"),
                0,  # is_devils_advocate — no longer used
                # New v2 fields
                assessment.get("direction", "neutral"),
                assessment.get("confidence", 0.5),
                json.dumps(assessment, default=str),
            ),
        )


def _estimate_session_cost(rounds_completed: int, agents_per_round: int = 5) -> float:
    """Estimate API cost. Uses Anthropic Sonnet pricing."""
    calls = rounds_completed * agents_per_round
    input_cost = calls * 2000 * (3.0 / 1_000_000)
    output_cost = calls * 500 * (15.0 / 1_000_000)
    return round(input_cost + output_cost, 4)


class CouncilEngine:
    """Orchestrate vote-first Modified Delphi council sessions."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        init_council_tables(self.db_path)

    def run_session(
        self,
        session_type: str = "daily",
        trigger_reason: str | None = None,
        custom_question: str | None = None,
    ) -> dict:
        """Run a vote-first council session.

        Round 1 always runs. Round 2 only if <3/5 consensus.
        Daily sessions never run Round 3.

        Args:
            session_type: "daily", "weekly", "monthly", "strategic"
            trigger_reason: Why this session was triggered
            custom_question: For strategic sessions — the founder's question

        Returns:
            Complete session result dict with votes, parameters, calibration.
        """
        session_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        logger.info("Starting council session %s (type=%s)", session_id, session_type)
        self._create_session_record(
            session_id,
            session_type,
            trigger_reason or custom_question,
            created_at,
        )
        shared_context = build_shared_context(self.db_path)

        try:
            round_data = self._run_rounds(session_id, session_type, shared_context, custom_question)
        except Exception as exc:
            logger.error("Round 1 failed: %s", exc)
            return self._finalize_session(session_id, 0, [], session_type)

        current_params, recommended, applied, rate_limited = self._apply_parameters(
            session_id,
            round_data["aggregation"],
        )
        self._store_calibrations(session_id, round_data["final_assessments"])

        cost = _estimate_session_cost(round_data["rounds_completed"])
        result_json, dissent = self._build_result_json(
            session_id=session_id,
            session_type=session_type,
            custom_question=custom_question,
            shared_context=shared_context,
            round_data=round_data,
            current_params=current_params,
            recommended=recommended,
            applied=applied,
            rate_limited=rate_limited,
            cost=cost,
        )
        self._persist_completed_session(
            session_id=session_id,
            aggregation=round_data["aggregation"],
            final_assessments=round_data["final_assessments"],
            rounds_completed=round_data["rounds_completed"],
            cost=cost,
            result_json=result_json,
        )
        aggregation = round_data["aggregation"]

        logger.info(
            "Council session %s complete: direction=%s, consensus=%s, "
            "rounds=%d, cost=$%.4f",
            session_id, aggregation["direction"],
            aggregation["consensus_type"], round_data["rounds_completed"], cost,
        )

        # Return full result
        return {
            "session_id": session_id,
            "session_type": session_type,
            "rounds_completed": round_data["rounds_completed"],
            "consensus": round_data["aggregation"]["direction"],
            "consensus_type": round_data["aggregation"]["consensus_type"],
            "aggregated_score": round_data["aggregation"]["aggregated_score"],
            "confidence_avg": round_data["aggregation"]["confidence_avg"],
            "is_contested": not round_data["aggregation"]["consensus_reached"],
            "vote_distribution": round_data["aggregation"]["vote_distribution"],
            "parameter_adjustments": result_json["parameter_adjustments"],
            "scan_aggressiveness": applied.get("scan_aggressiveness", "normal"),
            "sycophancy_flags": round_data["sycophancy_flags"],
            "dissent": dissent,
            "total_cost": cost,
            "agent_assessments": round_data["final_assessments"],
            "result_json": result_json,
        }

    def _create_session_record(
        self,
        session_id: str,
        session_type: str,
        trigger_reason: str | None,
        created_at: str,
    ) -> None:
        """Insert the council session shell row before running any rounds."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO council_sessions
                   (session_id, session_type, trigger_reason, created_at, rounds_completed)
                   VALUES (?, ?, ?, ?, 0)""",
                (session_id, session_type, trigger_reason, created_at),
            )
            conn.commit()

    def _run_rounds(
        self,
        session_id: str,
        session_type: str,
        shared_context: str,
        custom_question: str | None,
    ) -> dict:
        """Run Round 1 and the optional Round 2, persisting votes as they land."""
        round1 = run_round_1(
            shared_context,
            session_id=session_id,
            db_path=self.db_path,
            custom_question=custom_question,
        )
        with sqlite3.connect(self.db_path) as conn:
            _store_votes(conn, session_id, 1, round1)
            conn.execute(
                "UPDATE council_sessions SET rounds_completed = 1 WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()

        aggregation = aggregate_votes(round1, session_type)
        final_assessments = round1
        rounds_completed = 1
        sycophancy_flags = []

        if aggregation["round2_needed"]:
            logger.info("Round 2 triggered — no 3/5 consensus in Round 1")
            try:
                round2, sycophancy_flags = run_round_2(
                    round1,
                    shared_context,
                    session_id=session_id,
                    db_path=self.db_path,
                )
                with sqlite3.connect(self.db_path) as conn:
                    _store_votes(conn, session_id, 2, round2)
                    conn.execute(
                        "UPDATE council_sessions SET rounds_completed = 2 WHERE session_id = ?",
                        (session_id,),
                    )
                    conn.commit()
                final_assessments = round2
                aggregation = aggregate_votes(round2, session_type)
                rounds_completed = 2
            except Exception as exc:
                logger.error("Round 2 failed: %s", exc)
        else:
            logger.info(
                "Consensus reached in Round 1 (%s) — skipping Round 2",
                aggregation["consensus_type"],
            )

        return {
            "aggregation": aggregation,
            "final_assessments": final_assessments,
            "rounds_completed": rounds_completed,
            "sycophancy_flags": sycophancy_flags,
        }

    def _apply_parameters(
        self,
        session_id: str,
        aggregation: dict,
    ) -> tuple[dict, dict, dict, bool]:
        """Apply council parameter recommendations with rate limits and value logging."""
        from src.council.value_tracker import get_current_parameters, log_parameter_change

        current_params = get_current_parameters(self.db_path)
        recommended = aggregation.get("parameter_recommendations", {})

        if aggregation["confidence_avg"] < RATE_LIMITS["min_confidence_to_apply"]:
            applied = PARAMETER_DEFAULTS.copy()
            rate_limited = True
            logger.info(
                "[COUNCIL] Low confidence (%.2f) — using defaults",
                aggregation["confidence_avg"],
            )
        else:
            applied = apply_rate_limiters(recommended, current_params, self.db_path)
            rate_limited = applied.pop("_rate_limited", False)

        for param_name, applied_value in applied.items():
            if param_name == "scan_aggressiveness":
                continue
            default_value = PARAMETER_DEFAULTS.get(param_name, 1.0)
            council_value = recommended.get(param_name, default_value)
            log_parameter_change(
                session_id=session_id,
                parameter_name=param_name,
                default_value=float(default_value),
                council_value=float(council_value),
                applied_value=float(applied_value),
                rate_limited=rate_limited,
                agent_name="consensus",
                db_path=self.db_path,
            )

        return current_params, recommended, applied, rate_limited

    def _store_calibrations(self, session_id: str, assessments: list[dict]) -> None:
        """Persist falsifiable predictions emitted by the final council assessments."""
        for assessment in assessments:
            prediction = assessment.get("falsifiable_prediction")
            if not (prediction and isinstance(prediction, dict) and prediction.get("claim")):
                continue
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "INSERT INTO council_calibrations "
                        "(calibration_id, session_id, agent_name, prediction, "
                        "prediction_confidence, verification_date, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(uuid.uuid4()),
                            session_id,
                            assessment.get("agent", "unknown"),
                            prediction["claim"],
                            prediction.get("confidence", 0.5),
                            prediction.get("verification_date", ""),
                            datetime.now(ET).isoformat(),
                        ),
                    )
            except Exception as exc:
                logger.warning("[COUNCIL] Calibration insert failed: %s", exc)

    def _build_result_json(
        self,
        *,
        session_id: str,
        session_type: str,
        custom_question: str | None,
        shared_context: str,
        round_data: dict,
        current_params: dict,
        recommended: dict,
        applied: dict,
        rate_limited: bool,
        cost: float,
    ) -> tuple[dict, list[dict]]:
        """Construct the structured v2 session payload and dissent summary."""
        aggregation = round_data["aggregation"]
        final_assessments = round_data["final_assessments"]
        dissent = [
            {
                "agent": assessment["agent"],
                "direction": assessment.get("direction"),
                "confidence": assessment.get("confidence"),
                "key_reasoning": assessment.get("key_reasoning", ""),
            }
            for assessment in final_assessments
            if assessment.get("direction") != aggregation["direction"]
        ]
        result_json = {
            "session_meta": {
                "session_id": session_id,
                "session_type": session_type,
                "cost_usd": cost,
                "rounds_completed": round_data["rounds_completed"],
                "custom_question": custom_question,
            },
            "market_context": shared_context,
            "votes": {
                "aggregated_score": aggregation["aggregated_score"],
                "direction": aggregation["direction"],
                "confidence_avg": aggregation["confidence_avg"],
                "vote_distribution": aggregation["vote_distribution"],
                "consensus_reached": aggregation["consensus_reached"],
                "consensus_type": aggregation["consensus_type"],
                "round2_triggered": round_data["rounds_completed"] > 1,
                "sycophancy_flags": round_data["sycophancy_flags"],
            },
            "parameter_adjustments": {
                key: {
                    "previous": current_params.get(key),
                    "recommended": recommended.get(key),
                    "applied": applied.get(key),
                    "rate_limited": rate_limited,
                }
                for key in applied
                if key != "scan_aggressiveness"
            },
            "scan_aggressiveness": applied.get("scan_aggressiveness", "normal"),
            "agent_assessments": final_assessments,
            "dissent": dissent,
        }
        return result_json, dissent

    def _persist_completed_session(
        self,
        *,
        session_id: str,
        aggregation: dict,
        final_assessments: list[dict],
        rounds_completed: int,
        cost: float,
        result_json: dict,
    ) -> None:
        """Write the final council outcome back onto the session row."""
        old_tally = tally_votes(final_assessments)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE council_sessions
                   SET consensus = ?,
                       confidence_weighted_score = ?,
                       is_contested = ?,
                       total_cost = ?,
                       rounds_completed = ?,
                       result_json = ?
                   WHERE session_id = ?""",
                (
                    old_tally.get("consensus", aggregation["direction"]),
                    old_tally.get(
                        "confidence_weighted_score",
                        abs(aggregation["aggregated_score"]) * 100,
                    ),
                    1 if not aggregation["consensus_reached"] else 0,
                    cost,
                    rounds_completed,
                    json.dumps(result_json, default=str),
                    session_id,
                ),
            )
            conn.commit()

    def _finalize_session(
        self,
        session_id: str,
        rounds_completed: int,
        assessments: list[dict],
        session_type: str,
    ) -> dict:
        """Finalize a session that ended early due to errors."""
        cost = _estimate_session_cost(rounds_completed)

        aggregation = None
        if assessments:
            aggregation = aggregate_votes(assessments, session_type)

        direction = aggregation["direction"] if aggregation else "incomplete"
        score = aggregation["aggregated_score"] if aggregation else 0.0
        contested = not aggregation["consensus_reached"] if aggregation else True

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE council_sessions
                   SET consensus = ?,
                       confidence_weighted_score = ?,
                       is_contested = ?,
                       total_cost = ?,
                       rounds_completed = ?
                   WHERE session_id = ?""",
                (direction, abs(score) * 100, 1 if contested else 0,
                 cost, rounds_completed, session_id),
            )
            conn.commit()

        return {
            "session_id": session_id,
            "rounds_completed": rounds_completed,
            "consensus": direction,
            "is_contested": contested,
            "total_cost": cost,
            "reason": "Session ended early due to errors",
        }

    def get_session(self, session_id: str) -> dict | None:
        """Retrieve a council session and its votes."""
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

        result = dict(session)
        # Parse result_json if present
        if result.get("result_json"):
            try:
                result["result_json"] = json.loads(result["result_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        result["votes"] = [dict(v) for v in votes]
        return result

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        """Retrieve the most recent council sessions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

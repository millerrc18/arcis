"""Council Engine v2 -- vote-first Modified Delphi sessions.

Called by: cli/commands.py, notifications/telegram.py, scheduler/watch.py
Calls: council/constants.py, council/protocol.py, council/value_tracker.py
Owns tables: council_sessions, council_votes, council_calibrations, council_debug_log
Config keys: none
Tests: tests/test_council.py

Orchestrates council sessions with conditional rounds, parameter
auto-application, value tracking, calibration, and debug logging.

Modified Delphi Protocol
~~~~~~~~~~~~~~~~~~~~~~~~
The traditional Delphi method uses multiple anonymous rounds to converge
on expert consensus.  Our "Modified Delphi" adapts this for LLM agents:

1. **Vote-first** — agents vote *before* seeing others' opinions to
   avoid anchoring bias and sycophancy (LLMs are especially prone to
   agreement with the first opinion they see).

2. **Conditional rounds** — Round 2 only fires when Round 1 fails to
   reach consensus (<3 of 5 agents agree).  This saves API cost when
   the council already agrees, and avoids the "artificial convergence"
   problem where extra rounds manufacture false consensus.

3. **Anti-sycophancy detection** — Round 2 checks for agents that flip
   their vote to match the majority.  Flagged flips are reported in the
   session result so humans can calibrate trust in the consensus.

5 Agent Roles (from constants.DOMAIN_WEIGHTS):
  - tactical_operator: short-term technical signals (1.2x weight daily)
  - strategic_architect: long-term thesis (1.3x weight weekly)
  - red_team: adversarial challenge (always 1.0x — untainted)
  - innovation_engine: novel patterns and alpha ideas
  - macro_navigator: macro regime and cross-asset context

The consensus threshold is tuned for 5 agents (#119): >=3/5 agreement.
If the agent count changes, the threshold logic in protocol.py must be
updated or consensus math will break.

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

from src.config import DB_PATH
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

def init_council_tables(db_path: str = DB_PATH) -> None:
    """Create all council tables and run column migrations via the schema registry."""
    from src.schema.sqlite import create_all_tables, ensure_columns
    create_all_tables(db_path)
    ensure_columns(db_path)


def _store_votes(
    conn: sqlite3.Connection,
    session_id: str,
    round_num: int,
    assessments: list[dict],
) -> None:
    """Persist agent assessments — stores both old and new schema fields.

    FIX #2: Maps new direction/confidence to old position/confidence_int/vote
    for backward compatibility with existing dashboard and queries.

    The dual-schema write (old fields + new v2 fields) exists because the
    frontend dashboard and several SQL queries still reference the v1
    column names (position, confidence as int, vote).  The v2 fields
    (direction, confidence_float, assessment_json) carry richer data.
    Once the dashboard is migrated, the old columns can be dropped.

    confidence_int is derived by multiplying the 0.0-1.0 float by 10,
    giving a 0-10 integer scale.  This conversion is lossy but acceptable
    for the backward-compat columns (#121: confidence type not validated
    — the v2 float field is the source of truth).
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
    """Estimate API cost. Uses Anthropic Sonnet pricing.

    This is a rough estimate (not metered) to enforce cost caps and
    surface spend in the session result.  The 2000-token input / 500-token
    output assumptions are conservative averages; actual usage varies.
    """
    calls = rounds_completed * agents_per_round
    input_cost = calls * 2000 * (3.0 / 1_000_000)
    output_cost = calls * 500 * (15.0 / 1_000_000)
    return round(input_cost + output_cost, 4)


def run_council_command(question: str = "", db_path: str = DB_PATH) -> dict:
    """Run a council session from a command interface (Telegram, CLI).

    Convenience wrapper so callers don't need to instantiate CouncilEngine.
    """
    engine = CouncilEngine(db_path=db_path)
    if question.strip():
        return engine.run_session(
            session_type="strategic",
            trigger_reason=question.strip(),
            custom_question=question.strip(),
        )
    return engine.run_session(
        session_type="daily",
        trigger_reason="command",
    )


class CouncilEngine:
    """Orchestrate vote-first Modified Delphi council sessions.

    Session lifecycle:
      1. Create session shell row (so we can recover from crashes)
      2. Build shared context (market data, portfolio state)
      3. Run Round 1 → persist votes → aggregate
      4. If no consensus: check cost cap → Run Round 2 → re-aggregate
      5. Apply parameter recommendations (with rate limits)
      6. Extract falsifiable predictions for calibration tracking
      7. Build structured result JSON and persist final session state

    The session shell row is written *before* any LLM calls so that a
    mid-session crash leaves a recoverable record rather than a ghost.
    """

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

        Round 1 always runs. Round 2 only if <3/5 consensus (#119:
        the 3/5 threshold is hardcoded for 5 agents — changing the
        agent count requires updating the consensus logic).
        Daily sessions never run Round 3.

        Session types carry different agent domain weights (see
        constants.DOMAIN_WEIGHTS): daily sessions amplify the tactical
        operator, weekly/monthly sessions amplify the strategic architect.
        This prevents short-term noise from dominating long-term planning.

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
        """Run Round 1 and the optional Round 2, persisting votes as they land.

        Votes are persisted *immediately* after each round (not batched
        at session end) so that a crash between rounds doesn't lose
        Round 1 data.  The rounds_completed counter on the session row
        is updated atomically with the vote inserts.
        """
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

        aggregation = aggregate_votes(round1, session_type, db_path=self.db_path)
        final_assessments = round1
        rounds_completed = 1
        sycophancy_flags = []

        if aggregation["round2_needed"]:
            # #120 — Cost cap: check cumulative cost before Round 2.
            # Without this guard, a pathological session (e.g. all agents
            # timing out and retrying) could run up unbounded API spend.
            # The cap is configurable via council.max_session_cost in YAML.
            from src.config import load_config as _load_config
            _cfg = _load_config()
            max_cost = _cfg.get("council", {}).get("max_session_cost", 2.0)
            round1_cost = _estimate_session_cost(1)
            round2_est = _estimate_session_cost(1)
            if round1_cost + round2_est > max_cost:
                logger.warning(
                    "[COUNCIL] Cost cap reached ($%.2f > $%.2f) — skipping Round 2",
                    round1_cost + round2_est, max_cost,
                )
                return {
                    "aggregation": aggregation,
                    "final_assessments": round1,
                    "rounds_completed": 1,
                    "sycophancy_flags": [],
                }

            # Round 2: agents see the anonymized Round 1 vote distribution
            # and are asked to reconsider.  sycophancy_flags tracks any
            # agent that flipped its vote to match the majority — a sign
            # of artificial convergence rather than genuine reassessment.
            logger.info("Round 2 triggered — no consensus in Round 1")
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
                aggregation = aggregate_votes(round2, session_type, db_path=self.db_path)
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
        """Apply council parameter recommendations with rate limits and value logging.

        Rate limits (constants.RATE_LIMITS) prevent the council from
        making drastic parameter swings in a single session:
          - max 25% daily change, 50% weekly change
          - minimum 0.40 confidence to apply any changes at all
          - 3 consecutive low-confidence sessions → emergency reset to defaults

        The value_tracker logs every parameter change with the council's
        recommended value vs the rate-limited applied value, enabling
        counterfactual analysis: "what would have happened if we applied
        the council's recommendation without rate limiting?"
        """
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
        """Persist falsifiable predictions emitted by the final council assessments.

        Each agent can emit a prediction like "SPY will be above 520 by
        April 15".  These are stored in council_calibrations and verified
        later to build a calibration curve — are agents that say 80%
        confidence actually right 80% of the time?  This is the only way
        to tell if the council is well-calibrated or overconfident.
        """
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
        """Construct the structured v2 session payload and dissent summary.

        The dissent list explicitly captures minority-opinion agents.
        This is critical for the Modified Delphi protocol: dissent is
        signal, not noise.  A 4-1 vote where the lone dissenter is
        red_team may carry more information than a 5-0 rubber stamp.
        """
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
        """Write the final council outcome back onto the session row.

        Uses tally_votes() to compute the old-schema consensus string
        for backward compatibility with dashboard queries that filter
        by consensus = 'bullish'/'bearish'.  The v2 aggregation data
        is stored as JSON in result_json for richer programmatic access.
        """
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
        """Finalize a session that ended early due to errors.

        Even crashed sessions get a database record with is_contested=1
        and direction='incomplete'.  This prevents silent data gaps in
        the council session history and makes failures visible in the
        dashboard timeline.
        """
        cost = _estimate_session_cost(rounds_completed)

        aggregation = None
        if assessments:
            aggregation = aggregate_votes(assessments, session_type, db_path=self.db_path)

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

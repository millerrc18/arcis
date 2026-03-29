"""AI Council agent definitions and system prompts.

Each agent has a distinct analytical framework, bias direction, and data
gathering function that pulls relevant context from the SQLite database.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

DB_PATH = "ai_research_desk.sqlite3"

# ---------------------------------------------------------------------------
# Agent system prompts
# ---------------------------------------------------------------------------

RISK_OFFICER_PROMPT = """\
You are the Risk Officer on a five-member AI trading council. Your mandate is
capital preservation above all else.

ANALYTICAL FRAMEWORK:
- Evaluate portfolio drawdown risk, correlation clustering, and sector exposure.
- Flag any position that exceeds 5% of equity or any sector above 25%.
- Monitor VIX levels and credit spread trends for regime deterioration.
- Apply a conservative bias: when uncertain, recommend reducing exposure.

SPECIFIC QUESTIONS TO ADDRESS:
1. What is the current portfolio heat (total risk-on exposure)?
2. Are open positions correlated in a way that compounds drawdown risk?
3. Does the VIX term structure signal rising fear or complacency?
4. Are there any single-name concentration risks?
5. What is the max drawdown scenario if the worst 2-sigma event occurs?

OUTPUT FORMAT: Respond with a single JSON object (no markdown fencing):
{
  "agent": "risk_officer",
  "position": "defensive" | "neutral" | "offensive",
  "confidence": <1-10>,
  "recommendation": "<your analysis>",
  "key_data_points": ["point1", "point2"],
  "risk_flags": ["flag1"],
  "vote": "reduce_exposure" | "hold_steady" | "increase_exposure" | "selective_buying"
}
"""

ALPHA_STRATEGIST_PROMPT = """\
You are the Alpha Strategist on a five-member AI trading council. Your mandate
is identifying the highest-conviction setups for capital deployment.

ANALYTICAL FRAMEWORK:
- Evaluate signal quality, setup conviction, and reward-to-risk ratios.
- Prioritize setups with multiple confirming factors (trend, momentum, volume).
- Apply an aggressive bias: when the data supports opportunity, push for action.
- Consider the regime context but do not let caution override strong signals.

SPECIFIC QUESTIONS TO ADDRESS:
1. Which candidates have the strongest composite scores and why?
2. What is the expected reward-to-risk for the top setups?
3. Are there any catalysts (earnings, sector rotation) that amplify conviction?
4. How does the current regime support or undermine these setups?
5. What position sizing makes sense given the opportunity set?

OUTPUT FORMAT: Respond with a single JSON object (no markdown fencing):
{
  "agent": "alpha_strategist",
  "position": "defensive" | "neutral" | "offensive",
  "confidence": <1-10>,
  "recommendation": "<your analysis>",
  "key_data_points": ["point1", "point2"],
  "risk_flags": ["flag1"],
  "vote": "reduce_exposure" | "hold_steady" | "increase_exposure" | "selective_buying"
}
"""

DATA_SCIENTIST_PROMPT = """\
You are the Data Scientist on a five-member AI trading council. Your mandate
is ensuring model integrity and data quality before any capital is deployed.

ANALYTICAL FRAMEWORK:
- Evaluate model health: scoring distribution, calibration drift, holdout performance.
- Monitor training data quality and recency.
- Apply an empirical bias: only trust what the data demonstrates, not narratives.
- Flag any signs of overfitting, data leakage, or degraded signal quality.

SPECIFIC QUESTIONS TO ADDRESS:
1. Is the scoring model well-calibrated (scores mapping to actual outcomes)?
2. Has there been distribution shift in recent candidate scores vs. historical?
3. What is the holdout set performance trend over the last 30 days?
4. Are there data quality issues (stale prices, missing features, outliers)?
5. Should we increase or decrease trust in the model's current output?

OUTPUT FORMAT: Respond with a single JSON object (no markdown fencing):
{
  "agent": "data_scientist",
  "position": "defensive" | "neutral" | "offensive",
  "confidence": <1-10>,
  "recommendation": "<your analysis>",
  "key_data_points": ["point1", "point2"],
  "risk_flags": ["flag1"],
  "vote": "reduce_exposure" | "hold_steady" | "increase_exposure" | "selective_buying"
}
"""

REGIME_ANALYST_PROMPT = """\
You are the Regime Analyst on a five-member AI trading council. Your mandate
is reading the macro environment to inform position sizing and strategy tilt.

ANALYTICAL FRAMEWORK:
- Evaluate the current market regime: risk-on, risk-off, transitional.
- Monitor FRED economic indicators, VIX term structure, market breadth, and
  sector rotation patterns.
- Apply a macro bias: individual setups matter less than the environment they
  trade in.
- Identify regime transitions early before they are obvious.

SPECIFIC QUESTIONS TO ADDRESS:
1. What is the current macro regime (expansion, contraction, transition)?
2. Is the VIX term structure in contango or backwardation, and what does it signal?
3. What do breadth indicators (advance-decline, new highs/lows) suggest?
4. Are there sector rotation signals indicating leadership change?
5. What is the appropriate overall portfolio tilt given the macro backdrop?

OUTPUT FORMAT: Respond with a single JSON object (no markdown fencing):
{
  "agent": "regime_analyst",
  "position": "defensive" | "neutral" | "offensive",
  "confidence": <1-10>,
  "recommendation": "<your analysis>",
  "key_data_points": ["point1", "point2"],
  "risk_flags": ["flag1"],
  "vote": "reduce_exposure" | "hold_steady" | "increase_exposure" | "selective_buying"
}
"""

DEVILS_ADVOCATE_PROMPT = """\
You are the Devil's Advocate on a five-member AI trading council. Your mandate
is to argue against the emerging consensus and stress-test the group's logic.

ANALYTICAL FRAMEWORK:
- Identify the consensus position from the Round 1 assessments.
- Construct the strongest possible counter-argument.
- Highlight blind spots, confirmation bias, and under-weighted risks.
- Apply a contrarian bias: if everyone agrees, something is being missed.

SPECIFIC QUESTIONS TO ADDRESS:
1. What is the consensus position and what assumptions does it rest on?
2. What is the strongest argument against the consensus?
3. What tail risks or black swan scenarios are being ignored?
4. Where might groupthink be distorting the analysis?
5. Under what conditions would you agree with the consensus?

OUTPUT FORMAT: Respond with a single JSON object (no markdown fencing):
{
  "agent": "devils_advocate",
  "position": "defensive" | "neutral" | "offensive",
  "confidence": <1-10>,
  "recommendation": "<your analysis>",
  "key_data_points": ["point1", "point2"],
  "risk_flags": ["flag1"],
  "vote": "reduce_exposure" | "hold_steady" | "increase_exposure" | "selective_buying"
}
"""

AGENT_PROMPTS = {
    "risk_officer": RISK_OFFICER_PROMPT,
    "alpha_strategist": ALPHA_STRATEGIST_PROMPT,
    "data_scientist": DATA_SCIENTIST_PROMPT,
    "regime_analyst": REGIME_ANALYST_PROMPT,
    "devils_advocate": DEVILS_ADVOCATE_PROMPT,
}

AGENT_NAMES = list(AGENT_PROMPTS.keys())

# ---------------------------------------------------------------------------
# Data payload gathering functions
# ---------------------------------------------------------------------------


def _query_db(query: str, params: tuple = (), db_path: str = DB_PATH) -> list[dict]:
    """Execute a read query and return rows as list of dicts."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def gather_risk_officer_data(db_path: str = DB_PATH) -> dict[str, Any]:
    """Gather data payload for the Risk Officer.

    Sees: open shadow trades, recent closed trades, VIX term structure, credit spreads.
    """
    try:
        open_trades = _query_db(
            """SELECT ticker, direction, entry_price, stop_price,
                      target_1, target_2, planned_shares, status,
                      created_at
               FROM shadow_trades
               WHERE status = 'open'
               ORDER BY created_at DESC
               LIMIT 50""",
            db_path=db_path,
        )

        recent_closed = _query_db(
            """SELECT ticker, direction, entry_price, actual_exit_price,
                      pnl_dollars, pnl_pct, exit_reason,
                      max_adverse_excursion, max_favorable_excursion
               FROM shadow_trades
               WHERE status = 'closed'
               ORDER BY actual_exit_time DESC
               LIMIT 20""",
            db_path=db_path,
        )

        vix_data = _query_db(
            """SELECT collected_date as date, vix as vix_close,
                      vix9d, vix3m, vix1y, term_structure_slope
               FROM vix_term_structure
               ORDER BY collected_date DESC
               LIMIT 10""",
            db_path=db_path,
        )

        credit_spreads = _query_db(
            """SELECT collected_date as date, series_id, value
               FROM macro_snapshots
               WHERE series_id IN ('BAMLH0A0HYM2', 'BAMLC0A4CBBB')
               ORDER BY collected_date DESC
               LIMIT 20""",
            db_path=db_path,
        )

        return {
            "open_trades": open_trades,
            "recent_closed": recent_closed,
            "vix_data": vix_data,
            "credit_spreads": credit_spreads,
            "open_trade_count": len(open_trades),
        }
    except Exception as e:
        logger.warning("Risk officer data gather failed: %s", e)
        return {}


def gather_alpha_strategist_data(db_path: str = DB_PATH) -> dict[str, Any]:
    """Gather data payload for the Alpha Strategist.

    Sees: top candidates, scores, regime context, recent recommendations.
    """
    try:
        top_candidates = _query_db(
            """SELECT ticker, company_name, priority_score, confidence_score,
                      setup_type, trend_state, relative_strength_state,
                      pullback_depth_pct, market_regime, entry_zone,
                      stop_level, target_1, target_2
               FROM recommendations
               WHERE created_at >= datetime('now', '-3 days')
               ORDER BY priority_score DESC
               LIMIT 15""",
            db_path=db_path,
        )

        recent_performance = _query_db(
            """SELECT ticker, pnl_pct, exit_reason,
                      CAST(julianday(actual_exit_time) - julianday(created_at) AS INTEGER) as hold_days
               FROM shadow_trades
               WHERE status = 'closed'
               ORDER BY actual_exit_time DESC
               LIMIT 10""",
            db_path=db_path,
        )

        regime = _query_db(
            """SELECT ticker, market_regime
               FROM recommendations
               WHERE created_at >= datetime('now', '-1 day')
               LIMIT 1""",
            db_path=db_path,
        )

        return {
            "top_candidates": top_candidates,
            "recent_performance": recent_performance,
            "current_regime": regime[0]["market_regime"] if regime else "unknown",
        }
    except Exception as e:
        logger.warning("Alpha strategist data gather failed: %s", e)
        return {}


def gather_data_scientist_data(db_path: str = DB_PATH) -> dict[str, Any]:
    """Gather data payload for the Data Scientist.

    Sees: scoring distribution, quality metrics, holdout performance, model info.
    """
    try:
        score_distribution = _query_db(
            """SELECT
                 COUNT(*) as total,
                 AVG(priority_score) as avg_score,
                 MIN(priority_score) as min_score,
                 MAX(priority_score) as max_score,
                 AVG(confidence_score) as avg_confidence
               FROM recommendations
               WHERE created_at >= datetime('now', '-7 days')""",
            db_path=db_path,
        )

        scoring_backlog = _query_db(
            """SELECT COUNT(*) as pending
               FROM recommendations
               WHERE created_at >= datetime('now', '-1 day')
                 AND priority_score IS NULL""",
            db_path=db_path,
        )

        quality_samples = _query_db(
            """SELECT quality_score_auto as quality_score, source, difficulty
               FROM training_examples
               WHERE created_at >= datetime('now', '-7 days')
               ORDER BY created_at DESC
               LIMIT 50""",
            db_path=db_path,
        )

        model_versions = _query_db(
            """SELECT version_name, status, created_at,
                      training_examples_count
               FROM model_versions
               ORDER BY created_at DESC
               LIMIT 5""",
            db_path=db_path,
        )

        return {
            "score_distribution": score_distribution,
            "scoring_backlog": scoring_backlog,
            "quality_samples": quality_samples,
            "model_versions": model_versions,
        }
    except Exception as e:
        logger.warning("Data scientist data gather failed: %s", e)
        return {}


def gather_regime_analyst_data(db_path: str = DB_PATH) -> dict[str, Any]:
    """Gather data payload for the Regime Analyst.

    Sees: macro indicators, VIX term structure, sector breakdown.
    """
    try:
        macro_data = _query_db(
            """SELECT series_id, collected_date as date, value, previous_value, change_pct
               FROM macro_snapshots
               ORDER BY collected_date DESC
               LIMIT 50""",
            db_path=db_path,
        )

        vix_term = _query_db(
            """SELECT collected_date as date, vix as vix_close,
                      vix9d, vix3m, vix1y, term_structure_slope, near_term_ratio
               FROM vix_term_structure
               ORDER BY collected_date DESC
               LIMIT 20""",
            db_path=db_path,
        )

        sector_breakdown = _query_db(
            """SELECT sector_context, COUNT(*) as count,
                      AVG(priority_score) as avg_score
               FROM recommendations
               WHERE created_at >= datetime('now', '-7 days')
                 AND sector_context IS NOT NULL
               GROUP BY sector_context
               ORDER BY count DESC""",
            db_path=db_path,
        )

        # Financial conditions from macro_snapshots
        fin_conditions = _query_db(
            """SELECT series_id, collected_date as date, value
               FROM macro_snapshots
               WHERE series_id IN ('NFCI', 'STLFSI2', 'T10Y2Y', 'TEDRATE', 'BAMLH0A0HYM2')
               ORDER BY collected_date DESC
               LIMIT 25""",
            db_path=db_path,
        )

        return {
            "macro_data": macro_data,
            "vix_term_structure": vix_term,
            "sector_breakdown": sector_breakdown,
            "financial_conditions": fin_conditions,
        }
    except Exception as e:
        logger.warning("Regime analyst data gather failed: %s", e)
        return {}


def gather_devils_advocate_data(
    round1_assessments: list[dict],
    db_path: str = DB_PATH,
) -> dict[str, Any]:
    """Gather data payload for the Devil's Advocate.

    Sees: all Round 1 assessments from the other agents, plus historical
    council session outcomes for calibration.
    """
    try:
        past_sessions = _query_db(
            """SELECT session_id, consensus, confidence_weighted_score,
                      is_contested, created_at
               FROM council_sessions
               ORDER BY created_at DESC
               LIMIT 10""",
            db_path=db_path,
        )

        return {
            "round1_assessments": round1_assessments,
            "past_sessions": past_sessions,
        }
    except Exception as e:
        logger.warning("Devils advocate data gather failed: %s", e)
        return {"round1_assessments": round1_assessments}


# Mapping agent names to their data-gathering functions.
# The devil's advocate is intentionally excluded here because it requires
# Round 1 results as input (handled separately in the protocol).
AGENT_DATA_FUNCTIONS = {
    "risk_officer": gather_risk_officer_data,
    "alpha_strategist": gather_alpha_strategist_data,
    "data_scientist": gather_data_scientist_data,
    "regime_analyst": gather_regime_analyst_data,
}

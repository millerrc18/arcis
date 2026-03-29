"""LLM-as-Judge quality scoring for training examples.

Process-first rubric: scores analytical process blind to trade outcome,
then applies outcome-conditional overlays.
"""

import json
import logging
import re
import sqlite3

from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)

QUALITY_JUDGE_PROMPT = """You are scoring equity trade commentary for training data quality.

IMPORTANT: Score the PROCESS quality of the analysis — not whether the trade made money. You will NOT be told the outcome. Excellent analysis of a losing trade should score as high as excellent analysis of a winning trade.

Score each dimension 1-5 using these behavioral anchors:

1. THESIS CLARITY AND DIFFERENTIATION (weight: 25%)
   1 = Restates obvious facts ("stock pulled back 5%") with no analytical value
   2 = Identifies setup mechanically, doesn't explain why this pullback is a buying opportunity
   3 = Clear thesis with entry logic, but generic — could apply to any pullback in any stock
   4 = Names what the market is mispricing, identifies a catalyst within a timeframe, explains why pullback is noise not trend change
   5 = All of 4, plus quantifies expected move, places setup in historical context, articulates what consensus is missing

2. EVIDENCE GROUNDING (weight: 20%)
   1 = Purely qualitative assertions, no numbers
   2 = Some numbers but generic (market cap, last close) rather than analytically relevant
   3 = Cites relevant quantitative evidence (RSI, volume, multiples) but doesn't synthesize across data points
   4 = Integrates multiple quantitative signals into a coherent narrative with cross-source synthesis
   5 = All of 4, plus relative comparisons (vs sector, vs historical), notes data quality or limitations

3. RISK IDENTIFICATION (weight: 20%)
   1 = No risk discussion
   2 = Boilerplate risk language ("markets are volatile")
   3 = Names 1-2 genuine risks without quantifying impact
   4 = Identifies the specific thesis-killer plus 2-3 additional risks with estimated impact. Includes defined stop/exit.
   5 = Explicit bull/base/bear scenarios, identifies what information would change conviction, acknowledges base rates

4. CALIBRATION AND UNCERTAINTY (weight: 15%)
   1 = All categorical certainty, zero hedging ("the stock will rally to $200")
   2 = Weak boilerplate hedging ("results may vary")
   3 = Appropriate epistemic markers ("likely," "our base case") but not linked to evidence strength
   4 = Conviction explicitly linked to evidence quality ("strong support at $185 tested 4 times + institutional accumulation = moderate-high conviction")
   5 = All of 4, plus conditional reasoning ("if stock fails $182 within 3 sessions, thesis invalidated"), acknowledges unknowables

5. STRUCTURE AND COMMUNICATION (weight: 10%)
   1 = Disorganized, rambling, no clear flow
   2 = Basic structure but buries the conclusion after lengthy background
   3 = Clear sections, leads with thesis, readable
   4 = Conclusion-oriented, concise, every fact connected to trade implications
   5 = All of 4, plus professional institutional tone, appropriate length, no filler sentences

6. ACTIONABILITY (weight: 10%)
   1 = No entry, exit, or sizing information
   2 = Vague timing ("consider buying on weakness")
   3 = Specific entry level OR stop level, but not both
   4 = Entry zone, stop level, and at least one target with rationale
   5 = All of 4, plus position sizing context, timeframe for reassessment

Respond with ONLY a JSON object:
{
  "thesis_clarity": N,
  "evidence_grounding": N,
  "risk_identification": N,
  "calibration": N,
  "structure": N,
  "actionability": N,
  "weighted_overall": N.N,
  "process_quality": "excellent" / "good" / "adequate" / "poor",
  "issues": "brief note on the 1-2 most important improvements needed"
}

The weighted_overall should be: (thesis*0.25 + evidence*0.20 + risk*0.20 + calibration*0.15 + structure*0.10 + actionability*0.10), rounded to 1 decimal.
"""


def _compute_outcome_overlay(output_text: str, outcome: str) -> dict:
    """Compute outcome-conditional quality overlay.

    This is NOT used to adjust the process score. It's stored separately
    for analysis — tracking whether the model's commentary is appropriately
    calibrated across wins and losses.

    Args:
        output_text: The generated commentary
        outcome: "win", "loss", or "breakeven"

    Returns:
        {
            "outcome": "win",
            "annie_duke_quadrant": "good_process_good_outcome",
        }
    """
    return {"outcome": outcome}


def score_training_example(input_text: str, output_text: str,
                           outcome: str | None = None) -> dict | None:
    """Score a training example using Claude as judge.

    Stage 1: Score process quality WITHOUT outcome information.
    Stage 2 (optional): If outcome is provided, apply outcome-conditional overlay.

    The overlay checks:
    - For wins: Does the commentary acknowledge lucky factors? Unrealized risks?
    - For losses: Does it separate process from result? Classify the loss type?
    """
    from src.training.claude_client import generate_training_example

    # Stage 1: Process-blind scoring
    prompt = (
        f"Rate this trade commentary for training data quality.\n\n"
        f"INPUT DATA:\n{input_text[:1500]}\n\n"
        f"COMMENTARY TO SCORE:\n{output_text[:2000]}"
    )
    response = generate_training_example(QUALITY_JUDGE_PROMPT, prompt, purpose="scoring")

    if response is None:
        return None

    try:
        # Strip markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.removeprefix("```json").removeprefix("```")
        if clean.endswith("```"):
            clean = clean.removesuffix("```")
        clean = clean.strip()

        # Try direct parse first, then regex fallback
        try:
            scores = json.loads(clean)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[^}]+\}', clean, re.DOTALL)
            if json_match:
                scores = json.loads(json_match.group())
            else:
                return None

        # Compute weighted_overall if not provided or verify
        dims = {
            "thesis_clarity": 0.25,
            "evidence_grounding": 0.20,
            "risk_identification": 0.20,
            "calibration": 0.15,
            "structure": 0.10,
            "actionability": 0.10,
        }
        weighted = sum(scores.get(d, 3) * w for d, w in dims.items())
        scores["weighted_overall"] = round(weighted, 1)

        # Classify process quality
        if weighted >= 4.0:
            scores["process_quality"] = "excellent"
        elif weighted >= 3.0:
            scores["process_quality"] = "good"
        elif weighted >= 2.0:
            scores["process_quality"] = "adequate"
        else:
            scores["process_quality"] = "poor"

        # Backward compatibility: also store as "overall"
        scores["overall"] = scores["weighted_overall"]

    except (json.JSONDecodeError, ValueError, AttributeError):
        logger.warning("[QUALITY] Failed to parse judge response")
        return None

    # Stage 2: Outcome overlay (optional)
    if outcome and scores:
        scores["outcome_overlay"] = _compute_outcome_overlay(output_text, outcome)

    return scores


def score_all_unscored(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Score all training examples without quality_score_auto. Returns summary stats."""
    init_training_tables(db_path)

    # Ensure column exists
    with sqlite3.connect(db_path) as conn:
        try:
            conn.execute("ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL")
        except sqlite3.OperationalError:
            pass

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT example_id, input_text, output_text, source "
            "FROM training_examples WHERE quality_score_auto IS NULL"
        ).fetchall()

    if not rows:
        return {"scored": 0, "avg_score": 0, "skipped": 0}

    scored = 0
    skipped = 0
    total_score = 0.0

    for row in rows:
        # Determine outcome from source for overlay
        source = row["source"] or ""
        outcome = None
        if "win" in source:
            outcome = "win"
        elif "loss" in source:
            outcome = "loss"

        scores = score_training_example(row["input_text"], row["output_text"], outcome)
        if scores and "weighted_overall" in scores:
            overall = scores["weighted_overall"]
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE training_examples SET quality_score_auto = ? WHERE example_id = ?",
                    (overall, row["example_id"]),
                )
                conn.commit()
            scored += 1
            total_score += overall
        else:
            skipped += 1

    avg = total_score / scored if scored > 0 else 0

    logger.info("[QUALITY] Scored %d examples (avg: %.2f), skipped %d", scored, avg, skipped)
    return {"scored": scored, "avg_score": round(avg, 2), "skipped": skipped}

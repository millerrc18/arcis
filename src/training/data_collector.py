"""Training data collection from closed trades using the self-blinding pipeline."""

import json
import logging
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import load_config
from src.llm.prompts import BLINDED_ANALYSIS_PROMPT, QUALITY_ENHANCEMENT_PROMPT
from src.training.claude_client import generate_training_example
from src.training.ingestion_gate import (
    alert_training_halt,
    should_halt_batch,
    validate_training_example,
)
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def _build_feature_input(rec: dict) -> str:
    """Build structured feature text from a recommendation record."""
    return f"""Ticker: {rec.get('ticker', 'N/A')} ({rec.get('company_name', 'N/A')})
Current Price: ${rec.get('price_at_recommendation', 0):.2f}
Trend State: {rec.get('trend_state', 'n/a')}
Relative Strength: {rec.get('relative_strength_state', 'n/a')}
Pullback Depth: {rec.get('pullback_depth_pct', 0):.1f}% from 50-day high
ATR(14): ${rec.get('atr', 0):.2f}
Volume State: {rec.get('volume_state', 'n/a')}
Score: {rec.get('priority_score', 0):.0f}/100 | Confidence: {rec.get('confidence_score', 0):.0f}/10
Entry Zone: {rec.get('entry_zone', 'n/a')} | Stop: {rec.get('stop_level', 'n/a')} | Targets: {rec.get('target_1', 'n/a')} / {rec.get('target_2', 'n/a')}
Event Risk: {rec.get('event_risk_flag', 'none')}"""


def _build_outcome_text(trade: dict) -> str:
    """Build outcome text from a closed shadow trade.

    NOTE: This is stored for metadata/evaluation only — it is NEVER included
    in prompts sent to Claude during the self-blinding pipeline.
    """
    return f"""=== ACTUAL OUTCOME ===
Exit Reason: {trade.get('exit_reason', 'n/a')}
P&L: ${trade.get('pnl_dollars', 0):.2f} ({trade.get('pnl_pct', 0):.1f}%)
Duration: {trade.get('duration_days', 0)} days
MFE: ${trade.get('max_favorable_excursion', 0):.2f} | MAE: ${trade.get('max_adverse_excursion', 0):.2f}"""


def collect_training_examples_from_closed_trades(
    db_path: str = "ai_research_desk.sqlite3",
) -> int:
    """Generate training examples from closed trades using the self-blinding pipeline.

    The self-blinding pipeline ensures NO outcome information leaks into the
    generated commentary. This is architecturally enforced, not instructionally:

    Stage 1 (Blinded): Claude receives ONLY the setup data — zero outcome info.
                       Generates genuine pre-trade analysis with authentic uncertainty.

    Stage 2 (Enhancement): Claude receives ONLY the Stage 1 output plus writing
                          quality instructions. Still no outcome. Improves prose
                          without changing directional stance or conviction.

    Returns count of new examples created.
    """
    config = load_config()
    training_cfg = config.get("training", {})
    if not training_cfg.get("enabled", False):
        return 0

    init_training_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT st.*, r.*
            FROM shadow_trades st
            JOIN recommendations r ON st.recommendation_id = r.recommendation_id
            WHERE st.status = 'closed'
              AND st.recommendation_id NOT IN (
                  SELECT recommendation_id FROM training_examples
                  WHERE recommendation_id IS NOT NULL
              )
            ORDER BY st.actual_exit_time DESC
        """).fetchall()

    count = 0
    attempted = 0
    rejected = 0
    rejection_reasons: Counter[str] = Counter()
    for row in rows:
        trade = dict(row)

        # Use the full enriched prompt if available, fall back to basic rebuild
        enriched = trade.get("enriched_prompt")
        if enriched:
            feature_input = enriched
        else:
            feature_input = _build_feature_input(trade)

        # Get the scan/recommendation date for the blinded prompt
        rec_date = (trade.get("created_at") or "")[:10]  # YYYY-MM-DD

        # ═══ STAGE 1: BLINDED GENERATION ═══
        # Claude sees ONLY the setup data — ZERO outcome information
        blinded_prompt = BLINDED_ANALYSIS_PROMPT.format(date=rec_date)
        stage1_response = generate_training_example(blinded_prompt, feature_input, purpose="backfill_blinded")
        if stage1_response is None:
            logger.warning("[TRAINING] Stage 1 failed for %s, skipping", trade.get("ticker"))
            continue

        # ═══ STAGE 2: QUALITY ENHANCEMENT ═══
        # Claude sees ONLY the Stage 1 output — still no outcome
        enhancement_input = f"ORIGINAL INPUT DATA:\n{feature_input}\n\nDRAFT ANALYSIS:\n{stage1_response}"
        stage2_response = generate_training_example(QUALITY_ENHANCEMENT_PROMPT, enhancement_input, purpose="backfill_enhancement")

        # Use Stage 2 if successful, fall back to Stage 1
        final_output = stage2_response if stage2_response else stage1_response
        attempted += 1

        is_valid, rejection_reason = validate_training_example(final_output, db_path)
        if not is_valid:
            rejected += 1
            rejection_reasons[rejection_reason] += 1
            logger.warning("[TRAINING] Rejected example for %s: %s", trade.get("ticker"), rejection_reason)
            halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
            if halt:
                alert_training_halt(compliance, rejected, attempted, top_reason)
                logger.error("[TRAINING] Halting collection batch at %.1f%% compliance", compliance)
                break
            continue

        # ═══ STORE THE EXAMPLE ═══
        pnl = trade.get("pnl_dollars", 0) or 0
        source = "blinded_win" if pnl > 0 else "blinded_loss"

        # Store the outcome for metadata (NOT in the training example itself)
        outcome_text = _build_outcome_text(trade)

        example_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO training_examples
                   (example_id, created_at, source, ticker, recommendation_id,
                    feature_snapshot, trade_outcome, instruction, input_text, output_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (example_id, created_at, source, trade.get("ticker"),
                 trade.get("recommendation_id"), feature_input, outcome_text,
                 blinded_prompt, feature_input, final_output),
            )
            conn.commit()

        logger.info("  [TRAINING] Generated blinded example for %s (%s)", trade.get('ticker'), source)
        count += 1

        halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
        if halt:
            alert_training_halt(compliance, rejected, attempted, top_reason)
            logger.error("[TRAINING] Halting collection batch at %.1f%% compliance", compliance)
            break

    return count

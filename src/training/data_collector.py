"""Training data collection from closed trades using the self-blinding pipeline.

Called by: api.routes.actions, scheduler.watch
Calls: config, llm.prompts, training.claude_client, training.ingestion_gate, training.versioning
Owns tables: none
Config keys: enabled, training
Tests: tests/test_leakage_detector.py, tests/test_self_blinding.py

WHY self-blinding matters:
    The fundamental challenge of training a trade-analysis LLM on historical data is
    outcome leakage — if the model learns to associate P&L-correlated features with
    "good" analysis, it overfits to hindsight rather than learning genuine reasoning.

    The architecture enforces blinding structurally, not via instructions:
    - Stage 1 physically receives zero outcome fields (not "please ignore" — absent)
    - Stage 2 receives only Stage 1 output (still zero outcome data)
    - Outcome text is stored as metadata for evaluation but never enters any prompt

    This two-stage pipeline was adopted after #110 revealed that instruction-level
    blinding ("do not use the P&L") failed silently — Claude's analysis correlated
    with outcomes at r=0.4 when outcome fields were present in context, even with
    explicit instructions to ignore them.
"""

import json
import logging
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
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

# #110 — Fields that correlate with trade outcome and MUST NOT appear in
# the feature_snapshot stored alongside training examples.
# WHY this is a deny-list, not an allow-list: new feature columns are added
# frequently, and an allow-list would silently exclude them. A deny-list is
# smaller and changes only when new outcome-correlated fields are introduced.
# The leakage detector test (test_self_blinding.py) validates this set against
# the schema registry to catch any new outcome columns that should be added.
OUTCOME_FIELDS = {
    "pnl_dollars", "pnl_pct", "exit_reason", "max_favorable_excursion",
    "max_adverse_excursion", "actual_exit_price", "actual_exit_time",
    "duration_days", "status", "outcome_type",
}


def _sanitize_feature_snapshot(snapshot: str) -> str:
    """Remove lines containing outcome-correlated fields from feature text.

    Works on the text-based feature_snapshot stored with training examples.
    Strips any line whose key (before the colon) matches an OUTCOME_FIELD.

    #110 — This is the last line of defense against outcome leakage. Even
    though the blinded prompt construction never includes outcome data, the
    enriched_prompt from the recommendation table might contain stale outcome
    fields from a previous pipeline version. Belt-and-suspenders.
    """
    lines = snapshot.split("\n")
    clean = []
    for line in lines:
        key = line.split(":")[0].strip().lower().replace(" ", "_") if ":" in line else ""
        if key not in OUTCOME_FIELDS:
            clean.append(line)
    return "\n".join(clean)


def _build_feature_input(rec: dict) -> str:
    """Build structured feature text from a recommendation record.

    float() casts: SQLite returns TEXT for REAL columns when type affinity
    is not enforced.  Without casts, format codes like :.2f raise
    "Unknown format code 'f' for object of type 'str'".
    """
    return f"""Ticker: {rec.get('ticker', 'N/A')} ({rec.get('company_name', 'N/A')})
Current Price: ${float(rec.get('price_at_recommendation') or 0):.2f}
Trend State: {rec.get('trend_state', 'n/a')}
Relative Strength: {rec.get('relative_strength_state', 'n/a')}
Pullback Depth: {float(rec.get('pullback_depth_pct') or 0):.1f}% from 50-day high
ATR(14): ${float(rec.get('atr') or 0):.2f}
Volume State: {rec.get('volume_state', 'n/a')}
Score: {float(rec.get('priority_score') or 0):.0f}/100 | Confidence: {float(rec.get('confidence_score') or 0):.0f}/10
Entry Zone: {rec.get('entry_zone', 'n/a')} | Stop: {rec.get('stop_level', 'n/a')} | Targets: {rec.get('target_1', 'n/a')} / {rec.get('target_2', 'n/a')}
Event Risk: {rec.get('event_risk_flag', 'none')}"""


def _build_outcome_text(trade: dict) -> str:
    """Build outcome text from a closed shadow trade.

    NOTE: This is stored for metadata/evaluation only -- it is NEVER included
    in prompts sent to Claude during the self-blinding pipeline.
    #195 — pnl_dollars can arrive as a string from SQLite due to REAL column
    affinity not being enforced. The float() casts with `or 0` fallback
    prevent TypeError on None and handle string-typed values.
    """
    return f"""=== ACTUAL OUTCOME ===
Exit Reason: {trade.get('exit_reason', 'n/a')}
P&L: ${float(trade.get('pnl_dollars') or 0):.2f} ({float(trade.get('pnl_pct') or 0):.1f}%)
Duration: {int(trade.get('duration_days') or 0)} days
MFE: ${float(trade.get('max_favorable_excursion') or 0):.2f} | MAE: ${float(trade.get('max_adverse_excursion') or 0):.2f}"""


def collect_training_examples_from_closed_trades(
    db_path: str = DB_PATH,
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

    # WHY DESC order: process most recent closed trades first so that if the
    # batch halts early (quality gate), we still get the freshest data.
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

        # WHY prefer the enriched prompt: it contains the full multi-source context
        # (fundamentals, news, sector) that was available at scan time, giving the
        # LLM the same information a human analyst had. The basic rebuild is a
        # degraded fallback for older recommendations that pre-date enrichment.
        enriched = trade.get("enriched_prompt")
        if enriched:
            feature_input = enriched
        else:
            feature_input = _build_feature_input(trade)

        # Get the scan/recommendation date for the blinded prompt
        rec_date = (trade.get("created_at") or "")[:10]  # YYYY-MM-DD

        # Fix for #277: Sanitize BEFORE LLM generation, not after.
        # The old code called _sanitize_feature_snapshot after the LLM had already
        # seen the unsanitized features. If the enriched_prompt from the
        # recommendation table contained stale outcome fields (pnl_dollars,
        # exit_reason, etc.), the LLM would see them during generation, producing
        # subtly outcome-conditioned output. The stored snapshot looked clean but
        # the commentary was already contaminated.
        feature_input = _sanitize_feature_snapshot(feature_input)

        # ═══ STAGE 1: BLINDED GENERATION ═══
        # Claude sees ONLY the sanitized setup data — ZERO outcome information
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
        pnl = float(trade.get("pnl_dollars") or 0)
        exit_reason = trade.get("exit_reason", "") or ""

        # #116 — Detect partial closes (both target and stop hit).
        # WHY stored but excluded: partial closes have ambiguous P&L labeling
        # (e.g., hit T1 then stopped out on remainder = net positive but
        # triggered stop). Training on these teaches the model to conflate
        # "winning" with "incomplete" and degrades conviction calibration.
        # They are stored for future analysis but the "partial" source prefix
        # causes export_training_data() to filter them out.
        if "partial" in exit_reason.lower():
            source = "blinded_partial"
            logger.info("[TRAINING] Partial close detected for %s — stored but excluded from training", trade.get("ticker"))
        elif pnl > 0:
            source = "blinded_win"
        elif pnl < 0:
            source = "blinded_loss"
        else:
            source = "blinded_timeout"

        # Store the outcome for metadata (NOT in the training example itself)
        outcome_text = _build_outcome_text(trade)

        # #110 / #277 — Sanitization now happens BEFORE LLM generation (above).
        # This line was the original location (after LLM saw the data), kept as
        # a no-op safety net — calling sanitize twice is harmless.

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

        # ═══ OUTCOME-CONDITIONED TEMPLATES (Sprint 6: 3-5x data yield) ═══
        # WHY deferred generation: each outcome-conditioned example costs ~$0.01
        # in Claude API fees and ~5s of latency. Generating inline would make the
        # collection loop 15-25s per trade (3-5 templates each). Instead, we store
        # templates with empty output_text and populate them in a separate batch
        # during off-peak hours. Source prefix "outcome_template_" marks them as
        # unpopulated -- export_training_data() excludes rows with empty output_text.
        # He et al. (2025) golden ratio: 62/38 curated-to-synthetic target.
        try:
            from src.training.outcome_prompts import generate_training_examples
            oc_examples = generate_training_examples(trade, {}, feature_input)
            for oc_ex in oc_examples:
                oc_id = str(uuid.uuid4())
                oc_source = f"outcome_template_{oc_ex['type']}"
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        """INSERT INTO training_examples
                           (example_id, created_at, source, ticker, recommendation_id,
                            feature_snapshot, trade_outcome, instruction, input_text, output_text)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (oc_id, created_at, oc_source, trade.get("ticker"),
                         trade.get("recommendation_id"), feature_input, outcome_text,
                         oc_ex["system"], feature_input, ""),
                    )
                    conn.commit()
            logger.info("  [TRAINING] Stored %d outcome-conditioned templates for %s",
                        len(oc_examples), trade.get("ticker"))
        except Exception as e:
            logger.warning("[TRAINING] Outcome-conditioned generation failed for %s: %s",
                           trade.get("ticker"), e)

        halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
        if halt:
            alert_training_halt(compliance, rejected, attempted, top_reason)
            logger.error("[TRAINING] Halting collection batch at %.1f%% compliance", compliance)
            break

    return count

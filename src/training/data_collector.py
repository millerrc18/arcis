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
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.llm.prompts import QUALITY_ENHANCEMENT_PROMPT
from src.training.claude_client import ClaudeAuthError, generate_training_example
from src.training.ingestion_gate import (
    alert_training_halt,
    should_halt_batch,
    validate_training_example,
)
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


# #615 — Structured collection summary so callers (overnight task,
# /collect-training endpoint) can distinguish "no work to do" from "ran but
# every Stage-1 failed". Pre-#615, both produced the same `examples=0` log
# line, masking 11 days of complete pipeline outage during 4/13–4/23.
@dataclass
class CollectionResult:
    count: int = 0                         # successful inserts (incl. contrastive)
    attempted: int = 0                     # made it past Stage 1 → counted toward halt threshold
    rejected: int = 0                      # validator rejected
    stage1_failures: int = 0               # Stage-1 returned None (LLM unavailable, billing, etc.)
    skipped_no_features: int = 0           # no recommendation row + no shadow_trades fallback data
    halted: bool = False                   # batch halted early by ingestion gate
    halt_reason: str | None = None         # top rejection reason at halt time
    rejection_reasons: dict = field(default_factory=dict)

    @property
    def is_silent_failure(self) -> bool:
        """True when work was attempted but produced zero successful inserts.

        Distinguishes 'no eligible work' (count=0, stage1_failures=0) from
        'pipeline failure' (count=0 with stage1_failures or rejected > 0).
        """
        return self.count == 0 and (self.stage1_failures > 0 or self.rejected > 0 or self.attempted > 0)

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


def _classify_outcome(trade: dict) -> str:
    """Classify a closed trade's outcome type for prompt selection."""
    exit_reason = trade.get("exit_reason", "")

    if "timeout" in exit_reason:
        return "TIMEOUT"
    pnl = float(trade.get("pnl_dollars") or 0)
    if pnl > 0:
        return "WIN"
    return "LOSS"


def _get_outcome_prompt(outcome_type: str) -> str:
    """Get the system prompt template for a given outcome type."""
    from src.training.outcome_prompts import (
        WINNER_SYSTEM_PROMPT, LOSER_SYSTEM_PROMPT,
        TIMEOUT_SYSTEM_PROMPT, PASS_SYSTEM_PROMPT,
    )
    return {
        "WIN": WINNER_SYSTEM_PROMPT,
        "LOSS": LOSER_SYSTEM_PROMPT,
        "TIMEOUT": TIMEOUT_SYSTEM_PROMPT,
        "PASS": PASS_SYSTEM_PROMPT,
    }.get(outcome_type, WINNER_SYSTEM_PROMPT)


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


def _build_feature_input_from_trade(trade: dict) -> str | None:
    """Build feature text from shadow_trades columns when the recommendation row is missing.

    Returns None when the trade also lacks usable shadow_trades context — caller
    must skip rather than write a degenerate all-N/A training example. The
    "useful data" gate is setup_type / regime_at_entry / vix_at_entry: at least
    one must be populated. Earlier orphan trades pre-date the regime+vix
    capture and are intentionally excluded from the training corpus.
    """
    setup_type = trade.get("setup_type")
    regime = trade.get("regime_at_entry")
    vix = trade.get("vix_at_entry")
    if setup_type is None and regime is None and vix is None:
        return None

    ticker = trade.get("ticker") or "N/A"
    setup_conf = trade.get("setup_confidence")
    ranking = trade.get("ranking_at_entry")
    sector = trade.get("realized_sector")
    entry = trade.get("actual_entry_price")
    if entry is None:
        entry = trade.get("entry_price")
    stop = trade.get("stop_price")
    target_1 = trade.get("target_1")
    target_2 = trade.get("target_2")

    def _money(v):
        return f"${float(v):.2f}" if v is not None else "n/a"

    def _num(v, fmt=".2f"):
        return format(float(v), fmt) if v is not None else "n/a"

    setup_line = f"Setup: {setup_type or 'n/a'}"
    if setup_conf is not None:
        setup_line += f" (confidence {float(setup_conf):.2f})"

    return (
        f"Ticker: {ticker}\n"
        f"Entry Price: {_money(entry)}\n"
        f"{setup_line}\n"
        f"Market Regime at Entry: {regime or 'n/a'}\n"
        f"VIX at Entry: {_num(vix)}\n"
        f"Ranker Position at Entry: {ranking if ranking is not None else 'n/a'}\n"
        f"Sector: {sector or 'n/a'}\n"
        f"Stop: {_money(stop)} | Target 1: {_money(target_1)} | Target 2: {_money(target_2)}\n"
        f"[Note: rebuilt from shadow_trades fallback — recommendation row missing]"
    )


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
    """Backward-compatible entrypoint that returns the count only.

    Prefer `collect_training_examples_from_closed_trades_detailed` for callers
    that need to distinguish "no work" from "100% failed" (overnight task,
    /collect-training endpoint).
    """
    return collect_training_examples_from_closed_trades_detailed(db_path).count


def _emit_contrastive_example(
    outcome_type: str, trade: dict, feature_input: str,
    link_recommendation_id: str, outcome_text: str, created_at: str,
    db_path: str,
) -> bool:
    """Generate the DPO contrastive sibling for WIN/LOSS trades.

    For DPO training we need (chosen, rejected) pairs. The primary example
    is the "chosen" side; the contrastive argues the opposite stance and
    becomes the "rejected" side:
      WIN  → use PASS_SYSTEM_PROMPT (argue why you'd skip this trade)
      LOSS → use WINNER_SYSTEM_PROMPT (argue why this could be good)
    TIMEOUT trades get no contrastive — signal-decay analysis has no
    natural opposite. Returns True if a row was written, False otherwise.
    """
    if outcome_type not in ("WIN", "LOSS"):
        return False
    from src.training.outcome_prompts import (
        PASS_SYSTEM_PROMPT as _PASS_PROMPT,
        WINNER_SYSTEM_PROMPT as _WIN_PROMPT,
    )
    contrastive_prompt = _PASS_PROMPT if outcome_type == "WIN" else _WIN_PROMPT
    contrastive_source = f"contrastive_{outcome_type.lower()}"
    contrastive_response = generate_training_example(
        contrastive_prompt, feature_input, purpose="backfill_blinded",
    )
    if contrastive_response is None:
        logger.warning(
            "[TRAINING] Contrastive generation failed for %s, skipping",
            trade.get("ticker"),
        )
        return False
    contrastive_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO training_examples
               (example_id, created_at, source, ticker, recommendation_id,
                feature_snapshot, trade_outcome, instruction, input_text, output_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (contrastive_id, created_at, contrastive_source,
             trade.get("ticker"), link_recommendation_id,
             feature_input, outcome_text,
             contrastive_prompt, feature_input, contrastive_response),
        )
        conn.commit()
    logger.info(
        "  [TRAINING] Generated contrastive example for %s (%s)",
        trade.get("ticker"), contrastive_source,
    )
    return True


def collect_training_examples_from_closed_trades_detailed(
    db_path: str = DB_PATH,
) -> CollectionResult:
    """Generate training examples from closed trades using the self-blinding pipeline.

    The self-blinding pipeline ensures NO outcome information leaks into the
    generated commentary. This is architecturally enforced, not instructionally:

    Stage 1 (Blinded): Claude receives ONLY the setup data — zero outcome info.
                       Generates genuine pre-trade analysis with authentic uncertainty.

    Stage 2 (Enhancement): Claude receives ONLY the Stage 1 output plus writing
                          quality instructions. Still no outcome. Improves prose
                          without changing directional stance or conviction.

    Returns a CollectionResult with count + failure-mode breakdown so callers
    can distinguish "nothing to do" from "ran but every LLM call returned None".
    """
    config = load_config()
    training_cfg = config.get("training", {})
    if not training_cfg.get("enabled", False):
        return CollectionResult()

    init_training_tables(db_path)

    # WHY DESC order: process most recent closed trades first so that if the
    # batch halts early (quality gate), we still get the freshest data.
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT st.*, r.*
            FROM shadow_trades st
            LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id
            WHERE st.status = 'closed'
              AND COALESCE(st.quarantined, 0) = 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM training_examples te
                  WHERE te.recommendation_id = COALESCE(
                      st.recommendation_id,
                      'trade:' || st.trade_id
                  )
              )
            ORDER BY st.actual_exit_time DESC
        """).fetchall()

    count = 0
    attempted = 0
    rejected = 0
    stage1_failures = 0
    skipped_no_features = 0
    halted = False
    halt_reason: str | None = None
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
        elif (
            trade.get("price_at_recommendation") is None
            and trade.get("trend_state") is None
            and trade.get("pullback_depth_pct") is None
        ):
            # Recommendation row absent (LEFT JOIN miss). Without this branch
            # _build_feature_input(trade) would emit an all-N/A snapshot that
            # contaminates the training corpus. Fall back to shadow_trades
            # columns; if those are also empty, skip rather than write garbage.
            feature_input = _build_feature_input_from_trade(trade)
            if feature_input is None:
                skipped_no_features += 1
                logger.warning(
                    "[TRAINING] Skipping %s trade_id=%s — no feature data available for training",
                    trade.get("ticker"), trade.get("trade_id"),
                )
                continue
        else:
            feature_input = _build_feature_input(trade)

        # Get the scan/recommendation date for the blinded prompt
        rec_date = (trade.get("created_at") or "")[:10]  # YYYY-MM-DD

        # Some older / reconciled trades can have missing recommendation rows or
        # null recommendation_id. Keep these eligible by assigning a stable
        # synthetic link key so they can still be deduplicated in
        # training_examples.
        link_recommendation_id = trade.get("recommendation_id") or f"trade:{trade.get('trade_id')}"

        # Fix for #277: Sanitize BEFORE LLM generation, not after.
        # The old code called _sanitize_feature_snapshot after the LLM had already
        # seen the unsanitized features. If the enriched_prompt from the
        # recommendation table contained stale outcome fields (pnl_dollars,
        # exit_reason, etc.), the LLM would see them during generation, producing
        # subtly outcome-conditioned output. The stored snapshot looked clean but
        # the commentary was already contaminated.
        feature_input = _sanitize_feature_snapshot(feature_input)

        # ═══ STAGE 1: BLINDED GENERATION (outcome-conditioned) ═══
        # Claude sees ONLY the sanitized setup data — ZERO outcome information.
        # The outcome type selects WHICH analytical lens to apply (thesis
        # validation, risk weighting, signal decay) but the template itself
        # never reveals the outcome. Self-blinding is preserved architecturally.
        outcome_type = _classify_outcome(trade)
        outcome_prompt = _get_outcome_prompt(outcome_type)
        try:
            stage1_response = generate_training_example(outcome_prompt, feature_input, purpose="backfill_blinded")
        except ClaudeAuthError as exc:
            # #612 — Auth/billing failure is unrecoverable. Halt the entire batch
            # immediately so we don't waste cycles retrying every trade.
            stage1_failures += 1
            halted = True
            halt_reason = "claude_auth_error"
            logger.error(
                "[TRAINING] Halting batch — Claude auth/billing error: %s", exc,
            )
            break
        if stage1_response is None:
            stage1_failures += 1
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
                halted = True
                halt_reason = top_reason
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
                 link_recommendation_id, feature_input, outcome_text,
                 outcome_prompt, feature_input, final_output),
            )
            conn.commit()

        logger.info("  [TRAINING] Generated blinded example for %s (%s)", trade.get('ticker'), source)
        count += 1

        # ═══ CONTRASTIVE EXAMPLE (WIN/LOSS only — natural DPO pair) ═══
        if _emit_contrastive_example(
            outcome_type, trade, feature_input, link_recommendation_id,
            outcome_text, created_at, db_path,
        ):
            count += 1

        halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
        if halt:
            halted = True
            halt_reason = top_reason
            alert_training_halt(compliance, rejected, attempted, top_reason)
            logger.error("[TRAINING] Halting collection batch at %.1f%% compliance", compliance)
            break

    return CollectionResult(
        count=count,
        attempted=attempted,
        rejected=rejected,
        stage1_failures=stage1_failures,
        skipped_no_features=skipped_no_features,
        halted=halted,
        halt_reason=halt_reason,
        rejection_reasons=dict(rejection_reasons),
    )

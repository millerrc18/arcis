"""Three-stage curriculum training with difficulty classification and contrastive pairs.

Called by: api.routes.actions, cli.commands, training.trainer
Calls: training.claude_client, training.ingestion_gate, training.versioning
Owns tables: none
Config keys: none
Tests: tests/test_curriculum.py, tests/test_leakage_detector.py
"""

import json
import logging
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from src.training.ingestion_gate import (
    alert_training_halt,
    should_halt_batch,
    validate_training_example,
)
from src.config import DB_PATH
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

CONTRASTIVE_TRAINING_PROMPT = """You are writing TWO trade commentaries for a training dataset. These two trades looked very similar at entry — same sector, similar scores, similar market regime — but had OPPOSITE outcomes.

Your job: Write commentary for BOTH trades that highlights why they looked similar but had different results. The winning trade commentary should be confident. The losing trade commentary should include the subtle risk factor that distinguished it from the winner.

TRADE A (WINNER):
{winner_input}
OUTCOME A: {winner_outcome}

TRADE B (LOSER):
{loser_input}
OUTCOME B: {loser_outcome}

OUTPUT FORMAT:
=== TRADE A COMMENTARY ===
<why_now>
[2-3 sentences]
</why_now>
<analysis>
[4-6 paragraphs]
</analysis>
<metadata>
Conviction: [1-10]
Direction: LONG
Time Horizon: [description]
Key Risk: [one sentence]
</metadata>

=== TRADE B COMMENTARY ===
<why_now>
[2-3 sentences]
</why_now>
<analysis>
[4-6 paragraphs — risk section must address the distinguishing factor]
</analysis>
<metadata>
Conviction: [1-10]
Direction: LONG
Time Horizon: [description]
Key Risk: [one sentence]
</metadata>
"""


def classify_difficulty(example: dict) -> str:
    """Classify a training example's difficulty level.

    Easy: Single clear factor (score >= 90 AND clean_win, OR score <= 50 AND clean_loss)
    Hard: Conflicting signals between data sources
    Medium: Everything else

    Returns: "easy", "medium", or "hard"
    """
    input_text = example.get("input_text", "")
    output_text = example.get("output_text", "")
    feature_snapshot = example.get("feature_snapshot", "")

    # Try to parse feature_snapshot for structured data
    features = {}
    if feature_snapshot:
        try:
            features = json.loads(feature_snapshot)
        except (json.JSONDecodeError, TypeError):
            pass

    # Extract score from input_text
    score = _extract_score(input_text)
    outcome_quality = _extract_outcome_quality(input_text)
    insider_sentiment = _extract_field(input_text, "insider_sentiment", features)
    regime_label = _extract_field(input_text, "regime_label", features)
    news_sentiment = _extract_field(input_text, "news_sentiment", features)

    # Easy: clear single-factor cases
    if score is not None and outcome_quality:
        if score >= 90 and outcome_quality == "clean_win":
            return "easy"
        if score <= 50 and outcome_quality == "clean_loss":
            return "easy"

    # Hard: conflicting signals
    conflicts = 0

    # Technical bullish but insider selling
    if score is not None and score >= 70 and insider_sentiment == "net_selling":
        conflicts += 1

    # High score but bad regime
    if score is not None and score >= 70 and regime_label and any(
        w in regime_label.lower() for w in ("downtrend", "volatile", "correction")
    ):
        conflicts += 1

    # Earnings-adjacent trades
    if "earnings" in input_text.lower() and ("elevated" in input_text.lower() or "imminent" in input_text.lower()):
        conflicts += 1

    # MFE and MAE both significant (choppy)
    mfe = _extract_number(input_text, "MFE:")
    mae = _extract_number(input_text, "MAE:")
    if mfe is not None and mae is not None and mfe > 0 and mae < 0:
        if abs(mfe) > 1 and abs(mae) > 1:
            conflicts += 1

    # Positive score but negative news
    if score is not None and score >= 70 and news_sentiment == "negative":
        conflicts += 1

    if conflicts >= 2:
        return "hard"
    if conflicts == 1:
        return "medium"

    return "medium"


def assign_curriculum_stage(example: dict, difficulty: str) -> str:
    """Assign curriculum stage based on what the example teaches.

    Stage 1 (structure): All easy examples + clean medium examples
    Stage 2 (evidence): Medium and hard examples with multiple data sources available
    Stage 3 (decision): Hard examples with conflicting signals, losing trades with risk flags, contrastive pairs

    Returns: "structure", "evidence", or "decision"
    """
    input_text = example.get("input_text", "")
    source = example.get("source", "")

    # Contrastive pairs always go to stage 3
    if source == "contrastive_pair":
        return "decision"

    if difficulty == "easy":
        return "structure"

    if difficulty == "hard":
        return "decision"

    # Medium difficulty — check for multi-source data
    has_fundamentals = "FUNDAMENTAL SNAPSHOT" in input_text and "Not available" not in input_text
    has_insiders = "INSIDER ACTIVITY" in input_text and "Not available" not in input_text
    has_news = "RECENT NEWS" in input_text and "No recent news" not in input_text
    has_macro = "MACRO CONTEXT" in input_text and "Not available" not in input_text

    source_count = sum([has_fundamentals, has_insiders, has_news, has_macro])

    if source_count >= 2:
        return "evidence"

    return "structure"


def classify_all_examples(db_path: str = DB_PATH) -> dict:
    """Classify all untagged training examples. Returns counts by difficulty and stage."""
    init_training_tables(db_path)

    # Ensure columns exist
    _ensure_curriculum_columns(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT example_id, input_text, output_text, feature_snapshot, source "
            "FROM training_examples WHERE difficulty IS NULL OR curriculum_stage IS NULL"
        ).fetchall()

    if not rows:
        return {"classified": 0, "difficulty": {}, "stage": {}}

    difficulty_counts = {"easy": 0, "medium": 0, "hard": 0}
    stage_counts = {"structure": 0, "evidence": 0, "decision": 0}

    with sqlite3.connect(db_path) as conn:
        for row in rows:
            example = dict(row)
            difficulty = classify_difficulty(example)
            stage = assign_curriculum_stage(example, difficulty)

            conn.execute(
                "UPDATE training_examples SET difficulty = ?, curriculum_stage = ? WHERE example_id = ?",
                (difficulty, stage, example["example_id"]),
            )
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        conn.commit()

    return {
        "classified": len(rows),
        "difficulty": difficulty_counts,
        "stage": stage_counts,
    }


def find_contrastive_pairs(db_path: str = DB_PATH) -> list[tuple[dict, dict]]:
    """Find pairs of training examples with similar inputs but opposite outcomes.

    Matching criteria: same sector, similar score (within 10 points),
    similar regime, one clean_win and one clean_loss.
    """
    init_training_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT example_id, input_text, output_text, ticker, feature_snapshot "
            "FROM training_examples"
        ).fetchall()

    examples = [dict(r) for r in rows]

    # Classify each example
    wins = []
    losses = []
    for ex in examples:
        input_text = ex.get("input_text", "")
        if "clean_win" in input_text or "target_1_hit" in input_text or "target_2_hit" in input_text:
            ex["_score"] = _extract_score(input_text)
            ex["_sector"] = _extract_sector(input_text)
            ex["_regime"] = _extract_regime(input_text)
            wins.append(ex)
        elif "clean_loss" in input_text or "stop_hit" in input_text:
            ex["_score"] = _extract_score(input_text)
            ex["_sector"] = _extract_sector(input_text)
            ex["_regime"] = _extract_regime(input_text)
            losses.append(ex)

    pairs = []
    used_ids = set()

    for win in wins:
        if win["example_id"] in used_ids:
            continue
        for loss in losses:
            if loss["example_id"] in used_ids:
                continue
            # Match criteria
            if win["_sector"] and win["_sector"] == loss["_sector"]:
                if (win["_score"] is not None and loss["_score"] is not None
                        and abs(win["_score"] - loss["_score"]) <= 10):
                    if win["_regime"] and win["_regime"] == loss["_regime"]:
                        pairs.append((win, loss))
                        used_ids.add(win["example_id"])
                        used_ids.add(loss["example_id"])
                        break

    return pairs


def generate_contrastive_training_data(max_pairs: int = 50,
                                       db_path: str = DB_PATH) -> int:
    """Generate contrastive pair training examples via Claude API.
    Returns count of examples created (2 per pair).
    """
    from src.training.claude_client import generate_training_example

    pairs = find_contrastive_pairs(db_path)
    if not pairs:
        logger.info("[CURRICULUM] No contrastive pairs found")
        return 0

    pairs = pairs[:max_pairs]
    created = 0
    attempted = 0
    rejected = 0
    rejection_reasons: Counter[str] = Counter()
    halt_batch = False

    for winner, loser in pairs:
        if halt_batch:
            break

        winner_outcome = _extract_outcome_section(winner["input_text"])
        loser_outcome = _extract_outcome_section(loser["input_text"])

        prompt = CONTRASTIVE_TRAINING_PROMPT.format(
            winner_input=winner["input_text"][:2000],
            winner_outcome=winner_outcome,
            loser_input=loser["input_text"][:2000],
            loser_outcome=loser_outcome,
        )

        response = generate_training_example(
            "You are a senior equity analyst writing contrastive training data.",
            prompt,
            purpose="contrastive",
        )

        if not response:
            continue

        # Parse the two commentaries
        winner_commentary = _extract_commentary(response, "TRADE A")
        loser_commentary = _extract_commentary(response, "TRADE B")

        if not winner_commentary or not loser_commentary:
            continue

        # Store as training examples
        now = datetime.now(ET).isoformat()
        with sqlite3.connect(db_path) as conn:
            for commentary, orig in [(winner_commentary, winner), (loser_commentary, loser)]:
                attempted += 1
                is_valid, rejection_reason = validate_training_example(commentary, db_path)
                if not is_valid:
                    rejected += 1
                    rejection_reasons[rejection_reason] += 1
                    logger.warning(
                        "[CURRICULUM] Rejected contrastive example for %s: %s",
                        orig.get("ticker"),
                        rejection_reason,
                    )
                    halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
                    if halt:
                        alert_training_halt(compliance, rejected, attempted, top_reason)
                        logger.error("[CURRICULUM] Halting contrastive batch at %.1f%% compliance", compliance)
                        halt_batch = True
                        break
                    continue

                example_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO training_examples "
                    "(example_id, created_at, source, ticker, instruction, input_text, output_text, "
                    "difficulty, curriculum_stage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (example_id, now, "contrastive_pair", orig.get("ticker"),
                     "Write trade commentary for this setup.",
                     orig["input_text"], commentary, "hard", "decision"),
                )
                created += 1
            conn.commit()

    logger.info("[CURRICULUM] Generated %d contrastive training examples from %d pairs",
                created, len(pairs))
    return created


def _ensure_curriculum_columns(db_path: str) -> None:
    """Add curriculum columns if they don't exist."""
    with sqlite3.connect(db_path) as conn:
        for col, col_type in [("difficulty", "TEXT"), ("curriculum_stage", "TEXT"),
                               ("quality_score_auto", "REAL")]:
            try:
                conn.execute(f"ALTER TABLE training_examples ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()


def _extract_score(text: str) -> float | None:
    """Extract score from input text."""
    import re
    match = re.search(r'Score:\s*([\d.]+)/100', text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_outcome_quality(text: str) -> str | None:
    """Extract outcome quality from input text."""
    for q in ("clean_win", "clean_loss", "messy", "timeout"):
        if q in text:
            return q
    if "target_1_hit" in text or "target_2_hit" in text:
        return "clean_win"
    if "stop_hit" in text:
        return "clean_loss"
    return None


def _extract_field(text: str, field: str, features: dict) -> str | None:
    """Extract a field value from text or features dict."""
    if field in features:
        return str(features[field])
    import re
    pattern = rf'{field}[:\s]+(\S+)'
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_number(text: str, prefix: str) -> float | None:
    """Extract a number after a prefix."""
    import re
    pattern = rf'{re.escape(prefix)}\s*\$?([-+]?[\d.]+)'
    match = re.search(pattern, text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_sector(text: str) -> str | None:
    """Extract sector from input text."""
    import re
    match = re.search(r'Sector:\s*([^\n|]+)', text)
    if match:
        return match.group(1).strip()
    return None


def _extract_regime(text: str) -> str | None:
    """Extract regime label from input text."""
    import re
    match = re.search(r'Regime:\s*([^\n]+)', text)
    if match:
        return match.group(1).strip()
    return None


def _extract_outcome_section(text: str) -> str:
    """Extract the ACTUAL OUTCOME section from input text."""
    marker = "=== ACTUAL OUTCOME ==="
    idx = text.find(marker)
    if idx == -1:
        return "Outcome not available"
    return text[idx:].strip()


def _extract_commentary(response: str, trade_label: str) -> str | None:
    """Extract commentary for a specific trade from contrastive response."""
    marker = f"=== {trade_label} COMMENTARY ==="
    idx = response.find(marker)
    if idx == -1:
        return None

    start = idx + len(marker)
    # Find end — next === marker or end of text
    next_marker = response.find("===", start + 1)
    if next_marker != -1:
        return response[start:next_marker].strip()
    return response[start:].strip()

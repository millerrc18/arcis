"""Training data ingestion validation — prevents format contamination.

Called by: generator.py, training example creation paths
Calls: sqlite3 (training_examples for duplicate detection)
"""

import logging
import re
import sqlite3
from collections import Counter

logger = logging.getLogger(__name__)

TAG_PATTERN = re.compile(
    r"<why_now>(?P<why_now>.*?)</why_now>.*?"
    r"<analysis>(?P<analysis>.*?)</analysis>.*?"
    r"<metadata>(?P<metadata>.*?)</metadata>",
    re.IGNORECASE | re.DOTALL,
)
CONVICTION_PATTERN = re.compile(r"Conviction:\s*(\d+)", re.IGNORECASE)
DIRECTION_PATTERN = re.compile(r"Direction:\s*(LONG|SHORT|NEUTRAL)", re.IGNORECASE)
MARKDOWN_PATTERNS = [
    (re.compile(r"^\s*```", re.MULTILINE), "code_fence"),
    (re.compile(r"\*\*.+?\*\*"), "markdown_bold"),
    (re.compile(r"^\s*#{1,6}\s", re.MULTILINE), "markdown_heading"),
]


def _extract_sections(text: str) -> tuple[str, str, str] | None:
    """Extract why_now, analysis, and metadata sections in order."""
    match = TAG_PATTERN.search(text)
    if not match:
        return None
    return (
        match.group("why_now").strip(),
        match.group("analysis").strip(),
        match.group("metadata").strip(),
    )


def _detect_duplicate(text: str, db_path: str) -> bool:
    """Reject near-duplicates using TF-IDF cosine similarity."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except Exception as exc:
        logger.warning("[INGESTION] sklearn unavailable; duplicate check skipped: %s", exc)
        return False

    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT output_text FROM training_examples "
                "WHERE output_text IS NOT NULL ORDER BY created_at DESC LIMIT 500"
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("[INGESTION] Duplicate lookup failed: %s", exc)
        return False

    corpus = []
    for row in rows:
        value = None
        if isinstance(row, dict):
            value = row.get("output_text")
        else:
            try:
                value = row["output_text"]
            except (KeyError, TypeError, IndexError):
                try:
                    value = row[0]
                except (TypeError, IndexError, KeyError):
                    value = None
        if value:
            corpus.append(value)
    if not corpus:
        return False

    docs = [text, *corpus]
    try:
        matrix = TfidfVectorizer(stop_words="english").fit_transform(docs)
    except ValueError as exc:
        logger.warning("[INGESTION] Duplicate vectorization skipped: %s", exc)
        return False
    scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    return bool(scores.size and scores.max() > 0.90)


def validate_training_example(text: str, db_path: str) -> tuple[bool, str]:
    """Validate one candidate training example before insert."""
    if not text or not text.strip():
        return False, "empty_output"

    for pattern, reason in MARKDOWN_PATTERNS:
        if pattern.search(text):
            return False, reason

    sections = _extract_sections(text)
    if sections is None:
        return False, "missing_or_out_of_order_xml_tags"

    why_now, analysis, metadata = sections
    if len(why_now) < 50:
        return False, "why_now_too_short"
    if len(analysis) < 100:
        return False, "analysis_too_short"

    conviction_match = CONVICTION_PATTERN.search(metadata)
    if not conviction_match:
        return False, "missing_conviction"
    conviction = int(conviction_match.group(1))
    if conviction < 1 or conviction > 10:
        return False, "invalid_conviction"

    if not DIRECTION_PATTERN.search(metadata):
        return False, "invalid_direction"

    if _detect_duplicate(text, db_path):
        return False, "duplicate_similarity"

    return True, ""


def should_halt_batch(
    attempted: int,
    rejected: int,
    rejection_reasons: Counter[str],
) -> tuple[bool, float, str]:
    """Return whether a batch should halt for low format compliance."""
    if attempted < 10:
        return False, 100.0, ""

    compliance = ((attempted - rejected) / attempted) * 100 if attempted else 100.0
    top_reason = rejection_reasons.most_common(1)[0][0] if rejection_reasons else ""
    return compliance < 90.0, round(compliance, 1), top_reason


def alert_training_halt(compliance: float, rejected: int, total: int, top_reason: str) -> None:
    """Send the required Telegram alert when a batch falls below compliance threshold."""
    try:
        from src.notifications.telegram import send_telegram

        send_telegram(
            "🛑 TRAINING HALT: "
            f"{compliance:.1f}% format compliance ({rejected}/{total} rejected). "
            f"Top reason: {top_reason}"
        )
    except Exception as exc:
        logger.warning("[INGESTION] Training halt alert failed: %s", exc)

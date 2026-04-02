"""Quality drift metrics for monitoring model output degradation.

Called by: training.canary
Calls: none
Owns tables: quality_drift_metrics
Config keys: none
Tests: tests/test_leakage_detector.py, tests/test_quality_drift.py

Computes diversity and quality metrics across model outputs to detect
training-induced drift (mode collapse, vocabulary shrinkage, repetition).

All metrics are stdlib-only — no nltk or external NLP dependencies.
"""

import json
import logging
import math
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

QUALITY_DRIFT_SCHEMA = """
CREATE TABLE IF NOT EXISTS quality_drift_metrics (
    metric_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    cycle_number INTEGER,
    model_version TEXT,
    distinct_1 REAL,
    distinct_2 REAL,
    self_bleu REAL,
    vocab_size INTEGER,
    avg_length REAL,
    degradation_flag INTEGER DEFAULT 0,
    details TEXT
);
"""

# Thresholds: distinct_2 drop >10% OR self_BLEU rise >15% = investigate
DISTINCT_2_DROP_THRESHOLD = 0.10
SELF_BLEU_RISE_THRESHOLD = 0.15


def init_quality_drift_tables(db_path: str = DB_PATH) -> None:
    """Create quality_drift_metrics table if it doesn't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(QUALITY_DRIFT_SCHEMA)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    # Lowercase and split on whitespace; strip common punctuation from edges
    tokens = []
    for word in text.lower().split():
        cleaned = word.strip(".,;:!?\"'()[]{}—–-")
        if cleaned:
            tokens.append(cleaned)
    return tokens


def distinct_1(texts: list[str]) -> float:
    """Ratio of unique unigrams to total unigrams across all texts.

    Higher = more diverse output. Returns 0.0 for empty input.
    """
    all_tokens = []
    for text in texts:
        all_tokens.extend(_tokenize(text))
    if not all_tokens:
        return 0.0
    return len(set(all_tokens)) / len(all_tokens)


def distinct_2(texts: list[str]) -> float:
    """Ratio of unique bigrams to total bigrams across all texts.

    Higher = more diverse output. Returns 0.0 for empty input.
    """
    all_bigrams = []
    for text in texts:
        tokens = _tokenize(text)
        for i in range(len(tokens) - 1):
            all_bigrams.append((tokens[i], tokens[i + 1]))
    if not all_bigrams:
        return 0.0
    return len(set(all_bigrams)) / len(all_bigrams)


def vocab_size(texts: list[str]) -> int:
    """Number of unique tokens across all texts."""
    all_tokens = set()
    for text in texts:
        all_tokens.update(_tokenize(text))
    return len(all_tokens)


def avg_length(texts: list[str]) -> float:
    """Average output length in tokens."""
    if not texts:
        return 0.0
    lengths = [len(_tokenize(text)) for text in texts]
    return sum(lengths) / len(lengths)


# ---------------------------------------------------------------------------
# Simple BLEU-4 implementation (no external deps)
# ---------------------------------------------------------------------------

def _count_ngrams(tokens: list[str], n: int) -> Counter:
    """Count n-grams in a token list."""
    return Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def _bleu_4_sentence(hypothesis_tokens: list[str], reference_tokens: list[str]) -> float:
    """Compute BLEU-4 score between a hypothesis and a single reference.

    Uses clipped n-gram precision for n=1..4 with brevity penalty.
    Returns 0.0 if either sequence has fewer than 4 tokens.
    """
    if len(hypothesis_tokens) < 4 or len(reference_tokens) < 4:
        return 0.0

    precisions = []
    for n in range(1, 5):
        hyp_ngrams = _count_ngrams(hypothesis_tokens, n)
        ref_ngrams = _count_ngrams(reference_tokens, n)

        # Clipped counts
        clipped = 0
        total = 0
        for ngram, count in hyp_ngrams.items():
            clipped += min(count, ref_ngrams.get(ngram, 0))
            total += count

        if total == 0:
            return 0.0
        precisions.append(clipped / total)

    # Any zero precision -> BLEU is 0
    if any(p == 0 for p in precisions):
        return 0.0

    # Geometric mean of precisions
    log_avg = sum(math.log(p) for p in precisions) / 4

    # Brevity penalty
    bp = 1.0
    if len(hypothesis_tokens) < len(reference_tokens):
        bp = math.exp(1 - len(reference_tokens) / len(hypothesis_tokens))

    return bp * math.exp(log_avg)


def self_bleu(texts: list[str], max_pairs: int = 500) -> float:
    """Average BLEU-4 between pairs of outputs (lower = more diverse).

    For efficiency, samples up to max_pairs random pairs when the
    corpus is large. Returns 0.0 for fewer than 2 texts.
    """
    if len(texts) < 2:
        return 0.0

    tokenized = [_tokenize(t) for t in texts]

    # Filter out very short texts
    tokenized = [t for t in tokenized if len(t) >= 4]
    if len(tokenized) < 2:
        return 0.0

    import random

    # Build all pairs or sample
    n = len(tokenized)
    total_pairs = n * (n - 1) // 2
    if total_pairs <= max_pairs:
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    else:
        pairs = set()
        while len(pairs) < max_pairs:
            i = random.randint(0, n - 1)
            j = random.randint(0, n - 1)
            if i != j:
                pairs.add((min(i, j), max(i, j)))
        pairs = list(pairs)

    scores = []
    for i, j in pairs:
        score = _bleu_4_sentence(tokenized[i], tokenized[j])
        scores.append(score)

    return sum(scores) / len(scores) if scores else 0.0


def compute_all_metrics(texts: list[str]) -> dict:
    """Compute all quality drift metrics for a list of output texts.

    Returns dict with distinct_1, distinct_2, self_bleu, vocab_size, avg_length.
    """
    return {
        "distinct_1": distinct_1(texts),
        "distinct_2": distinct_2(texts),
        "self_bleu": self_bleu(texts),
        "vocab_size": vocab_size(texts),
        "avg_length": avg_length(texts),
    }


def check_degradation(
    current: dict,
    previous: dict | None = None,
) -> dict:
    """Check whether current metrics indicate quality degradation.

    Compares current metrics to previous cycle. If no previous data,
    only flags extreme values.

    Returns dict with degradation_flag (0 or 1) and details string.
    """
    issues = []

    if previous:
        # Distinct-2 drop
        if previous.get("distinct_2", 0) > 0:
            d2_delta = (current["distinct_2"] - previous["distinct_2"]) / previous["distinct_2"]
            if d2_delta < -DISTINCT_2_DROP_THRESHOLD:
                issues.append(
                    f"distinct_2 dropped {abs(d2_delta) * 100:.1f}% "
                    f"(from {previous['distinct_2']:.4f} to {current['distinct_2']:.4f})"
                )

        # Self-BLEU rise
        if previous.get("self_bleu", 0) > 0:
            sb_delta = (current["self_bleu"] - previous["self_bleu"]) / previous["self_bleu"]
            if sb_delta > SELF_BLEU_RISE_THRESHOLD:
                issues.append(
                    f"self_bleu rose {sb_delta * 100:.1f}% "
                    f"(from {previous['self_bleu']:.4f} to {current['self_bleu']:.4f})"
                )
        elif current["self_bleu"] > 0 and previous.get("self_bleu", 0) == 0:
            # Previous was 0, now it's non-zero — check absolute
            if current["self_bleu"] > 0.5:
                issues.append(f"self_bleu jumped to {current['self_bleu']:.4f} from 0")

        # Vocab shrinkage
        if previous.get("vocab_size", 0) > 0:
            vs_delta = (current["vocab_size"] - previous["vocab_size"]) / previous["vocab_size"]
            if vs_delta < -0.15:
                issues.append(
                    f"vocab_size shrank {abs(vs_delta) * 100:.1f}% "
                    f"(from {previous['vocab_size']} to {current['vocab_size']})"
                )

    # Absolute floor checks
    if current["distinct_1"] < 0.1:
        issues.append(f"distinct_1 critically low: {current['distinct_1']:.4f}")
    if current["distinct_2"] < 0.2:
        issues.append(f"distinct_2 critically low: {current['distinct_2']:.4f}")
    if current["self_bleu"] > 0.7:
        issues.append(f"self_bleu critically high: {current['self_bleu']:.4f}")

    degradation_flag = 1 if issues else 0
    details = "; ".join(issues) if issues else "all metrics within acceptable range"

    return {
        "degradation_flag": degradation_flag,
        "details": details,
    }


def store_metrics(
    metrics: dict,
    cycle_number: int | None = None,
    model_version: str | None = None,
    degradation_flag: int = 0,
    details: str = "",
    db_path: str = DB_PATH,
) -> str:
    """Store quality drift metrics to the database.

    Returns the metric_id.
    """
    init_quality_drift_tables(db_path)
    metric_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO quality_drift_metrics
               (metric_id, created_at, cycle_number, model_version,
                distinct_1, distinct_2, self_bleu, vocab_size, avg_length,
                degradation_flag, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metric_id,
                now,
                cycle_number,
                model_version,
                metrics.get("distinct_1"),
                metrics.get("distinct_2"),
                metrics.get("self_bleu"),
                metrics.get("vocab_size"),
                metrics.get("avg_length"),
                degradation_flag,
                details,
            ),
        )

    return metric_id


def get_previous_metrics(
    db_path: str = DB_PATH,
) -> dict | None:
    """Retrieve the most recent quality drift metrics from the database."""
    init_quality_drift_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM quality_drift_metrics
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()

    if not row:
        return None
    return dict(row)

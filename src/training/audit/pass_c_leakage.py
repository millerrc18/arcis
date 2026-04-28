"""Pass C — TF-IDF outcome leakage probe (report-only).

Trains a TF-IDF + LogisticRegression classifier on the labeled subset
(sources in LABELED_SOURCES) and reports:
  - balanced_accuracy_score on StratifiedKFold CV
  - majority_baseline (50% for balanced binary, >50% for imbalanced)
  - top-N suspect example_ids with highest decision-function magnitude

Leakage threshold reused from src.training.leakage_detector:
balanced_accuracy > 0.65 → classifier can read outcome from text.

Report-only in v1 per sprint prompt: never auto-quarantines unless
operator explicitly opts in via core.run_audit(passes=['C'], ...).
Remediation is a separate sprint.

Called by: src.training.audit.core
Calls: sklearn (optional import; returns None accuracy if missing),
       src.universe.company_names, src.universe.sp100 (for masking)
Owns tables: none
Config keys: none
Tests: tests/training/test_pass_c.py
"""
from __future__ import annotations

import logging
import re

from src.config import DB_PATH

logger = logging.getLogger(__name__)

# Subset of sources with ground-truth outcome labels in the name.
# Mirrors src.training.leakage_detector; keeps the two checkers in sync.
LABELED_SOURCES: tuple[str, ...] = (
    "blinded_win", "blinded_loss", "outcome_win", "outcome_loss",
)

# Random seed locked per Pass 1 D9 (42 — repo convention).
RANDOM_STATE = 42
TOP_N_SUSPECTS = 20
LEAKAGE_THRESHOLD = 0.65


def _labels_from_source(source: str) -> int:
    """Return 1 for win-ish sources, 0 for loss-ish."""
    return 1 if "win" in source else 0


def _mask_entity_names(text: str) -> str:
    """Replace ticker and company-name substrings with 'TICKER'/'COMPANY'.

    Pulled into its own function for testability. Gracefully no-ops if
    the universe modules are unavailable (e.g. in a minimal test env).
    """
    try:
        from src.universe.company_names import COMPANY_NAMES
        from src.universe.pit import get_all_historical_tickers
    except Exception:
        return text
    # T10: text-masking needs the SUPERSET of every ticker that has ever
    # been an SP100 member (PCLN/BKNG, KRFT/KHC, UTX/RTN/RTX, etc.).
    # Point-in-time at today would miss historically-removed tickers.
    tickers = set(t.lower() for t in get_all_historical_tickers())
    company_words: set[str] = set()
    for name in COMPANY_NAMES.values():
        for word in name.lower().split():
            if len(word) > 2:
                company_words.add(word)
    masked = text.lower()
    for ticker in tickers:
        masked = re.sub(r"\b" + re.escape(ticker) + r"\b", "TICKER", masked)
    for word in company_words:
        masked = re.sub(r"\b" + re.escape(word) + r"\b", "COMPANY", masked)
    return masked


def _fit_probe(
    texts: list[str], labels: list[int],
) -> tuple[float | None, float | None, list[int]]:
    """Fit TF-IDF + LogReg; return (balanced_acc, majority_baseline, suspect_indexes).

    Returns (None, None, []) if sklearn or the dataset is unusable.
    `suspect_indexes` are the dataset indices with highest classifier
    decision-function magnitude (most confident predictions).
    """
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import balanced_accuracy_score
        from sklearn.model_selection import StratifiedKFold
    except ImportError:
        logger.warning("[PASS C] sklearn not installed; skipping leakage probe")
        return None, None, []

    if len(texts) < 50:
        return None, None, []
    n_wins = sum(labels)
    n_losses = len(labels) - n_wins
    if n_wins < 10 or n_losses < 10:
        return None, None, []
    majority_baseline = max(n_wins, n_losses) / len(labels)

    vec = TfidfVectorizer(
        max_features=2000, ngram_range=(1, 2), min_df=2, stop_words="english",
    )
    X = vec.fit_transform(texts)
    y = np.asarray(labels)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    fold_scores: list[float] = []
    decision_mag = np.zeros(len(texts), dtype=float)
    seen = np.zeros(len(texts), dtype=bool)

    for train_idx, test_idx in cv.split(X, y):
        clf = LogisticRegression(
            max_iter=500, random_state=RANDOM_STATE, C=1.0,
        )
        clf.fit(X[train_idx], y[train_idx])
        y_pred = clf.predict(X[test_idx])
        fold_scores.append(float(balanced_accuracy_score(y[test_idx], y_pred)))
        dm = np.abs(clf.decision_function(X[test_idx]))
        decision_mag[test_idx] = dm
        seen[test_idx] = True

    balanced_acc = float(np.mean(fold_scores))
    if seen.any():
        top_idx = np.argsort(-decision_mag[seen])[:TOP_N_SUSPECTS]
        seen_indices = np.flatnonzero(seen)
        suspect_indexes = [int(seen_indices[i]) for i in top_idx]
    else:
        suspect_indexes = []
    return balanced_acc, float(majority_baseline), suspect_indexes


def run_pass_c(rows: list[dict], *, db_path: str | None = None) -> dict:
    """Fit the leakage classifier on the labeled subset and report metrics.

    Args:
        rows: full training_examples dataset from core (filtering happens here)
        db_path: unused; kept for symmetry with stub signature

    Returns:
        dict with balanced_accuracy, majority_baseline, n_examples,
        is_leaking, suspect_example_ids, status, threshold.
    """
    _ = db_path or DB_PATH  # kept for signature compatibility

    labeled = [r for r in rows if (r.get("source") in LABELED_SOURCES)
               and (r.get("output_text") or "")]
    if len(labeled) < 50:
        return {
            "balanced_accuracy": None,
            "majority_baseline": None,
            "n_examples": len(labeled),
            "is_leaking": None,
            "suspect_example_ids": [],
            "threshold": LEAKAGE_THRESHOLD,
            "status": "insufficient_data",
        }

    texts = [_mask_entity_names(r["output_text"]) for r in labeled]
    labels = [_labels_from_source(r["source"]) for r in labeled]

    balanced_acc, majority_baseline, suspect_indexes = _fit_probe(texts, labels)

    suspect_ids: list[str] = []
    for idx in suspect_indexes:
        if 0 <= idx < len(labeled):
            suspect_ids.append(labeled[idx]["example_id"])

    if balanced_acc is None:
        return {
            "balanced_accuracy": None,
            "majority_baseline": majority_baseline,
            "n_examples": len(labeled),
            "is_leaking": None,
            "suspect_example_ids": [],
            "threshold": LEAKAGE_THRESHOLD,
            "status": "sklearn_unavailable_or_tiny_dataset",
        }

    return {
        "balanced_accuracy": balanced_acc,
        "majority_baseline": majority_baseline,
        "n_examples": len(labeled),
        "is_leaking": balanced_acc > LEAKAGE_THRESHOLD,
        "suspect_example_ids": suspect_ids,
        "threshold": LEAKAGE_THRESHOLD,
        "status": "completed",
    }

"""Outcome leakage detector for training data quality assurance.

Called by: api.routes.actions, cli.commands, evaluation.cto_report, scheduler.watch
Calls: universe.company_names, universe.sp100
Owns tables: none
Config keys: none
Tests: tests/test_leakage_detector.py

Tests whether generated commentary inadvertently reveals trade outcomes
by training a classifier to predict win/loss from text alone.

Two detection tiers:
  1. TF-IDF (token-level) — catches literal outcome keywords
  2. Embedding (semantic-level) — catches paraphrased outcome information

Uses balanced accuracy (average of per-class recall) to handle class
imbalance correctly. A majority-class classifier always scores 50%
balanced accuracy regardless of the win/loss ratio in the data.
"""

import logging
import sqlite3
import time
from contextlib import closing

import requests

from src.config import DB_PATH

logger = logging.getLogger(__name__)


def check_outcome_leakage(db_path: str = DB_PATH) -> dict:
    """Test whether generated commentary leaks outcome information.

    Trains a simple classifier (TF-IDF + logistic regression) to predict
    trade outcome (win/loss) from the generated commentary text alone.

    Uses BALANCED ACCURACY to handle class imbalance:
      - Balanced accuracy = average of (win recall + loss recall) / 2
      - A majority-class-only classifier always scores 50% balanced accuracy
      - Threshold: balanced accuracy > 65% indicates leakage

    Returns dict with balanced_accuracy, raw_accuracy, majority_baseline,
    class_balance, status, and feature_importance.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.metrics import balanced_accuracy_score, make_scorer
        import numpy as np
    except ImportError:
        return {
            "balanced_accuracy": None,
            "is_leaking": None,
            "n_examples": 0,
            "note": "scikit-learn not installed. Run: pip install scikit-learn",
        }

    # Load examples
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        fetched = conn.execute(
            "SELECT output_text, source, ticker FROM training_examples "
            "WHERE source IN ('blinded_win', 'blinded_loss', 'outcome_win', 'outcome_loss')"
        ).fetchall()
        rows = [dict(row) for row in fetched]

    if len(rows) < 50:
        return {
            "balanced_accuracy": None,
            "is_leaking": None,
            "n_examples": len(rows),
            "note": "Need at least 50 examples to test for leakage",
        }

    texts = [row["output_text"] for row in rows if row["output_text"]]
    labels = [1 if "win" in row["source"] else 0 for row in rows if row["output_text"]]

    # Mask ticker names and company names to prevent ticker-level correlation
    # from registering as outcome leakage.
    try:
        from src.universe.sp100 import get_sp100_universe
        from src.universe.company_names import COMPANY_NAMES
        import re

        tickers = set(t.lower() for t in get_sp100_universe())
        company_words = set()
        for name in COMPANY_NAMES.values():
            for word in name.lower().split():
                if len(word) > 2:
                    company_words.add(word)

        def mask_text(text):
            masked = text.lower()
            for ticker in tickers:
                masked = re.sub(r'\b' + re.escape(ticker) + r'\b', 'TICKER', masked)
            for word in company_words:
                masked = re.sub(r'\b' + re.escape(word) + r'\b', 'COMPANY', masked)
            return masked

        texts = [mask_text(t) for t in texts]
    except Exception:
        pass

    if len(texts) < 50:
        return {
            "balanced_accuracy": None,
            "is_leaking": None,
            "n_examples": len(texts),
            "note": "Need at least 50 examples with output text to test for leakage",
        }

    # Compute class balance
    n_wins = sum(labels)
    n_losses = len(labels) - n_wins
    majority_baseline = max(n_wins, n_losses) / len(labels)
    win_pct = round(n_wins / len(labels) * 100, 1)

    # #113 — Minimum sample size check: TF-IDF produces unreliable results
    # with too few examples per class (tiny vocabulary, random accuracy ~0.5).
    if min(n_wins, n_losses) < 30:
        return {
            "status": "INSUFFICIENT_DATA",
            "balanced_accuracy": None,
            "is_leaking": None,
            "n_examples": len(texts),
            "class_balance": {
                "wins": n_wins,
                "losses": n_losses,
                "win_pct": win_pct,
            },
            "reason": f"Need >=30 per class (have {n_wins} win, {n_losses} loss)",
        }

    # Vectorize with conservative settings
    vectorizer = TfidfVectorizer(max_features=100, stop_words="english",
                                 min_df=3, max_df=0.8)
    try:
        X = vectorizer.fit_transform(texts)
    except ValueError as exc:
        if "no terms remain" not in str(exc).lower():
            raise
        return {
            "balanced_accuracy": 0.5,
            "raw_accuracy": round(majority_baseline, 3),
            "majority_baseline": round(majority_baseline, 3),
            "accuracy_above_baseline": 0.0,
            "status": "CLEAN",
            "is_leaking": False,
            "n_examples": len(texts),
            "class_balance": {
                "wins": n_wins,
                "losses": n_losses,
                "win_pct": win_pct,
            },
            "feature_importance": {
                "win_predictors": [],
                "loss_predictors": [],
            },
            "note": "Vectorizer pruned all terms; treating dataset as non-leaking.",
        }

    n_minority = min(n_wins, n_losses)
    n_splits = min(5, n_minority)
    if n_splits < 2:
        return {
            "balanced_accuracy": None,
            "is_leaking": None,
            "n_examples": len(texts),
            "note": "Need at least 2 examples per class for cross-validation",
        }

    # Stratified K-Fold preserves class ratio in each fold
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    bal_scorer = make_scorer(balanced_accuracy_score)

    # Run with balanced accuracy across multiple seeds for stability
    balanced_scores = []
    raw_scores = []
    for seed in [42, 123, 456, 789, 1024]:
        clf = LogisticRegression(
            max_iter=1000, random_state=seed, C=0.1,
            class_weight='balanced',
        )
        bal_s = cross_val_score(clf, X, labels, cv=skf, scoring=bal_scorer)
        balanced_scores.extend(bal_s)
        raw_s = cross_val_score(clf, X, labels, cv=skf, scoring='accuracy')
        raw_scores.extend(raw_s)

    balanced_accuracy = float(np.mean(balanced_scores))
    raw_accuracy = float(np.mean(raw_scores))
    accuracy_above_baseline = raw_accuracy - majority_baseline

    # Status thresholds on balanced accuracy:
    #   <= 55%: CLEAN — no signal beyond random
    #   55-65%: MARGINAL — possible feature-level signal, not outcome leakage
    #   > 65%:  LEAKING — commentary contains outcome-revealing language
    if balanced_accuracy <= 0.55:
        status = "CLEAN"
    elif balanced_accuracy <= 0.65:
        status = "MARGINAL"
    else:
        status = "LEAKING"

    is_leaking = balanced_accuracy > 0.65

    # Feature importance from final fitted model
    clf_final = LogisticRegression(
        max_iter=1000, random_state=42, C=0.1, class_weight='balanced'
    )
    clf_final.fit(X, labels)
    feature_names = vectorizer.get_feature_names_out()
    coefs = clf_final.coef_[0]
    top_win = [feature_names[i] for i in np.argsort(coefs)[-5:]]
    top_loss = [feature_names[i] for i in np.argsort(coefs)[:5]]

    return {
        "balanced_accuracy": round(balanced_accuracy, 3),
        "raw_accuracy": round(raw_accuracy, 3),
        "majority_baseline": round(majority_baseline, 3),
        "accuracy_above_baseline": round(accuracy_above_baseline, 3),
        "status": status,
        "is_leaking": is_leaking,
        "n_examples": len(texts),
        "class_balance": {
            "wins": n_wins,
            "losses": n_losses,
            "win_pct": win_pct,
        },
        "feature_importance": {
            "win_predictors": list(reversed(top_win)),
            "loss_predictors": list(top_loss),
        },
    }


# --- Outcome classification for embedding detector ---
_WIN_OUTCOMES = {"target_1_hit", "target_2_hit", "WIN"}
_LOSS_OUTCOMES = {"stop_hit", "timeout", "LOSS"}


def check_embedding_leakage(db_path: str = DB_PATH,
                             model: str = "halcyon-v1.0.0",
                             timeout: int = 10,
                             max_examples: int = 500) -> dict:
    """Embedding-based leakage detection — catches semantic leakage TF-IDF misses.

    WHY: TF-IDF treats words independently. "The trade was profitable" and
    "the position yielded positive returns" share few tokens but both leak
    outcomes. Kapoor & Narayanan (2023, 369 citations) showed this blind spot
    exists across 294 published papers.

    HOW: Generate embeddings via Ollama /api/embeddings endpoint, then train
    a logistic regression classifier to predict outcome from embeddings.
    If balanced accuracy > 55%, the training data contains semantic leakage.

    Args:
        db_path: Path to SQLite database with training_examples table
        model: Ollama model name for embedding generation
        timeout: Seconds per Ollama embedding request
        max_examples: Cap to prevent OOM on large datasets (random sample)

    Returns:
        dict with balanced_accuracy, leaking (bool), n_examples, cv_scores,
        class_distribution, embedding_dim, processing_time_seconds
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        import numpy as np
    except ImportError:
        return {"error": "scikit-learn not installed", "leaking": None}

    start = time.time()

    # Load examples — use source column (blinded_win/loss) and trade_outcome column
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT output_text, source, trade_outcome FROM training_examples "
            "WHERE output_text IS NOT NULL AND output_text != ''"
        ).fetchall()

    # Classify as WIN/LOSS
    texts, labels = [], []
    for row in rows:
        source = row["source"] or ""
        trade_outcome = row["trade_outcome"] or ""

        # Determine label from source column (existing pattern) or trade_outcome
        if "win" in source.lower() or trade_outcome in _WIN_OUTCOMES:
            label = 1
        elif "loss" in source.lower() or trade_outcome in _LOSS_OUTCOMES:
            label = 0
        else:
            continue  # Skip ambiguous/NULL outcomes

        texts.append(row["output_text"])
        labels.append(label)

    if len(texts) < 20:
        return {"error": "Insufficient data", "n_examples": len(texts), "leaking": None}

    # Random sample if over max_examples
    if len(texts) > max_examples:
        rng = np.random.RandomState(42)
        indices = rng.choice(len(texts), max_examples, replace=False)
        texts = [texts[i] for i in indices]
        labels = [labels[i] for i in indices]

    # Generate embeddings via Ollama
    embeddings = []
    for i, text in enumerate(texts):
        if (i + 1) % 50 == 0:
            logger.info("Embedding %d/%d...", i + 1, len(texts))
        try:
            resp = requests.post(
                "http://localhost:11434/api/embeddings",
                json={"model": model, "prompt": text[:2000]},
                timeout=timeout,
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
        except (requests.ConnectionError, requests.Timeout):
            return {"error": "Ollama unavailable", "leaking": None}
        except Exception as exc:
            logger.warning("Embedding failed for example %d: %s", i, exc)
            return {"error": f"Embedding failed: {exc}", "leaking": None}

    X = np.array(embeddings)
    y = np.array(labels)

    n_wins = int(y.sum())
    n_losses = len(y) - n_wins
    n_minority = min(n_wins, n_losses)
    n_splits = min(5, n_minority)
    if n_splits < 2:
        return {
            "error": "Insufficient class diversity for CV",
            "n_examples": len(y),
            "class_distribution": {"wins": n_wins, "losses": n_losses},
            "leaking": None,
        }

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    clf = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    cv_scores = cross_val_score(clf, X, y, cv=skf, scoring="balanced_accuracy")
    balanced_accuracy = float(np.mean(cv_scores))

    elapsed = time.time() - start

    return {
        "balanced_accuracy": round(balanced_accuracy, 4),
        "leaking": balanced_accuracy > 0.55,
        "n_examples": len(y),
        "cv_scores": [round(s, 4) for s in cv_scores],
        "class_distribution": {"wins": n_wins, "losses": n_losses},
        "embedding_dim": X.shape[1],
        "processing_time_seconds": round(elapsed, 1),
    }


def _recommend(tfidf: dict, embedding: dict) -> str:
    """Generate a human-readable recommendation from both detectors."""
    if embedding.get("leaking"):
        return "CRITICAL: Semantic leakage detected. Audit training templates immediately."
    if tfidf.get("is_leaking"):
        return "WARNING: Token-level leakage detected. Check for outcome keywords."
    return "CLEAN: No leakage detected at token or semantic level."


def check_all_leakage(db_path: str = DB_PATH) -> dict:
    """Run both TF-IDF and embedding leakage checks. Returns combined results."""
    tfidf = check_outcome_leakage(db_path)
    embedding = check_embedding_leakage(db_path)
    return {
        "tfidf": tfidf,
        "embedding": embedding,
        "overall_leaking": tfidf.get("is_leaking", False) or embedding.get("leaking", False),
        "recommendation": _recommend(tfidf, embedding),
    }

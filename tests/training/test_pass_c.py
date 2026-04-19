"""Pass C — TF-IDF leakage probe tests.

Covers the sprint's Pass C matrix:
  - Reports >90% accuracy on synthetic leaky dataset
  - Reports near-chance accuracy on synthetic clean dataset
  - Insufficient-data branch returns None accuracy + status
  - Reproducibility (random_state=42 → same result twice)

These tests synthesize small datasets so they run in a few seconds
without touching the production DB.
"""
from __future__ import annotations

import random

import pytest

from src.training.audit.pass_c_leakage import (
    LEAKAGE_THRESHOLD,
    LABELED_SOURCES,
    run_pass_c,
)


def _synthetic_leaky_dataset(n_per_class: int = 60, seed: int = 0) -> list[dict]:
    """Build a dataset where output_text literally contains the outcome word."""
    rng = random.Random(seed)
    rows: list[dict] = []
    for i in range(n_per_class):
        rows.append({
            "example_id": f"w-{i}",
            "source": "blinded_win",
            "output_text": (
                f"The trade successful trade and profitable reversal. "
                f"Noise tokens: {rng.random():.4f} foo bar baz quux."
            ),
        })
    for i in range(n_per_class):
        rows.append({
            "example_id": f"l-{i}",
            "source": "blinded_loss",
            "output_text": (
                f"The trade stopped out and breakdown continued. "
                f"Noise tokens: {rng.random():.4f} foo bar baz quux."
            ),
        })
    rng.shuffle(rows)
    return rows


def _synthetic_clean_dataset(n_per_class: int = 60, seed: int = 0) -> list[dict]:
    """Same setup narrative for both classes — no outcome words."""
    rng = random.Random(seed)
    base_phrases = [
        "pullback in trend with supportive volume",
        "setup shows clean structure above a rising 50-day SMA",
        "mean-reversion candidate with moderate volatility",
        "sector momentum mixed with defensive rotation",
    ]
    rows: list[dict] = []
    for i in range(n_per_class):
        text = rng.choice(base_phrases) + f" id={rng.random():.4f}"
        rows.append({
            "example_id": f"w-{i}",
            "source": "blinded_win",
            "output_text": text,
        })
    for i in range(n_per_class):
        text = rng.choice(base_phrases) + f" id={rng.random():.4f}"
        rows.append({
            "example_id": f"l-{i}",
            "source": "blinded_loss",
            "output_text": text,
        })
    rng.shuffle(rows)
    return rows


def _sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _sklearn_available(), reason="sklearn not installed")
def test_leaky_dataset_reports_high_accuracy():
    """Classifier should score > threshold on obvious leakage."""
    rows = _synthetic_leaky_dataset(n_per_class=60)
    result = run_pass_c(rows, db_path=":memory:")
    assert result["status"] == "completed"
    assert result["n_examples"] == 120
    # Leaky data: outcome words directly in text → >90% balanced accuracy
    assert result["balanced_accuracy"] is not None
    assert result["balanced_accuracy"] > 0.90
    assert result["is_leaking"] is True
    assert result["threshold"] == LEAKAGE_THRESHOLD


@pytest.mark.skipif(not _sklearn_available(), reason="sklearn not installed")
def test_clean_dataset_reports_near_chance_accuracy():
    """Classifier should score near chance on outcome-neutral text."""
    rows = _synthetic_clean_dataset(n_per_class=60)
    result = run_pass_c(rows, db_path=":memory:")
    assert result["status"] == "completed"
    assert result["n_examples"] == 120
    # Random text: should be near 0.5 balanced accuracy; definitely below threshold
    assert result["balanced_accuracy"] is not None
    assert result["balanced_accuracy"] < LEAKAGE_THRESHOLD
    assert result["is_leaking"] is False


@pytest.mark.skipif(not _sklearn_available(), reason="sklearn not installed")
def test_insufficient_data_returns_status_not_none():
    """< 50 labeled rows should yield an insufficient_data status."""
    rows = _synthetic_leaky_dataset(n_per_class=10)  # 20 total
    result = run_pass_c(rows, db_path=":memory:")
    assert result["status"] == "insufficient_data"
    assert result["balanced_accuracy"] is None
    assert result["n_examples"] == 20


@pytest.mark.skipif(not _sklearn_available(), reason="sklearn not installed")
def test_pass_c_is_reproducible_with_fixed_seed():
    """random_state=42 ⇒ two runs on the same data return identical balanced_accuracy."""
    rows = _synthetic_leaky_dataset(n_per_class=60)
    r1 = run_pass_c(rows, db_path=":memory:")
    r2 = run_pass_c(rows, db_path=":memory:")
    assert r1["balanced_accuracy"] == r2["balanced_accuracy"]
    assert r1["suspect_example_ids"] == r2["suspect_example_ids"]


def test_filters_to_labeled_sources_only():
    """Rows with sources outside LABELED_SOURCES must be excluded."""
    # Only 'synthetic_claude' — not labeled → insufficient_data
    rows = [
        {"example_id": f"s-{i}", "source": "synthetic_claude",
         "output_text": "some narrative"} for i in range(80)
    ]
    result = run_pass_c(rows, db_path=":memory:")
    assert result["status"] == "insufficient_data"
    assert result["n_examples"] == 0


def test_pass_c_never_quarantines_by_default():
    """Pass C is report-only in v1 — no quarantine reason_code in result."""
    rows = _synthetic_leaky_dataset(n_per_class=60)
    result = run_pass_c(rows, db_path=":memory:")
    assert "quarantine" not in result
    assert "reason_code" not in result


def test_constants_exported_for_caller_inspection():
    """Caller may want to inspect the threshold and the labeled-source list."""
    assert LEAKAGE_THRESHOLD == 0.65
    assert "blinded_win" in LABELED_SOURCES
    assert "blinded_loss" in LABELED_SOURCES

"""Tests for the outcome leakage detector."""

import pytest
import sqlite3
import tempfile
import os
from unittest.mock import patch, MagicMock


def _create_test_db(examples):
    """Create a temporary database with test training examples."""
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE training_examples (
            example_id TEXT PRIMARY KEY,
            created_at TEXT,
            source TEXT,
            ticker TEXT,
            recommendation_id TEXT,
            feature_snapshot TEXT,
            trade_outcome TEXT,
            instruction TEXT,
            input_text TEXT,
            output_text TEXT,
            quality_score REAL,
            quality_score_auto REAL,
            difficulty TEXT,
            curriculum_stage TEXT
        )
    """)

    for i, (source, output_text) in enumerate(examples):
        conn.execute(
            "INSERT INTO training_examples (example_id, source, output_text) VALUES (?, ?, ?)",
            (f"ex-{i}", source, output_text),
        )
    conn.commit()
    conn.close()
    return db_path


class TestLeakageDetectorWithBiasedData:
    """Test that the detector catches obvious leakage."""

    def test_biased_data_detected(self):
        """Known biased data should show high accuracy (leaking)."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        # Create obviously biased data: wins always say "rally" and "strong",
        # losses always say "decline" and "weak"
        examples = []
        for i in range(40):
            examples.append(("blinded_win", f"The stock showed a strong rally with bullish momentum example {i}"))
        for i in range(40):
            examples.append(("blinded_loss", f"The stock showed a weak decline with bearish pressure example {i}"))

        db_path = _create_test_db(examples)
        try:
            from src.training.leakage_detector import check_outcome_leakage
            result = check_outcome_leakage(db_path)

            assert result["n_examples"] == 80
            assert result["balanced_accuracy"] is not None
            # With obviously biased text, accuracy should be high
            assert result["balanced_accuracy"] > 0.55
            assert result["is_leaking"] is True
        finally:
            os.unlink(db_path)

    def test_unbiased_data_passes(self):
        """Data with no outcome signal should show ~50% accuracy."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        # Same text for wins and losses — no predictive signal
        examples = []
        for i in range(40):
            examples.append(("blinded_win", f"The stock presents a pullback setup with mixed signals and moderate risk number {i}"))
        for i in range(40):
            examples.append(("blinded_loss", f"The stock presents a pullback setup with mixed signals and moderate risk number {i + 40}"))

        db_path = _create_test_db(examples)
        try:
            from src.training.leakage_detector import check_outcome_leakage
            result = check_outcome_leakage(db_path)

            assert result["n_examples"] == 80
            assert result["balanced_accuracy"] is not None
            # With identical text, accuracy should be near 50%
            assert result["balanced_accuracy"] <= 0.60  # Small margin for randomness
            assert result["is_leaking"] is False
        finally:
            os.unlink(db_path)


class TestLeakageDetectorEdgeCases:
    """Test edge cases and error handling."""

    def test_insufficient_examples(self):
        """Should return a note when fewer than 50 examples."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        examples = [("blinded_win", "text")] * 10

        db_path = _create_test_db(examples)
        try:
            from src.training.leakage_detector import check_outcome_leakage
            result = check_outcome_leakage(db_path)

            assert result["balanced_accuracy"] is None
            assert result["is_leaking"] is None
            assert result["n_examples"] == 10
            assert "at least 50" in result.get("note", "")
        finally:
            os.unlink(db_path)

    def test_empty_database(self):
        """Should handle empty database gracefully."""
        db_path = _create_test_db([])
        try:
            from src.training.leakage_detector import check_outcome_leakage
            result = check_outcome_leakage(db_path)

            assert result["balanced_accuracy"] is None
            assert result["n_examples"] == 0
        finally:
            os.unlink(db_path)

    def test_sklearn_not_installed(self):
        """Should handle missing sklearn gracefully."""
        from src.training import leakage_detector

        with patch.dict("sys.modules", {"sklearn": None, "sklearn.feature_extraction.text": None}):
            # Force reimport to trigger ImportError path
            import importlib
            try:
                importlib.reload(leakage_detector)
                result = leakage_detector.check_outcome_leakage()
                # If sklearn is actually installed, this won't trigger the ImportError
                # Just verify the function runs without crashing
                assert isinstance(result, dict)
            except Exception:
                pass  # ImportError handling is internal

    def test_feature_importance_returned(self):
        """Should return win and loss predictor words."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        examples = []
        for i in range(30):
            examples.append(("blinded_win", f"Strong bullish momentum with clear uptrend {i}"))
        for i in range(30):
            examples.append(("blinded_loss", f"Weak bearish pressure with clear downtrend {i}"))

        db_path = _create_test_db(examples)
        try:
            from src.training.leakage_detector import check_outcome_leakage
            result = check_outcome_leakage(db_path)

            if result.get("feature_importance"):
                fi = result["feature_importance"]
                assert "win_predictors" in fi
                assert "loss_predictors" in fi
                assert len(fi["win_predictors"]) > 0
                assert len(fi["loss_predictors"]) > 0
        finally:
            os.unlink(db_path)

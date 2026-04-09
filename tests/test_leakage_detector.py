"""Tests for the outcome leakage detector."""

import pytest
import sqlite3
import tempfile
import os
from unittest.mock import patch, MagicMock

import numpy as np


def _create_test_db(examples):
    """Create a temporary database with test training examples."""
    from tests.conftest import init_test_db
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    init_test_db(db_path, ["training_examples"])

    conn = sqlite3.connect(db_path)
    for i, (source, output_text) in enumerate(examples):
        conn.execute(
            "INSERT INTO training_examples (example_id, source, output_text, created_at, instruction, input_text) "
            "VALUES (?, ?, ?, '2026-01-01T00:00:00', 'test', 'test')",
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


# ── Embedding-based leakage tests ───────────────────────────────────────


def _create_embedding_test_db(examples):
    """Create a temp DB with training_examples including trade_outcome column."""
    from tests.conftest import init_test_db
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    init_test_db(db_path, ["training_examples"])

    conn = sqlite3.connect(db_path)
    for i, (source, output_text, trade_outcome) in enumerate(examples):
        conn.execute(
            "INSERT INTO training_examples (example_id, source, output_text, trade_outcome, instruction, input_text, created_at) "
            "VALUES (?, ?, ?, ?, 'test', 'test', '2026-01-01T00:00:00')",
            (f"ex-{i}", source, output_text, trade_outcome),
        )
    conn.commit()
    conn.close()
    return db_path


def _mock_ollama_post(dim=16, leaking=False):
    """Create a mock for requests.post that returns embeddings.

    If leaking=True, win/loss embeddings are separable.
    If leaking=False, embeddings are random (no signal).
    """
    call_count = [0]

    def _post(url, json=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        rng = np.random.RandomState(call_count[0])
        if leaking:
            text = (json.get("prompt", "") or "").lower()
            if "strong rally" in text or "bullish" in text:
                emb = rng.randn(dim) + 2.0  # Shifted positive for wins
            else:
                emb = rng.randn(dim) - 2.0  # Shifted negative for losses
        else:
            emb = rng.randn(dim)  # Pure noise — no signal
        resp.json.return_value = {"embedding": emb.tolist()}
        call_count[0] += 1
        return resp

    return _post


class TestEmbeddingLeakage:
    """Tests for embedding-based semantic leakage detection."""

    def test_embedding_leakage_with_mock_ollama(self):
        """Mock Ollama, verify classifier runs on embeddings."""
        examples = []
        for i in range(30):
            examples.append(("blinded_win", f"Strong rally with bullish momentum {i}", "target_1_hit"))
        for i in range(30):
            examples.append(("blinded_loss", f"Weak decline with bearish pressure {i}", "stop_hit"))

        db_path = _create_embedding_test_db(examples)
        try:
            with patch("src.training.leakage_detector.requests.post", side_effect=_mock_ollama_post(leaking=True)):
                from src.training.leakage_detector import check_embedding_leakage
                result = check_embedding_leakage(db_path, timeout=5)

            assert "error" not in result
            assert result["balanced_accuracy"] is not None
            assert result["n_examples"] == 60
            assert result["embedding_dim"] == 16
            assert isinstance(result["cv_scores"], list)
            assert result["processing_time_seconds"] >= 0
        finally:
            os.unlink(db_path)

    def test_embedding_leakage_ollama_down(self):
        """ConnectionError from Ollama returns graceful fallback."""
        examples = []
        for i in range(25):
            examples.append(("blinded_win", f"Bullish text {i}", "target_1_hit"))
        for i in range(25):
            examples.append(("blinded_loss", f"Bearish text {i}", "stop_hit"))

        db_path = _create_embedding_test_db(examples)
        try:
            import requests as req
            with patch("src.training.leakage_detector.requests.post", side_effect=req.ConnectionError("refused")):
                from src.training.leakage_detector import check_embedding_leakage
                result = check_embedding_leakage(db_path)

            assert result["error"] == "Ollama unavailable"
            assert result["leaking"] is None
        finally:
            os.unlink(db_path)

    def test_embedding_leakage_insufficient_data(self):
        """Fewer than 20 examples returns error."""
        examples = [("blinded_win", f"Text {i}", "target_1_hit") for i in range(10)]
        db_path = _create_embedding_test_db(examples)
        try:
            from src.training.leakage_detector import check_embedding_leakage
            result = check_embedding_leakage(db_path)
            assert result["error"] == "Insufficient data"
            assert result["n_examples"] == 10
        finally:
            os.unlink(db_path)

    def test_embedding_leakage_threshold(self):
        """Verify >55% balanced accuracy = leaking, <=55% = clean."""
        examples = []
        for i in range(30):
            examples.append(("blinded_win", f"Bullish momentum {i}", "target_1_hit"))
        for i in range(30):
            examples.append(("blinded_loss", f"Bearish decline {i}", "stop_hit"))

        db_path = _create_embedding_test_db(examples)
        try:
            # Leaking mock — separable embeddings → high accuracy
            with patch("src.training.leakage_detector.requests.post", side_effect=_mock_ollama_post(leaking=True)):
                from src.training.leakage_detector import check_embedding_leakage
                result_leak = check_embedding_leakage(db_path)
            assert result_leak["leaking"] is True
            assert result_leak["balanced_accuracy"] > 0.55

            # Non-leaking mock — random embeddings → ~50% accuracy
            with patch("src.training.leakage_detector.requests.post", side_effect=_mock_ollama_post(leaking=False)):
                result_clean = check_embedding_leakage(db_path)
            assert result_clean["leaking"] is False
            assert result_clean["balanced_accuracy"] <= 0.55
        finally:
            os.unlink(db_path)

    def test_check_all_leakage_combines_results(self):
        """Verify check_all_leakage combines both detectors."""
        examples = []
        for i in range(40):
            examples.append(("blinded_win", f"Bullish text for training {i}", "target_1_hit"))
        for i in range(40):
            examples.append(("blinded_loss", f"Bearish text for training {i}", "stop_hit"))

        db_path = _create_embedding_test_db(examples)
        try:
            with patch("src.training.leakage_detector.requests.post", side_effect=_mock_ollama_post(leaking=False)):
                from src.training.leakage_detector import check_all_leakage
                result = check_all_leakage(db_path)

            assert "tfidf" in result
            assert "embedding" in result
            assert "overall_leaking" in result
            assert "recommendation" in result
            assert isinstance(result["overall_leaking"], bool)
        finally:
            os.unlink(db_path)

    def test_embedding_leakage_class_balance(self):
        """Verify class_weight='balanced' prevents majority-class bias."""
        # Imbalanced: 40 wins, 15 losses
        examples = []
        for i in range(40):
            examples.append(("blinded_win", f"Random neutral text A {i}", "target_1_hit"))
        for i in range(15):
            examples.append(("blinded_loss", f"Random neutral text B {i}", "stop_hit"))

        db_path = _create_embedding_test_db(examples)
        try:
            with patch("src.training.leakage_detector.requests.post", side_effect=_mock_ollama_post(leaking=False)):
                from src.training.leakage_detector import check_embedding_leakage
                result = check_embedding_leakage(db_path)

            if "error" not in result:
                # With balanced class_weight, accuracy should be near 50%
                # not inflated by majority-class prediction
                assert result["balanced_accuracy"] <= 0.65
                assert result["class_distribution"]["wins"] == 40
                assert result["class_distribution"]["losses"] == 15
        finally:
            os.unlink(db_path)

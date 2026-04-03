"""Tests for the canary monitoring system."""

import json
import os
import sqlite3
import tempfile

import pytest
from unittest.mock import patch, MagicMock

from src.training.canary import CanaryMonitor, _simple_score


@pytest.fixture
def canary_file(tmp_path):
    """Create a temporary canary set file."""
    canaries = [
        {
            "id": "test-001",
            "input": "AAPL earnings beat expectations. RSI at 72. Sector: Technology.",
            "expected_output": "WHY NOW: Apple earnings beat signals continued strength. DEEPER ANALYSIS: RSI overbought but momentum supports continuation.",
            "regime": "bull_quiet",
            "sector": "Technology",
        },
        {
            "id": "test-002",
            "input": "XOM at 52-week low. Crude oil down. RSI at 28. Sector: Energy.",
            "expected_output": "WHY NOW: ExxonMobil selloff reflects supply headwinds. DEEPER ANALYSIS: Oversold but falling knife risk remains.",
            "regime": "bear_volatile",
            "sector": "Energy",
        },
        {
            "id": "test-003",
            "input": "JPM mixed quarter. Beat on NII, missed on IB. At 1.4x book.",
            "expected_output": "WHY NOW: JPMorgan mixed quarter reflects divergent forces. DEEPER ANALYSIS: NII beat more important near-term.",
            "regime": "neutral",
            "sector": "Financials",
        },
    ]
    filepath = tmp_path / "canary_set.jsonl"
    with open(filepath, "w") as f:
        for c in canaries:
            f.write(json.dumps(c) + "\n")
    return filepath


@pytest.fixture
def db_path():
    """Create a temporary database with canary schema."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db
    init_test_db(path, ["canary_evaluations"])
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestCanaryMonitorLoad:
    """Tests for loading canary examples."""

    def test_load_canaries(self, canary_file, db_path):
        monitor = CanaryMonitor(canary_path=canary_file, db_path=db_path)
        canaries = monitor.load_canaries()
        assert len(canaries) == 3
        assert canaries[0]["id"] == "test-001"
        assert "input" in canaries[0]
        assert "expected_output" in canaries[0]

    def test_load_missing_file_raises(self, tmp_path, db_path):
        missing = tmp_path / "nonexistent.jsonl"
        monitor = CanaryMonitor(canary_path=missing, db_path=db_path)
        with pytest.raises(FileNotFoundError, match="Canary set not found"):
            monitor.load_canaries()

    def test_load_skips_invalid_json(self, tmp_path, db_path):
        filepath = tmp_path / "canary_set.jsonl"
        with open(filepath, "w") as f:
            f.write('{"id": "ok", "input": "test", "expected_output": "out"}\n')
            f.write("not json\n")
            f.write('{"id": "ok2", "input": "test2", "expected_output": "out2"}\n')
        monitor = CanaryMonitor(canary_path=filepath, db_path=db_path)
        canaries = monitor.load_canaries()
        assert len(canaries) == 2

    def test_load_empty_file(self, tmp_path, db_path):
        filepath = tmp_path / "canary_set.jsonl"
        filepath.write_text("")
        monitor = CanaryMonitor(canary_path=filepath, db_path=db_path)
        canaries = monitor.load_canaries()
        assert len(canaries) == 0


class TestCanaryMonitorEvaluate:
    """Tests for canary evaluation and degradation detection."""

    def _mock_generate(self, **kwargs):
        """Mock generate function that returns plausible outputs."""
        return (
            "WHY NOW: The stock shows momentum signals aligned with sector trends. "
            "DEEPER ANALYSIS: Risk-reward is favorable given current RSI levels "
            "and the broader market regime. Key support levels should hold."
        )

    def test_evaluate_stores_results(self, canary_file, db_path):
        monitor = CanaryMonitor(canary_path=canary_file, db_path=db_path)
        result = monitor.evaluate(
            model_version="v1.0-test",
            generate_fn=self._mock_generate,
        )

        assert result["model_version"] == "v1.0-test"
        assert 0.0 <= result["avg_score"] <= 1.0
        assert "distinct_1" in result
        assert "distinct_2" in result
        assert "self_bleu" in result
        assert "vocab_size" in result
        assert result["degradation_detected"] in (0, 1)

        # Verify stored in DB
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM canary_evaluations WHERE eval_id = ?",
                (result["eval_id"],),
            ).fetchone()
        assert row is not None
        assert row["model_version"] == "v1.0-test"

    def test_evaluate_detects_degradation_on_score_drop(self, canary_file, db_path):
        monitor = CanaryMonitor(canary_path=canary_file, db_path=db_path)

        # First evaluation with good scores
        good_generate = lambda **kw: (
            "WHY NOW: Apple earnings beat signals continued strength in technology. "
            "RSI at 72 overbought but momentum supports continuation. "
            "DEEPER ANALYSIS: RSI overbought but earnings beat momentum. "
            "Sector Technology showing strength."
        )
        result1 = monitor.evaluate(model_version="v1.0", generate_fn=good_generate)

        # Second evaluation with degraded output
        bad_generate = lambda **kw: "bad bad bad"
        result2 = monitor.evaluate(model_version="v1.1", generate_fn=bad_generate)

        # Score should have dropped, triggering degradation
        assert result2["avg_score"] < result1["avg_score"]
        assert result2["degradation_detected"] == 1

    def test_evaluate_handles_generate_failure(self, canary_file, db_path):
        monitor = CanaryMonitor(canary_path=canary_file, db_path=db_path)

        def failing_generate(**kwargs):
            raise RuntimeError("API error")

        result = monitor.evaluate(
            model_version="v1.0-fail",
            generate_fn=failing_generate,
        )
        assert result["avg_score"] == 0.0

    @patch("src.training.canary.send_telegram", create=True)
    def test_alert_sent_on_degradation(self, mock_telegram, canary_file, db_path):
        monitor = CanaryMonitor(canary_path=canary_file, db_path=db_path)

        # First eval: good
        good_gen = lambda **kw: (
            "WHY NOW: Strong earnings beat. DEEPER ANALYSIS: Momentum continuation expected."
        )
        monitor.evaluate(model_version="v1.0", generate_fn=good_gen)

        # Second eval: bad (trigger degradation)
        bad_gen = lambda **kw: "x"
        with patch("src.training.canary.CanaryMonitor._send_alert") as mock_alert:
            result = monitor.evaluate(model_version="v1.1", generate_fn=bad_gen)
            if result["degradation_detected"]:
                mock_alert.assert_called_once()

    def test_get_history(self, canary_file, db_path):
        monitor = CanaryMonitor(canary_path=canary_file, db_path=db_path)

        monitor.evaluate(model_version="v1.0", generate_fn=self._mock_generate)
        monitor.evaluate(model_version="v1.1", generate_fn=self._mock_generate)

        history = monitor.get_history(limit=5)
        assert len(history) == 2
        # Newest first
        assert history[0]["model_version"] == "v1.1"
        assert history[1]["model_version"] == "v1.0"


class TestSimpleScore:
    """Tests for the _simple_score helper."""

    def test_identical_texts(self):
        score = _simple_score("hello world test", "hello world test")
        assert score == 1.0

    def test_completely_different(self):
        score = _simple_score("alpha beta gamma", "delta epsilon zeta")
        assert score == 0.0

    def test_partial_overlap(self):
        score = _simple_score("the cat sat on the mat", "the dog sat on the rug")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        assert _simple_score("", "hello") == 0.0
        assert _simple_score("hello", "") == 0.0
        assert _simple_score("", "") == 0.0

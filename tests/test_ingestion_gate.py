"""Tests for training ingestion gates."""

import sqlite3
from collections import Counter

from src.training.ingestion_gate import should_halt_batch, validate_training_example


VALID_EXAMPLE = """<why_now>
Apple is pulling back in an orderly way toward its rising 50-day moving average after a clean breakout, which often creates a high-quality entry for institutional trend followers.
</why_now>
<analysis>
The stock remains above both its 50-day and 200-day moving averages, and relative strength versus the S&P 500 has stayed positive through the recent market chop. Volume has contracted on the pullback while prior accumulation days remain intact, which suggests the weakness is more likely profit taking than distribution. The setup still aligns with a strong-trend pullback pattern and leaves room for a measured move back toward the highs if the market remains supportive.
</analysis>
<metadata>
Conviction: 8
Direction: LONG
Time Horizon: 5-10 trading days
Key Risk: A sharp macro risk-off move could break the pullback structure
</metadata>"""


def _make_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE training_examples (output_text TEXT, created_at TEXT)"
        )
        conn.commit()


def test_valid_example_passes(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    ok, reason = validate_training_example(VALID_EXAMPLE, db_path)

    assert ok is True
    assert reason == ""


def test_missing_tags_rejected(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    invalid = VALID_EXAMPLE.replace("<analysis>", "<anal>")

    ok, reason = validate_training_example(invalid, db_path)

    assert ok is False
    assert reason == "missing_or_out_of_order_xml_tags"


def test_bad_conviction_rejected(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    invalid = VALID_EXAMPLE.replace("Conviction: 8", "Conviction: 11")

    ok, reason = validate_training_example(invalid, db_path)

    assert ok is False
    assert reason == "invalid_conviction"


def test_markdown_contamination_rejected(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    invalid = VALID_EXAMPLE.replace("The stock remains", "### The stock remains")

    ok, reason = validate_training_example(invalid, db_path)

    assert ok is False
    assert reason == "markdown_heading"


def test_duplicate_detected(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO training_examples (output_text, created_at) VALUES (?, ?)",
            (VALID_EXAMPLE, "2026-03-29T09:00:00"),
        )
        conn.commit()

    near_duplicate = VALID_EXAMPLE.replace("50-day moving average", "50 day moving average")

    ok, reason = validate_training_example(near_duplicate, db_path)

    assert ok is False
    assert reason == "duplicate_similarity"


def test_should_halt_batch_when_compliance_below_threshold():
    halt, compliance, top_reason = should_halt_batch(
        attempted=10,
        rejected=2,
        rejection_reasons=Counter({"duplicate_similarity": 2}),
    )

    assert halt is True
    assert compliance == 80.0
    assert top_reason == "duplicate_similarity"

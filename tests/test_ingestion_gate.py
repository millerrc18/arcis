"""Tests for training ingestion gates."""

import sqlite3
from collections import Counter
from unittest.mock import patch

from src.training.ingestion_gate import alert_training_halt, should_halt_batch, validate_training_example
from tests.conftest import init_test_db


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
    init_test_db(db_path, ["training_examples"])


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


def test_prompt_validator_metadata_coupling():
    """Coupling test: every system prompt that drives backfill data generation
    MUST tell the LLM about the metadata fields the validator requires.

    Background: in 2026-04 the backfill batch halted at 0% compliance because
    the outcome-conditioned system prompts told Claude to use <metadata> tags
    but never specified that `Conviction: N` and `Direction: V` lines must
    appear inside. The validator rejected every example for missing_conviction.

    This test couples the prompt source to the validator's requirements so the
    same drift can't happen again — if either side changes its field names or
    formats without the other being updated, this test fails immediately.
    """
    from src.training.outcome_prompts import (
        _FORMAT_RULES,
        WINNER_SYSTEM_PROMPT,
        LOSER_SYSTEM_PROMPT,
        TIMEOUT_SYSTEM_PROMPT,
        PASS_SYSTEM_PROMPT,
    )
    from src.training.ingestion_gate import CONVICTION_PATTERN, DIRECTION_PATTERN

    # The format rules block must mention both required fields.
    assert "Conviction:" in _FORMAT_RULES, (
        "_FORMAT_RULES must mention 'Conviction:' so the LLM knows to emit it"
    )
    assert "Direction:" in _FORMAT_RULES, (
        "_FORMAT_RULES must mention 'Direction:' so the LLM knows to emit it"
    )

    # And every prompt that uses _FORMAT_RULES must include those rules.
    for name, prompt in [
        ("WINNER_SYSTEM_PROMPT", WINNER_SYSTEM_PROMPT),
        ("LOSER_SYSTEM_PROMPT", LOSER_SYSTEM_PROMPT),
        ("TIMEOUT_SYSTEM_PROMPT", TIMEOUT_SYSTEM_PROMPT),
        ("PASS_SYSTEM_PROMPT", PASS_SYSTEM_PROMPT),
    ]:
        assert "Conviction:" in prompt, f"{name} must instruct the LLM to emit Conviction:"
        assert "Direction:" in prompt, f"{name} must instruct the LLM to emit Direction:"

    # Sanity-check the validator patterns themselves still recognize the
    # canonical format the prompt asks for. If someone renames a field on
    # either side, this assertion catches it.
    sample_metadata = "Conviction: 7\nDirection: LONG"
    assert CONVICTION_PATTERN.search(sample_metadata), (
        "CONVICTION_PATTERN failed to recognize the canonical 'Conviction: N' "
        "format. Prompt and validator drifted apart again."
    )
    assert DIRECTION_PATTERN.search(sample_metadata), (
        "DIRECTION_PATTERN failed to recognize the canonical 'Direction: V' "
        "format. Prompt and validator drifted apart again."
    )


def test_markdown_contamination_rejected(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    invalid = VALID_EXAMPLE.replace("The stock remains", "### The stock remains")

    ok, reason = validate_training_example(invalid, db_path)

    assert ok is False
    assert reason == "markdown_heading"


def test_inline_bold_emphasis_does_not_trigger_markdown_bold_rejection(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    candidate = VALID_EXAMPLE.replace(
        "which often creates a high-quality entry for institutional trend followers.",
        "which often creates a **high-quality** entry for institutional trend followers.",
    )

    ok, reason = validate_training_example(candidate, db_path)

    assert ok is True
    assert reason == ""


def test_markdown_bold_heading_rejected(tmp_path):
    """Full-line bold headings should be rejected (#334: narrowed to line-spanning only).

    #372: The regex was narrowed in #334 to only match bold that spans the full
    line (structural heading like "**Key Risks:**"). The old test used inline
    bold-then-text which is now intentionally allowed. Updated to use a
    standalone bold heading line which SHOULD be rejected.
    """
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    invalid = VALID_EXAMPLE.replace(
        "The stock remains",
        "**Market context:**\nThe stock remains",
    )

    ok, reason = validate_training_example(invalid, db_path)

    assert ok is False
    assert reason == "markdown_bold"


def test_inline_bold_with_punctuation_stays_valid(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    candidate = VALID_EXAMPLE.replace(
        "which often creates a high-quality entry for institutional trend followers.",
        "which often creates a (**high-quality**) entry for institutional trend followers.",
    )

    ok, reason = validate_training_example(candidate, db_path)

    assert ok is True
    assert reason == ""


def test_duplicate_detected(tmp_path):
    db_path = str(tmp_path / "training.db")
    _make_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO training_examples "
            "(example_id, created_at, source, instruction, input_text, output_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ex-dup-1", "2026-03-29T09:00:00", "test", "test instruction", "test input", VALID_EXAMPLE),
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


def test_alert_training_halt_includes_reason_hint():
    with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
        alert_training_halt(60.0, 4, 10, "markdown_bold")

    message = mock_send.call_args.args[0]
    assert "Top reason: markdown_bold (line-leading **bold** markdown heading)" in message

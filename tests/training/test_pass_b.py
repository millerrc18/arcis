"""Pass B — format drift tests (XML integrity + plain-text labels).

Covers R2 (independent pass) and the sprint's Pass B matrix:
  - Detects missing required XML tags (<why_now>, <analysis>)
  - Detects deprecated tags from older format versions
  - Detects open/close imbalance (malformed)
  - Detects missing input_text required labels
  - Priority ordering of reason codes
"""
from __future__ import annotations

from src.training.audit.pass_b_format import (
    DEPRECATED_OUTPUT_TAGS,
    REQUIRED_INPUT_LABELS,
    REQUIRED_OUTPUT_TAGS,
    check_input_labels,
    check_output_xml,
    decide,
    run_pass_b,
)


# Canonical, well-formed training-row sample (matches production shape)
CANONICAL_INPUT = (
    "Ticker: AAPL\n"
    "Current Price: $150.00\n"
    "Trend State: uptrend\n"
    "Exit Reason: target_1_hit\n"
)
CANONICAL_OUTPUT = (
    "<why_now>\n"
    "AAPL is pulling back in a strong uptrend.\n"
    "</why_now>\n"
    "<analysis>\n"
    "Technically compelling.\n"
    "</analysis>\n"
)


# ── output XML checks ────────────────────────────────────────────────


def test_canonical_row_passes_clean():
    d = decide(
        example_id="ok-1",
        output_text=CANONICAL_OUTPUT,
        input_text=CANONICAL_INPUT,
    )
    assert d.quarantine is False
    assert d.reason_code is None


def test_missing_required_tag_flags_missing_section():
    """Remove the whole <analysis>...</analysis> block."""
    d = decide(
        example_id="drift-1",
        output_text="<why_now>\nA thesis.\n</why_now>\n",
        input_text=CANONICAL_INPUT,
    )
    assert d.quarantine is True
    assert d.reason_code == "format_drift_missing_section"
    assert "<analysis>" in d.missing


def test_malformed_unbalanced_open_tag_flags_malformed():
    """<why_now> without a matching </why_now> = malformed."""
    d = decide(
        example_id="drift-2",
        output_text="<why_now>\nUnclosed thesis.\n<analysis>\nx\n</analysis>\n",
        input_text=CANONICAL_INPUT,
    )
    assert d.quarantine is True
    assert d.reason_code == "format_drift_malformed"
    assert d.malformed is True


def test_deprecated_tag_flags_deprecated_marker():
    """Presence of <risk_management> = older format version."""
    depr = DEPRECATED_OUTPUT_TAGS[0]
    # Must keep canonical tags balanced so malformed does not fire first
    drifted = (
        CANONICAL_OUTPUT
        + f"<{depr}>legacy content</{depr}>\n"
    )
    d = decide(
        example_id="drift-3",
        output_text=drifted,
        input_text=CANONICAL_INPUT,
    )
    assert d.quarantine is True
    assert d.reason_code == "format_drift_deprecated_marker"
    assert depr in d.deprecated_found


def test_malformed_wins_over_missing_when_both_would_fire():
    """A truncated output with BOTH an unbalanced required tag AND a
    missing other required tag should report malformed (higher priority)."""
    d = decide(
        example_id="drift-4",
        output_text="<why_now>half body",  # unbalanced AND <analysis> missing
        input_text=CANONICAL_INPUT,
    )
    assert d.quarantine is True
    assert d.reason_code == "format_drift_malformed"


def test_deprecated_wins_over_missing():
    """If a row has a deprecated marker AND misses a required label,
    deprecated is the more informative reason."""
    drifted_output = CANONICAL_OUTPUT + "<monitoring>foo</monitoring>\n"
    drifted_input = "Ticker: AAPL\nCurrent Price: $150\n"  # no Trend State:
    d = decide(
        example_id="drift-5",
        output_text=drifted_output,
        input_text=drifted_input,
    )
    assert d.quarantine is True
    assert d.reason_code == "format_drift_deprecated_marker"


# ── input label checks ───────────────────────────────────────────────


def test_missing_trend_state_label_flags_missing_section():
    """Remove a required label → missing_section drift.

    Uses `Trend State:` (100% prevalence in the corpus). The
    `=== ACTUAL OUTCOME ===` banner was evaluated as a candidate
    required label but proved source-specific (historical_backfill
    + synthetic_claude only), so it was dropped from REQUIRED_INPUT_LABELS
    during commit-12 dry-run calibration.
    """
    input_missing = "Ticker: AAPL\nCurrent Price: $150.00\n"
    d = decide(
        example_id="input-drift-1",
        output_text=CANONICAL_OUTPUT,
        input_text=input_missing,
    )
    assert d.quarantine is True
    assert d.reason_code == "format_drift_missing_section"
    assert any("Trend State" in m for m in d.missing)


def test_empty_text_flags_all_missing():
    """Empty input + output → every required field missing."""
    d = decide(example_id="empty", output_text="", input_text="")
    assert d.quarantine is True
    # With empty output, XML required tags absent → not malformed (open=close=0)
    assert d.reason_code == "format_drift_missing_section"
    assert len(d.missing) >= len(REQUIRED_OUTPUT_TAGS) + len(REQUIRED_INPUT_LABELS)


def test_check_input_labels_returns_missing_list():
    missing = check_input_labels("just some text with no labels")
    assert set(missing) == set(REQUIRED_INPUT_LABELS)


def test_check_output_xml_returns_tuple_shape():
    missing, deprecated, malformed = check_output_xml("")
    assert missing == list(REQUIRED_OUTPUT_TAGS)
    assert deprecated == []
    assert malformed is False


# ── batch + moderate strictness ──────────────────────────────────────


def test_run_pass_b_preserves_order_and_batches():
    rows = [
        {"example_id": "a", "output_text": CANONICAL_OUTPUT,
         "input_text": CANONICAL_INPUT},
        {"example_id": "b", "output_text": "<why_now>x", "input_text": ""},
    ]
    decisions = run_pass_b(rows)
    assert [d.example_id for d in decisions] == ["a", "b"]
    assert decisions[0].quarantine is False
    assert decisions[1].quarantine is True


def test_moderate_strictness_accepts_cosmetic_whitespace():
    """Extra blank lines inside tags should NOT flag — moderate strictness."""
    whitespace_output = (
        "<why_now>\n\n\nBody with extra blank lines.\n\n</why_now>\n"
        "\n<analysis>\n\n\n</analysis>\n\n\n"
    )
    d = decide(
        example_id="ws-ok",
        output_text=whitespace_output,
        input_text=CANONICAL_INPUT,
    )
    assert d.quarantine is False

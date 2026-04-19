"""Pass A — v1-attribution citation contamination tests.

Covers R2 (independent pass) + the sprint's Pass-A test matrix:
  - Quarantines when narrative contradicts v2_fixed
  - Does NOT quarantine when narrative is outcome-neutral
  - Correctly parses recommendation_id linkage
  - Degraded mode (no linkage) still runs without raising
"""
from __future__ import annotations

from src.training.audit.pass_a_citation import (
    WIN_SIGNALS,
    LOSS_SIGNALS,
    classify_direction,
    decide,
    run_pass_a,
)
from src.training.audit.taxonomy import (
    INFO_OUTCOME_NEUTRAL_PRESERVED,
    VALID_REASONS,
)


# ── direction classifier ─────────────────────────────────────────────


def test_classify_direction_win():
    text = "The trade was successful trade as price reached target hit."
    assert classify_direction(text) == "win"


def test_classify_direction_loss():
    text = "Price broke support and the trade stopped out near the stop."
    assert classify_direction(text) == "loss"


def test_classify_direction_neutral_when_no_signals():
    text = "The setup shows a pullback in trend above the 50-day SMA."
    assert classify_direction(text) == "neutral"


def test_classify_direction_neutral_when_mixed_signals():
    # Both win and loss signals fire → neutral (low-confidence mixed)
    text = "Price was stopped out early but later recovered for a profitable exit."
    assert classify_direction(text) == "neutral"


def test_classify_direction_empty_text():
    assert classify_direction("") == "neutral"
    assert classify_direction(None) == "neutral"  # type: ignore[arg-type]


def test_word_boundary_prevents_unsuccessful_from_counting_as_success():
    # "successful" matches; "unsuccessful" MUST NOT count as a win signal.
    assert classify_direction("the trade was unsuccessful") == "neutral"


# ── decide(): quarantine logic ───────────────────────────────────────


def test_decide_quarantines_when_narrative_cites_v1_contradicting_v2():
    """v1=loss, v2=win, narrative says 'stopped out' → quarantine."""
    d = decide(
        example_id="ex1",
        output_text="Price broke support and the trade stopped out at the stop level.",
        recommendation_id="rec-123",
        v1_outcome="loss",
        v2_outcome="win",
    )
    assert d.quarantine is True
    assert d.reason_code == "v1_attribution_contradicts_narrative"
    assert d.reason_code in VALID_REASONS
    assert d.narrative_direction == "loss"


def test_decide_preserves_outcome_neutral_v1_linked_example():
    """v1 diverged, but narrative is pattern-only — INFO, not quarantine."""
    d = decide(
        example_id="ex2",
        output_text="Pullback in trend above the rising 50-day moving average.",
        recommendation_id="rec-123",
        v1_outcome="loss",
        v2_outcome="win",
    )
    assert d.quarantine is False
    assert d.reason_code == INFO_OUTCOME_NEUTRAL_PRESERVED


def test_decide_does_not_quarantine_when_v1_and_v2_agree():
    """v1=v2 → not v1-affected, nothing to do."""
    d = decide(
        example_id="ex3",
        output_text="Price reached target hit after a profitable rebound.",
        recommendation_id="rec-456",
        v1_outcome="win",
        v2_outcome="win",
    )
    assert d.quarantine is False
    assert d.reason_code is None


def test_decide_does_not_quarantine_when_narrative_matches_v2():
    """Narrative aligned to post-fix outcome → legit data."""
    d = decide(
        example_id="ex4",
        output_text="Price reversed higher and the trade was profitable.",
        recommendation_id="rec-789",
        v1_outcome="loss",
        v2_outcome="win",
    )
    # direction=win matches v2, so not a contradiction
    assert d.quarantine is False
    assert d.reason_code is None


def test_decide_degraded_mode_no_recommendation_id():
    """No recommendation_id → Pass A skips (not quarantined)."""
    d = decide(
        example_id="ex5",
        output_text="The trade stopped out near support.",
        recommendation_id=None,
        v1_outcome=None,
        v2_outcome=None,
    )
    assert d.quarantine is False
    assert d.reason_code is None
    assert d.v1_outcome is None
    assert d.v2_outcome is None


def test_decide_handles_missing_v1_outcome_gracefully():
    """attribution_trades might have v1_outcome NULL — skip those."""
    d = decide(
        example_id="ex6",
        output_text="Trade was profitable after bouncing off support.",
        recommendation_id="rec-x",
        v1_outcome=None,
        v2_outcome="win",
    )
    assert d.quarantine is False


# ── run_pass_a(): batch mode preserves order ─────────────────────────


def test_run_pass_a_preserves_input_order_and_shape():
    rows = [
        {"example_id": "a", "output_text": "pullback in trend",
         "recommendation_id": "r-a", "v1_outcome": "loss", "v2_outcome": "win"},
        {"example_id": "b", "output_text": "stopped out at the stop",
         "recommendation_id": "r-b", "v1_outcome": "loss", "v2_outcome": "win"},
        {"example_id": "c", "output_text": "setup looks normal",
         "recommendation_id": None, "v1_outcome": None, "v2_outcome": None},
    ]
    decisions = run_pass_a(rows)
    assert [d.example_id for d in decisions] == ["a", "b", "c"]
    # a: neutral narrative + v1-linked → INFO
    assert decisions[0].reason_code == INFO_OUTCOME_NEUTRAL_PRESERVED
    # b: loss narrative matches v1, contradicts v2 → QUARANTINE
    assert decisions[1].quarantine is True
    assert decisions[1].reason_code == "v1_attribution_contradicts_narrative"
    # c: no linkage → no action
    assert decisions[2].quarantine is False
    assert decisions[2].reason_code is None


# ── lexicon sanity — guardrails ──────────────────────────────────────


def test_win_and_loss_lexicons_are_disjoint():
    """No phrase should appear in both lexicons."""
    assert not (set(WIN_SIGNALS) & set(LOSS_SIGNALS))

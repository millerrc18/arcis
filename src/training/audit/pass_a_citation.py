"""Pass A — v1-attribution citation contamination detector (pure logic).

Ground truth for "v1-affected": a row in `attribution_trades` where
`ranker_only_outcome_v1 != ranker_only_outcome`. 1,287 such trades
existed at sprint start. A training example linked via
`recommendation_id` is a candidate for quarantine if its narrative
`output_text` cites the buggy v1 outcome direction and therefore
contradicts the corrected v2 outcome.

Two classifier tiers:
    1. `narrative_direction` — scans output_text for win/loss signals
       (lexicon-based; see WIN_SIGNALS / LOSS_SIGNALS).
    2. `outcome_neutral` — no directional claim; narrative describes
       setup, pattern, or technical structure only. Preserves the row
       (does NOT quarantine) and records an INFO code for the report.

Called by: src.training.audit.core
Calls: src.training.audit.taxonomy
Owns tables: none (pure function; core writes DB updates)
Config keys: none
Tests: tests/training/test_pass_a.py
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.training.audit.taxonomy import INFO_OUTCOME_NEUTRAL_PRESERVED

# Lexicons derived from sampling output_text in v0.26.0 Pass 2 research.
# Matched case-insensitively. Strings are substring-matched on word-ish
# boundaries — see `_matches_lexicon` — so "successful" matches but
# "unsuccessful" does not.
WIN_SIGNALS: tuple[str, ...] = (
    "successful trade",
    "successful entry",
    "profitable",
    "target hit",
    "target reached",
    "hit the target",
    "reached target",
    "mean reversion",
    "bounce",
    "recovered",
    "gain of",
    "gained",
    "rebounded",
    "reversed higher",
)

LOSS_SIGNALS: tuple[str, ...] = (
    "stopped out",
    "stop-out",
    "stop out",
    "failed trade",
    "breakdown",
    "continued decline",
    "rejected",
    "loss of",
    "trade lost",
    "lost the trade",
    "reversed lower",
    "broke support",
    "cascading lower",
)

Direction = Literal["win", "loss", "neutral"]


@dataclass(frozen=True)
class PassADecision:
    """One row's decision."""
    example_id: str
    recommendation_id: str | None
    v1_outcome: str | None
    v2_outcome: str | None
    narrative_direction: Direction
    quarantine: bool
    reason_code: str | None  # taxonomy code OR info code OR None


def _matches_lexicon(text: str, lexicon: tuple[str, ...]) -> bool:
    """Return True if any lexicon phrase appears in text (case-insensitive).

    Phrase-level match; no heavy tokenization. Word-boundary regex is used
    for the first token of each phrase so "successful" doesn't match
    "unsuccessful".
    """
    low = text.lower()
    for phrase in lexicon:
        first_word = phrase.split()[0]
        rest = phrase[len(first_word):]
        if re.search(r"\b" + re.escape(first_word) + re.escape(rest), low):
            return True
    return False


def classify_direction(output_text: str) -> Direction:
    """Infer outcome-direction claim from narrative text.

    Priority: if BOTH win and loss signals fire, return 'neutral' (mixed
    signals aren't a confident claim in either direction). If only one
    fires, return it. If neither, return 'neutral'.
    """
    if not output_text:
        return "neutral"
    win = _matches_lexicon(output_text, WIN_SIGNALS)
    loss = _matches_lexicon(output_text, LOSS_SIGNALS)
    if win and not loss:
        return "win"
    if loss and not win:
        return "loss"
    return "neutral"


def decide(
    *,
    example_id: str,
    output_text: str,
    recommendation_id: str | None,
    v1_outcome: str | None,
    v2_outcome: str | None,
) -> PassADecision:
    """Compute a single row's Pass A decision.

    Args:
        example_id: stable id, echoed in the decision
        output_text: narrative to analyze
        recommendation_id: link to attribution_trades; None if unlinked
        v1_outcome: attribution_trades.ranker_only_outcome_v1 (or None)
        v2_outcome: attribution_trades.ranker_only_outcome (or None)

    Rules:
        1. No link OR v1/v2 agree OR either is None → not v1-affected;
           return neutral non-quarantine.
        2. Narrative outcome-neutral → preserve, record INFO code.
        3. Narrative direction matches v1 AND contradicts v2 → quarantine.
        4. Narrative direction matches v2 → consistent post-fix data,
           not quarantined.
    """
    direction = classify_direction(output_text)
    v1_diverged = (
        v1_outcome is not None
        and v2_outcome is not None
        and v1_outcome != v2_outcome
    )

    if not recommendation_id or not v1_diverged:
        return PassADecision(
            example_id=example_id,
            recommendation_id=recommendation_id,
            v1_outcome=v1_outcome,
            v2_outcome=v2_outcome,
            narrative_direction=direction,
            quarantine=False,
            reason_code=None,
        )

    if direction == "neutral":
        return PassADecision(
            example_id=example_id,
            recommendation_id=recommendation_id,
            v1_outcome=v1_outcome,
            v2_outcome=v2_outcome,
            narrative_direction=direction,
            quarantine=False,
            reason_code=INFO_OUTCOME_NEUTRAL_PRESERVED,
        )

    narrative_matches_v1 = (direction == v1_outcome)
    narrative_matches_v2 = (direction == v2_outcome)

    if narrative_matches_v1 and not narrative_matches_v2:
        return PassADecision(
            example_id=example_id,
            recommendation_id=recommendation_id,
            v1_outcome=v1_outcome,
            v2_outcome=v2_outcome,
            narrative_direction=direction,
            quarantine=True,
            reason_code="v1_attribution_contradicts_narrative",
        )

    return PassADecision(
        example_id=example_id,
        recommendation_id=recommendation_id,
        v1_outcome=v1_outcome,
        v2_outcome=v2_outcome,
        narrative_direction=direction,
        quarantine=False,
        reason_code=None,
    )


def run_pass_a(rows: list[dict]) -> list[PassADecision]:
    """Apply Pass A to each row in rows; return decisions in input order.

    Expected row keys: example_id, output_text, recommendation_id,
    v1_outcome, v2_outcome. Missing keys are treated as None.
    """
    return [
        decide(
            example_id=r["example_id"],
            output_text=r.get("output_text") or "",
            recommendation_id=r.get("recommendation_id"),
            v1_outcome=r.get("v1_outcome"),
            v2_outcome=r.get("v2_outcome"),
        )
        for r in rows
    ]

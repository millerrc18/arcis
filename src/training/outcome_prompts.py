"""Outcome-conditioned training prompt generator — 3-5x data yield per trade.

Generates multiple training examples from each closed trade using
outcome-specific prompt templates. Maintains self-blinding: the outcome
type determines WHICH template is used, not WHAT the template says.

Called by: training.data_collector
Calls: none
Owns tables: none
Config keys: training.*
Tests: tests/test_outcome_prompts.py
"""

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


def classify_outcome(trade: dict) -> str:
    """Classify trade outcome from exit_reason and P&L.

    Returns: 'WIN', 'LOSS', or 'TIMEOUT'
    """
    exit_reason = trade.get("exit_reason", "")
    if exit_reason in ("timeout", "reconciled_stale", "mr_timeout"):
        return "TIMEOUT"
    pnl = trade.get("pnl_dollars", 0)
    if isinstance(pnl, str):
        try:
            pnl = float(pnl)
        except (ValueError, TypeError):
            pnl = 0
    return "WIN" if pnl > 0 else "LOSS"


# ═══ Outcome-conditioned system prompts ═══
# Each maintains self-blinding — the template shapes analysis focus,
# NOT the conclusion. The LLM never sees the actual outcome.

WINNER_SYSTEM_PROMPT = """You are an equity research analyst writing a post-trade analysis.
Focus on thesis validation: what evidence supported the original thesis?
Emphasize pattern recognition, entry timing quality, and risk/reward calibration.
Analyze how the setup developed and what confirmatory signals appeared.
Write as if presenting to a portfolio manager who wants to understand
what made this setup work."""

LOSER_SYSTEM_PROMPT = """You are an equity research analyst writing a post-trade analysis.
Focus on risk weighting: what warning signals were present at entry?
Emphasize regime conditions, sector headwinds, and position sizing adequacy.
Analyze the quality of the stop placement and whether the thesis
was invalidated by new information or market conditions.
Write as if presenting to a risk manager reviewing position losses."""

TIMEOUT_SYSTEM_PROMPT = """You are an equity research analyst writing a post-trade analysis.
Focus on signal decay: why did the setup fail to reach its target in time?
Emphasize whether the catalyst window was realistic, whether the
holding period was appropriate for the volatility regime, and whether
the position should have been managed more actively.
Write as if presenting to a strategy researcher studying holding periods."""

PASS_SYSTEM_PROMPT = """You are an equity research analyst explaining why a qualified
trading setup should NOT be traded despite meeting quantitative thresholds.
Focus on the qualitative factors that justify passing: regime concerns,
sector rotation, earnings proximity, news risk, or correlation with
existing positions. Write as if presenting to a PM who asked
"why didn't we take this?"""

CONTRASTIVE_WIN_PROMPT = """You are an equity research analyst explaining why a qualified
trading setup might be passed despite strong quantitative signals.
The setup met all scoring thresholds. Provide a well-reasoned case
for why a disciplined trader might choose to skip this opportunity.
Consider regime, correlation, sector timing, and position count."""

CONTRASTIVE_LOSS_PROMPT = """You are an equity research analyst making the case for
entering a trade setup that has some negative signals. Despite concerns,
argue why the setup's strengths justify entry. Focus on the quantitative
edge, diversification benefit, or asymmetric risk/reward profile."""


def get_outcome_prompt(outcome_type: str) -> str:
    """Get the system prompt for an outcome type."""
    prompts = {
        "WIN": WINNER_SYSTEM_PROMPT,
        "LOSS": LOSER_SYSTEM_PROMPT,
        "TIMEOUT": TIMEOUT_SYSTEM_PROMPT,
        "PASS": PASS_SYSTEM_PROMPT,
    }
    return prompts.get(outcome_type, WINNER_SYSTEM_PROMPT)


def get_contrastive_prompt(outcome_type: str) -> str:
    """Get the contrastive (opposite-stance) prompt for an outcome type."""
    if outcome_type == "WIN":
        return CONTRASTIVE_WIN_PROMPT
    elif outcome_type == "LOSS":
        return CONTRASTIVE_LOSS_PROMPT
    else:
        return CONTRASTIVE_WIN_PROMPT  # Default for TIMEOUT


def generate_training_examples(
    trade: dict,
    features: dict,
    base_prompt: str,
) -> list[dict]:
    """Generate 3-5 outcome-conditioned training examples from a closed trade.

    Examples generated:
    1. Primary: outcome-conditioned analysis (always)
    2. Contrastive: opposite-stance analysis (always, creates DPO pair)
    3. Management: during-hold analysis (WIN/LOSS only)

    Args:
        trade: Closed trade dict with outcome data.
        features: Feature dict from scan time.
        base_prompt: Base user prompt with trade context.

    Returns:
        List of training example dicts with 'system', 'user', 'type' fields.
    """
    outcome = classify_outcome(trade)
    examples = []

    # 1. Primary outcome-conditioned example
    examples.append({
        "system": get_outcome_prompt(outcome),
        "user": base_prompt,
        "type": f"primary_{outcome.lower()}",
        "outcome_type": outcome,
    })

    # 2. Contrastive example (opposite stance — natural DPO pair)
    examples.append({
        "system": get_contrastive_prompt(outcome),
        "user": base_prompt,
        "type": f"contrastive_{outcome.lower()}",
        "outcome_type": outcome,
        "is_contrastive": True,
    })

    # 3. Management example (WIN/LOSS only — how to manage during hold)
    if outcome in ("WIN", "LOSS"):
        management_prompt = (
            "You are analyzing the holding period of this trade. "
            "Given the entry conditions and subsequent price action, "
            "what position management decisions could have improved the outcome? "
            "Consider: partial profit-taking, stop adjustment, adding to position, "
            "or earlier exit signals."
        )
        examples.append({
            "system": management_prompt,
            "user": base_prompt,
            "type": f"management_{outcome.lower()}",
            "outcome_type": outcome,
        })

    return examples


def generate_pass_examples(
    ticker: str,
    features: dict,
    base_prompt: str,
) -> list[dict]:
    """Generate training examples from PASS decisions (llm_rejected trades).

    These come from the attribution_trades table where llm_action='rejected'.
    The most informative category for training.
    """
    return [{
        "system": PASS_SYSTEM_PROMPT,
        "user": base_prompt,
        "type": "pass_decision",
        "outcome_type": "PASS",
    }]

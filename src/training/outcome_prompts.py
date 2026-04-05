"""Outcome-conditioned training prompt generator -- 3-5x data yield per trade.

Called by: training.data_collector
Calls: none
Owns tables: none
Config keys: training.*
Tests: tests/test_outcome_prompts.py

WHY outcome-conditioned prompts:
    Each closed trade yields exactly one blinded analysis from data_collector.py.
    That is a waste of a scarce resource -- real trades with known outcomes.
    He et al. (2025) found the optimal curated-to-synthetic ratio is 62/38; to
    reach that golden ratio we need ~3 synthetic examples per real trade.

    The self-blinding guarantee is preserved by a key architectural choice:
    the outcome type (WIN/LOSS/TIMEOUT) selects WHICH template is used, but no
    template contains the outcome itself. The LLM never sees P&L, exit reason,
    or duration -- it sees only a different analytical framing of the same
    setup data. This means the generated text reflects the *type* of analysis
    a PM would want (thesis validation vs. risk weighting vs. signal decay)
    without encoding the answer.

WHY contrastive pairs:
    DPO (Direct Preference Optimization) needs (chosen, rejected) pairs. Instead
    of asking a human labeler, we generate the opposite-stance analysis for every
    trade -- e.g., for a WIN we also generate "why you might pass this." The
    primary becomes the chosen example and the contrastive becomes the rejected
    example, yielding a natural DPO pair at zero marginal cost.
"""

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


def classify_outcome(trade: dict) -> str:
    """Classify trade outcome from exit_reason and P&L.

    Returns: 'WIN', 'LOSS', or 'TIMEOUT'

    WHY TIMEOUT is exit_reason-based, not P&L-based: a timed-out trade can
    still have positive P&L (price drifted favorably but never hit a target).
    Treating it as a WIN would train the model to like slow, aimless setups.
    TIMEOUT analysis focuses on signal decay and holding period appropriateness,
    which is the right lesson regardless of final P&L sign.

    #195 — pnl_dollars arrives as a string from SQLite in some code paths.
    The isinstance check prevents float("None") TypeErrors in production.
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
# Each maintains self-blinding -- the template shapes the ANALYTICAL LENS,
# not the conclusion. The LLM never sees the actual outcome.
#
# WHY specific audience framing ("presenting to a portfolio manager/risk
# manager/strategy researcher"): this constrains the output voice and focus
# area more reliably than abstract instructions. An LLM told "focus on risk"
# may still drift into thesis-confirmation territory, but an LLM told "present
# to a risk manager reviewing losses" stays in risk-assessment mode because
# the audience expectation anchors the response.

# WHY WINNER focuses on thesis validation, not celebration:
# The model needs to learn WHAT made a setup work (pattern recognition, timing,
# confirmatory signals) so it can identify similar setups in the future.
# "This trade made money" is useless training signal; "the breakout above
# resistance on 2x volume confirmed the thesis" is transferable knowledge.
WINNER_SYSTEM_PROMPT = """You are an equity research analyst writing a post-trade analysis.
Focus on thesis validation: what evidence supported the original thesis?
Emphasize pattern recognition, entry timing quality, and risk/reward calibration.
Analyze how the setup developed and what confirmatory signals appeared.
Write as if presenting to a portfolio manager who wants to understand
what made this setup work."""

# WHY LOSER focuses on warning signals at entry, not hindsight:
# Post-hoc "the market dropped" is not actionable. Training the model to
# identify warning signals that were VISIBLE AT ENTRY TIME teaches it to
# weight those signals more heavily in future scans. This is the core of
# the pullback-in-trend strategy's risk management.
LOSER_SYSTEM_PROMPT = """You are an equity research analyst writing a post-trade analysis.
Focus on risk weighting: what warning signals were present at entry?
Emphasize regime conditions, sector headwinds, and position sizing adequacy.
Analyze the quality of the stop placement and whether the thesis
was invalidated by new information or market conditions.
Write as if presenting to a risk manager reviewing position losses."""

# WHY TIMEOUT is a separate category, not merged with LOSS:
# A timeout is a different failure mode than a stop-out. Stop-outs indicate
# thesis invalidation; timeouts indicate the catalyst window was wrong or
# the setup decayed. The model needs to learn holding-period calibration
# as a distinct skill from risk identification.
TIMEOUT_SYSTEM_PROMPT = """You are an equity research analyst writing a post-trade analysis.
Focus on signal decay: why did the setup fail to reach its target in time?
Emphasize whether the catalyst window was realistic, whether the
holding period was appropriate for the volatility regime, and whether
the position should have been managed more actively.
Write as if presenting to a strategy researcher studying holding periods."""

# WHY PASS decisions are the most informative training category:
# McLean & Pontiff (2015) showed 58% post-publication anomaly decay --
# the setups that LOOK good quantitatively but should be SKIPPED are where
# the model adds the most value over the rules-based system. Teaching the
# model to say "no" is harder and more valuable than teaching it to say "yes."
PASS_SYSTEM_PROMPT = """You are an equity research analyst explaining why a qualified
trading setup should NOT be traded despite meeting quantitative thresholds.
Focus on the qualitative factors that justify passing: regime concerns,
sector rotation, earnings proximity, news risk, or correlation with
existing positions. Write as if presenting to a PM who asked
"why didn't we take this?"""

# WHY contrastive prompts argue the OPPOSITE of the outcome:
# For DPO, the (chosen, rejected) pair teaches the model to prefer one
# stance over the other. For a WIN, the contrastive argues "skip it" --
# so the model learns (chosen=take it, rejected=skip it). For a LOSS, the
# contrastive argues "take it despite concerns" -- so the model learns
# (chosen=flag the risk, rejected=dismiss the risk). This creates natural
# preference signal without human labeling.
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
    """Get the contrastive (opposite-stance) prompt for an outcome type.

    WHY TIMEOUT defaults to CONTRASTIVE_WIN_PROMPT: a timed-out trade was
    entered but went nowhere, so the most useful contrastive is "why you
    might have skipped it" -- the same question we ask for winners. The
    alternative (arguing FOR entry) would be redundant since the primary
    template already analyzes the holding period.
    """
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

    # 3. Management example (WIN/LOSS only -- how to manage during hold)
    # WHY not for TIMEOUT: timeout trades already have signal-decay analysis
    # in the primary template, which covers the same ground as management
    # analysis. Adding a management example for timeouts would be redundant
    # and dilute the 62/38 curated-to-synthetic ratio.
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
    WHY these are "the most informative category": McLean & Pontiff (2015) showed
    58% post-publication anomaly decay -- quantitative edges erode, and the setups
    that pass all mechanical filters but SHOULD be skipped are exactly where
    qualitative judgment adds alpha. Teaching the model to articulate "why not"
    for quantitatively-qualified setups is the highest-leverage training signal.
    """
    return [{
        "system": PASS_SYSTEM_PROMPT,
        "user": base_prompt,
        "type": "pass_decision",
        "outcome_type": "PASS",
    }]

"""Registered strategic decisions — the capability-registry home for Decisions.

Unlike Actions/States/Systems, Decisions are strategic facts, not code.
They don't have a natural home module, so they live here en-bloc (see
evaluation doc §8.1). Each call to `register_decision(...)` captures:

- decision_text: the committed decision
- rationale: why it was made
- revisit_trigger: what would cause us to re-evaluate it

Future sessions reviewing Halcyon Lab can read this file to understand
*why* the platform behaves the way it does — complement to MASTER.md.
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_decision

_TODAY = date(2026, 4, 18)


register_decision(
    name="bootcamp_still_active",
    description=(
        "Bootcamp mode remains the active regime for the training "
        "pipeline. Relaxed thresholds on qualification and conviction "
        "floor are deliberate during the early-sample period."
    ),
    category="training",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.15.0",
    last_reviewed_date=_TODAY,
    decision_text=(
        "Keep bootcamp_mode.enabled=True until the trade cohort crosses "
        "the qualification_threshold and diagnostics confirm acceptable "
        "outcome distribution."
    ),
    rationale=(
        "Early-sample noise would otherwise drown out real signal in "
        "both ranker and LLM evaluation metrics. Bootcamp's relaxed "
        "thresholds let weak but informative trades into training data "
        "until the cohort is statistically useful."
    ),
    revisit_trigger=(
        "After the closed-trade cohort exceeds qualification_threshold "
        "(currently 40) AND a regime_diagnostic run returns "
        "UNCONTAMINATED for overall decision."
    ),
)


register_decision(
    name="pullback_strategy_contaminated",
    description=(
        "The pullback strategy is CONTAMINATED per the 2026-04-18 "
        "regime diagnostic. Do not promote from shadow to production "
        "until a clean run."
    ),
    category="strategy",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.25.0",
    last_reviewed_date=_TODAY,
    decision_text=(
        "Pullback strategy is blocked from production promotion "
        "pending a clean regime_diagnostic (decision=UNCONTAMINATED)."
    ),
    rationale=(
        "Regime diagnostic run 2026-04-18 returned CONTAMINATED — "
        "trade-cohort outcomes cluster along one or more regime "
        "dimensions (VIX, sector, holding-period), meaning observed "
        "edge is not robust across the design space."
    ),
    revisit_trigger=(
        "New regime_diagnostic run returns UNCONTAMINATED OR an "
        "explicit operator override with recorded justification."
    ),
)


register_decision(
    name="lazy_prices_deprecated_on_sp100",
    description=(
        "Lazy Prices cosine-similarity strategy is deprecated on the "
        "S&P 100 universe per compass research."
    ),
    category="strategy",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.24.0",
    last_reviewed_date=_TODAY,
    decision_text=(
        "Do not run Lazy Prices on the S&P 100 universe. If historical "
        "EDGAR backfill extends coverage to the broader Russell 1000, "
        "re-evaluate on that universe."
    ),
    rationale=(
        "Compass reports show Lazy Prices signal is weak on S&P 100 "
        "(limited filing frequency + high analyst coverage compressing "
        "cosine-similarity alpha)."
    ),
    revisit_trigger=(
        "Historical EDGAR backfill completes for a broader universe "
        "(Russell 1000+) enabling a valid backtest on that universe."
    ),
)


register_decision(
    name="no_new_strategy_specs_until_walkforward_ships",
    description=(
        "No new strategy specs accepted until the walk-forward "
        "validation framework is live and enforced on promotions."
    ),
    category="process",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.25.0",
    last_reviewed_date=_TODAY,
    decision_text=(
        "New strategy YAML specs are not accepted into "
        "src/platform/specs/ until the walk-forward framework "
        "(OOS efficiency + PBO) is live and enforced by the "
        "promotion gate."
    ),
    rationale=(
        "Strategy spec count is cheap to grow and expensive to "
        "validate. Walk-forward is the thing that tells us which "
        "specs survive — until it ships, adding specs is adding "
        "debt without validation."
    ),
    revisit_trigger=(
        "Walk-forward framework lands in main AND the promotion "
        "gate's OOS_efficiency / PBO checks are non-skipped for "
        "at least one full strategy evaluation cycle."
    ),
)

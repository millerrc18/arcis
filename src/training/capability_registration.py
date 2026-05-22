"""Capability registrations for the training pipeline family (T7 keep-set).

Keep-set (3 entries):
  - run_finetune           ACTION   — fine-tune orchestrator (trainer.run_fine_tune)
  - model_promotion_gate   DECISION — grouped: 50-trade gate + canary + promotion criteria
  - training_quality_filter DECISION — grouped: quality scoring + drift + leakage + ingestion

Deferred (seed into Convention E EXEMPT_MODULES in Task 10):
  evaluate_holdout, rollback_model, build_training_corpus, run_dpo

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_*, lazy imports inside fns
Owns tables: none
Config keys: none
Tests: tests/test_capability_registry_coverage.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action, register_decision
from src.platform.capability_registry._io_schemas import simple_io_schema

_TODAY = date(2026, 5, 21)
_INTRODUCED = "v0.36.49"


# ---------------------------------------------------------------------------
# run_finetune — ACTION
# Real kickoff: POST /api/training/train (src/api/routes/training.py:50).
# Distinct from training_corpus STATE and training_data_audit ACTION.
# ---------------------------------------------------------------------------

@register_action(
    name="run_finetune",
    description=(
        "Orchestrate a full fine-tuning run via trainer.run_fine_tune(): "
        "export data with temporal holdout split, train via 3-stage "
        "curriculum, run canary + holdout evaluation, auto-rollback if "
        "expectancy or win-rate drops. Unloads/reloads Ollama around training."
    ),
    category="training",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    kickoff_endpoint="/api/training/train",
    input_schema=simple_io_schema(
        properties={
            "force": {
                "type": "boolean",
                "description": "Bypass the auto_train_min_examples threshold check.",
            },
        },
        required=[],
    ),
    output_schema=simple_io_schema(
        properties={
            "success": {"type": "boolean"},
            "model_version": {"type": "string"},
            "rolled_back": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        required=["success"],
    ),
    estimated_duration="30-90 minutes",
)
def run_finetune_capability() -> dict:
    return {
        "registered_at": _TODAY.isoformat(),
        "entry_module": "src.training.capability_registration",
    }


# ---------------------------------------------------------------------------
# model_promotion_gate — DECISION
# Grouped: 50-trade gate + canary + promotion criteria (methods/promotion_gate.py).
# ---------------------------------------------------------------------------

register_decision(
    name="model_promotion_gate",
    description=(
        "Grouped promotion-gate criteria governing when a fine-tuned model "
        "advances to champion. Folds together: minimum 50-trade track-record "
        "guard, canary evaluation on reference examples, and the combined "
        "holdout win-rate / expectancy threshold."
    ),
    category="training",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    decision_text=(
        "A new model version is promoted to champion only when: "
        "(1) the closed-trade cohort exceeds the MinTRL threshold (50 trades); "
        "(2) canary evaluation passes reference examples; "
        "(3) holdout win-rate and expectancy do not drop below the "
        "auto_rollback thresholds vs. the current champion."
    ),
    rationale=(
        "Promoting an undertrained model on insufficient data or a model "
        "that degrades reference examples corrupts the champion baseline. "
        "The three-gate design separates statistical readiness (MinTRL) "
        "from regression detection (canary) from live-performance "
        "preservation (holdout delta)."
    ),
    revisit_trigger=(
        "If the cohort reaches 200+ trades and canary pass-rate is "
        "consistently above 95%, consider relaxing MinTRL. Revisit "
        "auto_rollback thresholds after each benchmark cycle."
    ),
)


# ---------------------------------------------------------------------------
# training_quality_filter — DECISION
# Grouped: quality scoring + drift + leakage + ingestion gate.
# ---------------------------------------------------------------------------

register_decision(
    name="training_quality_filter",
    description=(
        "Grouped quality-filter criteria applied to training examples before "
        "inclusion in the fine-tune corpus. Folds together: LLM-as-Judge "
        "quality scoring (quality_filter.py), feature drift detection "
        "(quality_drift.py), temporal leakage detection (leakage_detector.py), "
        "and the ingestion gate (ingestion_gate.py)."
    ),
    category="training",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    decision_text=(
        "Training examples must pass all four quality gates before inclusion: "
        "(1) LLM quality score >= threshold (process-blind rubric, not outcome); "
        "(2) no detected feature drift vs. current distribution; "
        "(3) no temporal leakage (future features contaminate target); "
        "(4) ingestion gate approves the example for the active curriculum stage."
    ),
    rationale=(
        "Garbage-in garbage-out applies acutely to LLM fine-tuning. "
        "Low-quality examples introduce noise; leakage manufactures false "
        "signal; drift examples train on a stale regime. Each gate is "
        "independent so any single failure blocks inclusion without "
        "requiring all four to agree."
    ),
    revisit_trigger=(
        "If quality-filtered corpus size drops below auto_train_min_examples "
        "after a data collection cycle, audit the quality score threshold. "
        "Revisit leakage window after feature schema changes."
    ),
)

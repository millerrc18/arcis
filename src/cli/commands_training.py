"""CLI command implementations — training & evaluation domain (Arcis).

Called by: cli.commands (re-export), main (via re-export)
Calls: config, council.engine, email.notifier, evaluation.backtester, evaluation.cto_report, evaluation.feature_importance, evaluation.gate_evaluator, services.review_service, services.training_service, training.ab_evaluation, training.backfill, training.bootstrap, training.curriculum, training.dpo_pipeline, training.leakage_detector, training.quality_filter, training.trainer, training.validation, training.versioning
Owns tables: none
Config keys: none
Tests: tests/cli/test_cli_split_integrity.py, tests/cli/test_email_cli_passthrough.py, tests/test_cmd_run_promotion_gate_post_fix.py, tests/training/test_promotion_gate_wiring.py
"""

import json
import logging

from src.config import DB_PATH
from src.utils.db import connect_db
from src.email.notifier import send_email
from src.cli.commands_ops import _safe_print

logger = logging.getLogger(__name__)


def cmd_review(args):
    from src.services.review_service import get_pending_reviews, get_recommendation, submit_review

    sub = getattr(args, "review_sub", "list")
    if sub == "list" or not sub:
        pending = get_pending_reviews()
        if not pending:
            print("No trades pending review.")
            return
        print(f"\nTRADES PENDING REVIEW ({len(pending)}):")
        for row in pending:
            pnl = f"${row.get('shadow_pnl_dollars', 0):+.2f}" if row.get("shadow_pnl_dollars") is not None else "n/a"
            print(f"  {row['recommendation_id'][:8]}..  {row.get('ticker', '?'):6s}  {row.get('created_at', '')[:10]}  P&L={pnl}")
        return
    recommendation = get_recommendation(sub)
    if not recommendation:
        print(f"Recommendation {sub} not found.")
        return
    print(f"\nREVIEW: {recommendation['ticker']} — score {recommendation.get('confidence_score', 'n/a')}/10")
    try:
        approved = input("  Approved? (y/n): ").strip().lower()
        grade = input("  Grade (A/B/C/D/F): ").strip().upper()
        notes = input("  Notes: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    submit_review(
        sub,
        {
            "ryan_approved": 1 if approved == "y" else 0,
            "user_grade": grade if grade in "ABCDF" else None,
            "ryan_notes": notes or None,
        },
    )
    print(f"Review saved for {recommendation['ticker']}.")


def cmd_mark_executed(args):
    from src.services.review_service import mark_executed

    if mark_executed(args.ticker):
        print(f"Marked {args.ticker.upper()} as executed.")
    else:
        print(f"No recommendation found for {args.ticker.upper()}.")


def cmd_review_scorecard(args):
    from src.services.review_service import get_scorecard

    print(get_scorecard(weeks=getattr(args, "weeks", 1)))


def cmd_review_bootcamp(args):
    from src.services.review_service import get_bootcamp_report

    print(get_bootcamp_report(days=getattr(args, "days", 30)))


def cmd_postmortems(args):
    from src.services.review_service import get_postmortems

    results = get_postmortems(limit=getattr(args, "limit", 10), ticker=getattr(args, "ticker", None))
    if not results:
        print("No postmortems available.")
        return
    for row in results:
        print(f"  {row['ticker']:6s}  {row['date']}  {row['exit_reason']:>12s}  ${row['pnl_dollars']:+.2f}  {row['postmortem'][:60]}")


def cmd_postmortem_detail(args):
    from src.services.review_service import get_postmortem_detail

    recommendation = get_postmortem_detail(args.recommendation_id)
    if not recommendation:
        print(f"Not found: {args.recommendation_id}")
        return
    print(f"\nPOSTMORTEM: {recommendation['ticker']}")
    if recommendation.get("assistant_postmortem"):
        print(recommendation["assistant_postmortem"])


def cmd_training_status(args):
    from src.services.training_service import get_training_status

    status = get_training_status()
    print("\nTRAINING STATUS")
    print(f"  Model: {status['model_name']} | Dataset: {status['dataset_total']} examples | New: {status['new_since_last_train']}")
    print(f"  Train queued: {status['train_queued']} ({status['train_reason']})")
    print(f"  Rollback: {status['rollback_status']}")


def cmd_training_history(args):
    from src.services.training_service import get_training_history

    history = get_training_history()
    print("\nMODEL VERSION HISTORY")
    for version in history["versions"]:
        win_rate = f"{version['win_rate']:.1f}%" if version.get("win_rate") else "n/a"
        print(f"  {version['version_name']:<14s} {version['status']:<10s} trades={version['trade_count']}  WR={win_rate}")


def cmd_training_report(args):
    from src.services.training_service import get_training_report

    print(get_training_report())


def cmd_bootstrap_training(args):
    from src.training.bootstrap import estimate_bootstrap_cost, generate_synthetic_training_data

    count = getattr(args, "count", 500)
    cost = estimate_bootstrap_cost(count)
    print(f"Bootstrap: {count} examples, est. ${cost:.2f}")
    if not getattr(args, "yes", False) and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return
    created = generate_synthetic_training_data(count)
    print(f"Bootstrap complete: {created} examples created")


def cmd_backfill_training(args):
    from src.training.backfill import estimate_backfill_cost, run_historical_backfill

    months = getattr(args, "months", 12)
    max_examples = getattr(args, "max_examples", 2000)
    quality_filter = ["clean_win", "clean_loss"]
    if getattr(args, "include_messy", False):
        quality_filter = ["clean_win", "clean_loss", "messy", "timeout"]
    cost = estimate_backfill_cost(max_examples)
    print(f"Backfill: {months}mo, max {max_examples} examples, est. ${cost:.2f}")
    if not getattr(args, "yes", False) and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return
    stats = run_historical_backfill(
        months=months,
        min_score=getattr(args, "min_score", 70),
        quality_filter=quality_filter,
        max_examples=max_examples,
    )
    print(f"Backfill complete: {stats['examples_generated']} examples, ${stats['estimated_cost']:.2f}")


def cmd_train(args):
    from src.training.ab_evaluation import check_promotion_ready
    from src.training.trainer import export_training_data, run_fine_tune, should_train
    from src.training.versioning import (
        get_active_model_version,
        promote_evaluation_model,
        register_model_version,
        rollback_model,
        update_config_model,
    )

    if getattr(args, "register", False):
        active = get_active_model_version()
        if active and active["version_name"].startswith("halcyon-v1."):
            print(f"Active model already registered: {active['version_name']}")
            return
        version_name = "halcyon-v1.0.0"
        if active:
            import sqlite3

            with connect_db(DB_PATH) as conn:
                conn.execute(
                    "UPDATE model_versions SET version_name = ? WHERE version_id = ?",
                    (version_name, active["version_id"]),
                )
            _safe_print(f"Renamed {active['version_name']} -> {version_name}")
        else:
            version_id = register_model_version(
                version_name=version_name,
                examples_count=969,
                synthetic_count=0,
                outcome_count=0,
                model_file_path="halcyonlatest",
            )
            print(f"Registered {version_name} (id={version_id})")
        import subprocess

        try:
            subprocess.run(["ollama", "cp", "halcyonlatest", version_name], capture_output=True, text=True, timeout=60)
            print(f"Created Ollama tag: {version_name}")
        except Exception as exc:
            print(f"Ollama tag failed (do manually: ollama cp halcyonlatest {version_name}): {exc}")
        update_config_model(version_name)
        print(f"Config updated. Dashboard will show {version_name} after restart.")
        return
    if getattr(args, "rollback", False):
        restored = rollback_model()
        print(f"Rolled back to {restored['version_name']}" if restored else "Rollback failed.")
        return
    if getattr(args, "export", False):
        split, count = export_training_data()
        print(f"Exported {count} examples ({split.get('training', 0)} train, {split.get('holdout', 0)} holdout)")
        return
    if not getattr(args, "force", False):
        trigger, reason = should_train()
        if not trigger:
            print(f"Training not needed: {reason}\nUse --force to train anyway.")
            return
    result = run_fine_tune()
    print(f"Training complete: {result['version_name']}" if result else "Training failed.")


def cmd_classify_training(args):
    from src.training.curriculum import classify_all_examples

    result = classify_all_examples()
    print(f"Classified {result['classified']} examples")
    print(f"  Difficulty: {result['difficulty']}")
    print(f"  Stages: {result['stage']}")


def cmd_score_training(args):
    from src.training.quality_filter import score_all_unscored

    result = score_all_unscored()
    print(f"Scored {result['scored']} examples (avg: {result['avg_score']:.2f}), skipped {result['skipped']}")


def cmd_validate_training(args):
    from src.training.validation import validate_training_dataset

    result = validate_training_dataset()
    print(f"\nDATASET VALIDATION ({result['total_examples']} examples)")
    print(f"  Health: {result['overall_health']}")
    print(f"  Format compliance: {result['format_compliance']:.0%}")
    print(f"  Win/loss: {result['wins']}W/{result['losses']}L ({result['win_pct']:.0%})")
    print(f"  Tickers: {result['tickers_represented']} | Sectors: {result['sectors_covered']}")
    print(f"  Duplicates: {result['exact_duplicates']} exact, {result['near_duplicates']} near")
    if result["issues"]:
        print(f"  Issues: {'; '.join(result['issues'])}")


def cmd_generate_contrastive(args):
    from src.training.curriculum import generate_contrastive_training_data

    count = generate_contrastive_training_data(max_pairs=getattr(args, "max_pairs", 50))
    print(f"Generated {count} contrastive training examples")


def cmd_generate_preferences(args):
    from src.training.dpo_pipeline import generate_preference_pairs

    count = generate_preference_pairs(n_pairs=getattr(args, "count", 100))
    print(f"Generated {count} preference pairs")


def cmd_cto_report(args):
    from src.evaluation.cto_report import format_cto_report, generate_cto_report

    report = generate_cto_report(days=getattr(args, "days", 7))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_cto_report(report))
    if getattr(args, "email", False):
        body = json.dumps(report, indent=2, default=str) if getattr(args, "json", False) else format_cto_report(report)
        send_email("[TRADE DESK] CTO Report", body)


def cmd_evaluate_holdout(args):
    from src.training.trainer import evaluate_on_holdout

    print(json.dumps(evaluate_on_holdout(model_name=getattr(args, "model", "halcyon-latest")), indent=2))


def cmd_model_evaluation_status(args):
    from src.training.ab_evaluation import get_evaluation_status

    status = get_evaluation_status()
    if not status:
        print("No model in A/B evaluation.")
        return
    print(f"A/B: {status['model_name']} | {status['evaluations']} evals | WR={status['win_rate']:.0%} | {status['recommendation']}")


def cmd_promote_model(args):
    from src.training.ab_evaluation import check_promotion_ready
    from src.training.versioning import get_evaluation_model, promote_evaluation_model

    evaluation_model = get_evaluation_model()
    if not evaluation_model:
        print("No model in evaluation.")
        return
    if not getattr(args, "force", False):
        status = check_promotion_ready(evaluation_model["version_name"])
        if not status["ready"]:
            print(f"Not ready: {status['recommendation']}. Use --force.")
            return
    promoted = promote_evaluation_model()
    print(f"Promoted {promoted['version_name']}" if promoted else "Promotion failed.")


def cmd_feature_importance(args):
    from src.evaluation.feature_importance import compute_feature_importance

    result = compute_feature_importance(days=getattr(args, "days", 30))
    print(f"\nFEATURE IMPORTANCE ({result['closed_trades']} trades)")
    for feature in result.get("features", []):
        print(f"  {feature['name']:25s}  corr={feature['correlation_with_pnl']:+.3f}  [{feature['predictive_power']}]")


def cmd_backtest(args):
    from src.evaluation.backtester import backtest_model

    print(json.dumps(backtest_model(getattr(args, "model", "halcyon-latest"), months=getattr(args, "months", 6)), indent=2, default=str))


def cmd_compare_models(args):
    from src.evaluation.backtester import compare_models

    print(json.dumps(compare_models(args.model_a, args.model_b, months=getattr(args, "months", 3)), indent=2, default=str))


def cmd_check_leakage(args):
    from src.training.leakage_detector import check_outcome_leakage

    result = check_outcome_leakage()
    print("\n=== OUTCOME LEAKAGE TEST ===")
    if result.get("balanced_accuracy") is None:
        print(f"  {result.get('note', 'Insufficient data')}")
    else:
        print(f"  Status:            {result['status']}")
        print(f"  Balanced Accuracy: {result['balanced_accuracy']:.1%} (CLEAN ≤55%, MARGINAL 55-65%, LEAKING >65%)")
        print(f"  Raw Accuracy:      {result['raw_accuracy']:.1%}")
        print(f"  Majority Baseline: {result['majority_baseline']:.1%} (predicting all-majority-class)")
        print(f"  Above Baseline:    {result['accuracy_above_baseline']:+.1%}")
        class_balance = result.get("class_balance", {})
        print(f"  Class Balance:     {class_balance.get('wins', 0)} wins / {class_balance.get('losses', 0)} losses ({class_balance.get('win_pct', 0)}% win)")
        print(f"  Examples:          {result['n_examples']}")
        if result.get("feature_importance"):
            importance = result["feature_importance"]
            print(f"  Win predictors:    {', '.join(importance['win_predictors'][:3])}")
            print(f"  Loss predictors:   {', '.join(importance['loss_predictors'][:3])}")
        if result["is_leaking"]:
            print("\n  ACTION: Commentary text predicts outcomes beyond feature-level signal.")
            print("  Investigate whether language reveals directional expectations.")
        elif result["status"] == "MARGINAL":
            print("\n  MARGINAL: Some signal detected, likely feature-level (not outcome leakage).")
            print("  Safe to proceed with training. Monitor on future datasets.")
        else:
            print("\n  Commentary is outcome-independent. Safe to fine-tune.")


def cmd_run_promotion_gate(args):
    """Run the promotion gate against an existing model version by name."""
    import sqlite3 as _sqlite3
    from src.training.trainer import run_promotion_gate_for_version  # noqa: F401 (needed for patch)

    version_name = args.version_name
    n_trials = getattr(args, "n_trials", 1)

    with connect_db(DB_PATH) as conn:
        conn.row_factory = _sqlite3.Row
        row = conn.execute(
            "SELECT version_id, version_name FROM model_versions WHERE version_name = ?",
            (version_name,),
        ).fetchone()

    if not row:
        print(f"Version not found: {version_name}")
        return

    result = run_promotion_gate_for_version(
        version_id=row["version_id"],
        version_name=row["version_name"],
        db_path=DB_PATH,
        n_trials=n_trials,
    )
    print(f"Promotion gate result: decision={result['decision']} status={result['status']}")


def cmd_train_pipeline(args):
    """Run the complete training pipeline end-to-end."""
    from src.training.curriculum import classify_all_examples
    from src.training.leakage_detector import check_outcome_leakage
    from src.training.quality_filter import score_all_unscored
    from src.training.trainer import run_fine_tune

    print("\n=== ARCIS TRAINING PIPELINE ===\n")

    print("[1/5] Scoring unscored training examples...")
    result = score_all_unscored()
    print(f"  Scored {result.get('scored', 0)} examples")

    print("\n[2/5] Running outcome leakage test...")
    leakage = check_outcome_leakage()
    if leakage.get("is_leaking"):
        print(f"  LEAKING — balanced accuracy {leakage['balanced_accuracy']:.1%}")
        if not getattr(args, "force", False):
            print("  ABORT: Fix leakage before training. Use --force to override.")
            return
        print("  --force: Proceeding despite leakage warning")
    else:
        balanced_accuracy = leakage.get("balanced_accuracy")
        status = leakage.get("status", "CLEAN")
        print(f"  {status} — balanced accuracy {balanced_accuracy:.1%}" if balanced_accuracy else f"  {status}")

    print("\n[3/5] Classifying training examples...")
    classify_result = classify_all_examples()
    print(f"  Classified {classify_result.get('classified', 0)} examples")

    print("\n[4/5] Exporting training data...")
    print("\n[5/5] Starting fine-tuning...")
    fine_tune_result = run_fine_tune()
    if fine_tune_result:
        print(f"\n  Model registered: {fine_tune_result.get('version_name', 'halcyon-latest')}")
        print("  TRAINING PIPELINE COMPLETE")
    else:
        print("\n  Training failed. Check logs.")


def cmd_evaluate_gate(args):
    """Run the 50-trade gate evaluation."""
    from src.evaluation.gate_evaluator import evaluate_50_trade_gate

    print("\n=== 50-TRADE GATE EVALUATION ===\n")
    result = evaluate_50_trade_gate()

    gates = result.get("gates", {})
    for key, gate in gates.items():
        status_icon = {"green": "[OK]", "yellow": "[WARN]", "red": "[FAIL]"}.get(gate.get("status"), "[--]")
        _safe_print(f"  {status_icon} {gate.get('label', key)}: {gate.get('value', 'n/a')} (green: {gate.get('green', 'n/a')}, yellow: {gate.get('yellow', 'n/a')})")

    print(f"\n  Trade count: {result.get('trade_count', 0)}")
    print(f"  Greens: {result.get('greens', 0)}, Reds: {result.get('reds', 0)}")
    print(f"\n  DECISION: {result.get('decision', 'insufficient data')}\n")

    if result.get("psr") is not None:
        print(f"  PSR(0): {result['psr']:.1%}")
    if result.get("bootstrap_ci"):
        ci = result["bootstrap_ci"]
        print(f"  Bootstrap Sharpe CI: [{ci[0]:.3f}, {ci[2]:.3f}]")


def cmd_performance_report(args):
    """Generate a performance report."""
    from src.evaluation.cto_report import format_cto_report, generate_cto_report

    days = getattr(args, "days", 30)
    print(f"\n=== PERFORMANCE REPORT (last {days} days) ===\n")
    try:
        data = generate_cto_report(days=days)
        print(format_cto_report(data))
    except Exception as exc:
        print(f"Error generating report: {exc}")


def cmd_council(args):
    from src.council.engine import CouncilEngine

    session_type = getattr(args, "type", "daily")
    question = getattr(args, "question", None)
    if question:
        session_type = "strategic"
    print(f"Running AI Council session (type: {session_type})...")
    if question:
        print(f"Question: {question}")
    engine = CouncilEngine()
    result = engine.run_session(
        session_type=session_type,
        trigger_reason=question or f"CLI {session_type}",
        custom_question=question,
    )
    direction = result.get("consensus", "unknown")
    consensus_type = result.get("consensus_type", "?")
    contested = result.get("is_contested", False)
    print(f"\nDirection: {direction.upper()} ({consensus_type}){' — CONTESTED' if contested else ''}")
    print(f"Score: {result.get('aggregated_score', 0):+.2f} | Confidence: {result.get('confidence_avg', 0):.0%}")
    print(f"Rounds: {result.get('rounds_completed', 0)} | Cost: ${result.get('total_cost', 0):.4f}")
    for assessment in result.get("agent_assessments", []):
        direction = assessment.get("direction", "?")
        confidence = assessment.get("confidence", 0)
        marker = {"bullish": "[BUY]", "neutral": "[---]", "bearish": "[SELL]"}.get(direction, "[---]")
        _safe_print(f"  {marker} {assessment.get('agent', '?')}: {direction} ({confidence:.0%}) -- {assessment.get('key_reasoning', '')[:80]}")

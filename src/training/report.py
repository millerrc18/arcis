"""Training progress report generator.

Called by: scheduler.watch, services.training_service
Calls: training.trainer, training.versioning
Owns tables: none
Config keys: none
Tests: tests/test_leakage_detector.py
"""

from src.training.trainer import should_train, check_model_performance
from src.training.versioning import (
    get_active_model_version,
    get_model_history,
    get_performance_by_version,
    get_training_example_counts,
)


def generate_training_report(db_path: str = "ai_research_desk.sqlite3") -> str:
    """Build a comprehensive plain-text training progress report."""
    lines = []
    lines.append("[TRADE DESK] Training Progress Report")
    lines.append("")

    # MODEL STATUS
    active = get_active_model_version(db_path)
    counts = get_training_example_counts(db_path)
    trigger, trigger_reason = should_train(db_path)

    lines.append("MODEL STATUS")
    if active:
        trained_date = active["created_at"][:10]
        lines.append(f"  Active model:     {active['version_name']} (trained {trained_date})")
    else:
        lines.append("  Active model:     base (no fine-tuned model)")

    total = counts["total"]
    new_since = 0
    if active:
        from src.training.versioning import get_new_examples_since
        new_since = get_new_examples_since(active["created_at"], db_path)

    lines.append(f"  Training examples: {total} total (+{new_since} since last train)")

    if trigger:
        lines.append(f"  Next training:     Queued ({trigger_reason})")
    else:
        lines.append(f"  Next training:     {trigger_reason}")

    # Auto-rollback status
    perf_check = check_model_performance(db_path)
    if perf_check["action"] == "waiting":
        lines.append(f"  Auto-rollback:     Watching (need {perf_check.get('trades_needed', '?')} more trades)")
    elif perf_check["action"] == "rolled_back":
        lines.append(f"  Auto-rollback:     Triggered — {perf_check.get('reason', '')}")
    else:
        lines.append(f"  Auto-rollback:     Passing — {perf_check.get('status', 'ok')}")
    lines.append("")

    # PERFORMANCE BY MODEL VERSION
    lines.append("PERFORMANCE BY MODEL VERSION")
    lines.append(f"  {'Version':<14s} {'Trained':<12s} {'Examples':>8s}  {'Trades':>6s}  {'Win Rate':>8s}  {'Expectancy':>10s}")
    lines.append("  " + "-" * 64)

    history = get_model_history(db_path)
    perf_data = get_performance_by_version(db_path)
    perf_map = {p["version_name"]: p for p in perf_data}

    for v in history:
        name = v["version_name"]
        trained = v["created_at"][:10]
        examples = v.get("training_examples_count") or 0
        p = perf_map.get(name, {})
        trades = p.get("trade_count", 0)
        wr = f"{p['win_rate']:.1f}%" if trades > 0 else "n/a"
        exp = f"${p['expectancy']:+.2f}" if trades > 0 and p.get("expectancy") is not None else "n/a"
        lines.append(f"  {name:<14s} {trained:<12s} {examples:>8d}  {trades:>6d}  {wr:>8s}  {exp:>10s}")

    # Add base model row
    base_perf = perf_map.get("base", {})
    base_trades = base_perf.get("trade_count", 0)
    base_wr = f"{base_perf['win_rate']:.1f}%" if base_trades > 0 else "n/a"
    base_exp = f"${base_perf['expectancy']:+.2f}" if base_trades > 0 and base_perf.get("expectancy") is not None else "n/a"
    lines.append(f"  {'base':<14s} {'--':<12s} {'--':>8s}  {base_trades:>6d}  {base_wr:>8s}  {base_exp:>10s}")
    lines.append("")

    # TRAINING DATA BREAKDOWN
    lines.append("TRAINING DATA BREAKDOWN")
    lines.append(f"  {'Source':<24s} {'Count':>6s}  {'% of total':>10s}")
    lines.append("  " + "-" * 42)

    for source, label in [("historical_backfill", "Historical backfill"),
                          ("synthetic_claude", "Synthetic (Claude)"),
                          ("outcome_win", "Closed trades (wins)"),
                          ("outcome_loss", "Closed trades (losses)")]:
        c = counts.get(source, 0)
        pct = f"{c / total * 100:.1f}%" if total > 0 else "0.0%"
        lines.append(f"  {label:<24s} {c:>6d}  {pct:>10s}")
    lines.append("")

    # NEXT STEPS
    lines.append("NEXT STEPS")
    if total == 0:
        lines.append("  Run 'bootstrap-training' to generate initial dataset")
    elif trigger:
        lines.append(f"  {trigger_reason} — training is queued")
    elif not active:
        lines.append(f"  {total} examples collected. Run 'train --force' when ready.")
    else:
        lines.append(f"  Collecting data. {trigger_reason}")
    lines.append("")

    lines.append("---")
    lines.append("Arcis Training Pipeline")

    return "\n".join(lines)

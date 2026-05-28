"""CLI command implementations for Arcis — re-export facade.

Phase 5 PR-C T13 split this module by command domain into three siblings:
commands_data.py (data/ingestion/shadow-trading), commands_training.py
(training/evaluation/council/review), and commands_ops.py (system/config/
startup/notifications/digest). This module re-exports the SAME function
objects from those siblings so existing `from src.cli.commands import cmd_X`
imports and the src/main.py argparse dispatch keep working unchanged.

Called by: main
Calls: cli.commands_data, cli.commands_ops, cli.commands_training
Owns tables: none
Config keys: enabled, live_trading, shadow_trading, starting_capital
Tests: tests/cli/test_cli_split_integrity.py, tests/cli/test_commands_imports.py
"""

from src.cli.commands_data import (
    cmd_cancel_all_pending,
    cmd_collect_data,
    cmd_eod_recap,
    cmd_fetch_earnings,
    cmd_halt_trading,
    cmd_ingest,
    cmd_live_close,
    cmd_live_history,
    cmd_live_status,
    cmd_morning_watchlist,
    cmd_reconcile_live,
    cmd_resume_trading,
    cmd_scan,
    cmd_shadow_account,
    cmd_shadow_close,
    cmd_shadow_history,
    cmd_shadow_status,
)
from src.cli.commands_training import (
    cmd_backfill_training,
    cmd_backtest,
    cmd_bootstrap_training,
    cmd_check_leakage,
    cmd_classify_training,
    cmd_compare_models,
    cmd_council,
    cmd_cto_report,
    cmd_evaluate_gate,
    cmd_evaluate_holdout,
    cmd_feature_importance,
    cmd_generate_contrastive,
    cmd_generate_preferences,
    cmd_mark_executed,
    cmd_model_evaluation_status,
    cmd_performance_report,
    cmd_postmortem_detail,
    cmd_postmortems,
    cmd_promote_model,
    cmd_review,
    cmd_review_bootcamp,
    cmd_review_scorecard,
    cmd_run_promotion_gate,
    cmd_score_training,
    cmd_train,
    cmd_train_pipeline,
    cmd_training_history,
    cmd_training_report,
    cmd_training_status,
    cmd_validate_training,
)
from src.cli.commands_ops import (
    _assert_safe_live_governor_combo,
    _build_startup_result,
    _notify_startup_telegram,
    _print_startup_check,
    _safe_print,
    _startup_decision,
    _VALID_DIGEST_TIERS,
    cmd_config_diff,
    cmd_config_fix,
    cmd_dashboard,
    cmd_demo_packet,
    cmd_digest_handover_check,
    cmd_digest_preview,
    cmd_init_db,
    cmd_preflight,
    cmd_send_test_email,
    cmd_send_test_telegram,
    cmd_startup,
    cmd_validate_schema,
    cmd_validate_system,
    cmd_watch,
)

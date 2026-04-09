"""Arcis CLI bootstrap and parser wiring.

Called by: none (entry point)
Calls: cli.commands, config, journal.store, log_config
Owns tables: none
Config keys: file, level, logging
Tests: tests/test_live_trading.py, tests/test_main_refactor.py
"""

import argparse
import warnings

warnings.filterwarnings("ignore", message=".*utcnow.*deprecated.*")
warnings.filterwarnings("ignore", message=".*Timestamp.utcnow.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

# Patch pd.Timestamp.utcnow globally — yfinance calls it from Cython C code
# which bypasses Python's warnings.filterwarnings. Replacing the method with
# the non-deprecated equivalent eliminates the warning at the source.
try:
    import pandas as _pd
    if hasattr(_pd.Timestamp, "utcnow"):
        _pd.Timestamp.utcnow = staticmethod(lambda: _pd.Timestamp.now(tz="UTC"))
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv()  # reads .env before any os.environ lookups

from src.cli.commands import (
    cmd_backfill_training,
    cmd_backtest,
    cmd_bootstrap_training,
    cmd_check_leakage,
    cmd_classify_training,
    cmd_collect_data,
    cmd_compare_models,
    cmd_council,
    cmd_cto_report,
    cmd_dashboard,
    cmd_demo_packet,
    cmd_eod_recap,
    cmd_evaluate_gate,
    cmd_evaluate_holdout,
    cmd_feature_importance,
    cmd_fetch_earnings,
    cmd_generate_contrastive,
    cmd_generate_preferences,
    cmd_cancel_all_pending,
    cmd_halt_trading,
    cmd_ingest,
    cmd_init_db,
    cmd_live_close,
    cmd_live_history,
    cmd_live_status,
    cmd_mark_executed,
    cmd_model_evaluation_status,
    cmd_morning_watchlist,
    cmd_performance_report,
    cmd_postmortem_detail,
    cmd_postmortems,
    cmd_preflight,
    cmd_config_fix,
    cmd_config_diff,
    cmd_promote_model,
    cmd_reconcile_live,
    cmd_resume_trading,
    cmd_review,
    cmd_review_bootcamp,
    cmd_review_scorecard,
    cmd_scan,
    cmd_score_training,
    cmd_send_test_email,
    cmd_send_test_telegram,
    cmd_shadow_account,
    cmd_shadow_close,
    cmd_shadow_history,
    cmd_shadow_status,
    cmd_train,
    cmd_train_pipeline,
    cmd_training_history,
    cmd_training_report,
    cmd_training_status,
    cmd_startup,
    cmd_validate_schema,
    cmd_validate_system,
    cmd_validate_training,
    cmd_watch,
)
from src.config import DB_PATH
from src.journal.store import initialize_database


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level Arcis CLI parser."""
    parser = argparse.ArgumentParser(description="Arcis — Systematic Equity Research")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db")
    init_db.add_argument("--db-path", default=DB_PATH)
    init_db.set_defaults(func=cmd_init_db)

    subparsers.add_parser("demo-packet").set_defaults(func=cmd_demo_packet)
    subparsers.add_parser("send-test-email").set_defaults(func=cmd_send_test_email)
    subparsers.add_parser("send-test-telegram", help="Test Telegram notification delivery").set_defaults(func=cmd_send_test_telegram)
    subparsers.add_parser("ingest").set_defaults(func=cmd_ingest)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--verbose", action="store_true")
    scan.add_argument("--email", action="store_true")
    scan.add_argument("--dry-run", action="store_true")
    scan.add_argument("--no-shadow", action="store_true")
    scan.set_defaults(func=cmd_scan)

    morning_watchlist = subparsers.add_parser("morning-watchlist")
    morning_watchlist.add_argument("--email", action="store_true")
    morning_watchlist.add_argument("--dry-run", action="store_true")
    morning_watchlist.set_defaults(func=cmd_morning_watchlist)

    eod_recap = subparsers.add_parser("eod-recap")
    eod_recap.add_argument("--email", action="store_true")
    eod_recap.add_argument("--dry-run", action="store_true")
    eod_recap.set_defaults(func=cmd_eod_recap)

    subparsers.add_parser("shadow-status").set_defaults(func=cmd_shadow_status)
    shadow_history = subparsers.add_parser("shadow-history")
    shadow_history.add_argument("--days", type=int, default=30)
    shadow_history.set_defaults(func=cmd_shadow_history)
    shadow_close = subparsers.add_parser("shadow-close")
    shadow_close.add_argument("ticker")
    shadow_close.add_argument("--reason", default="manual")
    shadow_close.set_defaults(func=cmd_shadow_close)
    subparsers.add_parser("shadow-account").set_defaults(func=cmd_shadow_account)

    subparsers.add_parser("live-status", help="Show live account balance and open positions").set_defaults(func=cmd_live_status)
    live_history = subparsers.add_parser("live-history", help="Show live trade history")
    live_history.add_argument("--days", type=int, default=30)
    live_history.set_defaults(func=cmd_live_history)
    live_close = subparsers.add_parser("live-close", help="Close a live position")
    live_close.add_argument("ticker")
    live_close.add_argument("--reason", default="manual")
    live_close.set_defaults(func=cmd_live_close)
    reconcile_live = subparsers.add_parser("reconcile-live", help="Reconcile Alpaca live positions with shadow_trades DB")
    reconcile_live.add_argument("--dry-run", action="store_true", help="Report discrepancies without modifying DB")
    reconcile_live.set_defaults(func=cmd_reconcile_live)

    review = subparsers.add_parser("review")
    review.add_argument("review_sub", nargs="?", default="list")
    review.set_defaults(func=cmd_review)
    mark_executed = subparsers.add_parser("mark-executed")
    mark_executed.add_argument("ticker")
    mark_executed.set_defaults(func=cmd_mark_executed)
    review_scorecard = subparsers.add_parser("review-scorecard")
    review_scorecard.add_argument("--weeks", type=int, default=1)
    review_scorecard.add_argument("--email", action="store_true")
    review_scorecard.set_defaults(func=cmd_review_scorecard)
    review_bootcamp = subparsers.add_parser("review-bootcamp")
    review_bootcamp.add_argument("--days", type=int, default=30)
    review_bootcamp.add_argument("--email", action="store_true")
    review_bootcamp.set_defaults(func=cmd_review_bootcamp)
    postmortems = subparsers.add_parser("postmortems")
    postmortems.add_argument("--limit", type=int, default=10)
    postmortems.add_argument("--ticker")
    postmortems.set_defaults(func=cmd_postmortems)
    postmortem = subparsers.add_parser("postmortem")
    postmortem.add_argument("recommendation_id")
    postmortem.set_defaults(func=cmd_postmortem_detail)

    subparsers.add_parser("training-status").set_defaults(func=cmd_training_status)
    subparsers.add_parser("training-history").set_defaults(func=cmd_training_history)
    training_report = subparsers.add_parser("training-report")
    training_report.add_argument("--email", action="store_true")
    training_report.set_defaults(func=cmd_training_report)
    bootstrap_training = subparsers.add_parser("bootstrap-training")
    bootstrap_training.add_argument("--count", type=int, default=500)
    bootstrap_training.add_argument("--yes", action="store_true")
    bootstrap_training.set_defaults(func=cmd_bootstrap_training)
    backfill_training = subparsers.add_parser("backfill-training")
    backfill_training.add_argument("--months", type=int, default=12)
    backfill_training.add_argument("--max-examples", type=int, default=2000)
    backfill_training.add_argument("--min-score", type=float, default=70)
    backfill_training.add_argument("--include-messy", action="store_true")
    backfill_training.add_argument("--yes", action="store_true")
    backfill_training.set_defaults(func=cmd_backfill_training)
    train = subparsers.add_parser("train")
    train.add_argument("--force", action="store_true")
    train.add_argument("--rollback", action="store_true")
    train.add_argument("--export", action="store_true")
    train.add_argument("--register", action="store_true", help="Register current halcyonlatest as halcyon-v1.0.0")
    train.set_defaults(func=cmd_train)
    train_pipeline = subparsers.add_parser("train-pipeline", help="Run complete training pipeline (score → leakage → classify → train)")
    train_pipeline.add_argument("--force", action="store_true", help="Continue even if leakage detected")
    train_pipeline.set_defaults(func=cmd_train_pipeline)

    subparsers.add_parser("classify-training-data").set_defaults(func=cmd_classify_training)
    subparsers.add_parser("score-training-data").set_defaults(func=cmd_score_training)
    subparsers.add_parser("validate-training-data").set_defaults(func=cmd_validate_training)
    generate_contrastive = subparsers.add_parser("generate-contrastive")
    generate_contrastive.add_argument("--max-pairs", type=int, default=50)
    generate_contrastive.set_defaults(func=cmd_generate_contrastive)
    generate_preferences = subparsers.add_parser("generate-preferences")
    generate_preferences.add_argument("--count", type=int, default=100)
    generate_preferences.set_defaults(func=cmd_generate_preferences)

    cto_report = subparsers.add_parser("cto-report")
    cto_report.add_argument("--days", type=int, default=7)
    cto_report.add_argument("--json", action="store_true")
    cto_report.add_argument("--email", action="store_true")
    cto_report.set_defaults(func=cmd_cto_report)
    evaluate_holdout = subparsers.add_parser("evaluate-holdout")
    evaluate_holdout.add_argument("--model", default="halcyon-latest")
    evaluate_holdout.set_defaults(func=cmd_evaluate_holdout)
    subparsers.add_parser("model-evaluation-status").set_defaults(func=cmd_model_evaluation_status)
    promote_model = subparsers.add_parser("promote-model")
    promote_model.add_argument("--force", action="store_true")
    promote_model.set_defaults(func=cmd_promote_model)
    feature_importance = subparsers.add_parser("feature-importance")
    feature_importance.add_argument("--days", type=int, default=30)
    feature_importance.set_defaults(func=cmd_feature_importance)
    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--model", default="halcyon-latest")
    backtest.add_argument("--months", type=int, default=6)
    backtest.set_defaults(func=cmd_backtest)
    compare_models = subparsers.add_parser("compare-models")
    compare_models.add_argument("--model-a", required=True)
    compare_models.add_argument("--model-b", required=True)
    compare_models.add_argument("--months", type=int, default=3)
    compare_models.set_defaults(func=cmd_compare_models)
    subparsers.add_parser("check-leakage").set_defaults(func=cmd_check_leakage)
    subparsers.add_parser("evaluate-gate", help="Run 50-trade gate evaluation (Phase 1 → Phase 2)").set_defaults(func=cmd_evaluate_gate)
    performance_report = subparsers.add_parser("performance-report", help="Generate performance report")
    performance_report.add_argument("--days", type=int, default=30)
    performance_report.set_defaults(func=cmd_performance_report)

    subparsers.add_parser("collect-data", help="Run market data collection pipeline").set_defaults(func=cmd_collect_data)
    subparsers.add_parser("fetch-earnings", help="Fetch upcoming earnings dates for S&P 100").set_defaults(func=cmd_fetch_earnings)
    subparsers.add_parser("halt-trading").set_defaults(func=cmd_halt_trading)
    subparsers.add_parser("resume-trading").set_defaults(func=cmd_resume_trading)
    subparsers.add_parser("cancel-all-pending", help="Cancel all pending Alpaca orders").set_defaults(func=cmd_cancel_all_pending)
    subparsers.add_parser("preflight").set_defaults(func=cmd_preflight)
    subparsers.add_parser("config-fix", help="Merge missing keys from example into local config").set_defaults(func=cmd_config_fix)
    subparsers.add_parser("config-diff", help="Show keys missing from local config").set_defaults(func=cmd_config_diff)
    council = subparsers.add_parser("council", help="Run an AI Council session")
    council.add_argument("--type", default="daily", choices=["daily", "weekly", "monthly", "strategic"])
    council.add_argument("--question", "-q", type=str, default=None, help="Strategic question for the council (auto-sets type to strategic)")
    council.set_defaults(func=cmd_council)
    watch = subparsers.add_parser("watch")
    watch.add_argument("--email-mode", choices=["full_stream", "daily_summary", "digest", "silent"])
    watch.add_argument("--overnight", action="store_true", help="Enable overnight schedule (post-close, news, enrichment, pre-market)")
    watch.set_defaults(func=cmd_watch)

    startup = subparsers.add_parser("startup", help="Validate system and launch watch loop")
    startup.add_argument("--email-mode", default="digest",
                         choices=["full_stream", "daily_summary", "digest", "silent"])
    startup.add_argument("--no-overnight", action="store_true",
                         help="Disable overnight schedule (data collection, news, enrichment)")
    startup.add_argument("--force", action="store_true",
                         help="Launch despite critical failures")
    startup.add_argument("--check-only", action="store_true",
                         help="Run validation only, don't launch watch loop")
    startup.set_defaults(func=cmd_startup)

    dashboard = subparsers.add_parser("dashboard")
    dashboard.add_argument("--port", type=int, default=8000)
    dashboard.set_defaults(func=cmd_dashboard)

    validate_system = subparsers.add_parser("validate-system", help="Run system validation checks across all subsystems")
    validate_system.add_argument("--json", action="store_true", help="Output structured JSON")
    validate_system.add_argument("--fix", action="store_true", help="Attempt auto-fixes for common issues")
    validate_system.set_defaults(func=cmd_validate_system)

    validate_schema = subparsers.add_parser(
        "validate-schema", help="Validate database schema against registry"
    )
    validate_schema.add_argument(
        "--fix", action="store_true", help="Auto-fix missing tables/columns"
    )
    validate_schema.add_argument(
        "--postgres", action="store_true", help="Also validate Render Postgres"
    )
    validate_schema.set_defaults(func=cmd_validate_schema)

    return parser


def main():
    """Initialize logging, DB state, and dispatch the parsed CLI command."""
    from src.config import load_config
    from src.log_config import setup_logging

    config = load_config()
    logging_config = config.get("logging", {})
    setup_logging(
        level=logging_config.get("level", "INFO"),
        log_file=logging_config.get("file", "logs/arcis.log"),
    )
    initialize_database()
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

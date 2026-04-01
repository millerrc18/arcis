"""Migrate Render Postgres schema to match local SQLite.

Usage:
    $env:DATABASE_URL = "your-external-database-url"
    python scripts/render_migrate.py
"""

import os
import sys

try:
    import psycopg2
except ImportError:
    print("Run: pip install psycopg2-binary")
    sys.exit(1)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: Set DATABASE_URL environment variable first.")
    print("  PowerShell: $env:DATABASE_URL = \"your-external-url\"")
    sys.exit(1)

MIGRATIONS = [
    # shadow_trades — new columns from live trading + setup classifier
    ("shadow_trades", "source", "ALTER TABLE shadow_trades ADD COLUMN source TEXT"),
    ("shadow_trades", "setup_type", "ALTER TABLE shadow_trades ADD COLUMN setup_type TEXT"),
    ("shadow_trades", "setup_confidence", "ALTER TABLE shadow_trades ADD COLUMN setup_confidence REAL"),

    # recommendations — new columns added via ALTER TABLE in store.py
    ("recommendations", "enriched_prompt", "ALTER TABLE recommendations ADD COLUMN enriched_prompt TEXT"),
    ("recommendations", "setup_type", "ALTER TABLE recommendations ADD COLUMN setup_type TEXT"),
    ("recommendations", "setup_confidence", "ALTER TABLE recommendations ADD COLUMN setup_confidence REAL"),
    ("recommendations", "llm_conviction", "ALTER TABLE recommendations ADD COLUMN llm_conviction INTEGER"),
    ("recommendations", "llm_conviction_reason", "ALTER TABLE recommendations ADD COLUMN llm_conviction_reason TEXT"),
    ("recommendations", "model_version", "ALTER TABLE recommendations ADD COLUMN model_version TEXT"),
    ("recommendations", "market_regime", "ALTER TABLE recommendations ADD COLUMN market_regime TEXT"),

    # shadow_trades — new columns added via ALTER TABLE in store.py
    ("shadow_trades", "order_type", "ALTER TABLE shadow_trades ADD COLUMN order_type TEXT"),

    # Slippage tracking columns
    ("shadow_trades", "signal_entry_price", "ALTER TABLE shadow_trades ADD COLUMN signal_entry_price REAL"),
    ("shadow_trades", "fill_entry_price", "ALTER TABLE shadow_trades ADD COLUMN fill_entry_price REAL"),
    ("shadow_trades", "entry_slippage_bps", "ALTER TABLE shadow_trades ADD COLUMN entry_slippage_bps REAL"),
    ("shadow_trades", "signal_exit_price", "ALTER TABLE shadow_trades ADD COLUMN signal_exit_price REAL"),
    ("shadow_trades", "fill_exit_price", "ALTER TABLE shadow_trades ADD COLUMN fill_exit_price REAL"),
    ("shadow_trades", "exit_slippage_bps", "ALTER TABLE shadow_trades ADD COLUMN exit_slippage_bps REAL"),

    # Columns added by executor.py and Sprint 4E migration (missing from original Postgres schema)
    ("shadow_trades", "signal_price", "ALTER TABLE shadow_trades ADD COLUMN signal_price REAL"),
    ("shadow_trades", "fill_price", "ALTER TABLE shadow_trades ADD COLUMN fill_price REAL"),
    ("shadow_trades", "implementation_shortfall_bps", "ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL"),
    ("shadow_trades", "strategy_type", "ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback'"),

    # NLP columns on edgar_filings
    ("edgar_filings", "sentiment_polarity", "ALTER TABLE edgar_filings ADD COLUMN sentiment_polarity REAL"),
    ("edgar_filings", "sentiment_negative_count", "ALTER TABLE edgar_filings ADD COLUMN sentiment_negative_count INTEGER"),
    ("edgar_filings", "sentiment_uncertainty_count", "ALTER TABLE edgar_filings ADD COLUMN sentiment_uncertainty_count INTEGER"),
    ("edgar_filings", "cautionary_phrases", "ALTER TABLE edgar_filings ADD COLUMN cautionary_phrases TEXT"),
    ("edgar_filings", "sentiment_delta_polarity", "ALTER TABLE edgar_filings ADD COLUMN sentiment_delta_polarity REAL"),

    # Fix column mismatches: SQLite uses different PKs than Postgres init created
    # api_costs: SQLite has cost_id as PK, Postgres has id SERIAL
    ("api_costs", "cost_id", "ALTER TABLE api_costs ADD COLUMN cost_id TEXT"),
    ("api_costs", "cost_dollars", "ALTER TABLE api_costs ADD COLUMN cost_dollars REAL"),
    # UNIQUE index for ON CONFLICT upsert
    ("api_costs", "_idx_cost_id", "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_costs_cost_id ON api_costs(cost_id)"),

    # training_examples: SQLite has many columns not in Postgres init
    ("training_examples", "recommendation_id", "ALTER TABLE training_examples ADD COLUMN recommendation_id TEXT"),
    ("training_examples", "feature_snapshot", "ALTER TABLE training_examples ADD COLUMN feature_snapshot TEXT"),
    ("training_examples", "regime_label", "ALTER TABLE training_examples ADD COLUMN regime_label TEXT"),
    ("training_examples", "trade_outcome", "ALTER TABLE training_examples ADD COLUMN trade_outcome TEXT"),
    ("training_examples", "instruction", "ALTER TABLE training_examples ADD COLUMN instruction TEXT"),
    ("training_examples", "difficulty", "ALTER TABLE training_examples ADD COLUMN difficulty TEXT"),
    ("training_examples", "quality_score_auto", "ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL"),

    # Columns added by Sprint 4E migration
    ("training_examples", "outcome_type", "ALTER TABLE training_examples ADD COLUMN outcome_type TEXT"),
    ("training_examples", "regime", "ALTER TABLE training_examples ADD COLUMN regime TEXT"),

    # Activity log level column (added by Sprint 4E migration)
    ("activity_log", "level", "ALTER TABLE activity_log ADD COLUMN level TEXT DEFAULT 'INFO'"),

    # setup_signals: SQLite has rich signal data, Postgres was created minimal
    ("setup_signals", "signal_id", "ALTER TABLE setup_signals ADD COLUMN signal_id TEXT"),
    ("setup_signals", "date", "ALTER TABLE setup_signals ADD COLUMN date TEXT"),
    ("setup_signals", "theoretical_entry", "ALTER TABLE setup_signals ADD COLUMN theoretical_entry REAL"),
    ("setup_signals", "theoretical_stop", "ALTER TABLE setup_signals ADD COLUMN theoretical_stop REAL"),
    ("setup_signals", "theoretical_target", "ALTER TABLE setup_signals ADD COLUMN theoretical_target REAL"),
    ("setup_signals", "regime", "ALTER TABLE setup_signals ADD COLUMN regime TEXT"),
    ("setup_signals", "adx", "ALTER TABLE setup_signals ADD COLUMN adx REAL"),
    ("setup_signals", "atr_ratio", "ALTER TABLE setup_signals ADD COLUMN atr_ratio REAL"),
    ("setup_signals", "rsi", "ALTER TABLE setup_signals ADD COLUMN rsi REAL"),
    ("setup_signals", "volume_profile", "ALTER TABLE setup_signals ADD COLUMN volume_profile TEXT"),
    ("setup_signals", "actual_return_1d", "ALTER TABLE setup_signals ADD COLUMN actual_return_1d REAL"),
    ("setup_signals", "actual_return_5d", "ALTER TABLE setup_signals ADD COLUMN actual_return_5d REAL"),
    ("setup_signals", "actual_return_10d", "ALTER TABLE setup_signals ADD COLUMN actual_return_10d REAL"),
    ("setup_signals", "actual_return_20d", "ALTER TABLE setup_signals ADD COLUMN actual_return_20d REAL"),
    ("setup_signals", "was_traded", "ALTER TABLE setup_signals ADD COLUMN was_traded INTEGER"),
    # UNIQUE index for ON CONFLICT upsert
    ("setup_signals", "_idx_signal_id", "CREATE UNIQUE INDEX IF NOT EXISTS idx_setup_signals_signal_id ON setup_signals(signal_id)"),

    # New tables
    ("schedule_metrics", None, """CREATE TABLE IF NOT EXISTS schedule_metrics (
        id SERIAL PRIMARY KEY,
        metric_date TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL,
        details TEXT
    )"""),
    ("schedule_metrics", "metric_name", "ALTER TABLE schedule_metrics ADD COLUMN metric_name TEXT"),
    ("schedule_metrics", "metric_value", "ALTER TABLE schedule_metrics ADD COLUMN metric_value REAL"),
    ("schedule_metrics", "details", "ALTER TABLE schedule_metrics ADD COLUMN details TEXT"),
    ("schedule_metrics", "_idx_metric_date_name", "CREATE INDEX IF NOT EXISTS idx_schedule_metrics_date ON schedule_metrics(metric_date, metric_name)"),

    ("council_sessions", None, """CREATE TABLE IF NOT EXISTS council_sessions (
        session_id TEXT PRIMARY KEY,
        session_type TEXT NOT NULL DEFAULT 'daily',
        trigger_reason TEXT,
        created_at TEXT NOT NULL,
        consensus TEXT,
        confidence_weighted_score REAL,
        is_contested INTEGER DEFAULT 0,
        total_cost REAL,
        rounds_completed INTEGER DEFAULT 0,
        result_json TEXT
    )"""),
    ("council_sessions", "session_type", "ALTER TABLE council_sessions ADD COLUMN session_type TEXT"),
    ("council_sessions", "trigger_reason", "ALTER TABLE council_sessions ADD COLUMN trigger_reason TEXT"),
    ("council_sessions", "confidence_weighted_score", "ALTER TABLE council_sessions ADD COLUMN confidence_weighted_score REAL"),
    ("council_sessions", "is_contested", "ALTER TABLE council_sessions ADD COLUMN is_contested INTEGER DEFAULT 0"),
    ("council_sessions", "total_cost", "ALTER TABLE council_sessions ADD COLUMN total_cost REAL"),
    ("council_sessions", "rounds_completed", "ALTER TABLE council_sessions ADD COLUMN rounds_completed INTEGER DEFAULT 0"),
    ("council_sessions", "result_json", "ALTER TABLE council_sessions ADD COLUMN result_json TEXT"),

    ("council_votes", None, """CREATE TABLE IF NOT EXISTS council_votes (
        vote_id TEXT PRIMARY KEY,
        session_id TEXT,
        round INTEGER,
        agent_name TEXT,
        position TEXT,
        confidence REAL,
        recommendation TEXT,
        key_data_points TEXT,
        risk_flags TEXT,
        vote TEXT,
        is_devils_advocate INTEGER DEFAULT 0,
        direction TEXT,
        confidence_float REAL,
        assessment_json TEXT
    )"""),
    ("council_votes", "vote_id", "ALTER TABLE council_votes ADD COLUMN vote_id TEXT"),
    ("council_votes", "direction", "ALTER TABLE council_votes ADD COLUMN direction TEXT"),
    ("council_votes", "confidence_float", "ALTER TABLE council_votes ADD COLUMN confidence_float REAL"),
    ("council_votes", "assessment_json", "ALTER TABLE council_votes ADD COLUMN assessment_json TEXT"),
    ("council_votes", "_idx_vote_id", "CREATE UNIQUE INDEX IF NOT EXISTS idx_council_votes_vote_id ON council_votes(vote_id)"),

    ("validation_results", None, """CREATE TABLE IF NOT EXISTS validation_results (
        result_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        overall_status TEXT NOT NULL,
        checks_passed INTEGER NOT NULL,
        checks_failed INTEGER NOT NULL,
        checks_warning INTEGER NOT NULL,
        results_json TEXT NOT NULL
    )"""),

    ("traffic_light_state", None, """CREATE TABLE IF NOT EXISTS traffic_light_state (
        id INTEGER PRIMARY KEY,
        current_regime TEXT NOT NULL DEFAULT 'GREEN',
        pending_regime TEXT,
        pending_count INTEGER DEFAULT 0,
        last_vix_score INTEGER DEFAULT 0,
        last_trend_score INTEGER DEFAULT 0,
        last_credit_score INTEGER DEFAULT 0,
        last_total_score INTEGER DEFAULT 0,
        updated_at TEXT,
        last_transition_at TEXT
    )"""),
    ("traffic_light_state", "last_transition_at",
     "ALTER TABLE traffic_light_state ADD COLUMN last_transition_at TEXT"),

    ("council_calibrations", None, """CREATE TABLE IF NOT EXISTS council_calibrations (
        calibration_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        agent_name TEXT,
        prediction TEXT NOT NULL,
        prediction_confidence REAL NOT NULL,
        verification_date TEXT NOT NULL,
        actual_outcome TEXT,
        correct INTEGER,
        created_at TEXT NOT NULL
    )"""),

    ("council_debug_log", None, """CREATE TABLE IF NOT EXISTS council_debug_log (
        debug_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        round INTEGER NOT NULL,
        system_prompt_hash TEXT,
        user_message TEXT,
        raw_response TEXT,
        parsed_successfully INTEGER DEFAULT 0,
        parse_error TEXT,
        latency_ms INTEGER,
        created_at TEXT NOT NULL
    )"""),

    ("council_parameter_log", None, """CREATE TABLE IF NOT EXISTS council_parameter_log (
        log_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        agent_name TEXT,
        parameter_name TEXT NOT NULL,
        default_value REAL NOT NULL,
        council_value REAL NOT NULL,
        applied_value REAL NOT NULL,
        rate_limited INTEGER DEFAULT 0,
        attribution_start TEXT NOT NULL,
        attribution_end TEXT,
        trades_during_window INTEGER DEFAULT 0,
        pnl_during_window REAL,
        counterfactual_pnl REAL,
        value_added_dollars REAL,
        created_at TEXT NOT NULL
    )"""),

    ("council_parameter_state", None, """CREATE TABLE IF NOT EXISTS council_parameter_state (
        parameter_name TEXT PRIMARY KEY,
        current_value REAL NOT NULL,
        default_value REAL NOT NULL,
        last_session_id TEXT,
        last_updated TEXT NOT NULL
    )"""),

    ("user_notes", None, """CREATE TABLE IF NOT EXISTS user_notes (
        note_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT DEFAULT '',
        tags TEXT DEFAULT '[]',
        pinned INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )"""),

    ("setup_signals", None, """CREATE TABLE IF NOT EXISTS setup_signals (
        id SERIAL PRIMARY KEY,
        ticker TEXT,
        scan_date TEXT,
        setup_type TEXT,
        confidence REAL,
        features_json TEXT,
        created_at TEXT
    )"""),

    ("canary_evaluations", None, """CREATE TABLE IF NOT EXISTS canary_evaluations (
        id SERIAL PRIMARY KEY,
        model_version TEXT,
        perplexity REAL,
        distinct_2 REAL,
        verdict TEXT,
        details TEXT,
        created_at TEXT
    )"""),

    ("quality_drift_metrics", None, """CREATE TABLE IF NOT EXISTS quality_drift_metrics (
        id SERIAL PRIMARY KEY,
        metric_date TEXT,
        avg_score REAL,
        score_std REAL,
        pass_rate REAL,
        template_fallback_rate REAL,
        created_at TEXT
    )"""),

    ("activity_log", None, """CREATE TABLE IF NOT EXISTS activity_log (
        id SERIAL PRIMARY KEY,
        event_type TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    )"""),

    ("sync_state", None, """CREATE TABLE IF NOT EXISTS sync_state (
        table_name TEXT PRIMARY KEY,
        last_synced_at TEXT
    )"""),

    # New data collection tables (Sprint: Free Data Collectors)
    ("edgar_filings", None, """CREATE TABLE IF NOT EXISTS edgar_filings (
        id SERIAL PRIMARY KEY,
        ticker TEXT NOT NULL,
        cik TEXT NOT NULL,
        form_type TEXT NOT NULL,
        filing_date TEXT NOT NULL,
        accession_number TEXT UNIQUE NOT NULL,
        filing_url TEXT,
        description TEXT,
        full_text TEXT,
        sections_json TEXT,
        word_count INTEGER,
        collected_at TEXT NOT NULL
    )"""),

    ("insider_transactions", None, """CREATE TABLE IF NOT EXISTS insider_transactions (
        id SERIAL PRIMARY KEY,
        ticker TEXT NOT NULL,
        insider_name TEXT,
        title TEXT,
        transaction_type TEXT,
        transaction_date TEXT,
        filing_date TEXT,
        shares REAL,
        price REAL,
        value REAL,
        shares_after REAL,
        source TEXT DEFAULT 'finnhub',
        collected_at TEXT NOT NULL
    )"""),

    ("short_interest", None, """CREATE TABLE IF NOT EXISTS short_interest (
        id SERIAL PRIMARY KEY,
        ticker TEXT NOT NULL,
        settlement_date TEXT NOT NULL,
        short_interest REAL,
        avg_daily_volume REAL,
        days_to_cover REAL,
        short_pct_float REAL,
        source TEXT DEFAULT 'finnhub',
        collected_at TEXT NOT NULL,
        UNIQUE(ticker, settlement_date)
    )"""),

    ("fed_communications", None, """CREATE TABLE IF NOT EXISTS fed_communications (
        id SERIAL PRIMARY KEY,
        comm_type TEXT NOT NULL,
        title TEXT,
        date TEXT NOT NULL,
        speaker TEXT,
        url TEXT,
        full_text TEXT,
        word_count INTEGER,
        collected_at TEXT NOT NULL,
        UNIQUE(comm_type, date, title)
    )"""),

    ("api_costs", None, """CREATE TABLE IF NOT EXISTS api_costs (
        id SERIAL PRIMARY KEY,
        model TEXT,
        purpose TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        estimated_cost REAL,
        created_at TEXT
    )"""),

    ("training_examples", None, """CREATE TABLE IF NOT EXISTS training_examples (
        id SERIAL PRIMARY KEY,
        example_id TEXT UNIQUE,
        ticker TEXT,
        trade_date TEXT,
        input_text TEXT,
        output_text TEXT,
        quality_score REAL,
        curriculum_stage TEXT,
        outcome TEXT,
        source TEXT,
        model_version TEXT,
        created_at TEXT
    )"""),

    ("analyst_estimates", None, """CREATE TABLE IF NOT EXISTS analyst_estimates (
        id SERIAL PRIMARY KEY,
        ticker TEXT NOT NULL,
        date TEXT NOT NULL,
        consensus_buy INTEGER,
        consensus_hold INTEGER,
        consensus_sell INTEGER,
        consensus_strong_buy INTEGER,
        consensus_strong_sell INTEGER,
        price_target_high REAL,
        price_target_low REAL,
        price_target_mean REAL,
        price_target_median REAL,
        num_analysts INTEGER,
        source TEXT DEFAULT 'finnhub',
        collected_at TEXT NOT NULL,
        UNIQUE(ticker, date, source)
    )"""),

    # Options / sentiment data tables (synced as latest_only snapshots)
    ("options_chains", None, """CREATE TABLE IF NOT EXISTS options_chains (
        id SERIAL PRIMARY KEY,
        collected_at TEXT NOT NULL,
        ticker TEXT NOT NULL,
        expiration TEXT NOT NULL,
        strike REAL NOT NULL,
        option_type TEXT NOT NULL,
        bid REAL,
        ask REAL,
        last_price REAL,
        volume INTEGER,
        open_interest INTEGER,
        implied_volatility REAL,
        delta REAL,
        gamma REAL,
        theta REAL,
        vega REAL,
        in_the_money INTEGER,
        underlying_price REAL
    )"""),
    ("options_chains", "_idx_ticker_date", "CREATE INDEX IF NOT EXISTS idx_options_chains_ticker_date ON options_chains(ticker, collected_at)"),
    ("options_chains", "_idx_collected", "CREATE INDEX IF NOT EXISTS idx_options_chains_collected ON options_chains(collected_at)"),

    ("cboe_ratios", None, """CREATE TABLE IF NOT EXISTS cboe_ratios (
        id SERIAL PRIMARY KEY,
        collected_at TEXT NOT NULL,
        collected_date TEXT NOT NULL,
        equity_pc_ratio REAL,
        index_pc_ratio REAL,
        total_pc_ratio REAL,
        equity_pc_vs_20d_avg REAL
    )"""),
    ("cboe_ratios", "_idx_date", "CREATE INDEX IF NOT EXISTS idx_cboe_ratios_date ON cboe_ratios(collected_date)"),

    ("google_trends", None, """CREATE TABLE IF NOT EXISTS google_trends (
        id SERIAL PRIMARY KEY,
        collected_at TEXT NOT NULL,
        collected_date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        search_interest REAL,
        interest_vs_90d_avg REAL,
        spike_flag INTEGER
    )"""),
    ("google_trends", "_idx_ticker_date", "CREATE INDEX IF NOT EXISTS idx_google_trends_ticker_date ON google_trends(ticker, collected_date)"),

    # Research intelligence tables
    ("research_papers", None, """CREATE TABLE IF NOT EXISTS research_papers (
        id SERIAL PRIMARY KEY,
        source TEXT NOT NULL,
        external_id TEXT UNIQUE,
        title TEXT NOT NULL,
        authors TEXT,
        abstract TEXT,
        url TEXT NOT NULL,
        published_date TEXT,
        categories TEXT,
        relevance_score REAL,
        relevance_reason TEXT,
        full_text TEXT,
        actionable INTEGER DEFAULT 0,
        action_taken TEXT,
        collected_at TEXT NOT NULL
    )"""),

    ("research_digests", None, """CREATE TABLE IF NOT EXISTS research_digests (
        id SERIAL PRIMARY KEY,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        papers_reviewed INTEGER,
        actionable_count INTEGER,
        digest_text TEXT,
        threats TEXT,
        opportunities TEXT,
        created_at TEXT NOT NULL
    )"""),

    # ── Tables that exist locally but were missing from Postgres migration ──

    ("build_score_history", None, """CREATE TABLE IF NOT EXISTS build_score_history (
        score_id TEXT PRIMARY KEY,
        score_date TEXT,
        build_score REAL,
        gate_velocity REAL,
        system_health REAL,
        data_asset_value REAL,
        model_quality REAL,
        research_velocity REAL,
        reliability REAL,
        decay_applied INTEGER DEFAULT 0,
        components_json TEXT,
        created_at TEXT
    )"""),
    ("build_score_history", "_idx_score_date", "CREATE INDEX IF NOT EXISTS idx_build_score_date ON build_score_history(score_date)"),

    ("audit_reports", None, """CREATE TABLE IF NOT EXISTS audit_reports (
        audit_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        audit_date TEXT NOT NULL,
        overall_assessment TEXT NOT NULL,
        summary TEXT,
        flags TEXT,
        metrics_to_watch TEXT,
        model_health TEXT,
        full_report TEXT
    )"""),

    ("metric_snapshots", None, """CREATE TABLE IF NOT EXISTS metric_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        metrics_json TEXT NOT NULL
    )"""),
    ("metric_snapshots", "_idx_snapshot_date", "CREATE INDEX IF NOT EXISTS idx_metric_snapshots_date ON metric_snapshots(snapshot_date)"),

    ("earnings_calendar", None, """CREATE TABLE IF NOT EXISTS earnings_calendar (
        id SERIAL PRIMARY KEY,
        ticker TEXT NOT NULL,
        earnings_date TEXT NOT NULL,
        earnings_time TEXT,
        confirmed INTEGER DEFAULT 0,
        collected_at TEXT NOT NULL
    )"""),
    ("earnings_calendar", "_idx_ticker", "CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_calendar(ticker)"),
    ("earnings_calendar", "_idx_date", "CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings_calendar(earnings_date)"),

    ("macro_snapshots", None, """CREATE TABLE IF NOT EXISTS macro_snapshots (
        id SERIAL PRIMARY KEY,
        collected_at TEXT NOT NULL,
        collected_date TEXT NOT NULL,
        series_id TEXT NOT NULL,
        series_name TEXT NOT NULL,
        value REAL,
        previous_value REAL,
        change_pct REAL
    )"""),
    ("macro_snapshots", "_idx_date", "CREATE INDEX IF NOT EXISTS idx_macro_snapshots_date ON macro_snapshots(collected_date)"),
    ("macro_snapshots", "_idx_series", "CREATE INDEX IF NOT EXISTS idx_macro_snapshots_series ON macro_snapshots(series_id, collected_date)"),

    ("options_metrics", None, """CREATE TABLE IF NOT EXISTS options_metrics (
        id SERIAL PRIMARY KEY,
        collected_at TEXT NOT NULL,
        collected_date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        iv_rank REAL,
        iv_percentile REAL,
        put_call_volume_ratio REAL,
        put_call_oi_ratio REAL,
        atm_iv_30d REAL,
        iv_skew REAL,
        unusual_volume_flag INTEGER,
        max_unusual_volume_ratio REAL,
        total_call_volume INTEGER,
        total_put_volume INTEGER,
        total_call_oi INTEGER,
        total_put_oi INTEGER
    )"""),
    ("options_metrics", "_idx_ticker_date", "CREATE INDEX IF NOT EXISTS idx_options_metrics_ticker_date ON options_metrics(ticker, collected_date)"),

    ("vix_term_structure", None, """CREATE TABLE IF NOT EXISTS vix_term_structure (
        id SERIAL PRIMARY KEY,
        collected_at TEXT NOT NULL,
        collected_date TEXT NOT NULL,
        vix REAL,
        vix9d REAL,
        vix3m REAL,
        vix1y REAL,
        term_structure_slope REAL,
        near_term_ratio REAL
    )"""),
    ("vix_term_structure", "_idx_date", "CREATE INDEX IF NOT EXISTS idx_vix_ts_date ON vix_term_structure(collected_date)"),

    ("scan_metrics", None, """CREATE TABLE IF NOT EXISTS scan_metrics (
        id SERIAL PRIMARY KEY,
        scan_number INTEGER,
        scan_time TEXT,
        universe_count INTEGER,
        features_count INTEGER,
        scored_count INTEGER,
        packet_worthy INTEGER,
        risk_passed INTEGER,
        paper_traded INTEGER,
        live_traded INTEGER,
        llm_success INTEGER,
        llm_total INTEGER,
        llm_fallback INTEGER,
        avg_conviction REAL,
        duration_seconds REAL,
        created_at TEXT
    )"""),

    ("research_docs", None, """CREATE TABLE IF NOT EXISTS research_docs (
        id TEXT PRIMARY KEY,
        filename TEXT,
        title TEXT,
        category TEXT,
        content TEXT,
        size_kb REAL,
        updated_at TEXT
    )"""),

    ("model_versions", None, """CREATE TABLE IF NOT EXISTS model_versions (
        version_id TEXT PRIMARY KEY,
        version_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        training_examples_count INTEGER,
        synthetic_examples_count INTEGER,
        outcome_examples_count INTEGER,
        model_file_path TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        notes TEXT,
        holdout_score REAL,
        holdout_details TEXT
    )"""),
    ("model_versions", "version_id", "ALTER TABLE model_versions ADD COLUMN version_id TEXT"),
    ("model_versions", "training_examples_count", "ALTER TABLE model_versions ADD COLUMN training_examples_count INTEGER"),
    ("model_versions", "synthetic_examples_count", "ALTER TABLE model_versions ADD COLUMN synthetic_examples_count INTEGER"),
    ("model_versions", "outcome_examples_count", "ALTER TABLE model_versions ADD COLUMN outcome_examples_count INTEGER"),
    ("model_versions", "model_file_path", "ALTER TABLE model_versions ADD COLUMN model_file_path TEXT"),
    ("model_versions", "holdout_score", "ALTER TABLE model_versions ADD COLUMN holdout_score REAL"),
    ("model_versions", "holdout_details", "ALTER TABLE model_versions ADD COLUMN holdout_details TEXT"),
    ("model_versions", "_idx_version_id", "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_version_id ON model_versions(version_id)"),

    # Command queue tables (Sprint 4C: Dashboard as Control Plane)
    ("pending_commands", None, """CREATE TABLE IF NOT EXISTS pending_commands (
        command_id TEXT PRIMARY KEY,
        command_type TEXT NOT NULL,
        command_name TEXT NOT NULL,
        payload_json TEXT DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        priority INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        claimed_at TEXT,
        expires_at TEXT,
        created_by TEXT DEFAULT 'dashboard'
    )"""),

    ("command_results", None, """CREATE TABLE IF NOT EXISTS command_results (
        result_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT DEFAULT '{}',
        error_message TEXT,
        execution_ms INTEGER,
        created_at TEXT NOT NULL
    )"""),

    ("config_overrides", None, """CREATE TABLE IF NOT EXISTS config_overrides (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL,
        previous_value TEXT,
        updated_at TEXT NOT NULL,
        updated_by TEXT DEFAULT 'dashboard'
    )"""),

    ("log_entries", None, """CREATE TABLE IF NOT EXISTS log_entries (
        log_id TEXT PRIMARY KEY,
        log_level TEXT NOT NULL,
        source TEXT NOT NULL,
        message TEXT NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL
    )"""),

    ("pending_commands", "_idx_status", "CREATE INDEX IF NOT EXISTS idx_pending_commands_status ON pending_commands(status, created_at)"),
    ("command_results", "_idx_command", "CREATE INDEX IF NOT EXISTS idx_command_results_command ON command_results(command_id)"),
    ("log_entries", "_idx_level", "CREATE INDEX IF NOT EXISTS idx_log_entries_level ON log_entries(log_level, created_at)"),
    ("shadow_trades", "_idx_status", "CREATE INDEX IF NOT EXISTS idx_shadow_trades_status ON shadow_trades(status)"),
    ("shadow_trades", "_idx_status_time", "CREATE INDEX IF NOT EXISTS idx_shadow_trades_status_time ON shadow_trades(status, actual_entry_time)"),
    ("recommendations", "_idx_created_at", "CREATE INDEX IF NOT EXISTS idx_recommendations_created_at ON recommendations(created_at)"),
]


def _wrap_alter_idempotent(sql: str) -> str:
    """Wrap ALTER TABLE ADD COLUMN in PL/pgSQL to be idempotent.

    Returns the original SQL for non-ALTER statements (CREATE TABLE/INDEX).
    """
    sql_upper = sql.strip().upper()
    if sql_upper.startswith("ALTER TABLE") and "ADD COLUMN" in sql_upper:
        return f"DO $$ BEGIN {sql}; EXCEPTION WHEN duplicate_column THEN NULL; END $$;"
    return sql


def main():
    print("Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    for table, column, sql in MIGRATIONS:
        try:
            cur.execute(_wrap_alter_idempotent(sql))
            if column:
                print(f"  [OK] {table}.{column}")
            else:
                print(f"  [OK] Created/verified table: {table}")
        except psycopg2.errors.DuplicateTable:
            print(f"  [SKIP] {table} already exists")
        except Exception as e:
            print(f"  [ERROR] {table}: {e}")

    conn.close()
    print("\nDone! Render Postgres schema is up to date.")
    print("The sync thread will populate data on the next cycle (within 2 minutes).")


if __name__ == "__main__":
    main()

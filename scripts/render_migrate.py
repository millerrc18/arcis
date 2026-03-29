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

    # shadow_trades — new columns added via ALTER TABLE in store.py
    ("shadow_trades", "order_type", "ALTER TABLE shadow_trades ADD COLUMN order_type TEXT"),

    # Slippage tracking columns
    ("shadow_trades", "signal_entry_price", "ALTER TABLE shadow_trades ADD COLUMN signal_entry_price REAL"),
    ("shadow_trades", "fill_entry_price", "ALTER TABLE shadow_trades ADD COLUMN fill_entry_price REAL"),
    ("shadow_trades", "entry_slippage_bps", "ALTER TABLE shadow_trades ADD COLUMN entry_slippage_bps REAL"),
    ("shadow_trades", "signal_exit_price", "ALTER TABLE shadow_trades ADD COLUMN signal_exit_price REAL"),
    ("shadow_trades", "fill_exit_price", "ALTER TABLE shadow_trades ADD COLUMN fill_exit_price REAL"),
    ("shadow_trades", "exit_slippage_bps", "ALTER TABLE shadow_trades ADD COLUMN exit_slippage_bps REAL"),

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
        metric_date TEXT,
        gpu_utilization REAL,
        scan_count INTEGER,
        scoring_count INTEGER,
        training_minutes REAL,
        created_at TEXT
    )"""),

    ("council_sessions", None, """CREATE TABLE IF NOT EXISTS council_sessions (
        session_id TEXT PRIMARY KEY,
        trigger TEXT,
        consensus TEXT,
        confidence REAL,
        summary TEXT,
        recommendation TEXT,
        rounds INTEGER,
        agent_count INTEGER,
        model TEXT,
        created_at TEXT
    )"""),

    ("council_votes", None, """CREATE TABLE IF NOT EXISTS council_votes (
        id SERIAL PRIMARY KEY,
        session_id TEXT,
        round INTEGER,
        agent_name TEXT,
        position TEXT,
        confidence REAL,
        recommendation TEXT,
        key_data_points TEXT,
        risk_flags TEXT,
        vote TEXT,
        is_devils_advocate INTEGER DEFAULT 0
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
        event_type TEXT,
        detail TEXT,
        created_at TEXT
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
        id SERIAL PRIMARY KEY,
        version_name TEXT,
        base_model TEXT,
        dataset_size INTEGER,
        training_loss REAL,
        eval_loss REAL,
        status TEXT DEFAULT 'candidate',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        promoted_at TIMESTAMP,
        notes TEXT
    )"""),

    # ── Sprint 1: v2 council tables + new columns ─────────────────

    # New tables for v2 council
    ("traffic_light_state", None, """CREATE TABLE IF NOT EXISTS traffic_light_state (
        id SERIAL PRIMARY KEY,
        current_regime TEXT,
        last_total_score REAL,
        updated_at TEXT
    )"""),

    ("council_calibrations", None, """CREATE TABLE IF NOT EXISTS council_calibrations (
        calibration_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        agent_name TEXT NOT NULL,
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

    ("validation_results", None, """CREATE TABLE IF NOT EXISTS validation_results (
        result_id TEXT PRIMARY KEY,
        validation_type TEXT,
        status TEXT,
        details TEXT,
        created_at TEXT
    )"""),

    # New columns on existing tables
    ("shadow_trades", "signal_price", "ALTER TABLE shadow_trades ADD COLUMN signal_price REAL"),
    ("shadow_trades", "implementation_shortfall_bps", "ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL"),
    ("shadow_trades", "strategy_type", "ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback'"),

    ("council_sessions", "result_json", "ALTER TABLE council_sessions ADD COLUMN result_json TEXT"),
    ("council_sessions", "session_type", "ALTER TABLE council_sessions ADD COLUMN session_type TEXT"),
    ("council_sessions", "trigger_reason", "ALTER TABLE council_sessions ADD COLUMN trigger_reason TEXT"),
    ("council_sessions", "is_contested", "ALTER TABLE council_sessions ADD COLUMN is_contested INTEGER DEFAULT 0"),
    ("council_sessions", "total_cost", "ALTER TABLE council_sessions ADD COLUMN total_cost REAL"),
    ("council_sessions", "rounds_completed", "ALTER TABLE council_sessions ADD COLUMN rounds_completed INTEGER DEFAULT 0"),
    ("council_sessions", "confidence_weighted_score", "ALTER TABLE council_sessions ADD COLUMN confidence_weighted_score REAL"),

    ("council_votes", "direction", "ALTER TABLE council_votes ADD COLUMN direction TEXT"),
    ("council_votes", "confidence_float", "ALTER TABLE council_votes ADD COLUMN confidence_float REAL"),
    ("council_votes", "assessment_json", "ALTER TABLE council_votes ADD COLUMN assessment_json TEXT"),
    ("council_votes", "vote_id", "ALTER TABLE council_votes ADD COLUMN vote_id TEXT"),
]


def main():
    print(f"Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    for table, column, sql in MIGRATIONS:
        try:
            cur.execute(sql)
            if column:
                print(f"  ✅ Added {table}.{column}")
            else:
                print(f"  ✅ Created/verified table: {table}")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
            print(f"  ⏭️  {table}.{column} already exists")
        except psycopg2.errors.DuplicateTable:
            conn.rollback()
            print(f"  ⏭️  {table} already exists")
        except Exception as e:
            conn.rollback()
            print(f"  ❌ {table}: {e}")

    conn.close()
    print("\nDone! Render Postgres schema is up to date.")
    print("The sync thread will populate data on the next cycle (within 2 minutes).")


if __name__ == "__main__":
    main()

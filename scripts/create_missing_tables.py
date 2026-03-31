"""Create all missing tables in local SQLite database.

Run once to silence sync errors for tables that haven't been created
by their respective features yet (council, new data collectors, etc).

Usage:
    python scripts/create_missing_tables.py
"""

import sqlite3
import os

DB_PATH = "ai_research_desk.sqlite3"

TABLES = [
    # AI Council
    """CREATE TABLE IF NOT EXISTS council_sessions (
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
    )""",

    """CREATE TABLE IF NOT EXISTS council_votes (
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
        is_devils_advocate INTEGER DEFAULT 0
    )""",

    # Schedule metrics
    """CREATE TABLE IF NOT EXISTS schedule_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_date TEXT,
        gpu_utilization REAL,
        scan_count INTEGER,
        scoring_count INTEGER,
        training_minutes REAL,
        created_at TEXT
    )""",

    # SEC EDGAR filings
    """CREATE TABLE IF NOT EXISTS edgar_filings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    )""",

    # Insider transactions
    """CREATE TABLE IF NOT EXISTS insider_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    )""",

    # Short interest
    """CREATE TABLE IF NOT EXISTS short_interest (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        settlement_date TEXT NOT NULL,
        short_interest REAL,
        avg_daily_volume REAL,
        days_to_cover REAL,
        short_pct_float REAL,
        source TEXT DEFAULT 'finnhub',
        collected_at TEXT NOT NULL,
        UNIQUE(ticker, settlement_date)
    )""",

    # Fed communications
    """CREATE TABLE IF NOT EXISTS fed_communications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comm_type TEXT NOT NULL,
        title TEXT,
        date TEXT NOT NULL,
        speaker TEXT,
        url TEXT,
        full_text TEXT,
        word_count INTEGER,
        collected_at TEXT NOT NULL,
        UNIQUE(comm_type, date, title)
    )""",

    # Analyst estimates
    """CREATE TABLE IF NOT EXISTS analyst_estimates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    )""",

    # Command queue (Sprint 4C: Dashboard as Control Plane)
    """CREATE TABLE IF NOT EXISTS pending_commands (
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
    )""",

    """CREATE TABLE IF NOT EXISTS command_results (
        result_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT DEFAULT '{}',
        error_message TEXT,
        execution_ms INTEGER,
        created_at TEXT NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS config_overrides (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL,
        previous_value TEXT,
        updated_at TEXT NOT NULL,
        updated_by TEXT DEFAULT 'dashboard'
    )""",

    """CREATE TABLE IF NOT EXISTS log_entries (
        log_id TEXT PRIMARY KEY,
        log_level TEXT NOT NULL,
        source TEXT NOT NULL,
        message TEXT NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL
    )""",

    # Build score history (referenced by build_score.py but never explicitly created)
    """CREATE TABLE IF NOT EXISTS build_score_history (
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
        created_at TEXT)""",

    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_build_score_date ON build_score_history(score_date)",
    "CREATE INDEX IF NOT EXISTS idx_edgar_ticker_date ON edgar_filings(ticker, filing_date)",
    "CREATE INDEX IF NOT EXISTS idx_insider_ticker_date ON insider_transactions(ticker, filing_date)",
    "CREATE INDEX IF NOT EXISTS idx_council_created ON council_sessions(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_pending_commands_status ON pending_commands(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_command_results_command ON command_results(command_id)",
    "CREATE INDEX IF NOT EXISTS idx_log_entries_level ON log_entries(log_level, created_at)",
]

# Column additions that may be missing on existing installations
ALTER_STATEMENTS = [
    ("shadow_trades", "strategy_type", "ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback'"),
    ("training_examples", "outcome_type", "ALTER TABLE training_examples ADD COLUMN outcome_type TEXT"),
    ("training_examples", "regime", "ALTER TABLE training_examples ADD COLUMN regime TEXT"),
    ("activity_log", "level", "ALTER TABLE activity_log ADD COLUMN level TEXT DEFAULT 'INFO'"),
]


def main():
    print(f"Creating missing tables in {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for sql in TABLES:
        try:
            cur.execute(sql)
            # Extract table/index name for display
            if "CREATE TABLE" in sql:
                name = sql.split("EXISTS")[1].split("(")[0].strip()
                print(f"  ✅ {name}")
            elif "CREATE INDEX" in sql:
                name = sql.split("EXISTS")[1].split("ON")[0].strip()
                print(f"  ✅ index: {name}")
        except Exception as e:
            print(f"  ❌ {e}")

    # Add missing columns to existing tables
    print("\nAdding missing columns...")
    for table, column, sql in ALTER_STATEMENTS:
        try:
            existing = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
            if column in existing:
                print(f"  ✅ {table}.{column} (already exists)")
            else:
                cur.execute(sql)
                print(f"  ✅ {table}.{column} (added)")
        except Exception as e:
            print(f"  ❌ {table}.{column}: {e}")

    conn.commit()
    conn.close()
    print("\nDone! All tables and columns created. Sync errors will stop on next cycle.")


if __name__ == "__main__":
    main()

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

    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_edgar_ticker_date ON edgar_filings(ticker, filing_date)",
    "CREATE INDEX IF NOT EXISTS idx_insider_ticker_date ON insider_transactions(ticker, filing_date)",
    "CREATE INDEX IF NOT EXISTS idx_council_created ON council_sessions(created_at)",
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

    conn.commit()
    conn.close()
    print("\nDone! All tables created. Sync errors will stop on next cycle.")


if __name__ == "__main__":
    main()

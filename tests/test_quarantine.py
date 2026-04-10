"""Tests for quarantine filtering in shadow_trades queries."""
import sqlite3
import pytest


@pytest.fixture
def db_with_quarantine(tmp_path):
    """Create a test DB with quarantined and clean trades."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            pnl_dollars REAL,
            pnl_pct REAL,
            exit_reason TEXT,
            actual_exit_price REAL,
            quarantined INTEGER DEFAULT 0,
            created_at TEXT DEFAULT '2026-04-01'
        )
    """)
    # 3 clean trades
    conn.execute("INSERT INTO shadow_trades VALUES ('t1','AAPL','closed',100,1.5,'target_1_hit',155.0,0,'2026-04-01')")
    conn.execute("INSERT INTO shadow_trades VALUES ('t2','MSFT','closed',-50,-0.8,'stop_hit',410.0,0,'2026-04-02')")
    conn.execute("INSERT INTO shadow_trades VALUES ('t3','GOOG','open',NULL,NULL,NULL,NULL,0,'2026-04-03')")
    # 2 quarantined trades
    conn.execute("INSERT INTO shadow_trades VALUES ('t4','SPY','closed',NULL,NULL,'reconciled_stale',NULL,1,'2026-04-10')")
    conn.execute("INSERT INTO shadow_trades VALUES ('t5','QQQ','closed',NULL,NULL,'order_rejected_buying_power',NULL,1,'2026-04-10')")
    conn.commit()
    return db_path


def test_quarantine_excludes_bad_trades(db_with_quarantine):
    conn = sqlite3.connect(db_with_quarantine)
    clean = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0"
    ).fetchone()[0]
    assert clean == 2, f"Expected 2 clean closed trades, got {clean}"


def test_quarantine_preserves_all_records(db_with_quarantine):
    conn = sqlite3.connect(db_with_quarantine)
    total = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
    assert total == 5, f"Expected 5 total trades (quarantine preserves records), got {total}"


def test_pnl_excludes_quarantined(db_with_quarantine):
    conn = sqlite3.connect(db_with_quarantine)
    pnl = conn.execute(
        "SELECT SUM(CAST(pnl_dollars AS REAL)) FROM shadow_trades "
        "WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0"
    ).fetchone()[0]
    assert pnl == 50.0, f"Expected $50 P&L from clean trades, got {pnl}"

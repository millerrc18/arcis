"""One-time script to quarantine April 10 cascade records.

Run: python scripts/quarantine_april10.py
"""
import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DB_PATH = "ai_research_desk.sqlite3"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Quarantine rejected trades (never executed)
    rejected = conn.execute(
        "UPDATE shadow_trades SET quarantined = 1 "
        "WHERE exit_reason = 'order_rejected_buying_power' AND quarantined = 0"
    ).rowcount
    log.info(f"Quarantined {rejected} rejected trades (buying power failures)")

    # 2. Quarantine reconciled-stale with NO exit price
    no_exit = conn.execute(
        "UPDATE shadow_trades SET quarantined = 1 "
        "WHERE exit_reason = 'reconciled_stale' "
        "AND (actual_exit_price IS NULL OR actual_exit_price = '' OR actual_exit_price = '0') "
        "AND quarantined = 0"
    ).rowcount
    log.info(f"Quarantined {no_exit} reconciled-stale trades (no exit price)")

    # 3. Quarantine stale open WMT trade
    wmt = conn.execute(
        "UPDATE shadow_trades SET quarantined = 1, status = 'closed', "
        "exit_reason = 'reconciled_stale' "
        "WHERE ticker = 'WMT' AND status = 'open' "
        "AND trade_id LIKE 'bb10c4b7%' AND quarantined = 0"
    ).rowcount
    log.info(f"Quarantined {wmt} stale WMT open trade(s)")

    conn.commit()

    # Report final state
    total_q = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE quarantined = 1").fetchone()[0]
    total_clean = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE quarantined = 0").fetchone()[0]
    clean_closed = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE quarantined = 0 AND status = 'closed'"
    ).fetchone()[0]
    clean_open = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE quarantined = 0 AND status = 'open'"
    ).fetchone()[0]

    log.info(f"\n=== QUARANTINE SUMMARY ===")
    log.info(f"Quarantined: {total_q}")
    log.info(f"Clean:       {total_clean} ({clean_closed} closed, {clean_open} open)")

    # Verify the verified trades are NOT quarantined
    verified_pnl = conn.execute(
        "SELECT COUNT(*), SUM(CAST(pnl_dollars AS REAL)) FROM shadow_trades "
        "WHERE quarantined = 0 AND status = 'closed' AND pnl_dollars IS NOT NULL"
    ).fetchone()
    log.info(f"Verified trades: {verified_pnl[0]}, Total P&L: ${verified_pnl[1]:.2f}")

    conn.close()


if __name__ == "__main__":
    main()

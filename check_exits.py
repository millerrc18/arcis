import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT ticker, status, exit_reason, trade_id FROM shadow_trades WHERE status IN ('exit_failed', 'pending_exit', 'open') ORDER BY status, ticker").fetchall()
for r in rows:
    print(f"  {r['ticker']:6s} | {r['status']:12s} | {r['exit_reason'] or '-'}")
print(f"\n{len(rows)} total")

import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT ticker, status, strategy_type, entry_price, pnl_dollars, pnl_pct, exit_reason, created_at FROM shadow_trades WHERE created_at LIKE '2026-04-09%' ORDER BY created_at DESC").fetchall()
print(f"{len(rows)} trades today")
for r in rows:
    print(dict(r))

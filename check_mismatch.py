import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
conn.row_factory = sqlite3.Row

# All non-closed trades
rows = conn.execute("SELECT ticker, status, exit_reason FROM shadow_trades WHERE status != 'closed' ORDER BY status, ticker").fetchall()
print(f"{len(rows)} non-closed trades in DB:")
for r in rows:
    print(f"  {r['ticker']:6s} | {r['status']:15s} | {r['exit_reason'] or '-'}")

# Compare with Alpaca
from src.shadow_trading.alpaca_adapter import get_all_positions
positions = get_all_positions()
db_tickers = set(r['ticker'] for r in rows)
alp_tickers = set(p['symbol'] for p in positions)

print(f"\nAlpaca: {len(positions)} positions")
print(f"DB open: {len(db_tickers)}")
print(f"On Alpaca but NOT in DB: {alp_tickers - db_tickers}")
print(f"In DB but NOT on Alpaca: {db_tickers - alp_tickers}")

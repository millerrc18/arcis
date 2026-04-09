import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')

# What columns does scan_metrics have?
cursor = conn.execute("PRAGMA table_info(scan_metrics)")
print("=== SCAN_METRICS COLUMNS ===")
for col in cursor.fetchall():
    print(f"  {col[1]} ({col[2]})")

# Last 5 scans - just grab everything
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM scan_metrics ORDER BY created_at DESC LIMIT 5").fetchall()
print("\n=== LAST 5 SCANS ===")
for r in rows:
    print(dict(r))

# Total trades + last trade
total = conn.execute("SELECT COUNT(*) as cnt FROM shadow_trades").fetchone()
print(f"\nTotal trades: {total['cnt']}")

last = conn.execute("SELECT ticker, status, created_at FROM shadow_trades ORDER BY created_at DESC LIMIT 1").fetchone()
if last:
    print(f"Last trade: {last['ticker']} ({last['status']}) at {last['created_at']}")

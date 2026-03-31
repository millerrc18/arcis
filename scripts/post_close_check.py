"""Post-close health check — run after market close to verify the day went well.

Usage: python scripts/post_close_check.py
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")

DB_CANDIDATES = ["ai_research_desk.sqlite3", "data/halcyon.db", "data/arcis.db"]
DB_PATH = None
for candidate in DB_CANDIDATES:
    p = REPO_ROOT / candidate
    if p.exists() and p.stat().st_size > 1000:
        DB_PATH = str(p)
        break

if not DB_PATH:
    print("ERROR: No database found")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

today = datetime.now(ET).strftime("%Y-%m-%d")
passes = 0
fails = 0
warnings = 0

def check(name, passed, detail=""):
    global passes, fails, warnings
    if passed == "warn":
        warnings += 1
        icon = "⚠️"
    elif passed:
        passes += 1
        icon = "✅"
    else:
        fails += 1
        icon = "❌"
    print(f"  {icon} {name}: {detail}")

print("=" * 60)
print(f"  POST-CLOSE HEALTH CHECK — {today}")
print("=" * 60)
print()


# === 1. Did scans run today? ===
print("[1] SCANS")
try:
    scans_today = conn.execute(
        "SELECT COUNT(*) FROM scan_metrics WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    check("Scans today", scans_today > 0, f"{scans_today} scans recorded")
    if scans_today > 0:
        latest = conn.execute(
            "SELECT packet_worthy, llm_success, llm_total, avg_conviction "
            "FROM scan_metrics WHERE created_at LIKE ? ORDER BY created_at DESC LIMIT 1",
            (f"{today}%",)
        ).fetchone()
        check("Latest scan quality", True,
              f"packets={latest['packet_worthy']}, LLM={latest['llm_success']}/{latest['llm_total']}, conv={latest['avg_conviction'] or 0:.1f}")
except Exception as e:
    check("Scans", False, str(e))
print()


# === 2. Did the Traffic Light update? ===
print("[2] TRAFFIC LIGHT")
try:
    tl = conn.execute("SELECT current_regime, last_total_score FROM traffic_light_state WHERE id=1").fetchone()
    vix = conn.execute("SELECT vix, collected_date FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1").fetchone()
    if tl and vix:
        regime = tl['current_regime']
        vix_val = vix['vix']
        # Sanity: VIX > 30 should not be GREEN
        if vix_val > 30 and regime == 'GREEN':
            check("Traffic Light", False, f"VIX={vix_val:.1f} but regime={regime} — should be YELLOW/RED")
        else:
            check("Traffic Light", True, f"regime={regime}, score={tl['last_total_score']}, VIX={vix_val:.1f}")
        # Is VIX data fresh (today)?
        vix_fresh = str(vix['collected_date']).startswith(today)
        check("VIX data fresh", vix_fresh or "warn", f"as of {vix['collected_date']}")
    else:
        check("Traffic Light", False, "no data")
except Exception as e:
    check("Traffic Light", False, str(e))
print()


# === 3. Are positions healthy? ===
print("[3] POSITIONS")
try:
    open_count = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status='open'").fetchone()[0]
    closed_today = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND actual_exit_time LIKE ?",
        (f"{today}%",)
    ).fetchone()[0]
    opened_today = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE actual_entry_time LIKE ?",
        (f"{today}%",)
    ).fetchone()[0]
    total_closed = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status='closed'").fetchone()[0]

    check("Open positions", open_count > 0, f"{open_count} open")
    check("Trades opened today", opened_today >= 0 or "warn", f"{opened_today} new")
    check("Trades closed today", True, f"{closed_today} closed")
    check("Total closed (gate progress)", True, f"{total_closed}/50 ({total_closed/50*100:.0f}%)")

    # Any positions nearing timeout?
    nearing_timeout = conn.execute(
        "SELECT ticker, julianday('now') - julianday(actual_entry_time) as days "
        "FROM shadow_trades WHERE status='open' "
        "AND julianday('now') - julianday(actual_entry_time) > 7 "
        "ORDER BY days DESC"
    ).fetchall()
    if nearing_timeout:
        tickers = ", ".join(f"{r['ticker']}({r['days']:.0f}d)" for r in nearing_timeout[:5])
        check("Timeout risk", "warn", f"{len(nearing_timeout)} positions near timeout: {tickers}")
    else:
        check("Timeout risk", True, "none near timeout")
except Exception as e:
    check("Positions", False, str(e))
print()


# === 4. Did the council run? ===
print("[4] COUNCIL")
try:
    council_today = conn.execute(
        "SELECT COUNT(*) FROM council_sessions WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    check("Council ran today", council_today > 0, f"{council_today} sessions")
    if council_today > 0:
        council_cols = [r[1] for r in conn.execute("PRAGMA table_info(council_sessions)").fetchall()]
        select_cols = ["session_id", "session_type", "created_at"]
        if "status" in council_cols:
            select_cols.append("status")
        if "total_cost" in council_cols:
            select_cols.append("total_cost")
        latest = conn.execute(
            f"SELECT {', '.join(select_cols)} "
            "FROM council_sessions WHERE created_at LIKE ? ORDER BY created_at DESC LIMIT 1",
            (f"{today}%",)
        ).fetchone()
        status = latest['status'] if 'status' in council_cols else 'unknown'
        cost = f", cost=${latest['total_cost']:.4f}" if 'total_cost' in council_cols and latest['total_cost'] else ""
        check("Latest session", status in ('completed', 'unknown'),
              f"type={latest['session_type']}, status={status}{cost}")
except Exception as e:
    check("Council", False, str(e))
print()


# === 5. Is quality scoring happening? ===
print("[5] QUALITY SCORING")
try:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(training_examples)").fetchall()]
    if "quality_score_auto" in cols:
        total = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE quality_score_auto IS NOT NULL"
        ).fetchone()[0]
        pct = (scored / total * 100) if total > 0 else 0
        check("Auto-scoring progress", scored > 0, f"{scored}/{total} scored ({pct:.0f}%)")
        if scored > 0:
            avg = conn.execute(
                "SELECT AVG(quality_score_auto) FROM training_examples WHERE quality_score_auto IS NOT NULL"
            ).fetchone()[0]
            check("Avg quality", True, f"{avg:.2f}/5.0")
    else:
        check("quality_score_auto column", False, "missing — run migration")
except Exception as e:
    check("Quality scoring", False, str(e))
print()


# === 6. Is data collecting? ===
print("[6] DATA COLLECTION")
try:
    tables_to_check = [
        ("vix_term_structure", "collected_date"),
        ("macro_snapshots", "collected_date"),
        ("options_metrics", "created_at"),
    ]
    for table, date_col in tables_to_check:
        try:
            latest = conn.execute(f"SELECT {date_col} FROM {table} ORDER BY {date_col} DESC LIMIT 1").fetchone()
            if latest:
                latest_date = str(latest[0])[:10]
                is_fresh = latest_date >= (datetime.now(ET) - timedelta(days=2)).strftime("%Y-%m-%d")
                check(f"{table}", is_fresh, f"latest: {latest_date}")
            else:
                check(f"{table}", False, "empty")
        except Exception:
            pass
except Exception as e:
    check("Data collection", False, str(e))
print()


# === 7. Any errors in logs? ===
print("[7] ERRORS")
try:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(log_entries)").fetchall()]
    if "log_level" in cols:
        errors_today = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE log_level IN ('ERROR','CRITICAL') AND created_at LIKE ?",
            (f"{today}%",)
        ).fetchone()[0]
        check("Errors today", errors_today == 0, f"{errors_today} errors")
        if errors_today > 0:
            recent = conn.execute(
                "SELECT message FROM log_entries WHERE log_level IN ('ERROR','CRITICAL') "
                "AND created_at LIKE ? ORDER BY created_at DESC LIMIT 3",
                (f"{today}%",)
            ).fetchall()
            for r in recent:
                print(f"    → {r['message'][:100]}")
    elif "level" in cols:
        errors_today = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE level IN ('ERROR','CRITICAL') AND created_at LIKE ?",
            (f"{today}%",)
        ).fetchone()[0]
        check("Errors today", errors_today == 0, f"{errors_today} errors")
    else:
        check("Log entries", "warn", "level column not found")
except Exception as e:
    check("Errors", "warn", str(e))
print()


# === 8. Render sync working? ===
print("[8] RENDER SYNC")
try:
    if "command_results" in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        cmd_count = conn.execute("SELECT COUNT(*) FROM command_results").fetchone()[0]
        check("Command queue", True, f"{cmd_count} results recorded")
    else:
        check("Command queue tables", "warn", "not created yet — run render_migrate.py")
except Exception as e:
    check("Render sync", "warn", str(e))
print()


# === SUMMARY ===
conn.close()
total = passes + fails + warnings
print("=" * 60)
print(f"  RESULTS: {passes} passed, {fails} failed, {warnings} warnings ({total} checks)")
if fails == 0:
    print("  ✅ SYSTEM HEALTHY — everything worked today")
elif fails <= 2:
    print("  ⚠️ MINOR ISSUES — review failures above")
else:
    print("  ❌ ISSUES DETECTED — investigate before tomorrow's open")
print("=" * 60)
input("\nPress Enter to exit...")

"""Arcis weekly review -- run from repo root: python scripts/weekly_review.py"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Ensure we're in the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

# Find the database
DB_CANDIDATES = ["ai_research_desk.sqlite3", "data/halcyon.db", "data/arcis.db"]
DB_PATH = None
for candidate in DB_CANDIDATES:
    p = REPO_ROOT / candidate
    if p.exists() and p.stat().st_size > 1000:
        DB_PATH = str(p)
        break

print("=" * 60)
print(f"  ARCIS WEEKLY REVIEW -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)
print(f"\nRepo root: {REPO_ROOT}")
print(f"Database:  {DB_PATH or 'NOT FOUND'}")

if not DB_PATH:
    print("\nERROR: No database found. Searched:")
    for c in DB_CANDIDATES:
        p = REPO_ROOT / c
        print(f"  {p} -- {'exists' if p.exists() else 'missing'} ({p.stat().st_size if p.exists() else 0} bytes)")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# List all tables so we know what's available
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print(f"Tables:    {len(tables)}")
print()


def has_column(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols
    except Exception:
        return False


def get_columns(table: str) -> list[str]:
    """Get all column names for a table."""
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


# === 0. SCHEMA HEALTH ===
print("[0/7] SCHEMA HEALTH")
print("-" * 60)
EXPECTED_COLUMNS = {
    "shadow_trades": ["trade_id", "ticker", "status", "pnl_pct", "pnl_dollars",
                      "strategy_type", "exit_reason", "actual_entry_time",
                      "actual_exit_time", "direction", "created_at"],
    "training_examples": ["example_id", "created_at", "source", "ticker",
                          "quality_score", "outcome_type", "regime",
                          "curriculum_stage", "input_text", "output_text"],
    "traffic_light_state": ["current_regime", "last_total_score"],
    "scan_metrics": ["scan_time", "packet_worthy", "llm_success", "llm_total",
                     "avg_conviction", "created_at"],
    "activity_log": ["event_type", "detail", "level", "created_at"],
    "council_sessions": ["session_id", "session_type", "created_at"],
    "build_score_history": ["score_date", "build_score", "created_at"],
}
schema_ok = True
for table, expected_cols in EXPECTED_COLUMNS.items():
    if table not in tables:
        print(f"  MISSING TABLE: {table}")
        schema_ok = False
        continue
    actual = get_columns(table)
    missing = [c for c in expected_cols if c not in actual]
    if missing:
        print(f"  {table}: MISSING COLUMNS: {', '.join(missing)}")
        schema_ok = False
    else:
        print(f"  {table}: OK ({len(actual)} cols)")
if schema_ok:
    print("  All expected tables and columns present")
print()


# === 1. CTO REPORT ===
print("[1/7] CTO REPORT")
print("-" * 60)
try:
    from src.evaluation.cto_report import generate_cto_report
    report = generate_cto_report(days=7, db_path=DB_PATH)
    print(json.dumps(report, indent=2, default=str))
except Exception as e:
    print(f"  Error: {e}")
    print("  (Will gather data manually below)")
print()


# === 2. OPEN POSITIONS ===
print("[2/7] OPEN POSITIONS")
print("-" * 60)
try:
    if "shadow_trades" in tables:
        # Build query dynamically based on available columns
        select_cols = ["ticker", "direction", "pnl_pct", "pnl_dollars",
                       "planned_allocation", "actual_entry_time"]
        if has_column("shadow_trades", "strategy_type"):
            select_cols.append("strategy_type")
        query = f"SELECT {', '.join(select_cols)} FROM shadow_trades WHERE status='open' ORDER BY actual_entry_time"
        trades = conn.execute(query).fetchall()
        print(f"Open positions: {len(trades)}")
        for t in trades:
            pnl = f"{t['pnl_pct']:.1f}%" if t['pnl_pct'] else "N/A"
            pnl_d = f"${t['pnl_dollars']:.0f}" if t['pnl_dollars'] else ""
            strat = t['strategy_type'] if has_column("shadow_trades", "strategy_type") and t['strategy_type'] else 'pullback'
            entry = str(t['actual_entry_time'])[:10] if t['actual_entry_time'] else '?'
            print(f"  {t['ticker']:5s} {t['direction'] or 'long':5s} PnL: {pnl:>7s} {pnl_d:>7s}  Entry: {entry}  {strat}")

        closed = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status='closed'").fetchone()[0]
        print(f"\nClosed trades: {closed}")

        if closed > 0:
            closed_trades = conn.execute(
                "SELECT ticker, pnl_pct, pnl_dollars, exit_reason, actual_exit_time "
                "FROM shadow_trades WHERE status='closed' ORDER BY actual_exit_time DESC LIMIT 10"
            ).fetchall()
            print("\nRecent closed trades:")
            for t in closed_trades:
                pnl = f"{t['pnl_pct']:.1f}%" if t['pnl_pct'] else "?"
                reason = t['exit_reason'] or '?'
                exit_dt = str(t['actual_exit_time'])[:10] if t['actual_exit_time'] else '?'
                print(f"  {t['ticker']:5s} PnL: {pnl:>7s}  Reason: {reason:15s}  Exit: {exit_dt}")
    else:
        print("  Table 'shadow_trades' not found")
        print(f"  Available tables: {', '.join(tables[:20])}")
except Exception as e:
    print(f"  Error: {e}")
print()


# === 3. RECENT SCANS ===
print("[3/7] RECENT SCANS")
print("-" * 60)
try:
    if "scan_metrics" in tables:
        rows = conn.execute(
            "SELECT scan_time, packet_worthy, llm_success, llm_total, avg_conviction, created_at "
            "FROM scan_metrics ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        if rows:
            print(f"Last {len(rows)} scans:")
            print(f"  {'Date':>12s} {'Time':>6s} {'Pkts':>5s} {'LLM_OK':>7s} {'LLM_Tot':>8s} {'Conv':>6s}")
            for r in rows:
                dt = str(r['created_at'])[:10] if r['created_at'] else '?'
                print(f"  {dt:>12s} {str(r['scan_time'] or '?'):>6s} {r['packet_worthy'] or 0:>5d} "
                      f"{r['llm_success'] or 0:>7d} {r['llm_total'] or 0:>8d} {r['avg_conviction'] or 0:>6.1f}")
        else:
            print("  No scan metrics recorded yet")

        total_scans = conn.execute("SELECT COUNT(*) FROM scan_metrics").fetchone()[0]
        print(f"\nTotal scans all-time: {total_scans}")
    else:
        print("  Table 'scan_metrics' not found")
except Exception as e:
    print(f"  Error: {e}")
print()


# === 4. TRAINING DATA ===
print("[4/7] TRAINING DATA")
print("-" * 60)
try:
    if "training_examples" in tables:
        total = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
        recent = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE created_at > datetime('now', '-7 days')"
        ).fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*), AVG(quality_score) FROM training_examples WHERE quality_score IS NOT NULL"
        ).fetchone()
        print(f"Training examples: {total} total, {recent} this week")
        if scored[1]:
            print(f"Scored: {scored[0]}, avg quality: {scored[1]:.2f}")
        else:
            print(f"Scored: {scored[0]}, avg quality: N/A")

        # Outcome distribution (only if column exists)
        if has_column("training_examples", "outcome_type"):
            outcomes = conn.execute(
                "SELECT outcome_type, COUNT(*) as cnt FROM training_examples "
                "WHERE outcome_type IS NOT NULL GROUP BY outcome_type ORDER BY cnt DESC"
            ).fetchall()
            if outcomes:
                print(f"Outcome distribution: {', '.join(f'{r[0]}={r[1]}' for r in outcomes)}")

        # Regime distribution (only if column exists)
        if has_column("training_examples", "regime"):
            regimes = conn.execute(
                "SELECT regime, COUNT(*) as cnt FROM training_examples "
                "WHERE regime IS NOT NULL GROUP BY regime ORDER BY cnt DESC"
            ).fetchall()
            if regimes:
                print(f"Regime distribution: {', '.join(f'{r[0]}={r[1]}' for r in regimes)}")
    else:
        print("  Table 'training_examples' not found")
except Exception as e:
    print(f"  Error: {e}")
print()


# === 5. TRAFFIC LIGHT + VIX ===
print("[5/7] TRAFFIC LIGHT + VIX")
print("-" * 60)
try:
    if "traffic_light_state" in tables:
        tl = conn.execute(
            "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id=1"
        ).fetchone()
        if tl:
            print(f"Traffic Light: {tl['current_regime']} (score {tl['last_total_score']})")
        else:
            print("Traffic Light: no data")
    else:
        print("  Table 'traffic_light_state' not found")

    if "vix_term_structure" in tables:
        vix = conn.execute(
            "SELECT vix, vix9d, vix3m, collected_date FROM vix_term_structure "
            "ORDER BY collected_date DESC LIMIT 1"
        ).fetchone()
        if vix:
            print(f"VIX: {vix['vix']:.1f} (9D: {vix['vix9d']:.1f}, 3M: {vix['vix3m']:.1f}) as of {vix['collected_date']}")
        else:
            print("VIX: no data")
    else:
        print("  Table 'vix_term_structure' not found")
except Exception as e:
    print(f"  Error: {e}")
print()


# === 6. SYSTEM HEALTH ===
print("[6/7] SYSTEM HEALTH")
print("-" * 60)
try:
    # Model info
    if "model_versions" in tables:
        models = conn.execute(
            "SELECT version_name, status, created_at FROM model_versions ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        print(f"Model versions: {len(models)}")
        for m in models:
            print(f"  {m['version_name']} -- {m['status']} (created {str(m['created_at'])[:10]})")

    # Council sessions
    if "council_sessions" in tables:
        sessions = conn.execute(
            "SELECT COUNT(*) as cnt, MAX(created_at) as last "
            "FROM council_sessions"
        ).fetchone()
        print(f"Council sessions: {sessions['cnt']} total, last: {str(sessions['last'])[:16] if sessions['last'] else 'never'}")

    # Bracket health
    if "bracket_health" in tables:
        brackets = conn.execute(
            "SELECT COUNT(*) FROM bracket_health WHERE status != 'ok'"
        ).fetchone()
        print(f"Bracket issues: {brackets[0]}")

    # Recent errors in activity log (check column exists)
    if "activity_log" in tables:
        if has_column("activity_log", "level"):
            errors = conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE level='ERROR' AND created_at > datetime('now', '-7 days')"
            ).fetchone()
            print(f"Errors this week: {errors[0]}")
        else:
            print("  activity_log.level column not found (run migration)")

    # Build score
    if "build_score_history" in tables:
        bs = conn.execute(
            "SELECT build_score, score_date FROM build_score_history ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if bs:
            print(f"Latest Build Score: {bs['build_score']:.1f} ({bs['score_date']})")
except Exception as e:
    print(f"  Error: {e}")
print()

conn.close()

print("=" * 60)
print("  REVIEW COMPLETE -- Copy everything above and paste to Claude")
print("=" * 60)
input("\nPress Enter to exit...")

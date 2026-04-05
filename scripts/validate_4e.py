"""Sprint 4E validation script -- checks DB schema and data health.

When to run:
    One-time after completing Sprint 4E, or ad-hoc to verify that
    all expected tables and columns exist. Superseded by `validate-schema`
    for general use, but kept for backwards compatibility.

What it reads:
    - Target SQLite database (PRAGMA table_info for each expected table)
    - Data counts from training_examples, shadow_trades, traffic_light_state

What it writes:
    - Nothing — stdout-only validation report

Prerequisites:
    - Database at the specified path (default: ai_research_desk.sqlite3)

Usage: python scripts/validate_4e.py [path/to/db]
"""

import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "ai_research_desk.sqlite3"

try:
    conn = sqlite3.connect(DB)
except Exception as e:
    print(f"Cannot connect to {DB}: {e}")
    sys.exit(1)

EXPECTED_COLUMNS = {
    "shadow_trades": ["trade_id", "ticker", "status", "pnl_pct", "pnl_dollars",
                      "signal_price", "fill_entry_price", "implementation_shortfall_bps",
                      "strategy_type", "exit_reason", "actual_entry_time",
                      "actual_exit_time", "planned_allocation", "direction", "created_at"],
    "training_examples": ["example_id", "created_at", "source", "ticker",
                          "quality_score", "outcome_type", "regime",
                          "curriculum_stage", "input_text", "output_text"],
    "traffic_light_state": ["id", "current_regime", "last_total_score"],
    "vix_term_structure": ["id", "collected_date", "vix", "vix9d", "vix3m"],
    "scan_metrics": ["scan_time", "packet_worthy", "llm_success",
                     "llm_total", "avg_conviction", "created_at"],
    "council_sessions": ["session_id", "session_type",
                         "total_cost", "created_at"],
    "council_votes": ["vote_id", "session_id", "agent_name",
                      "confidence"],
    "build_score_history": ["score_id", "score_date", "build_score", "created_at"],
    "activity_log": ["level"],
    "pending_commands": ["command_id", "command_type", "status"],
    "command_results": ["result_id", "command_id", "status"],
    "config_overrides": ["setting_key", "setting_value"],
    "log_entries": ["log_id", "log_level", "source", "message"],
}

errors = []
for table, expected_cols in EXPECTED_COLUMNS.items():
    existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if not existing:
        errors.append(f"TABLE MISSING: {table}")
        continue
    for col in expected_cols:
        if col not in existing:
            errors.append(f"COLUMN MISSING: {table}.{col}")

if errors:
    print("SCHEMA VALIDATION FAILED:")
    for e in errors:
        print(f"  [FAIL] {e}")
    sys.exit(1)
else:
    print("[OK] Schema validation passed -- all expected tables and columns exist")

# Data health checks
print()
total_te = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
with_outcome = conn.execute("SELECT COUNT(*) FROM training_examples WHERE outcome_type IS NOT NULL").fetchone()[0]
print(f"Training examples: {total_te} total, {with_outcome} with outcome_type ({with_outcome/max(total_te,1)*100:.0f}%)")

total_st = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
with_strat = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE strategy_type IS NOT NULL").fetchone()[0]
print(f"Shadow trades: {total_st} total, {with_strat} with strategy_type ({with_strat/max(total_st,1)*100:.0f}%)")

tl = conn.execute("SELECT current_regime, last_total_score FROM traffic_light_state WHERE id=1").fetchone()
if tl:
    print(f"Traffic Light: regime={tl[0]}, score={tl[1]}")

vix = conn.execute("SELECT vix, collected_date FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1").fetchone()
if vix:
    print(f"Latest VIX: {vix[0]} (as of {vix[1]})")

conn.close()
print("\n[OK] Validation complete")

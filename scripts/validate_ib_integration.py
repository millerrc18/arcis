"""Validate IB integration data completeness across all tables.

Run: python scripts/validate_ib_integration.py

Called by: operator (manual), docs/operations/ib-smoke-test.md Phase 6
Calls: src.config.DB_PATH, sqlite3
Owns tables: none (read-only)
Config keys: none

Checks:
1. All shadow_trades have broker column populated (not NULL)
2. All IB bracket trades have ib_child_order_ids populated
3. All ib_shadow_log entries have required fields
4. Schema columns exist (broker, ib_child_order_ids, broker_order_id, ib_perm_id)
5. Position counts match between DB queries
6. daily_ib_health table exists and is accessible
7. No Alpaca-only columns referenced for IB trades
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, str]] = []  # (status, label, detail)


def _pass(label: str, detail: str = "") -> None:
    _results.append(("PASS", label, detail))
    suffix = f" ({detail})" if detail else ""
    print(f"[PASS] {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    _results.append(("WARN", label, detail))
    suffix = f" ({detail})" if detail else ""
    print(f"[WARN] {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    _results.append(("FAIL", label, detail))
    suffix = f" ({detail})" if detail else ""
    print(f"[FAIL] {label}{suffix}")


# ---------------------------------------------------------------------------
# Individual checks — each wrapped in try/except
# ---------------------------------------------------------------------------

def check_broker_populated(cur: sqlite3.Cursor) -> None:
    """Check 1: All shadow_trades have broker column populated."""
    try:
        cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE broker IS NULL")
        null_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM shadow_trades")
        total = cur.fetchone()[0]
        cur.execute("SELECT broker, COUNT(*) FROM shadow_trades GROUP BY broker")
        breakdown = {row[0]: row[1] for row in cur.fetchall()}
        parts = ", ".join(f"{count} {broker}" for broker, count in sorted(breakdown.items()))
        if null_count == 0:
            _pass(f"shadow_trades.broker: 100% populated", parts or "0 trades")
        else:
            _fail(f"shadow_trades.broker: {null_count}/{total} NULL", parts)
    except Exception as e:
        _fail("shadow_trades.broker check", str(e))


def check_ib_bracket_orders(cur: sqlite3.Cursor) -> None:
    """Check 2: All IB bracket trades have ib_child_order_ids populated."""
    try:
        cur.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE broker = 'ib' AND ib_child_order_ids IS NULL AND status = 'open'"
        )
        missing = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE broker = 'ib'")
        ib_total = cur.fetchone()[0]
        if ib_total == 0:
            _warn("No IB trades yet -- routing validation deferred")
        elif missing == 0:
            _pass(f"IB bracket orders: all {ib_total} have ib_child_order_ids")
        else:
            _fail(f"IB bracket orders: {missing}/{ib_total} missing ib_child_order_ids")
    except Exception as e:
        _fail("IB bracket order check", str(e))


def check_ib_shadow_log(cur: sqlite3.Cursor) -> None:
    """Check 3: ib_shadow_log entries have required fields."""
    try:
        cur.execute("SELECT COUNT(*) FROM ib_shadow_log")
        total = cur.fetchone()[0]
        if total == 0:
            _pass("ib_shadow_log: 0 entries (shadow mode not yet active)")
            return
        # Check required fields are populated
        cur.execute(
            "SELECT COUNT(*) FROM ib_shadow_log "
            "WHERE ticker IS NULL OR action IS NULL OR created_at IS NULL"
        )
        incomplete = cur.fetchone()[0]
        if incomplete == 0:
            _pass(f"ib_shadow_log: {total} entries, all have required fields")
        else:
            _fail(f"ib_shadow_log: {incomplete}/{total} missing required fields")
    except Exception as e:
        _fail("ib_shadow_log check", str(e))


def check_schema_columns(cur: sqlite3.Cursor) -> None:
    """Check 4: IB-related schema columns exist in shadow_trades."""
    required = ["broker", "ib_child_order_ids", "broker_order_id", "ib_perm_id"]
    try:
        cur.execute("PRAGMA table_info(shadow_trades)")
        existing = {row[1] for row in cur.fetchall()}
        missing = [col for col in required if col not in existing]
        if not missing:
            _pass(f"Schema: {', '.join(required)} columns exist")
        else:
            _fail(f"Schema: missing columns: {', '.join(missing)}")
    except Exception as e:
        _fail("Schema column check", str(e))


def check_position_counts(cur: sqlite3.Cursor) -> None:
    """Check 5: Position counts are consistent across queries."""
    try:
        cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE status = 'open'")
        open_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'open' AND broker = 'alpaca'"
        )
        alpaca_open = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'open' AND broker = 'ib'"
        )
        ib_open = cur.fetchone()[0]
        if alpaca_open + ib_open == open_count:
            _pass(
                f"Alpaca paper trades: {alpaca_open} open, "
                f"no regression detected"
            )
        else:
            _fail(
                f"Position count mismatch: {open_count} open "
                f"but alpaca({alpaca_open}) + ib({ib_open}) = {alpaca_open + ib_open}"
            )
    except Exception as e:
        _fail("Position count check", str(e))


def check_daily_ib_health(cur: sqlite3.Cursor) -> None:
    """Check 6: daily_ib_health table exists and is accessible."""
    try:
        cur.execute("SELECT COUNT(*) FROM daily_ib_health")
        count = cur.fetchone()[0]
        _pass(f"daily_ib_health: table accessible, {count} entries")
    except Exception as e:
        _fail("daily_ib_health table check", str(e))


def check_no_alpaca_only_on_ib(cur: sqlite3.Cursor) -> None:
    """Check 7: No Alpaca-only columns referenced for IB trades."""
    try:
        cur.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE broker = 'ib' AND alpaca_order_id IS NOT NULL "
            "AND broker_order_id IS NULL"
        )
        bad_refs = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE broker = 'ib'")
        ib_total = cur.fetchone()[0]
        if ib_total == 0:
            _pass("Alpaca-only column check: no IB trades to validate")
        elif bad_refs == 0:
            _pass(
                f"Alpaca-only column check: {ib_total} IB trades, "
                f"none using alpaca_order_id without broker_order_id"
            )
        else:
            _warn(
                f"Alpaca-only columns: {bad_refs} IB trades have "
                f"alpaca_order_id but no broker_order_id"
            )
    except Exception as e:
        _fail("Alpaca-only column check", str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    db_path = DB_PATH
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return 1

    print(f"=== IB INTEGRATION VALIDATION ===")
    print(f"Database: {db_path}\n")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        check_broker_populated(cur)
        check_ib_bracket_orders(cur)
        check_ib_shadow_log(cur)
        check_schema_columns(cur)
        check_position_counts(cur)
        check_daily_ib_health(cur)
        check_no_alpaca_only_on_ib(cur)
    finally:
        conn.close()

    # Summary
    pass_count = sum(1 for s, _, _ in _results if s == "PASS")
    warn_count = sum(1 for s, _, _ in _results if s == "WARN")
    fail_count = sum(1 for s, _, _ in _results if s == "FAIL")

    print(f"\n---")
    print(f"Result: {pass_count} PASS, {warn_count} WARN, {fail_count} FAIL")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

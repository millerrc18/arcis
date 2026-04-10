# Sprint: Data Quarantine & Schema Hardening

> **Branch:** `fix/data-quarantine`
> **Priority:** HIGH — blocks accurate performance reporting and Phase 1 gate tracking
> **Estimated time:** 4-6 hours CC time
> **Depends on:** Data quality audit report at `docs/audits/data-quality-audit-2026-04-10.md`

> ⚠️ **Read first:** `docs/audits/data-quality-audit-2026-04-10.md` — the full blast radius analysis.
> This sprint implements the quarantine recommendation from that audit.
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b fix/data-quarantine
> python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
> ```

---

## Context

The April 10 cascade created 77 compromised records in `shadow_trades`:
- 42 rejected orders (never executed — buying power failures)
- 27 reconciled-stale with NO exit price or P&L
- 7 reconciled-stale with ESTIMATED (unverified) P&L
- 1 stale open WMT trade (no matching Alpaca position)

Only 18 closed trades have verified P&L (math-checked: entry × shares = recorded P&L ±$1).
2 open trades (CAT, CVX) are matched on Alpaca and valid.

The database is salvageable. Training data (1,019 examples) and recommendations
(1,507) are confirmed clean. This sprint quarantines the bad trade records and
fixes the queries that read from them.

---

## Task 1: Add `quarantined` column to schema registry

**File:** `src/schema/registry.py`

Add to the `shadow_trades` table definition, after the last existing `ColumnDef`:

```python
ColumnDef("quarantined", "INTEGER", default="0"),
```

Then run:
```bash
python -m src.main validate-schema --fix
```

This will `ALTER TABLE shadow_trades ADD COLUMN quarantined INTEGER DEFAULT 0`.

**Verify:**
```bash
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
cols = [r[1] for r in conn.execute('PRAGMA table_info(shadow_trades)').fetchall()]
assert 'quarantined' in cols, 'MISSING: quarantined column'
print('✓ quarantined column exists')
# Verify all existing rows default to 0
q = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE quarantined != 0').fetchone()[0]
assert q == 0, f'Expected 0 quarantined rows, got {q}'
print('✓ all rows default to quarantined=0')
"
```

---

## Task 2: Flag compromised records

**File:** Create `scripts/quarantine_april10.py`

```python
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

    # Verify the 18 verified trades are NOT quarantined
    verified_pnl = conn.execute(
        "SELECT COUNT(*), SUM(CAST(pnl_dollars AS REAL)) FROM shadow_trades "
        "WHERE quarantined = 0 AND status = 'closed' AND pnl_dollars IS NOT NULL"
    ).fetchone()
    log.info(f"Verified trades: {verified_pnl[0]}, Total P&L: ${verified_pnl[1]:.2f}")

    conn.close()

if __name__ == "__main__":
    main()
```

**Run it:**
```bash
python scripts/quarantine_april10.py
```

**Expected output:**
```
Quarantined 42 rejected trades (buying power failures)
Quarantined ~27-34 reconciled-stale trades (no exit price)
Quarantined 1 stale WMT open trade(s)

=== QUARANTINE SUMMARY ===
Quarantined: ~70-77
Clean:       ~20 (18 closed, 2 open)
Verified trades: 18, Total P&L: $603.96
```

---

## Task 3: Add quarantine filter to ALL shadow_trades queries

**Files (every file below must be updated):**
- `src/evaluation/hshs_live.py`
- `src/evaluation/system_validator.py`
- `src/evaluation/auditor.py`
- `src/evaluation/build_score.py`
- `src/evaluation/model_monitor.py`
- `src/evaluation/change_detector.py`
- `src/evaluation/gate_evaluator.py`
- `src/journal/store.py`
- `src/api/cloud_routes/analytics.py`
- `src/api/cloud_routes/core.py`
- `src/services/shadow_service.py`

**Rule:** Every query that reads from `shadow_trades` MUST add a quarantine filter.

For queries that already have a WHERE clause, append:
```sql
AND COALESCE(quarantined, 0) = 0
```

For queries without a WHERE clause, add:
```sql
WHERE COALESCE(quarantined, 0) = 0
```

Use `COALESCE(quarantined, 0)` instead of just `quarantined = 0` to handle
any rows where the column is NULL (defensive coding for SQLite).

**EXCEPTION:** Do NOT filter quarantined records in `store.py:get_trade_by_id()`
(line ~212) — this is used for individual lookups and should return any trade
regardless of quarantine status.

**Verify:** After updating all files:
```bash
# Count remaining unfiltered queries (should be 0 except get_trade_by_id)
grep -rn "FROM shadow_trades" src/ --include="*.py" | \
  grep -v __pycache__ | grep -v registry | grep -v schema | \
  grep -v quarantine_april10 | \
  grep -v "quarantined" | \
  grep -v "get_trade_by_id"
```

If that grep returns ANY lines, those queries still need the filter. Fix them.

---

## Task 4: Fix TEXT→REAL type casting in shadow_service.py

**File:** `src/services/shadow_service.py`

The audit found that numeric columns may be stored as TEXT in existing databases
(the schema registry defines them as REAL, but databases created before the
registry have TEXT types). Add defensive casting wherever numeric shadow_trades
columns are read.

Find every place that reads `entry_price`, `actual_entry_price`, `actual_exit_price`,
`pnl_dollars`, `pnl_pct`, `planned_shares`, `planned_allocation`, `stop_price`,
`target_1`, `target_2` from a dict row and wrap with `float()` or `int()`:

```python
# Pattern to apply everywhere:
entry = float(t.get("actual_entry_price") or t.get("entry_price") or 0)
shares = int(float(t.get("planned_shares") or t.get("actual_shares") or 0))
pnl = float(t.get("pnl_dollars") or 0)
```

Also check and fix in:
- `src/journal/store.py` — any arithmetic on shadow_trades columns
- `src/evaluation/gate_evaluator.py` — P&L calculations
- `src/evaluation/hshs_live.py` — win rate and drawdown math
- `src/api/cloud_routes/analytics.py` — all P&L aggregations

**Use SQL CAST as the primary fix** — it's cleaner than Python-side casting:
```sql
-- Instead of:
SELECT pnl_dollars FROM shadow_trades WHERE status = 'closed'
-- Use:
SELECT CAST(pnl_dollars AS REAL) as pnl_dollars FROM shadow_trades WHERE status = 'closed'
```

For aggregate queries, CAST inside the aggregate:
```sql
SELECT COALESCE(SUM(CAST(pnl_dollars AS REAL)), 0) FROM shadow_trades ...
```

**Verify:**
```bash
python -c "
from src.services.shadow_service import get_shadow_status
result = get_shadow_status()
print(f'Open trades: {len(result[\"trades\"])}')
print('✓ shadow_service runs without TypeError')
"
```

---

## Task 5: Investigate the COP -$993.82 stop-hit

**Read-only investigation.** Check if this trade was affected by the cascade:

```python
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
conn.row_factory = sqlite3.Row

# Find the COP stop-hit trade
cop = conn.execute(
    "SELECT * FROM shadow_trades WHERE ticker = 'COP' AND pnl_dollars < -500"
).fetchone()

if cop:
    print(f"Trade ID: {cop['trade_id']}")
    print(f"Entry: {cop['entry_price']} / Actual entry: {cop['actual_entry_price']}")
    print(f"Stop: {cop['stop_price']}")
    print(f"Exit: {cop['actual_exit_price']}")
    print(f"Shares: {cop['planned_shares']} / Actual: {cop.get('actual_shares')}")
    print(f"P&L: ${cop['pnl_dollars']}")
    print(f"Entry date: {cop['created_at']}")
    print(f"Exit date: {cop['actual_exit_time']}")
    print(f"Source: {cop['source']}")
    print(f"Exit reason: {cop['exit_reason']}")

    # Check if exit date is during/after the cascade
    if cop['actual_exit_time'] and '2026-04-10' in str(cop['actual_exit_time']):
        print("\n⚠️ EXIT DATE IS APRIL 10 — potentially affected by cascade")
    else:
        print("\n✓ Exit date is not April 10")

    # Verify the math
    entry = float(cop['actual_entry_price'] or cop['entry_price'] or 0)
    exit_p = float(cop['actual_exit_price'] or 0)
    shares = int(float(cop['planned_shares'] or cop.get('actual_shares') or 0))
    if entry and exit_p and shares:
        expected = (exit_p - entry) * shares
        print(f"\nP&L math: ({exit_p} - {entry}) × {shares} = ${expected:.2f}")
        print(f"Recorded P&L: ${float(cop['pnl_dollars']):.2f}")
        if abs(expected - float(cop['pnl_dollars'])) > 1:
            print("⚠️ P&L MISMATCH — this trade may need quarantine")
        else:
            print("✓ P&L math checks out — this is a legitimate loss")
```

**If the COP trade is cascade-affected** (exit on April 10, P&L mismatch):
```sql
UPDATE shadow_trades SET quarantined = 1
WHERE ticker = 'COP' AND pnl_dollars < -500;
```

**If legitimate:** Leave it. Document the finding in the commit message.

---

## Task 6: Update dashboard metrics

**File:** `src/api/cloud_routes/analytics.py`

The CTO report and dashboard KPI cards will now show different numbers because
quarantined trades are excluded. Verify the numbers are correct by running:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
closed = conn.execute(
    'SELECT COUNT(*), '
    'SUM(CASE WHEN CAST(pnl_dollars AS REAL) > 0 THEN 1 ELSE 0 END), '
    'SUM(CASE WHEN CAST(pnl_dollars AS REAL) <= 0 THEN 1 ELSE 0 END), '
    'SUM(CAST(pnl_dollars AS REAL)) '
    'FROM shadow_trades WHERE status = \"closed\" AND COALESCE(quarantined, 0) = 0 '
    'AND pnl_dollars IS NOT NULL'
).fetchone()
print(f'Closed trades: {closed[0]}')
print(f'Wins: {closed[1]}, Losses: {closed[2]}')
print(f'Win rate: {closed[1]/closed[0]*100:.1f}%' if closed[0] else 'N/A')
print(f'Total P&L: \${closed[3]:.2f}')
"
```

**Expected:** ~18 closed trades, ~83% win rate, ~$604 total P&L (or ~$1,598 if COP is not quarantined).

---

## Task 7: Add quarantine-aware test

**File:** `tests/test_quarantine.py`

```python
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
```

**Run:**
```bash
python -m pytest tests/test_quarantine.py -v
```

---

## Task 8: Documentation update

**Files:**
- `MASTER.md` — Update Section 2 volatile counts: closed trades = 18 (verified), 77 quarantined
- `CHANGELOG.md` — Add entry for quarantine
- `docs/audits/data-quality-audit-2026-04-10.md` — Add "IMPLEMENTED" header with date

**Commit messages (one per logical unit):**

```bash
git add src/schema/registry.py
git commit -m "schema: add quarantined column to shadow_trades

INTEGER DEFAULT 0. Used to flag compromised records from the April 10
cascade without deleting them. All queries must filter on this column."

git add scripts/quarantine_april10.py
git commit -m "scripts: one-time quarantine of April 10 cascade records

Flags 77 compromised shadow_trades: 42 rejected (never executed),
34 reconciled-stale (no exit price), 1 stale WMT open trade.
Preserves 18 verified trades ($603.96 P&L) and 2 live positions."

git add src/
git commit -m "fix: add quarantine filter to all shadow_trades queries

Every query reading from shadow_trades now includes
COALESCE(quarantined, 0) = 0. Also adds CAST(... AS REAL) for
TEXT-typed numeric columns in existing databases.

Fixes: TypeError in shadow_service.py (str > int comparison)"

git add tests/test_quarantine.py
git commit -m "test: quarantine filtering for shadow_trades

Verifies: quarantined records excluded from analytics,
total records preserved, P&L calculations correct."

git add MASTER.md CHANGELOG.md docs/
git commit -m "docs: update counts post-quarantine — 18 verified trades, 77 quarantined"
```

**Push:**
```bash
git push origin fix/data-quarantine
```

Then create PR via GitHub UI or:
```bash
curl -s -X POST "https://api.github.com/repos/millerrc18/halcyon-lab/pulls" \
  -H "Authorization: token YOUR_PAT" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "fix: data quarantine — April 10 cascade blast radius",
    "body": "Implements quarantine recommendation from data quality audit.\n\n- Adds `quarantined` column to shadow_trades\n- Flags 77 compromised records (42 rejected, 34 stale, 1 orphan)\n- Preserves 18 verified trades ($604 P&L) and 2 live positions\n- Adds quarantine filter to ALL shadow_trades queries\n- Fixes TEXT→REAL type casting in shadow_service\n- Investigates COP -$994 stop-hit\n\nDoes NOT delete any data. Quarantine = flag, not purge.",
    "head": "fix/data-quarantine",
    "base": "main"
  }'
```

---

## Verification checklist

```bash
# All tests pass
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# New test passes
python -m pytest tests/test_quarantine.py -v

# Shadow service works without TypeError
python -c "from src.services.shadow_service import get_shadow_status; print('✓')"

# Frontend builds
cd frontend && npm run build && cd ..

# Quarantine counts are correct
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
q = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE quarantined = 1').fetchone()[0]
c = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE quarantined = 0 AND status = \"closed\"').fetchone()[0]
print(f'Quarantined: {q}, Clean closed: {c}')
assert q >= 70, f'Expected 70+ quarantined, got {q}'
assert c >= 18, f'Expected 18+ clean closed, got {c}'
print('✓ counts correct')
"

# No unfiltered shadow_trades queries remain
count=$(grep -rn "FROM shadow_trades" src/ --include="*.py" | \
  grep -v __pycache__ | grep -v registry | grep -v schema | \
  grep -v quarantine | grep -v "quarantined" | \
  grep -v "get_trade_by_id" | wc -l)
echo "Unfiltered queries: $count (should be 0)"
```

## File size guardrails
```bash
# No src/ file over 400 lines
find src/ -name "*.py" -not -path "*/__pycache__/*" | xargs wc -l | sort -rn | head -5
# No function over 60 lines (spot-check modified files)
```

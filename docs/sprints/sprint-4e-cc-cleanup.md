# Sprint 4E: Post-Review Cleanup & Production Hardening (Claude Code)

> **Executor:** Claude Code
> **Scope:** 10 tasks
> **Prerequisite:** Sprints 4A + 4B + 4C + 4D ALL MERGED. This is the final cleanup sprint.
> **Read first:** AGENTS.md, docs/conventions.md
> **Context:** First weekly review found issues. Some were caused by computer sleep (now resolved — screen turns off, PC stays on). Schema gaps and wiring issues still need fixing. Leakage investigation completed: false alarm (balanced accuracy 0.613 can't beat majority baseline of 0.714). After this sprint, system goes into autonomous trading mode for the week.
> **Test baseline:** 1,105 test functions. Must not decrease.

---

## Weekly Review Findings (March 30, 2026)

| # | Issue | Severity | Root Cause |
|---|---|---|---|
| 1 | `strategy_type` column missing from production DB | 🚨 P0 | ALTER TABLE never ran on live DB |
| 2 | `outcome_type` column missing from training_examples | 🚨 P0 | Same — schema migration gap |
| 3 | VIX 30.6 but Traffic Light says GREEN (score 1) | 🚨 P0 | Traffic Light not updating from VIX data (may be partly caused by computer sleep) |
| 4 | scan_metrics table has 0 records | 🚨 P0 | Scans not recorded — likely caused by computer sleep interrupting watch loop |
| 5 | 0 quality-scored training examples (out of 972) | ⚠️ P1 | Quality rubric not applied |
| 6 | Only 1 council session since go-live | ⚠️ P1 | Council scheduler not triggering (computer sleep was a factor) |
| 7 | ~~Leakage test at 0.613~~ | ✅ CLOSED | False alarm: balanced accuracy can't beat 71.4% majority baseline. "Forbidden words" are structural XML template fields, not look-ahead. Class imbalance (71% WIN) is the real issue — addressed in v2 training spec. |
| 8 | `level` column missing from activity_log | ⚠️ P2 | Schema gap |
| 9 | README still references old architecture | ⚠️ P2 | Stale docs |
| 10 | Sprint 4C command queue tables not created on production DB | 🚨 P0 | create_missing_tables.py updated but never run on live DB |

**Note:** Computer sleeping during market hours (now resolved) likely caused issues #3, #4, and #6. The fixes should still be applied to make the system resilient to future sleep/restart events.

---

## Pre-Sprint Checks (MANDATORY)

```bash
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60: print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

---

## Task 1: Fix Production DB Schema — Missing Columns + Tables

The codebase expects columns and tables that don't exist in the production `ai_research_desk.sqlite3`. Sprint 4C added command queue tables to `create_missing_tables.py` but the script was never run on the live DB.

**Create `scripts/migrate_production_db.py`** — a safe migration script that:
1. Checks which columns already exist (using `PRAGMA table_info`)
2. Only adds columns that are missing via ALTER TABLE
3. Runs `create_missing_tables.py` logic to create any missing tables (including 4C's command queue tables: pending_commands, command_results, config_overrides, log_entries, build_score_history)
4. Prints what it did
5. Does NOT drop or modify existing data
6. Works on both `ai_research_desk.sqlite3` and any other DB path passed as argument

Missing columns to add:
```sql
ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback';
ALTER TABLE training_examples ADD COLUMN outcome_type TEXT;
ALTER TABLE training_examples ADD COLUMN regime TEXT;
ALTER TABLE activity_log ADD COLUMN level TEXT DEFAULT 'INFO';
```

After creating the script, **RUN IT** against the production database:
```bash
python scripts/migrate_production_db.py
```

Verify it worked by checking all tables and columns exist (see V1 in the validation plan).

**Also update `scripts/create_missing_tables.py`** to include these ALTER TABLE statements so new installations get them automatically.

Write tests in `tests/test_db_migration.py` (≥3 tests: migration is idempotent, adds missing columns, doesn't touch existing data).

---

## Task 2: Fix Traffic Light Update

The Traffic Light shows GREEN (score 1) when VIX is 30.6 — this should be YELLOW or RED.

**Investigate:** Check `src/features/traffic_light.py` — specifically:
1. Is `compute_traffic_light()` actually being called during scans?
2. Is it reading VIX from the correct table (`vix_term_structure`)?
3. Is it writing the result to `traffic_light_state`?
4. Is the VIX threshold correct? (should be: VIX <20 = 0, 20-30 = 1, >30 = 2)

**Check `src/scheduler/watch.py`** — is the Traffic Light updated during each scan cycle, or only on a separate schedule?

**Fix:** Ensure `compute_traffic_light()` is called at the START of each scan cycle (before any trade decisions) and writes the updated regime to `traffic_light_state`. If VIX data is stale (>24 hours old), flag as YELLOW regardless.

Write a test that verifies: VIX=30.6 → Traffic Light score includes VIX component = 2.

---

## Task 3: Fix scan_metrics Recording

The `scan_metrics` table has 0 records, which means either:
- Scans ARE running but metrics aren't being saved
- Scans are NOT running at all (watch loop issue)

**Investigate `src/services/scan_service.py`:**
1. Does `run_scan()` write to `scan_metrics` at the end?
2. If not, add the INSERT statement
3. Fields: scan_time, packet_worthy (count), llm_success, llm_total, avg_conviction, created_at

**Investigate `src/scheduler/watch.py`:**
1. Is `_run_scan()` being called on schedule?
2. Is it catching and swallowing errors silently?

**Fix:** Ensure every scan cycle (successful or not) writes a row to `scan_metrics`. Failed scans should record `packet_worthy=0, llm_success=0, llm_total=0`.

---

## Task 4: Fix Council Scheduling

Only 1 council session since March 27. The council should run daily.

**Investigate `src/scheduler/watch.py`:**
1. Find where council sessions are scheduled
2. Check the time condition (should run once per trading day, e.g., 8:30 AM ET)
3. Check if the council is failing silently (error swallowed)

**Fix:** Ensure the council runs daily during market hours. Add a Telegram notification if the council fails to run (not just if it succeeds).

---

## Task 5: Backfill outcome_type on Training Examples

After Task 1 adds the `outcome_type` column, backfill it from existing data:

```python
# For examples linked to closed trades:
UPDATE training_examples SET outcome_type = 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM shadow_trades st 
            WHERE st.recommendation_id = training_examples.recommendation_id 
            AND st.pnl_pct > 0
        ) THEN 'WIN'
        WHEN EXISTS (
            SELECT 1 FROM shadow_trades st 
            WHERE st.recommendation_id = training_examples.recommendation_id 
            AND st.pnl_pct <= 0
        ) THEN 'LOSS'
        ELSE NULL
    END
WHERE outcome_type IS NULL;
```

If the training examples don't have `recommendation_id`, check which column links them to trades and adjust accordingly.

Also backfill `strategy_type` on `shadow_trades` — all existing trades are 'pullback' (only strategy live in Phase 1).

---

## Task 6: Update weekly_review.py for Robustness

The current `scripts/weekly_review.py` crashes on missing columns. Fix:
1. Before querying any column, check it exists via `PRAGMA table_info`
2. Use `try/except` per section (already partially done, but some sections still fail)
3. Add a "schema health" section that lists expected vs actual columns
4. Fix the open positions query to not reference `strategy_type` if it doesn't exist

---

## Task 7: Update README.md

The README still references the old architecture. Rewrite it for Arcis:

Include:
- **What Arcis is** — 2-3 sentences (systematic equity research platform, fine-tuned LLMs, 5-agent AI council)
- **Current status** — Phase 1 bootcamp, paper trading, ~25 positions
- **Architecture overview** — watch loop → scan → LLM → governor → executor → bracket orders
- **Quick start** — how to run: `python -m src.main watch`
- **Dashboard** — halcyonlab.app
- **Tech stack** — Python 3.12, FastAPI, React 18, SQLite, Alpaca, Ollama
- **Research** — 67 documents in docs/research/
- **SEC compliance note** — "AI-informed", "systematic", "research-driven"

Keep it under 100 lines. This is a private repo, so the README is for Ryan + AI agents, not public marketing.

---

## Task 8: Fix weekly_review.bat Wrapper

Replace the current `scripts/weekly_review.bat` with:
```bat
@echo off
cd /d "%~dp0\.."
python scripts\weekly_review.py
```
This ensures it always runs from the repo root regardless of where the bat file is saved.

---

## Task 9: Documentation Update (MANDATORY)

Run verification commands from `docs/sprint-checklist.md`. Update:
- AGENTS.md counts (new scripts, new test file)
- CHANGELOG.md (Sprint 4E entry)
- architecture.md (if schema changes affect documented architecture)
- Regenerate `config/known_violations.json` if any violations were fixed

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Paste and complete sprint checklist.

---

## COMPREHENSIVE VALIDATION PLAN

After all 9 tasks are complete, run every section below IN ORDER. Every check must pass before the sprint is considered done. If any check fails, fix it before moving to the next section.

### V1: Database Schema Validation

Verify all expected columns exist in production DB:

```python
"""Run: python scripts/validate_4e.py (create this script)"""
import sqlite3
import sys

DB = "ai_research_desk.sqlite3"
conn = sqlite3.connect(DB)

EXPECTED_COLUMNS = {
    "shadow_trades": ["trade_id", "ticker", "status", "pnl_pct", "pnl_dollars",
                      "signal_price", "fill_price", "implementation_shortfall_bps",
                      "strategy_type", "exit_reason", "actual_entry_time",
                      "actual_exit_time", "planned_allocation", "direction", "created_at"],
    "training_examples": ["example_id", "created_at", "source", "ticker",
                          "quality_score", "outcome_type", "regime",
                          "curriculum_stage", "input_text", "output_text"],
    "traffic_light_state": ["id", "current_regime", "last_total_score"],
    "vix_term_structure": ["id", "collected_date", "vix", "vix9d", "vix3m"],
    "scan_metrics": ["metric_id", "scan_time", "packet_worthy", "llm_success",
                     "llm_total", "avg_conviction", "created_at"],
    "council_sessions": ["session_id", "session_type", "status", "result_json",
                         "total_cost", "created_at"],
    "council_votes": ["vote_id", "session_id", "agent_name", "direction",
                      "confidence", "created_at"],
    "build_score_history": ["score_id", "score_date", "build_score", "created_at"],
    "activity_log": ["level"],
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
        print(f"  ✗ {e}")
    sys.exit(1)
else:
    print("✓ Schema validation passed — all expected tables and columns exist")
```

### V2: Traffic Light Accuracy

Verify the Traffic Light correctly responds to current VIX:

```bash
python -c "
from src.features.traffic_light import compute_traffic_light
result = compute_traffic_light()
print(f'Regime: {result[\"regime\"]}')
print(f'Score: {result[\"total_score\"]}')
print(f'VIX component: {result.get(\"vix_score\", \"?\")}')
print(f'Trend component: {result.get(\"trend_score\", \"?\")}')
print(f'Credit component: {result.get(\"credit_score\", \"?\")}')

# Verify it updated the DB
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
tl = conn.execute('SELECT current_regime, last_total_score FROM traffic_light_state WHERE id=1').fetchone()
vix = conn.execute('SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1').fetchone()
print(f'\nDB state: regime={tl[0]}, score={tl[1]}')
print(f'Latest VIX: {vix[0]}')

# Sanity check: VIX > 30 should NOT produce GREEN
if vix[0] > 30 and tl[0] == 'GREEN':
    print('✗ FAIL: VIX > 30 but Traffic Light is GREEN')
else:
    print('✓ Traffic Light is consistent with VIX level')
"
```

### V3: Scan Pipeline End-to-End

Verify a scan cycle produces metrics:

```bash
# Run one scan manually
python -m src.main scan

# Check scan_metrics has a new row
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
row = conn.execute('SELECT COUNT(*) FROM scan_metrics').fetchone()
print(f'Scan metrics rows: {row[0]}')
if row[0] == 0:
    print('✗ FAIL: scan_metrics still empty after manual scan')
else:
    latest = conn.execute('SELECT scan_time, packet_worthy, llm_success, llm_total, created_at FROM scan_metrics ORDER BY created_at DESC LIMIT 1').fetchone()
    print(f'✓ Latest scan: time={latest[0]}, packets={latest[1]}, llm_ok={latest[2]}/{latest[3]}, at={latest[4]}')
"
```

### V4: Council Execution

Verify a council session runs and stores properly:

```bash
python -m src.main council --session-type daily

python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
conn.row_factory = sqlite3.Row
session = conn.execute('SELECT session_id, session_type, status, total_cost, created_at FROM council_sessions ORDER BY created_at DESC LIMIT 1').fetchone()
if session:
    print(f'✓ Latest session: {session[\"session_id\"][:8]}... type={session[\"session_type\"]} status={session[\"status\"]} cost=${session[\"total_cost\"]:.4f}')
    votes = conn.execute('SELECT COUNT(*) FROM council_votes WHERE session_id = ?', (session['session_id'],)).fetchone()[0]
    print(f'  Votes recorded: {votes} (expected 5)')
    if votes != 5:
        print('  ✗ FAIL: expected 5 votes (one per agent)')
else:
    print('✗ FAIL: no council session found')
"
```

### V5: Bracket Health Check

Verify bracket monitor can run against open positions:

```bash
python -c "
from src.shadow_trading.bracket_monitor import check_bracket_health
result = check_bracket_health()
print(f'Positions checked: {result.get(\"checked\", 0)}')
print(f'Brackets intact: {result.get(\"intact\", 0)}')
print(f'Issues found: {result.get(\"issues\", 0)}')
if result.get('issues', 0) == 0:
    print('✓ All brackets intact')
else:
    print('⚠ Bracket issues detected — review')
"
```

### V6: Build Score Computation

Verify the Build Score module works end-to-end:

```bash
python -c "
from src.evaluation.build_score import compute_build_score
result = compute_build_score()
print(f'Build Score: {result[\"build_score\"]}')
print(f'Components:')
for key, val in result['components'].items():
    status = '✓' if val > 0 else '⚠ ZERO'
    print(f'  {key:25s} {val:6.1f}  {status}')
print(f'\nData asset detail:')
for key, val in result.get('data_asset_detail', {}).items():
    print(f'  {key:15s} {val:6.1f}')
"
```

### V7: Alpaca Reconciliation

Verify local DB matches broker state:

```bash
python -m src.main reconcile-live

python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
open_count = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE status=\"open\"').fetchone()[0]
closed_count = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE status=\"closed\"').fetchone()[0]
print(f'Open positions: {open_count}')
print(f'Closed trades: {closed_count}')
print(f'Total: {open_count + closed_count}')
print('✓ Reconciliation complete — verify these numbers match Alpaca dashboard')
"
```

### V8: Training Data Health

Verify outcome_type backfill and data quality:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')

total = conn.execute('SELECT COUNT(*) FROM training_examples').fetchone()[0]
with_outcome = conn.execute('SELECT COUNT(*) FROM training_examples WHERE outcome_type IS NOT NULL').fetchone()[0]
print(f'Training examples: {total}')
print(f'With outcome_type: {with_outcome} ({with_outcome/total*100:.0f}%)')

# Check distribution
outcomes = conn.execute('SELECT outcome_type, COUNT(*) FROM training_examples WHERE outcome_type IS NOT NULL GROUP BY outcome_type').fetchall()
for o in outcomes:
    print(f'  {o[0]}: {o[1]}')

# Check strategy_type on shadow_trades
with_strat = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE strategy_type IS NOT NULL').fetchone()[0]
total_trades = conn.execute('SELECT COUNT(*) FROM shadow_trades').fetchone()[0]
print(f'\nShadow trades with strategy_type: {with_strat}/{total_trades}')

# Leakage recheck
try:
    from src.training.leakage_detector import check_outcome_leakage
    result = check_outcome_leakage()
    print(f'Leakage test: balanced_acc={result[\"balanced_accuracy\"]:.3f} status={result[\"status\"]}')
except Exception as e:
    print(f'Leakage test: {e}')
"
```

### V9: Frontend Build + API Connectivity

Verify the dashboard compiles and API endpoints return valid data:

```bash
# Frontend compiles
cd frontend && npm run build && cd ..
echo "✓ Frontend build passed"

# API endpoints return valid JSON (run local server briefly)
python -c "
import requests, json, time, subprocess, signal, sys

# Start server in background
proc = subprocess.Popen([sys.executable, '-m', 'src.api.app'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

endpoints = [
    '/api/build-score',
    '/api/traffic-light/current',
    '/api/shadow/open',
    '/api/shadow/closed',
    '/api/health/hshs',
    '/api/council/latest',
]

try:
    for ep in endpoints:
        try:
            r = requests.get(f'http://localhost:8000{ep}', timeout=5)
            status = '✓' if r.status_code == 200 else '✗'
            print(f'{status} {ep} → {r.status_code} ({len(r.content)} bytes)')
        except Exception as e:
            print(f'✗ {ep} → {e}')
finally:
    proc.terminate()
"
```

### V10: Full Weekly Review (final validation)

Run the weekly review script — every section should produce data, no errors:

```bash
python scripts/weekly_review.py
```

**Expected:** All 6 sections produce output. No "Error:" lines. No "no such table" or "no such column" errors. Traffic Light reflects actual VIX. Scan metrics show at least 1 row. Build Score computes non-zero.

### V11: Watch Loop Smoke Test

Start the watch loop, let it run for 5 minutes, then check it's functioning:

```bash
# Start watch loop
python -m src.main watch

# After 5 minutes, check Telegram for:
# 1. Startup banner notification
# 2. Premarket bracket check (if during market hours)
# 3. At least one scan attempt (if during market hours)
# 4. No error notifications

# Then Ctrl+C to stop and verify no crashes
```

---

## Validation Summary Checklist

CC must verify all of these pass before marking the sprint done:

- [ ] V1: All expected tables and columns exist in production DB
- [ ] V2: Traffic Light regime is consistent with current VIX level
- [ ] V3: Manual scan produces a row in scan_metrics
- [ ] V4: Council session runs, stores 5 votes, returns result
- [ ] V5: Bracket monitor checks all open positions
- [ ] V6: Build Score computes with all 6 non-zero components
- [ ] V7: Alpaca reconciliation completes without errors
- [ ] V8: outcome_type backfilled, strategy_type backfilled, leakage recheck passes
- [ ] V9: Frontend builds, all API endpoints return 200
- [ ] V10: weekly_review.py runs clean with no errors
- [ ] V11: Watch loop starts, runs 5 min, no crashes

**If any validation fails, fix it before committing. Do not mark the sprint complete with failing validations.**

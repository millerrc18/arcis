# Sprint 4E: Post-Review Cleanup & Production Hardening (Claude Code)

> **Executor:** Claude Code
> **Scope:** 9 tasks
> **Prerequisite:** Sprints 4A + 4B + 4D MERGED. Sprint 4C (command queue) is deferred — this cleanup is more urgent.
> **Read first:** AGENTS.md, docs/conventions.md
> **Context:** First weekly review found 6 issues that need fixing before the system can trade reliably.

---

## Weekly Review Findings (March 30, 2026)

| # | Issue | Severity | Root Cause |
|---|---|---|---|
| 1 | `strategy_type` column missing from production DB | 🚨 P0 | ALTER TABLE never ran on live DB |
| 2 | `outcome_type` column missing from training_examples | 🚨 P0 | Same — schema migration gap |
| 3 | VIX 30.6 but Traffic Light says GREEN (score 1) | 🚨 P0 | Traffic Light not updating from VIX data |
| 4 | scan_metrics table has 0 records | 🚨 P0 | Scans not being recorded |
| 5 | 0 quality-scored training examples (out of 972) | ⚠️ P1 | Quality rubric not applied |
| 6 | Only 1 council session since go-live | ⚠️ P1 | Council scheduler not triggering |
| 7 | Leakage test at 0.613 (threshold 0.55) | ⚠️ P1 | Investigate — may be look-ahead bias |
| 8 | `level` column missing from activity_log | ⚠️ P2 | Schema gap |
| 9 | README still references old architecture | ⚠️ P2 | Stale docs |

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

## Task 1: Fix Production DB Schema — Missing Columns

The codebase expects columns that don't exist in the production `ai_research_desk.sqlite3`:

```sql
-- shadow_trades: add strategy_type
ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback';

-- training_examples: add outcome_type
ALTER TABLE training_examples ADD COLUMN outcome_type TEXT;

-- training_examples: add regime (if missing)
ALTER TABLE training_examples ADD COLUMN regime TEXT;

-- activity_log: add level (if missing)
ALTER TABLE activity_log ADD COLUMN level TEXT DEFAULT 'INFO';
```

**Create `scripts/migrate_production_db.py`** — a safe migration script that:
1. Checks which columns already exist (using `PRAGMA table_info`)
2. Only adds columns that are missing
3. Prints what it did
4. Does NOT drop or modify existing data
5. Works on both `ai_research_desk.sqlite3` and any other DB path passed as argument

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

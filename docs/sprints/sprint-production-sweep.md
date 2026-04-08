# Sprint: Production Hotfix Sweep — All 14 Open Issues

> **Branch:** `fix/production-sweep`
> **Tags:** v0.15.1 (critical), v0.15.2 (high), v0.15.3 (medium)
> **Estimated time:** 6-8 hours CC time
> **Ralph Loop:** 3× on each phase

> ⚠️ **Read first:** `MASTER.md`, then this entire sprint before starting.
> This sprint fixes ALL 14 open GitHub issues in 3 phases, tagging after each phase.

---

## Pre-Flight

```bash
git checkout main
git pull origin main
git checkout -b fix/production-sweep
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py
# Record baseline test count (expect ~1515)
cd frontend && npm run build && cd ..
```

---

## Phase 1: CRITICAL — Tag v0.15.1

**5 issues. These affect every scan cycle and trade safety.**

### Task 1.1: Stop-price guard before bracket orders (#326)

**Problem:** Bracket orders can be placed with `stop_price=0`, which means no stop-loss protection.

**Files:** `src/shadow_trading/executor.py`

**Fix:** Before any bracket order placement, validate:
```python
if not stop_price or float(stop_price) <= 0:
    logger.error("[EXECUTOR] Refusing bracket order for %s: stop_price=%s (must be > 0)", ticker, stop_price)
    return {"error": "stop_price must be > 0", "ticker": ticker}
```

Add this guard in:
1. `_submit_entry_order()` — before calling `place_bracket_order()`
2. `_submit_paper_entry()` — before calling `place_bracket_order()`
3. Any other path that creates bracket orders

**Test:** `test_bracket_order_rejects_zero_stop` — verify stop_price=0 is rejected with error, not silently placed.

---

### Task 1.2: Fractional share truncation in reconciliation (#325)

**Problem:** `BrokerPosition` truncates fractional shares, causing reconciliation mismatches.

**Files:** `src/shadow_trading/reconcile.py`, `src/shadow_trading/alpaca_adapter.py`

**Fix:** Ensure quantity comparisons use `float` precision, not `int`:
```python
# In reconciliation comparison logic:
local_qty = float(local_trade.get("planned_shares", 0))
alpaca_qty = float(position.get("qty", 0))
# Compare with tolerance for fractional rounding:
if abs(local_qty - alpaca_qty) < 0.01:
    # Match — not a discrepancy
```

**Test:** `test_reconcile_fractional_shares` — verify 10.5 shares local vs 10.5 shares Alpaca = match, not mismatch.

---

### Task 1.3: LLM conviction parsing (#329)

**Problem:** Only 1/9 tickers return a parseable conviction. The rest default to 5.

**Files:** `src/llm/packet_writer.py`

**Investigation first — read the debug files:**
```bash
# Check what the LLM is actually outputting
ls -la data/debug/llm_responses/
# Read the latest 5 responses
cat data/debug/llm_responses/*.txt | head -200
```

Then identify why the existing 5 extraction patterns fail. Common causes:
1. Model outputs `Conviction: 7/10` instead of `<conviction>7</conviction>`
2. Model outputs conviction in a sentence: "My conviction level is 7"
3. Model outputs conviction with extra whitespace or newlines inside XML tags

**Fix:** Based on what the debug files show, add extraction patterns. Likely additions:
```python
# Pattern 7: "conviction: N/10" or "conviction level: N"
match = re.search(r'(?:conviction|confidence)\s*(?:level)?[:\s]+(\d+)\s*(?:/\s*10)?', response, re.IGNORECASE)

# Pattern 8: "N/10" standalone on a line
match = re.search(r'^(\d+)\s*/\s*10\s*$', response, re.MULTILINE)
```

**Add conviction parse success rate to dashboard:**
In the scan summary logging (watch.py), compute and log:
```python
conviction_parsed = sum(1 for p in packets if p.conviction != 5)
conviction_total = len(packets)
logger.info("[WATCH] Conviction parse rate: %d/%d (%.0f%%)",
            conviction_parsed, conviction_total,
            conviction_parsed / conviction_total * 100 if conviction_total else 0)
```

**Test:**
- `test_conviction_extraction_pattern_7` — "conviction: 7/10" → 7
- `test_conviction_extraction_pattern_8` — "8/10" on standalone line → 8
- `test_conviction_default_still_works` — unparseable → defaults to 5

---

### Task 1.4: Type comparison bug in 3 subsystems (#330)

**Problem:** `'>=' not supported between instances of 'str' and 'float'` in training check (70x), paper trade management (19x), and live trade check (19x).

**Files:** Find all unguarded numeric comparisons:
```bash
grep -rn ">=\|<=\|>\|<" src/training/ src/shadow_trading/executor.py --include="*.py" | grep -v "__pycache__" | grep -v "import\|#\|str\|len\|range\|enumerate"
```

**Fix:** Apply `safe_float()` from `src/utils/type_safety.py` at each comparison site. The pattern:
```python
# Before (broken):
if value >= threshold:

# After (safe):
from src.utils.type_safety import safe_float
if safe_float(value, 0.0) >= threshold:
```

Key sites to fix:
1. **Training pipeline:** `src/training/trainer.py` or `src/training/data_collector.py` — where `quality_score` or similar is compared to a threshold
2. **Paper trade management:** `src/shadow_trading/executor.py` — in the position monitoring loop where prices/quantities are compared
3. **Live trade check:** Same file, different code path for live positions

**Test:**
- `test_type_safety_in_training_threshold` — string "0.75" compared to float 0.5 doesn't crash
- `test_type_safety_in_position_check` — string "150.25" compared to float limit doesn't crash

---

### Task 1.5: Overnight training script broken (#335)

**Problem:** `scripts/overnight_train.py` imports `from src.scheduler.overnight import OvernightPipeline` but the module doesn't exist.

**Files:** `scripts/overnight_train.py`

**Fix:**
1. Check if `OvernightPipeline` was renamed or moved:
   ```bash
   grep -rn "OvernightPipeline\|class.*Pipeline" src/scheduler/ src/training/ --include="*.py"
   ```
2. If found elsewhere, update the import path
3. If the class was deleted, determine what the script should call instead (likely `src/training/trainer.py` functions directly)
4. Also fix the downstream type error in the trainer (covered by Task 1.4)

**Test:** `python scripts/overnight_train.py --help` should not crash with ImportError.

---

### Phase 1 Commit + Tag

```bash
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py
cd frontend && npm run build && cd ..

git add -A
git commit -m "fix: 5 critical production bugs — bracket guard, reconciliation, conviction, type safety, training

#326: Stop-price > 0 guard before all bracket order placements
#325: Fractional share tolerance in reconciliation (0.01 threshold)
#329: Additional conviction extraction patterns + parse rate logging
#330: safe_float() applied to training, paper trade, live trade comparisons
#335: Fix overnight training script import path

Closes #325, #326, #329, #330, #335"

git checkout main && git merge fix/production-sweep --no-ff
git tag -a v0.15.1 -m "v0.15.1 — 5 critical hotfixes: bracket guard, reconciliation, conviction parsing, type safety, training script"
git push origin main && git push origin v0.15.1

# Continue on the branch for Phase 2
git checkout fix/production-sweep
git merge main
```

---

## Phase 2: HIGH — Tag v0.15.2

**4 issues. Schema drift, sync errors, and code quality.**

### Task 2.1: Postgres schema drift — missing tables and column (#331)

**Problem:** 3 tables missing on Render, 1 column missing, generating 250+ errors/cycle.

**Files:** `src/schema/registry.py`, `src/sync/render_sync.py`

**Fix:**
1. Ensure `options_chains`, `google_trends`, `cboe_ratios` are in the schema registry with `sync_to_postgres=True`
2. Ensure `shadow_trades` includes `signal_price` column in the registry definition
3. Add a startup check that compares local schema to Render schema:
   ```python
   def validate_render_schema(pg_conn, local_tables):
       """Compare Render Postgres tables/columns against local registry."""
       for table_name, table_def in local_tables.items():
           if not table_def.sync_to_postgres:
               continue
           # Check table exists on Render
           # Check all columns exist
           # Log missing tables/columns as WARNINGS
   ```
4. The actual migration runs on next sync cycle — the sync pipeline creates tables that don't exist

**Fix for null PK issues** (`traffic_light_state`, `research_docs`):
In `src/sync/render_sync.py`, skip rows with NULL primary keys:
```python
# Before upsert, filter out rows with NULL PKs
rows = [r for r in rows if r.get(pk_column) is not None]
if skipped := len(original_rows) - len(rows):
    logger.warning("[SYNC] Skipped %d rows with NULL %s in %s", skipped, pk_column, table_name)
```

**Test:** `test_sync_skips_null_pks` — verify rows with NULL id are filtered, not sent to Postgres.

---

### Task 2.2: Postgres sync duplicate key errors (#332)

**Problem:** INSERT fails when row already exists. 185+ errors across 4 tables.

**Files:** `src/sync/render_sync.py`, `src/schema/sync_config.py`

**Fix:** Change sync mode for these tables to use ON CONFLICT UPDATE:
```python
# In the upsert function, ensure all synced tables use:
INSERT INTO {table} ({columns}) VALUES ({placeholders})
ON CONFLICT ({pk_column}) DO UPDATE SET {update_clause}
```

Check the existing `_upsert_to_postgres()` function — it may already support this but some tables might be using a different code path. Verify that `macro_snapshots`, `edgar_filings`, `options_metrics`, `vix_term_structure` all go through the upsert path.

**Test:** `test_sync_upsert_duplicate_no_error` — insert a row, then insert the same row again, verify no error.

---

### Task 2.3: DDL outside schema registry (#327)

**Problem:** Some scripts contain CREATE TABLE statements outside the centralized schema registry.

**Files:** Search for violations:
```bash
grep -rn "CREATE TABLE\|CREATE INDEX" scripts/ src/ --include="*.py" | grep -v registry.py | grep -v __pycache__ | grep -v test_
```

**Fix:** For each violation found:
1. Move the DDL to `src/schema/registry.py` as a proper `TableDef`
2. Replace the inline CREATE TABLE with a call to `ensure_table()` or rely on the startup schema validation
3. If it's a temporary/local table (e.g., for testing), mark it clearly with a comment

**Test:** Run the existing schema CI guardrail: `python -m pytest tests/test_schema.py -v`

---

### Task 2.4: Local API route regression (#328)

**Problem:** Some API routes are not working correctly in the local development environment.

**Files:** Read the issue for details, then:
```bash
# Start the server and test each route
python -m src.main serve &
sleep 3
curl -s http://localhost:8000/api/status | python -m json.tool | head -5
curl -s http://localhost:8000/api/shadow/open | python -m json.tool | head -5
curl -s http://localhost:8000/api/model-performance | python -m json.tool | head -5
curl -s http://localhost:8000/api/simulation/results | python -m json.tool | head -5
kill %1
```

**Fix:** Based on what's broken, fix the route handlers. Common issues:
- Import errors from refactored modules
- Missing cloud vs local route distinction
- New endpoints not registered in the router

---

### Phase 2 Commit + Tag

```bash
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py
cd frontend && npm run build && cd ..

git add -A
git commit -m "fix: 4 high-priority fixes — Postgres schema, sync upsert, DDL cleanup, API routes

#331: Missing tables + column added to schema registry, NULL PK guard in sync
#332: Upsert mode for macro_snapshots, edgar_filings, options_metrics, vix_term_structure
#327: DDL statements moved from scripts to schema registry
#328: Local API route regression fixed

Closes #327, #328, #331, #332"

git checkout main && git merge fix/production-sweep --no-ff
git tag -a v0.15.2 -m "v0.15.2 — 4 high-priority fixes: Postgres schema, sync, DDL, API routes"
git push origin main && git push origin v0.15.2

git checkout fix/production-sweep
git merge main
```

---

## Phase 3: MEDIUM — Tag v0.15.3

**5 issues. Infrastructure reliability and training quality.**

### Task 3.1: Render sync NULL primary keys (#302)

**Problem:** NULL PKs being synced to Render, causing insertion failures.

**Note:** Partially addressed by Task 2.1 (NULL PK guard). This task adds:
1. Root cause fix — find WHERE the NULL PKs originate in local SQLite
2. Add NOT NULL constraint to PK columns in schema registry where missing
3. Add a data quality check in the daily audit that flags NULL PKs

**Files:** `src/schema/registry.py` (add NOT NULL constraints), `src/evaluation/auditor.py` (add check)

---

### Task 3.2: Research source resilience (#303)

**Problem:** SSRN, OpenAI blog, Anthropic blog feeds fail and cause errors.

**Files:** `src/data_collection/research_sources.py` (or wherever research feeds are fetched)

**Fix:**
1. Wrap each source fetch in a try/except with graceful degradation
2. Cache last successful fetch — serve stale data on failure instead of erroring
3. Add per-source timeout (30s) and retry (1x with backoff)
4. Log source failures as WARNING, not ERROR (they're expected network issues)

**Test:** `test_research_source_failure_graceful` — mock a timeout, verify cache serves stale data.

---

### Task 3.3: VRAM handoff reliability (#304, #333)

**Problem:** Ollama doesn't release GPU memory when killed, preventing training.

**Files:** `src/scheduler/vram_manager.py` (or wherever VRAM handoff lives)

**Fix:**
1. After killing Ollama, wait 10 seconds then call `torch.cuda.empty_cache()`
2. Add 3 retry attempts with 15-second backoff between each
3. If all 3 retries fail, send Telegram alert and defer training to next cycle
4. Add a 30-minute scheduling buffer between inference cutoff and training start
5. Log VRAM state at each step: `nvidia-smi --query-gpu=memory.used --format=csv`

**Test:** Unit test is hard for VRAM — add an integration test flag that only runs on the local machine.

---

### Task 3.4: Training compliance gate rejection rate (#334)

**Problem:** 12.5% rejection from `markdown_bold` detection. XOM was rejected.

**Files:** `src/training/ingestion_gate.py`

**Fix:**
1. First, inspect the XOM example that triggered the gate:
   ```bash
   grep -A 5 "XOM.*rejected\|XOM.*markdown\|XOM.*halted" arcis.log | head -20
   ```
2. If false positive (inline bold emphasis, not structural markdown):
   - Further narrow the regex to only match line-leading `## Heading` patterns
   - Allow inline `**bold**` emphasis (common in financial writing)
3. If true positive (LLM actually outputting markdown headers):
   - Add anti-markdown instruction to the training generation prompt
   - Consider post-processing to strip markdown before ingestion

**Test:** `test_ingestion_allows_inline_bold` — verify `"The stock was **very** strong"` passes the gate.

---

### Task 3.5: Remaining sync cleanup (#302 completion)

Verify all sync tables have:
1. Valid PK columns with NOT NULL constraints
2. Upsert mode (not plain insert)
3. Correct sync_to_postgres flags
4. Run a full sync cycle and verify zero errors:
   ```bash
   python -c "from src.sync.render_sync import run_full_sync; run_full_sync()"
   ```

---

### Phase 3 Commit + Tag

```bash
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py
cd frontend && npm run build && cd ..

git add -A
git commit -m "fix: 5 medium-priority fixes — sync hygiene, research resilience, VRAM, training gate

#302: NULL PK root cause + NOT NULL constraints in schema registry
#303: Research source graceful degradation with caching + timeouts
#304/#333: VRAM handoff retry logic (3 attempts, 15s backoff, Telegram alert)
#334: Ingestion gate narrowed for inline bold emphasis

Closes #302, #303, #304, #333, #334"

git checkout main && git merge fix/production-sweep --no-ff
git tag -a v0.15.3 -m "v0.15.3 — 5 medium-priority fixes: sync, research, VRAM, training gate"
git push origin main && git push origin v0.15.3
```

---

## Phase 4: Documentation + Cleanup

```bash
# Delete the fix branch
git branch -d fix/production-sweep

# Update MASTER.md
# - Version: v0.15.3
# - Issues: 0 open (all closed)
# - Test count: update from verify_docs.py

# Update RELEASES.md with v0.15.1, v0.15.2, v0.15.3 entries
# Update CHANGELOG.md
# Update README.md badges (version, test count)

# Run verify_docs.py
python scripts/verify_docs.py

# Commit
git add MASTER.md RELEASES.md CHANGELOG.md README.md
git commit -m "docs: full documentation pass — v0.15.3, 0 open issues, all counts updated"
git push origin main
```

---

## Final Verification

```bash
# Zero open issues
# All tests pass
# Frontend builds
# verify_docs.py: all PASS
# arcis.log: run for 1 hour and verify error count is dramatically lower
```

---

## Summary

| Phase | Tag | Issues Closed | Focus |
|---|---|---|---|
| 1 | v0.15.1 | #325, #326, #329, #330, #335 | Trade safety + conviction + type safety |
| 2 | v0.15.2 | #327, #328, #331, #332 | Postgres schema + sync + API |
| 3 | v0.15.3 | #302, #303, #304, #333, #334 | Infrastructure reliability |
| 4 | — | — | Documentation sweep |

**Total: 14 issues → 0 open issues. 3 tags. Zero regressions.**

---

## Ralph Loop Verification

### Iteration 1 gaps found and fixed:
- Task 1.1 didn't specify ALL bracket order paths — added both paper and live entry functions
- Task 1.3 didn't include investigation step (read debug files first) — added
- Phase commits didn't include merge-back-to-branch step for continuation — added
- No mention of closing related duplicate (#333 is duplicate of #304) — added to Phase 3

### Iteration 2 gaps found and fixed:
- Task 2.1 NULL PK fix only filtered at sync time, didn't address root cause — added root cause investigation to Task 3.1
- Task 1.4 didn't specify HOW to find the comparison sites — added grep command
- No pre-flight step to record baseline test count — added
- Phase 2 didn't test API routes systematically — added curl verification commands

### Iteration 3 gaps found and fixed:
- Task 3.3 VRAM test is impractical in CI — noted as integration-test-only
- Task 3.4 didn't specify inspection step before fixing — added grep for XOM rejection
- Phase 4 didn't mention deleting the fix branch — added
- No final verification step to run the system and check error reduction — added 1-hour monitoring step
